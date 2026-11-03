"""Tests for the hosted minutes switch (ops OpenSpec hosted-minutes-switch). A fake gh stands in for
GitHub, so nothing here touches the network. Run: python3 -m unittest discover -s tools/hosted-switch"""
import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import switch  # noqa: E402

HOSTED = '"ubuntu-latest"'
LIGHT = '["light"]'
OPS_MAC = '["self-hosted", "macOS", "ARM64", "ops"]'
MID = dt.datetime(2026, 11, 20, 9, 0, tzinfo=dt.timezone.utc)
FIRST = dt.datetime(2026, 12, 1, 0, 30, tzinfo=dt.timezone.utc)
WORKFLOW = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/hosted-minutes-switch.yml"


def row(repo, quantity, sku="Actions Linux", unit="Minutes", product="actions"):
    return dict(product=product, sku=sku, unitType=unit, quantity=quantity, repositoryName=repo)


class FakeGH:
    """Answers `api` calls from what a test set, records writes, and fails a path with an HTTP status."""

    def __init__(self, rows=(), light=HOSTED, ops=HOSTED, public=("poke-memory", ".github", "website")):
        self.usage = {"usageItems": list(rows)}
        self.vars = {"LIGHT_RUNNER": light, "OPS_LIGHT_RUNNER": ops}
        self.public = list(public)
        self.fail = {}      # substring of the path -> HTTP status
        self.writes = []

    def __call__(self, args):
        path = next(a for a in args[1:] if "/" in a and "=" not in a.split("?")[0])
        for key, status in self.fail.items():
            if key in path:
                raise switch.Failed(f"HTTP {status}")
        if "-X" in args:
            name = path.rsplit("/", 1)[1]
            value = next(a for a in args if a.startswith("value=")).split("=", 1)[1]
            self.writes.append((name, value))
            self.vars[name] = value
            return {}
        if "billing/usage" in path:
            return self.usage
        if "/repos" in path:
            return [dict(name=n) for n in self.public]
        name = path.rsplit("/", 1)[1]
        if name not in self.vars:
            raise switch.Failed("HTTP 404")
        return dict(name=name, value=self.vars[name])


def rows(private, public=0):
    out = [row("koinori", private)] if private else []
    return out + ([row("poke-memory", public)] if public else [row("website", 1)])


class Mode(unittest.TestCase):
    def test_2699_is_hosted(self):
        g = FakeGH(rows(2699), light=LIGHT, ops=OPS_MAC)
        self.assertEqual(switch.run(g, MID, write=True)["mode"], "hosted")
        self.assertEqual(g.vars, {"LIGHT_RUNNER": HOSTED, "OPS_LIGHT_RUNNER": HOSTED})

    def test_2700_is_mac(self):
        g = FakeGH(rows(2700))
        self.assertEqual(switch.run(g, MID, write=True)["mode"], "mac")
        self.assertEqual(g.vars, {"LIGHT_RUNNER": LIGHT, "OPS_LIGHT_RUNNER": OPS_MAC})

    def test_reaching_the_limit_mid_month(self):
        g = FakeGH(rows(2712))
        switch.run(g, MID, write=True)
        self.assertEqual(len(g.writes), 2)

    def test_month_reset_switches_back_with_no_other_step(self):
        g = FakeGH(rows(4), light=LIGHT, ops=OPS_MAC)
        self.assertEqual(switch.run(g, FIRST, write=True)["mode"], "hosted")
        self.assertEqual(g.vars["LIGHT_RUNNER"], HOSTED)

    def test_public_minutes_do_not_count(self):
        g = FakeGH(rows(1000, public=3555))
        result = switch.run(g, MID, write=True)
        self.assertEqual((result["total"], result["mode"]), (1000, "hosted"))

    def test_storage_rows_do_not_count(self):
        g = FakeGH(rows(1000) + [row("koinori", 9000, sku="Actions storage", unit="GigabyteHours")])
        self.assertEqual(switch.run(g, MID, write=True)["total"], 1000)

    def test_a_new_private_repo_counts_with_no_change(self):
        g = FakeGH(rows(1000) + [row("brand-new", 50)])
        self.assertEqual(switch.run(g, MID, write=True)["total"], 1050)

    def test_no_write_when_unchanged(self):
        g = FakeGH(rows(1000))
        switch.run(g, MID, write=True)
        self.assertEqual(g.writes, [])

    def test_the_billing_read_names_this_month(self):
        seen = []

        def g(args):
            seen.extend(args)
            return FakeGH(rows(1))(args)
        switch.run(g, MID, write=False)
        self.assertTrue(any("year=2026&month=11" in a for a in seen), seen)


