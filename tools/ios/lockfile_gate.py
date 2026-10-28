"""Lockfile gate: does this change need the Lockfile job on the Xcode runner? (ops #345)

Runs on a light runner in ios-ci.yml. Prints the reason and writes `run=true` or `run=false` to
$GITHUB_OUTPUT. True when a file that can change the package graph changed (Package.resolved,
project.pbxproj, project.yml, a file in the engine package, any Package.swift, a workflow file), on
dispatch, and whenever the changed files are unknown (a new branch, a failing diff, another event):
the gate fails safe towards running the check.

Environment: EVENT (github.event_name), BASE and HEAD (PR base and head, or push before and after),
ENGINE_PACKAGE. Tests: tools/ios/test_lockfile_gate.py.
"""
import os
import subprocess
import sys


def needs_lockfile(files, engine_package):
    """True when any of `files` can change what the build resolves."""
    engine = engine_package.strip("/") + "/" if engine_package.strip("/") else None
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if name in ("Package.resolved", "project.pbxproj", "project.yml", "Package.swift"):
            return True
        if f.startswith(".github/workflows/"):
            return True
        if engine and f.startswith(engine):
            return True
    return False


def decide(event, base, head, engine_package, cwd=None):
    """Return (run, reason)."""
    if event == "workflow_dispatch":
        return True, "manual run"
    if event in ("pull_request", "pull_request_target"):
        spec = f"{base}...{head}"
    elif event == "push":
        if not base or set(base) == {"0"}:
            return True, "new branch push: changed files unknown"
        spec = f"{base}..{head}"
    else:
        return True, f"{event or 'unknown'} event: changed files unknown"
    if not base or not head:
        return True, "no commit range: changed files unknown"
    # --no-renames: a rename lists only the new path, so Package.resolved renamed away would be hidden.
    proc = subprocess.run(["git", "diff", "--name-only", "--no-renames", spec], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        return True, f"git diff {spec} failed: changed files unknown"
    files = [line for line in proc.stdout.splitlines() if line]
    if needs_lockfile(files, engine_package):
        return True, "a package, project or workflow file changed"
    return False, f"none of the {len(files)} changed files can change the package graph"


def main():
    run, reason = decide(os.environ.get("EVENT", ""), os.environ.get("BASE", ""), os.environ.get("HEAD", ""),
                         os.environ.get("ENGINE_PACKAGE", ""))
    print(f"Lockfile check needed: {'yes' if run else 'no'} ({reason}).")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
