"""Tests for archive.py check. Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'
Needs the openspec CLI (Homebrew, on the CI Mac)."""
import importlib
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

    def test_em_dash_fails(self):
        (self.root / "openspec/changes/c/proposal.md").write_text("# c " + chr(0x2014) + " x\n")
        self.assertFalse(self.archive.check())


if __name__ == "__main__":
    unittest.main()
