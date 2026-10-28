#!/usr/bin/env bash
#
# with-build-lock.sh --label <who> -- <command...>: run <command> under the host-wide build lock, so
# only one Xcode build or test runs on the Mac at a time (ops #345, light-runner-fleet D3 and D4;
# light-runner-shared-ci D5).
#
# The lock is ops `scripts/build-lock.sh` in the ops checkout on the Mac
# ($BUILD_LOCK_SCRIPT overrides the path, for tests). When that file is missing or not executable (a
# different machine), this prints a ::warning:: and runs <command> without the lock: the job never
# fails for it. The exit code is always <command>'s. Tests: tools/ios/tests/with-build-lock.test.sh.

set -uo pipefail

LOCK="${BUILD_LOCK_SCRIPT:-$HOME/Projects/frazzled-productions/ops/scripts/build-lock.sh}"
label=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --label) label="${2:-}"; shift 2 ;;
    --) shift; break ;;
    *) echo "::error::usage: with-build-lock.sh --label <who> -- <command...>" >&2; exit 2 ;;
  esac
done
if [ "$#" -eq 0 ] || [ -z "$label" ]; then
  echo "::error::usage: with-build-lock.sh --label <who> -- <command...>" >&2
  exit 2
fi

if [ -x "$LOCK" ]; then
  exec "$LOCK" run --label "$label" -- "$@"
fi
echo "::warning::No build lock at $LOCK; running '$label' without it."
exec "$@"
