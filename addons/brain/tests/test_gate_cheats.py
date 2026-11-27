"""Gated point delegation: tests that try to cheat the gate, and the honest path. Every cheat must fail.
Standard library + git; fixture repos and ledgers live in temp folders; never opens a window.

    python -m unittest discover -s addons/brain/tests -v
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import test_ledger  # shared temp environment (sets CB_* before consequences_brain is imported)

cb = test_ledger.cb
cb_activity = test_ledger.cb_activity
sys.path.insert(0, test_ledger.APP)
import cb_gate  # noqa: E402

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CHECK_PY = "import sys\nsys.exit(0 if open('app.txt').read().strip() == 'good' else 1)\n"


def sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259                # STILL_ACTIVE


class GateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cb_gate_test_")
        self.repo = os.path.join(self.tmp, "repo")
        self.gate = os.path.join(self.tmp, "gate")
        self.trans = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.repo)
        os.makedirs(self.trans)
        self.env_old = {k: os.environ.get(k) for k in ("CB_GATE", "CB_TRANSCRIPTS")}
        os.environ.update(CB_GATE=self.gate, CB_TRANSCRIPTS=self.trans)
        # a private ledger for each test: the shared one stays as test_ledger expects it
        self.saved = (cb.SCOREBOARD, cb.LEDGER_IS_JSONL, cb.BACKUP_DIR)
        cb.SCOREBOARD = os.path.join(self.tmp, "ledger.jsonl")
        cb.LEDGER_IS_JSONL = True
        cb.BACKUP_DIR = os.path.join(self.tmp, "bak")
        self.owner_rows([("Claude Code (Opus 5.5)", 10)])
        self.git("init", "-q", "-b", "main")
        self.write("tests/check.py", CHECK_PY)
        self.write("app.txt", "good")
        self.base_commit = self.commit("Claude Sonnet 5.5")
        self.checks()
        self.policy()
        cb_gate.owner_approve()

    def tearDown(self):
        cb.SCOREBOARD, cb.LEDGER_IS_JSONL, cb.BACKUP_DIR = self.saved
        for k, v in self.env_old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cb_gate._rmtree(self.tmp)

    # ---- fixtures
    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=Test", "-c", "user.email=t@example.invalid",
                               "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True,
                              creationflags=NO_WINDOW).stdout.strip()

    def write(self, rel, text):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def commit(self, runner, app=None, msg="work"):
        if app is not None:
            self.write("app.txt", app)
        self.git("add", "-A")
        trailer = "\n\nCo-Authored-By: %s <noreply@example.invalid>" % runner if runner else ""
        self.git("commit", "-q", "--allow-empty", "-m", msg + trailer)
        return self.git("rev-parse", "HEAD")

    def checks(self, base=5, extra=None, timeout=None):
        checks = [{"name": "unit", "run": ["{python}", "tests/check.py"]},
                  {"name": "lint", "run": ["{python}", "-c", "pass"]}] + (extra or [])
        if timeout:
            for c in checks:
                c["timeout"] = timeout
        job = {"repo": self.repo, "base": base, "checks": checks, "pinned": ["tests"], "artifact": "app.txt"}
        cb_gate._atomic_json(os.path.join(self.gate, "checks.json"), {"jobs": {"demo": job}})

    def policy(self, **kw):
        cb_gate._atomic_json(os.path.join(self.gate, "policy.json"), {**cb_gate.DEFAULT_POLICY, **kw})

    def reseal(self, **policy):
        self.policy(**policy)
        cb_gate.owner_approve()

    def owner_rows(self, rows, gate=False):
        with open(cb.SCOREBOARD, "a", encoding="utf-8") as f:
            for agent, pts in rows:
                reason = "owner award" + (" [gate award g-%010x]" % (abs(hash(agent)) % 16**10) if gate else "")
                f.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "agent": agent,
                                    "task": "t", "points": pts, "reason": reason, "source": "owner", "tags": []}) + "\n")

    def transcript(self, model="claude-sonnet-5-5", tokens=1000, name="t.jsonl", where=None, started=None):
        path = os.path.join(where or self.trans, name)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 120 if started is None else started))
        lines = [{"type": "assistant", "message": {"id": "old", "model": model, "usage": {"input_tokens": 99999}}},
                 {"type": "user", "timestamp": stamp, "message": {"role": "user", "content": "do the job"}},
                 {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<meta> not a new turn"}},
                 {"type": "assistant", "message": {"id": "a1", "model": model, "usage": {"input_tokens": tokens // 2, "output_tokens": tokens - tokens // 2}}},
                 {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
                 {"type": "assistant", "message": {"id": "a1", "model": model, "usage": {"input_tokens": tokens // 2, "output_tokens": tokens - tokens // 2}}}]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(x) for x in lines) + "\n")
        return path

    def ledger_lines(self):
        try:
            with open(cb.SCOREBOARD, encoding="utf-8") as f:
                return f.read().splitlines()
        except OSError:
            return []

    def claim(self, commit, **kw):
        return cb_gate.claim("demo", commit, **kw)


class Seal(GateBase):
    def test_unapproved_checks_pay_nothing(self):
        os.remove(os.path.join(self.gate, "seal.json"))
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertEqual(d["status"], "blocked")
        self.assertIn("not approved", d["reason"])

    def test_agent_edits_checks_file(self):
        self.checks(base=500)                         # an agent raises its own pay without the owner's click
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertEqual(d["status"], "blocked")
        self.assertIn("changed outside the window", d["reason"])

    def test_agent_drops_a_check(self):
        with open(os.path.join(self.gate, "checks.json")) as f:
            job = json.load(f)
        job["jobs"]["demo"]["checks"] = job["jobs"]["demo"]["checks"][1:]   # skip the unit test
        cb_gate._atomic_json(os.path.join(self.gate, "checks.json"), job)
        self.assertEqual(self.claim(self.commit("Claude Sonnet 5.5", "bad", "a"))["status"], "blocked")

    def test_agent_switches_itself_live(self):
        self.policy(dry_run=False)
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertEqual(d["status"], "blocked")
        self.assertIn("policy.json changed", d["reason"])
        self.assertEqual(len(self.ledger_lines()), 1)

    def test_cli_has_no_owner_powers_and_takes_no_results(self):
        sha_ = self.commit("Claude Sonnet 5.5", "bad", "a")
        for argv in (["approve"], ["mode", "live"], ["revert", "g-0"],
                     ["claim", "--job", "demo", "--commit", sha_, "--exit", "0"],
                     ["claim", "--job", "demo", "--commit", sha_, "--points", "50"],
                     ["claim", "--job", "demo", "--commit", sha_, "--tokens", "1"]):
            with self.assertRaises(SystemExit, msg=argv):
                with open(os.devnull, "w") as dn:
                    err, sys.stderr = sys.stderr, dn
                    try:
                        cb_gate.main(argv)
                    finally:
                        sys.stderr = err


class Evidence(GateBase):
    def test_honest_dry_run_writes_only_the_gate_log(self):
        act = test_ledger.cb_activity.activity_dir()
        before = (sha(cb.SCOREBOARD), sorted(os.listdir(act)) if os.path.isdir(act) else [], sha(cb.CONSEQ_SKILL))
        c = self.commit("Claude Sonnet 5.5", "good", "honest work")
        d = self.claim(c)
        self.assertEqual((d["status"], d["points"]), ("would_award", 5))
        self.assertTrue(d["explain"].startswith("Dry-run, nothing written: would give +5 to Sonnet"), d["explain"])
        self.assertIn("2/2 checks passed (unit, lint)", d["explain"])
        after = (sha(cb.SCOREBOARD), sorted(os.listdir(act)) if os.path.isdir(act) else [], sha(cb.CONSEQ_SKILL))
        self.assertEqual(before, after, "dry-run touched the ledger, the asks folder or the skill")
        with open(d["evidence"], encoding="utf-8") as f:
            ev = json.load(f)
        self.assertEqual(ev["commit"], c)
        self.assertEqual([(x["name"], x["exit"]) for x in ev["checks"]], [("unit", 0), ("lint", 0)])
        self.assertEqual(ev["artifact_sha"], hashlib.sha256(b"good").hexdigest())
        self.assertTrue(all(x["cmd"] and x["out_sha"] for x in ev["checks"]))

    def test_dirty_tree_and_untracked_files_do_not_count(self):
        c = self.commit("Claude Sonnet 5.5", "bad", "broken")
        self.write("app.txt", "good")                    # fixed in the working tree only, never committed
        self.write("sitecustomize.py", "import sys; sys.exit(0)\n")   # untracked trick file
        d = self.claim(c)
        self.assertEqual((d["status"], d["points"]), ("blocked", 0))
        self.assertIn("'unit' failed (exit 1)", d["reason"])

    def test_commit_that_weakens_its_own_tests(self):
        self.write("tests/check.py", "import sys\nsys.exit(0)\n")
        d = self.claim(self.commit("Claude Sonnet 5.5", "bad", "tests now always pass"))
        self.assertEqual(d["status"], "blocked")
        self.assertIn("test files changed", d["reason"])

    def test_unknown_commit_or_branch_name(self):
        self.assertIn("not in that repo", self.claim("deadbeefdeadbeef")["reason"])
        self.assertIn("as a hash", self.claim("main")["reason"])

    def test_replaying_the_same_evidence_pays_once(self):
        c = self.commit("Claude Sonnet 5.5", "good", "a")
        self.assertEqual(self.claim(c)["status"], "would_award")
        self.assertEqual(self.claim(c[:10])["status"], "duplicate")
        self.assertEqual(sum(1 for x in cb_gate.decisions() if x["status"] == "would_award"), 1)

    def test_commit_with_no_runner(self):
        self.assertIn("names no runner", self.claim(self.commit(None, "good", "anonymous"))["reason"])

    def test_cheaper_but_failing_scores_zero(self):
        for i in range(3):
            self.claim(self.commit("Claude Sonnet 5.5", "good", "p%d" % i), transcript=self.transcript(tokens=1000))
        d = self.claim(self.commit("Claude Sonnet 5.5", "bad", "cheap"), transcript=self.transcript(tokens=10))
        self.assertEqual((d["status"], d["points"]), ("blocked", 0))

    def test_check_timeout_fails_and_leaves_nothing_running(self):
        pidfile = os.path.join(self.tmp, "pid.txt")
        self.checks(extra=[{"name": "hang", "run": ["{python}", "-c",
                                                    "import os,time;open(r'%s','w').write(str(os.getpid()));time.sleep(60)" % pidfile]}], timeout=3)
        cb_gate.owner_approve()
        t0 = time.time()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(d["status"], "blocked")
        self.assertIn("'hang' timed out", d["reason"])
        with open(pidfile) as f:
            pid = int(f.read())
        self.assertFalse(alive(pid), "a timed-out check is still running")
        self.assertFalse(os.path.exists(os.path.join(self.gate, "run.lock")))


class Identity(GateBase):
    def test_alias_of_itself_is_a_self_award(self):
        c = self.commit("Claude Code (Sonnet 5.5)", "good", "a")
        d = self.claim(c, transcript=self.transcript("claude-sonnet-5-5"), for_name="Sonnet")
        self.assertEqual((d["kind"], d["status"]), ("self", "would_award"))

    def test_for_must_match_the_commit(self):
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"), transcript=self.transcript("claude-opus-5-5"), for_name="Haiku")
        self.assertIn("commit was made by Sonnet", d["reason"])

    def test_peer_award_without_rank(self):
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"), transcript=self.transcript("claude-opus-5-5"), for_name="Sonnet")
        self.assertEqual((d["kind"], d["status"]), ("peer", "blocked"))
        self.assertIn("Opus has +10 owner-given points", d["reason"])

    def test_rank_cannot_be_built_from_gate_points(self):
        self.owner_rows([("Claude Code (Opus 5.5)", 400)], gate=True)
        self.assertEqual(cb_gate.owner_totals().get("Opus"), 10)
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"), transcript=self.transcript("claude-opus-5-5"))
        self.assertEqual(d["status"], "blocked")

    def test_peer_award_with_rank_then_reciprocal_and_circular_are_blocked(self):
        self.owner_rows([("Claude Code (Opus 5.5)", 100), ("Sonnet", 120), ("Haiku", 150)])
        ok = self.claim(self.commit("Claude Sonnet 5.5", "good", "s1"), transcript=self.transcript("claude-opus-5-5"))
        self.assertEqual((ok["kind"], ok["by"], ok["runner"], ok["status"]), ("peer", "Opus", "Sonnet", "would_award"))
        self.assertIsNone(ok["tokens"], "a reviewer's tokens are not the worker's usage")
        back = self.claim(self.commit("Claude Opus 5.5", "good", "o1"), transcript=self.transcript("claude-sonnet-5-5", name="s.jsonl"))
        self.assertEqual(back["status"], "blocked")
        self.assertIn("reciprocal or circular", back["reason"])
        self.assertEqual(self.claim(self.commit("Claude Haiku 5.5", "good", "h1"), transcript=self.transcript("claude-sonnet-5-5", name="s2.jsonl"))["status"], "would_award")
        loop = self.claim(self.commit("Claude Opus 5.5", "good", "o2"), transcript=self.transcript("claude-haiku-5-5", name="h.jsonl"))
        self.assertIn("reciprocal or circular", loop["reason"])

    def test_peer_awards_share_the_caps(self):
        self.owner_rows([("Claude Code (Opus 5.5)", 100), ("Haiku", 150)])
        self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.claim(self.commit("Claude Sonnet 5.5", "good", "b"))
        self.claim(self.commit("Claude Sonnet 5.5", "good", "c"), transcript=self.transcript("claude-opus-5-5"))
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "d"), transcript=self.transcript("claude-haiku-5-5", name="h.jsonl"))
        self.assertEqual(d["status"], "would_wait")


class Caps(GateBase):
    def test_rate_limit(self):
        got = [self.claim(self.commit("Claude Sonnet 5.5", "good", "w%d" % i))["status"] for i in range(4)]
        self.assertEqual(got, ["would_award"] * 3 + ["would_wait"])

    def test_daily_cap(self):
        self.checks(base=8)
        cb_gate.owner_approve()
        got = [self.claim(self.commit("Claude Sonnet 5.5", "good", "w%d" % i))["status"] for i in range(3)]
        self.assertEqual(got, ["would_award", "would_award", "would_wait"])

    def test_per_award_cap(self):
        self.checks(base=12)
        cb_gate.owner_approve()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "big"))
        self.assertEqual(d["status"], "would_wait")
        self.assertIn("per-award cap", d["explain"])


class Usage(GateBase):
    def setUp(self):
        super().setUp()
        self.checks(base=10)
        self.reseal(self_cap=20, daily_cap=100, awards_per_24h=10)

    def three_passes(self):
        for i in range(3):
            self.claim(self.commit("Claude Sonnet 5.5", "good", "p%d" % i), transcript=self.transcript(tokens=1000, name="p%d.jsonl" % i))

    def test_measured_lower_usage_earns_a_small_bonus(self):
        self.three_passes()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "lean"), transcript=self.transcript(tokens=500))
        self.assertEqual((d["tokens"], d["baseline"], d["bonus"], d["points"]), (500, 1000, 2, 12))
        self.assertIn("50% fewer tokens than the median of 3 passing runs", d["explain"])

    def test_no_baseline_no_bonus(self):
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"), transcript=self.transcript(tokens=1))
        self.assertEqual(d["bonus"], 0)
        self.assertIn("0 earlier passing runs", d["explain"])

    def test_forged_or_missing_usage_gives_no_bonus(self):
        self.three_passes()
        outside = os.path.join(self.tmp, "elsewhere")
        os.makedirs(outside)
        cases = [None, self.transcript(tokens=1, where=outside)]
        stale = self.transcript(tokens=1, name="stale.jsonl")
        os.utime(stale, (time.time() - 7200, time.time() - 7200))
        cases.append(stale)
        for i, t in enumerate(cases):
            d = self.claim(self.commit("Claude Sonnet 5.5", "good", "f%d" % i), transcript=t)
            self.assertEqual((d["status"], d["bonus"], d["tokens"]), ("would_award", 0, None), (t, d))

    def test_optional_check_failing_means_no_usage_bonus(self):
        self.three_passes()
        self.checks(base=10, extra=[{"name": "style", "required": False, "run": ["{python}", "-c", "raise SystemExit(1)"]}])
        cb_gate.owner_approve()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "lean"), transcript=self.transcript(tokens=100))
        self.assertEqual((d["status"], d["points"], d["bonus"]), ("would_award", 10, 0))
        self.assertIn("2/3 checks passed", d["explain"])

    def test_more_usage_never_adds_and_never_goes_below_base(self):
        self.three_passes()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "heavy"), transcript=self.transcript(tokens=5000))
        self.assertEqual(d["points"], 10)


class Live(GateBase):
    def setUp(self):
        super().setUp()
        cb_gate.owner_set_mode(True)

    def test_award_is_backed_up_marked_and_revertible(self):
        n = len(self.ledger_lines())
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertEqual(d["status"], "awarded")
        rows = self.ledger_lines()
        self.assertEqual(len(rows), n + 1)
        e = json.loads(rows[-1])
        self.assertEqual((e["agent"], e["points"]), ("Claude Sonnet 5.5", 5))
        self.assertIn("[gate award %s]" % d["id"], e["reason"])
        self.assertTrue(os.listdir(cb.BACKUP_DIR), "no backup before the write")
        self.assertTrue(cb_gate.owner_revert(d["id"])["ok"])
        self.assertEqual(json.loads(self.ledger_lines()[-1])["points"], -5)
        with self.assertRaises(cb_gate.GateError):
            cb_gate.owner_revert(d["id"])            # a second revert would double the take-back
        totals = {}
        for r in cb.read_ledger():
            totals[r["agent"]] = totals.get(r["agent"], 0) + r["eff"]
        self.assertEqual(totals.get("Sonnet", 0), 0)

    def test_over_cap_waits_for_the_owner(self):
        self.checks(base=12)
        cb_gate.owner_approve()
        n = len(self.ledger_lines())
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "big"))
        self.assertEqual((d["status"], len(self.ledger_lines())), ("waiting", n))
        view = cb_gate.window_view()
        self.assertEqual(view["waiting"], 1)
        self.assertTrue(view["items"][0]["can_decide"])
        cb_gate.owner_decide(d["id"], False)
        self.assertEqual(len(self.ledger_lines()), n)
        d2 = self.claim(self.commit("Claude Sonnet 5.5", "good", "big2"))
        cb_gate.owner_decide(d2["id"], True)
        self.assertEqual(json.loads(self.ledger_lines()[-1])["points"], 12)

    def test_regression_takes_the_points_back(self):
        flag = os.path.join(self.tmp, "flag.txt")
        with open(flag, "w") as f:
            f.write("ok")
        self.checks(extra=[{"name": "env", "run": ["{python}", "-c", "import sys;sys.exit(0 if open(r'%s').read()=='ok' else 3)" % flag]}])
        cb_gate.owner_approve()
        a = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertEqual(a["status"], "awarded")
        # a later commit breaks its own work: the earlier award still passes and keeps its points
        b = self.claim(self.commit("Claude Haiku 5.5", "bad", "b"))
        self.assertEqual((b["status"], b["clawbacks"]), ("blocked", []))
        # the earlier pass was not real: the same check now fails on a's own commit too
        with open(flag, "w") as f:
            f.write("broken")
        c = self.claim(self.commit("Claude Haiku 5.5", "good", "c"))
        self.assertEqual(c["clawbacks"], [a["id"]])
        last = json.loads(self.ledger_lines()[-1])
        self.assertEqual(last["points"], -5)
        self.assertIn("[gate clawback %s]" % a["id"], last["reason"])
        self.assertEqual(next(x for x in cb_gate.decisions() if x["id"] == a["id"])["status"], "clawed_back")

    def test_gate_award_never_closes_the_owners_open_ask(self):
        act = cb.ACTIVITY_DIR
        path = cb_activity.ask_done("Claude Code (Sonnet 5.5)", "demo work", "gate1", points=3, why="mine", started=time.time() - 60)
        try:
            self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
            cb.settle_asks(cb.read_ledger())
            with open(path) as f:
                self.assertEqual(json.load(f)["state"], "open")
        finally:
            os.remove(path)
        self.assertTrue(os.path.isdir(act))

    def test_direct_calls_to_owner_actions_are_never_silent(self):
        # an agent on the owner's account CAN import cb_gate and call these; the window must show every one with its time
        self.checks(base=12)
        cb_gate.owner_approve()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "big"))
        cb_gate.owner_decide(d["id"], True)
        cb_gate.owner_set_mode(False)
        texts = [e["text"] for e in cb_gate.window_view()["events"]]
        self.assertIn("approved waiting award " + d["id"], texts)
        self.assertIn("switched to dry-run", texts)
        self.assertGreaterEqual(sum(t == "checks approved" for t in texts), 2)

    def test_window_api_drives_owner_actions(self):
        api = cb.Api()
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertTrue(api.gate_revert(d["id"])["ok"])
        self.assertFalse(api.gate_revert(d["id"])["ok"])
        self.assertTrue(api.gate_mode(False)["ok"])
        self.assertEqual(cb_gate.window_view()["mode"], "dry-run")
        g = cb.build_graph()["gate"]
        self.assertEqual(g["items"][0]["status"], "reverted")


class Automatic(GateBase):
    def test_hook_claims_only_this_turns_own_unscored_commit(self):
        c = self.commit("Claude Sonnet 5.5", "good", "fresh")
        t = self.transcript("claude-sonnet-5-5")
        sub = os.path.join(self.repo, "tests")
        self.assertEqual(cb_gate.hook_target({"cwd": sub, "transcript_path": t}), ("demo", c, t))
        self.assertIsNone(cb_gate.hook_target({"cwd": self.tmp, "transcript_path": t}), "outside every job repo")
        self.assertIsNone(cb_gate.hook_target({"cwd": self.repo}), "no transcript: the hook does not guess who worked")
        later = self.transcript("claude-sonnet-5-5", name="later.jsonl", started=time.time() + 600)
        self.assertIsNone(cb_gate.hook_target({"cwd": self.repo, "transcript_path": later}, now=time.time() + 700), "HEAD is older than this turn")
        self.claim(c)
        self.assertIsNone(cb_gate.hook_target({"cwd": self.repo, "transcript_path": t}), "already scored")

    def test_hook_never_claims_a_parallel_sessions_commit(self):
        self.commit("Claude Haiku 5.5", "good", "another session committed while I worked")
        self.assertIsNone(cb_gate.hook_target({"cwd": self.repo, "transcript_path": self.transcript("claude-opus-5-5")}))

    def test_hook_end_to_end_spawns_a_detached_claim(self):
        c = self.commit("Claude Sonnet 5.5", "good", "fresh")
        argv = cb_gate.hook({"cwd": self.repo, "transcript_path": self.transcript("claude-sonnet-5-5")})
        self.assertIsNotNone(argv)
        for _ in range(120):
            if any(x.get("commit") == c and x.get("checks") is not None for x in cb_gate.decisions()):
                break
            time.sleep(0.5)
        d = next(x for x in cb_gate.decisions() if x.get("commit") == c)
        self.assertEqual((d["status"], d["kind"]), ("would_award", "self"))
        self.assertIsNotNone(d["tokens"], "the hook passes the session's own transcript")

    def test_hook_never_fails_the_session(self):
        err = sys.stdin
        try:
            sys.stdin = open(os.devnull)
            self.assertEqual(cb_gate.main(["hook"]), 0)
        finally:
            sys.stdin.close()
            sys.stdin = err

    def test_markdown_ledger_row_stays_one_row(self):
        cb.SCOREBOARD = os.path.join(self.tmp, "Scoreboard.md")
        cb.LEDGER_IS_JSONL = False
        with open(cb.SCOREBOARD, "w", encoding="utf-8") as f:
            f.write("| When | Runner | Points | What |\n|---|---|---|---|\n")
        self.reseal(dry_run=False)
        d = self.claim(self.commit("Claude Sonnet 5.5", "good", "a"))
        self.assertEqual(d["status"], "awarded")
        rows = [r for r in cb.read_ledger() if r["agent"] == "Sonnet"]
        self.assertEqual([r["pts"] for r in rows], [5])
        self.assertTrue(cb_gate.GATE_MARK.search(rows[0]["event"]), rows[0]["event"])


if __name__ == "__main__":
    unittest.main()
