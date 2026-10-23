# Sourced by the reusable workflow openspec-archive.yml (Frazzled-Productions/.github).
# Defines LOG (append command output to it) and fail <what> <why>: prints the error, opens an issue labelled "openspec" titled
# "OpenSpec archive failed: <what>" with the log (or comments on the open one), and exits 1.
# Needs GH_TOKEN, GITHUB_REPOSITORY and RUN_URL; BASE names the base branch (default main).
LOG=$(mktemp)

fail() {
  local what=$1 why=$2 title="OpenSpec archive failed: $1" body existing
  echo "::error::$why"
  # shellcheck disable=SC2016 # the backticks are Markdown, not command substitution
  body=$(printf '%s\n\n%s\n\nRun: %s\n\n<details><summary>Output</summary>\n\n```\n%s\n```\n</details>\n\n%s\n' \
    "The OpenSpec archive bot could not archive \`$what\` after it merged to ${BASE:-main}." "$why" "$RUN_URL" \
    "$(grep -v '^✓ ' "$LOG" | tail -c 60000)" \
    'Fix it on a branch (AGENTS.md in this repository, section "OpenSpec": usually the delta needs a "## Purpose" for a new capability, or a MODIFIED title no longer matches main), merge the fix, and the bot archives on that merge. Use "Run workflow" on the OpenSpec archive workflow to retry without a change.')
  gh label create openspec --color 0E8A16 --description "OpenSpec specs and the archive bot" >/dev/null 2>&1 || true
  # The title is passed to jq as data (--arg), never spliced into the filter.
  existing=$(gh issue list --state open --label openspec --limit 100 --json number,title \
    | jq -r --arg t "$title" '.[] | select(.title == $t) | .number' | head -1)
  if [ -n "$existing" ]; then gh issue comment "$existing" --body "$body"
  else gh issue create --title "$title" --label openspec --body "$body"; fi
  exit 1
}
