"""Tests for report-failure.sh (fail <what> <why>), run for real under bash with a fake gh.

Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'

The failing step must end with the real error (not the generic reason alone), and the issue must open
with it, so the step's echoed script source is never taken for the error (roast-conductor #186,
run 39938831804, where the only error in the job log was "Archiving or the checks failed").
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fakegh  # noqa: E402

REPORTER = HERE / "report-failure.sh"
FIXTURE_186 = HERE / "fixtures" / "issue-186-archive.log"
HEADER = "Why the OpenSpec archive failed"
NOTE = "The script printed at the start of each step is its source, not output."
RUN_URL = "https://github.com/Frazzled-Productions/example/actions/runs/1"


class Reporter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.env = {**fakegh.install(self.dir), "GITHUB_REPOSITORY": "Frazzled-Productions/example",
                    "RUN_URL": RUN_URL, "BASE": "main"}

    def tearDown(self):
        self.tmp.cleanup()

    def fail(self, what, why, log_text, issues="[]"):
        (self.dir / "out.log").write_text(log_text, encoding="utf-8")
        script = 'set +e -uo pipefail; source "$1"; cat "$2" >> "$LOG"; fail "$3" "$4"'
        proc = subprocess.run(["bash", "-c", script, "bash", str(REPORTER), str(self.dir / "out.log"), what, why],
                              env={**self.env, "FAKE_GH_ISSUES": issues}, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        return proc.stdout.splitlines()

    def tail_block(self, lines):
        """The lines from the last header to the end; asserts the header is there."""
        starts = [i for i, line in enumerate(lines) if HEADER in line]
        self.assertTrue(starts, "no 'Why' block in:\n" + "\n".join(lines))
        return lines[starts[-1]:]

    def body(self, verb):
        call = next(c for c in fakegh.calls(self.dir) if c[:2] == ["issue", verb])
        return fakegh.option(call, "--body")

    def test_186_log_ends_with_the_real_error(self):
        lines = self.fail("watch-screenshot-layout", "Archiving or the checks failed (output below).",
                          FIXTURE_186.read_text(encoding="utf-8"))
        block = self.tail_block(lines)
        self.assertEqual(block[-1], NOTE)
        self.assertEqual(block[-2], "Issue: " + fakegh.ISSUE_URL)
        errors = [line for line in block if line.startswith("::error")]
        self.assertTrue(any("Archiving or the checks failed" in e for e in errors))
        problem = [e for e in errors if "2 incomplete tasks (9/11 completed)" in e]
        self.assertEqual(len(problem), 1, errors)
        self.assertTrue(problem[0].startswith("::error::PROBLEM: openspec validate --archived failed"))
        self.assertIn("%0A", problem[0])  # one annotation, its lines encoded, not one command per line
        self.assertNotIn("Specs updated successfully", "\n".join(block))  # only the error, not the whole log

    def test_186_issue_opens_with_the_real_error(self):
        self.fail("watch-screenshot-layout", "Archiving or the checks failed (output below).",
                  FIXTURE_186.read_text(encoding="utf-8"))
        create = next(c for c in fakegh.calls(self.dir) if c[:2] == ["issue", "create"])
        self.assertEqual(fakegh.option(create, "--title"), "OpenSpec archive failed: watch-screenshot-layout")
        body = self.body("create")
        why, problem, run = body.index("## Why it failed"), body.index("2 incomplete tasks (9/11 completed)"), body.index("Run: " + RUN_URL)
        self.assertLess(why, problem)
        self.assertLess(problem, run)
        self.assertLess(run, body.index("<details>"))
        self.assertIn("unticked task", body[body.index("</details>"):])  # the common causes include it
        self.assertNotIn("usually", body)
        self.assertNotIn("✓ spec/alarms", body)

    def test_second_failure_comments_with_the_same_opening(self):
        issues = json.dumps([{"number": 7, "title": "OpenSpec archive failed: watch-screenshot-layout"}])
        lines = self.fail("watch-screenshot-layout", "Archiving or the checks failed (output below).",
                          FIXTURE_186.read_text(encoding="utf-8"), issues)
        self.assertFalse([c for c in fakegh.calls(self.dir) if c[:2] == ["issue", "create"]])
        body = self.body("comment")
        self.assertLess(body.index("## Why it failed"), body.index("Run: " + RUN_URL))
        self.assertIn("2 incomplete tasks (9/11 completed)", body.split("Run: ")[0])
        self.assertEqual(self.tail_block(lines)[-2], "Issue: https://github.com/Frazzled-Productions/example/issues/7#issuecomment-1")

    def test_no_problem_lines_gives_the_last_20_lines(self):
        log = "".join(f"line {n}\n" for n in range(1, 31)) + "HTTP 403: GitHub Actions is not permitted to create pull requests\n"
        lines = self.fail("add-x", "Could not open the archive PR.", log)
        block = self.tail_block(lines)
        errors = [line for line in block if line.startswith("::error::") and "%0A" in line]
        self.assertEqual(len(errors), 1)
        shown = errors[0][len("::error::"):].split("%0A")
        self.assertEqual(len(shown), 20)
        self.assertEqual(shown[0], "line 12")
        self.assertEqual(shown[-1], "HTTP 403: GitHub Actions is not permitted to create pull requests")
        self.assertIn("HTTP 403", self.body("create").split("Run: ")[0])

    def test_stuck_check_ends_with_the_checks(self):
        log = "Engine and app tests / Engine and app tests\tcompleted\tfailure\nTest integrity / Test integrity\tcompleted\tsuccess\n"
        lines = self.fail("#42", "The archive PR #42 has been open for 31 minutes without merging.", log)
        block = "\n".join(self.tail_block(lines))
        self.assertIn("Engine and app tests / Engine and app tests\tcompleted\tfailure", block)

    def test_log_text_cannot_issue_workflow_commands(self):
        log = "PROBLEM: bad spec\n::add-mask::secret\n::warning::injected\n%0A::error::also\n"
        block = self.tail_block(self.fail("add-x", "Archiving or the checks failed (output below).", log))
        commands = [line for line in block if line.startswith("::")]
        self.assertTrue(all(line.startswith("::error") for line in commands), commands)
        self.assertEqual(len(commands), 2)  # the reason and the one PROBLEM block
        self.assertIn("%250A::error::also", commands[1])  # a literal %0A stays text

    def test_issue_cannot_be_opened(self):
        self.env["FAKE_GH_FAIL"] = "issue create"
        block = self.tail_block(self.fail("add-x", "Could not push.", "PROBLEM: push refused\n"))
        self.assertEqual(block[-1], NOTE)
        self.assertIn("Could not open or comment on the issue", block[-2])
        self.assertTrue(any("PROBLEM: push refused" in line for line in block))


if __name__ == "__main__":
    unittest.main()
