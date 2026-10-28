#!/usr/bin/env bash
#
# retry-test-on-launch-failure.sh <ci-sim-udid> <command...>: run an `xcodebuild test` command and,
# ONLY when it fails with the simulator launch-failure signature, reboot the same CI simulator and run
# the same command ONCE more. A real test failure or a build failure is never retried.
#
# From koinori's .github/scripts/retry-test-on-launch-failure.sh (koinori #1192, #1463, #1486;
# origin/qa 217b3f179), with one retry instead of three and no wait for host load: the host build
# lock already keeps other builds off the Mac (ops #345, light-runner-shared-ci design D6).
#
# Default-deny: retry only when ALL hold:
#   1. the run failed (non-zero exit), AND
#   2. the log has the launch-failure signature (LAUNCH_FAILURE_RE), AND
#   3. the log has NO test-assertion failure (XCTAssert, XCTFail, Swift Testing's "recorded an issue"
#      or its cross mark), AND
#   4. the log has NO build failure ("** BUILD FAILED **", "The following build commands failed").
# Anything else fails at once with the original exit code. Before the retry the same UDID is shut
# down, erased, booted and waited for, so the command's `-destination id=<udid>` stays valid, and the
# `-resultBundlePath` bundle is removed (xcodebuild refuses to overwrite one).
# Tests: tools/ios/tests/retry.test.sh.

set -uo pipefail

udid="${1:?usage: retry-test-on-launch-failure.sh <ci-sim-udid> <command...>}"
shift
if [ "$#" -eq 0 ]; then
  echo "::error::no test command given to retry-test-on-launch-failure.sh" >&2
  exit 2
fi

# The launch and UI-query infrastructure signatures, as koinori lists them (each entry is dated and
# explained in koinori's copy). "No such process" is anchored to a launch-failure context.
LAUNCH_FAILURE_RE='Simulator device failed to launch|Failed to install or launch the test runner|Failed to get launch progress|did not return a process handle|failed to launch.*No such process|Failed to get matching snapshots|Timed out while evaluating UI query|test runner timed out while preparing to run tests|test runner hung before establishing connection|Failed to get screenshot|Timed out while requesting screenshot'
REAL_TEST_FAILURE_RE="XCTAssert|XCTFail|recorded an issue|✘"
COMPILE_FAILURE_RE='\*\* BUILD FAILED \*\*|The following build commands failed'
MAX_ATTEMPTS=2

# run_once <log> <command...>: mirror output to the console and the log; return the command's code.
run_once() {
  local log="$1"; shift
  set +o pipefail
  "$@" 2>&1 | tee "$log"
  local rc="${PIPESTATUS[0]}"
  set -o pipefail
  return "$rc"
}

reboot_ci_sim() {
  echo "--- rebooting CI simulator $1 before the one retry (shutdown, erase, boot, wait) ---"
  xcrun simctl shutdown "$1" 2>/dev/null || true
  xcrun simctl erase "$1" 2>/dev/null || true
  xcrun simctl boot "$1" 2>/dev/null || true
  xcrun simctl bootstatus "$1" -b 2>/dev/null || true
}

clean_result_bundle() {
  local prev="" a
  for a in "$@"; do
    if [ "$prev" = "-resultBundlePath" ] && [ -n "$a" ]; then rm -rf "$a" 2>/dev/null || true; fi
    prev="$a"
  done
}

attempt=1
while : ; do
  log="$(mktemp "${TMPDIR:-/tmp}/retrytest.XXXXXX")"
  echo "--- test attempt ${attempt} of ${MAX_ATTEMPTS} ---"
  clean_result_bundle "$@"
  run_once "$log" "$@"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    [ "$attempt" -gt 1 ] && echo "Attempt ${attempt} passed: the earlier failure was the simulator launch flake."
    rm -f "$log"
    exit 0
  fi

  is_launch_flake=0
  if grep -qE "$LAUNCH_FAILURE_RE" "$log" \
     && ! grep -qE "$REAL_TEST_FAILURE_RE" "$log" \
     && ! grep -qE "$COMPILE_FAILURE_RE" "$log"; then
    is_launch_flake=1
  fi
  rm -f "$log"

  if [ "$is_launch_flake" -eq 1 ] && [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    echo "::warning::Simulator launch-failure signature with no test or build failure (attempt ${attempt}); rebooting the CI simulator and retrying once."
    reboot_ci_sim "$udid"
    attempt=$((attempt + 1))
    continue
  fi

  if [ "$is_launch_flake" -eq 1 ]; then
    echo "::error::The simulator launch failure happened again on the retry (exit ${rc}); failing."
  else
    echo "::error::Tests failed (exit ${rc}) and it is not the simulator launch failure; no retry."
  fi
  exit "$rc"
done
