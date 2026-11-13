"""Off-Mac liveness check for the ops command centre (ops OpenSpec command-centre-core, design D6, and
reliable-watcher-trigger, design D5).

The Mac writes these repository variables of this repo (epoch seconds):
  CC_HEARTBEAT_AT  the stall watcher, on every run
  CC_NOW_MD_AT     the now.md job
  CC_MAC_AWAKE     "<awake_since> <last_tick>", the Mac trigger (ops scripts/trigger/cc-trigger.sh), every
                   10 minutes while the Mac is awake
  CC_TRIGGER_AT    the trigger's last tick (or the Mac's last wake, if later), relayed by the watcher
  CC_HOST_AWAKE    "<awake_since> <last_tick>", the always-on host's tick, every 10 minutes (ops OpenSpec
                   always-on-host)
The workflow reads them from the vars context (no token needed to read) and opens, updates or closes one
issue when, in this order (it mentions nobody: system failures go on the ops daily card, whose Health
line names the open issue; Fraser's ruling of 12 November 2026, ops #494):
  1. the Mac has been awake for 30 minutes or more and the watcher heartbeat is over 30 minutes old;
  2. the watcher heartbeat is more than 30 minutes newer than the trigger's last tick (the watcher runs
     only on the backstop cron because the trigger is silent);
  3. the host's last tick is over 30 minutes old, at any hour (the host never sleeps);
  4. now.md is older than 26 hours.
A laptop that is off opens nothing (Fraser's ruling of 13 November 2026, call 13 of ops always-on-host):
the page's "needs Mac" line says when it was last seen. Rule 1 cannot fire while the Mac sleeps, because
the trigger's last tick is then old. A variable never
written is "not connected", never stale. This check's own cron is throttled by GitHub to about every 3
to 5 hours, so it is a coarse "the command centre is dead" alarm; the 30-minute signal while Fraser
works comes from the session hooks on the Mac.

CLI (used by the workflow): python3 liveness.py   with NOW, HEARTBEAT_AT, NOW_MD_AT, MAC_AWAKE,
TRIGGER_AT, HOST_AWAKE, GH_TOKEN, GH_REPO set.
"""
import json
import os
import subprocess
import sys
import time

LIMIT = 26 * 3600
STALE = 30 * 60        # watcher heartbeat older than this while awake (rule 1), trigger silence (rule 2)
AWAKE = 30 * 60        # the Mac must have been awake this long for rule 1
TICKING = 20 * 60      # the trigger's last tick must be this recent for the Mac to count as awake
CADENCE = ("This check runs about every 3 to 5 hours (GitHub throttles its cron), so this alarm can arrive "
           "up to about 5 hours after the problem started.")
TITLE_PREFIX = "Command centre heartbeat stale"


