#!/usr/bin/env bash
# Feeds sample review output to the CI review's verdict step and the risky-paths helper (OpenSpec
# ci-review in ops, tasks 1.2 and 1.3). No gh, no Claude. Run from the repo root.
set -uo pipefail
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
pass=0; fail=0
clean='{"findings":[{"severity":"P2","file":"a.py","line":1,"summary":"s"}],"change_compared":"c","p1_count":0}'
p1='{"findings":[{"severity":"P1","file":"a.py","line":1,"summary":"s","against":"c"}],"change_compared":"c","p1_count":1}'

check() { # check <label> <expected JSON subset, jq boolean> <review JSON or ""> <verdict.py flags...>
  local label=$1 want=$2 review=$3; shift 3
  printf '%s' "$review" > "$tmp/out.json"
  if python3 tools/review/verdict.py decide --output "$tmp/out.json" "$@" | jq -e "$want" > /dev/null; then
    pass=$((pass + 1)); echo "ok   $label"
  else
    fail=$((fail + 1)); echo "FAIL $label"
  fi
}

check "0 P1 passes" '.state == "success" and .labels == []' "$clean"
check "a P2 never fails" '.state == "success"' "$clean" --rounds 2
check "1 P1 fails with no label" '.state == "failure" and .labels == [] and .rounds == 1' "$p1"
check "second failing review, no label" '.state == "failure" and .labels == [] and .rounds == 2' "$p1" --rounds 1
check "third failing review adds needs-fraser" '.state == "failure" and .labels == ["needs-fraser"] and (.body | contains("CI review escalated"))' "$p1" --rounds 2
check "bot PR P1 adds needs-fraser at once" '.state == "failure" and .labels == ["needs-fraser"]' "$p1" --bot 1
check "skipped plus risky fails" '.state == "failure" and .labels == ["review-skipped"]' "" --risky 1
check "skipped plus ordinary passes" '.state == "success" and .description == "review skipped" and .labels == ["review-skipped"]' ""
check "token error is named for the watcher" '.state == "success" and (.description | contains("token missing or expired"))' "" --token-error 1
check "not a verdict counts as skipped" '.labels == ["review-skipped"]' '{"oops":1}'
check "no change found is reported" '.body | contains("none found")' '{"findings":[],"p1_count":0}'

# apply: real verdict.py against a fake gh on PATH, which logs its writes
mkdir -p "$tmp/bin"
cat > "$tmp/bin/gh" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/calls"
case "$*" in
  "pr view"*) echo "{\"author\":{\"is_bot\":${FAKE_BOT:-false}},\"headRefOid\":\"newhead\"}" ;;
  *"/comments?per_page=100"*) [ -n "${FAKE_READ_FAIL:-}" ] && exit 1; cat "$FAKE_DIR/comments.jsonl" ;;
  *"/status?per_page=100"*) cat "$FAKE_DIR/status.json" ;;
  *"$FAKE_FAIL"*) [ -n "$FAKE_FAIL" ] && exit 1 ;;
