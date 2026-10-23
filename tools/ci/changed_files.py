#!/usr/bin/env python3
"""Decide from git, never from anything a PR author sets, whether a change only touches docs.

Shipped from Frazzled-Productions/.github and run by its reusable workflows against the caller's
checkout (the current directory), never from the caller's own tree.

  changed_files.py docs <range>        exit 0 if the range is docs-only (CI's fast path), else 1
  changed_files.py openspec <range>    exit 0 if the range only touches openspec/, else 1
  changed_files.py openspec-worktree   exit 0 if the uncommitted changes (untracked files too) only
                                       touch openspec/, else 1

<range> is anything `git diff` takes, e.g. base...head or before..after. Entries come from
`git diff --raw --no-renames -z`, so a rename shows as a deletion plus an addition and both paths are
judged. Every entry must be a plain file (mode 100644, so no symlinks, executables or submodules)
that is added or modified; a deletion is allowed only under openspec/ (archiving deletes a change's
delta files). An empty change is never docs-only.

Docs paths: anything under openspec/, and Markdown only in places no build reads: *.md at the repo
root, docs/**/*.md and .claude/**/*.md. Markdown anywhere else (an app's source folders, its engine
package, tools/, Config/) needs the full build.
Exit 2 when git fails, which CI treats as "run the full build".
"""
import os
import pathlib
import re
import stat
import subprocess
import sys

# \Z, not $: "$" would also match before a trailing newline in a path. re.S lets "." span one.
DOCS_RE = re.compile(r"\Aopenspec/|\A[^/]+\.md\Z|\Adocs/.+\.md\Z|\A\.claude/.+\.md\Z", re.S)
OPENSPEC_RE = re.compile(r"\Aopenspec/")
PLAIN = "100644"
NONE = "000000"


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout.decode("utf-8", "surrogateescape")


def parse_raw(out):
    """Parse `git diff --raw -z` into (status, old mode, new mode, path) tuples."""
    tokens = out.split("\0")
    entries = []
    i = 0
    while i < len(tokens) and tokens[i]:
        meta = tokens[i].lstrip(":").split()
        old_mode, new_mode, status = meta[0], meta[1], meta[4]
        entries.append((status[0], old_mode, new_mode, tokens[i + 1]))
        i += 2
    return entries


def diff_entries(rev_range, cwd=None):
    return parse_raw(_git(["diff", "--raw", "--no-renames", "-z", rev_range], cwd))


def worktree_entries(cwd=None):
    entries = parse_raw(_git(["diff", "--raw", "--no-renames", "-z", "HEAD"], cwd))
    for path in filter(None, _git(["ls-files", "--others", "--exclude-standard", "-z"], cwd).split("\0")):
        st = os.lstat(os.path.join(cwd or ".", path))
        if stat.S_ISLNK(st.st_mode):
            mode = "120000"
        elif stat.S_ISREG(st.st_mode):
            mode = "100755" if st.st_mode & 0o111 else PLAIN
        else:
            mode = "other"
        entries.append(("A", NONE, mode, path))
    return entries


def check(entries, rule):
    """Return (ok, reasons). rule is "docs" or "openspec"."""
    allowed = DOCS_RE if rule == "docs" else OPENSPEC_RE
    reasons = []
    if not entries:
        reasons.append("no changed files")
    for status, old, new, path in entries:
        shown = repr(path) if "\n" in path else path
        if not allowed.search(path):
            reasons.append(f"{shown}: not an allowed {rule} path")
        if status == "A":
            if new != PLAIN:
                reasons.append(f"{shown}: added with mode {new}, not a plain file")
        elif status == "M":
            if old != PLAIN or new != PLAIN:
                reasons.append(f"{shown}: mode {old} -> {new}, not a plain file")
        elif status == "D":
            if not OPENSPEC_RE.search(path):
                reasons.append(f"{shown}: deleted outside openspec/")
            elif old != PLAIN:
                reasons.append(f"{shown}: deleted with mode {old}, not a plain file")
        else:
            reasons.append(f"{shown}: status {status} (only added, modified, or deleted under openspec/)")
    return not reasons, reasons


def symlinks_under(root):
    """Every symlink (file or folder) under root, without following any."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = pathlib.Path(dirpath, name)
            if p.is_symlink():
                found.append(p)
    return sorted(found)


def main(argv):
    try:
        if len(argv) == 2 and argv[0] in ("docs", "openspec"):
            entries, rule = diff_entries(argv[1]), argv[0]
        elif argv == ["openspec-worktree"]:
            entries, rule = worktree_entries(), "openspec"
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (subprocess.CalledProcessError, OSError, IndexError) as e:
        print(f"Could not read the changed files: {e}", file=sys.stderr)
        return 2
    ok, reasons = check(entries, rule)
    for status, _, new, path in entries:
        print(f"  {status} {new} {path!r}" if "\n" in path else f"  {status} {new} {path}")
    for r in reasons:
        print(f"Not {rule}-only: {r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
