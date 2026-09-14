#!/usr/bin/env bash
# Single entry point wiring the build and every verification step together.
#
#   tools/check.sh              # build (online) + verify + no-fork guard
#   tools/check.sh --offline    # reuse whatever is already cached, still verifies checksums
#   tools/check.sh --no-build   # skip the build step, verify whatever is already at dist/darq
#
# The build step produces both dist/darq and dist/install.sh; the verify step checks both.
#
# DARQ_CHECK_ROOT overrides the root this script operates on, for tests only: it exists so the
# hermetic suite in tests/test_check_sh.py can point this exact script at a scratch tree instead
# of this real repository. It is a production risk if it ever leaks into a real invocation --
# a set-and-forgotten env var could make this script silently report "All checks passed." about a
# tree nobody meant to check -- so when it is in effect this script says so, loudly, at both the
# start and the end of its own output, never only once where a long run could scroll it away.
set -euo pipefail

if [ -n "${DARQ_CHECK_ROOT:-}" ]; then
  ROOT_DIR="$DARQ_CHECK_ROOT"
  ROOT_OVERRIDDEN=1
else
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  ROOT_OVERRIDDEN=0
fi
cd "$ROOT_DIR"

_announce_root_override() {
  echo "############################################################"
  echo "# DARQ_CHECK_ROOT override is in effect: checking $ROOT_DIR"
  echo "# This is NOT the real DARQ repository."
  echo "############################################################"
}

if [ "$ROOT_OVERRIDDEN" -eq 1 ]; then
  _announce_root_override
  echo
fi

BUILD_ARGS=()
DO_BUILD=1
for arg in "$@"; do
  case "$arg" in
    --offline) BUILD_ARGS+=("--offline") ;;
    --no-build) DO_BUILD=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "== unit tests =="
PYTHONPATH="$ROOT_DIR" python3 -m unittest discover -s tests -q

echo
echo "== check_no_engine_code.py =="
python3 tools/check_no_engine_code.py

if [ "$DO_BUILD" -eq 1 ]; then
  echo
  echo "== build_darq.py =="
  python3 tools/build_darq.py "${BUILD_ARGS[@]}"
fi

echo
echo "== verify_darq.py =="
python3 tools/verify_darq.py

if [ "$ROOT_OVERRIDDEN" -eq 1 ]; then
  echo
  _announce_root_override
fi

echo
echo "All checks passed."