class ReportOnly(unittest.TestCase):
    def test_no_write_in_report_only_mode(self):
        g = FakeGH(rows(1000), light=LIGHT, ops=OPS_MAC)
        result = switch.run(g, MID, write=False)
        self.assertEqual(result["mode"], "hosted")
        self.assertEqual(g.writes, [])
        self.assertEqual(g.vars["LIGHT_RUNNER"], LIGHT)

    def test_write_flag_needs_exactly_true(self):
        for value, expected in (("true", True), ("", False), (None, False), ("yes", False), ("TRUE", False)):
            self.assertIs(switch.writes_on(value), expected)


class FailsSafe(unittest.TestCase):
    def assert_nothing_changes(self, g, now=MID):
        before = dict(g.vars)
        with self.assertRaises(switch.Failed):
            switch.run(g, now, write=True)
        self.assertEqual(g.vars, before)
        self.assertEqual(g.writes, [])

    def test_http_failures_on_the_billing_read(self):
        for status in (503, 429, 401):
            g = FakeGH(rows(1000), light=LIGHT, ops=OPS_MAC)
            g.fail["billing/usage"] = status
            self.assert_nothing_changes(g)

    def test_no_usage_items_field(self):
        g = FakeGH(rows(1000), light=LIGHT, ops=OPS_MAC)
        g.usage = {"message": "something else"}
        self.assert_nothing_changes(g)

    def test_row_with_no_quantity(self):
        bad = row("koinori", 1)
        del bad["quantity"]
        self.assert_nothing_changes(FakeGH([bad], light=LIGHT, ops=OPS_MAC))

    def test_empty_answer_mid_month(self):
        self.assert_nothing_changes(FakeGH([], light=LIGHT, ops=OPS_MAC))

    def test_empty_answer_on_the_first_is_a_new_month(self):
        g = FakeGH([], light=LIGHT, ops=OPS_MAC)
        self.assertEqual(switch.run(g, FIRST, write=True)["total"], 0)

    def test_a_failed_public_repo_list(self):
        g = FakeGH(rows(1000), light=LIGHT, ops=OPS_MAC)
        g.fail["/repos"] = 502
        self.assert_nothing_changes(g)

    def test_a_public_list_without_this_repo_makes_no_sense(self):
        self.assert_nothing_changes(FakeGH(rows(1000), light=LIGHT, ops=OPS_MAC, public=[]))

    def test_unreadable_variable(self):
        g = FakeGH(rows(1000), light=LIGHT, ops=OPS_MAC)
        del g.vars["OPS_LIGHT_RUNNER"]
        with self.assertRaisesRegex(switch.Failed, "OPS_LIGHT_RUNNER.*HTTP 404"):  # says which one is missing
            switch.run(g, MID, write=True)
        self.assertEqual(g.writes, [])

    def test_a_write_failing_part_way_is_repaired_by_the_next_run(self):
        g = FakeGH(rows(2712))
        real = g.__call__

        def refuse_second(args):
            if "-X" in args and any("OPS_LIGHT_RUNNER" in a for a in args):
                raise switch.Failed("HTTP 403")
            return real(args)
        with self.assertRaises(switch.Failed):
            switch.run(refuse_second, MID, write=True)
        self.assertEqual(g.vars, {"LIGHT_RUNNER": LIGHT, "OPS_LIGHT_RUNNER": HOSTED})
        switch.run(g, MID, write=True)
        self.assertEqual(g.vars, {"LIGHT_RUNNER": LIGHT, "OPS_LIGHT_RUNNER": OPS_MAC})
        self.assertEqual(g.writes, [("LIGHT_RUNNER", LIGHT), ("OPS_LIGHT_RUNNER", OPS_MAC)])

    def test_the_log_line_has_totals_only(self):
        line = switch.summary(dict(mode="hosted", total=1000, changed=[], write=False))
        self.assertIn("1000", line)
        self.assertNotIn("koinori", line)

    def test_a_gh_failure_keeps_the_status_and_drops_the_text(self):
        message = switch.failure_text("gh: secret-repo-name Not Found (HTTP 404)")
        self.assertEqual(message, "HTTP 404")
        self.assertEqual(switch.failure_text("connection reset, secret-repo-name"), "no HTTP status")

    def test_a_rate_limit_403_is_not_a_refused_credential(self):
        for stderr in ("HTTP 403: API rate limit exceeded for installation ID 1 (secret-repo-name)",
                       "HTTP 403: You have exceeded a secondary rate limit."):
            text = switch.failure_text(stderr)
            self.assertEqual(text, "HTTP 403 (rate limit)")
            self.assertFalse(switch.refused(text))
        self.assertTrue(switch.refused(switch.failure_text("HTTP 403: Resource not accessible")))


