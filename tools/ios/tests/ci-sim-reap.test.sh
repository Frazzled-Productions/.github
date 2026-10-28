#!/usr/bin/env bash
# ci-sim-reap.test.sh: `ci-sim.sh reap` kills only the job's own workspace and its own CI simulator.
#
# Ported from koinori's .github/scripts/ci-sim-reap.test.sh (koinori #2349) with the markers narrowed
# (ops #345, design D4): koinori's project and scheme markers also matched a local agent build of the
# same app in an Orca worktree (koinori #2592), so the shared reap keeps only the runner workspace and
# the repo's own CI simulator.
#
# The decoys are real `sleep` processes, so a kill is a real kill. `ps`, `lsof` and `xcrun` are shimmed
# onto PATH and only ever report the FIXTURE table below (plus the reap's own ancestors), so the reap
# under test cannot reach a real build on this machine, however broad its markers.
#
#   tools/ios/tests/ci-sim-reap.test.sh                 test tools/ios/ci-sim.sh
#   CI_SIM_SCRIPT=/path/to/ci-sim.sh <this>             test another copy

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${CI_SIM_SCRIPT:-$HERE/../ci-sim.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL: %s\n' "$1"; }

T="$(mktemp -d "${TMPDIR:-/tmp}/cisimreap.XXXXXX")"
DECOYS=()
cleanup() {
  local p
  for p in "${DECOYS[@]:-}"; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null; done
  rm -rf "$T"
}
trap cleanup EXIT

# decoy VAR: start a real throwaway process and store its PID in VAR.
decoy() { sleep 300 >/dev/null 2>&1 & DECOYS+=("$!"); printf -v "$1" '%s' "$!"; disown "$!"; }
alive() { kill -0 "$1" 2>/dev/null; }

WS="$T/actions-runner-roast-conductor/_work/roast-conductor/roast-conductor"
KOINORI_WS="$T/actions-runner-koinori/_work/koinori/koinori"
AGENT_WT="$T/orca/workspaces/roast-conductor/brave-otter"
mkdir -p "$WS/RoastConductor" "$KOINORI_WS" "$AGENT_WT" "$T/bin" "$T/cwd"
SIM_NAME="RoastConductor-CI-iPhone"
CI_UDID="11111111-AAAA-4AAA-8AAA-111111111111"
OTHER_UDID="22222222-BBBB-4BBB-8BBB-222222222222"
LY_UDID="33333333-CCCC-4CCC-8CCC-333333333333"
XB=/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild
SIMCTL=/Applications/Xcode.app/Contents/Developer/usr/bin/simctl
CS=/Library/Developer/PrivateFrameworks/CoreSimulator.framework/Versions/A/XPCServices
LAUNCHD_SIM=/Library/Developer/CoreSimulator/Volumes/iOS_27/launchd_sim

# ps: `-Ao pid=,ppid=,command=` prints the fixture table, then the reap's own ancestors (from the
# topmost ci-sim.sh process up to, not including, this test) dressed as xcodebuild processes inside the
# workspace, so a reap that forgot to spare its ancestors would kill itself. `-o command= -p PID`
# prints one command.
cat > "$T/bin/ps" <<SHIM
#!/usr/bin/env bash
case "\$*" in
  *"-p "*) pid="\${*##* }"; awk -F '\t' -v p="\$pid" '\$1 == p { print \$4 }' "$T/procs.tsv" ;;
  *)
    awk -F '\t' '{ printf "%s %s %s\n", \$1, \$2, \$4 }' "$T/procs.tsv"
    chain=(); p=\$PPID
    while [ "\${p:-0}" -gt 1 ] && [ "\$p" != "$$" ]; do
      chain+=("\$p"); p=\$(/bin/ps -o ppid= -p "\$p" | tr -d ' ')
    done
    top=-1; i=0
    for p in "\${chain[@]}"; do
      case "\$(/bin/ps -o command= -p "\$p")" in *ci-sim.sh*) top=\$i ;; esac
      i=\$((i+1))
    done
    [ "\$top" -ge 0 ] || exit 0
    i=0
    for p in "\${chain[@]}"; do
      if [ "\$i" -ge "\$top" ]; then
        printf '%s %s %s\n' "\$p" "\$(/bin/ps -o ppid= -p "\$p" | tr -d ' ')" "$XB build -workspace $WS/ancestor"
      fi
      i=\$((i+1))
    done ;;
esac
SHIM
# lsof -a -p PID -d cwd -Fn: the fixture cwd.
cat > "$T/bin/lsof" <<SHIM
#!/usr/bin/env bash
while [ \$# -gt 0 ]; do [ "\$1" = "-p" ] && pid="\$2"; shift; done
awk -F '\t' -v p="\${pid:-}" '\$1 == p { printf "p%s\nfcwd\nn%s\n", \$1, \$3 }' "$T/procs.tsv"
SHIM
# xcrun: a fixed device list; every call is recorded.
cat > "$T/bin/xcrun" <<SHIM
#!/usr/bin/env bash
echo "\$*" >> "$T/xcrun.calls"
case "\$*" in
  "simctl list devices --json")
    printf '{"devices":{"com.apple.CoreSimulator.SimRuntime.iOS-27-0":[{"name":"$SIM_NAME","udid":"$CI_UDID"},{"name":"iPhone 18 Pro","udid":"$OTHER_UDID"},{"name":"LoopYear-CI-iPhone","udid":"$LY_UDID"}]}}\n' ;;
