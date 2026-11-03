"""Hosted minutes switch (ops OpenSpec hosted-minutes-switch): keeps private repos' light jobs on the
included GitHub-hosted minutes, and moves them to the Mac when those are nearly gone.

Each run reads the calendar month's Actions minutes, leaves out public repos, and sets LIGHT_RUNNER and
OPS_LIGHT_RUNNER: hosted mode under 2,700 of 3,000 minutes, Mac mode at 2,700 or more. The mode comes
from the month's figure alone, with no stored state, so a missed run or a lost write repairs itself and
the month's reset is the switch back. An unreadable or senseless answer changes nothing and fails the run.

This repo is public, so its logs are: print totals only, never a private repo's name or a gh error's text.

CLI (used by hosted-minutes-switch.yml):
  python3 switch.py run                     with GH_TOKEN (the switch's credential), HOSTED_SWITCH_WRITE
  python3 switch.py report <step outcome>   with GH_TOKEN (the workflow's own token), GH_REPO, AUTH_FAILED
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

ORG = "Frazzled-Productions"
SWITCH_AT = 2700  # of 3,000 included; the margin is in design.md, D2
WORKFLOW_FILE = "hosted-minutes-switch.yml"
HOSTED = '"ubuntu-latest"'
MODES = {
    "hosted": {"LIGHT_RUNNER": HOSTED, "OPS_LIGHT_RUNNER": HOSTED},
    "mac": {"LIGHT_RUNNER": '["light"]', "OPS_LIGHT_RUNNER": '["self-hosted", "macOS", "ARM64", "ops"]'},
}
FAILURES_TO_REPORT = 3
TITLE = "Hosted minutes switch failing"
OWNER = "@fraserbrookhouse"
BOT = "app/github-actions"  # the failure issue's author: the report step uses the workflow's own token
MISSING = "no credential: HOSTED_SWITCH_TOKEN is not set in the hosted-switch environment"


class Failed(Exception):
    """The run cannot trust what it read, or could not write. Its text goes in a public log."""


def failure_text(stderr):
    """A gh error reduced to its HTTP status: gh's own text can name a private repo. A 403 for a rate
    limit says so, as it is no sign of a bad credential."""
    found = re.search(r"HTTP (\d{3})", stderr)
    if not found:
        return "no HTTP status"
    limited = found.group(1) == "403" and re.search(r"rate limit", stderr, re.I)
    return f"HTTP {found.group(1)}" + (" (rate limit)" if limited else "")


def gh(args):
    p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise Failed(f"gh {args[0]}: {failure_text(p.stderr)}")
    if "-X" in args or (args[0] == "issue" and args[1] != "list"):  # 204 with no body, or a URL: not JSON
        return None
    return json.loads(p.stdout)


def private_minutes(usage, public, day):
    """This month's Actions minutes outside public repos. Public repos are subtracted rather than private
    ones listed, so a new private repo counts with no change and the read needs no wider access."""
    items = usage.get("usageItems") if isinstance(usage, dict) else None
    if not isinstance(items, list):
        raise Failed("the billing answer has no usageItems")
    minutes = [i for i in items if i.get("product") == "actions"
               and str(i.get("unitType", "")).lower().startswith("minute")]
    if not minutes and day > 1:
        raise Failed("no Actions minute rows after the 1st")
    if any(not isinstance(i.get("quantity"), (int, float)) for i in minutes):
        raise Failed("an Actions minute row has no quantity")
    return int(sum(i["quantity"] for i in minutes if i.get("repositoryName") not in public))


def run(ghf, now, write):
    """One pass. Reads everything before it writes anything. Returns mode, total, changed and write."""
    usage = ghf(["api", f"/organizations/{ORG}/settings/billing/usage?year={now.year}&month={now.month}"])
    public = {r["name"] for r in ghf(["api", "--paginate", f"orgs/{ORG}/repos?type=public&per_page=100"])}
    if ".github" not in public:  # this repo is public, so the list is wrong and every minute would look private
        raise Failed("the public repo list does not include this repo")
    total = private_minutes(usage, public, now.day)
    mode = "mac" if total >= SWITCH_AT else "hosted"
    current = {}
    for name in MODES[mode]:
        try:
            current[name] = ghf(["api", f"orgs/{ORG}/actions/variables/{name}"])["value"]
        except Failed as e:  # a variable's name is not private; say which one, as a 404 means it is missing
            raise Failed(f"reading {name}: {e}") from None
    changed = [name for name, value in MODES[mode].items() if current[name] != value]
    if write:
        for name in changed:
            ghf(["api", "-X", "PATCH", f"orgs/{ORG}/actions/variables/{name}", "-f", f"value={MODES[mode][name]}"])
    return dict(mode=mode, total=total, changed=changed, write=write)


def summary(result):
    verb = "wrote" if result["write"] else "report-only, would write"
    return (f"switch: {result['mode']} mode, {result['total']} private minutes, "
            f"{verb} {', '.join(result['changed']) or 'nothing'}")


def writes_on(value):
    return value == "true"


def refused(text):
    """A missing credential, or a 401 or 403 other than a rate limit: the credential is missing, expired or
    lacks access, which no later run repairs, and in hosted mode the minutes keep running out meanwhile,
    so it is reported on the first run."""
    return MISSING in text or re.search(r"HTTP 40[13](?! \(rate limit\))\b", text) is not None


def decide_report(outcome, earlier, open_issue, auth=False):
    """What to do with the one failure issue. outcome: this run's switch step; earlier: conclusions of
    earlier completed runs, newest first; auth: this run's credential was refused."""
    if outcome == "success":
        if open_issue:
            return dict(action="close", issue=open_issue, body="A run succeeded, so the switch is working again.")
        return dict(action="none")
    if outcome != "failure":
        return dict(action="none")
    streak = 1
    for conclusion in earlier:
        if conclusion != "failure":
            break
        streak += 1
    if streak < FAILURES_TO_REPORT and not auth:
        return dict(action="none")
    cause = ("its credential is missing or was refused (HTTP 401 or 403), so it has probably expired: set "
             "`HOSTED_SWITCH_TOKEN` in the `hosted-switch` environment"
             if auth else f"it has failed at least {streak} runs in a row")
    body = (f"{OWNER} the hosted minutes switch cannot run: {cause}. `LIGHT_RUNNER` is keeping its last "
            "value. Hosted mode with the minutes gone means red checks; Mac mode means checks wait for the "
            f"Mac. Read the latest run of `{WORKFLOW_FILE}`: it gives the HTTP status. Manual override: set "
            "`HOSTED_SWITCH_WRITE` to `false` so the switch cannot overwrite it, then set `LIGHT_RUNNER` and "
            "`OPS_LIGHT_RUNNER` by hand (steps in `runbooks/mac-runners.md` in ops). This issue closes "
            "itself after a good run.")
    return dict(action="update" if open_issue else "open", issue=open_issue, body=body)


