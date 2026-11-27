"""Consequences Brain: points asks (quiet/loud, clean headlines, settling from the ledger), sample mode, the CLI and
publish guards. Standard library only; never opens a window.

    python -m unittest discover -s addons/brain/tests -v
"""
import atexit
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import test_ledger  # sets the temp environment BEFORE consequences_brain is imported, and shares it with this module

cb = test_ledger.cb
cb_activity = test_ledger.cb_activity
APP = test_ledger.APP
BRAIN = os.path.dirname(APP)
LEDGER = cb.SCOREBOARD
NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
atexit.register(shutil.rmtree, test_ledger.TMP, ignore_errors=True)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def clear_dir(folder):
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def set_age(path, seconds):
    rec = load(path)
    rec["ts"] = time.time() - seconds
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f)


def add_row(agent, points, task="docs", reason="fine"):
    """A ledger event stamped now, as an agent that logged its own award would write it."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"timestamp": stamp, "agent": agent, "task": task, "points": points, "reason": reason,
                            "source": "owner", "tags": []}) + "\n")


def cli_env(tmp, config):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CB_", "SHIP_GATE"))}
    env.update(CB_CONFIG=config, CB_ACTIVITY=os.path.join(tmp, "activity"), CB_BACKUPS=os.path.join(tmp, "bak"),
               CB_SKILLS=os.path.join(tmp, "skills"), CB_NO_SESSIONS="1", CB_SHARED_ACTIVITY="")
    return env


def run_py(args, env, timeout=60):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, timeout=timeout, env=env,
                          creationflags=NO_WINDOW)


class CleanTask(unittest.TestCase):
    def test_attachment_is_stripped_even_when_cut_off(self):
        self.assertEqual(cb_activity.clean_task("fix this [Image: source: C:\\x\\y.png] please"), "fix this please")
        self.assertEqual(cb_activity.clean_task("look at [Image: source: C:\\x\\y.png"), "look at")

    def test_tool_markup_is_stripped(self):
        self.assertEqual(cb_activity.clean_task("<system-note>ignore this</system-note> build the page"), "build the page")
        self.assertEqual(cb_activity.clean_task("build the page <cross-session-message from=riley"), "build the page")

    def test_file_paths_are_stripped(self):
        t = cb_activity.clean_task("edit C:\\work\\app\\main.py and /home/riley/app/util.py then ~/notes/a.md now")
        for frag in ("C:\\", "main.py", "/home/", "util.py", "~/", "a.md"):
            self.assertNotIn(frag, t)
        self.assertEqual(t, "edit and then now")

    def test_whitespace_collapses(self):
        self.assertEqual(cb_activity.clean_task("a   b\n\n\tc  "), "a b c")

    def test_length_is_capped_with_an_ellipsis(self):
        t = cb_activity.clean_task("word " * 100)
        self.assertTrue(t.endswith("\u2026"), t)
        self.assertLessEqual(len(t), cb_activity.TASK_CAP + 1)
        self.assertEqual(cb_activity.clean_task("one two three four", cap=9), "one two\u2026")

    def test_bare_relay_wrapper_is_empty(self):
        self.assertEqual(cb_activity.clean_task("Another Claude session sent a message:"), "")
        self.assertEqual(cb_activity.clean_task(""), "")
        self.assertEqual(cb_activity.clean_task(None), "")


class ProjectName(unittest.TestCase):
    def test_home_folder_has_no_project(self):
        home = os.path.expanduser("~")
        self.assertEqual(cb_activity.project_name(home), "")
        self.assertEqual(cb_activity.project_name(home + os.sep), "")
        self.assertEqual(cb_activity.project_name(""), "")
        self.assertEqual(cb_activity.project_name(None), "")

    def test_other_folders_use_their_name(self):
        self.assertEqual(cb_activity.project_name(os.path.join(test_ledger.TMP, "demo-app")), "demo-app")
        self.assertEqual(cb_activity.project_name(os.path.join(test_ledger.TMP, "demo-app") + os.sep), "demo-app")


class AsksBase(unittest.TestCase):
    """Every test starts with an empty activity folder and gets the shared ledger back exactly as it was."""

    def setUp(self):
        self.folder = cb.ACTIVITY_DIR
        os.makedirs(self.folder, exist_ok=True)
        clear_dir(self.folder)
        self._ledger = read_bytes(LEDGER)
        cb.DEMO.update(on=False, extra=[], asks=None)

    def tearDown(self):
        cb.DEMO.update(on=False, extra=[], asks=None)
        with open(LEDGER, "wb") as f:
            f.write(self._ledger)
        clear_dir(self.folder)
        cb.STATE.refresh(force=True)

    def graph(self):
        cb.STATE.refresh(force=True)
        return cb.STATE.graph

    def state_of(self, path):
        return load(path)


class QuietAndLoud(AsksBase):
    def test_points_decide_quiet_or_loud(self):
        cb_activity.ask_done("Riley", "docs", "s1")
        cb_activity.ask_done("Codex", "api", "s2", points=4, why="tests green")
        by = {a["agent"]: a for a in cb_activity.read_asks(self.folder)}
        self.assertIs(by["Riley"]["quiet"], True)
        self.assertIs(by["Codex"]["quiet"], False)

    def test_quiet_ask_expires_before_a_suggested_one(self):
        quiet = cb_activity.ask_done("Riley", "docs", "s1")
        loud = cb_activity.ask_done("Codex", "api", "s2", points=4, why="ok")
        age = cb_activity.QUIET_TTL + 60
        self.assertLess(age, cb_activity.ASK_TTL)
        set_age(quiet, age)
        set_age(loud, age)
        left = [a["agent"] for a in cb_activity.read_asks(self.folder)]
        self.assertEqual(left, ["Codex"])


class GraphAsks(AsksBase):
    def test_ask_card_uses_leaderboard_name_and_clean_task(self):
        cb_activity.ask_done("Claude Code (Opus 4.6)", "<system-note>x</system-note> ship the login [Image: source: C:\\x\\y.png]",
                             "s9", points=4, why="verified", project="demo-app")
        asks = self.graph()["asks"]
        self.assertEqual(len(asks), 1)
        a = asks[0]
        self.assertEqual(a["agent"], "Opus")
        self.assertEqual(a["via"], "Claude Code (Opus 4.6)")
        self.assertEqual(a["project"], "demo-app")
        self.assertEqual(a["task"], "ship the login")
        self.assertEqual((a["suggested"], a["quiet"]), (4, False))

    def test_plain_runner_has_no_via(self):
        cb_activity.ask_done("Riley", "docs", "s1")
        a = self.graph()["asks"][0]
        self.assertEqual((a["agent"], a["via"], a["quiet"]), ("Riley", "", True))


class SettleAsks(AsksBase):
    def test_ledger_row_for_the_runner_closes_the_ask(self):
        path = cb_activity.ask_done("Riley", "docs", "s1")
        add_row("Riley", 3)
        self.graph()
        rec = self.state_of(path)
        self.assertEqual((rec["state"], rec.get("via")), ("awarded", "ledger"))
        self.assertEqual(rec["points"], 3)
        self.assertEqual(self.graph()["asks"], [])

    def test_row_for_a_different_runner_does_not_close_it(self):
        path = cb_activity.ask_done("Riley", "docs", "s1")
        add_row("Codex", 3)
        self.graph()
        self.assertEqual(self.state_of(path)["state"], "open")

    def test_two_open_asks_of_one_runner_are_both_left_alone(self):
        p1 = cb_activity.ask_done("Riley", "docs", "s1")
        p2 = cb_activity.ask_done("Riley", "tests", "s2")
        add_row("Riley", 3)
        self.graph()
        self.assertEqual((self.state_of(p1)["state"], self.state_of(p2)["state"]), ("open", "open"))

    def test_a_row_the_window_wrote_does_not_close_another_ask(self):
        p1 = cb_activity.ask_done("Riley", "docs", "s1", points=2, why="clear")
        p2 = cb_activity.ask_done("Riley", "tests", "s2", points=2, why="green")
        r = cb.Api().award("local", os.path.basename(p1), 2)
        self.assertTrue(r["ok"], r)
        self.graph()
        self.assertEqual(self.state_of(p1)["state"], "awarded")
        self.assertNotEqual(self.state_of(p1).get("via"), "ledger")
        self.assertEqual(self.state_of(p2)["state"], "open", "the window's own award row closed a different ask")


class DismissQuiet(AsksBase):
    def test_clears_only_quiet_asks(self):
        quiet = cb_activity.ask_done("Riley", "docs", "s1")
        loud = cb_activity.ask_done("Codex", "api", "s2", points=4, why="ok")
        r = cb.Api().dismiss_quiet()
        self.assertEqual((r["ok"], r["cleared"]), (True, 1))
        self.assertEqual(self.state_of(quiet)["state"], "dismissed")
        self.assertEqual(self.state_of(loud)["state"], "open")
        self.assertEqual([a["agent"] for a in self.graph()["asks"]], ["Codex"])


class SampleMode(AsksBase):
    def tearDown(self):
        try:
            cb.Api().sample(False)
        finally:
            super().tearDown()

    def test_sample_data_and_award_never_touch_the_ledger(self):
        before = read_bytes(LEDGER)
        try:
            self.assertTrue(cb.Api().sample(True)["sample"])
            g = cb.STATE.graph
            self.assertIs(g["sample"], True)
            runners = {n["label"] for n in g["nodes"] if n["type"] == "agent"}
            self.assertTrue({"Opus", "Gemini", "Grok"} <= runners, runners)
            self.assertNotIn("Riley", runners)
            self.assertEqual(len(g["asks"]), 1)
            ask = g["asks"][0]
            r = cb.Api().award("sample", ask["file"], 8)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["backup"], None)
            self.assertEqual(cb.STATE.graph["asks"], [])
            self.assertEqual(read_bytes(LEDGER), before)
        finally:
            cb.Api().sample(False)
        g = self.graph()
        self.assertIs(g["sample"], False)
        self.assertEqual(g["totals"].get("Riley"), 5)
        self.assertEqual(read_bytes(LEDGER), before)


class SetupHint(unittest.TestCase):
    def test_empty_flag_in_a_fresh_environment(self):
        tmp = tempfile.mkdtemp(prefix="cb_empty_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ledger, config = os.path.join(tmp, "ledger.jsonl"), os.path.join(tmp, "config.json")
        open(ledger, "w").close()
        with open(config, "w", encoding="utf-8") as f:
            json.dump({"ledger": ledger}, f)
        code = ("import sys, json; sys.path.insert(0, %r); import consequences_brain as cb; cb.STATE.refresh(force=True); "
                "print(json.dumps(cb.STATE.graph['setup']['empty']))" % APP)
        out = run_py(["-c", code], cli_env(tmp, config))
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        self.assertEqual(out.stdout.strip().splitlines()[-1], "true")

    def test_not_empty_with_events(self):
        g = test_ledger.cb.STATE
        g.refresh(force=True)
        self.assertIs(g.graph["setup"]["empty"], False)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cb_cli_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.script = os.path.join(APP, "consequences_brain.py")

    def config(self, ledger):
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ledger": ledger}, f)
        return cli_env(self.tmp, path)

    def test_version(self):
        out = run_py([self.script, "--version"], self.config(os.path.join(self.tmp, "ledger.jsonl")))
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        self.assertEqual(out.stdout.strip(), "1.8.0")

    def test_award_appends_one_jsonl_event(self):
        ledger = os.path.join(self.tmp, "ledger.jsonl")
        out = run_py([self.script, "award", "Riley", "+5", "docs", "--why", "clear"], self.config(ledger))
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        with open(ledger, encoding="utf-8") as f:
            events = [json.loads(l) for l in f.read().splitlines() if l.strip()]
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["agent"], events[0]["points"], events[0]["task"], events[0]["reason"]),
                         ("Riley", 5, "docs", "clear"))

    def test_done_creates_an_ask_file(self):
        env = self.config(os.path.join(self.tmp, "ledger.jsonl"))
        out = run_py([self.script, "done", "Riley", "--task", "docs", "--points", "3", "--why", "x"], env)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        folder = os.path.join(self.tmp, "activity")
        asks = [n for n in os.listdir(folder) if n.startswith("ask--") and n.endswith(".json")]
        self.assertEqual(len(asks), 1, os.listdir(folder))
        rec = load(os.path.join(folder, asks[0]))
        self.assertEqual((rec["agent"], rec["state"], rec["suggested"], rec["task"], rec["why"]), ("Riley", "open", 3, "docs", "x"))

    def test_award_on_a_missing_markdown_ledger_creates_header_and_row(self):
        ledger = os.path.join(self.tmp, "Scoreboard.md")
        self.assertFalse(os.path.exists(ledger))
        out = run_py([self.script, "award", "Riley", "+5", "docs", "--why", "clear"], self.config(ledger))
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        with open(ledger, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], "# Scoreboard")
        self.assertIn("| When | Runner | Points | What |", lines)
        rows = [l for l in lines if re.match(r"^\| \d{4}-\d{2}-\d{2} \d{2}:\d{2} \| Riley \| \+5 \| ", l)]
        self.assertEqual(len(rows), 1, lines)


class PublishGuards(unittest.TestCase):
    def test_bridge_copy_of_cb_activity_is_identical(self):
        self.assertEqual(read_bytes(os.path.join(BRAIN, "bridges", "cb_activity.py")), read_bytes(os.path.join(APP, "cb_activity.py")))

    def test_no_personal_home_paths_in_the_app(self):
        rx = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}(?!someone|you|name|<)", re.I)
        hits = []
        for root, dirs, files in os.walk(APP):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "vendor")]
            for name in files:
                if not name.endswith((".py", ".html", ".js")):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, 1):
                        if rx.search(line):
                            hits.append("%s:%d" % (os.path.relpath(path, APP), n))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