esac
exit 0
SHIM
chmod +x "$T/bin/"*

survives() { if alive "$2"; then ok "spares $1"; else bad "KILLED $1 (pid $2)"; fi; }
dies()     { if alive "$2"; then bad "did not kill $1 (pid $2)"; else ok "kills $1"; fi; }

# scenario <workspace>: fresh decoys, one reap with GITHUB_WORKSPACE=<workspace>.
scenario() {
  local ws="$1"
  decoy koinori_build; decoy agent_build; decoy cs_service; decoy other_sim; decoy sibling_ws
  decoy own_build; decoy own_child; decoy orphan_diag; decoy ci_sim
  # shellcheck disable=SC2154 # the decoy PIDs are assigned by `decoy` through printf -v
  {
    printf '%s\t1\t%s\t%s\n' "$koinori_build" "$KOINORI_WS" "$XB test -project Koinori/Koinori.xcodeproj -scheme Koinori -destination platform=iOS Simulator,name=Koinori-CI-iPhone"
    printf '%s\t1\t%s\t%s\n' "$agent_build" "$AGENT_WT" "$XB test -project RoastConductor.xcodeproj -scheme RoastConductor -destination platform=iOS Simulator,name=iPhone 18 Pro"
    printf '%s\t1\t/\t%s\n' "$cs_service" "$CS/com.apple.CoreSimulator.CoreSimulatorService.xpc/Contents/MacOS/com.apple.CoreSimulator.CoreSimulatorService"
    printf '%s\t1\t/\t%s\n' "$other_sim" "$LAUNCHD_SIM $HOME/Library/Developer/CoreSimulator/Devices/$OTHER_UDID/data/var/run/launchd_bootstrap.plist"
    printf '%s\t1\t%s\t%s\n' "$sibling_ws" "$WS-other" "$XB build -project Other.xcodeproj -scheme Other"
    printf '%s\t1\t%s\t%s\n' "$own_build" "$WS" "$XB test -project RoastConductor.xcodeproj -scheme RoastConductor -destination id=$CI_UDID"
    printf '%s\t%s\t/\t%s\n' "$own_child" "$own_build" "$SIMCTL diagnose -b --no-archive --output=/tmp/xcresult-staging"
    printf '%s\t1\t%s\t%s\n' "$orphan_diag" "$WS/RoastConductor" "$SIMCTL diagnose -b --no-archive --output=/tmp/orphaned-staging"
    printf '%s\t1\t/\t%s\n' "$ci_sim" "$LAUNCHD_SIM $HOME/Library/Developer/CoreSimulator/Devices/$CI_UDID/data/var/run/launchd_bootstrap.plist"
  } > "$T/procs.tsv"
  : > "$T/xcrun.calls"
  ( cd "$T/cwd" && PATH="$T/bin:$PATH" GITHUB_WORKSPACE="$ws" CI_SIMULATOR_NAME="$SIM_NAME" \
      bash "$SCRIPT" reap ) > "$T/reap.log" 2>&1
  rc=$?
  sleep 0.3   # let SIGKILL land before probing
  if [ "$rc" -eq 0 ] && grep -q "Reap complete" "$T/reap.log"; then
    ok "reap finishes and exits 0 (its own ancestors spared)"
  else
    bad "reap exited $rc or died before finishing (killed itself or its parent?)"
  fi
  survives "another runner's koinori xcodebuild" "$koinori_build"
  survives "a local agent build of the same app in an Orca worktree" "$agent_build"
  survives "CoreSimulatorService (shared by every repo)" "$cs_service"
  survives "another simulator's launchd_sim" "$other_sim"
  survives "an xcodebuild in a sibling of the workspace (prefix, not inside)" "$sibling_ws"
  dies "the job's own xcodebuild on the CI simulator" "$own_build"
  dies "the simctl diagnose child of the job's xcodebuild" "$own_child"
  dies "the CI simulator's launchd_sim" "$ci_sim"
  if [ -n "$ws" ] && [ "$ws" != / ]; then
    dies "an orphaned simctl diagnose with its cwd in the workspace" "$orphan_diag"
  else
    survives "an orphan known only by its cwd, when the workspace is '$ws'" "$orphan_diag"
  fi
  if grep -q "shutdown all" "$T/xcrun.calls"; then bad "ran 'simctl shutdown all'"
  else ok "never runs 'simctl shutdown all'"; fi
  if grep -qx "simctl shutdown $CI_UDID" "$T/xcrun.calls"; then ok "shuts the CI simulator down"
  else bad "did not shut the CI simulator ($CI_UDID) down"; fi
  if grep -qE "shutdown ($OTHER_UDID|$LY_UDID)" "$T/xcrun.calls"; then bad "shut down another simulator"
  else ok "leaves other simulators alone"; fi
  if [ "$FAIL" -ne 0 ]; then echo "  reap log:"; sed 's/^/    /' "$T/reap.log"; fi
}

echo "ci-sim.sh reap against: $SCRIPT"
echo "Workspace set:"; scenario "$WS"
echo "Workspace empty:"; scenario ""
echo "Workspace '/':"; scenario "/"

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"
