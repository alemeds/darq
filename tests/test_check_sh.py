"""Tests for `tools/check.sh`'s own logic: argument parsing (`--offline`, `--no-build`, unknown
argument exits 2) and step sequencing (which banners print, which steps get skipped, what the
exit code is). Exercised by actually running the script and reading its output and exit code --
there is no other way to test bash argument parsing or a bash script's own control flow.

Sequencing used to be tested by two tests that shelled out to the real `check.sh` against this
real repository, and skipped unless `dist/darq` and `build/cache/` already existed -- both
`.gitignore`d, so on a fresh clone neither exists and those two tests proved nothing while the
run still printed OK. `tools/check.sh` now accepts a `DARQ_CHECK_ROOT` override (see its own
docstring) precisely so this can be hermetic: `CheckShRootOverrideSequencingTests` below builds a
throwaway tree in `/dev/shm` with stub `build_darq.py` / `verify_darq.py` / `check_no_engine_code.py`
and a trivial `tests/`, points the real `check.sh` at it, and asserts sequencing. This never
needs a build, a network, or a populated `build/cache/`, and it now also covers what nothing
covered before: what happens when a step fails.

What this buys, and what it does not: these tests prove `check.sh` sequences its steps correctly
and reports the right exit code for each of them. They do NOT prove the real `build_darq.py` /
`verify_darq.py` / `check_no_engine_code.py` chain actually works end to end -- that stays a
manual `tools/check.sh` run against this real repository. A green run of this file is not
evidence that a release build up-to-date.

Recursion guard: `tools/check.sh`'s own "unit tests" step runs `python3 -m unittest discover -s
tests`, which picks up this very file. A test here that shells out to `check.sh` would otherwise
launch check.sh -> discover -> this file -> check.sh -> ... forever. `DARQ_CHECK_SH_TEST_NESTED`
breaks that: any test that invokes `check.sh` sets it in the child's environment, and every test in
this file skips immediately if it is already set in its own environment -- so a real invocation
runs check.sh exactly once, one level deep.

`DARQ_CHECK_ROOT` does not change this: the guard is keyed on "does this process invoke check.sh
at all", not on which root check.sh operates on, so a root-overridden invocation is still exactly
one level of nesting, and its own "unit tests" step runs `unittest discover` against the *scratch*
tree's own `tests/` directory (a different filesystem path from this one entirely), never against
this file. The two guards -- `DARQ_CHECK_SH_TEST_NESTED` and `DARQ_CHECK_ROOT` -- are independent
and do not need to interact: nesting depth is about which process is running, root override is
about which tree it inspects.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
CHECK_SH = ROOT / "tools" / "check.sh"
_NESTED_GUARD = "DARQ_CHECK_SH_TEST_NESTED"

#: Per the project's scratch-tree rule: every throwaway tree lives on tmpfs when it can, falling
#: back to the platform default only on a machine that has no `/dev/shm`.
_SCRATCH_PARENT = "/dev/shm" if Path("/dev/shm").is_dir() else None


def _run_check_sh(*args: str, root: Path | None = None, **extra_env: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[_NESTED_GUARD] = "1"
    if root is not None:
        env["DARQ_CHECK_ROOT"] = str(root)
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(CHECK_SH), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _write_stub(path: Path, banner: str, exit_env_var: str) -> None:
    """A stub step script: prints its banner (and, if invoked with `--offline`, an
    `OFFLINE: reusing cached` line mirroring what the real `build_darq.py` prints), then exits
    with the code named by `exit_env_var` (default 0) -- so a test can make any one step fail
    without touching the other two.
    """
    path.write_text(
        textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import os
            import sys
            print("{banner}")
            if "--offline" in sys.argv:
                print("OFFLINE: reusing cached stub assets")
            sys.exit(int(os.environ.get("{exit_env_var}", "0")))
            """),
        encoding="utf-8",
    )


def _make_stub_root() -> Path:
    """A throwaway tree in `/dev/shm` shaped like DARQ's own root, but with stub `tools/` scripts
    standing in for `build_darq.py`, `verify_darq.py` and `check_no_engine_code.py`, and a
    trivial `tests/` directory -- so `tools/check.sh`, pointed here via `DARQ_CHECK_ROOT`, can run
    its full sequence without a real build, a network, or a populated `build/cache/`.
    """
    root = Path(mkdtemp(prefix="darq-check-sh-scratch-", dir=_SCRATCH_PARENT))
    tools_dir = root / "tools"
    tools_dir.mkdir()
    tests_dir = root / "tests"
    tests_dir.mkdir()

    _write_stub(tools_dir / "check_no_engine_code.py", "check_no_engine_code stub: PASS", "DARQ_STUB_GUARD_EXIT")
    _write_stub(tools_dir / "build_darq.py", "build_darq stub: running", "DARQ_STUB_BUILD_EXIT")
    _write_stub(tools_dir / "verify_darq.py", "verify_darq stub: PASS", "DARQ_STUB_VERIFY_EXIT")

    (tests_dir / "test_stub.py").write_text(
        textwrap.dedent("""\
            import unittest

            class StubTests(unittest.TestCase):
                def test_trivial(self) -> None:
                    self.assertTrue(True)
            """),
        encoding="utf-8",
    )
    return root


