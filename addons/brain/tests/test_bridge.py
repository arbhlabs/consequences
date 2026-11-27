"""Offline test of the OpenCode -> beacon bridge: feeds event shapes seen on the real server (probe 2026-11-27)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="cb_bridge_")
os.environ["CB_SHARED_ACTIVITY"] = TMP
os.environ["CB_MACHINE"] = "server"
sys.path.insert(0, os.path.join(ROOT, "bridges"))
sys.path.insert(0, os.path.join(ROOT, "app"))
import opencode_beacon_bridge as br  # noqa: E402
import cb_activity  # noqa: E402

br.OUT = TMP
br.get_json = lambda path: None  # offline


def created(sid, title, model="deepseek-v4.1-flash-free", meta=None):
    return {"type": "session.created", "data": {"sessionID": sid, "title": title, "model": {"id": model, "providerID": "opencode"},
                                                 "metadata": meta or {}}}


class Bridge(unittest.TestCase):
    def setUp(self):
        for f in os.listdir(TMP):
            os.remove(os.path.join(TMP, f))
        self.S = br.Sessions()

    def test_run_raises_working_then_points_ask(self):
        br.handle(created("ses_aaaaaaaaaaaaaaaaaaaa1", "fix kiosk camera cards"), self.S)
        br.handle({"type": "session.status", "data": {"sessionID": "ses_aaaaaaaaaaaaaaaaaaaa1", "status": {"type": "busy"}}}, self.S)
        b = cb_activity.read(TMP)
        self.assertEqual(len(b), 1)
        self.assertTrue(b[0]["active"])
        self.assertEqual(b[0]["agent"], "DeepSeek V4.1 Flash Free (OpenCode, server)")
        self.assertEqual(b[0]["task"], "fix kiosk camera cards")
        br.handle({"type": "session.idle", "data": {"sessionID": "ses_aaaaaaaaaaaaaaaaaaaa1"}}, self.S)
        self.assertFalse(cb_activity.read(TMP)[0]["active"])
        asks = cb_activity.read_asks(TMP)
        self.assertEqual([a["task"] for a in asks], ["fix kiosk camera cards"])
        # a second idle for the same run does not raise another ask
        br.handle({"type": "session.execution.succeeded", "data": {"sessionID": "ses_aaaaaaaaaaaaaaaaaaaa1"}}, self.S)
        self.assertEqual(cb_activity.read_asks(TMP)[0]["turns"], 1)

    def test_title_arriving_late_fills_the_task(self):
        br.handle({"type": "session.status", "data": {"sessionID": "ses_d1", "status": {"type": "busy"}}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [])  # unknown session, server offline in this test: skipped safely
        br.handle(created("ses_d2", ""), self.S)
        br.handle({"type": "session.execution.started", "data": {"sessionID": "ses_d2"}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [])
        br.handle({"type": "session.updated", "data": {"sessionID": "ses_d2", "title": "kiosk media card"}}, self.S)
        self.assertTrue(cb_activity.read(TMP)[0]["active"])
        self.assertEqual(cb_activity.read(TMP)[0]["task"], "kiosk media card")

    def test_health_check_titled_late_never_shows_working(self):
        """The real 2026-11-27 00:14 case: created untitled, started, then titled 'health check 00:14', then interrupted."""
        br.handle(created("ses_h1rbzAkdAvK2", ""), self.S)
        br.handle({"type": "session.execution.started", "data": {"sessionID": "ses_h1rbzAkdAvK2"}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [], "untitled run is not shown as working")
        br.handle({"type": "session.updated", "data": {"sessionID": "ses_h1rbzAkdAvK2", "title": "health check 00:14"}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [], "automated run must vanish once its title is known")
        br.handle({"type": "session.execution.interrupted", "data": {"sessionID": "ses_h1rbzAkdAvK2"}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [])
        self.assertEqual(cb_activity.read_asks(TMP), [])

    def test_rate_limit_retry_is_not_working(self):
        br.handle(created("ses_r1", "refactor kiosk"), self.S)
        br.handle({"type": "session.status", "data": {"sessionID": "ses_r1", "status": {"type": "busy"}}}, self.S)
        self.assertTrue(cb_activity.read(TMP)[0]["active"])
        br.handle({"type": "session.status", "data": {"sessionID": "ses_r1", "status": {"type": "retry"}}}, self.S)
        self.assertFalse(cb_activity.read(TMP)[0]["active"], "out of quota / retrying is not working")
        self.assertEqual(cb_activity.read_asks(TMP), [])

    def test_instantly_archived_session_is_automated(self):
        d = created("ses_a1", "")["data"]
        d["time"] = {"created": 1, "archived": 2}
        br.handle({"type": "session.created", "data": d}, self.S)
        br.handle({"type": "session.execution.started", "data": {"sessionID": "ses_a1"}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [])

    def test_suggested_points_reach_the_ask(self):
        br.handle(created("ses_s1", "media card fix"), self.S)
        br.handle({"type": "session.execution.started", "data": {"sessionID": "ses_s1"}}, self.S)
        br.handle({"type": "message.part.updated", "data": {"part": {"sessionID": "ses_s1", "type": "text",
                   "text": "Fixed and verified on the kiosk. Points for this? Suggested: +10 (fix proven on the device)"}}}, self.S)
        br.handle({"type": "session.idle", "data": {"sessionID": "ses_s1"}}, self.S)
        a = cb_activity.read_asks(TMP)[0]
        self.assertEqual((a["suggested"], a["why"]), (10, "fix proven on the device"))

    def test_automatic_sessions_are_ignored(self):
        br.handle(created("ses_b1", "health check 23:43"), self.S)
        br.handle(created("ses_b2", "harp-ai-arbiter (auto-deleted)", "beam-free", {"harp": "ai-arbiter", "ephemeral": True}), self.S)
        for sid in ("ses_b1", "ses_b2"):
            br.handle({"type": "session.execution.started", "data": {"sessionID": sid}}, self.S)
            br.handle({"type": "session.execution.succeeded", "data": {"sessionID": sid}}, self.S)
        self.assertEqual(cb_activity.read(TMP), [])
        self.assertEqual(cb_activity.read_asks(TMP), [])

    def test_failed_run_goes_idle_without_ask(self):
        br.handle(created("ses_c1", "big pickle job", "big-pickle"), self.S)
        br.handle({"type": "session.execution.started", "data": {"sessionID": "ses_c1"}}, self.S)
        self.assertEqual(cb_activity.read(TMP)[0]["agent"], "Big Pickle (OpenCode, server)")
        br.handle({"type": "session.execution.failed", "data": {"sessionID": "ses_c1"}}, self.S)
        self.assertFalse(cb_activity.read(TMP)[0]["active"])
        self.assertEqual(cb_activity.read_asks(TMP), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
