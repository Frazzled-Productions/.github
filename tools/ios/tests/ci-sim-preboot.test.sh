#!/usr/bin/env bash
# ci-sim-preboot.test.sh: each iOS app tests on its own erased CI simulator (ops #345, design D3).
#
# `xcrun` is a stub that serves fixed runtime, device type and device lists and logs every call, so
# nothing touches a real simulator. Checks: the name derived from the repository; a missing device is
# created on the newest available iOS runtime as the requested model; a device of the wrong model is
# deleted and recreated; shutdown, erase, boot, bootstatus in that order; the UDID is the last line;
# the default GUI simulator is refused; a boot that never finishes fails within the bound.
#
#   tools/ios/tests/ci-sim-preboot.test.sh            test tools/ios/ci-sim.sh
#   CI_SIM_SCRIPT=/path/to/ci-sim.sh <this>           test another copy

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${CI_SIM_SCRIPT:-$HERE/../ci-sim.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL: %s\n' "$1"; }

T="$(mktemp -d "${TMPDIR:-/tmp}/cisimpreboot.XXXXXX")"
# The hang case's stub bootstatus records its PID so a survivor is killed here.
trap 'kill -9 $(cat "$T/hung" 2>/dev/null) 2>/dev/null; rm -rf "$T"' EXIT
mkdir -p "$T/bin"

RT_OLD=com.apple.CoreSimulator.SimRuntime.iOS-26-0
RT_NEW=com.apple.CoreSimulator.SimRuntime.iOS-27-1
RT_GONE=com.apple.CoreSimulator.SimRuntime.iOS-28-0
PRO18=com.apple.CoreSimulator.SimDeviceType.iPhone-18-Pro
PRO17=com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro
NEW_UDID=99999999-0000-4000-8000-000000000009

cat > "$T/runtimes.json" <<JSON
{"runtimes":[
 {"identifier":"$RT_OLD","version":"26.0","platform":"iOS","isAvailable":true},
 {"identifier":"$RT_NEW","version":"27.1","platform":"iOS","isAvailable":true},
 {"identifier":"$RT_GONE","version":"28.0","platform":"iOS","isAvailable":false},
 {"identifier":"com.apple.CoreSimulator.SimRuntime.watchOS-27-0","version":"27.0","platform":"watchOS","isAvailable":true}
]}
JSON
cat > "$T/devicetypes.json" <<JSON
{"devicetypes":[
 {"name":"iPhone 17 Pro","identifier":"$PRO17"},
 {"name":"iPhone 18 Pro","identifier":"$PRO18"}
]}
JSON

cat > "$T/bin/xcrun" <<SHIM
#!/usr/bin/env bash
echo "\$*" >> "$T/calls"
case "\$*" in
  "simctl list runtimes --json") cat "$T/runtimes.json" ;;
  "simctl list devicetypes --json") cat "$T/devicetypes.json" ;;
  "simctl list devices --json") cat "$T/devices.json" ;;
  "simctl create "*) echo "$NEW_UDID" ;;
  "simctl bootstatus "*) if [ -e "$T/hang" ]; then echo "\$\$" >> "$T/hung"; exec sleep 30; fi ;;
esac
exit 0
SHIM
chmod +x "$T/bin/xcrun"

# run_preboot <devices-json> <env assignments...>: run preboot "iPhone 18 Pro"; sets RC and OUT.
run_preboot() {
  printf '%s\n' "$1" > "$T/devices.json"; shift
  : > "$T/calls"
  OUT=$(env -u CI_SIMULATOR_NAME PATH="$T/bin:$PATH" "$@" bash "$SCRIPT" preboot "iPhone 18 Pro" 2>"$T/err")
  RC=$?
}
last_line() { printf '%s\n' "$OUT" | tail -n1; }
calls_for() { grep -E "^simctl (shutdown|erase|boot|bootstatus|delete|create) " "$T/calls" | tr '\n' '|'; }

echo "ci-sim.sh preboot against: $SCRIPT"

# 1. Missing device, name derived from the repository.
run_preboot '{"devices":{}}' GITHUB_REPOSITORY=Frazzled-Productions/roast-conductor
if [ "$RC" -eq 0 ]; then ok "missing device: exits 0"; else bad "missing device: exit $RC ($(cat "$T/err"))"; fi
if grep -qx "simctl create RoastConductor-CI-iPhone $PRO18 $RT_NEW" "$T/calls"; then
  ok "roast-conductor gives RoastConductor-CI-iPhone, created as iPhone 18 Pro on the newest available iOS"
else bad "did not create RoastConductor-CI-iPhone as $PRO18 on $RT_NEW: $(tr '\n' '|' < "$T/calls")"; fi
want="simctl create RoastConductor-CI-iPhone $PRO18 $RT_NEW|simctl shutdown $NEW_UDID|simctl erase $NEW_UDID|simctl boot $NEW_UDID|simctl bootstatus $NEW_UDID -b|"
if [ "$(calls_for)" = "$want" ]; then ok "order is create, shutdown, erase, boot, bootstatus"
else bad "order: $(calls_for)"; fi
if [ "$(last_line)" = "$NEW_UDID" ]; then ok "UDID is the last line"; else bad "last line is '$(last_line)'"; fi

