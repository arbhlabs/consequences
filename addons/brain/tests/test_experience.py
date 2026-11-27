import os
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="cb_xp_")
os.environ.setdefault("CB_CONFIG", os.path.join(_TMP, "config.json"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import consequences_brain as cb  # noqa: E402


def row(runner, pts, eff=None):
    return {"runner": runner, "agent": cb.canon_agent(runner), "pts": pts, "eff": pts if eff is None else eff}


class ExperienceTests(unittest.TestCase):
    def test_names_model_and_program_only_when_written(self):
        self.assertEqual(cb.model_of("Opus 5.5 (Claude Code, app 1.6.0)"), "Opus 5.5")
        self.assertEqual(cb.model_of("Claude Code (Sonnet)"), "Sonnet")
        self.assertIsNone(cb.model_of("Night Shift"))
        self.assertEqual(cb.program_of("Opus 5.5 (Claude Code)"), "Claude Code")
        self.assertIsNone(cb.program_of("Opus"))
        self.assertIsNone(cb.model_of("Gemini CLI"))

    def test_proven_xp_needs_good_results(self):
        x = cb.experience([row("Claude Code (Opus 5.5)", 30), row("Claude Code (Opus 5.5)", -5), row("Codex", 40),
                           row("Codex", -40), row("Codex", -1), row("Night Shift", 0),
                           row("UNATTRIBUTED", 7), row("Codex (reattribution from UNATTRIBUTED)", 7)])
        self.assertEqual(x["jobs"], 6)
        by = {g["name"]: g for g in x["programs"]}
        self.assertEqual((by["Claude Code"]["jobs"], by["Claude Code"]["rate"], by["Claude Code"]["xp"]), (2, 50, 15))
        self.assertEqual((by["Codex"]["jobs"], by["Codex"]["xp"], by["Codex"]["net"]), (3, 13, -1))
        self.assertEqual([g["name"] for g in x["programs"]], ["Claude Code", "Codex"])
        self.assertEqual(x["unnamed"], {"models": 4, "programs": 1})


if __name__ == "__main__":
    unittest.main()
