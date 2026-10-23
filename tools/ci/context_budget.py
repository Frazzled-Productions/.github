#!/usr/bin/env python3
""""Context budget": a ceiling on the instruction surface (AGENTS.md, CLAUDE.md, rules, skills).

Shipped from Frazzled-Productions/.github and run by context-budget.yml against the caller's checkout
(the current directory). A port of Koinori's tools/dev/check-context-budget.sh (owner decision
23 October 2026), keeping its budget file format:

  <path or spec><TAB><max lines>      # lines starting with # are comments

where the spec is a path, GLOB:<pattern> (every matching file, summed) or RULES_UNSCOPED
(.claude/rules/*.md without `paths:` in their first 12 lines, the rules every session loads). Lines
are counted as `grep -c ''` counts them; a missing file counts 0.

  context_budget.py [--budget-file PATH] [--base REV]

Fails when any entry is over budget; under budget only prints a note. A missing budget file fails
and prints a seed with today's counts. With --base (the PR's base), each entry whose number went up
needs a `#` line added since the base, in the comment block directly above it, naming
`<old> -> <new>` and a reason of at least 20 characters; a removed entry needs an added
`# removed <spec>: <reason>` line. A new entry needs nothing. Exit 0 pass, 1 fail, 2 when git fails.
"""
import argparse
import difflib
import glob
import os
import re
import subprocess
import sys

REASON_MIN = 20
ADVICE = """
Context budget: FAILED - the instruction surface grew past its ceiling.
  Do not just raise the number: these files regrow because every single addition looks reasonable.
  Remove something superseded, move it behind a paths:-scoped rule in .claude/rules/, or move the
  rationale to docs/ and leave a pointer. If the growth is genuinely warranted,
  raise the budget in the same PR, with a '# <old> -> <new> on <date>: <reason>' line directly
  above the entry."""


def count(path):
    """Lines as `grep -c ''` counts them: a last line without a newline counts, an empty file is 0."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def unscoped_rules():
    for path in sorted(glob.glob(".claude/rules/*.md")):
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            head = [next(f, "") for _ in range(12)]
        if not any(line.startswith("paths:") for line in head):
            yield path


def count_for(spec):
    if spec.startswith("GLOB:"):
        return sum(count(p) for p in glob.glob(spec[len("GLOB:"):]) if os.path.isfile(p))
    if spec == "RULES_UNSCOPED":
        return sum(count(p) for p in unscoped_rules())
    return count(spec) if os.path.isfile(spec) else 0


def parse(text):
    """Return [(line index, spec, budget text)] for every entry line."""
    entries = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or line.startswith("#"):
            continue
        spec, _, budget = line.partition("\t")
        if budget.strip():
            entries.append((i, spec, budget.strip()))
    return entries


def seed(budget_file):
    lines = [f"# {budget_file}: <path or GLOB:pattern or RULES_UNSCOPED><TAB><max lines>.",
             "# Seeded at today's counts. Lower a number freely; raise one only with a",
             "# '# <old> -> <new> on <date>: <reason>' line directly above it."]
    for path in ("AGENTS.md", "CLAUDE.md"):
        if os.path.isfile(path):
            lines.append(f"{path}\t{count(path)}")
    if glob.glob(".claude/rules/*.md"):
        lines.append(f"RULES_UNSCOPED\t{count_for('RULES_UNSCOPED')}")
    return "\n".join(lines)


def check_counts(entries):
    ok = True
    print(f"{'WHAT':<34} {'ACTUAL':>8} {'BUDGET':>8}")
    for _, spec, budget in entries:
        label = spec[len("GLOB:"):] if spec.startswith("GLOB:") else spec
        if not budget.isdigit():
            print(f"::error::{spec}: budget '{budget}' is not a whole number.")
            ok = False
            continue
        actual, limit = count_for(spec), int(budget)
        if actual > limit:
            print(f"{label:<34} {actual:>8} {limit:>8}  OVER by {actual - limit}")
            print(f"::error::{label} is {actual} lines, over its budget of {limit} by {actual - limit}.")
            ok = False
        elif actual < limit:
            print(f"{label:<34} {actual:>8} {limit:>8}  (under by {limit - actual})")
        else:
            print(f"{label:<34} {actual:>8} {limit:>8}")
    return ok


def check_raises(base_text, head_text):
    """Return the problems with raised or removed entries compared with the base."""
    base_lines, head_lines = base_text.splitlines(), head_text.splitlines()
    added = set()
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, base_lines, head_lines, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            added.update(range(j1, j2))
    old = {spec: budget for _, spec, budget in parse(base_text)}
    new = {spec: (i, budget) for i, spec, budget in parse(head_text)}
    problems = []
    for spec, (i, budget) in new.items():
        was = old.get(spec)
        if not (was and was.isdigit() and budget.isdigit()) or int(budget) <= int(was):
            continue
        block, k = [], i - 1
        while k >= 0 and head_lines[k].startswith("#"):
            block.append(k)
            k -= 1
        pattern = re.compile(rf"\b{was}\s*->\s*{budget}\b(.*)")
        if not any(k in added and (m := pattern.search(head_lines[k])) and len(m.group(1).strip(" :-.,")) >= REASON_MIN
                   for k in block):
            problems.append(f"The raise of {spec} from {was} to {budget} needs a reason line: add "
                            f"'# {was} -> {budget} on <date>: <reason of {REASON_MIN}+ characters>' directly above it.")
    for spec in old:
        if spec in new:
            continue
        pattern = re.compile(rf"^#\s*removed\s+{re.escape(spec)}\s*:(.*)")
        if not any(k in added and (m := pattern.search(line)) and len(m.group(1).strip()) >= REASON_MIN
                   for k, line in enumerate(head_lines)):
            problems.append(f"Removing the {spec} entry needs a reason line: add "
                            f"'# removed {spec}: <reason of {REASON_MIN}+ characters>'.")
    return problems


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--budget-file", default=".github/context-budget.txt")
    p.add_argument("--base", help="the PR's base commit; raised entries need a reason compared with it")
    args = p.parse_args(argv)
    if not os.path.isfile(args.budget_file):
        print(f"::error::No budget file at {args.budget_file}. Commit it with these lines (today's counts):")
        print(seed(args.budget_file))
        return 1
    with open(args.budget_file, encoding="utf-8") as f:
        head_text = f.read()
    ok = check_counts(parse(head_text))
    if args.base:
        try:
            listed = subprocess.run(["git", "ls-tree", "--name-only", args.base, "--", args.budget_file],
                                    check=True, capture_output=True, text=True).stdout.strip()
            base_text = subprocess.run(["git", "show", f"{args.base}:{args.budget_file}"], check=True,
                                       capture_output=True, text=True).stdout if listed else ""
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"::error::Could not read {args.budget_file} at {args.base}: {e}")
            return 2
        for problem in check_raises(base_text, head_text):
            print(f"::error::{problem}")
            ok = False
    else:
        print("No base commit given, so raised budgets were not compared with one.")
    if not ok:
        print(ADVICE)
        return 1
    print("\nContext budget: PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
