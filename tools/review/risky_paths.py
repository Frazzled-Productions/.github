"""The risky-paths list (OpenSpec ci-review): parses `standards/review-tiers.md` and matches changed files.

The list is the ```risky-paths fenced block, one "<repo or *> <glob>" per line; a file with no fence is read
whole, so the reviewer's plain copy parses too. The same code lives in ops as scripts/watcher/risky_paths.py:
the reviewer runs in other repos and cannot read ops, which is private. Change both together.

Usage: risky_paths.py <list file> <repo> [extra globs, one per line] < changed files. Prints the risky files;
exit 0 when there are any, 1 when none.
"""
import re
import sys

FENCE = re.compile(r"^```risky-paths\n(.*?)^```", re.M | re.S)


def parse(text):
    """[(repo or "*", glob)] from the fenced block, or from the whole text when it has none."""
    fenced = FENCE.search(text)
    rules = []
    for line in (fenced.group(1) if fenced else text).splitlines():
        parts = line.split()
        if len(parts) == 2 and not line.startswith("#"):
            rules.append((parts[0], parts[1]))
    return rules


def _regex(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z")


def risky(repo, files, rules, extra=""):
    """The files that match a rule for repo or for every repo, or an extra glob."""
    globs = [g for r, g in rules if r in ("*", repo)] + extra.split()
    res = [_regex(g) for g in globs]
    return [f for f in files if any(r.match(f) for r in res)]


def main(argv):
    with open(argv[1]) as f:
        rules = parse(f.read())
    found = risky(argv[2], sys.stdin.read().split("\n"), rules, argv[3] if len(argv) > 3 else "")
    print("\n".join(found))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
