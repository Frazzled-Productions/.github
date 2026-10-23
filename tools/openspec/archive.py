#!/usr/bin/env python3
"""Archive OpenSpec changes that have merged to main, and check the result.

Used by the reusable workflows openspec-archive.yml and openspec-docs-check.yml in
Frazzled-Productions/.github; also runs locally against any checkout (the current directory, or
OPENSPEC_ROOT).

  archive.py list              print each active change (not under archive/), in name order
  archive.py archive <name>    run `openspec archive <name> --yes`, then the checks below
  archive.py check             run the checks only

Checks (each failure is printed and makes the exit code 1):
  - no spec Purpose is the "TBD - created" placeholder the archive writes for a new capability
    whose delta had no "## Purpose" section;
  - `openspec validate --specs --strict` passes;
  - no em dash anywhere under openspec/ (house style);
  - the working tree changes nothing but plain files under openspec/ (tools/ci/changed_files.py),
    and nothing under openspec/changes is a symlink.

The em dash is written as chr(0x2014) so this file contains none itself.
"""
import os
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True  # a __pycache__ folder would count as a change outside openspec/
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ci"))
import changed_files  # noqa: E402  tools/ci/changed_files.py

ROOT = pathlib.Path(os.environ.get("OPENSPEC_ROOT", ".")).resolve()
CHANGES = ROOT / "openspec" / "changes"
SPECS = ROOT / "openspec" / "specs"
EM_DASH = chr(0x2014)
ENV = {**os.environ, "OPENSPEC_TELEMETRY": "0", "NO_COLOR": "1"}


def run(*args):
    """Run a command in ROOT, echo its output, and return (exit code, output)."""
    proc = subprocess.run(args, cwd=ROOT, env=ENV, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    print(f"$ {' '.join(args)}\n{out}\n", flush=True)
    return proc.returncode, out


def active_changes():
    if not CHANGES.is_dir():
        return []
    return sorted(p.name for p in CHANGES.iterdir() if p.is_dir() and p.name != "archive" and not p.name.startswith("."))


def check():
    problems = []

    for spec in sorted(SPECS.glob("*/spec.md")):
        if re.search(r"^TBD - created", spec.read_text(encoding="utf-8"), re.M):
            problems.append(
                f"{spec.relative_to(ROOT)}: Purpose is the 'TBD - created' placeholder. Add a '## Purpose' "
                "section to the change's delta for this new capability (or write the Purpose in the spec)."
            )

    code, out = run("openspec", "validate", "--specs", "--strict", "--no-interactive")
    if code != 0:
        problems.append("openspec validate --specs --strict failed:\n" + out)

    for path in sorted((ROOT / "openspec").rglob("*")):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if EM_DASH in line:
                    problems.append(f"{path.relative_to(ROOT)}:{n}: em dash (house style bans them)")

    # Uncommitted changes (untracked files too), renames split into delete plus add: plain files under
    # openspec/ only. A clean tree (CI's fast path) has nothing to judge.
    entries = changed_files.worktree_entries(cwd=ROOT)
    if entries:
        ok, reasons = changed_files.check(entries, "openspec")
        if not ok:
            problems.append("changes that are not plain files under openspec/:\n" + "\n".join(reasons))

    for link in changed_files.symlinks_under(CHANGES):
        problems.append(f"{link.relative_to(ROOT)}: symlink under openspec/changes (not allowed)")

    for p in problems:
        print(f"PROBLEM: {p}", flush=True)
    return not problems


def archive(name):
    if name not in active_changes():
        print(f"{name} is not an active change (already archived?); nothing to do.")
        return True
    code, _ = run("openspec", "archive", name, "--yes")
    if code != 0:
        print(f"PROBLEM: openspec archive {name} failed (exit {code}).")
        return False
    if name in active_changes():
        print(f"PROBLEM: openspec archive {name} left openspec/changes/{name} in place.")
        return False
    return check()


def main(argv):
    if argv[:1] == ["list"]:
        print("\n".join(active_changes()))
        return 0
    if argv[:1] == ["check"]:
        return 0 if check() else 1
    if len(argv) == 2 and argv[0] == "archive":
        return 0 if archive(argv[1]) else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
