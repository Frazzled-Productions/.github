#!/usr/bin/env bash
# retry.test.sh: the test run is retried once on the simulator launch failure only (ops #345, D6).
#
# The command under the wrapper is a stub that prints a fixed log per attempt and exits with a fixed
# code; `xcrun` is a stub that records calls. Nothing touches a real simulator.
#
#   tools/ios/tests/retry.test.sh                    test tools/ios/retry-test-on-launch-failure.sh
#   RETRY_SCRIPT=/path/to/copy.sh <this>             test another copy

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${RETRY_SCRIPT:-$HERE/../retry-test-on-launch-failure.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL: %s\n' "$1"; }

T="$(mktemp -d "${TMPDIR:-/tmp}/retrytest.XXXXXX")"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
UDID=12345678-1111-4111-8111-123456789012

cat > "$T/bin/xcrun" <<SHIM
#!/usr/bin/env bash
echo "\$*" >> "$T/xcrun.calls"
exit 0
SHIM
# fake-xcodebuild <args...>: attempt N prints $T/log.N and exits with $T/rc.N (0 when missing). It
# records whether the result bundle existed when it started.
cat > "$T/bin/fake-xcodebuild" <<SHIM
#!/usr/bin/env bash
n=\$(( \$(cat "$T/attempts" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "$T/attempts"
[ -e "$T/Result.xcresult" ] && echo "attempt \$n found an old result bundle" >> "$T/bundle.notes"
mkdir -p "$T/Result.xcresult"
[ -f "$T/log.\$n" ] && cat "$T/log.\$n"
exit "\$(cat "$T/rc.\$n" 2>/dev/null || echo 0)"
SHIM
chmod +x "$T/bin/"*

LAUNCH='Testing failed:
	Simulator device failed to launch com.frazzledproductions.roastconductor.
	Failed to install or launch the test runner.
** TEST FAILED **'
ASSERT='error: -[RoastConductorTests.FooTests testBar] : XCTAssertEqual failed: ("1") is not equal to ("2")'
BUILD='** BUILD FAILED **
The following build commands failed:
	SwiftCompile normal arm64'

# scenario <log1> <rc1> [<log2> <rc2> [<log3> <rc3>]]: run the wrapper once; sets RC and ATTEMPTS.
scenario() {
  rm -f "$T"/log.* "$T"/rc.* "$T/attempts" "$T/xcrun.calls" "$T/bundle.notes"
  rm -rf "$T/Result.xcresult"
  local i=1
  while [ "$#" -ge 2 ]; do
    printf '%s\n' "$1" > "$T/log.$i"; echo "$2" > "$T/rc.$i"; shift 2; i=$((i + 1))
  done
  ( cd "$T" && PATH="$T/bin:$PATH" RETRY_LAUNCH_CALM_WAIT=0 bash "$SCRIPT" "$UDID" \
      fake-xcodebuild test -resultBundlePath "$T/Result.xcresult" ) > "$T/out" 2>&1
  RC=$?
  ATTEMPTS=$(cat "$T/attempts" 2>/dev/null || echo 0)
}
rebooted() { [ "$(tr '\n' '|' < "$T/xcrun.calls" 2>/dev/null)" = "simctl shutdown $UDID|simctl erase $UDID|simctl boot $UDID|simctl bootstatus $UDID -b|" ]; }

echo "retry wrapper against: $SCRIPT"

scenario "Test run passed" 0
if [ "$RC" -eq 0 ] && [ "$ATTEMPTS" -eq 1 ]; then ok "a green run is run once"; else bad "green run: rc $RC, attempts $ATTEMPTS"; fi

scenario "$LAUNCH" 65 "Test run passed" 0
if [ "$RC" -eq 0 ] && [ "$ATTEMPTS" -eq 2 ]; then ok "launch signature alone: retried once, then green"
else bad "launch flake: rc $RC, attempts $ATTEMPTS"; fi
if rebooted; then ok "the same simulator is shut down, erased, booted and waited for before the retry"
else bad "reboot calls: $(tr '\n' '|' < "$T/xcrun.calls" 2>/dev/null)"; fi
if [ ! -s "$T/bundle.notes" ]; then ok "the result bundle is removed before the retry"
else bad "$(cat "$T/bundle.notes")"; fi

scenario "$LAUNCH
$ASSERT" 65 "Test run passed" 0
if [ "$RC" -eq 65 ] && [ "$ATTEMPTS" -eq 1 ] && [ ! -s "$T/xcrun.calls" ]; then
  ok "launch signature plus XCTAssert: fails at once with the original code, no reboot"
else bad "signature plus assertion: rc $RC, attempts $ATTEMPTS"; fi

scenario "$LAUNCH
$BUILD" 65 "Test run passed" 0
if [ "$RC" -eq 65 ] && [ "$ATTEMPTS" -eq 1 ]; then ok "launch signature plus a build failure: no retry"
else bad "signature plus build failure: rc $RC, attempts $ATTEMPTS"; fi

scenario "$ASSERT" 65 "Test run passed" 0
if [ "$RC" -eq 65 ] && [ "$ATTEMPTS" -eq 1 ]; then ok "a plain test failure: no retry"
else bad "plain failure: rc $RC, attempts $ATTEMPTS"; fi

scenario "$LAUNCH" 65 "$LAUNCH" 65 "Test run passed" 0
if [ "$RC" -eq 65 ] && [ "$ATTEMPTS" -eq 2 ]; then ok "two launch failures: stops after the second attempt"
else bad "launch flake twice: rc $RC, attempts $ATTEMPTS (one retry only)"; fi

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"
