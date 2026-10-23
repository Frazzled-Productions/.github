"""A fake `gh` for the OpenSpec tools tests (not a test itself).

install(tmp) writes an executable `gh` into tmp/bin that records each call's arguments (one JSON
list per line in tmp/gh-calls.jsonl) and answers from environment variables:
  FAKE_GH_ISSUES  the JSON printed for `gh issue list` (default "[]")
  FAKE_GH_FAIL    calls whose joined arguments contain this text exit 1
`gh issue create` prints a new issue URL, `gh issue comment N` a comment URL; the rest print nothing.
"""
import json
import os
import pathlib
import sys

ISSUE_URL = "https://github.com/Frazzled-Productions/example/issues/999"

SCRIPT = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
fail = os.environ.get("FAKE_GH_FAIL")
if fail and fail in " ".join(args):
    print("HTTP 403: refused by the fake gh", file=sys.stderr)
    sys.exit(1)
if args[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_GH_ISSUES", "[]"))
elif args[:2] == ["issue", "create"]:
    print("ISSUE_URL")
elif args[:2] == ["issue", "comment"]:
    print("https://github.com/Frazzled-Productions/example/issues/" + args[2] + "#issuecomment-1")
'''.replace("ISSUE_URL", ISSUE_URL)


def install(tmp):
    """Install the fake gh under tmp; return the environment to run the code under test with."""
    tmp = pathlib.Path(tmp)
    (tmp / "bin").mkdir(exist_ok=True)
    gh = tmp / "bin" / "gh"
    gh.write_text(SCRIPT.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1), encoding="utf-8")
    gh.chmod(0o755)
    return {**os.environ, "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_CALLS": str(tmp / "gh-calls.jsonl"), "GH_TOKEN": "fake"}


def calls(tmp):
    """Every recorded gh call, in order, as argument lists."""
    path = pathlib.Path(tmp) / "gh-calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def option(call, name):
    """The value after `name` in one recorded call, or None."""
    return call[call.index(name) + 1] if name in call else None
