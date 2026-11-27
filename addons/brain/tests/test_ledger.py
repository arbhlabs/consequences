"""Consequences Brain: ledger, awards, claims, pools and selftest. Standard library only; never opens a window.

    python -m unittest discover -s addons/brain/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
TMP = tempfile.mkdtemp(prefix="cb_public_")
LEDGER = os.path.join(TMP, "ledger.jsonl")
CONFIG = os.path.join(TMP, "config.json")
EVENTS = [
    {"timestamp": "2026-01-05T09:00:00.000Z", "agent": "Claude Code (Opus 4.6)", "task": "login page", "points": 10,
     "reason": "shipped with proof", "source": "owner", "tags": []},
    {"timestamp": "2026-01-05T10:00:00.000Z", "agent": "Codex", "task": "api", "points": -3,
     "reason": "claimed done without running tests", "source": "owner", "tags": []},
    {"timestamp": "2026-01-05T11:00:00.000Z", "agent": "Riley", "task": "docs", "points": 5,
     "reason": "clear README", "source": "owner", "tags": []},
    {"timestamp": "2026-01-05T12:00:00.000Z", "agent": "UNATTRIBUTED", "task": "night fix", "points": 7,
     "reason": "nobody signed it", "source": "owner", "tags": []},
]
with open(LEDGER, "w", encoding="utf-8") as f:
    f.write("\n".join(json.dumps(e) for e in EVENTS) + "\n")
with open(CONFIG, "w", encoding="utf-8") as f:
    json.dump({"ledger": LEDGER, "runners": [{"name": "Riley", "match": "\\briley\\b"}]}, f)
os.environ.update(CB_CONFIG=CONFIG, CB_ACTIVITY=os.path.join(TMP, "activity"), CB_BACKUPS=os.path.join(TMP, "bak"),
                  CB_SKILLS=os.path.join(TMP, "skills"), CB_NO_SESSIONS="1", CB_SHARED_ACTIVITY="",
                  CB_GATE=os.path.join(TMP, "gate"))
sys.path.insert(0, APP)
import cb_activity  # noqa: E402
import consequences_brain as cb  # noqa: E402


class Ledger(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def graph(self):
        cb.STATE.refresh(force=True)
        return cb.STATE.graph

    def test_1_reads_the_points_addon_ledger(self):
        g = self.graph()
        self.assertTrue(cb.LEDGER_IS_JSONL)
        self.assertEqual(g["totals"]["Opus"], 10)
        self.assertEqual(g["totals"]["Codex"], -3)
        self.assertEqual(g["totals"]["Riley"], 5)
        runners = sorted(n["label"] for n in g["nodes"] if n["type"] == "agent")
        self.assertEqual(runners, ["Codex", "Opus", "Riley"], "the UNATTRIBUTED pool is not a runner")
        self.assertEqual(g["pools"], {"UNATTRIBUTED": 7})

    def test_2_award_appends_an_addon_event(self):
        cb_activity.ask_done("Codex", "api fix", "s1", points=5, why="tests green")
        ask = [a for a in self.graph()["asks"]][0]
        self.assertEqual((ask["suggested"], ask["why"]), (5, "tests green"))
        r = cb.Api().award(ask["dir"], ask["file"], 5)
        self.assertTrue(r["ok"], r)
        with open(LEDGER, encoding="utf-8") as f:
            last = json.loads(f.read().splitlines()[-1])
        self.assertEqual((last["agent"], last["points"], last["task"], last["source"], last["tags"]), ("Codex", 5, "tests green", "owner", []))   # the agent's own reason is the ledger task, not the raw task line
        self.assertTrue(last["timestamp"].endswith("Z"))
        self.assertEqual(self.graph()["totals"]["Codex"], 2)
        self.assertTrue(os.listdir(os.path.join(TMP, "bak")), "ledger backed up before writing")

    def test_3_claim_moves_points_from_the_pool(self):
        cb_activity.claim("Riley", 7, "the night fix was mine: commit abc123")
        ask = [a for a in self.graph()["asks"] if a.get("kind") == "claim"][0]
        self.assertTrue(cb.Api().award(ask["dir"], ask["file"], 7)["ok"])
        g = self.graph()
        self.assertEqual(g["totals"]["Riley"], 12)
        self.assertEqual(g["pools"].get("UNATTRIBUTED", 0), 0)

    def test_4_markdown_scoreboard_works_too(self):
        rows = cb.parse_scoreboard("| when | runner | pts | event |\n|---|---|---|---|\n| 2026-01-06 08:00 | Gemini | +4 | fixed flaky test |\n"
                                   "- 2026-01-06 09:00 | Gemini | -1 | missed a lint |\n")
        self.assertEqual([(r["agent"], r["pts"]) for r in rows], [("Gemini", 4), ("Gemini", -1)])

    def test_5_default_ranks_without_a_skill(self):
        self.assertEqual(cb.ladder(150), "Lead")
        self.assertEqual(cb.ladder(-50), "Probation")
        self.assertTrue(cb.can_suggest_for_others("Lead"))

    def test_6_selftest_never_opens_a_window(self):
        out = subprocess.run([sys.executable, os.path.join(APP, "consequences_brain.py"), "--selftest"],
                             capture_output=True, text=True, timeout=60, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        d = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertTrue(d["ok"] and d["ui"] and d["three"] and d["icon"], d)
        self.assertEqual(d["ledger_format"], "jsonl")


if __name__ == "__main__":
    unittest.main(verbosity=2)