def parse(value):
    try:
        v = int(str(value).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_awake(value):
    """CC_MAC_AWAKE or CC_HOST_AWAKE "<awake_since> <last_tick>" as a tuple, or None when unset or malformed."""
    parts = str(value or "").split()
    if len(parts) != 2:
        return None
    a, t = parse(parts[0]), parse(parts[1])
    return (a, t) if a and t else None


def _age(now, at):
    return "never written" if at is None else f"{int((now - at) // 3600)} h"


def _issue(open_issue, title, body, reason):
    if open_issue:
        return dict(action="update", issue=open_issue, title=title, body=body, reason=f"still {reason}")
    return dict(action="open", issue=None, title=title, body=body, reason=reason)


def decide(now, heartbeat, now_md, open_issue, mac_awake=None, trigger_at=None, host_awake=None):
    """Return {action: none|open|update|close, issue, title, body, reason}.
    mac_awake and host_awake: (awake_since, last_tick) from CC_MAC_AWAKE and CC_HOST_AWAKE, or None;
    trigger_at: CC_TRIGGER_AT or None."""
    last_tick = mac_awake[1] if mac_awake else None
    if heartbeat is None and now_md is None and mac_awake is None and host_awake is None:
        return dict(action="none", issue=open_issue, reason="not connected yet (no heartbeat variables written)")
    seen = f"Heartbeat: {_age(now, heartbeat)} old. now.md: {_age(now, now_md)} old."
    if mac_awake:
        seen += f" Mac-awake heartbeat: last tick {int((now - last_tick) // 60)} min ago, awake for " \
                f"{int((now - mac_awake[0]) // 60)} min."
    if trigger_at:
        seen += f" Trigger last tick relayed by the watcher: {int((now - trigger_at) // 60)} min ago."
    seen += (f" Host: last tick {int((now - host_awake[1]) // 60)} min ago." if host_awake else " Host: not connected.")
    fix = ("See runbooks/command-centre.md in ops (Mac trigger): on the Mac run "
           "~/Projects/frazzled-productions/ops/scripts/trigger/install.sh --check and read "
           "~/Library/Logs/frazzled-cc-trigger.log.")

    # 1. Watcher stopped while the Mac is awake (for example the gh login expired, or the runner is offline).
    if (mac_awake and heartbeat is not None and now - last_tick <= TICKING and now - mac_awake[0] >= AWAKE
            and now - heartbeat > STALE):
        mins = int((now - heartbeat) // 60)
        body = (f"The ops stall watcher has not run for {mins} minutes while the Mac has been awake. "
                f"The Mac trigger is ticking, so its dispatches are failing or the ops runner is not picking "
                f"them up.\n\n{seen}\n\n{fix} Also check the ops runner is online (ops repo, Settings, Actions, "
                f"Runners).\n\n{CADENCE} This issue closes itself when the watcher is running again.")
        return _issue(open_issue, f"{TITLE_PREFIX} (watcher {mins} min, Mac awake)", body, "watcher stale while awake")

    # 2. Trigger silent, watcher running only on the backstop cron.
    if heartbeat is not None and trigger_at is not None and heartbeat - trigger_at > STALE:
        mins = int((heartbeat - trigger_at) // 60)
        body = (f"The Mac trigger had been silent for {mins} minutes when the stall watcher last ran "
                f"(on GitHub's backstop cron), so the watcher is running only a few times a day.\n\n{seen}\n\n"
                f"{fix}\n\n{CADENCE} This issue closes itself when the trigger ticks again.")
        return _issue(open_issue, f"{TITLE_PREFIX} (trigger silent {mins} min)", body, "trigger silent")

    # 3. The always-on host's tick silent for over 30 minutes: it never sleeps, so no hour excuses it.
    if host_awake and now - host_awake[1] > STALE:
        mins = int((now - host_awake[1]) // 60)
        body = (f"The always-on host's clock has not ticked for {mins} minutes: the host is off, its home "
                f"internet is down, or its timer or GitHub login has failed.\n\n{seen}\n\nSee "
                f"runbooks/always-on-host.md in ops (What a dead host looks like).\n\n{CADENCE} This issue closes "
                f"itself when the host ticks again.")
        return _issue(open_issue, f"{TITLE_PREFIX} (host {mins} min)", body, "host silent")

    # 4. now.md older than 26 hours (the page builder commits at least once a day). A variable never written
    # is "not connected", not stale. A laptop that is off is no alarm: the page says when it was last seen.
    if now_md is not None and now - now_md > LIMIT:
        hours = int((now - now_md) // 3600)
        body = (f"The ops command centre looks stopped: now.md has not been rebuilt for over 26 hours.\n\n"
                f"{seen}\n\nCheck the host that builds the page and its ops runner (ops repo, Settings, Actions, "
                f"Runners). {fix}\n\n{CADENCE} This issue closes itself when the page is rebuilt.")
        return _issue(open_issue, f"{TITLE_PREFIX} ({hours} h)", body, "stale")
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
    mac, trig = parse_awake(os.environ.get("MAC_AWAKE")), parse(os.environ.get("TRIGGER_AT"))
    host = parse_awake(os.environ.get("HOST_AWAKE"))
    issues = json.loads(gh("issue", "list", "--state", "open", "--search", f'"{TITLE_PREFIX}" in:title',
                           "--json", "number,title"))
    open_issue = next((i["number"] for i in issues if i["title"].startswith(TITLE_PREFIX)), None)
    d = decide(now, hb, nm, open_issue, mac_awake=mac, trigger_at=trig, host_awake=host)
    print(f"liveness: {d['action']} ({d['reason']})")
    if d["action"] == "open":
        gh("issue", "create", "--title", d["title"], "--body", d["body"])
    elif d["action"] == "update":
        # Edit in place (no new comment), so a long outage is one issue, not a stream of notifications.
        gh("issue", "edit", str(d["issue"]), "--title", d["title"], "--body", d["body"])
    elif d["action"] == "close":
        gh("issue", "close", str(d["issue"]), "--comment", d["body"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