esac
exit 0
FAKE
chmod +x "$tmp/bin/gh"
applied() { # applied <label> <grep pattern in calls, ! to negate> ; review in $tmp/out.json
  local label=$1; shift
  local ok=1
  for pat in "$@"; do
    if [[ $pat == !* ]]; then grep -q -- "${pat#!}" "$tmp/calls" && ok=0
    else grep -q -- "$pat" "$tmp/calls" || ok=0; fi
  done
  if [ "$ok" = 1 ]; then pass=$((pass + 1)); echo "ok   $label"; else fail=$((fail + 1)); echo "FAIL $label"; cat "$tmp/calls"; fi
}
run_apply() { # run_apply <verdict JSON or ""> <comments jsonl> <head status JSON> [flags]
  printf '%s' "$1" > "$tmp/out.json"; printf '%s' "$2" > "$tmp/comments.jsonl"; printf '%s' "$3" > "$tmp/status.json"; shift 3
  : > "$tmp/calls"
  PATH="$tmp/bin:$PATH" FAKE_DIR="$tmp" GITHUB_REPOSITORY=o/r python3 tools/review/verdict.py apply --output "$tmp/out.json" --pr 7 --head reviewed "$@" 2>/dev/null
}
bot='"user":{"login":"github-actions[bot]"}'
sticky2="{\"id\":5,$bot,\"body\":\"<!-- ci-review rounds=2 -->\\nold\"}"
none='{"statuses":[]}'
run_apply "$p1" "$sticky2" "$none"
applied "third P1 from the sticky count labels and patches" 'labels\[\]=needs-fraser' 'PATCH repos/o/r/issues/comments/5' 'statuses/reviewed' 'state=failure' '!newhead'
spoof='{"id":6,"user":{"login":"someone"},"body":"<!-- ci-review rounds=2 -->"}'
run_apply "$p1" "$spoof" "$none"
applied "a marker from anyone else is ignored" '!needs-fraser' '!PATCH' 'rounds=1'
reply="{\"id\":8,\"author_association\":\"MEMBER\",\"user\":{\"login\":\"a\"},\"body\":\"Review reply: it is a false alarm\"}"
run_apply "$p1" "$sticky2
$reply" "$none"
applied "escalation carries the agent's reply" 'it is a false alarm'
outsider='{"id":9,"author_association":"NONE","user":{"login":"x"},"body":"Review reply: outsider text"}'
run_apply "$p1" "$sticky2
$outsider" "$none"
applied "a reply from outside the repo is not quoted" '!outsider text'
p1status='{"statuses":[{"context":"CI review","state":"failure","description":"1 P1 finding"}]}'
stickyp1="{\"id\":5,$bot,\"body\":\"<!-- ci-review rounds=1 -->\\nCI review failed. the finding text\"}"
run_apply "" "$stickyp1" "$p1status"
applied "a skipped re-review never clears a P1 and keeps the finding" 'state=failure' 'review-skipped' 'the finding text' 'description=P1 stands'
run_apply "" "$stickyp1" "$p1status" --token-error 1
applied "a skipped re-review still names a token error" 'state=failure' 'token missing or expired'
run_apply "" "" '{"statuses":[{"context":"CI review","state":"failure","description":"review skipped, risky path"}]}' --risky 1
applied "a risky skip is not called a P1" 'state=failure' '!P1 stands'
: > "$tmp/calls"; printf '%s' "$p1" > "$tmp/out.json"; printf '%s' "$none" > "$tmp/status.json"
PATH="$tmp/bin:$PATH" FAKE_DIR="$tmp" FAKE_READ_FAIL=1 GITHUB_REPOSITORY=o/r python3 tools/review/verdict.py apply --output "$tmp/out.json" --pr 7 --head reviewed 2>/dev/null
applied "a failed read still posts a failure" 'statuses/reviewed' 'state=failure'
: > "$tmp/calls"; printf '%s' "$p1" > "$tmp/out.json"; printf '' > "$tmp/comments.jsonl"; printf '%s' "$none" > "$tmp/status.json"
PATH="$tmp/bin:$PATH" FAKE_DIR="$tmp" FAKE_FAIL=/comments GITHUB_REPOSITORY=o/r python3 tools/review/verdict.py apply --output "$tmp/out.json" --pr 7 --head reviewed 2>/dev/null
applied "a failed comment write still posts the status" 'state=failure'

tok() { # tok <label> <want 0|1> <text>
  printf '%s' "$3" > "$tmp/exec.json"
  local got; got=$(python3 tools/review/verdict.py token-error --output "$tmp/exec.json")
  if [ "$got" = "$2" ]; then pass=$((pass + 1)); echo "ok   $1"; else fail=$((fail + 1)); echo "FAIL $1 (got $got)"; fi
}
tok "an auth error is a token error" 1 '{"type":"result","is_error":true,"result":"API Error: 401 authentication_error"}'
tok "a stray 401 is not" 0 '{"result":"line 1401 of 2401, tokens 40100"}'

risky() { # risky <label> <want exit> <repo> <file> [extra]
  printf '%s\n' "$4" | python3 tools/review/risky_paths.py tools/review/risky-paths.txt "$3" "${5:-}" > /dev/null
  local got=$?
  if [ "$got" = "$2" ]; then pass=$((pass + 1)); echo "ok   $1"; else fail=$((fail + 1)); echo "FAIL $1 (exit $got)"; fi
}
printf 'x\n' | python3 tools/review/risky_paths.py "$tmp/no-such-file" r > /dev/null 2>&1
got=$?; if [ "$got" != 0 ] && [ "$got" != 3 ]; then pass=$((pass + 1)); echo "ok   a helper crash is neither answer"; else fail=$((fail + 1)); echo "FAIL helper crash gave $got"; fi
risky "a repo path through risky-paths-extra" 0 loop-year LoopYear/Unlock/Gate.swift 'LoopYear/Unlock/**'
risky "a workflow anywhere" 0 website .github/workflows/ci.yml
risky "docs are not risky" 3 ops docs/readme.md

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
