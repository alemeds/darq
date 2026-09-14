#!/usr/bin/env python3
"""Build the `darq` distribution artifact from a pinned, published pegasus release.

DARQ contains zero engine code and zero copies of engine content. Every build starts from the
`pegasus` binary, `build_zipapp.py`, `build_installer.py` and the `install.sh` template published
at the exact tag pinned in `engine.pin`, verifies all four against the sha256 pinned there (the
trust boundary: any mismatch is a hard refusal, never a warning), rebrands the extracted content
tree in place with `rebrand/transform.py`, overlays this repo's own `content/` on top, and finally
reuses the downloaded `build_zipapp.py` and `build_installer.py` -- never a local copy of the
engine's -- to produce `dist/darq` and `dist/install.sh`.

    python3 tools/build_darq.py
    python3 tools/build_darq.py --offline   # reuse whatever is already in the cache dir

I/O (downloading, extracting, writing) is kept in this module; `rebrand.transform` and this
module's own pure helpers below hold no I/O of their own beyond what is unavoidable to drive them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rebrand.transform import RebrandMap, _brand_fragments, apply_to_tree, mask, parse_map  # noqa: E402

ENGINE_PIN = ROOT / "engine.pin"
REBRAND_JSON = ROOT / "rebrand.json"
IDENTITY_JSON = ROOT / "identity.json"
CONTENT_OVERLAY = ROOT / "content"
DEFAULT_CACHE_DIR = ROOT / "build" / "cache"
DEFAULT_WORK_DIR = ROOT / "build" / "work"
def raw_content_dir_for(work_dir: Path) -> Path:
    """Where the engine's content tree is persisted *before* `rebrand.transform.apply_to_tree`
    rewrites it in place, for a given `work_dir`. Always a sibling of `<work_dir>/extracted`, so
    two builds run with different `--work-dir` values never collide on the same raw copy location.

    This is verification input only -- it sits outside `<work_dir>/extracted/pegasus`, the tree
    that `run_build_zipapp`/`run_build_installer` package, so it never reaches `dist/`. See
    `tests/test_build_darq.py::RawContentCopyTests` for the checks that it stays out of what gets
    packaged and that it derives from `work_dir` rather than a fixed path.
    """
    return work_dir / "extracted-raw" / "content"


#: `raw_content_dir_for`'s value for `DEFAULT_WORK_DIR`, kept as today's default so passing no
#: `--work-dir` changes nothing.
DEFAULT_RAW_CONTENT_DIR = raw_content_dir_for(DEFAULT_WORK_DIR)
DEFAULT_OUT = ROOT / "dist" / "darq"
DEFAULT_INSTALLER_OUT = ROOT / "dist" / "install.sh"

#: Every asset `engine.pin` pins and this build downloads (or reuses, under `--offline`) and
#: verifies unconditionally. Order is insignificant -- `fetch_pinned_assets` verifies all of them
#: before any is used -- but is kept stable here for readable build logs.
PINNED_ASSETS = ("pegasus", "build_zipapp.py", "build_installer.py", "install.sh")


class BuildError(RuntimeError):
    """The build cannot proceed. Always fatal -- there is no partial or best-effort build."""


def load_pin(path: Path = ENGINE_PIN) -> dict:
    """Load and parse `engine.pin`. A `BuildError` names `path` and the reason on either of its
    two ways to fail -- unreadable (permissions, missing) or present but not valid JSON -- never a
    bare traceback. See D13 in the README's "Deudas" table."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"could not read {path} to load the engine pin: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BuildError(f"{path} is not valid JSON ({exc}); fix its syntax and retry") from exc


def asset_url(pin: dict, asset_name: str) -> str:
    tag = pin["tag"]
    template = pin["assets"][asset_name]["url_template"]
    return template.format(tag=tag)


def expected_sha256(pin: dict, asset_name: str) -> str:
    return pin["assets"][asset_name]["sha256"]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, destination.open("wb") as handle:  # noqa: S310
        shutil.copyfileobj(response, handle)


