"""No AI-attribution trailer in a PR body or in the commits a change adds (ops #345, D7).

House style forbids any AI attribution on any artefact (ops standards). The pattern is koinori's
(tools/dev/check-house-style.sh, origin/qa 217b3f179), matched case-insensitively.

Run by em-dash-check.yml. Environment:
  EVENT    github.event_name
  PR_BODY  the pull request body from the event payload (pull_request only)
  BASE     the PR base SHA, or the push's `before`
  HEAD     the PR head SHA, or the push's `after`
On pull_request it checks the body and the commits merge-base(BASE, HEAD)..HEAD; on push the commits
BASE..HEAD (none for a new branch, whose `before` is all zeros). Any other event has nothing to check.
Exits 1 naming each line or commit. Tests: tools/ci/test_trailer.py.
"""
import os
import re
import subprocess
import sys

PATTERN = re.compile(
    r"generated with .{0,3}claude code|co-authored-by:.*claude|claude\.ai/code|claude\.com/claude-code",
    re.IGNORECASE)


def body_hits(text):
    """[(line number, line)] for each line of `text` that carries the trailer."""
    return [(n, line) for n, line in enumerate(text.splitlines(), 1) if PATTERN.search(line)]


def git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def commit_hits(base, head, cwd=None):
    """[(sha, subject, matching line)] for each commit in base..head whose message carries the trailer."""
    out = git(["log", "--format=%H%x00%B%x01", f"{base}..{head}"], cwd=cwd)
    hits = []
    for record in out.split("\x01"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, message = record.partition("\x00")
        lines = body_hits(message)
        if lines:
            hits.append((sha, message.splitlines()[0] if message else "", lines[0][1]))
    return hits


def main():
    event = os.environ.get("EVENT", "")
    base, head = os.environ.get("BASE", ""), os.environ.get("HEAD", "")
    failed = False
    if event in ("pull_request", "pull_request_target"):
        for n, line in body_hits(os.environ.get("PR_BODY", "")):
            print(f"::error::AI-attribution trailer in the PR body, line {n}: {line.strip()}")
            failed = True
        base = git(["merge-base", base, head]).strip()
    elif event == "push":
        if not base or set(base) == {"0"}:
            print("New branch push: no earlier commit to compare with, so no commits to check.")
            base = ""
    else:
        print(f"Event {event} has no PR body or pushed commits to check.")
        base = ""
    if base:
        for sha, subject, line in commit_hits(base, head):
            print(f"::error::AI-attribution trailer in commit {sha[:7]} ({subject}): {line.strip()}")
            failed = True
    if failed:
        print("::error::House style forbids AI attribution on any artefact. Edit the PR body, or reword "
              "the commit that carries it.")
        return 1
    print("No AI-attribution trailer in the PR body or the added commits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
