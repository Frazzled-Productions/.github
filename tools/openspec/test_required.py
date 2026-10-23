"""Tests for required.py ("OpenSpec required"). Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'

Each test builds a throwaway git repo with a base commit and a PR head commit, and answers the PR and
its issue events through the fake gh (fakegh.py).
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

TOOL = HERE / "required.py"
REPO = "Frazzled-Productions/example"
PR = 7
FRASER = "fraserbrookhouse"
SWIFT = "RoastConductor/Views/MenuView.swift"
DELTA = "## ADDED Requirements\n\n### Requirement: X\nIt SHALL x.\n\n#### Scenario: x\n- **WHEN** x\n- **THEN** x\n"
BASE_FILES = {"openspec/config.yaml": "schema: spec-driven\n", SWIFT: "// menu\n", "AGENTS.md": "# Agents\n"}


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def labelled(login, name="no-spec", at="2026-10-23T10:00:00Z", event="labeled"):
    return {"event": event, "label": {"name": name}, "actor": {"login": login}, "created_at": at}


class Required(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.root = self.dir / "repo"
        self.root.mkdir()
        self.env = fakegh.install(self.dir)

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

    def pr(self, change, base=None, author="someone", labels=(), body="", events=(), comments=(),
           budget=".github/context-budget.txt"):
        """Commit base, then change on top; run the tool. Returns (exit code, output)."""
        git(self.root, "init", "-q", "-b", "main")
        self.write(BASE_FILES if base is None else base)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base", "--allow-empty")
        base_sha = git(self.root, "rev-parse", "HEAD")
        self.write(change)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "head", "--allow-empty")
        head_sha = git(self.root, "rev-parse", "HEAD")
        self.env["FAKE_GH_API"] = json.dumps({
            f"repos/{REPO}/pulls/{PR}": {"user": {"login": author}, "body": body,
                                         "labels": [{"name": n} for n in labels]},
            f"repos/{REPO}/issues/{PR}/events": list(events),
            f"repos/{REPO}/issues/{PR}/comments": list(comments)})
        return self.run_tool(base_sha, head_sha, budget)

    def run_tool(self, base_sha, head_sha, budget):
        proc = subprocess.run([sys.executable, str(TOOL), "--repo", REPO, "--pr", str(PR), "--base", base_sha,
                               "--head", head_sha, "--budget-file", budget],
                              cwd=self.root, env=self.env, capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def posts(self):
        return [c for c in fakegh.calls(self.dir) if c[:1] == ["api"] and fakegh.option(c, "-X") in ("POST", "PATCH")]

    # A PR that changes more than docs carries an OpenSpec change

    def test_code_without_a_change_fails_naming_the_file(self):
        code, out = self.pr({SWIFT: "// menu v2\n"})
        self.assertEqual(code, 1, out)
        self.assertIn(SWIFT, out)
        self.assertIn("needs an OpenSpec change", out)

    def test_code_with_a_delta_passes_naming_the_change(self):
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/add-x/proposal.md": "# x\n",
                             "openspec/changes/add-x/specs/menus/spec.md": DELTA})
        self.assertEqual(code, 0, out)
        self.assertIn("add-x", out)

    def test_skip_specs_change_passes(self):
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/tidy-x/proposal.md": "# x\n",
                             "openspec/changes/tidy-x/.openspec.yaml": "schema: spec-driven\nskip_specs: true\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("tidy-x", out)

    def test_skip_specs_false_does_not_count(self):
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/tidy-x/proposal.md": "# x\n",
                             "openspec/changes/tidy-x/.openspec.yaml": "schema: spec-driven\nskip_specs: false\n"})
        self.assertEqual(code, 1, out)

    def test_change_with_neither_delta_nor_skip_specs_fails(self):
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/add-x/proposal.md": "# x\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("add-x has no delta and no skip_specs: true", out)

    def test_ticking_an_active_changes_tasks_passes(self):
        base = {**BASE_FILES, "openspec/changes/add-x/proposal.md": "# x\n",
                "openspec/changes/add-x/specs/menus/spec.md": DELTA,
                "openspec/changes/add-x/tasks.md": "- [ ] 1.1 do\n"}
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/add-x/tasks.md": "- [x] 1.1 do\n"}, base=base)
        self.assertEqual(code, 0, out)
        self.assertIn("add-x", out)

    def test_only_an_archived_change_touched_fails(self):
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/archive/2026-10-01-add-x/tasks.md": "- [x] done\n",
                             "openspec/changes/archive/2026-10-01-add-x/specs/menus/spec.md": DELTA})
        self.assertEqual(code, 1, out)
        self.assertIn("needs an OpenSpec change", out)

    def test_a_change_deleted_at_head_does_not_count(self):
        base = {**BASE_FILES, "openspec/changes/add-x/proposal.md": "# x\n",
                "openspec/changes/add-x/specs/menus/spec.md": DELTA}
        code, out = self.pr({SWIFT: "// v2\n", "openspec/changes/add-x/proposal.md": None,
                             "openspec/changes/add-x/specs/menus/spec.md": None}, base=base)
        self.assertEqual(code, 1, out)

    # Docs-only PRs pass

    def test_docs_only_passes(self):
        code, out = self.pr({"AGENTS.md": "# Agents v2\n", "docs/features.md": "# Features\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("docs-only", out)

    def test_budget_file_alone_passes(self):
        code, out = self.pr({".github/context-budget.txt": "AGENTS.md\t2\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("docs-only", out)

    def test_budget_file_and_agents_md_pass(self):
        code, out = self.pr({".github/context-budget.txt": "AGENTS.md\t2\n", "AGENTS.md": "# A\nb\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("docs-only", out)

    def test_another_github_file_is_not_docs(self):
        code, out = self.pr({".github/other.txt": "x\n"})
        self.assertEqual(code, 1, out)

    def test_deleted_doc_outside_openspec_is_not_docs_only(self):
        base = {**BASE_FILES, "docs/old.md": "# old\n"}
        code, out = self.pr({"docs/old.md": None}, base=base)
        self.assertEqual(code, 1, out)
        self.assertIn("docs/old.md", out)

    # A repo without OpenSpec is told to adopt it first

    def test_no_openspec_folder_fails_with_the_adopt_first_text(self):
        code, out = self.pr({"app/page.tsx": "x\n"}, base={"app/page.tsx": "y\n", "README.md": "# r\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("This repo has not adopted OpenSpec yet. Adopt OpenSpec first", out)
        self.assertIn("ops/standards/openspec-adoption/README.md", out)

    def test_docs_in_a_repo_without_openspec_pass(self):
        code, out = self.pr({"README.md": "# r2\n"}, base={"app/page.tsx": "y\n", "README.md": "# r\n"})
        self.assertEqual(code, 0, out)

    def test_the_adoption_pr_passes(self):
        code, out = self.pr({"openspec/config.yaml": "schema: spec-driven\n",
                             ".github/workflows/openspec-required.yml": "name: x\n",
                             "openspec/changes/adopt-openspec/proposal.md": "# adopt\n",
                             "openspec/changes/adopt-openspec/.openspec.yaml": "skip_specs: true\n"},
                            base={"app/page.tsx": "y\n", "README.md": "# r\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("adopt-openspec", out)

    # The archive bot's PRs, and branches named like them

    def test_archive_bot_diff_passes_as_docs_only(self):
        base = {**BASE_FILES, "openspec/specs/menus/spec.md": "# menus\n",
                "openspec/changes/add-x/proposal.md": "# x\n", "openspec/changes/add-x/specs/menus/spec.md": DELTA}
        code, out = self.pr({"openspec/specs/menus/spec.md": "# menus v2\n",
                             "openspec/changes/add-x/proposal.md": None,
                             "openspec/changes/add-x/specs/menus/spec.md": None,
                             "openspec/changes/archive/2026-10-23-add-x/proposal.md": "# x\n"},
                            base=base, author="github-actions[bot]")
        self.assertEqual(code, 0, out)
        self.assertIn("docs-only", out)

    def test_a_persons_openspec_archive_branch_with_code_fails(self):
        # The tool is never told the branch name, so the name gains nothing.
        code, out = self.pr({SWIFT: "// v2\n", "openspec/specs/menus/spec.md": "# menus\n"})
        self.assertEqual(code, 1, out)

    # Only Fraser's no-spec label exempts a PR, and it is logged

    def test_fraser_label_with_reason_passes_logs_and_comments_once(self):
        body = "Revert.\n\n## No spec\nEmergency revert of #12.\n\n## Test changes\nnone\n"
        code, out = self.pr({SWIFT: "// v2\n"}, labels=["no-spec"], body=body,
                            events=[labelled("someone", "bug"), labelled(FRASER, at="2026-10-23T11:00:00Z")])
        self.assertEqual(code, 0, out)
        self.assertIn(f"Passed without an OpenSpec change: no-spec added by {FRASER} at 2026-10-23T11:00:00Z", out)
        posts = self.posts()
        self.assertEqual(len(posts), 1, posts)
        self.assertEqual(fakegh.option(posts[0], "-X"), "POST")
        sent = fakegh.option(posts[0], "-f")
        self.assertIn("Emergency revert of #12.", sent)
        self.assertNotIn("Test changes", sent)

    def test_fraser_label_with_a_crlf_body_passes(self):
        # GitHub's web editor saves PR bodies with CRLF line endings.
        code, out = self.pr({SWIFT: "// v2\n"}, labels=["no-spec"], body="## No spec\r\nEmergency revert of #12.\r\n",
                            events=[labelled(FRASER)])
        self.assertEqual(code, 0, out)

    def test_a_budget_file_input_that_is_not_a_budget_file_is_refused(self):
        # The caller file is PR-editable: budget-file must not turn a source file into "docs".
        code, out = self.pr({"src/x.py": "x\n"}, budget="src/x.py")
        self.assertEqual(code, 2, out)
        self.assertIn("context-budget.txt", out)

    def test_fraser_label_rerun_edits_the_one_comment(self):
        body = "## No spec\nEmergency revert of #12.\n"
        old = {"id": 55, "user": {"login": "github-actions[bot]", "type": "Bot"},
               "body": "<!-- openspec-required:no-spec -->\nold"}
        code, out = self.pr({SWIFT: "// v2\n"}, labels=["no-spec"], body=body, events=[labelled(FRASER)],
                            comments=[old])
        self.assertEqual(code, 0, out)
        posts = self.posts()
        self.assertEqual(len(posts), 1, posts)
        self.assertEqual(fakegh.option(posts[0], "-X"), "PATCH")
        self.assertIn(f"repos/{REPO}/issues/comments/55", posts[0])

    def test_label_by_another_login_fails_naming_it(self):
        code, out = self.pr({SWIFT: "// v2\n"}, labels=["no-spec"], body="## No spec\nBecause reasons here.\n",
                            events=[labelled(FRASER), labelled("agent-account", at="2026-10-23T12:00:00Z")])
        self.assertEqual(code, 1, out)
        self.assertIn("only Fraser's no-spec label exempts a PR", out)
        self.assertIn("agent-account", out)
        self.assertEqual(self.posts(), [])

    def test_label_by_a_bot_fails_naming_it(self):
        code, out = self.pr({SWIFT: "// v2\n"}, labels=["no-spec"], body="## No spec\nBecause reasons here.\n",
                            events=[labelled("github-actions[bot]")])
        self.assertEqual(code, 1, out)
        self.assertIn("github-actions[bot]", out)

    def test_label_without_a_reason_fails(self):
        code, out = self.pr({SWIFT: "// v2\n"}, labels=["no-spec"], body="Just a revert.\n## No spec\n\n## Other\nx\n",
                            events=[labelled(FRASER)])
        self.assertEqual(code, 1, out)
        self.assertIn("## No spec", out)
        self.assertEqual(self.posts(), [])

    def test_removed_label_fails(self):
        code, out = self.pr({SWIFT: "// v2\n"}, labels=[], body="## No spec\nEmergency revert of #12.\n",
                            events=[labelled(FRASER), labelled(FRASER, event="unlabeled")])
        self.assertEqual(code, 1, out)
        self.assertIn("needs an OpenSpec change", out)

    def test_label_on_a_docs_only_pr_posts_nothing(self):
        code, out = self.pr({"AGENTS.md": "# v2\n"}, labels=["no-spec"], body="## No spec\nEmergency revert of #12.\n",
                            events=[labelled(FRASER)])
        self.assertEqual(code, 0, out)
        self.assertIn("docs-only", out)
        self.assertEqual(self.posts(), [])

    def test_label_exempts_a_repo_without_openspec(self):
        code, out = self.pr({"app/page.tsx": "x\n"}, base={"app/page.tsx": "y\n"}, labels=["no-spec"],
                            body="## No spec\nHotfix before the adoption change.\n", events=[labelled(FRASER)])
        self.assertEqual(code, 0, out)

    # Dependabot updates pass without a spec

    def test_dependabot_workflow_and_manifests_pass(self):
        code, out = self.pr({".github/workflows/ci.yml": "name: ci\n", "package-lock.json": "{}\n",
                             "web/package.json": "{}\n", "requirements-dev.txt": "x\n"},
                            base={"README.md": "# r\n"}, author="dependabot[bot]")
        self.assertEqual(code, 0, out)
        self.assertIn("Dependabot", out)

    def test_dependabot_touching_source_fails(self):
        code, out = self.pr({"package-lock.json": "{}\n", "src/index.ts": "x\n"}, author="dependabot[bot]")
        self.assertEqual(code, 1, out)

    def test_a_persons_lock_file_pr_fails(self):
        code, out = self.pr({"package-lock.json": "{}\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("package-lock.json", out)


if __name__ == "__main__":
    unittest.main()
