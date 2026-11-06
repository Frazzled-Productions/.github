"""Runs openspec-archive.yml's "Archive, open the PR and start its checks" step for real under bash.

Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'
Needs git and the openspec CLI (the pinned binary on self-test).

The step's script is read from the workflow file, so these tests judge what ships. It runs in a clone
of a local bare origin, with the fake gh (which refuses a title over 256 characters, as GitHub does)
and stubs for approve_runs.py and close_resolved.py, which talk to GitHub. Covers the opt-in
`skip-not-started` input and the short titles (koinori #2591).
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import fakegh  # noqa: E402

WORKFLOW = REPO / ".github/workflows/openspec-archive.yml"
STEP = "      - name: Archive, open the PR and start its checks\n        run: |\n"
PROPOSAL = "# c\n\n## Why\nA change used only by these tests, long enough to pass.\n\n## What Changes\n- Nothing real.\n"
RULES = '[{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "CI"}]}}]'
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def step_script():
    text = WORKFLOW.read_text(encoding="utf-8")
    lines = text[text.index(STEP) + len(STEP):].splitlines()
    body = []
    for line in lines:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


class ArchiveStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.origin = self.dir / "origin.git"
        self.work = self.dir / "work"
        seed = self.dir / "seed"
        (seed / "openspec/specs").mkdir(parents=True)
        (seed / "openspec/changes/archive").mkdir(parents=True)
        (seed / "openspec/changes/archive/.gitkeep").write_text("")
        self.seed = seed
        self.git(seed, "init", "-q", "-b", "qa")
        # The tools as the workflow fetches them, with the two GitHub-facing tools stubbed out.
        tools = self.dir / "runner/frazzled-openspec-tools"
        shutil.copytree(REPO / "tools", tools / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        for stub in ("approve_runs.py", "close_resolved.py"):
            (tools / "tools/openspec" / stub).write_text("import sys\nsys.exit(0)\n")
        self.env = {**fakegh.install(self.dir), "GITHUB_REPOSITORY": "Frazzled-Productions/example",
                    "RUN_URL": "https://github.com/Frazzled-Productions/example/actions/runs/1",
                    "RUNNER_TEMP": str(self.dir / "runner"), "BRANCH": "openspec-archive", "BASE": "qa",
                    "REQUIRED_CONTEXTS": "CI", "SKIP_NOT_STARTED": "false", "OPENSPEC_TELEMETRY": "0",
                    "FAKE_GH_API": '{"repos/Frazzled-Productions/example/rules/branches/qa": ' + RULES + "}",
                    "PYTHONDONTWRITEBYTECODE": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd, *args):
        return subprocess.run(["git", *GIT_ID, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def change(self, name, tasks):
        d = self.seed / "openspec/changes" / name
        d.mkdir(parents=True)
        (d / "proposal.md").write_text(PROPOSAL)
        (d / "tasks.md").write_text("# Tasks\n\n## 1. Work\n\n" + tasks)

    def run_step(self, **env):
        self.git(self.seed, "add", "-A")
        self.git(self.seed, "commit", "-qm", "base")
        subprocess.run(["git", "clone", "-q", "--bare", str(self.seed), str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", "-b", "qa", str(self.origin), str(self.work)], check=True)
        proc = subprocess.run(["bash", "-c", step_script()], cwd=self.work, env={**self.env, **env},
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def gh_calls(self, verb):
        return [c for c in fakegh.calls(self.dir) if c[:2] == verb]

    def pushed(self):
        out = subprocess.run(["git", "log", "--format=%s", "qa..openspec-archive"], cwd=self.origin,
                             capture_output=True, text=True)
        return out.stdout.splitlines() if out.returncode == 0 and out.stdout.strip() else []

    # skip-not-started

    def test_skip_on_leaves_a_proposal_and_archives_the_built_change(self):
        self.change("a-proposal", "- [ ] 1.1 a\n- [ ] 1.2 b\n")
        self.change("b-built", "- [x] 1.1 a\n")
        code, out = self.run_step(SKIP_NOT_STARTED="true")
        self.assertEqual(code, 0, out)
        self.assertIn("Not started (no task ticked), left in place: a-proposal", out)
        (create,) = self.gh_calls(["pr", "create"])
        self.assertEqual(fakegh.option(create, "--title"), "Archive OpenSpec change b-built into the main specs")
        self.assertEqual(self.pushed(), ["Archive OpenSpec change b-built into the main specs"])

    def test_skip_off_still_fails_on_a_proposal(self):
        self.change("a-proposal", "- [ ] 1.1 a\n")
        code, out = self.run_step()
        self.assertEqual(code, 1, out)
        (issue,) = self.gh_calls(["issue", "create"])
        self.assertEqual(fakegh.option(issue, "--title"), "OpenSpec archive failed: a-proposal")
        self.assertEqual(self.pushed(), [])

    def test_skip_on_still_fails_on_a_partly_ticked_change(self):
        self.change("a-partial", "- [x] 1.1 a\n- [ ] 1.2 b\n")
        code, out = self.run_step(SKIP_NOT_STARTED="true")
        self.assertEqual(code, 1, out)
        (issue,) = self.gh_calls(["issue", "create"])
        self.assertEqual(fakegh.option(issue, "--title"), "OpenSpec archive failed: a-partial")

    def test_skip_on_with_unreadable_task_counts_fails_and_lands_nothing(self):
        self.change("b-built", "- [x] 1.1 a\n")
        fake = self.dir / "brokenbin"
        fake.mkdir()
        real = shutil.which("openspec")
        self.assertIsNotNone(real, "the openspec CLI must be on PATH")
        # Archive still works; only `openspec list` fails.
        (fake / "openspec").write_text(f'#!/bin/sh\n[ "$1" = list ] && {{ echo broken >&2; exit 7; }}\nexec "{real}" "$@"\n')
        (fake / "openspec").chmod(0o755)
        code, out = self.run_step(SKIP_NOT_STARTED="true", PATH=f"{fake}{os.pathsep}{self.env['PATH']}")
        self.assertEqual(code, 1, out)
        self.assertNotIn("Nothing to archive", out)
        (issue,) = self.gh_calls(["issue", "create"])
        self.assertEqual(fakegh.option(issue, "--title"), "OpenSpec archive failed: all changes")
        self.assertEqual(self.pushed(), [])

    def test_skip_on_with_every_change_not_started_archives_nothing(self):
        self.change("a-proposal", "- [ ] 1.1 a\n")
        code, out = self.run_step(SKIP_NOT_STARTED="true")
        self.assertEqual(code, 0, out)
        self.assertIn("Not started (no task ticked), left in place: a-proposal", out)
        self.assertIn("Nothing to archive.", out)
        self.assertEqual(self.gh_calls(["pr", "create"]), [])
        self.assertEqual(self.pushed(), [])

    # Titles

    def names(self, n):
        return [f"change-{i:02d}-with-a-fairly-long-descriptive-name" for i in range(n)]

    def test_large_run_opens_its_pr_with_a_short_title_and_the_full_list(self):
        names = self.names(6)
        for name in names:
            self.change(name, "- [x] 1.1 a\n")
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        (create,) = self.gh_calls(["pr", "create"])
        self.assertEqual(fakegh.option(create, "--title"), "Archive 6 OpenSpec changes into the main specs")
        for name in names:
            self.assertIn(name, fakegh.option(create, "--body"))

    def test_large_run_failing_after_the_build_opens_its_issue_with_a_short_title(self):
        names = self.names(6)
        for name in names:
            self.change(name, "- [x] 1.1 a\n")
        code, out = self.run_step(FAKE_GH_FAIL="pr create")
        self.assertEqual(code, 1, out)
        (issue,) = self.gh_calls(["issue", "create"])
        self.assertEqual(fakegh.option(issue, "--title"), "OpenSpec archive failed: 6 changes")
        for name in names:
            self.assertIn(name, fakegh.option(issue, "--body"))

    def test_small_run_keeps_the_names_in_the_title(self):
        self.change("a-built", "- [x] 1.1 a\n")
        self.change("b-built", "- [x] 1.1 a\n")
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        (create,) = self.gh_calls(["pr", "create"])
        self.assertEqual(fakegh.option(create, "--title"),
                         "Archive OpenSpec changes a-built, b-built into the main specs")


if __name__ == "__main__":
    unittest.main()
