"""Tests for archive.py check and simulate. Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'
Needs the openspec CLI (Homebrew, on the CI Mac)."""
import contextlib
import importlib
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = """# x Specification

## Purpose
A capability used only by these tests, long enough to satisfy strict validation of a Purpose.

## Requirements

### Requirement: Thing works
The thing SHALL work.

#### Scenario: Works
- **WHEN** used
- **THEN** it works
"""


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "openspec/specs/x").mkdir(parents=True)
        (self.root / "openspec/changes/c").mkdir(parents=True)
        (self.root / "openspec/specs/x/spec.md").write_text(SPEC)
        (self.root / "openspec/changes/c/proposal.md").write_text("# c\n")
        (self.root / "tools").mkdir()
        (self.root / "tools/run.sh").write_text("x\n")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                      "commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)
        os.environ["OPENSPEC_ROOT"] = str(self.root)
        sys.path.insert(0, HERE)
        import archive
        self.archive = importlib.reload(archive)

    def tearDown(self):
        self.tmp.cleanup()
        del os.environ["OPENSPEC_ROOT"]

    def test_clean_tree_passes(self):
        self.assertTrue(self.archive.check())

    def test_change_outside_openspec_fails(self):
        (self.root / "tools/run.sh").write_text("changed\n")
        self.assertFalse(self.archive.check())

    def test_rename_out_of_openspec_fails(self):
        subprocess.run(["git", "mv", "openspec/changes/c/proposal.md", "tools/proposal.md"], cwd=self.root, check=True)
        self.assertFalse(self.archive.check())

    def test_untracked_symlink_in_openspec_fails(self):
        os.symlink("../../../tools/run.sh", self.root / "openspec/specs/x/link.md")
        self.assertFalse(self.archive.check())

    def test_committed_symlink_under_changes_fails(self):
        os.symlink("/etc", self.root / "openspec/changes/c/evil")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "link"], cwd=self.root, check=True)
        self.assertFalse(self.archive.check())

    def test_tbd_purpose_fails(self):
        (self.root / "openspec/specs/x/spec.md").write_text(SPEC.replace(
            "A capability used only", "TBD - created by archiving change c. Update Purpose after archive.\nA capability used only"))
        self.assertFalse(self.archive.check())

    def _archived(self, tasks):
        d = self.root / "openspec/changes/archive/2026-01-01-done"
        (d / "specs/x").mkdir(parents=True)
        (d / "proposal.md").write_text("# done\n\n## Why\nA change used only by these tests, long enough to pass.\n\n## What Changes\n- Nothing real.\n")
        (d / "tasks.md").write_text("# Tasks\n\n## 1. Work\n\n" + tasks)
        (d / "specs/x/spec.md").write_text("## ADDED Requirements\n\n### Requirement: Other\nThe other SHALL work.\n\n#### Scenario: Works\n- **WHEN** used\n- **THEN** it works\n")

    def test_archived_change_with_an_unticked_task_fails(self):
        self._archived("- [x] 1.1 Done\n- [ ] 1.2 Not done\n")
        self.assertFalse(self.archive.check())

    def test_archived_change_with_every_task_ticked_passes(self):
        self._archived("- [x] 1.1 Done\n- [x] 1.2 ~~Device check~~ moved to #12 (23 October 2026)\n")
        self.assertTrue(self.archive.check())

    def test_em_dash_fails(self):
        (self.root / "openspec/changes/c/proposal.md").write_text("# c " + chr(0x2014) + " x\n")
        self.assertFalse(self.archive.check())


def requirement(length):
    """A requirement body of exactly `length` characters, starting with SHALL so strict validation reads it."""
    head = "The thing SHALL work"
    return head + "." * (length - len(head))


def delta(kind, title, body):
    return (f"## {kind} Requirements\n\n### Requirement: {title}\n{body}\n\n"
            "#### Scenario: Works\n- **WHEN** used\n- **THEN** it works\n")


PROPOSAL = "# c\n\n## Why\nA change used only by these tests, long enough to pass.\n\n## What Changes\n- Nothing real.\n"


