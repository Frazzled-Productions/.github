"""Tests for the "Fetch the shared OpenSpec tools" step in the openspec-*.yml reusable workflows.

Run: python3 -m unittest discover -s tools/ci -p 'test_*.py'   (needs git and access to github.com)

The step is copied into each workflow, so the test first checks every copy is identical, then runs it
with a made-up job context: a commit SHA and an annotated tag object's SHA must fetch that commit; a
non-SHA, an unknown SHA or a bad repository name must fail before any tool is used.
"""
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("openspec-*.yml"))
STEP = "- name: Fetch the shared OpenSpec tools at this workflow's commit"
REPO = "Frazzled-Productions/.github"
# v1.1.0 is an annotated tag on 8ca80e1 (the release holding the shared OpenSpec workflows).
COMMIT = "8ca80e192552baf33aabd101f17e2c77f95ebe0c"
TAG = "v1.1.0"


def fetch_steps(text):
    """Return the run script of every fetch step in a workflow file."""
    lines, scripts = text.splitlines(), []
    for i, line in enumerate(lines):
        if line.strip() != STEP:
            continue
        j = next(k for k in range(i + 1, len(lines)) if lines[k].strip() == "run: |")
        indent = len(lines[j]) - len(lines[j].lstrip()) + 2
        body = []
        for k in range(j + 1, len(lines)):
            if lines[k].strip() and len(lines[k]) - len(lines[k].lstrip()) < indent:
                break
            body.append(lines[k][indent:])
        scripts.append("\n".join(body).rstrip() + "\n")
    return scripts


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


class FetchGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = [s for w in WORKFLOWS for s in fetch_steps(w.read_text(encoding="utf-8"))]
        out = git("ls-remote", f"https://github.com/{REPO}", f"refs/tags/{TAG}", f"refs/tags/{TAG}^{{}}")
        refs = dict(reversed(line.split("\t")) for line in out.splitlines())
        cls.tag_object = refs[f"refs/tags/{TAG}"]
        cls.tag_commit = refs[f"refs/tags/{TAG}^{{}}"]

    def run_step(self, repo, sha):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "RUNNER_TEMP": tmp, "GITHUB_SERVER_URL": "https://github.com",
                   "JOB_CONTEXT": json.dumps({"workflow_repository": repo, "workflow_sha": sha})}
            proc = subprocess.run(["bash", "-c", self.scripts[0]], env=env, capture_output=True, text=True)
            head = None
            tools = pathlib.Path(tmp, "frazzled-openspec-tools")
            if proc.returncode == 0:
                head = git("-C", str(tools), "rev-parse", "HEAD")
            return proc.returncode, head, proc.stdout + proc.stderr

    def test_every_workflow_has_the_same_step(self):
        self.assertEqual(len(self.scripts), len(WORKFLOWS) + 1)  # openspec-archive.yml has two jobs
        self.assertEqual(len(set(self.scripts)), 1)

    def test_v1_1_0_is_annotated(self):
        self.assertEqual(self.tag_commit, COMMIT)
        self.assertNotEqual(self.tag_object, COMMIT)

    def test_commit_sha_fetches_that_commit(self):
        code, head, out = self.run_step(REPO, COMMIT)
        self.assertEqual(code, 0, out)
        self.assertEqual(head, COMMIT)

    def test_annotated_tag_object_fetches_its_commit(self):
        code, head, out = self.run_step(REPO, self.tag_object)
        self.assertEqual(code, 0, out)
        self.assertEqual(head, COMMIT)

    def test_a_tag_name_is_refused(self):
        code, _, out = self.run_step(REPO, "v1")
        self.assertNotEqual(code, 0, out)

    def test_an_unknown_sha_is_refused(self):
        code, _, out = self.run_step(REPO, "0" * 39 + "1")
        self.assertNotEqual(code, 0, out)

    def test_a_bad_repository_is_refused(self):
        code, _, out = self.run_step("not a repo", COMMIT)
        self.assertNotEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
