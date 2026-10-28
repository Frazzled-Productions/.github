#!/usr/bin/env bash
# with-build-lock.test.sh: Xcode steps run under the host build lock, and a missing lock script warns
# and runs the command anyway (ops #345, light-runner-shared-ci design D5). Never takes the real lock:
# BUILD_LOCK_SCRIPT points at a missing file or a stub.

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${WITH_BUILD_LOCK_SCRIPT:-$HERE/../with-build-lock.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL: %s\n' "$1"; }

T="$(mktemp -d "${TMPDIR:-/tmp}/withlock.XXXXXX")"
trap 'rm -rf "$T"' EXIT

echo "with-build-lock.sh against: $SCRIPT"

# Lock script missing: warning, command runs, its exit code is kept.
out=$(BUILD_LOCK_SCRIPT="$T/missing/build-lock.sh" bash "$SCRIPT" --label "roast-conductor CI" -- \
  bash -c 'echo ran > "$1"; exit 0' _ "$T/ran" 2>&1)
rc=$?
if [ "$rc" -eq 0 ] && [ -f "$T/ran" ]; then ok "lock script missing: the command runs and the step passes"
else bad "lock script missing: rc $rc, ran $( [ -f "$T/ran" ] && echo yes || echo no)"; fi
if printf '%s\n' "$out" | grep -q '^::warning::'; then ok "lock script missing: prints ::warning::"
else bad "no ::warning:: printed: $out"; fi
BUILD_LOCK_SCRIPT="$T/missing/build-lock.sh" bash "$SCRIPT" --label x -- bash -c 'exit 7' >/dev/null 2>&1
rc=$?
if [ "$rc" -eq 7 ]; then ok "lock script missing: the command's exit code is kept"; else bad "exit code $rc, want 7"; fi

# Lock script present: called as `run --label <label> -- <cmd...>`, arguments intact.
cat > "$T/build-lock.sh" <<STUB
#!/usr/bin/env bash
printf '%s\n' "\$@" > "$T/lock.args"
while [ "\$1" != "--" ]; do shift; done
shift
"\$@"
STUB
chmod +x "$T/build-lock.sh"
BUILD_LOCK_SCRIPT="$T/build-lock.sh" bash "$SCRIPT" --label "roast-conductor CI" -- \
  printf '%s\n' "two words" "-flag" > "$T/cmd.out" 2>&1
rc=$?
want=$'run\n--label\nroast-conductor CI\n--\nprintf\n%s\\n\ntwo words\n-flag'
if [ "$rc" -eq 0 ] && [ "$(cat "$T/lock.args" 2>/dev/null)" = "$want" ]; then
  ok "lock script present: called as run --label <label> -- <cmd>"
else bad "lock args: $(tr '\n' '|' < "$T/lock.args" 2>/dev/null)"; fi
if [ "$(cat "$T/cmd.out")" = $'two words\n-flag' ]; then ok "the command runs through the lock with its arguments"
else bad "command output: $(cat "$T/cmd.out")"; fi

# Present but not executable: treated as missing.
chmod -x "$T/build-lock.sh"; rm -f "$T/lock.args" "$T/ran"
out=$(BUILD_LOCK_SCRIPT="$T/build-lock.sh" bash "$SCRIPT" --label x -- bash -c 'echo ran > "$1"' _ "$T/ran" 2>&1)
if [ -f "$T/ran" ] && [ ! -f "$T/lock.args" ] && printf '%s\n' "$out" | grep -q '^::warning::'; then
  ok "lock script not executable: warns and runs the command unlocked"
else bad "not executable: $out"; fi

echo
if [ "$FAIL" -ne 0 ]; then echo "$PASS passed, $FAIL FAILED"; exit 1; fi
echo "$PASS passed"
