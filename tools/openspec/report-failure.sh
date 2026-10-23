# Sourced by the reusable workflow openspec-archive.yml (Frazzled-Productions/.github).
# Defines LOG (append command output to it) and fail <what> <why>: opens an issue labelled "openspec" titled
# "OpenSpec archive failed: <what>" (or comments on the open one), starting with the real error lines
# (tools/openspec/failure_lines.py), then ends the step's output with the "Why the OpenSpec archive failed"
# block (the reason and those lines as ::error:: annotations, the issue link) and exits 1. The block is
# last so the real error is the end of the log, never the step's echoed script (roast-conductor #186).
# Needs GH_TOKEN, GITHUB_REPOSITORY, RUN_URL and python3; BASE names the base branch (default main).
LOG=$(mktemp)
OPENSPEC_TOOLS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

fail() {
  local what=$1 why=$2 title="OpenSpec archive failed: $1" body existing errors link
  errors=$(python3 "$OPENSPEC_TOOLS_DIR/failure_lines.py" text "$LOG")
  # shellcheck disable=SC2016 # the backticks are Markdown, not command substitution
  body=$(printf '%s\n\n## Why it failed\n\n%s\n\n````\n%s\n````\n\nRun: %s\n\n<details><summary>Full output</summary>\n\n```\n%s\n```\n</details>\n\n%s\n' \
    "The OpenSpec archive bot could not archive \`$what\` after it merged to ${BASE:-main}." "$why" "$errors" "$RUN_URL" \
    "$(grep -v '^✓ ' "$LOG" | tail -c 60000)" \
    'Common causes: an unticked task in the change'"'"'s tasks.md (tick it if done, else move it to an issue and tick it as moved); a new capability'"'"'s delta with no "## Purpose"; a MODIFIED requirement whose title no longer matches main. Fix it on a branch (AGENTS.md in this repository, section "OpenSpec") and merge the fix: the bot archives on that merge and closes this issue. Use "Run workflow" on the OpenSpec archive workflow to retry without a change.')
  gh label create openspec --color 0E8A16 --description "OpenSpec specs and the archive bot" >/dev/null 2>&1 || true
  # The title is passed to jq as data (--arg), never spliced into the filter.
  existing=$(gh issue list --state open --label openspec --limit 100 --json number,title \
    | jq -r --arg t "$title" '.[] | select(.title == $t) | .number' | head -1)
  if [ -n "$existing" ]; then link=$(gh issue comment "$existing" --body "$body" 2>&1)
  else link=$(gh issue create --title "$title" --label openspec --body "$body" 2>&1); fi
  # shellcheck disable=SC2181 # the status of the assignment just above
  if [ $? -ne 0 ] || [ -z "$link" ]; then
    link="Could not open or comment on the issue: $(tr '\n' ' ' <<< "$link")"
  else
    link=$(tail -n 1 <<< "$link") # gh prints the URL last
  fi
  echo
  echo "==== Why the OpenSpec archive failed ===="
  python3 "$OPENSPEC_TOOLS_DIR/failure_lines.py" annotations "$LOG" "$why"
  echo "Issue: $link"
  echo "The script printed at the start of each step is its source, not output."
  exit 1
}