@unittest.skipIf(os.environ.get(_NESTED_GUARD), "nested invocation from check.sh itself; see module docstring")
class CheckShArgumentParsingTests(unittest.TestCase):
    def test_an_unknown_argument_exits_2_without_running_anything_else(self) -> None:
        result = _run_check_sh("--not-a-real-flag")

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument: --not-a-real-flag", result.stderr)
        # It exits before the "== unit tests ==" banner ever prints.
        self.assertNotIn("unit tests", result.stdout)


@unittest.skipIf(os.environ.get(_NESTED_GUARD), "nested invocation from check.sh itself; see module docstring")
class CheckShRootOverrideSequencingTests(unittest.TestCase):
    """Hermetic replacements for the two tests that used to skip on a fresh clone. Each test
    builds its own scratch tree, fresh, in `/dev/shm` -- nothing here depends on `dist/darq` or
    `build/cache/` existing, and none of it writes into this real repository.
    """

    def setUp(self) -> None:
        self.scratch_root = _make_stub_root()
        self.addCleanup(self._cleanup_scratch_root)

    def _cleanup_scratch_root(self) -> None:
        import shutil
        shutil.rmtree(self.scratch_root, ignore_errors=True)

    def test_root_override_is_announced_prominently(self) -> None:
        result = _run_check_sh("--no-build", root=self.scratch_root)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("DARQ_CHECK_ROOT override is in effect", result.stdout)
        self.assertIn("This is NOT the real DARQ repository.", result.stdout)
        # Announced both before the steps run and again right before the final verdict, so it
        # cannot scroll off unnoticed either at the top or at the bottom of a long run.
        self.assertEqual(result.stdout.count("DARQ_CHECK_ROOT override is in effect"), 2)

        # Position, asserted against the two landmarks it actually has to sit between: after the
        # last step, and before the verdict. That window is the only place a reader who scrolled
        # straight to the result cannot miss which tree produced it.
        #
        # The first version of this assertion compared the banner's position against
        # `find("All checks passed.") - len(stdout)`, which is *always negative* -- `find` returns
        # an index smaller than the length whenever it matches at all. So it read `437 > -19`: a
        # tautology that any banner position satisfies, including both banners printed at the top
        # with nothing near the verdict. It was checking a number, not the property the comment
        # above claims. Reproduced, then replaced.
        closing = result.stdout.rfind("DARQ_CHECK_ROOT override is in effect")
        last_step = result.stdout.find("== verify_darq.py ==")
        verdict = result.stdout.find("All checks passed.")
        self.assertNotEqual(-1, last_step, "no step banner found, so position proves nothing")
        self.assertNotEqual(-1, verdict, "no verdict found, so position proves nothing")
        self.assertLess(
            last_step, closing,
            "the closing announcement must come after the last step, not with the opening one",
        )
        self.assertLess(
            closing, verdict,
            "the closing announcement must come immediately before the verdict it qualifies",
        )

    def test_no_build_skips_the_build_step_and_still_runs_verify(self) -> None:
        result = _run_check_sh("--offline", "--no-build", root=self.scratch_root)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("== unit tests ==", result.stdout)
        self.assertIn("== check_no_engine_code.py ==", result.stdout)
        self.assertNotIn("== build_darq.py ==", result.stdout)
        self.assertIn("== verify_darq.py ==", result.stdout)
        self.assertIn("All checks passed.", result.stdout)

    def test_offline_alone_runs_the_build_step_too(self) -> None:
        result = _run_check_sh("--offline", root=self.scratch_root)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("== build_darq.py ==", result.stdout)
        self.assertIn("OFFLINE: reusing cached", result.stdout)
        self.assertIn("All checks passed.", result.stdout)

    def test_a_failing_step_aborts_with_nonzero_exit_and_no_pass_banner(self) -> None:
        # Nothing exercised this before: what happens when a step actually fails. `set -euo
        # pipefail` in check.sh means the first non-zero step aborts the whole script immediately.
        result = _run_check_sh(
            "--no-build", root=self.scratch_root, DARQ_STUB_VERIFY_EXIT="1",
        )

        self.assertNotEqual(result.returncode, 0)
        # The steps before the failing one still ran and printed...
        self.assertIn("== check_no_engine_code.py ==", result.stdout)
        self.assertIn("== verify_darq.py ==", result.stdout)
        # ...but the run never reaches the final verdict.
        self.assertNotIn("All checks passed.", result.stdout)


if __name__ == "__main__":
    unittest.main()
