"""Tests for the command-centre liveness rules: 26 hours, open, update, close, not connected, and the
awake-aware rules from ops OpenSpec reliable-watcher-trigger (watcher stale while the Mac is awake,
trigger silent while the watcher runs on the backstop)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import liveness  # noqa: E402

H = 3600
NOW = 1_800_000_000


M = 60


def at(hh, mm, day=0):
    """Epoch for hh:mm UTC on a fixed day (day=-1 is the day before)."""
    return 1_792_713_600 + day * 86400 + hh * H + mm * M  # 2026-10-23T00:00:00Z


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


class AwakeAware(unittest.TestCase):
    def test_gh_expired_while_awake_opens(self):
        # Awake since 09:00, ticking every 10 minutes, every dispatch failing; watcher last ran 09:05.
        now = at(12, 17)
        d = liveness.decide(now, at(9, 5), at(9, 7), None, mac_awake=(at(9, 0), at(12, 10)), trigger_at=at(12, 10))
        self.assertEqual(d["action"], "open")
        self.assertEqual(d["title"], "Command centre heartbeat stale (watcher 192 min, Mac awake)")
        self.assertIn("@fraserbrookhouse", d["body"])
        self.assertIn("3 to 5 hours", d["body"])

    def test_asleep_6_hours_no_issue(self):
        now = at(3, 17)
        d = liveness.decide(now, at(23, 41, -1), at(23, 7, -1), None, mac_awake=(at(8, 0, -1), at(23, 40, -1)),
                            trigger_at=at(23, 40, -1))
        self.assertEqual(d["action"], "none")

    def test_just_woke_no_issue(self):
        now = at(7, 17)
        d = liveness.decide(now, at(23, 41, -1), at(23, 7, -1), None, mac_awake=(at(7, 9), at(7, 10)),
                            trigger_at=at(23, 40, -1))
        self.assertEqual(d["action"], "none")

    def test_awake_29_minutes_no_issue_30_opens(self):
        hb = at(8, 0)
        self.assertEqual(liveness.decide(at(10, 0), hb, hb, None, mac_awake=(at(9, 31), at(9, 55)))["action"], "none")
        self.assertEqual(liveness.decide(at(10, 0), hb, hb, None, mac_awake=(at(9, 30), at(9, 55)))["action"], "open")

    def test_watcher_30_minutes_old_is_fresh_31_is_stale(self):
        aw = (at(8, 0), at(10, 0))
        self.assertEqual(liveness.decide(at(10, 5), at(9, 35), at(9, 35), None, mac_awake=aw)["action"], "none")
        self.assertEqual(liveness.decide(at(10, 5), at(9, 34), at(9, 34), None, mac_awake=aw)["action"], "open")

    def test_trigger_silent_watcher_on_backstop_opens(self):
        # Trigger unloaded at 10:00; a backstop cron watcher run at 13:12 relays that last tick.
        now = at(15, 17)
        d = liveness.decide(now, at(13, 12), at(13, 13), None, mac_awake=(at(8, 0), at(10, 0)), trigger_at=at(10, 0))
        self.assertEqual(d["action"], "open")
        self.assertEqual(d["title"], "Command centre heartbeat stale (trigger silent 192 min)")

    def test_mac_awake_heartbeat_26_hour_rule(self):
        now = at(12, 0)
        d = liveness.decide(now, now - 1 * H, now - 1 * H, None, mac_awake=(now - 30 * H, now - 27 * H))
        self.assertEqual(d["action"], "open")
        self.assertEqual(d["title"], "Command centre heartbeat stale (27 h)")
        self.assertIn("Mac-awake heartbeat", d["body"])

    def test_unset_new_variables_are_not_connected(self):
        self.assertEqual(liveness.decide(NOW, NOW - 2 * H, NOW - 2 * H, None, mac_awake=None, trigger_at=None)["action"],
                         "none")

    def test_back_to_normal_closes(self):
        now = at(12, 0)
        d = liveness.decide(now, at(11, 55), at(11, 7), 9, mac_awake=(at(8, 0), at(11, 50)), trigger_at=at(11, 50))
        self.assertEqual((d["action"], d["issue"]), ("close", 9))
        self.assertIn("Back to normal", d["body"])

    def test_still_stale_awake_updates_in_place(self):
        d = liveness.decide(at(12, 17), at(9, 5), at(9, 7), 9, mac_awake=(at(9, 0), at(12, 10)))
        self.assertEqual((d["action"], d["issue"]), ("update", 9))

    def test_parse_mac_awake(self):
        self.assertEqual(liveness.parse_awake("1792765449 1792766049"), (1792765449, 1792766049))
        self.assertIsNone(liveness.parse_awake(""))
        self.assertIsNone(liveness.parse_awake("abc"))
        self.assertIsNone(liveness.parse_awake("1792765449"))


if __name__ == "__main__":
    unittest.main()
