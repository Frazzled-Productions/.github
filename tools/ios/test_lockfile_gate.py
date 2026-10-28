"""Tests for the Lockfile gate and check in the shared iOS CI (ops #345, light-runner-shared-ci).

Run: python3 -m unittest discover -s tools/ios -p 'test_*.py'

lockfile_gate.py decides, on a light runner, whether the Xcode runner is needed for the Lockfile job:
only when a file that can change the package graph changed, on dispatch, or when the changed files are
unknown. lockfile-check.sh is the Xcode half; here `xcodebuild` is a stub, so nothing is resolved.
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lockfile_gate  # noqa: E402

CHECK = HERE / "lockfile-check.sh"
ZERO = "0" * 40


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PathRules(unittest.TestCase):
    def needs(self, *files):
        return lockfile_gate.needs_lockfile(list(files), "RoastEngine")

    def test_swift_only_is_false(self):
        self.assertFalse(self.needs("RoastConductor/Views/Home.swift", "RoastConductorTests/HomeTests.swift"))

    def test_docs_only_is_false(self):
        self.assertFalse(self.needs("README.md", "openspec/changes/x/tasks.md"))

    def test_package_resolved_is_true(self):
        self.assertTrue(self.needs("RoastConductor.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"))

    def test_project_pbxproj_is_true(self):
        self.assertTrue(self.needs("RoastConductor.xcodeproj/project.pbxproj"))

    def test_project_yml_is_true(self):
        self.assertTrue(self.needs("project.yml"))

    def test_engine_package_file_is_true(self):
        self.assertTrue(self.needs("RoastEngine/Sources/RoastEngine/Roast.swift"))

    def test_engine_prefix_is_not_the_package(self):
        self.assertFalse(self.needs("RoastEngineNotes/plan.swift"))

    def test_any_package_swift_is_true(self):
        self.assertTrue(self.needs("Tools/LocalKit/Package.swift"))

    def test_workflow_file_is_true(self):
        self.assertTrue(self.needs(".github/workflows/ci.yml"))


class Decide(unittest.TestCase):
    """decide() on a real fixture repository."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = cls.repo = cls.tmp.name
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        pathlib.Path(repo, "App.swift").write_text("let a = 1\n")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "base")
        cls.base = git(repo, "rev-parse", "HEAD")
        pathlib.Path(repo, "App.swift").write_text("let a = 2\n")
        git(repo, "commit", "-q", "-am", "code only")
        cls.code = git(repo, "rev-parse", "HEAD")
        pathlib.Path(repo, "project.yml").write_text("name: App\n")
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "project")
        cls.project = git(repo, "rev-parse", "HEAD")
        lock = pathlib.Path(repo, "App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
        lock.parent.mkdir(parents=True)
        lock.write_text('{"pins": [], "version": 3}\n')
        git(repo, "add", "."); git(repo, "commit", "-q", "-m", "lock")
        cls.locked = git(repo, "rev-parse", "HEAD")
        git(repo, "mv", str(lock), str(lock) + ".old"); git(repo, "commit", "-q", "-m", "rename the lockfile away")
        cls.renamed = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", cls.locked)
        git(repo, "rm", "-q", str(lock)); git(repo, "commit", "-q", "-m", "delete the lockfile")
        cls.deleted = git(repo, "rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def decide(self, event, base, head):
        return lockfile_gate.decide(event, base, head, "RoastEngine", cwd=self.repo)[0]

    def test_pull_request_code_only_is_false(self):
        self.assertFalse(self.decide("pull_request", self.base, self.code))

    def test_pull_request_with_project_yml_is_true(self):
        self.assertTrue(self.decide("pull_request", self.base, self.project))

    def test_push_range_code_only_is_false(self):
        self.assertFalse(self.decide("push", self.base, self.code))

    def test_push_range_with_project_yml_is_true(self):
        self.assertTrue(self.decide("push", self.code, self.project))

    def test_lockfile_renamed_away_is_true(self):
        # git diff's rename detection would list only Package.resolved.old.
        self.assertTrue(self.decide("pull_request", self.locked, self.renamed))

    def test_lockfile_deleted_is_true(self):
        self.assertTrue(self.decide("pull_request", self.locked, self.deleted))

    def test_dispatch_is_true(self):
        self.assertTrue(self.decide("workflow_dispatch", "", ""))

    def test_zero_before_is_true(self):
        self.assertTrue(self.decide("push", ZERO, self.code))

    def test_failing_diff_is_true(self):
        self.assertTrue(self.decide("pull_request", "1" * 40, self.code))

    def test_other_event_is_true(self):
        self.assertTrue(self.decide("schedule", "", ""))

    def test_cli_writes_the_output(self):
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
            env = {**os.environ, "GITHUB_OUTPUT": out.name, "EVENT": "pull_request", "BASE": self.base,
                   "HEAD": self.code, "ENGINE_PACKAGE": "RoastEngine"}
            proc = subprocess.run([sys.executable, str(HERE / "lockfile_gate.py")], cwd=self.repo, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out.read().strip(), "run=false")


class Check(unittest.TestCase):
    """lockfile-check.sh with a stub xcodebuild that records its calls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.bin = self.root / "bin"
        self.repo.mkdir(); self.bin.mkdir()
        self.calls = self.root / "xcodebuild.calls"
        stub = self.bin / "xcodebuild"
        # Records its arguments; writes the workspace-state.json the test asks for into the
        # -derivedDataPath; optionally rewrites the lockfile as resolution would.
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$*" >> "{self.calls}"\n'
            'dd=""; prev=""; for a in "$@"; do [ "$prev" = -derivedDataPath ] && dd="$a"; prev="$a"; done\n'
            'mkdir -p "$dd/SourcePackages"\n'
            f'cp "{self.root}/state.json" "$dd/SourcePackages/workspace-state.json"\n'
            f'[ -f "{self.root}/rewrite.json" ] && cp "{self.root}/rewrite.json" "$RESOLVED_FOR_STUB"\n'
            "exit 0\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        self.resolved = self.repo / "App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"

    def tearDown(self):
        self.tmp.cleanup()

    def commit_lock(self, pins):
        self.resolved.parent.mkdir(parents=True, exist_ok=True)
        self.resolved.write_text(json.dumps({"pins": pins, "version": 3}, indent=2) + "\n")
        git(self.repo, "add", "."); git(self.repo, "commit", "-q", "-m", "lock")

    def state(self, identities):
        deps = [{"packageRef": {"identity": i, "kind": "remoteSourceControl"}} for i in identities]
        deps.append({"packageRef": {"identity": "roastengine", "kind": "fileSystem"}})
        (self.root / "state.json").write_text(json.dumps({"object": {"dependencies": deps}}))

    def run_check(self):
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
               "RUNNER_TEMP": str(self.root), "RESOLVED_FOR_STUB": str(self.resolved)}
        return subprocess.run(["bash", str(CHECK), "App.xcodeproj", "App"], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def test_no_lockfile_with_local_packages_only_passes(self):
        (self.repo / "README.md").write_text("x\n")
        git(self.repo, "add", "."); git(self.repo, "commit", "-q", "-m", "init")
        self.state([])
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("No Package.resolved", proc.stdout)
        self.assertIn("-resolvePackageDependencies", self.calls.read_text())

    def test_lockfile_removed_with_remote_packages_fails_naming_them(self):
        pin = {"identity": "swift-collections", "kind": "remoteSourceControl", "location": "x",
               "state": {"revision": "a", "version": "1.1.0"}}
        self.commit_lock([pin])
        git(self.repo, "rm", "-q", str(self.resolved)); git(self.repo, "commit", "-q", "-m", "drop the lockfile")
        self.state(["swift-collections"])
        proc = self.run_check()
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("'swift-collections' is resolved into the build but is not in Package.resolved", proc.stdout)

    def test_complete_lockfile_passes(self):
        pin = {"identity": "swift-collections", "kind": "remoteSourceControl", "location": "x",
               "state": {"revision": "a", "version": "1.1.0"}}
        self.commit_lock([pin])
        self.state(["swift-collections"])
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("-resolvePackageDependencies", self.calls.read_text())

    def test_unpinned_dependency_fails_naming_it(self):
        self.commit_lock([])
        self.state(["swift-issue-reporting"])
        proc = self.run_check()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("'swift-issue-reporting' is resolved into the build but is not in Package.resolved", proc.stdout)

    def test_version_rewritten_by_resolution_fails_naming_it(self):
        pin = {"identity": "swift-crypto", "kind": "remoteSourceControl", "location": "x",
               "state": {"revision": "a", "version": "5.0.0"}}
        self.commit_lock([pin])
        self.state(["swift-crypto"])
        rolled = dict(pin, state={"revision": "b", "version": "4.2.0"})
        (self.root / "rewrite.json").write_text(json.dumps({"pins": [rolled], "version": 3}, indent=2) + "\n")
        proc = self.run_check()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("'swift-crypto' is pinned at 5.0.0 but the build resolves 4.2.0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
