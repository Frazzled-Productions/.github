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

risky() { # risky <label> <want exit> <repo> <file> [extra]
  printf '%s\n' "$4" | python3 tools/review/risky_paths.py tools/review/risky-paths.txt "$3" "${5:-}" > /dev/null
  local got=$?
  if [ "$got" = "$2" ]; then pass=$((pass + 1)); echo "ok   $1"; else fail=$((fail + 1)); echo "FAIL $1 (exit $got)"; fi
}
risky "a repo path through risky-paths-extra" 0 loop-year LoopYear/Unlock/Gate.swift 'LoopYear/Unlock/**'
risky "a workflow anywhere" 0 website .github/workflows/ci.yml
risky "docs are not risky" 1 ops docs/readme.md

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
