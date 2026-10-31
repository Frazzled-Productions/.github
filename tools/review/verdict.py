"""The CI review's verdict step (OpenSpec ci-review in ops, spec pr-review).

`decide` turns the review's structured output into the "CI review" commit status, labels and the sticky
comment; it is pure. `apply` reads the PR and applies the result through gh, the status first: with no status
the watcher would settle the PR as skipped, which could pass a P1. tools/tests/ci-review-verdict.sh covers both.

A review that cannot run never clears a failure already on that commit, or a "Review reply:" comment during
an outage would pass a P1. The rounds are counted in the marker of this job's own sticky comment, so a re-review of one commit (a "Review reply:"
comment) counts too. The third review that reports a P1 escalates; on a bot PR the first does. A token error
says so in the status description, which is what the stall watcher reads to open the one ops issue: this
job's GITHUB_TOKEN cannot write to ops.

Usage: verdict.py decide --output FILE --rounds N --bot 0|1 --risky 0|1 --token-error 0|1 --failed 0|1
       verdict.py apply  --output FILE --pr N --head SHA --risky 0|1 --token-error 0|1
       verdict.py token-error --output EXECUTION_FILE   prints 1 or 0
"""
import argparse
import json
import os
import re
import subprocess
import sys

CONTEXT = "CI review"
MARKER = "<!-- ci-review rounds={} -->"
MARKER_RE = re.compile(r"<!-- ci-review rounds=(\d+) -->")
SKIPPED = "review-skipped"
ESCALATE = "needs-fraser"
ROUNDS = 3
BOT = "github-actions[bot]"
REPLY = "Review reply:"
# A real authentication failure, never a bare 401: the file also holds the diff and token counts.
TOKEN_ERROR = re.compile(r"authentication_error|invalid bearer token|oauth token has expired|invalid api key"
                         r"|api error: 401", re.I)


def _findings(review):
    rows = [f"- **{f.get('severity')}** `{f.get('file')}:{f.get('line')}`: {f.get('summary')}"
            + (f" (against {f['against']})" if f.get("against") else "") for f in review.get("findings") or []]
    return "\n".join(rows) or "No findings."


def decide(review, rounds, bot, risky, token_error, failed=False, reply=""):
    """review: the structured output, or None when no review ran. failed: the commit already has a failing
    result. reply: the agent's newest "Review reply:". Returns state, description, labels, body, rounds."""
    if review is None and failed:
        return dict(state="failure", description="P1 stands, re-review skipped", labels=[SKIPPED], rounds=rounds,
                    body="CI review could not run again, so the earlier P1 stands on this commit.")
    if review is None:
        why = "token missing or expired" if token_error else "the review could not run"
        state = "failure" if risky else "success"
        desc = "review skipped" + (", risky path" if risky else "") + (": token missing or expired" if token_error else "")
        body = (f"CI review skipped ({why}). "
                + ("This PR touches a risky path, so it waits for a later review." if risky else "This PR may merge."))
        return dict(state=state, description=desc, labels=[SKIPPED], body=body, rounds=rounds)
    p1 = sum(f.get("severity") == "P1" for f in review.get("findings") or [])
    compared = review.get("change_compared") or "none found"
    text = f"Compared with OpenSpec change: {compared}.\n\n{_findings(review)}"
    if p1 == 0:
        return dict(state="success", description="no P1 findings", labels=[], body=f"CI review passed. {text}",
                    rounds=rounds)
    rounds += 1
    labels, note = [], ("Fix the finding, or comment starting \"Review reply:\" with why it is wrong; "
                        "either runs the review again.")
    if bot or rounds >= ROUNDS:
        labels, note = [ESCALATE], ("CI review escalated to Fraser: "
                                    + ("a bot PR with a P1 stays open." if bot else
                                       f"review {rounds} still reports a P1. The finding is above; the agent's "
                                       "last reply was: " + (reply[:500] or "none.")))
    return dict(state="failure", description=f"{p1} P1 finding{'' if p1 == 1 else 's'}", labels=labels,
                body=f"CI review failed. {text}\n\n{note}", rounds=rounds)


def load(path):
    """The structured output, or None when the file is missing, empty or not a verdict."""
    try:
        with open(path) as f:
            text = f.read().strip()
        data = json.loads(text) if text else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "findings" in data else None


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def apply(args):
    repo, pr = os.environ["GITHUB_REPOSITORY"], args.pr
    info = json.loads(gh("pr", "view", pr, "-R", repo, "--json", "author,headRefOid"))
    head = args.head or info["headRefOid"]  # the commit reviewed, not whatever is newest now
    lines = gh("api", "--paginate", "--jq", ".[]", f"repos/{repo}/issues/{pr}/comments?per_page=100").splitlines()
    comments = [json.loads(line) for line in lines if line.strip()]
    mine = next((c for c in comments if c["user"]["login"] == BOT and MARKER_RE.search(c["body"])), None)
    rounds = int(MARKER_RE.search(mine["body"]).group(1)) if mine else 0
    replies = [c["body"] for c in comments if c["body"].startswith(REPLY)]
    statuses = json.loads(gh("api", f"repos/{repo}/commits/{head}/status?per_page=100"))["statuses"]
    failed = any(s["context"] == CONTEXT and s["state"] == "failure" for s in statuses)
    out = decide(load(args.output), rounds, bool(info["author"].get("is_bot")), args.risky == 1, args.token_error == 1,
                 failed, replies[-1] if replies else "")
    gh("api", "-X", "POST", f"repos/{repo}/statuses/{head}", "-f", f"state={out['state']}",
       "-f", f"context={CONTEXT}", "-f", f"description={out['description']}")
    print(out["description"])
    body = f"{MARKER.format(out['rounds'])}\n{out['body']}"
    if mine:
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{mine['id']}", "-f", f"body={body}")
    else:
        gh("api", "-X", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}")
    for label in out["labels"]:
        gh("api", "-X", "POST", f"repos/{repo}/issues/{pr}/labels", "-f", f"labels[]={label}")


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("decide", "apply", "token-error"))
    p.add_argument("--output", required=True)
    p.add_argument("--pr", default="")
    p.add_argument("--head", default="")
    p.add_argument("--failed", type=int, default=0)
    p.add_argument("--rounds", type=int, default=0)
    p.add_argument("--bot", type=int, default=0)
    p.add_argument("--risky", type=int, default=0)
    p.add_argument("--token-error", type=int, default=0)
    args = p.parse_args(argv)
    if args.command == "apply":
        apply(args)
    elif args.command == "token-error":
        try:
            with open(args.output) as f:
                print(1 if TOKEN_ERROR.search(f.read()) else 0)
        except OSError:
            print(0)
    else:
        print(json.dumps(decide(load(args.output), args.rounds, args.bot == 1, args.risky == 1, args.token_error == 1,
                                args.failed == 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
