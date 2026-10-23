#!/usr/bin/env python3
""""OpenSpec required": a PR that changes more than docs must carry an OpenSpec change.

Shipped from Frazzled-Productions/.github and run by openspec-required.yml against the caller's
checkout (the current directory), never from the caller's own tree (owner decision 23 October 2026).

  required.py --repo OWNER/NAME --pr N --base SHA --head SHA [--budget-file PATH]

Judged in this order; the first that applies decides:
  1. Docs-only passes: every file in base...head passes `changed_files.py docs`, with the repo's
     context budget file also counting as docs.
  2. A Dependabot update passes: the author is dependabot[bot] and every changed file is a dependency
     manifest or lock file, or a workflow under .github/workflows/.
  3. No openspec/ folder at the head fails: adopt OpenSpec first.
  4. A change passes: the PR adds or edits a file in openspec/changes/<name>/ (not archive/), and that
     change at the head has specs/<capability>/spec.md or `skip_specs: true` in .openspec.yaml.
Anything else fails, unless the PR carries the `no-spec` label, the latest "labeled" event for it in
the PR's issue events was by fraserbrookhouse (fixed here, never an input), and the body has a
`## No spec` section with text. Then it passes, prints who added the label and when, and keeps one PR
comment recording the exemption and the reason.

The PR's author, labels and body are read through `gh api` when needed, so a re-run sees the current
ones. Needs git, python3 and gh. Exit 0 pass, 1 fail, 2 when git or gh fails.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ci"))
import changed_files  # noqa: E402

FRASER = "fraserbrookhouse"
LABEL = "no-spec"
MARKER = "<!-- openspec-required:no-spec -->"
KIT = "ops/standards/openspec-adoption/README.md"
ADOPT_FIRST = ("This repo has not adopted OpenSpec yet. Adopt OpenSpec first (" + KIT + "): make this PR, "
               "or the one before it, the adoption change.")
DEPENDABOT = "dependabot[bot]"
MANIFESTS = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Package.swift",
             "Package.resolved", "Gemfile", "Gemfile.lock"}
REQUIREMENTS_RE = re.compile(r"\Arequirements[^/]*\.txt\Z")
CHANGE_RE = re.compile(r"\Aopenspec/changes/([^/]+)/.")
SKIP_SPECS_RE = re.compile(r"^skip_specs:\s*true\s*(#.*)?$", re.M)
DELTA_RE = re.compile(r"\Aspecs/[^/]+/spec\.md\Z")
NO_SPEC_RE = re.compile(r"^##[ \t]+No spec[ \t]*$(.*?)(?=^#{1,2}[ \t]|\Z)", re.M | re.S | re.I)


class Failure(Exception):
    pass


def git(args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout.decode("utf-8", "surrogateescape")


def gh_json(args):
    out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def gh_list(path):
    out = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".[] | tojson"], check=True,
                         capture_output=True, text=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def is_docs_only(entries, budget_file):
    rest = [e for e in entries if not (e[3] == budget_file and e[0] in "AM" and e[2] == changed_files.PLAIN)]
    if entries and not rest:
        return True, []
    return changed_files.check(rest, "docs")


def is_dependency_file(path):
    name = path.rsplit("/", 1)[-1]
    return name in MANIFESTS or bool(REQUIREMENTS_RE.search(name)) or path.startswith(".github/workflows/")


def tree(head, prefix):
    return [p for p in git(["ls-tree", "-r", "-z", "--name-only", head, "--", prefix]).split("\0") if p]


def change_state(head, name):
    """'delta', 'skip' or 'neither' for an active change at the head, or None when it is not there."""
    files = tree(head, f"openspec/changes/{name}/")
    if not files:
        return None
    inside = [f[len(f"openspec/changes/{name}/"):] for f in files]
    if any(DELTA_RE.search(f) for f in inside):
        return "delta"
    if ".openspec.yaml" in inside:
        meta = git(["show", f"{head}:openspec/changes/{name}/.openspec.yaml"])
        if SKIP_SPECS_RE.search(meta):
            return "skip"
    return "neither"


def judge(entries, head, budget_file, author):
    """Return (passed, message, reason). author is a callable, so gh is only asked when needed."""
    ok, why = is_docs_only(entries, budget_file)
    if ok:
        return True, "This PR is docs-only (openspec/, docs Markdown and the context budget file), so it needs no OpenSpec change.", "docs-only"
    if all(is_dependency_file(e[3]) for e in entries) and author() == DEPENDABOT:
        return True, "Passed as a Dependabot update: only dependency manifests, lock files and workflow files changed.", "dependabot"
    if not tree(head, "openspec/"):
        return False, ADOPT_FIRST, "adopt-first"
    states = {}
    for _, _, _, path in entries:
        m = CHANGE_RE.search(path)
        if m and m.group(1) != "archive":
            states.setdefault(m.group(1), change_state(head, m.group(1)))
    good = sorted(n for n, s in states.items() if s in ("delta", "skip"))
    if good:
        return True, "Carries the OpenSpec change " + ", ".join(good) + ".", "change"
    first = next((r.split(":", 1)[0] for r in why if ": " in r), entries[0][3] if entries else "the PR")
    bad = sorted(n for n, s in states.items() if s == "neither")
    if bad:
        detail = "; ".join(f"{n} has no delta and no skip_specs: true" for n in bad)
        return False, f"{first} is not docs, so this PR needs an OpenSpec change, and {detail} (add specs/<capability>/spec.md, or skip_specs: true in its .openspec.yaml).", "no-change"
    return False, (f"{first} is not docs, so this PR needs an OpenSpec change: add or edit an active change in "
                   "openspec/changes/<name>/ with a delta (specs/<capability>/spec.md) or skip_specs: true."), "no-change"


def no_spec_reason(body):
    m = NO_SPEC_RE.search((body or "").replace("\r\n", "\n"))
    if not m:
        return ""
    return re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()


def exemption(repo, pr, data):
    """Return (passed, message) for the no-spec label."""
    events = [e for e in gh_list(f"repos/{repo}/issues/{pr}/events")
              if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == LABEL]
    if not events:
        return False, f"The {LABEL} label is on the PR but no labelled event was found for it, so it does not exempt the PR."
    last = events[-1]
    who, when = (last.get("actor") or {}).get("login") or "an unknown account", last.get("created_at") or "an unknown time"
    if who != FRASER:
        return False, f"The {LABEL} label was added by {who}, but only Fraser's no-spec label exempts a PR ({FRASER})."
    reason = no_spec_reason(data.get("body"))
    if not reason:
        return False, (f"{FRASER} added {LABEL}, but the PR body has no reason: add a '## No spec' section saying "
                       "why this PR has no OpenSpec change, then re-run this check.")
    note = f"Passed without an OpenSpec change: {LABEL} added by {who} at {when}"
    body = f"{MARKER}\n**{note}.**\n\nReason, from the PR body's `## No spec` section:\n\n" + \
        "\n".join("> " + line for line in reason.splitlines())
    mine = [c for c in gh_list(f"repos/{repo}/issues/{pr}/comments")
            if MARKER in (c.get("body") or "") and (c.get("user") or {}).get("type") == "Bot"]
    if mine:
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{repo}/issues/comments/{mine[0]['id']}", "-f", f"body={body}"],
                       check=True, capture_output=True)
    else:
        subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}"],
                       check=True, capture_output=True)
    return True, note


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--budget-file", default=".github/context-budget.txt")
    args = p.parse_args(argv)
    # The caller file is PR-editable, so budget-file must not be able to turn any other file into "docs".
    if args.budget_file.rsplit("/", 1)[-1] != "context-budget.txt":
        print(f"::error::budget-file '{args.budget_file}' is not a context-budget.txt file.")
        write_output("error", "fail")
        return 2
    cache = {}

    def pr_data():
        if "pr" not in cache:
            cache["pr"] = gh_json(["api", f"repos/{args.repo}/pulls/{args.pr}"])
        return cache["pr"]

    try:
        entries = changed_files.diff_entries(f"{args.base}...{args.head}")
        print(f"Changed files ({args.base[:12]}...{args.head[:12]}):")
        for status, _, new, path in entries:
            print(f"  {status} {new} {path!r}" if "\n" in path else f"  {status} {new} {path}")
        passed, message, reason = judge(entries, args.head, args.budget_file, lambda: pr_data()["user"]["login"])
        if passed:
            print(f"::notice::{message}" if reason == "dependabot" else message)
            write_output(reason, "pass")
            return 0
        if LABEL in [lab.get("name") for lab in pr_data().get("labels") or []]:
            ok, note = exemption(args.repo, args.pr, pr_data())
            if ok:
                print(f"::notice::{note}")
                write_output("label", "pass")
                return 0
            print(f"::error::{note}")
            write_output("label-refused", "fail")
            return 1
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, IndexError) as e:
        detail = getattr(e, "stderr", None)
        detail = detail.decode() if isinstance(detail, bytes) else detail
        print(f"::error::Could not run the OpenSpec required check: {e} {detail or ''}".rstrip())
        write_output("error", "fail")
        return 2
    print(f"::error::{message}")
    if reason != "adopt-first":
        print(f"A rare exception needs Fraser's {LABEL} label and a '## No spec' section in the PR body saying why.")
    write_output(reason, "fail")
    return 1


def write_output(reason, result):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"result={result}\nreason={reason}\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
