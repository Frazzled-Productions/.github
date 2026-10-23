"""Tests for context_budget.py ("Context budget"). Run: python3 -m unittest discover -s tools/ci -p 'test_*.py'

Each test builds a throwaway git repo. fixtures/koinori-context-budget.txt is Koinori's real
tools/dev/context-budget.txt (qa at 5ad8fdf26, 23 October 2026).
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE / "context_budget.py"
KOINORI = (HERE / "fixtures/koinori-context-budget.txt").read_text()
BUDGET = ".github/context-budget.txt"


def lines(n):
    return "".join(f"line {i}\n" for i in range(n))


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ContextBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, files):
        for path, text in files.items():
            p = self.root / path
            if text is None:
                p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)

    def commit(self, files):
        self.write(files)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "c", "--allow-empty")
        return git(self.root, "rev-parse", "HEAD")

    def run_tool(self, *args):
        proc = subprocess.run([sys.executable, str(TOOL), *args], cwd=self.root, capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def check(self, files, budget_file=BUDGET):
        self.write(files)
        return self.run_tool("--budget-file", budget_file)

    def raise_pr(self, base_budget, head_budget, files=None):
        base = self.commit({BUDGET: base_budget, "AGENTS.md": lines(200), **(files or {})})
        self.commit({BUDGET: head_budget})
        return self.run_tool("--budget-file", BUDGET, "--base", base)

    # Counting

    def test_over_budget_fails(self):
        code, out = self.check({BUDGET: "AGENTS.md\t212\n", "AGENTS.md": lines(215)})
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"AGENTS\.md\s+215\s+212\s+OVER by 3")
        self.assertIn("raise the budget in the same PR", out)

    def test_under_budget_passes_with_a_note(self):
        code, out = self.check({BUDGET: "AGENTS.md\t212\n", "AGENTS.md": lines(210)})
        self.assertEqual(code, 0, out)
        self.assertIn("under by 2", out)

    def test_exactly_on_budget_passes(self):
        code, out = self.check({BUDGET: "AGENTS.md\t212\n", "AGENTS.md": lines(212)})
        self.assertEqual(code, 0, out)

    def test_lines_are_counted_like_grep_c(self):
        # grep -c '' counts a last line with no newline, and an empty file as 0.
        code, out = self.check({BUDGET: "AGENTS.md\t2\nCLAUDE.md\t0\n", "AGENTS.md": "a\nb", "CLAUDE.md": ""})
        self.assertEqual(code, 0, out)
        code, out = self.check({BUDGET: "AGENTS.md\t1\n", "AGENTS.md": "a\nb"})
        self.assertEqual(code, 1, out)

    def test_a_missing_listed_file_counts_zero(self):
        code, out = self.check({BUDGET: "docs/next.md\t40\n"})
        self.assertEqual(code, 0, out)

    def test_glob_sums(self):
        files = {BUDGET: "GLOB:.claude/skills/*/SKILL.md\t10\n",
                 ".claude/skills/a/SKILL.md": lines(6), ".claude/skills/b/SKILL.md": lines(5)}
        code, out = self.check(files)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"\.claude/skills/\*/SKILL\.md\s+11\s+10\s+OVER by 1")

    def test_rules_unscoped_skips_scoped_rules(self):
        scoped = "---\n" + lines(10) + "paths:\n  - x/**\n---\n" + lines(50)
        late = "---\n" + lines(12) + "paths:\n---\n"
        files = {BUDGET: "RULES_UNSCOPED\t19\n", ".claude/rules/a.md": lines(4), ".claude/rules/scoped.md": scoped,
                 ".claude/rules/late.md": late}
        code, out = self.check(files)
        self.assertEqual(code, 0, out)
        # late.md has paths: on line 14, outside the first 12, so it counts: 4 + 15 = 19.
        self.assertRegex(out, r"RULES_UNSCOPED\s+19\s+19")

    def test_comments_and_blank_lines_are_skipped(self):
        code, out = self.check({BUDGET: "# a comment\tthat has a tab 1\n\nAGENTS.md\t5\n", "AGENTS.md": lines(3)})
        self.assertEqual(code, 0, out)

    def test_a_budget_that_is_not_a_number_fails(self):
        code, out = self.check({BUDGET: "AGENTS.md\tlots\n", "AGENTS.md": lines(3)})
        self.assertEqual(code, 1, out)
        self.assertIn("lots", out)

    def test_koinoris_real_file_parses(self):
        code, out = self.check({"tools/dev/context-budget.txt": KOINORI}, budget_file="tools/dev/context-budget.txt")
        self.assertEqual(code, 0, out)
        for label in ("AGENTS.md", "WORKFLOW.md", "docs/next.md", "RULES_UNSCOPED", ".claude/agents/*.md",
                      ".claude/skills/*/SKILL.md"):
            self.assertIn(label, out)

    # A repo with no budget file is given a seed

    def test_missing_budget_file_fails_and_prints_a_seed(self):
        code, out = self.check({"AGENTS.md": lines(212), "CLAUDE.md": "@AGENTS.md\n", ".claude/rules/a.md": lines(7)})
        self.assertEqual(code, 1, out)
        self.assertIn(BUDGET, out)
        self.assertIn("AGENTS.md\t212", out)
        self.assertIn("CLAUDE.md\t1", out)
        self.assertIn("RULES_UNSCOPED\t7", out)

    def test_seed_leaves_out_rules_when_there_are_none(self):
        code, out = self.check({"AGENTS.md": lines(3), "CLAUDE.md": "@AGENTS.md\n"})
        self.assertEqual(code, 1, out)
        self.assertNotIn("RULES_UNSCOPED", out)

    # A raised budget says why

    def test_raise_with_a_reason_passes(self):
        head = "# AGENTS.md budget\n# 212 -> 215 on 2026-10-24: OpenSpec required and Context budget lines (#N)\nAGENTS.md\t215\n"
        code, out = self.raise_pr("# AGENTS.md budget\nAGENTS.md\t212\n", head)
        self.assertEqual(code, 0, out)

    def test_silent_raise_fails_naming_the_entry(self):
        code, out = self.raise_pr("AGENTS.md\t212\n", "AGENTS.md\t215\n")
        self.assertEqual(code, 1, out)
        self.assertIn("AGENTS.md from 212 to 215 needs a reason line", out)

    def test_raise_with_an_old_reason_line_only_fails(self):
        base = "# 200 -> 212 on 2026-10-01: an older raise with its own reason\nAGENTS.md\t212\n"
        head = "# 200 -> 212 on 2026-10-01: an older raise with its own reason\nAGENTS.md\t215\n"
        code, out = self.raise_pr(base, head)
        self.assertEqual(code, 1, out)

    def test_raise_with_a_short_reason_fails(self):
        code, out = self.raise_pr("AGENTS.md\t212\n", "# 212 -> 215: more\nAGENTS.md\t215\n")
        self.assertEqual(code, 1, out)

    def test_raise_reason_above_another_entry_does_not_count(self):
        base = "CLAUDE.md\t1\nAGENTS.md\t212\n"
        head = "# 212 -> 215 on 2026-10-24: a reason placed above the wrong entry\nCLAUDE.md\t1\nAGENTS.md\t215\n"
        code, out = self.raise_pr(base, head)
        self.assertEqual(code, 1, out)

    def test_removed_entry_without_a_line_fails(self):
        code, out = self.raise_pr("AGENTS.md\t212\nCLAUDE.md\t1\n", "CLAUDE.md\t1\n")
        self.assertEqual(code, 1, out)
        self.assertIn("AGENTS.md", out)

    def test_removed_entry_with_a_line_passes(self):
        head = "# removed AGENTS.md: the file moved to docs/agents.md on 2026-10-24\nCLAUDE.md\t1\n"
        code, out = self.raise_pr("AGENTS.md\t212\nCLAUDE.md\t1\n", head)
        self.assertEqual(code, 0, out)

    def test_lowered_passes(self):
        code, out = self.raise_pr("AGENTS.md\t212\n", "AGENTS.md\t205\n")
        self.assertEqual(code, 0, out)

    def test_new_entry_passes(self):
        code, out = self.raise_pr("AGENTS.md\t212\n", "AGENTS.md\t212\nCLAUDE.md\t1\n", files={"CLAUDE.md": "x\n"})
        self.assertEqual(code, 0, out)

    def test_base_without_a_budget_file_needs_no_reasons(self):
        base = self.commit({"AGENTS.md": lines(200)})
        self.commit({BUDGET: "AGENTS.md\t212\n"})
        code, out = self.run_tool("--budget-file", BUDGET, "--base", base)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
