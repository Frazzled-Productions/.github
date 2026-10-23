#!/usr/bin/env python3
"""OpenSpec overlap check for a pull request (reusable workflow openspec-overlap.yml in
Frazzled-Productions/.github). Runs against the caller's checkout (the current directory).

OpenSpec's archive merges a delta into the main spec by requirement title. When two changes in
flight both MODIFY (or REMOVE, or RENAME) the same requirement, whichever archives second silently
overwrites the first (OpenSpec issues #1246, #1387, #2033). A MODIFIED target that is no longer on
main makes the archive fail after merge. This check catches both before merge.

For every delta this PR adds or changes (openspec/changes/<change>/specs/<capability>/spec.md, not
under archive/) it reads the MODIFIED and REMOVED titles and the RENAMED FROM titles, then:
  - fails when another open PR's delta touches the same capability and requirement title;
  - fails when a target is missing from openspec/specs/<capability>/spec.md on main (a MODIFIED
    title that this delta RENAMES TO is checked by its FROM title instead);
  - warns (without failing) when an ADDED title is already on main or added by another open PR, and
    when a delta for a capability not yet on main has no "## Purpose" section.
Every finding is a warning annotation; the exit code is 1 only for the two failing kinds.

Live (in the workflow):  overlap.py --pr <number> [--main-ref origin/main]
Local test:              overlap.py --this-files a.md b.md --others-json others.json [--main-ref REF]
  others.json is {"<pr number>": {"<path>": "<file content>", ...}, ...}
"""
import argparse
import json
import os
import re
import subprocess
import sys

DELTA_RE = re.compile(r"^openspec/changes/(?!archive/)([^/]+)/specs/([^/]+)/spec\.md$")
SECTION_RE = re.compile(r"^##\s+(ADDED|MODIFIED|REMOVED|RENAMED)\s+Requirements\s*$", re.I)
HEADER_RE = re.compile(r"^###\s*Requirement:\s*(.+?)\s*$")
FROM_RE = re.compile(r"^\s*[-*+]?\s*FROM:\s*`?###\s*Requirement:\s*(.+?)`?\s*$")
TO_RE = re.compile(r"^\s*[-*+]?\s*TO:\s*`?###\s*Requirement:\s*(.+?)`?\s*$")


def parse_delta(text):
    """Return {"ADDED": [...], "MODIFIED": [...], "REMOVED": [...], "RENAMED": [(from, to)], "purpose": bool}."""
    out = {"ADDED": [], "MODIFIED": [], "REMOVED": [], "RENAMED": [], "purpose": False}
    section, fence, pending = None, False, None
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = SECTION_RE.match(line)
        if m:
            section, pending = m.group(1).upper(), None
            continue
        if re.match(r"^##\s+Purpose\s*$", line, re.I):
            out["purpose"], section = True, None
            continue
        if re.match(r"^##\s", line):
            section = None
            continue
        if section == "RENAMED":
            f, t = FROM_RE.match(line), TO_RE.match(line)
            if f:
                pending = f.group(1).strip()
            elif t and pending:
                out["RENAMED"].append((pending, t.group(1).strip()))
                pending = None
            continue
        h = HEADER_RE.match(line)
        if h and section in ("ADDED", "MODIFIED", "REMOVED"):
            out[section].append(h.group(1).strip())
    return out


def touched(delta):
    """Titles (as they are on main) that this delta changes."""
    renamed_to = {t: f for f, t in delta["RENAMED"]}
    titles = {renamed_to.get(t, t) for t in delta["MODIFIED"]}
    titles |= set(delta["REMOVED"])
    titles |= {f for f, _ in delta["RENAMED"]}
    return titles


def main_titles(main_ref, capability):
    proc = subprocess.run(["git", "show", f"{main_ref}:openspec/specs/{capability}/spec.md"], capture_output=True, text=True)
    if proc.returncode != 0:
        return None  # the capability is not on main
    return {m.group(1).strip() for line in proc.stdout.splitlines() if (m := HEADER_RE.match(line))}