def fetch_pinned_assets(pin: dict, cache_dir: Path, *, offline: bool) -> dict[str, Path]:
    """Download (or reuse, when `offline`) every asset in `PINNED_ASSETS` into `cache_dir`, then
    verify all of them against `engine.pin` unconditionally -- verification is never skipped, even
    when the download itself was.

    `offline` means what its own `--help` text promises: reuse whatever is already cached, never
    touch the network. If an asset is not present at `cache_dir / asset_name`, this is a hard
    refusal naming the missing asset and where it was expected -- never a silent fall-back to
    downloading it. See `tests/test_fetch_pinned_assets.py::test_offline_with_a_missing_cached_
    asset_is_a_hard_refusal_naming_it` for the behaviour this fixes: before this, `offline and
    destination.is_file()` was the only gate, so a cache miss fell straight into the `else`
    branch and quietly reached the network regardless of `offline`.

    There are exactly three ways a pinned asset can turn out to be unusable, and all three are
    named `BuildError`s -- never a raw traceback: not cached (above), sha256 mismatch (below), and
    -- cached (or freshly downloaded) but unreadable, e.g. broken permissions -- also below, where
    `sha256_of` opens it. That last one applies in both modes: a file just downloaded can be just
    as unreadable as one reused from a stale cache.
    """
    paths: dict[str, Path] = {}
    for asset_name in PINNED_ASSETS:
        destination = cache_dir / asset_name
        if offline:
            if not destination.is_file():
                raise BuildError(
                    f"--offline refused: {asset_name} is not cached at {destination}. "
                    f"Populate the cache first by running `python3 tools/build_darq.py` "
                    f"(without --offline) once, then retry with --offline."
                )
            print(f"OFFLINE: reusing cached {asset_name} at {destination}")
        else:
            url = asset_url(pin, asset_name)
            print(f"FETCH: {asset_name} <- {url}")
            download(url, destination)
        paths[asset_name] = destination

    for asset_name, path in paths.items():
        if not path.is_file():
            raise BuildError(
                f"{asset_name} is not present at {path}; run without --offline to download it"
            )
        try:
            actual = sha256_of(path)
        except OSError as exc:
            raise BuildError(
                f"REFUSED: {asset_name} at {path} could not be read to verify its sha256 -- {exc}. "
                f"This is the third way an asset can be unusable (after: not cached, hash "
                f"mismatch) -- fix its permissions (or whatever the OS error above names) and "
                f"retry."
            ) from exc
        expected = expected_sha256(pin, asset_name)
        if actual != expected:
            raise BuildError(
                f"REFUSED: {asset_name} sha256 mismatch -- expected {expected}, got {actual}. "
                f"This is the trust boundary between DARQ and the pinned pegasus release; a "
                f"mismatch is never a warning."
            )
        print(f"VERIFIED: {asset_name} sha256 {actual} matches engine.pin")
    return paths


def extract_pegasus_package(pegasus_binary: Path, work_dir: Path) -> Path:
    """Extract the published `pegasus` zipapp and return `<work_dir>/extracted/pegasus`."""
    extracted = work_dir / "extracted"
    if extracted.exists():
        shutil.rmtree(extracted)
    if not zipfile.is_zipfile(pegasus_binary):
        raise BuildError(f"{pegasus_binary} is not a valid zipapp (zipfile.is_zipfile() is False)")
    try:
        with zipfile.ZipFile(pegasus_binary) as archive:
            archive.extractall(extracted)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BuildError(
            f"could not extract {pegasus_binary} into {extracted}: {exc}"
        ) from exc
    package = extracted / "pegasus"
    if not (package / "__main__.py").is_file():
        raise BuildError(f"{package} has no __main__.py; extraction did not produce the expected layout")
    return package


def persist_raw_content_copy(content_root: Path, raw_content_dir: Path) -> None:
    """Copy `content_root` (the freshly extracted, not-yet-rebranded `pegasus/content` tree) to
    `raw_content_dir` before `apply_to_tree` rewrites `content_root` in place.

    This is the only copy of the engine's raw content DARQ ever persists, and it exists solely so
    `tests/test_rebrand.py` can assert what the transform actually *derives* from real engine
    content, rather than asserting idempotence against content the previous build already
    rewrote. It is never read by the build itself again and must never be packaged -- see
    `DEFAULT_RAW_CONTENT_DIR`'s docstring for how that is kept true.
    """
    if raw_content_dir.exists():
        shutil.rmtree(raw_content_dir)
    raw_content_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(content_root, raw_content_dir)
    except OSError as exc:
        # `shutil.Error` (raised when `copytree` hits per-file failures, e.g. an unreadable
        # source file) is itself a subclass of `OSError`, so this one clause already covers both.
        raise BuildError(
            f"could not copy raw content from {content_root} to {raw_content_dir}: {exc}"
        ) from exc


