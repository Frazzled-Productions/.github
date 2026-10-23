#!/usr/bin/env python3
"""Approve the held pull_request runs on the archive bot's own PR, and nothing else.

  approve_runs.py <repo> <pr-number> <expected-head-sha> [--branch <archive branch>] [--base <base branch>]

--branch defaults to openspec-archive and --base to main (the reusable workflow
Frazzled-Productions/.github/.github/workflows/openspec-archive.yml passes its inputs).

GitHub holds the pull_request runs on a PR that github-actions[bot] opens ("action required") until
someone approves them. Owner decision 22 October 2026 (issue #168): the archive bot approves the held
runs on its own archive PR, so archiving needs no human step. It approves only when every guard holds:

  - the PR is open, authored by github-actions[bot] (type Bot), from the archive branch in this
    repository into the base branch in this repository (so never a fork);
  - the PR head is exactly the commit the bot has just pushed;
  - the PR's diff touches only plain files under openspec/ (tools/ci/changed_files.py, rule openspec);
  - each run approved is on that head commit, event pull_request, conclusion action_required,
    triggered by github-actions[bot], from this repository's archive branch.

It polls for up to ~90 seconds (GitHub creates the runs a few seconds after the PR or push), logs each
approval, and exits 1 if any guard fails or a held run is left unapproved.
"""
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ci"))
import changed_files  # noqa: E402

BOT = "github-actions[bot]"
BRANCH = "openspec-archive"
BASE = "main"


def gh_api(path):
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def gh_post(path):
    subprocess.run(["gh", "api", "-X", "POST", path], check=True, capture_output=True, text=True)


def pr_guards(pr, repo, expected_sha, branch=BRANCH, base_branch=BASE):
    """Return a list of reasons the PR may not have its runs approved (empty means it may)."""
    reasons = []
    if pr.get("state") != "open":
        reasons.append(f"PR is {pr.get('state')}, not open")
    user = pr.get("user") or {}
    if user.get("login") != BOT or user.get("type") != "Bot":
        reasons.append(f"PR author is {user.get('login')} ({user.get('type')}), not {BOT}")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if head.get("ref") != branch:
        reasons.append(f"head branch is {head.get('ref')}, not {branch}")
    if (head.get("repo") or {}).get("full_name") != repo:
        reasons.append("head is not in this repository")
    if base.get("ref") != base_branch or (base.get("repo") or {}).get("full_name") != repo:
        reasons.append(f"base is not {base_branch} in this repository")
    if head.get("sha") != expected_sha:
        reasons.append(f"PR head is {head.get('sha')}, not the pushed commit {expected_sha}")
    return reasons


def approvable(run, repo, sha, branch=BRANCH):
    return (
        run.get("head_sha") == sha
        and run.get("event") == "pull_request"
        and run.get("conclusion") == "action_required"
        and (run.get("triggering_actor") or {}).get("login") == BOT
        and run.get("head_branch") == branch
        and (run.get("head_repository") or {}).get("full_name") == repo
    )


def parse_args(argv):
    """Return (repo, number, sha, branch, base) or None when the arguments are wrong."""
    positional, opts, rest = [], {"--branch": BRANCH, "--base": BASE}, list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a in opts:
            if not rest:
                return None
            opts[a] = rest.pop(0)
        elif a.startswith("-"):
            return None
        else:
            positional.append(a)
    if len(positional) != 3 or not all(opts.values()):
        return None
    return (*positional, opts["--branch"], opts["--base"])


def main(argv, api=gh_api, post=gh_post, diff_ok=None, sleep=time.sleep, polls=9, wait=10):
    args = parse_args(argv)
    if args is None:
        print(__doc__, file=sys.stderr)
        return 2
    repo, number, sha, branch, base_branch = args
    pr = api(f"repos/{repo}/pulls/{number}")
    reasons = pr_guards(pr, repo, sha, branch, base_branch)
    base_sha = (pr.get("base") or {}).get("sha")
    if not reasons:
        ok = diff_ok(f"{base_sha}...{sha}") if diff_ok else changed_files.check(
            changed_files.diff_entries(f"{base_sha}...{sha}"), "openspec")[0]
        if not ok:
            reasons.append("the PR changes something other than plain files under openspec/")
    if reasons:
        for r in reasons:
            print(f"Not approving: {r}")
        return 1

    approved = set()
    for attempt in range(polls):
        runs = api(f"repos/{repo}/actions/runs?head_sha={sha}&event=pull_request&per_page=100").get("workflow_runs", [])
        held = [r for r in runs if r.get("conclusion") == "action_required"]
        for run in held:
            if run["id"] in approved:
                continue
            if not approvable(run, repo, sha, branch):
                print(f"Not approving run {run['id']} ({run.get('name')}): it does not match the archive PR's own runs")
                return 1
            post(f"repos/{repo}/actions/runs/{run['id']}/approve")
            approved.add(run["id"])
            print(f"Approved run {run['id']} ({run.get('name')}) on {sha[:7]}")
        if runs and not [r for r in runs if r.get("conclusion") == "action_required" and r["id"] not in approved]:
            # Every pull_request run so far is approved or was never held; wait one more poll for late ones.
            if attempt >= 2:
                break
        sleep(wait)
    if not approved:
        print("No held runs appeared on the archive PR; nothing approved.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
