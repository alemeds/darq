"""Pure transform logic for rebranding an extracted pegasus package tree into DARQ's own.

Everything here is a pure function over strings, paths and the parsed ``rebrand.json`` map: no
filesystem access, no network. The one function that touches a real directory on disk,
``apply_to_tree``, is a thin edge that only ever calls the pure functions below and never contains
transform logic of its own -- see that function's own docstring.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_PLACEHOLDER_TEMPLATE = "\x00DARQ_PROTECTED_{index}\x00"
"""A NUL-delimited marker, chosen because it can never occur in real markdown/text prose and
because it is trivially removable if a mask is ever left unrestored by a bug -- unlike a
human-readable placeholder, it can never be mistaken for real substituted content."""


@dataclass(frozen=True)
class RebrandMap:
    """The parsed, immutable contents of ``rebrand.json``.

    ``protected_tokens`` is stored pre-sorted longest-first: masking and unmasking both walk it in
    this order so a token that is itself a prefix of a longer one (``.pegasus-`` inside
    ``.pegasus-data``) is never masked in a way that clips the longer token out from under it.
    """

    renames: tuple[tuple[str, str], ...]
    substitutions: tuple[tuple[str, str], ...]
    protected_tokens: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    forbidden_fragments: tuple[str, ...] = ()
    substitution_extensions: tuple[str, ...] = (".md", ".txt")

    @property
    def rename_map(self) -> dict[str, str]:
        return dict(self.renames)


class RebrandIOError(RuntimeError):
    """A read, write, remove or rename that :func:`load_map` or :func:`apply_to_tree` needed
    failed at the filesystem. Always fatal, and always names the file and the OS reason -- never
    a bare traceback out of ``Path.read_text``/``write_text``/``unlink``/``replace``. See D13 in
    the README's "Deudas" table: this is the same "named refusal" shape `tools.build_darq
    .fetch_pinned_assets` already uses, applied here."""


def load_map(path: Path) -> RebrandMap:
    """Parse ``rebrand.json`` into a :class:`RebrandMap`. The only I/O in this function is the
    single read of ``path`` itself; everything else is pure construction."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RebrandIOError(f"could not read rebrand map {path}: {exc}") from exc
    payload = json.loads(raw)
    return parse_map(payload)


def parse_map(payload: dict) -> RebrandMap:
    renames = tuple((entry["from"], entry["to"]) for entry in payload["renames"])
    substitutions = tuple((pair[0], pair[1]) for pair in payload["substitutions"])
    protected = tuple(sorted(payload["protected_tokens"], key=len, reverse=True))
    excluded = tuple(payload.get("excluded_paths", ()))
    forbidden_fragments = tuple(payload.get("forbidden_fragments", ()))
    return RebrandMap(
        renames=renames,
        substitutions=substitutions,
        protected_tokens=protected,
        excluded_paths=excluded,
        forbidden_fragments=forbidden_fragments,
    )


def mask(text: str, protected_tokens: tuple[str, ...]) -> str:
    """Replace every occurrence of a protected token with an opaque, order-indexed placeholder.

    ``protected_tokens`` must already be sorted longest-first (``RebrandMap`` guarantees this on
    construction) -- masking a shorter token before a longer one that contains it would replace
    part of the longer token and leave the rest behind as literal, unmasked text.
    """
    for index, token in enumerate(protected_tokens):
        text = text.replace(token, _PLACEHOLDER_TEMPLATE.format(index=index))
    return text


def unmask(text: str, protected_tokens: tuple[str, ...]) -> str:
    """The inverse of :func:`mask`: restore every placeholder to its original protected token."""
    for index, token in enumerate(protected_tokens):
        text = text.replace(_PLACEHOLDER_TEMPLATE.format(index=index), token)
    return text


def substitute_body(text: str, rebrand_map: RebrandMap) -> str:
    """Apply every body substitution rule, in declared order, with protected tokens masked out
    for the duration.

    Order is correctness-critical and is never re-derived here: ``rebrand_map.substitutions`` is
    applied exactly in the order ``rebrand.json`` declares it, longest-match-first, so
    ``king-pegasus`` becomes ``arquitecto-darq`` as a whole before the later, bare ``pegasus`` rule
    ever sees it -- see ``tests/test_rebrand.py::test_king_pegasus_never_degrades``.
    """
    masked = mask(text, rebrand_map.protected_tokens)
    for old, new in rebrand_map.substitutions:
        masked = masked.replace(old, new)
    return unmask(masked, rebrand_map.protected_tokens)


class RebrandPathError(RuntimeError):
    """Raised at transform time when a resolved output path still carries one of the engine's
    brand fragments after both the explicit ``renames`` lookup and mechanical derivation have run.

    This is deliberately a hard failure during the transform itself, not something left to surface
    later as an install-time ``ContentError`` -- see :func:`rename_relative_path`.
    """


def _brand_fragments(rebrand_map: RebrandMap) -> tuple[str, ...]:
    """The brand fragments no resolved output path may still contain: the UNION of
    ``rebrand_map.forbidden_fragments`` and the left-hand side of every declared body-substitution
    rule -- never a second, hand-written list that could drift out of sync with ``rebrand.json``.

    These two sources answer two different questions, and the union exists precisely because
    neither one alone is enough:

    - ``substitutions`` answers HOW a leak, once found, is repaired -- its left-hand sides are
      rewrite-rule inputs. Any fragment that *is* a substitution key has, by construction, already
      been rewritten by :func:`substitute_body` before this check ever runs, so on the derivation
      path this half of the union can in practice never fire; it is kept anyway so an
      explicitly-renamed path (which skips derivation entirely) is still checked against it.
    - ``forbidden_fragments`` answers WHAT COUNTS AS a leak in the first place -- it can name a
      fragment with no corresponding rewrite rule at all (``"harness"`` is forbidden but nothing
      ever substitutes it), which is exactly the register the mirror needs to catch a fragment
      derivation alone would never have removed.
    """
    return tuple(rebrand_map.forbidden_fragments) + tuple(old for old, _ in rebrand_map.substitutions)


def rename_relative_path(relative_posix: str, rebrand_map: RebrandMap) -> str:
    """The path a file should be written to, relative to the content root.

    Resolution order:

    1. An explicit entry in ``rebrand.json``'s ``renames`` wins outright. This is reserved for
       deliberate, non-mechanical re-namings -- a path whose target isn't a textual substitution
       of its source (``agents/king-pegasus.md`` -> ``agents/arquitecto-darq.md`` is the persona's
       new name, not a string swap of ``pegasus``).
    2. Otherwise, the path is run through the same substitution map (and the same protected-token
       masking) already applied to file bodies by :func:`substitute_body`. A content filename that
       merely carries the brand -- ``agents/pegasus-general.md`` -- is renamed for free, the moment
       the engine ships it, with no ``rebrand.json`` entry required.
    3. Either way, the resolved path is checked against every declared brand fragment (masking
       protected tokens first, so a legitimate wire identifier in a path is never mistaken for a
       leak): see :func:`_brand_fragments`, which is the UNION of ``rebrand.json``'s
       ``forbidden_fragments`` (WHAT COUNTS AS a leak, independent of whether anything rewrites
       it -- e.g. ``"harness"``, which no substitution rule ever touches) and the left-hand side of
       every ``substitutions`` entry (HOW an already-found leak is repaired). If a fragment
       survives, that is a defect in step 1 or step 2 -- caught here, at transform time, via
       :class:`RebrandPathError`, rather than surfacing later as an opaque ``ContentError`` when
       the engine tries to ``load()`` a mismatched name/path pair.
    """
    explicit = rebrand_map.rename_map.get(relative_posix)
    resolved = explicit if explicit is not None else substitute_body(relative_posix, rebrand_map)

    masked_resolved = mask(resolved, rebrand_map.protected_tokens)
    leaked = [fragment for fragment in _brand_fragments(rebrand_map) if fragment in masked_resolved]
    if leaked:
        raise RebrandPathError(
            f"rebrand output path {resolved!r} (from {relative_posix!r}) still contains brand "
            f"fragment(s) {leaked!r} after rename resolution. Fix by adding an explicit semantic "
            f"rename for this path to rebrand.json's 'renames' list, or by extending "
            f"'substitutions' so mechanical derivation covers it."
        )
    return resolved


def is_excluded(relative_posix: str, rebrand_map: RebrandMap) -> bool:
    """Whether a path must never be read or rewritten by the transform, regardless of extension."""
    name = relative_posix.rsplit("/", 1)[-1]
    return relative_posix in rebrand_map.excluded_paths or name in rebrand_map.excluded_paths


def should_substitute_body(relative_posix: str, rebrand_map: RebrandMap) -> bool:
    """Whether a file's body is a candidate for substitution: right extension, not excluded.

    Deliberately extension-gated rather than content-sniffed: ``.json`` files (in particular
    ``content/mcp/playwright-package-lock.json``, which pins a real npm root package name the
    engine itself synthesized) are never substituted, by design -- see ``rebrand.json``'s
    ``accepted_residue`` entry.
    """
    if is_excluded(relative_posix, rebrand_map):
        return False
    return any(relative_posix.endswith(extension) for extension in rebrand_map.substitution_extensions)


def apply_to_tree(content_root: Path, rebrand_map: RebrandMap) -> None:
    """Apply the rebrand transform to every file under ``content_root``, in place.

    The only I/O in this module: walk every file once, decide (via the pure functions above)
    whether its body is substituted and whether its path is renamed, then write it back. Renames
    are resolved before any file is written, so a rename target that itself needs its body
    substituted still gets both -- new content at the new path, nothing left behind at the old one.
    """
    files = sorted(path for path in content_root.rglob("*") if path.is_file())
    for path in files:
        relative_posix = path.relative_to(content_root).as_posix()
        if is_excluded(relative_posix, rebrand_map):
            continue
        target_relative = rename_relative_path(relative_posix, rebrand_map)
        target_path = content_root / target_relative
        if should_substitute_body(relative_posix, rebrand_map):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise RebrandIOError(f"could not read {path} to rebrand it: {exc}") from exc
            new_text = substitute_body(text, rebrand_map)
            if target_path != path:
                try:
                    path.unlink()
                except OSError as exc:
                    raise RebrandIOError(
                        f"could not remove {path} after rebranding it to {target_path}: {exc}"
                    ) from exc
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(new_text, encoding="utf-8")
            except OSError as exc:
                raise RebrandIOError(
                    f"could not write rebranded content to {target_path}: {exc}"
                ) from exc
        elif target_path != path:
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                path.replace(target_path)
            except OSError as exc:
                raise RebrandIOError(f"could not rename {path} to {target_path}: {exc}") from exc
