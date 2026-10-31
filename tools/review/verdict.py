"""The CI review's verdict step (OpenSpec ci-review in ops, spec pr-review).

`decide` turns the review's structured output into the "CI review" commit status, labels and the sticky
comment; it is pure, and tools/tests/ci-review-verdict.sh feeds it samples. `main` reads the PR, applies the
result through gh, and always exits 0 unless gh fails: the status is the check, not this job's conclusion.

The rounds are counted in the sticky comment's marker, so a re-review of one commit (a "Review reply:"
comment) counts too. The third review that reports a P1 escalates; on a bot PR the first does. A token error
says so in the status description, which is what the stall watcher reads to open the one ops issue: this
job's GITHUB_TOKEN cannot write to ops.

Usage: verdict.py decide --output FILE --rounds N --bot 0|1 --risky 0|1 --token-error 0|1
       verdict.py apply  --output FILE --pr N --risky 0|1 --token-error 0|1
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


def _findings(review):
    rows = [f"- **{f.get('severity')}** `{f.get('file')}:{f.get('line')}`: {f.get('summary')}"
            + (f" (against {f['against']})" if f.get("against") else "") for f in review.get("findings") or []]
    return "\n".join(rows) or "No findings."


def decide(review, rounds, bot, risky, token_error):
    """review: the structured output, or None when no review ran. Returns state, description, labels, body,
    rounds."""
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
                                       "replies are in the comments."))
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
    comments = json.loads(gh("api", f"repos/{repo}/issues/{pr}/comments?per_page=100"))
    mine = next((c for c in comments if MARKER_RE.search(c["body"])), None)
    rounds = int(MARKER_RE.search(mine["body"]).group(1)) if mine else 0
    out = decide(load(args.output), rounds, bool(info["author"].get("is_bot")), args.risky == 1, args.token_error == 1)
    body = f"{MARKER.format(out['rounds'])}\n{out['body']}"
    if mine:
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{mine['id']}", "-f", f"body={body}")
    else:
        gh("api", "-X", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}")
    for label in out["labels"]:
        gh("api", "-X", "POST", f"repos/{repo}/issues/{pr}/labels", "-f", f"labels[]={label}")
    gh("api", "-X", "POST", f"repos/{repo}/statuses/{info['headRefOid']}", "-f", f"state={out['state']}",
       "-f", f"context={CONTEXT}", "-f", f"description={out['description']}")
    print(out["description"])


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("decide", "apply"))
    p.add_argument("--output", required=True)
    p.add_argument("--pr", default="")
    p.add_argument("--rounds", type=int, default=0)
    p.add_argument("--bot", type=int, default=0)
    p.add_argument("--risky", type=int, default=0)
    p.add_argument("--token-error", type=int, default=0)
    args = p.parse_args(argv)
    if args.command == "apply":
        apply(args)
    else:
        print(json.dumps(decide(load(args.output), args.rounds, args.bot == 1, args.risky == 1, args.token_error == 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
