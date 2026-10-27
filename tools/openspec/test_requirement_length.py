"""Tests for requirement_length.py. Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'
The cross-checks against OpenSpec need the openspec CLI (Homebrew on the Mac, npm on self-test)."""
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requirement_length  # noqa: E402

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
SCENARIO = "\n#### Scenario: Works\n- **WHEN** used\n- **THEN** it works\n"


def body(n):
    """Requirement text of exactly n characters as OpenSpec counts it: two lines joined by a newline."""
    first = "The thing SHALL work, and this first line wraps"
    return first + "\n" + "y" * (n - len(first) - 1)


def delta(section, text, extra=""):
    title = "Thing works" if section == "MODIFIED" else "Other thing"
    return f"## {section} Requirements\n\n### Requirement: {title}\n{text}\n{extra}{SCENARIO}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "openspec/specs/x").mkdir(parents=True)
        (self.root / "openspec/specs/x/spec.md").write_text(SPEC)

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, text, name="c"):
        d = self.root / "openspec/changes" / name
        (d / "specs/x").mkdir(parents=True)
        (d / "proposal.md").write_text("## Why\nA change used only by these tests, to check requirement length.\n\n"
                                       "## What Changes\n- The thing changes.\n")
        (d / "tasks.md").write_text("## 1. Build\n\n- [x] 1.1 Done\n")
        (d / "specs/x/spec.md").write_text(text)

    def problems(self):
        with redirect_stdout(io.StringIO()):
            return requirement_length.check(self.root)


class Lint(Base):
    def test_modified_501_fails_and_names_file_requirement_and_length(self):
        self.change(delta("MODIFIED", body(501)))
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("openspec/changes/c/specs/x/spec.md", problems[0])
        self.assertIn('MODIFIED requirement "Thing works" is 501 characters', problems[0])
        self.assertIn("move examples and edge cases into scenarios", problems[0])

    def test_modified_500_passes(self):
        self.change(delta("MODIFIED", body(500)))
        self.assertEqual(self.problems(), [])

    def test_added_501_fails(self):
        self.change(delta("ADDED", body(501)))
        self.assertIn('ADDED requirement "Other thing" is 501 characters', self.problems()[0])

    def test_scenarios_blank_lines_and_fenced_code_do_not_count(self):
        fenced = "\n```\n" + "z" * 600 + "\n```\n\n"
        self.change(delta("MODIFIED", body(500), extra=fenced + "#### Scenario: Long\n- **WHEN** " + "w" * 600 + "\n"))
        self.assertEqual(self.problems(), [])

    def test_removed_and_archived_are_not_checked(self):
        self.change("## REMOVED Requirements\n\n### Requirement: Thing works\n" + body(900) + "\n")
        self.change(delta("MODIFIED", body(900)), name="archive/2026-10-01-old")
        self.assertEqual(self.problems(), [])

    def test_bom_crlf_and_lower_case_headers_still_checked(self):
        # OpenSpec strips a BOM, normalises CRLF and matches section headers in any case.
        text = "\ufeff" + delta("MODIFIED", body(501)).replace("## MODIFIED Requirements", "## modified requirements")
        self.change(text.replace("\n", "\r\n"))
        self.assertEqual(len(self.problems()), 1)

    def test_metadata_only_body_is_counted(self):
        self.change(delta("MODIFIED", "**Rule**: The thing SHALL " + "m" * 480))
        self.assertIn("is 506 characters", self.problems()[0])

    def test_counts_utf16_code_units_like_javascript(self):
        # Each emoji is two UTF-16 code units: 498 + 2 = 500 passes, 499 + 2 = 501 fails.
        self.change(delta("MODIFIED", body(498) + "\N{GRINNING FACE}"))
        self.assertEqual(self.problems(), [])
        shutil.rmtree(self.root / "openspec/changes/c")
        self.change(delta("MODIFIED", body(499) + "\N{GRINNING FACE}"))
        self.assertEqual(len(self.problems()), 1)


@unittest.skipUnless(shutil.which("openspec"), "needs the openspec CLI")
class MatchesOpenSpec(Base):
    """The lint fails exactly where OpenSpec's post-archive `validate --specs --strict` fails."""

    def openspec(self, *args):
        env = {**os.environ, "OPENSPEC_TELEMETRY": "0", "NO_COLOR": "1"}
        return subprocess.run(["openspec", *args, "--no-interactive"], cwd=self.root, env=env,
                              capture_output=True, text=True).returncode

    def archived_specs_valid(self):
        subprocess.run(["openspec", "archive", "c", "--yes"], cwd=self.root, capture_output=True,
                       env={**os.environ, "OPENSPEC_TELEMETRY": "0"}, check=True)
        return self.openspec("validate", "--specs", "--strict") == 0

    def test_501_passes_change_validation_but_fails_after_archive(self):
        self.change(delta("MODIFIED", body(501)))
        self.assertEqual(self.openspec("validate", "--changes", "--strict"), 0, "the gap ops #313 is about")
        self.assertTrue(self.problems())
        self.assertFalse(self.archived_specs_valid())

    def test_500_passes_both(self):
        self.change(delta("MODIFIED", body(500)))
        self.assertEqual(self.problems(), [])
        self.assertTrue(self.archived_specs_valid())


if __name__ == "__main__":
    unittest.main()