class OverlayCollisionError(RuntimeError):
    """A content-overlay file would overwrite a path the rebranded engine tree already provides --
    either the overlay file's own leaf path, or one of the directories it needs along the way.

    Always fatal: DARQ's own content is only ever added on top of the engine's tree, never
    replacing it. There is deliberately no declarable exception mechanism for this (no
    `accepted_residue`-style allowlist) -- see `overlay_content`'s docstring for why.
    """


class OverlayBrandLeakError(RuntimeError):
    """A content-overlay file's path or body still carries an engine brand fragment.

    Always fatal: unlike `rebrand.transform.rename_relative_path`/`substitute_body`, which REWRITE
    a leak found in the engine's own inherited tree, DARQ's own `content/` is never rewritten --
    it is rejected outright, because a leak in content DARQ itself authored is a defect in that
    content, not something the rebrand mirror should paper over.
    """


def _overlay_brand_leaks(text: str, rebrand_map: RebrandMap) -> list[str]:
    """The brand fragments (see `rebrand.transform._brand_fragments`) that survive in `text`
    after protected tokens are masked out -- empty if `text` is clean.

    Reuses the same detection machinery `rename_relative_path` uses to reject an engine path that
    still carries the brand after rewriting, but here purely to DETECT and never to rewrite:
    overlay content is DARQ's own, so a leak in it is rejected outright rather than repaired.
    """
    masked = mask(text, rebrand_map.protected_tokens)
    return [fragment for fragment in _brand_fragments(rebrand_map) if fragment in masked]


def overlay_content(package: Path, overlay_root: Path, rebrand_map: RebrandMap) -> None:
    """Copy every file from `overlay_root` into `<package>/content`, adding to the inherited tree
    the rebrand transform already rewrote -- never replacing any of it.

    Two hard failures, both unconditional:

    - `OverlayCollisionError`: an overlay file's relative path already exists in the rebranded
      engine tree, or one of that path's intermediate directories exists there as a *file*
      instead (an overlay file needing `skills/x/y.md` when the engine tree already has a plain
      file at `skills/x` is caught the same way, before `Path.mkdir` would otherwise fail with a
      bare, path-less `FileExistsError`). Deliberately has no declarable exception (no
      `accepted_residue`-style allowlist for a permitted collision): none of DARQ's content today
      collides with the engine's ~90 content paths (verified directly, see
      `tests/test_overlay_content.py`), so adding one now would be an empty, inert permission
      list -- exactly the kind of debt this repo has already removed elsewhere once found: both
      `rebrand.json`'s now-deleted `PEGASUS_INSTALL_BASE_URL` protected-token entry (it could never
      match anything DARQ's own installer produces) and its former `renames` list (both entries
      were exactly reproducible by mechanical derivation) were cut for the same reason -- an inert
      allowlist entry teaches whoever reads it to stop trusting the list. The day a real collision
      is needed, this failure is what stops it in front of whoever introduces it, and that is when
      the exception mechanism gets designed, against a real case.
    - `OverlayBrandLeakError`: an overlay file's path or body still carries an engine brand
      fragment (via `_overlay_brand_leaks`, reusing `rebrand.transform`'s own fragment detection).
      DARQ's own content must never carry the engine's brand; `protected_tokens` remain a valid
      exception (a stable wire identifier is not a leak).

    `OVERLAY:` in the printed log names a file added fresh; a collision is never silently logged
    that way -- it always raises, naming the path, instead.
    """
    if not overlay_root.is_dir():
        return
    destination_root = package / "content"
    for source_path in sorted(p for p in overlay_root.rglob("*") if p.is_file()):
        relative = source_path.relative_to(overlay_root)
        relative_posix = relative.as_posix()

        path_leaks = _overlay_brand_leaks(relative_posix, rebrand_map)
        if path_leaks:
            raise OverlayBrandLeakError(
                f"content overlay file path {relative_posix!r} still carries engine brand "
                f"fragment(s) {path_leaks!r}; DARQ's own content must never carry the engine's "
                f"brand in a file name -- rename the file instead of overlaying it as is."
            )
        try:
            body = source_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            body = None
        if body is not None:
            body_leaks = _overlay_brand_leaks(body, rebrand_map)
            if body_leaks:
                raise OverlayBrandLeakError(
                    f"content overlay file {relative_posix!r} body still carries engine brand "
                    f"fragment(s) {body_leaks!r}; DARQ's own content must never carry the "
                    f"engine's brand -- fix the file's own text instead of overlaying it as is."
                )

        destination_path = destination_root / relative
        if destination_path.exists():
            raise OverlayCollisionError(
                f"OVERLAY-COLLISION: {relative_posix} would overwrite {destination_path}, which "
                f"the rebranded engine tree already provides at this path. DARQ's content/ only "
                f"ever adds to the engine's tree, never replaces it -- this path is frozen "
                f"against future upstream engine changes until a real collision is designed for; "
                f"see OverlayCollisionError's docstring."
            )
        # The check above only sees a collision once the destination *leaf* exists. If the
        # engine tree instead has a *file* sitting at one of the destination's intermediate
        # directories, the leaf doesn't exist yet, so that check never fires -- and without this
        # loop the collision would surface later as a raw `FileExistsError` out of `Path.mkdir`,
        # naming nothing and explaining nothing. Walk every intermediate component, top-down, so
        # it is reported the same way as a leaf collision.
        intermediate_ancestors = []
        ancestor = destination_path.parent
        while ancestor != destination_root:
            intermediate_ancestors.append(ancestor)
            ancestor = ancestor.parent
        for ancestor_path in reversed(intermediate_ancestors):
            if ancestor_path.exists() and not ancestor_path.is_dir():
                ancestor_relative = ancestor_path.relative_to(destination_root).as_posix()
                raise OverlayCollisionError(
                    f"OVERLAY-COLLISION: {relative_posix} needs {ancestor_relative!r} as a "
                    f"directory, but the rebranded engine tree already provides "
                    f"{ancestor_relative!r} as a file at {ancestor_path}. DARQ's content/ only "
                    f"ever adds to the engine's tree, never replaces it -- this path is frozen "
                    f"against future upstream engine changes until a real collision is designed "
                    f"for; see OverlayCollisionError's docstring."
                )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        print(f"OVERLAY: {relative_posix}")


