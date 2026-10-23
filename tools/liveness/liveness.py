"""Off-Mac liveness check for the ops command centre (ops OpenSpec command-centre-core, design D6).

The Mac's stall watcher writes CC_HEARTBEAT_AT and its now.md job writes CC_NOW_MD_AT (epoch seconds)
as repository variables of this repo. Every 3 hours the workflow reads them from the vars context
(no token needed to read) and opens, updates or closes one issue mentioning Fraser. 26 hours, not 1:
the Mac sleeps overnight and this check cannot tell sleep from failure.

CLI (used by the workflow): python3 liveness.py   with NOW, HEARTBEAT_AT, NOW_MD_AT, GH_TOKEN, GH_REPO set.
"""
import json
import os
import subprocess
import sys
import time

LIMIT = 26 * 3600
TITLE_PREFIX = "Command centre heartbeat stale"
OWNER = "@fraserbrookhouse"


def parse(value):
    try:
        v = int(str(value).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _age(now, at):
    return "never written" if at is None else f"{int((now - at) // 3600)} h"


def decide(now, heartbeat, now_md, open_issue):
    """Return {action: none|open|update|close, issue, title, body, reason}."""
    if heartbeat is None and now_md is None:
        return dict(action="none", issue=open_issue, reason="not connected yet (no heartbeat variables written)")
    hb_stale = heartbeat is None or now - heartbeat > LIMIT
    nm_stale = now_md is None or now - now_md > LIMIT
    seen = f"Heartbeat: {_age(now, heartbeat)} old. now.md: {_age(now, now_md)} old."
    if hb_stale or nm_stale:
        worst = max((now - x) if x else LIMIT + 1 for x in (heartbeat, now_md))
        hours = int(worst // 3600)
        title = f"{TITLE_PREFIX} ({hours} h)"
        what = []
        if hb_stale:
            what.append("the stall watcher on the Mac has not reported")
        if nm_stale:
            what.append("now.md has not been rebuilt")
        body = (f"{OWNER} the ops command centre looks stopped: {' and '.join(what)} for over 26 hours.\n\n"
                f"{seen}\n\nCheck that the Mac is awake and the ops runner is online (ops repo, Settings, "
                "Actions, Runners), then see runbooks/command-centre.md in ops. This issue closes itself when "
                "both are fresh again.")
        if open_issue:
            return dict(action="update", issue=open_issue, title=title, body=body, reason="still stale")
        return dict(action="open", issue=None, title=title, body=body, reason="stale")
    if open_issue:
        return dict(action="close", issue=open_issue, title=None, body=f"Back to normal. {seen}", reason="fresh again")
    return dict(action="none", issue=None, reason=f"fresh. {seen}")


def gh(*args):
    p = subprocess.run(["gh"] + list(args), capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:2])} failed: {p.stderr.strip()}")
    return p.stdout


def main():
    now = parse(os.environ.get("NOW")) or int(time.time())
    hb, nm = parse(os.environ.get("HEARTBEAT_AT")), parse(os.environ.get("NOW_MD_AT"))
    issues = json.loads(gh("issue", "list", "--state", "open", "--search", f'"{TITLE_PREFIX}" in:title',
                           "--json", "number,title"))
    open_issue = next((i["number"] for i in issues if i["title"].startswith(TITLE_PREFIX)), None)
    d = decide(now, hb, nm, open_issue)
    print(f"liveness: {d['action']} ({d['reason']})")
    if d["action"] == "open":
        gh("issue", "create", "--title", d["title"], "--body", d["body"])
    elif d["action"] == "update":
        # Edit in place (no new comment), so a long outage mentions Fraser once, not every 3 hours.
        gh("issue", "edit", str(d["issue"]), "--title", d["title"], "--body", d["body"])
    elif d["action"] == "close":
        gh("issue", "close", str(d["issue"]), "--comment", d["body"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