class RealGh(unittest.TestCase):
    """switch.gh itself, with only the process faked: FakeGH replaces it above, so never sees gh's output."""

    @staticmethod
    def process(g, read_output=None):
        def fake(cmd, **_):
            answer = g(cmd[1:])
            out = "" if "-X" in cmd else (json.dumps(answer) if read_output is None else read_output)
            return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        return fake

    def test_both_writes_go_through_though_a_patch_answers_204_with_no_body(self):
        g = FakeGH(rows(2712))
        with mock.patch.object(switch.subprocess, "run", self.process(g)):
            switch.run(switch.gh, MID, write=True)
        self.assertEqual(g.vars, {"LIGHT_RUNNER": LIGHT, "OPS_LIGHT_RUNNER": OPS_MAC})

    def test_an_empty_answer_to_a_read_still_fails(self):
        g = FakeGH(rows(2712))
        with mock.patch.object(switch.subprocess, "run", self.process(g, read_output="")):
            with self.assertRaises(ValueError):
                switch.run(switch.gh, MID, write=True)
        self.assertEqual(g.writes, [])


class NoPrivateNameInPublicLogs(unittest.TestCase):
    """This repo's logs are public: no failure path may print a private repo's name (made up here)."""
    SECRET = "zz-private-repo"

    def run_main(self, stderr, argv, env=None):
        def fake(cmd, **_):
            return types.SimpleNamespace(returncode=1, stdout="", stderr=stderr)
        out, err = io.StringIO(), io.StringIO()
        env = {"GH_TOKEN": "fake", **(env or {})}
        with mock.patch.object(switch.subprocess, "run", fake), mock.patch.dict(os.environ, env), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = switch.main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_failing_reads_and_report_print_no_private_name(self):
        for stderr in (f"gh: {self.SECRET} Not Found (HTTP 404)", f"HTTP 401: Bad credentials ({self.SECRET})",
                       f"HTTP 403 {self.SECRET} forbidden", f"connection reset by {self.SECRET}"):
            for argv in (["run"], ["report", "failure"]):
                code, printed = self.run_main(stderr, argv)
                self.assertEqual(code, 1)
                self.assertNotIn(self.SECRET, printed)

    def test_a_refused_credential_is_flagged_for_the_report_step(self):
        for stderr, flagged in (("HTTP 401: Bad credentials", True), ("HTTP 403", True), ("HTTP 503", False)):
            with tempfile.TemporaryDirectory() as d:
                target = pathlib.Path(d) / "output"
                target.write_text("", encoding="utf-8")
                self.run_main(stderr, ["run"], {"GITHUB_OUTPUT": str(target)})
                self.assertEqual("auth-failed=true" in target.read_text(encoding="utf-8"), flagged, stderr)

    def test_a_missing_secret_is_flagged_and_named(self):
        """gh with no token prints no HTTP status, so the run says so itself (GITHUB_ACTIONS, empty GH_TOKEN)."""
        with tempfile.TemporaryDirectory() as d:
            target = pathlib.Path(d) / "output"
            target.write_text("", encoding="utf-8")
            code, printed = self.run_main("gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN "
                                          "environment variable.", ["run"], {"GITHUB_OUTPUT": str(target),
                                                                             "GH_TOKEN": ""})
            self.assertEqual(code, 1)
            self.assertIn("HOSTED_SWITCH_TOKEN", printed)
            self.assertIn("auth-failed=true", target.read_text(encoding="utf-8"))


class Report(unittest.TestCase):
    def test_first_two_failures_open_nothing(self):
        self.assertEqual(switch.decide_report("failure", [], None)["action"], "none")
        self.assertEqual(switch.decide_report("failure", ["failure", "success"], None)["action"], "none")

    def test_third_failure_opens_one_issue_mentioning_fraser(self):
        d = switch.decide_report("failure", ["failure", "failure", "success"], None)
        self.assertEqual(d["action"], "open")
        self.assertIn("@fraserbrookhouse", d["body"])

    def test_a_refused_credential_opens_the_issue_on_the_first_failure(self):
        d = switch.decide_report("failure", [], None, auth=True)
        self.assertEqual(d["action"], "open")
        self.assertIn("@fraserbrookhouse", d["body"])
        self.assertIn("401 or 403", d["body"])
        self.assertIn("Manual override: set `HOSTED_SWITCH_WRITE` to `false`", d["body"])

    def test_a_refused_credential_updates_an_open_issue(self):
        self.assertEqual(switch.decide_report("failure", [], 7, auth=True)["action"], "update")

    def test_fourth_failure_updates_the_same_issue(self):
        d = switch.decide_report("failure", ["failure", "failure", "failure"], 7)
        self.assertEqual((d["action"], d["issue"]), ("update", 7))

    def test_a_good_run_closes_the_issue(self):
        self.assertEqual(switch.decide_report("success", ["failure"], 7)["action"], "close")

    def test_a_good_run_with_no_issue_does_nothing(self):
        self.assertEqual(switch.decide_report("success", [], None)["action"], "none")

    def test_a_cancelled_run_changes_nothing(self):
        self.assertEqual(switch.decide_report("cancelled", ["failure", "failure"], 7)["action"], "none")

    def test_the_body_names_no_private_detail(self):
        body = switch.decide_report("failure", ["failure"] * 2, None)["body"]
        self.assertNotRegex(body, r"koinori|plan-bee|ghp_|github_pat_")


