"""A fake `gh` for the OpenSpec tools tests (not a test itself).

install(tmp) writes an executable `gh` into tmp/bin that records each call's arguments (one JSON
list per line in tmp/gh-calls.jsonl) and answers from environment variables:
  FAKE_GH_ISSUES  the JSON printed for `gh issue list` (default "[]")
  FAKE_GH_FAIL    calls whose joined arguments contain this text exit 1
  FAKE_GH_CHATTER a line printed before the URL of `gh issue create` or `gh issue comment`
  FAKE_GH_API     a JSON object mapping a `gh api` path to the JSON it answers (a GET of a path not
                  in it exits 1 with HTTP 404); with `--jq '.[] | tojson'` a list answer is printed
                  one element per line, as gh prints it
`gh issue create` prints a new issue URL, `gh issue comment N` a comment URL; `gh api` with
`-X POST` or `-X PATCH` prints {}; the rest print nothing.
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
    if os.environ.get("FAKE_GH_CHATTER"):
        print(os.environ["FAKE_GH_CHATTER"], file=sys.stderr)
    print("ISSUE_URL")
elif args[:2] == ["issue", "comment"]:
    if os.environ.get("FAKE_GH_CHATTER"):
        print(os.environ["FAKE_GH_CHATTER"], file=sys.stderr)
    print("https://github.com/Frazzled-Productions/example/issues/" + args[2] + "#issuecomment-1")
elif args[:1] == ["api"]:
    method, jq, path, i = "GET", None, None, 1
    while i < len(args):
        if args[i] in ("-X", "--method"):
            method, i = args[i + 1].upper(), i + 2
        elif args[i] == "--jq":
            jq, i = args[i + 1], i + 2
        elif args[i] in ("-f", "-F", "--field", "--raw-field", "-H", "--header"):
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            path, i = path or args[i], i + 1
    if method != "GET":
        print("{}")
        sys.exit(0)
    answers = json.loads(os.environ.get("FAKE_GH_API", "{}"))
    if path not in answers:
        print("HTTP 404: Not Found (" + str(path) + ")", file=sys.stderr)
        sys.exit(1)
    answer = answers[path]
    if jq == ".[] | tojson" and isinstance(answer, list):
        for item in answer:
            print(json.dumps(item))
    else:
        print(json.dumps(answer))
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
