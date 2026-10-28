#!/usr/bin/env bash
#
# ci-sim.sh: the CI simulator guards for the shared iOS workflows (ios-ci.yml, ios-testflight.yml).
# Generalised from koinori's .github/scripts/ci-sim.sh (origin/qa 217b3f179) for every iOS app
# (ops #345, light-runner-shared-ci design D3 and D4).
#
#   ci-sim.sh reap              kill this job's stray xcodebuild / simctl processes and shut its CI
#                               simulator down. Run before the work and as an `if: always()` step.
#   ci-sim.sh preboot <model>   create (if missing), erase and boot this repo's CI simulator of device
#                               model <model> (e.g. "iPhone 18 Pro") on the newest iOS runtime that
#                               supports that model, and print its UDID on the LAST line of stdout.
#
# The CI simulator is named $CI_SIMULATOR_NAME, or when that is empty the repository name from
# $GITHUB_REPOSITORY in PascalCase plus "-CI-iPhone" (roast-conductor gives RoastConductor-CI-iPhone).
# Each app has its own, so two apps never share or erase each other's device.
#
# Everything is best-effort and idempotent except preboot's failures to find a runtime, model or
# device, or to boot within CI_SIM_BOOT_TIMEOUT seconds (default 180), which fail the step.
# Tests: tools/ios/tests/ci-sim-reap.test.sh, ci-sim-preboot.test.sh.

set -uo pipefail

# ci_name: the CI simulator's name.
ci_name() {
  if [ -n "${CI_SIMULATOR_NAME:-}" ]; then
    printf '%s\n' "${CI_SIMULATOR_NAME}"
    return
  fi
  local repo="${GITHUB_REPOSITORY:-}"
  repo="${repo##*/}"
  if [ -z "${repo}" ]; then
    echo "::error::No CI_SIMULATOR_NAME and no GITHUB_REPOSITORY to derive one from." >&2
    return 1
  fi
  printf '%s\n' "${repo}" | awk -F '[-_.]' '{
    out = ""
    for (i = 1; i <= NF; i++) if ($i != "") out = out toupper(substr($i, 1, 1)) substr($i, 2)
    print out "-CI-iPhone"
  }'
}

# The human's default GUI simulator: never target it from CI (koinori #569, #917). Matched by UDID
# prefix so the full UDID need not be hard-coded.
DEFAULT_GUI_SIM_PREFIX="49420412"