class ReportThroughGh(unittest.TestCase):
    """report() against a working fake gh, so the issue and run calls' arguments are checked."""

    def fake(self, issues, conclusions):
        calls = []

        def ghf(args):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return issues
            if args[:2] == ["run", "list"]:
                return [dict(conclusion=c) for c in conclusions]
            return None
        return ghf, calls

    def test_the_lookups_ask_for_its_own_issue_and_main_s_finished_runs(self):
        ghf, calls = self.fake([], ["failure", "failure"])
        with contextlib.redirect_stdout(io.StringIO()):
            switch.report(ghf, "failure")
        issue_list, run_list, create = calls
        self.assertEqual(issue_list[:2], ["issue", "list"])
        self.assertEqual(issue_list[issue_list.index("--author") + 1], "app/github-actions")
        self.assertEqual(issue_list[issue_list.index("--state") + 1], "open")
        for flag, value in (("--workflow", "hosted-minutes-switch.yml"), ("--branch", "main"),
                            ("--status", "completed"), ("--json", "conclusion")):
            self.assertEqual(run_list[run_list.index(flag) + 1], value)
        self.assertEqual(create[:2], ["issue", "create"])
        self.assertEqual(create[create.index("--title") + 1], switch.TITLE)

    def test_a_look_alike_issue_from_someone_else_is_not_edited(self):
        """The search is limited to the workflow's own issues; a same-title issue it returns is still
        matched on the bot author, so an outsider's issue is never edited in place of opening one."""
        outsider = dict(number=9, title=switch.TITLE, author=dict(login="someone"))
        ghf, calls = self.fake([outsider], [])
        with contextlib.redirect_stdout(io.StringIO()):
            switch.report(ghf, "failure", auth=True)
        self.assertEqual(calls[-1][:2], ["issue", "create"])

    def test_its_own_issue_is_edited_then_closed(self):
        mine = dict(number=7, title=switch.TITLE, author=dict(login="app/github-actions"))
        ghf, calls = self.fake([mine], ["failure"] * 3)
        with contextlib.redirect_stdout(io.StringIO()):
            switch.report(ghf, "failure")
        self.assertEqual(calls[-1][:3], ["issue", "edit", "7"])
        ghf, calls = self.fake([mine], ["failure"])
        with contextlib.redirect_stdout(io.StringIO()):
            switch.report(ghf, "success")
        self.assertEqual(calls[-1][:3], ["issue", "close", "7"])
        self.assertIn("--comment", calls[-1])


class WorkflowShape(unittest.TestCase):
    """The fork-PR and credential scenarios, proved on the workflow file itself."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_dispatch_triggers_it_until_the_credential_exists(self):
        # Rollout step 4 adds the hourly schedule, with this assertion and an hourly-cron test.
        on = re.search(r"^on:\n((?:  .*\n|\n)+)", self.text, re.M).group(1)
        self.assertEqual(re.findall(r"^  (\w+):", on, re.M), ["workflow_dispatch"])

    def test_the_credential_is_read_through_the_main_only_environment(self):
        self.assertRegex(self.text, r"\n    environment: hosted-switch\n")

    def test_the_report_step_hears_about_a_refused_credential(self):
        self.assertIn("steps.switch.outputs.auth-failed", self.text.split("- name: Report", 1)[1])

    def test_the_write_credential_reaches_one_step_only(self):
        self.assertEqual(self.text.count("secrets."), 1)
        report = self.text.split("- name: Report", 1)[1]
        self.assertNotIn("secrets.", report)
        self.assertIn("github.token", report)

    def test_the_report_runs_after_a_failure(self):
        self.assertRegex(self.text.split("- name: Report", 1)[1], r"if: always\(\)")

    def test_no_third_party_action_and_the_checkout_is_pinned(self):
        self.assertEqual(re.findall(r"uses: (\S+)", self.text),
                         ["actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"])

    def test_concurrent_runs_wait_rather_than_cancel(self):
        self.assertIn("cancel-in-progress: false", self.text)


if __name__ == "__main__":
    unittest.main()