def run_build_zipapp(build_zipapp_py: Path, source: Path, identity: Path, out: Path) -> None:
    if out.exists():
        out.unlink()
    result = subprocess.run(
        [sys.executable, str(build_zipapp_py), "--source", str(source), "--identity", str(identity), "--out", str(out)],
        capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise BuildError(f"build_zipapp.py failed with exit code {result.returncode}")


def format_checksum_sidecar(sha256_digest: str, filename: str) -> str:
    """The exact `.sha256` sidecar format `build_zipapp.py` already writes for `dist/darq`
    (`"<digest>  <filename>\\n"`), reused here so `dist/install.sh.sha256` matches it byte for byte
    rather than inventing a second, subtly different checksum format for the same repo.
    """
    return f"{sha256_digest}  {filename}\n"


def write_checksum_sidecar(out: Path, sha256_digest: str, filename: str) -> Path:
    """Write `<out>.sha256` in `format_checksum_sidecar`'s format and return its path. A
    `BuildError` names the sidecar path and the reason on failure -- e.g. a broken permission or a
    full disk -- instead of a bare traceback. See D13."""
    checksum_path = out.with_name(out.name + ".sha256")
    try:
        checksum_path.write_text(format_checksum_sidecar(sha256_digest, filename), encoding="utf-8")
    except OSError as exc:
        raise BuildError(
            f"could not write checksum sidecar {checksum_path} for {filename}: {exc}"
        ) from exc
    return checksum_path


def read_checksum_sidecar(path: Path, *, artifact_name: str) -> str:
    """Read and strip a `.sha256` sidecar `path`, for logging. A `BuildError` names `path`, the
    artifact it documents (`artifact_name`) and the reason on failure -- e.g. missing or
    unreadable -- instead of a bare traceback. See D13."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BuildError(
            f"could not read {artifact_name}'s checksum sidecar at {path}: {exc}"
        ) from exc


def run_build_installer(
    build_installer_py: Path, template: Path, package_source: Path, identity: Path, out: Path
) -> None:
    """Generate `dist/install.sh` by invoking the engine's own `build_installer.py` -- never a
    local reimplementation of its templating -- against the downloaded, verified `install.sh`
    template, DARQ's own `identity.json`, and the extracted `pegasus` package tree (used only to
    validate the identity, per `build_installer.py --package-source`).
    """
    if out.exists():
        out.unlink()
    result = subprocess.run(
        [
            sys.executable, str(build_installer_py),
            "--template", str(template),
            "--package-source", str(package_source),
            "--identity", str(identity),
            "--out", str(out),
        ],
        capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise BuildError(f"build_installer.py failed with exit code {result.returncode}")
    if not out.is_file():
        raise BuildError(f"build_installer.py exited 0 but did not write {out}")

    checksum_path = write_checksum_sidecar(out, sha256_of(out), out.name)
    print(f"WROTE checksum: {checksum_path}")


def load_rebrand_map(path: Path = REBRAND_JSON) -> RebrandMap:
    """Load and parse `rebrand.json` into a `RebrandMap`. A `BuildError` names `path` and the
    reason on either of its two ways to fail -- unreadable or present but not valid JSON -- the
    same shape `load_pin` uses for `engine.pin`. See D13."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"could not read {path} to load the rebrand map: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BuildError(f"{path} is not valid JSON ({exc}); fix its syntax and retry") from exc
    return parse_map(payload)


