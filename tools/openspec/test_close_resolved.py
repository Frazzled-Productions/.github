"""Tests for close_resolved.py, run for real with a fake gh.

Run: python3 -m unittest discover -s tools/openspec -p 'test_*.py'

After a successful archive run the bot closes its own open "OpenSpec archive failed: <name>" issues
for the changes it archived, and nothing else.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fakegh  # noqa: E402

SCRIPT = HERE / "close_resolved.py"
REPO = "Frazzled-Productions/example"
RUN_URL = "https://github.com/Frazzled-Productions/example/actions/runs/2"
BOT = {"login": "app/github-actions", "is_bot": True}
PERSON = {"login": "fraser", "is_bot": False}


def issue(number, what, author=BOT):
    return {"number": number, "title": f"OpenSpec archive failed: {what}", "author": author}


ISSUES = [
    issue(1, "add-x"),
    issue(2, "add-x"),
    issue(3, "add-y"),
    issue(4, "add-x-extra"),
    issue(5, "add-x", PERSON),
    issue(6, "all changes"),
    issue(7, "unexpected change folder"),
    issue(8, "#42"),
    issue(9, "add-x, add-y"),
    {"number": 10, "title": "Something else about add-x", "author": BOT},
]


class CloseResolved(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.env = {**fakegh.install(self.dir), "FAKE_GH_ISSUES": json.dumps(ISSUES)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *names, pr="77"):
        proc = subprocess.run([sys.executable, str(SCRIPT), REPO, pr, RUN_URL, *names],
                              env=self.env, capture_output=True, text=True)
        return proc

    def closed(self):
        return [int(c[2]) for c in fakegh.calls(self.dir) if c[:2] == ["issue", "close"]]

    def touched(self):
        return sorted({int(c[2]) for c in fakegh.calls(self.dir) if c[:2] in (["issue", "close"], ["issue", "comment"])})

    def test_closes_every_bot_issue_for_the_archived_change_only(self):
        proc = self.run_script("add-x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.closed(), [1, 2])
        self.assertEqual(self.touched(), [1, 2])  # add-y, add-x-extra, the person's, the others: no comment

    def test_the_comment_links_the_run_and_the_pr(self):
        self.run_script("add-x")
        for call in (c for c in fakegh.calls(self.dir) if c[:2] == ["issue", "close"]):
            self.assertEqual(fakegh.option(call, "--repo"), REPO)
            self.assertEqual(fakegh.option(call, "--reason"), "completed")
            comment = fakegh.option(call, "--comment")
            self.assertIn(RUN_URL, comment)
            self.assertIn("#77", comment)
            self.assertIn("`add-x`", comment)

    def test_lists_only_open_openspec_issues(self):
        self.run_script("add-x")
        listing = next(c for c in fakegh.calls(self.dir) if c[:2] == ["issue", "list"])
        self.assertEqual(fakegh.option(listing, "--state"), "open")
        self.assertEqual(fakegh.option(listing, "--label"), "openspec")
        self.assertEqual(fakegh.option(listing, "--repo"), REPO)

    def test_an_issue_naming_several_changes_needs_all_of_them(self):
        self.run_script("add-x", "add-y")
        self.assertEqual(self.closed(), [1, 2, 3, 9])

    def test_an_issue_naming_several_changes_stays_open_when_one_is_missing(self):
        self.run_script("add-y")
        self.assertEqual(self.closed(), [3])

    def test_no_names_closes_nothing(self):
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.touched(), [])

    def test_no_matching_issue_says_so(self):
        proc = self.run_script("add-z")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.touched(), [])
        self.assertIn("No open failure issues to close", proc.stdout)

    def test_a_refused_close_warns_and_carries_on(self):
        self.env["FAKE_GH_FAIL"] = "close 1 "
        proc = self.run_script("add-x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::", proc.stdout)
        self.assertIn("#1", proc.stdout.split("::warning::", 1)[1])
        self.assertEqual(self.closed(), [1, 2])  # #2 was still tried

    def test_a_refused_listing_warns_and_succeeds(self):
        self.env["FAKE_GH_FAIL"] = "issue list"
        proc = self.run_script("add-x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::", proc.stdout)

    def test_names_are_data(self):
        self.env["FAKE_GH_ISSUES"] = json.dumps([issue(1, "add-x"), issue(2, ".*")])
        self.run_script(".*")  # not a change name: refused, matches nothing
        self.assertEqual(self.touched(), [])

    def test_bad_pr_number_is_refused(self):
        proc = self.run_script("add-x", pr="77; rm -rf /")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(fakegh.calls(self.dir), [])

    def test_another_bots_issue_stays_open(self):
        self.env["FAKE_GH_ISSUES"] = json.dumps([issue(1, "add-x", {"login": "app/dependabot", "is_bot": True})])
        self.run_script("add-x")
        self.assertEqual(self.touched(), [])

    def test_a_trailing_newline_is_not_a_name(self):
        self.env["FAKE_GH_ISSUES"] = json.dumps([issue(1, "add-x\n")])
        self.run_script("add-x\n")
        self.assertEqual(self.touched(), [])
        self.run_script("add-x")
        self.assertEqual(self.touched(), [])

    def test_a_crash_warns_and_exits_0(self):
        self.env["PATH"] = str(self.dir / "no-such-bin")  # no gh at all
        proc = self.run_script("add-x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::", proc.stdout)


class Wiring(unittest.TestCase):
    """A contract on the archive job's script (source text): the closer runs last, after auto-merge is
    on and never on "Nothing to archive", with the PR, the run URL and the archived names as separate
    arguments, and a refusal only warns."""

    def test_the_closer_is_called_last_with_the_archived_names(self):
        text = (HERE.parent.parent / ".github/workflows/openspec-archive.yml").read_text(encoding="utf-8")
        archive_job = text[text.index("  archive:"):text.index("  stuck:")]
        call = archive_job.index('close_resolved.py" "$GITHUB_REPOSITORY" "$pr" "$RUN_URL" ${archived[@]+"${archived[@]}"}')
        self.assertGreater(call, archive_job.index('gh pr merge "$pr" --auto'))
        self.assertGreater(call, archive_job.index('echo "Nothing to archive."; exit 0'))
        self.assertIn("|| echo \"::warning::", archive_job[call:call + 300])
        self.assertIn('archived+=("$n"); done <<< "$names"', archive_job)
        stuck = text[text.index("  stuck:"):]
        self.assertNotIn("close_resolved.py", stuck)
        # The stuck job lists the checks last, so they are in the "Why" block's last 20 lines.
        self.assertLess(stuck.index('gh pr view "$pr" --json mergeStateStatus'), stuck.index("/check-runs?per_page=100"))


if __name__ == "__main__":
    unittest.main()
