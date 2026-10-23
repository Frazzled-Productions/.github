#!/usr/bin/env python3
"""Close the archive bot's own failure issues for the changes a successful run archived.

  close_resolved.py <owner/repo> <archive PR number> <run URL> [<change name>...]

Run by openspec-archive.yml at the end of a successful archive job (the archive PR is open, its held
checks approved and auto-merge on). Closes, as completed and with a comment linking the run and the
archive PR, each open issue that:
  - is labelled "openspec",
  - was opened by the bot (github-actions), and
  - is titled exactly "OpenSpec archive failed: <names>", where <names> is one change name, or several
    joined by ", ", and every one of them was archived by this run.
Every other issue stays open: other changes', a person's, and the bot's "all changes", "unexpected
change folder" and stuck-PR ("#N") issues. Titles are compared as data, never used in a command.

A failure to list, comment on or close an issue prints a ::warning:: and the script still exits 0:
the archive itself is done. Bad arguments exit 2.
"""
import json
import re
import subprocess
import sys

PREFIX = "OpenSpec archive failed: "
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BOT_LOGINS = {"app/github-actions", "github-actions[bot]", "github-actions"}


def gh(*args):
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def warn(message):
    print("::warning::" + message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"), flush=True)


def by_bot(issue):
    author = issue.get("author") or {}
    return author.get("login") in BOT_LOGINS and author.get("is_bot", True) is not False


def named_changes(title):
    """The change names an issue title is about, or None when it is not about changes only."""
    if not title.startswith(PREFIX):
        return None
    names = title[len(PREFIX):].split(", ")
    return names if names and all(NAME.match(n) for n in names) else None


def resolved(issues, archived):
    out = []
    for issue in issues:
        names = named_changes(issue.get("title", ""))
        if names and by_bot(issue) and set(names) <= archived:
            out.append((issue["number"], names))
    return sorted(out)


def main(argv):
    if len(argv) < 3 or not REPO.match(argv[0]) or not argv[1].isdigit() or not argv[2].startswith("https://"):
        print(__doc__, file=sys.stderr)
        return 2
    repo, pr, run_url, names = argv[0], argv[1], argv[2], argv[3:]
    archived = set()
    for name in names:
        if NAME.match(name):
            archived.add(name)
        else:
            warn(f"'{name}' is not a change name; no issue is closed for it.")
    if not archived:
        print("No change archived, so no failure issues to close.")
        return 0

    code, out = gh("issue", "list", "--repo", repo, "--state", "open", "--label", "openspec",
                   "--limit", "200", "--json", "number,title,author")
    try:
        issues = json.loads(out) if code == 0 else None
    except json.JSONDecodeError:
        issues = None
    if not isinstance(issues, list):
        warn(f"Could not list the open openspec issues, so none were closed: {out}")
        return 0

    found = resolved(issues, archived)
    if not found:
        print(f"No open failure issues to close for {', '.join(sorted(archived))}.")
        return 0
    for number, issue_names in found:
        changes = ", ".join(f"`{n}`" for n in issue_names)
        comment = (f"Fixed: run {run_url} archived {changes} and opened the archive PR #{pr}, which merges "
                   "once its required checks pass. Closing this issue (the archive bot does this when a "
                   "later run archives the change).")
        code, out = gh("issue", "close", str(number), "--repo", repo, "--reason", "completed", "--comment", comment)
        if code == 0:
            print(f"Closed #{number} ({', '.join(issue_names)}).")
        else:
            warn(f"Could not close #{number} ({', '.join(issue_names)}); close it by hand: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