def build(
    *,
    offline: bool,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    work_dir: Path = DEFAULT_WORK_DIR,
    out: Path = DEFAULT_OUT,
    installer_out: Path = DEFAULT_INSTALLER_OUT,
    raw_content_dir: Path | None = None,
) -> Path:
    """`raw_content_dir` defaults to `raw_content_dir_for(work_dir)` -- a sibling of
    `work_dir/extracted` -- rather than to a fixed path, so a custom `work_dir` never collides
    with another build's raw content copy. Pass it explicitly only to override that derivation."""
    pin = load_pin()
    print(f"PIN: pegasus-harness tag {pin['tag']}")

    if raw_content_dir is None:
        raw_content_dir = raw_content_dir_for(work_dir)

    assets = fetch_pinned_assets(pin, cache_dir, offline=offline)

    work_dir.mkdir(parents=True, exist_ok=True)
    package = extract_pegasus_package(assets["pegasus"], work_dir)
    print(f"EXTRACTED: {package}")

    persist_raw_content_copy(package / "content", raw_content_dir)
    print(f"PERSISTED: raw (unrebranded) content copy at {raw_content_dir}")

    rebrand_map = load_rebrand_map()
    apply_to_tree(package / "content", rebrand_map)
    print("REBRANDED: content tree rewritten in place")

    overlay_content(package, CONTENT_OVERLAY, rebrand_map)

    out.parent.mkdir(parents=True, exist_ok=True)
    run_build_zipapp(assets["build_zipapp.py"], package, IDENTITY_JSON, out)

    checksum_path = out.with_name(out.name + ".sha256")
    if not checksum_path.is_file():
        raise BuildError(f"build_zipapp.py did not write {checksum_path}")
    print(f"BUILT: {out}")
    print(f"CHECKSUM: {read_checksum_sidecar(checksum_path, artifact_name=out.name)}")

    installer_out.parent.mkdir(parents=True, exist_ok=True)
    run_build_installer(assets["build_installer.py"], assets["install.sh"], package, IDENTITY_JSON, installer_out)
    installer_checksum_path = installer_out.with_name(installer_out.name + ".sha256")
    print(f"BUILT: {installer_out}")
    print(
        f"CHECKSUM: "
        f"{read_checksum_sidecar(installer_checksum_path, artifact_name=installer_out.name)}"
    )

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="reuse cached assets instead of downloading; verification still runs unconditionally")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--installer-out", type=Path, default=DEFAULT_INSTALLER_OUT)
    arguments = parser.parse_args()
    try:
        build(
            offline=arguments.offline,
            cache_dir=arguments.cache_dir,
            work_dir=arguments.work_dir,
            out=arguments.out,
            installer_out=arguments.installer_out,
        )
    except BuildError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