def report(ghf, outcome, auth=False):
    # Only its own issue: the repo is public, so anyone can open one with the same title.
    issues = ghf(["issue", "list", "--state", "open", "--author", BOT, "--search", f'"{TITLE}" in:title',
                  "--json", "number,title,author"])
    open_issue = next((i["number"] for i in issues
                       if i["title"] == TITLE and (i.get("author") or {}).get("login") == BOT), None)
    runs = ghf(["run", "list", "--workflow", WORKFLOW_FILE, "--branch", "main", "--status", "completed",
                "--limit", str(FAILURES_TO_REPORT), "--json", "conclusion"])
    d = decide_report(outcome, [r["conclusion"] for r in runs], open_issue, auth)
    print(f"report: {d['action']}")
    if d["action"] == "open":
        ghf(["issue", "create", "--title", TITLE, "--body", d["body"]])
    elif d["action"] == "update":
        # Edit in place (no new comment), so a long outage mentions Fraser once, not on every run.
        ghf(["issue", "edit", str(d["issue"]), "--body", d["body"]])
    elif d["action"] == "close":
        ghf(["issue", "close", str(d["issue"]), "--comment", d["body"]])


def main(argv):
    try:
        if argv[:1] == ["run"]:
            if not os.environ.get("GH_TOKEN"):  # gh then prints no HTTP status, so say it here
                raise Failed(MISSING)
            now = dt.datetime.now(dt.timezone.utc)
            print(summary(run(gh, now, writes_on(os.environ.get("HOSTED_SWITCH_WRITE")))))
        elif argv[:1] == ["report"] and len(argv) == 2:
            report(gh, argv[1], os.environ.get("AUTH_FAILED") == "true")
        else:
            print(__doc__.rsplit("\n\n", 1)[1], file=sys.stderr)
            return 2
    except Failed as e:
        print(f"::error::switch changed nothing further: {e}")
        if argv[:1] == ["run"] and refused(str(e)) and os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                out.write("auth-failed=true\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
