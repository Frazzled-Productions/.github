"""Tests for tools/ci/changed_files.py. Run: python3 -m unittest discover -s tools/ci -p 'test_*.py'

Each git test builds a throwaway repo, makes one change and asks which kind of change it is.
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changed_files as cf  # noqa: E402

SOURCE_DIRS = ["RoastConductor", "Shared", "WatchShared", "RoastConductorTests", "RoastConductorWidgets",
               "RoastConductorWatch", "RoastConductorWatchWidgets", "RoastEngine", "Config"]


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class Repo:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name)
        git(self.path, "init", "-q", "-b", "main")
        git(self.path, "config", "user.name", "t")
        git(self.path, "config", "user.email", "t@example.invalid")
        git(self.path, "config", "commit.gpgsign", "false")
        for p in ["README.md", "docs/a.md", "openspec/specs/x/spec.md", "openspec/changes/c/specs/x/spec.md",
                  "RoastConductor/Foo.swift", "RoastEngine/Package.swift", "tools/run.sh"]:
            self.write(p, "base\n")
        self.commit("base")
        self.base = self.head()

    def write(self, p, text):
        f = self.path / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def commit(self, msg="change"):
        git(self.path, "add", "-A")
        git(self.path, "commit", "-qm", msg, "--allow-empty")

    def head(self):
        return git(self.path, "rev-parse", "HEAD").strip()

    def kind(self, rule):
        return cf.check(cf.diff_entries(f"{self.base}...{self.head()}", cwd=self.path), rule)


class DocsOnlyRule(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.tmp.cleanup()

    def ok(self, rule="docs"):
        self.r.commit()
        return self.r.kind(rule)[0]

    def test_markdown_and_openspec_edits_are_docs_only(self):
        self.r.write("README.md", "new\n")
        self.r.write("docs/a.md", "new\n")
        self.r.write("docs/new/b.md", "new\n")
        self.r.write("openspec/specs/x/spec.md", "new\n")
        self.r.write("openspec/changes/c/.openspec.yaml", "schema: spec-driven\n")
        self.assertTrue(self.ok())

    def test_archive_deleting_openspec_deltas_is_docs_only(self):
        git(self.r.path, "mv", "openspec/changes/c", "openspec/changes/archive-c")
        self.assertTrue(self.ok())

    def test_rename_of_code_to_markdown_is_not_docs_only(self):
        git(self.r.path, "mv", "RoastConductor/Foo.swift", "Foo.md")
        self.assertFalse(self.ok())

    def test_rename_of_package_swift_into_docs_is_not_docs_only(self):
        git(self.r.path, "mv", "RoastEngine/Package.swift", "docs/Package.md")
        self.assertFalse(self.ok())

    def test_deleting_a_non_openspec_markdown_file_is_not_docs_only(self):
        git(self.r.path, "rm", "-q", "docs/a.md")
        self.assertFalse(self.ok())

    def test_any_code_change_is_not_docs_only(self):
        self.r.write("README.md", "new\n")
        self.r.write("tools/run.sh", "new\n")
        self.assertFalse(self.ok())

    def test_markdown_inside_source_dirs_is_not_docs_only(self):
        for d in SOURCE_DIRS:
            with self.subTest(d=d):
                r = Repo()
                r.write(f"{d}/Notes.md", "x\n")
                r.commit()
                self.assertFalse(r.kind("docs")[0])
                r.tmp.cleanup()

    def test_symlink_is_not_docs_only(self):
        os.symlink("../RoastConductor/Foo.swift", self.r.path / "docs/link.md")
        self.assertFalse(self.ok())

    def test_symlink_under_openspec_is_not_docs_only(self):
        os.symlink("../../RoastEngine/Package.swift", self.r.path / "openspec/specs/link.md")
        self.assertFalse(self.ok())

    def test_executable_markdown_is_not_docs_only(self):
        self.r.write("docs/run.md", "x\n")
        os.chmod(self.r.path / "docs/run.md", 0o755)
        self.assertFalse(self.ok())

    def test_mode_change_is_not_docs_only(self):
        os.chmod(self.r.path / "README.md", 0o755)
        self.assertFalse(self.ok())

    def test_no_changes_is_not_docs_only(self):
        self.assertFalse(self.ok())

    def test_paths_with_spaces_and_newlines(self):
        self.r.write("docs/odd name\nwith newline.md", "x\n")
        self.assertTrue(self.ok())


class OpenSpecOnlyRule(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.tmp.cleanup()

    def test_archive_is_openspec_only(self):
        git(self.r.path, "mv", "openspec/changes/c", "openspec/changes/archive-c")
        self.r.write("openspec/specs/x/spec.md", "new\n")
        self.r.commit()
        self.assertTrue(self.r.kind("openspec")[0])

    def test_markdown_outside_openspec_is_not_openspec_only(self):
        self.r.write("README.md", "new\n")
        self.r.commit()
        self.assertFalse(self.r.kind("openspec")[0])

    def test_rename_out_of_openspec_is_not_openspec_only(self):
        git(self.r.path, "mv", "openspec/specs/x/spec.md", "RoastConductor/spec.swift")
        self.r.commit()
        self.assertFalse(self.r.kind("openspec")[0])

    def test_working_tree_with_untracked_files(self):
        self.r.write("openspec/specs/y/spec.md", "new\n")
        self.assertTrue(cf.check(cf.worktree_entries(cwd=self.r.path), "openspec")[0])
        self.r.write("tools/new.sh", "x\n")
        self.assertFalse(cf.check(cf.worktree_entries(cwd=self.r.path), "openspec")[0])

    def test_untracked_symlink_is_rejected(self):
        os.symlink("../../RoastEngine/Package.swift", self.r.path / "openspec/specs/link.md")
        self.assertFalse(cf.check(cf.worktree_entries(cwd=self.r.path), "openspec")[0])


class SymlinksUnderChanges(unittest.TestCase):
    def test_symlinks_found(self):
        r = Repo()
        self.assertEqual(cf.symlinks_under(r.path / "openspec/changes"), [])
        os.symlink("/etc", r.path / "openspec/changes/c/evil")
        self.assertEqual([p.name for p in cf.symlinks_under(r.path / "openspec/changes")], ["evil"])
        r.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
