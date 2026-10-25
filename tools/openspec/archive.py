#!/usr/bin/env python3
"""Archive OpenSpec changes that have merged to main, and check the result.

Used by the reusable workflows openspec-archive.yml and openspec-docs-check.yml in
Frazzled-Productions/.github; also runs locally against any checkout (the current directory, or
OPENSPEC_ROOT).

  archive.py list              print each active change (not under archive/), in name order
  archive.py archive <name>    run `openspec archive <name> --yes`, then the checks below
  archive.py check             run the checks only
  archive.py simulate          on a temporary copy of openspec/, archive every active change in name
                               order, then run the merged-spec checks (the first two below); the PR
                               check for what the archive after merge would fail (ops #227)

Checks (each failure is printed and makes the exit code 1):
  - no spec Purpose is the "TBD - created" placeholder the archive writes for a new capability
    whose delta had no "## Purpose" section;
  - `openspec validate --specs --strict` passes;
  - `openspec validate --archived` passes: every archived change has all its tasks ticked;
  - no em dash anywhere under openspec/ (house style);
  - the working tree changes nothing but plain files under openspec/ (tools/ci/changed_files.py),
    and nothing under openspec/changes is a symlink.

The em dash is written as chr(0x2014) so this file contains none itself.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # a __pycache__ folder would count as a change outside openspec/
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ci"))
import changed_files  # noqa: E402  tools/ci/changed_files.py

ROOT = pathlib.Path(os.environ.get("OPENSPEC_ROOT", ".")).resolve()
CHANGES = ROOT / "openspec" / "changes"
SPECS = ROOT / "openspec" / "specs"
EM_DASH = chr(0x2014)
ENV = {**os.environ, "OPENSPEC_TELEMETRY": "0", "NO_COLOR": "1"}


def run(*args, cwd=ROOT):
    """Run a command in cwd (ROOT by default), echo its output, and return (exit code, output)."""
    try:
        proc = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True)
    except FileNotFoundError:
        out = f"{args[0]}: command not found on PATH"
        print(f"$ {' '.join(args)}\n{out}\n", flush=True)
        return 127, out
    out = (proc.stdout + proc.stderr).strip()
    print(f"$ {' '.join(args)}\n{out}\n", flush=True)
    return proc.returncode, out


def active_changes():
    if not CHANGES.is_dir():
        return []
    return sorted(p.name for p in CHANGES.iterdir() if p.is_dir() and p.name != "archive" and not p.name.startswith("."))


def spec_problems(root=ROOT):
    """The checks that read the merged specs: no 'TBD - created' Purpose, and strict validation."""
    problems = []
    for spec in sorted((root / "openspec" / "specs").glob("*/spec.md")):
        if re.search(r"^TBD - created", spec.read_text(encoding="utf-8"), re.M):
            problems.append(
                f"{spec.relative_to(root)}: Purpose is the 'TBD - created' placeholder. Add a '## Purpose' "
                "section to the change's delta for this new capability (or write the Purpose in the spec)."
            )

    code, out = run("openspec", "validate", "--specs", "--strict", "--no-interactive", cwd=root)
    if code != 0:
        problems.append("openspec validate --specs --strict failed:\n" + out)
    return problems


def check():
    problems = spec_problems()

    # Every archived change has all its tasks ticked; a task left for later is moved to an issue and
    # ticked as moved ("~~...~~ moved to #N"). With nothing archived yet it passes.
    code, out = run("openspec", "validate", "--archived", "--no-interactive")
    if code != 0:
        problems.append("openspec validate --archived failed (an archived change has an unticked task; "
                        "tick it if done, else move it to an issue and tick it as moved):\n" + out)

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


def simulate():
    """Archive every active change on a copy of openspec/, then run the merged-spec checks there.

    Not `validate --archived`: unticked tasks are the "OpenSpec tasks ticked" check's job, and the
    em dash and symlink checks already run on the real tree. The checkout is never touched."""
    names = active_changes()
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        copy = pathlib.Path(tmp)
        if (ROOT / "openspec").is_dir():
            shutil.copytree(ROOT / "openspec", copy / "openspec", symlinks=True)
        for name in names:
            code, _ = run("openspec", "archive", name, "--yes", cwd=copy)
            if code != 0:
                problems.append(f"openspec archive {name} failed (exit {code}).")
                break
        else:
            problems = spec_problems(copy)
    label = f"Simulated archive of {', '.join(names)}:" if names else "No active changes;"
    if not problems:
        print(f"{label} specs valid", flush=True)
        return True
    print(label, flush=True)
    for p in problems:
        print(f"PROBLEM: {p}", flush=True)
    return False


def main(argv):
    if argv[:1] == ["list"]:
        print("\n".join(active_changes()))
        return 0
    if argv[:1] == ["check"]:
        return 0 if check() else 1
    if argv[:1] == ["simulate"]:
        return 0 if simulate() else 1
    if len(argv) == 2 and argv[0] == "archive":
        return 0 if archive(argv[1]) else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