class Simulate(unittest.TestCase):
    """archive.py simulate: archive every active change on a copy, then validate the merged specs (ops #227)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "repo"
        (self.root / "openspec/specs/x").mkdir(parents=True)
        (self.root / "openspec/changes/archive").mkdir(parents=True)
        (self.root / "openspec/changes/archive/.gitkeep").write_text("")
        (self.root / "openspec/specs/x/spec.md").write_text(SPEC.replace("The thing SHALL work.", requirement(100)))
        self.git("init", "-q", "-b", "main")
        self.commit()
        # Temporary folders go here, so a test can see the copy is gone afterwards.
        self.scratch = pathlib.Path(self.tmp.name) / "scratch"
        self.scratch.mkdir()
        self.old_tempdir, tempfile.tempdir = tempfile.tempdir, str(self.scratch)
        os.environ["OPENSPEC_ROOT"] = str(self.root)
        sys.path.insert(0, HERE)
        import archive
        self.archive = importlib.reload(archive)

    def tearDown(self):
        tempfile.tempdir = self.old_tempdir
        self.tmp.cleanup()
        del os.environ["OPENSPEC_ROOT"]

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "x", "--allow-empty")

    def change(self, name, spec_delta, capability="x", tasks="- [x] 1.1 Done\n"):
        d = self.root / "openspec/changes" / name
        (d / "specs" / capability).mkdir(parents=True)
        (d / "proposal.md").write_text(PROPOSAL)
        (d / "tasks.md").write_text("# Tasks\n\n## 1. Work\n\n" + tasks)
        (d / "specs" / capability / "spec.md").write_text(spec_delta)
        self.commit()

    def simulate(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.archive.main(["simulate", *args])
        return code, out.getvalue()

    def changed_since(self, base):
        """The PR's changed paths, as the workflow writes them, in a file outside the checkout."""
        listing = pathlib.Path(self.tmp.name) / "changed.txt"
        listing.write_text(self.git("diff", "--name-only", base, "HEAD"))
        return str(listing)

    def test_modified_requirement_past_500_fails_while_check_passes(self):
        self.change("c", delta("MODIFIED", "Thing works", requirement(600)))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.archive.check(), "the bug: check passes on the unarchived tree")
        code, out = self.simulate()
        self.assertEqual(code, 1, out)
        self.assertIn("openspec validate --specs --strict failed", out)
        self.assertIn("very long", out)

    def test_change_that_archives_cleanly_passes(self):
        self.change("c", delta("MODIFIED", "Thing works", requirement(300)))
        code, out = self.simulate()
        self.assertEqual(code, 0, out)
        self.assertIn("Simulated archive of c: specs valid", out)

    def test_no_active_change_and_no_specs_passes(self):
        self.git("rm", "-rq", "openspec/specs")
        self.commit()
        code, out = self.simulate()
        self.assertEqual(code, 0, out)
        self.assertIn("No active changes; specs valid", out)

    def test_repo_without_openspec_folder_passes(self):
        # The .github self-test runs the overlap workflow on this repo, which has no openspec/.
        self.git("rm", "-rq", "openspec")
        self.commit()
        code, out = self.simulate()
        self.assertEqual(code, 0, out)
        self.assertIn("No openspec/ folder; nothing to simulate", out)

    def test_two_changes_are_archived_cumulatively_in_name_order(self):
        # Archived the other way round the requirement would end at 300 characters and pass.
        self.change("a-first", delta("MODIFIED", "Thing works", requirement(300)))
        self.change("b-second", delta("MODIFIED", "Thing works", requirement(600)))
        code, out = self.simulate()
        self.assertEqual(code, 1, out)
        self.assertIn("Simulated archive of a-first, b-second", out)
        self.assertIn("very long", out)

    def test_unticked_tasks_do_not_fail_simulate(self):
        self.change("c", delta("MODIFIED", "Thing works", requirement(300)), tasks="- [ ] 1.1 Not done\n")
        code, out = self.simulate()
        self.assertEqual(code, 0, out)

    def test_new_capability_without_purpose_fails(self):
        self.change("c", delta("ADDED", "New thing", requirement(100)), capability="y")
        code, out = self.simulate()
        self.assertEqual(code, 1, out)
        self.assertIn("TBD - created", out)

    def test_openspec_missing_fails_with_the_reason(self):
        self.change("c", delta("MODIFIED", "Thing works", requirement(300)))
        self.archive.ENV["PATH"] = "/usr/bin:/bin"
        code, out = self.simulate()
        self.assertEqual(code, 1, out)
        self.assertIn("openspec", out)
        self.assertIn("not found", out)

    def test_change_stuck_on_main_is_named_already_on_main(self):
        # The archive bot failed after this change merged, so it sits on main; the PR touches a README.
        self.change("stuck", delta("MODIFIED", "Thing works", requirement(600)))
        base = self.git("rev-parse", "HEAD").strip()
        (self.root / "README.md").write_text("docs\n")
        self.commit()
        code, out = self.simulate("--changed-files", self.changed_since(base))
        self.assertEqual(code, 1, out)
        self.assertIn("Simulated archive of stuck (already on main):", out)

    def test_change_the_pr_adds_is_named_from_this_pr(self):
        self.change("a-stuck", delta("MODIFIED", "Thing works", requirement(600)))
        base = self.git("rev-parse", "HEAD").strip()
        self.change("b-new", delta("ADDED", "Other thing", requirement(100)))
        code, out = self.simulate("--changed-files", self.changed_since(base))
        self.assertEqual(code, 1, out)
        self.assertIn("Simulated archive of a-stuck (already on main), b-new (from this PR):", out)

    def test_failed_archive_problem_line_gives_the_reason(self):
        self.change("c", delta("MODIFIED", "Missing one", requirement(100)))
        code, out = self.simulate()
        self.assertEqual(code, 1, out)
        problem = [line for line in out.splitlines() if line.startswith("PROBLEM:")]
        self.assertEqual(len(problem), 1, out)
        self.assertIn("openspec archive c failed (exit 1)", problem[0])
        self.assertIn("not found", problem[0])

    def test_checkout_and_temp_folder_left_alone(self):
        self.change("c", delta("MODIFIED", "Thing works", requirement(600)))
        before = (self.git("status", "--porcelain"), sorted(str(p) for p in self.root.rglob("*")))
        self.simulate()
        after = (self.git("status", "--porcelain"), sorted(str(p) for p in self.root.rglob("*")))
        self.assertEqual(before, after)
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
