"""Regression test for cb_chatpoints: which owner messages become ledger rows, and that each prompt logs once."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import cb_chatpoints as cp  # noqa: E402


class Amounts(unittest.TestCase):
    def test_signed_amounts(self):
        self.assertEqual(cp.amounts("minus 20 points"), [-20])
        self.assertEqual(cp.amounts("+3"), [3])
        self.assertEqual(cp.amounts("plus 5"), [5])
        self.assertEqual(cp.amounts("-20 points for that"), [-20])
        self.assertEqual(cp.amounts("nice work +5 pts"), [5])
        self.assertEqual(cp.amounts("\u221210 points"), [-10])

    def test_not_points(self):
        self.assertEqual(cp.amounts("I will award you 200 points"), [])   # a promise has no sign
        self.assertEqual(cp.amounts("range 5-10"), [])
        self.assertEqual(cp.amounts("version 1.2-3 and v2.0"), [])
        self.assertEqual(cp.amounts(""), [])

    def test_bare_sign_only_in_short_text(self):
        long = "please look at the build log again, the step with +3 retries is the one that keeps failing"
        self.assertEqual(cp.amounts(long), [])
        self.assertEqual(cp.amounts(long + " and -5 points for that"), [-5])


class Logging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CB_CHATPOINTS_STATE"] = os.path.join(self.tmp, "seen.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k in ("CB_CHATPOINTS_STATE", "CB_CHATPOINTS_LEDGER"):
            os.environ.pop(k, None)

    def _transcript(self):
        p = os.path.join(self.tmp, "t.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5"}}) + "\n")
        return p

    def test_markdown_once(self):
        led = os.path.join(self.tmp, "Scoreboard.md")
        os.environ["CB_CHATPOINTS_LEDGER"] = led
        d = {"prompt": "minus 20 points", "session_id": "s1", "transcript_path": self._transcript(), "cwd": "/x/demo"}
        self.assertIn("-20", cp.handle(d))
        self.assertIsNone(cp.handle(d))                    # the same prompt never logs twice
        with open(led, encoding="utf-8") as f:
            rows = f.read().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertRegex(rows[0], r"^\| \d{4}-\d\d-\d\d \d\d:\d\d \| Sonnet 5\.5 \(Claude Code, demo\) \| -20 \| owner ")

    def test_jsonl_and_nothing_for_promises(self):
        led = os.path.join(self.tmp, "ledger.jsonl")
        os.environ["CB_CHATPOINTS_LEDGER"] = led
        self.assertIsNone(cp.handle({"prompt": "I will award you 200 points", "session_id": "s2"}))
        self.assertFalse(os.path.exists(led))
        cp.handle({"prompt": "+3", "session_id": "s2", "transcript_path": self._transcript()})
        with open(led, encoding="utf-8") as f:
            e = json.loads(f.read().splitlines()[0])
        self.assertEqual((e["points"], e["source"]), (3, "owner"))


if __name__ == "__main__":
    unittest.main()