# 2. Other repo names.
run_preboot '{"devices":{}}' GITHUB_REPOSITORY=Frazzled-Productions/loop-year
if grep -q "^simctl create LoopYear-CI-iPhone " "$T/calls"; then ok "loop-year gives LoopYear-CI-iPhone"
else bad "loop-year name: $(tr '\n' '|' < "$T/calls")"; fi
run_preboot '{"devices":{}}' GITHUB_REPOSITORY=Frazzled-Productions/koinori
if grep -q "^simctl create Koinori-CI-iPhone " "$T/calls"; then ok "koinori gives Koinori-CI-iPhone"
else bad "koinori name: $(tr '\n' '|' < "$T/calls")"; fi
run_preboot '{"devices":{}}' GITHUB_REPOSITORY=Frazzled-Productions/loop-year CI_SIMULATOR_NAME=Custom-CI
if grep -q "^simctl create Custom-CI " "$T/calls"; then ok "an explicit ci-simulator-name wins"
else bad "explicit name: $(tr '\n' '|' < "$T/calls")"; fi

# 3. Existing device of the right model: reused, erased, booted.
OWN=44444444-1111-4111-8111-444444444444
run_preboot "{\"devices\":{\"$RT_NEW\":[{\"name\":\"RoastConductor-CI-iPhone\",\"udid\":\"$OWN\",\"deviceTypeIdentifier\":\"$PRO18\"},{\"name\":\"LoopYear-CI-iPhone\",\"udid\":\"55555555-1111-4111-8111-555555555555\",\"deviceTypeIdentifier\":\"$PRO18\"}]}}" \
  GITHUB_REPOSITORY=Frazzled-Productions/roast-conductor
want="simctl shutdown $OWN|simctl erase $OWN|simctl boot $OWN|simctl bootstatus $OWN -b|"
if [ "$RC" -eq 0 ] && [ "$(calls_for)" = "$want" ] && [ "$(last_line)" = "$OWN" ]; then
  ok "existing right-model device is reused; another app's device is never touched"
else bad "existing device: rc $RC, calls $(calls_for), last '$(last_line)'"; fi

# 4. Wrong model left over: deleted and recreated.
STALE=66666666-1111-4111-8111-666666666666
run_preboot "{\"devices\":{\"$RT_NEW\":[{\"name\":\"LoopYear-CI-iPhone\",\"udid\":\"$STALE\",\"deviceTypeIdentifier\":\"$PRO17\"}]}}" \
  GITHUB_REPOSITORY=Frazzled-Productions/loop-year
want="simctl shutdown $STALE|simctl delete $STALE|simctl create LoopYear-CI-iPhone $PRO18 $RT_NEW|simctl shutdown $NEW_UDID|simctl erase $NEW_UDID|simctl boot $NEW_UDID|simctl bootstatus $NEW_UDID -b|"
if [ "$RC" -eq 0 ] && [ "$(calls_for)" = "$want" ] && [ "$(last_line)" = "$NEW_UDID" ]; then
  ok "wrong model is deleted and recreated as iPhone 18 Pro"
else bad "wrong model: rc $RC, calls $(calls_for)"; fi

# 5. The default GUI simulator is refused.
GUI=49420412-1111-4111-8111-777777777777
run_preboot "{\"devices\":{\"$RT_NEW\":[{\"name\":\"RoastConductor-CI-iPhone\",\"udid\":\"$GUI\",\"deviceTypeIdentifier\":\"$PRO18\"}]}}" \
  GITHUB_REPOSITORY=Frazzled-Productions/roast-conductor
if [ "$RC" -ne 0 ] && ! grep -qE "^simctl (erase|boot) $GUI" "$T/calls"; then
  ok "a device with the GUI simulator prefix is refused, never erased or booted"
else bad "GUI simulator: rc $RC, calls $(calls_for)"; fi

# 6. Unknown model fails.
printf '{"devicetypes":[]}\n' > "$T/devicetypes.json"
run_preboot '{"devices":{}}' GITHUB_REPOSITORY=Frazzled-Productions/roast-conductor
if [ "$RC" -ne 0 ] && ! grep -q "^simctl create" "$T/calls"; then ok "an unknown model fails without creating anything"
else bad "unknown model: rc $RC, calls $(calls_for)"; fi

# 7. A boot that never finishes (wedged bootstatus) fails within the bound, naming the simulator, so
# the job fails and releases the host build lock instead of holding it for the whole step.
printf '{"devicetypes":[{"name":"iPhone 18 Pro","identifier":"%s"}]}\n' "$PRO18" > "$T/devicetypes.json"
touch "$T/hang"
start=$SECONDS
run_preboot '{"devices":{}}' GITHUB_REPOSITORY=Frazzled-Productions/roast-conductor CI_SIM_BOOT_TIMEOUT=3
took=$((SECONDS - start))
rm -f "$T/hang"
if [ "$RC" -ne 0 ] && [ "$took" -lt 20 ] && grep -q "RoastConductor-CI-iPhone ($NEW_UDID) did not boot within 3 seconds" "$T/err"; then
  ok "a wedged boot fails in ${took}s with an error naming the simulator"
else bad "wedged boot: rc $RC after ${took}s, stderr: $(tr '\n' '|' < "$T/err")"; fi

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"