# reap: kill only what is provably this job's (design D4).
#
# The Mac hosts several repos' runners, the light runners and local agent builds. A process is reaped
# only when BOTH hold:
#   - it is a tool process: an xcodebuild, simctl or xcrun invocation, or a per-device process under
#     CoreSimulator (launchd_sim and friends). CoreSimulatorService itself is NEVER reaped;
#   - it belongs to this job: its command line names this repo's CI simulator (by name or UDID) or
#     this runner's $GITHUB_WORKSPACE, or its working directory is inside $GITHUB_WORKSPACE.
# There are no project or scheme markers: in koinori they also matched a local agent build of the same
# app in an Orca worktree and killed it (koinori #2592). The reap and its ancestors are always spared;
# every descendant of a reaped process goes with it (a `simctl diagnose` child of a killed xcodebuild).
# Only this repo's CI simulator is shut down, never `shutdown all`.
reap() {
  local name ws udids udid pids pid
  name=$(ci_name) || name=""
  echo "Reaping this job's stray xcodebuild / simctl processes and its CI simulator ${name:-(none)}."
  ws="${GITHUB_WORKSPACE:-}"
  # A workspace too short to be specific (unset, `/`, a typo) must never become a marker that matches
  # everything; then only the CI simulator markers remain.
  case "${ws}" in /*/*/*) ;; *) ws="" ;; esac
  udids=""
  [ -n "${name}" ] && udids=$(ci_device_udids "${name}")
  # shellcheck disable=SC2086 # the UDID list is deliberately word-split into markers
  pids=$(reap_probe | reap_select "$$" "$ws" ${name:+"$name"} ${udids} ${ws:+"$ws/"})
  if [ -n "${pids}" ]; then
    for pid in ${pids}; do
      echo "  killing ${pid}: $(ps -o command= -p "${pid}" 2>/dev/null | cut -c1-160)"
    done
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  else
    echo "  no xcodebuild / simctl processes of this job to reap."
  fi
  for udid in ${udids}; do
    echo "  shutting down CI simulator ${udid}"
    xcrun simctl shutdown "${udid}" 2>/dev/null || true
  done
  # Best-effort prune of stale result bundles left by a killed job (cwd is the workspace).
  rm -rf ./*.xcresult || true
  echo "Reap complete."
}

# ci_device_udids <name>: every simulator called <name>, on any runtime, one UDID per line. Never the
# default GUI simulator, whatever it is called.
ci_device_udids() {
  xcrun simctl list devices --json 2>/dev/null | python3 -c '
import sys, json
name, guard = sys.argv[1], sys.argv[2]
try:
    devices = json.load(sys.stdin).get("devices", {})
except Exception:
    sys.exit(0)
for devs in devices.values():
    for d in devs:
        udid = d.get("udid") or ""
        if d.get("name") == name and udid and not udid.startswith(guard):
            print(udid)
' "$1" "${DEFAULT_GUI_SIM_PREFIX}" 2>/dev/null || true
}

# The tool-process test. Matches the executable as a path component, so `xcodebuild` matches
# `/usr/bin/xcodebuild archive ...` but not `my-xcodebuild-notes.txt`.
REAP_TOOL_RE='(^|[ /])(xcodebuild|simctl|xcrun|launchd_sim)( |$)|/CoreSimulator/'

# reap_probe: the live process table as TSV  PID<TAB>PPID<TAB>CWD<TAB>COMMAND. CWD is looked up
# (lsof) only for tool processes, '-' otherwise.
reap_probe() {
  local pid ppid cmd cwd
  ps -Ao pid=,ppid=,command= 2>/dev/null | while read -r pid ppid cmd; do
    cwd="-"
    if [[ "${cmd}" =~ ${REAP_TOOL_RE} ]]; then
      # Bounded (macOS has no `timeout`): lsof on a wedged process must not hang the reap.
      cwd=$(perl -e 'alarm 5; exec @ARGV' lsof -a -p "${pid}" -d cwd -Fn </dev/null 2>/dev/null \
        | sed -n 's/^n//p' | head -n1)
      [ -n "${cwd}" ] || cwd="-"
    fi
    printf '%s\t%s\t%s\t%s\n' "${pid}" "${ppid}" "${cwd}" "${cmd}"
  done
}

# reap_select <self-pid> <workspace-or-empty> <marker>...: PURE. Reads reap_probe TSV on stdin and
# prints the PIDs to kill, one per line.
reap_select() {
  local self="$1" ws="$2"
  shift 2
  # Passed through the environment, not `awk -v`: BSD awk rejects a newline in a -v value.
  REAP_MARKERS=$(printf '%s\n' "$@") REAP_SELF="${self}" REAP_WS="${ws}" REAP_TOOLRE="${REAP_TOOL_RE}" \
  awk -F '\t' '
    BEGIN {
      self = ENVIRON["REAP_SELF"]; ws = ENVIRON["REAP_WS"]; toolre = ENVIRON["REAP_TOOLRE"]
      nm = split(ENVIRON["REAP_MARKERS"], m, "\n")
    }
    function scoped(c, d,   i) {
      for (i = 1; i <= nm; i++) if (m[i] != "" && index(c, m[i]) > 0) return 1
      if (ws != "" && (d == ws || index(d, ws "/") == 1)) return 1
      return 0
    }
    {
      p = $1; pp = $2; d = $3; c = $4
      for (i = 5; i <= NF; i++) c = c "\t" $i
      n++; pid[n] = p; ppid[n] = pp
      cmd[p] = c; cwd[p] = d; parent[p] = pp
    }
    END {
      for (a = self; a != "" && !(a in spare); a = parent[a]) spare[a] = 1
      for (i = 1; i <= n; i++) {
        p = pid[i]
        if (p + 0 <= 1 || cmd[p] ~ /CoreSimulatorService/) spare[p] = 1
        if (!spare[p] && cmd[p] ~ toolre && scoped(cmd[p], cwd[p])) kill[p] = 1
      }
      do {
        grew = 0
        for (i = 1; i <= n; i++)
          if (!(pid[i] in kill) && !spare[pid[i]] && (ppid[i] in kill)) { kill[pid[i]] = 1; grew = 1 }
      } while (grew)
      for (i = 1; i <= n; i++) if (pid[i] in kill) print pid[i]
    }'
}

# preboot <model>: resolve (creating if needed) this repo's CI simulator of <model> on the newest
# available iOS runtime that supports <model>, erase it (so the post-test `simctl diagnose` sweep has
# almost no backlog, koinori #917) and boot it. A device of that name but another model is deleted and
# recreated, so the device never drifts; so is one left on a runtime that is unavailable or no longer
# supports <model>. A failed create fails the step (roast-conductor run 40748691093 passed simctl's
# error text on as the UDID). Progress goes to stderr; the UDID is the last line of stdout.
preboot() {
  local model="${1:-}" name sel runtime_id fits device_type found udid stale err rc=0
  if [ -z "${model}" ]; then
    echo "::error::usage: ci-sim.sh preboot <device model, e.g. iPhone 18 Pro>" >&2
    exit 2
  fi
  name=$(ci_name) || exit 1

  device_type=$(xcrun simctl list devicetypes --json | python3 -c '
import sys, json
model = sys.argv[1]
t = next((d for d in json.load(sys.stdin).get("devicetypes", []) if d.get("name") == model), None)
print(t["identifier"] if t else "")
' "${model}")
  if [ -z "${device_type}" ]; then
    echo "::error::No simulator device type called '${model}'." >&2
    exit 1
  fi

  # The newest available iOS runtime whose supportedDeviceTypes has the model (a new point release can
  # drop it: iOS 27.1 does not support iPhone 18 Pro), then every runtime that fits, space-separated.
  # Otherwise ERROR:<the runtimes checked>.
  sel=$(xcrun simctl list runtimes --json | python3 -c '
import sys, json
want = sys.argv[1]
rts = [r for r in json.load(sys.stdin).get("runtimes", [])
       if r.get("isAvailable") and r.get("platform", "iOS") == "iOS"
       and r.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")]
def key(r):
    return [int(x) for x in r.get("version", "0").split(".") if x.isdigit()]
rts.sort(key=key, reverse=True)
ok = [r for r in rts if any(t.get("identifier") == want for t in r.get("supportedDeviceTypes", []))]
print(" ".join(r["identifier"] for r in ok) if ok
      else "ERROR:" + (", ".join(r["identifier"] for r in rts) or "none"))
' "${device_type}")
  case "${sel}" in
    ERROR:*|"")
      echo "::error::No available iOS simulator runtime supports ${model} (${device_type}); runtimes checked: ${sel#ERROR:}." >&2
      exit 1
      ;;
  esac
  runtime_id="${sel%% *}"
  fits="${sel}"

  # Devices of this name left on another runtime that is unavailable or does not support the model
  # (or that simctl marks unavailable): deleted so the device is recreated on the chosen runtime.
  # Never another name, never the default GUI simulator.
  stale=$(xcrun simctl list devices --json | python3 -c '
import sys, json
runtime_id, name, fits, guard = sys.argv[1], sys.argv[2], sys.argv[3].split(), sys.argv[4]
for rt, ds in json.load(sys.stdin).get("devices", {}).items():
    if rt == runtime_id:
        continue
    for d in ds:
        udid = d.get("udid") or ""
        if d.get("name") == name and udid and not udid.startswith(guard) \
           and (rt not in fits or d.get("isAvailable") is False):
            print(udid)
' "${runtime_id}" "${name}" "${fits}" "${DEFAULT_GUI_SIM_PREFIX}")
  for udid in ${stale}; do
    echo "Existing ${name} (${udid}) is on an unavailable runtime or one without ${model}; deleting it." >&2
    xcrun simctl shutdown "${udid}" 2>/dev/null || true
    xcrun simctl delete "${udid}" 2>/dev/null || true
  done

  # An existing device of this name on the runtime: its UDID if it is the right model, else
  # WRONGTYPE:<udid> so it is recreated.
  found=$(xcrun simctl list devices --json | python3 -c '
import sys, json
runtime_id, name, want = sys.argv[1], sys.argv[2], sys.argv[3]
devices = json.load(sys.stdin).get("devices", {}).get(runtime_id, [])
match = next((d for d in devices if d.get("name") == name), None)
if match is None:
    print("")
elif match.get("deviceTypeIdentifier") == want:
    print(match["udid"])
else:
    print("WRONGTYPE:" + match["udid"])
' "${runtime_id}" "${name}" "${device_type}")

  case "${found}" in
    WRONGTYPE:*)
      udid="${found#WRONGTYPE:}"
      echo "Existing ${name} (${udid}) is another model; recreating it as ${model}." >&2
      xcrun simctl shutdown "${udid}" 2>/dev/null || true
      xcrun simctl delete "${udid}" 2>/dev/null || true
      udid=""
      ;;
    *) udid="${found}" ;;
  esac

  if [ -z "${udid}" ]; then
    echo "Creating CI simulator '${name}' (${model}) on ${runtime_id}." >&2
    err=$(mktemp "${TMPDIR:-/tmp}/cisim-create.XXXXXX")
    udid=$(xcrun simctl create "${name}" "${device_type}" "${runtime_id}" 2>"${err}") || rc=$?
    # Anything but a bare UUID (simctl prints its error text on stdout too) fails here, so it never
    # reaches xcodebuild as a destination.
    if [ "${rc}" -ne 0 ] || ! printf '%s' "${udid}" | grep -Eqix '[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}'; then
      echo "::error::Could not create the CI simulator ${name} (${model}) on ${runtime_id} (exit ${rc}): $(tr '\n' ' ' < "${err}") ${udid}" >&2
      rm -f "${err}"
      exit 1
    fi
    rm -f "${err}"
  fi
  if [ -z "${udid}" ]; then
    echo "::error::Could not resolve or create the CI simulator ${name}." >&2
    exit 1
  fi

  case "${udid}" in
    "${DEFAULT_GUI_SIM_PREFIX}"*)
      echo "::error::Refusing to use the default GUI simulator ${udid} for CI." >&2
      exit 1
      ;;
  esac

  xcrun simctl shutdown "${udid}" 2>/dev/null || true
  echo "Erasing CI simulator ${name} (${udid})." >&2
  xcrun simctl erase "${udid}" 2>/dev/null || true
  echo "Booting CI simulator ${name} (${udid})." >&2
  # Boot and bootstatus share one bound (macOS has no `timeout`): a wedged boot inside the locked
  # step would otherwise hold the host build lock for the whole step. bootstatus is exec'd so the
  # alarm lands on it; stdout goes to /dev/null so a leftover child never holds the caller's
  # `$(... | tail -n1)` pipe open. SIGALRM gives 142; any other failure stays tolerated as before.
  local boot_limit="${CI_SIM_BOOT_TIMEOUT:-180}"
  rc=0
  perl -e 'alarm shift; exec @ARGV' "${boot_limit}" \
    bash -c 'xcrun simctl boot "$1" >/dev/null 2>&1; exec xcrun simctl bootstatus "$1" -b' _ "${udid}" \
    >/dev/null 2>&1 || rc=$?
  if [ "${rc}" -eq 142 ]; then
    echo "::error::CI simulator ${name} (${udid}) did not boot within ${boot_limit} seconds; failing so the job releases the build lock." >&2
    exit 1
  fi
  echo "Simulator ready: ${name} (${udid})" >&2
  echo "${udid}"
}

case "${1:-}" in
  reap)    reap ;;
  preboot) shift; preboot "$@" ;;
  *)
    echo "usage: ci-sim.sh {reap|preboot <device model>}" >&2
    exit 2
    ;;
esac
