"""Tests for approve_runs.py. Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approve_runs  # noqa: E402

REPO = "Frazzled-Productions/roast-conductor"
SHA = "a" * 40
BOT = {"login": "github-actions[bot]", "type": "Bot"}


def pr(**over):
    p = {"state": "open", "user": dict(BOT),
         "head": {"ref": "openspec-archive", "sha": SHA, "repo": {"full_name": REPO}},
         "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": REPO}}}
    p.update(over)
    return p


def run(i, **over):
    r = {"id": i, "name": f"run {i}", "head_sha": SHA, "event": "pull_request", "conclusion": "action_required",
         "triggering_actor": dict(BOT), "head_branch": "openspec-archive", "head_repository": {"full_name": REPO}}
    r.update(over)
    return r


class Fake:
    def __init__(self, the_pr, runs):
        self.pr, self.runs, self.posted = the_pr, runs, []

    def api(self, path):
        if path.startswith(f"repos/{REPO}/pulls/"):
            return self.pr
        return {"workflow_runs": [dict(r, conclusion=None) if r["id"] in self.posted else r for r in self.runs]}

    def post(self, path):
        self.posted.append(int(path.split("/")[-2]))


def go(fake, diff_ok=True, extra=()):
    return approve_runs.main(["x", REPO, "7", SHA, *extra], api=fake.api, post=fake.post,
                             diff_ok=lambda _r: diff_ok, sleep=lambda _s: None, polls=4)


class ApproveRuns(unittest.TestCase):
    def test_approves_the_bots_own_held_runs(self):
        f = Fake(pr(), [run(1), run(2)])
        self.assertEqual(go(f), 0)
        self.assertEqual(sorted(f.posted), [1, 2])

    def test_refuses_a_pr_by_a_person(self):
        f = Fake(pr(user={"login": "fraser", "type": "User"}), [run(1)])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_another_branch(self):
        f = Fake(pr(head={"ref": "feature", "sha": SHA, "repo": {"full_name": REPO}}), [run(1)])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_a_fork(self):
        f = Fake(pr(head={"ref": "openspec-archive", "sha": SHA, "repo": {"full_name": "someone/roast-conductor"}}), [run(1)])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_when_the_head_moved(self):
        f = Fake(pr(head={"ref": "openspec-archive", "sha": "c" * 40, "repo": {"full_name": REPO}}), [run(1)])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_a_closed_pr(self):
        f = Fake(pr(state="closed"), [run(1)])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_a_diff_outside_openspec(self):
        f = Fake(pr(), [run(1)])
        self.assertEqual(go(f, diff_ok=False), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_a_held_run_someone_else_triggered(self):
        f = Fake(pr(), [run(1, triggering_actor={"login": "fraser"})])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_refuses_a_held_run_from_another_event(self):
        f = Fake(pr(), [run(1, event="pull_request_target")])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_fails_when_nothing_was_held(self):
        f = Fake(pr(), [])
        self.assertEqual(go(f), 1)

    def test_leaves_runs_that_were_never_held(self):
        f = Fake(pr(), [run(1), run(2, conclusion="success")])
        self.assertEqual(go(f), 0)
        self.assertEqual(f.posted, [1])

    def test_refuses_another_base(self):
        f = Fake(pr(base={"ref": "qa", "sha": "b" * 40, "repo": {"full_name": REPO}}), [run(1)])
        self.assertEqual(go(f), 1)
        self.assertEqual(f.posted, [])

    def test_custom_branch_and_base(self):
        f = Fake(pr(head={"ref": "spec-archive", "sha": SHA, "repo": {"full_name": REPO}},
                    base={"ref": "qa", "sha": "b" * 40, "repo": {"full_name": REPO}}),
                 [run(1, head_branch="spec-archive")])
        self.assertEqual(go(f, extra=("--branch", "spec-archive", "--base", "qa")), 0)
        self.assertEqual(f.posted, [1])

    def test_custom_branch_still_refuses_the_default_branch(self):
        f = Fake(pr(), [run(1)])
        self.assertEqual(go(f, extra=("--branch", "spec-archive")), 1)
        self.assertEqual(f.posted, [])

    def test_custom_branch_refuses_a_run_from_another_branch(self):
        f = Fake(pr(head={"ref": "spec-archive", "sha": SHA, "repo": {"full_name": REPO}}), [run(1)])
        self.assertEqual(go(f, extra=("--branch", "spec-archive")), 1)
        self.assertEqual(f.posted, [])

    def test_bad_arguments(self):
        f = Fake(pr(), [run(1)])
        self.assertEqual(go(f, extra=("--branch",)), 2)
        self.assertEqual(go(f, extra=("--colour", "x")), 2)
        self.assertEqual(approve_runs.main(["x", REPO, "7"], api=f.api, post=f.post), 2)
        self.assertEqual(f.posted, [])


if __name__ == "__main__":
    unittest.main()