def gh_json(*args):
    return json.loads(subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout or "null")


def gh_raw(repo, path, ref):
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/{repo}/contents/{path}?ref={ref}"],
        capture_output=True, text=True,
    )
    return proc.stdout if proc.returncode == 0 else None  # deleted in that PR, or unreadable


def live_inputs(repo, number):
    this = gh_json("pr", "view", str(number), "--repo", repo, "--json", "files")
    this_paths = [f["path"] for f in this["files"] if DELTA_RE.match(f["path"])]
    this_files = {p: open(p, encoding="utf-8").read() for p in this_paths if os.path.exists(p)}
    others = {}
    for pr in gh_json("pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,headRefOid,files"):
        if pr["number"] == number:
            continue
        for f in pr.get("files") or []:
            if DELTA_RE.match(f["path"]):
                content = gh_raw(repo, f["path"], pr["headRefOid"])
                if content is not None:
                    others.setdefault(str(pr["number"]), {})[f["path"]] = content
    return this_files, others


def check(this_files, others, main_ref):
    findings = []  # (failing, path, message)
    other_deltas = []  # (pr, capability, delta)
    for pr, files in others.items():
        for path, content in files.items():
            m = DELTA_RE.match(path)
            if m:
                other_deltas.append((pr, m.group(2), parse_delta(content)))

    for path, content in sorted(this_files.items()):
        m = DELTA_RE.match(path)
        if not m:
            continue
        capability, delta = m.group(2), parse_delta(content)
        on_main = main_titles(main_ref, capability)
        mine = touched(delta)

        for title in sorted(mine):
            if on_main is None or title not in on_main:
                where = "is not on main" if on_main is not None else "has no spec on main"
                findings.append((True, path, f'"{title}" ({capability}) is modified, removed or renamed here, but {where}. '
                                             "Rebase on main and point the delta at the requirement as it is now."))
        for pr, cap, other in other_deltas:
            if cap != capability:
                continue
            for title in sorted(mine & touched(other)):
                findings.append((True, path, f'"{title}" ({capability}) is also modified, removed or renamed by open PR #{pr}. '
                                             "Whichever archives second would overwrite the other: land one first, then "
                                             "rebase the other and write its delta against the result."))
            for title in sorted(set(delta["ADDED"]) & set(other["ADDED"])):
                findings.append((False, path, f'"{title}" ({capability}) is also ADDED by open PR #{pr}.'))
        for title in delta["ADDED"]:
            if on_main and title in on_main:
                findings.append((False, path, f'"{title}" ({capability}) is ADDED here but already on main: MODIFY it instead.'))
        if on_main is None and not delta["purpose"]:
            findings.append((False, path, f'{capability} is a new capability: start the delta with a "## Purpose" section, '
                                          "or the archive bot will fail on the TBD placeholder after merge."))
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--main-ref", default="origin/main")
    ap.add_argument("--this-files", nargs="*")
    ap.add_argument("--others-json")
    a = ap.parse_args()

    if a.pr:
        this_files, others = live_inputs(a.repo, a.pr)
    else:
        this_files = {p: open(p, encoding="utf-8").read() for p in a.this_files or []}
        others = json.load(open(a.others_json, encoding="utf-8")) if a.others_json else {}

    findings = check(this_files, others, a.main_ref)
    failing = [f for f in findings if f[0]]
    for _, path, msg in findings:
        print(f"::warning file={path},title=OpenSpec overlap::{msg}")
    summary = (["### OpenSpec overlap", ""] + [f"- {'FAIL' if bad else 'warn'}: `{p}`: {msg}" for bad, p, msg in findings]
               if findings else ["### OpenSpec overlap", "", f"No overlaps across {len(this_files)} delta(s) in this PR."])
    print("\n".join(summary))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")
    if failing:
        print(f"::error::OpenSpec overlap: {len(failing)} problem(s) would make the archive after merge lose or fail a change.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
