"""Proves the no-fork guard actually catches a violation -- not just that it stays quiet on a
clean tree, which a guard that never checks anything would do too.

Every violation-planting test below runs against a scratch git repository under `/dev/shm`, never
against this repo's own working tree. `check(root=...)` and `repo_paths(root=...)` both take a
root, and `git ls-files` works against any repository, so the guard's real behaviour -- git-scoped
file discovery, gitignore honoring, every violation kind it detects -- can be exercised without
writing a single byte into the tree these tests themselves run from.

Two tests are the exception, on purpose, because they are about *this* repository specifically,
not about the guard's general behaviour: `test_the_real_darq_tree_is_clean` reads (never writes)
to assert the actual DARQ tree has no violation today, and
`test_build_directory_is_still_gitignored_in_the_real_tree` reads (never writes) to assert DARQ's
own `.gitignore` still exempts `build/`. That second one closes a gap the scratch-repo rewrite
below would otherwise leave: a scratch repo with its own synthetic `.gitignore` proves the guard
honors gitignore *in general*, but says nothing about whether *this* repository's `.gitignore`
still says what the guard's `build/` exemption assumes it says.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.check_no_engine_code import ROOT, check

#: Per the project's scratch-tree rule: every throwaway tree lives on tmpfs when it can, falling
#: back to the platform default only on a machine that has no `/dev/shm`.
_SCRATCH_PARENT = "/dev/shm" if Path("/dev/shm").is_dir() else None


def _make_scratch_repo() -> Path:
    """A throwaway git repository, empty but for a `.gitignore` that ignores `build/` -- the one
    piece of scope these tests need to control without touching the real repo's own file.
    """
    root = Path(tempfile.mkdtemp(prefix="darq-guard-scratch-", dir=_SCRATCH_PARENT))
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root, check=True, capture_output=True, text=True,
    )
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    return root


class CheckNoEngineCodeTests(unittest.TestCase):
    def test_the_real_darq_tree_is_clean(self) -> None:
        self.assertEqual(check(), [])

    def test_build_directory_is_still_gitignored_in_the_real_tree(self) -> None:
        """The half `test_the_guard_takes_its_scope_from_gitignore_not_from_its_own_list` (below)
        cannot cover once it runs against a scratch repo: that *this* repository's own
        `.gitignore` still exempts `build/`. This test reads only -- `git check-ignore` -- and
        writes nothing to the real tree.
        """
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "--quiet", "build/guard-scope-probe.py"],
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            "build/ is no longer ignored by the real .gitignore; the scratch-repo version of "
            "test_the_guard_takes_its_scope_from_gitignore_not_from_its_own_list no longer "
            "proves anything about this repo's own exemption for build/"
        )

    def test_guard_catches_an_engine_layer_directory_violation(self) -> None:
        repo = _make_scratch_repo()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)

        violation_dir = repo / "core"
        violation_dir.mkdir()
        (violation_dir / "content.py").write_text("# copied engine module\n", encoding="utf-8")

        violations = check(root=repo)
        self.assertTrue(violations, "the guard must fail once a core/ directory exists")
        self.assertTrue(any("core" in message for message in violations))

    def test_guard_catches_a_copied_engine_content_artifact(self) -> None:
        repo = _make_scratch_repo()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)

        content_dir = repo / "content"
        content_dir.mkdir()
        (content_dir / "king-pegasus.md").write_text(
            "---\nname: king-pegasus\n---\ncopied content\n", encoding="utf-8"
        )

        violations = check(root=repo)
        self.assertTrue(violations)
        self.assertTrue(any("king-pegasus.md" in message for message in violations))

    def test_guard_catches_a_python_file_that_imports_the_engine(self) -> None:
        """The check that closes the other two's blind spot: a single engine module copied to the
        repo root, named nothing in particular, sitting in no engine-shaped directory.
        """
        repo = _make_scratch_repo()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)

        (repo / "helper.py").write_text("from pegasus.core import content\n", encoding="utf-8")

        violations = check(root=repo)
        self.assertTrue(violations, "the guard must fail on a Python file importing the engine")
        self.assertTrue(any("helper.py" in message for message in violations))

    def test_the_guard_takes_its_scope_from_gitignore_not_from_its_own_list(self) -> None:
        """Proves the guard's scope comes from `.gitignore` *in general* -- not that DARQ's own
        `.gitignore` still ignores `build/` *today*; see
        `test_build_directory_is_still_gitignored_in_the_real_tree` above for that half.

        A hardcoded list of directory names to skip would be a second source of truth, free to
        disagree with `.gitignore`: the day a directory stopped being ignored, the guard would keep
        skipping it and report PASS with engine code committed inside. Asserting the same violation
        is exempt under an ignored path and caught outside it is what pins the scope to git.
        """
        repo = _make_scratch_repo()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)

        body = "from pegasus.core import content\n"
        ignored = repo / "build" / "guard-scope-probe"
        ignored.mkdir(parents=True)
        (ignored / "leak.py").write_text(body, encoding="utf-8")

        self.assertEqual(
            check(root=repo), [], "a violation under an ignored path must not trip the guard"
        )

        (repo / "guard-scope-probe.py").write_text(body, encoding="utf-8")

        self.assertTrue(
            check(root=repo), "the identical file outside an ignored path must trip it"
        )


if __name__ == "__main__":
    unittest.main()
