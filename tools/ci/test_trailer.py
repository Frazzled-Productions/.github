"""Tests for tools/ci/trailer.py, the AI-attribution check in em-dash-check.yml (ops #345, D7).

Run: python3 -m unittest discover -s tools/ci -p 'test_*.py'

The trailer strings are built from parts so this file never holds one whole (a check over this repo's
own added lines would otherwise match it).
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import trailer  # noqa: E402

CLAUDE = "Clau" + "de"
TRAILERS = [
    "Generated with " + CLAUDE + " Code",
    "Co-Authored-By: " + CLAUDE + " <noreply@example.com>",
    "https://" + CLAUDE.lower() + ".ai/code",
    "https://" + CLAUDE.lower() + ".com/" + CLAUDE.lower() + "-code",
]


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Body(unittest.TestCase):
    def test_each_pattern_in_any_case_fails(self):
        for t in TRAILERS:
            for variant in (t, t.upper(), t.lower()):
                with self.subTest(variant=variant):
                    hits = trailer.body_hits(f"Summary\n\n{variant}\n")
                    self.assertEqual([n for n, _ in hits], [3])

    def test_emoji_prefixed_generated_line_fails(self):
        self.assertTrue(trailer.body_hits("\U0001F916 " + TRAILERS[0] + " (link)"))

    def test_clean_body_passes(self):
        self.assertEqual(trailer.body_hits("Fixes the reap.\n\nCloses #12\n"), [])

    def test_empty_body_passes(self):
        self.assertEqual(trailer.body_hits(""), [])

    def test_mentioning_the_tool_is_not_a_trailer(self):
        self.assertEqual(trailer.body_hits("Ran the " + CLAUDE + " review skill on this."), [])


class Commits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.repo = self.tmp.name
        git(r, "init", "-q", "-b", "main")
        git(r, "config", "user.email", "test@example.com")
        git(r, "config", "user.name", "Test")
        pathlib.Path(r, "a").write_text("1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base\n\n" + TRAILERS[1])  # before the range
        self.base = git(r, "rev-parse", "HEAD")
        pathlib.Path(r, "a").write_text("2\n")
        git(r, "commit", "-q", "-am", "clean change")
        self.clean = git(r, "rev-parse", "HEAD")
        pathlib.Path(r, "a").write_text("3\n")
        git(r, "commit", "-q", "-am", "bad change\n\n" + TRAILERS[1])
        self.bad = git(r, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_range_passes(self):
        self.assertEqual(trailer.commit_hits(self.base, self.clean, cwd=self.repo), [])

    def test_range_with_one_trailer_fails_naming_the_commit(self):
        hits = trailer.commit_hits(self.base, self.head(), cwd=self.repo)
        self.assertEqual([sha for sha, _, _ in hits], [self.bad])
        self.assertEqual(hits[0][1], "bad change")

    def head(self):
        return self.bad

    def run_cli(self, **env):
        full = {**os.environ, "PR_BODY": "", "BASE": "", "HEAD": "", **env}
        return subprocess.run([sys.executable, str(HERE / "trailer.py")], cwd=self.repo, env=full,
                              capture_output=True, text=True)

    def test_cli_pull_request_names_the_commit(self):
        proc = self.run_cli(EVENT="pull_request", BASE=self.base, HEAD=self.bad)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn(self.bad[:7], proc.stdout)

    def test_cli_pull_request_body_fails_naming_the_line(self):
        proc = self.run_cli(EVENT="pull_request", BASE=self.base, HEAD=self.clean,
                            PR_BODY="Summary\n\n" + TRAILERS[0])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("line 3", proc.stdout)

    def test_cli_clean_pull_request_passes(self):
        proc = self.run_cli(EVENT="pull_request", BASE=self.base, HEAD=self.clean, PR_BODY="Fixes #1")
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_cli_push_checks_the_pushed_commits(self):
        proc = self.run_cli(EVENT="push", BASE=self.clean, HEAD=self.bad)
        self.assertEqual(proc.returncode, 1, proc.stdout)

    def test_cli_new_branch_push_skips_commits(self):
        proc = self.run_cli(EVENT="push", BASE="0" * 40, HEAD=self.bad)
        self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()
