"""Tests for the command-centre liveness rule: 26 hours, open, update, close, not connected."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import liveness  # noqa: E402

H = 3600
NOW = 1_800_000_000


class Rule(unittest.TestCase):
    def test_fresh_and_no_issue_does_nothing(self):
        self.assertEqual(liveness.decide(NOW, NOW - 2 * H, NOW - 3 * H, None)["action"], "none")

    def test_heartbeat_27_hours_old_opens_an_issue(self):
        d = liveness.decide(NOW, NOW - 27 * H, NOW - 1 * H, None)
        self.assertEqual(d["action"], "open")
        self.assertEqual(d["title"], "Command centre heartbeat stale (27 h)")
        self.assertIn("@fraserbrookhouse", d["body"])

    def test_now_md_stale_opens_an_issue(self):
        d = liveness.decide(NOW, NOW - 1 * H, NOW - 30 * H, None)
        self.assertEqual(d["action"], "open")
        self.assertIn("now.md", d["body"])

    def test_exactly_26_hours_is_still_fresh(self):
        self.assertEqual(liveness.decide(NOW, NOW - 26 * H, NOW - 26 * H, None)["action"], "none")

    def test_still_stale_with_an_open_issue_updates_it(self):
        d = liveness.decide(NOW, NOW - 40 * H, NOW - 1 * H, 7)
        self.assertEqual((d["action"], d["issue"]), ("update", 7))
        self.assertEqual(d["title"], "Command centre heartbeat stale (40 h)")

    def test_back_to_normal_closes_with_the_times_seen(self):
        d = liveness.decide(NOW, NOW - 1 * H, NOW - 2 * H, 7)
        self.assertEqual((d["action"], d["issue"]), ("close", 7))
        self.assertIn("1 h", d["body"])
        self.assertIn("2 h", d["body"])

    def test_not_connected_yet_does_nothing(self):
        self.assertEqual(liveness.decide(NOW, None, None, None)["action"], "none")
        self.assertIn("not connected", liveness.decide(NOW, None, None, None)["reason"])

    def test_one_value_never_written_is_not_connected_not_stale(self):
        self.assertEqual(liveness.decide(NOW, NOW - 1 * H, None, None)["action"], "none")
        self.assertEqual(liveness.decide(NOW, None, NOW - 30 * H, None)["action"], "open")

    def test_bad_value_counts_as_missing(self):
        self.assertEqual(liveness.parse("abc"), None)
        self.assertEqual(liveness.parse(""), None)
        self.assertEqual(liveness.parse("1700000000"), 1700000000)


if __name__ == "__main__":
    unittest.main()
