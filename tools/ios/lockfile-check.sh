#!/usr/bin/env bash
#
# lockfile-check.sh <project> <scheme> [<Package.resolved>]: the lockfile records what the build
# resolves (ops #345). From koinori's ci.yml Lockfile job (koinori #1942 and the 2026-10-05 Dependabot
# rollback, origin/qa 217b3f179), with the project and lockfile paths as arguments.
#
#   1. Every remote package the build resolves (DerivedData's workspace-state.json, which is what the
#      build actually used) is pinned in Package.resolved. Diffing the file alone misses this:
#      resolution can pull in a new transitive package without writing it back.
#   2. Resolving leaves Package.resolved unchanged; a change means a pinned version is outside a
#      dependency's range, and resolution silently picked another.
# With no Package.resolved (an app with no remote packages) it passes with a note and resolves nothing.
# The lockfile defaults to <project>/project.xcworkspace/xcshareddata/swiftpm/Package.resolved.
# Tests: tools/ios/test_lockfile_gate.py.

set -uo pipefail

project="${1:?usage: lockfile-check.sh <project> <scheme> [<Package.resolved>]}"
scheme="${2:?usage: lockfile-check.sh <project> <scheme> [<Package.resolved>]}"
lock="${3:-$project/project.xcworkspace/xcshareddata/swiftpm/Package.resolved}"

if [ ! -f "$lock" ]; then
  echo "No Package.resolved at $lock: the app pins no remote packages, so there is nothing to check."
  exit 0
fi

dd="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/lockfile-dd"
log="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/lockfile-resolve.log"
committed="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/lockfile-committed.json"
rm -rf "$dd"
cp "$lock" "$committed"

xcodebuild -resolvePackageDependencies -project "$project" -scheme "$scheme" -derivedDataPath "$dd" >"$log" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "::error::Could not resolve packages (exit $rc); last lines follow."
  tail -20 "$log"
  exit "$rc"
fi

python3 - "$committed" "$lock" "$dd/SourcePackages/workspace-state.json" "$project" "$scheme" <<'PY'
import json, sys
committed_path, lock_path, state_path, project, scheme = sys.argv[1:6]

def pins(path):
    return {p["identity"]: p.get("state", {}) for p in json.load(open(path, encoding="utf-8")).get("pins", [])}

committed, resolved = pins(committed_path), pins(lock_path)
obj = json.load(open(state_path, encoding="utf-8")).get("object", {})
# Local packages have no remote to pin, so they are not lockfile entries.
used = {d["packageRef"]["identity"] for d in obj.get("dependencies", [])
        if d.get("packageRef", {}).get("kind") not in ("local", "fileSystem")}
bad = False
for m in sorted(used - set(committed)):
    print(f"::error::'{m}' is resolved into the build but is not in Package.resolved.")
    bad = True
for ident in sorted(set(committed) | set(resolved)):
    before, after = committed.get(ident), resolved.get(ident)
    if before == after:
        continue
    bad = True
    if after is None:
        print(f"::error::'{ident}' is pinned in Package.resolved but resolution dropped it.")
    elif before is None:
        print(f"::error::'{ident}' was added to Package.resolved by resolution.")
    else:
        print(f"::error::'{ident}' is pinned at {before.get('version') or before.get('revision')} but the build "
              f"resolves {after.get('version') or after.get('revision')}.")
if bad:
    print("::error::The committed lockfile does not describe what this build uses. Run:")
    print(f"::error::xcodebuild -resolvePackageDependencies -project {project} -scheme {scheme}, then commit")
    print("::error::Package.resolved. A Dependabot bump edits version strings without running resolution,")
    print("::error::so it can pin a version outside a dependency's range or miss a new transitive package.")
    sys.exit(1)
print("Lockfile is complete and its versions are the ones the build resolves.")
PY
