#!/usr/bin/env python3
"""Gated point delegation: agents ask the gate for points; the gate runs the OWNER's checks itself and pays only for
passing evidence. Standard library only. Design: docs/gated-delegation.md.

The agent being scored only names the job type and the commit. It cannot pass check results, scores, usage or a mode:
  cb_gate.py claim --job consequences-brain --commit <sha> [--transcript <its Claude Code transcript>] [--for <peer>]
  cb_gate.py recheck [--days 14]      # rerun checks for recent awards; a check that now fails takes the points back
  cb_gate.py status                   # mode, seal, recent decisions in plain words

Owner-only actions (approve checks, go live / back to dry-run, approve or decline a waiting award, revert) are the
owner_* functions, called by the Consequences Brain window. There is no CLI for them on purpose.

Folder: $CB_GATE, else %LOCALAPPDATA%/Consequences/gate (Windows) or ~/.consequences/gate.
  checks.json   job types: repo, checks (argv lists), pinned test paths, base points, artifact path   (owner)
  policy.json   caps, rate limits, peer rank, windows, bonus ceiling, dry_run                           (owner)
  seal.json     SHA-256 of both files + git ids of the pinned paths, written by the window on approval
  evidence/     one JSON per decision: command, exit code, seconds, output hash, artifact hash, commit
  gate.jsonl    append-only log of every decision, revert, clawback, approval and seal change

Honest limit: on one Windows account this is tamper-EVIDENT, not tamper-proof. A same-user process can edit these
files; any edit that does not come from the window breaks the seal and the gate stops paying (fail closed).
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
IDLE_PRIORITY = 0x00000040 if os.name == "nt" else 0
DEFAULT_POLICY = {
    "dry_run": True,            # start state: log what would be awarded, write nothing else
    "self_cap": 10,             # max points one gate award may pay without the owner's click
    "daily_cap": 20,            # max gate points one runner may receive per 24 h without a click
    "awards_per_24h": 3,        # max gate awards one runner may receive per 24 h without a click
    "peer_rank": "Lead",        # rank (from owner-sourced points only) needed to award someone else
    "cycle_days": 30,           # reciprocal / circular award window
    "bonus_ceiling": 0.3,       # usage bonus is at most this share of the base points
    "bonus_min_runs": 3,        # passing runs needed before a usage baseline exists
    "check_timeout": 600,       # seconds per check
    "cores": 2,                 # checks run on at most this many cores, at idle priority
    "recheck_days": 14,
}
GATE_MARK = re.compile(r"\[gate (?:award|approved|revert|clawback) g-[0-9a-f]{10}\]")
COUNTED = {"live": ("awarded",), "dry": ("would_award",)}
OWNER_EVENTS = {"seal": "checks approved", "mode": "mode", "approved": "approved waiting award", "declined": "declined waiting award",
                "reverted": "reverted award"}
EDGES = {"live": ("awarded", "waiting"), "dry": ("would_award", "would_wait")}


class GateError(Exception):
    pass


# ---------------------------------------------------------------- files
def gate_dir():
    d = os.environ.get("CB_GATE")
    if not d:
        base = os.environ.get("LOCALAPPDATA")
        d = os.path.join(base, "Consequences", "gate") if base else os.path.join(os.path.expanduser("~"), ".consequences", "gate")
    return d


def _p(*parts):
    return os.path.join(gate_dir(), *parts)


def _bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _sha(b):
    return hashlib.sha256(b or b"").hexdigest()


def _json(path, default):
    b = _bytes(path)
    if b is None:
        return default
    try:
        return json.loads(b.decode("utf-8"))
    except ValueError:
        return default


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _log(rec):
    os.makedirs(gate_dir(), exist_ok=True)
    with open(_p("gate.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec) + "\n")


def load_checks():
    c = _json(_p("checks.json"), {})
    return c if isinstance(c, dict) and isinstance(c.get("jobs"), dict) else {"jobs": {}}


def load_policy():
    p = _json(_p("policy.json"), {})
    return {**DEFAULT_POLICY, **(p if isinstance(p, dict) else {})}


def brain():
    """The window module, for the ledger (read, append with backup), runner names and ranks."""
    if "consequences_brain" in sys.modules:
        return sys.modules["consequences_brain"]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import consequences_brain
    return consequences_brain


# ---------------------------------------------------------------- git
def _git(repo, *args, binary=False, check=True):
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GateError("git failed: %s" % e)
    if check and r.returncode:
        raise GateError("git %s: %s" % (args[0], r.stderr.decode("utf-8", "replace").strip()[:200]))
    return r if not check else (r.stdout if binary else r.stdout.decode("utf-8", "replace").strip())


def resolve_commit(repo, ref):
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", ref or ""):
        raise GateError("give the commit as a hash, not a branch or tag")
    if _git(repo, "cat-file", "-t", ref + "^{commit}", check=False).returncode:
        raise GateError("commit %s is not in that repo" % ref[:12])
    return _git(repo, "rev-parse", ref + "^{commit}")


def pin_ids(repo, commit, paths):
    out = {}
    for path in paths:
        r = _git(repo, "rev-parse", "%s:%s" % (commit, path.replace("\\", "/")), check=False)
        out[path] = r.stdout.decode().strip() if not r.returncode else None
    return out


def changed_pins(repo, commit, pins):
    """Pinned paths whose git id at `commit` differs from the one the owner approved."""
    return [p for p, oid in pin_ids(repo, commit, list(pins)).items() if oid != pins.get(p)]


def commit_runner(repo, commit):
    """Who did the work, from the commit itself: the first Co-Authored-By naming a known runner, else the author."""
    B = brain()
    text = _git(repo, "log", "-1", "--format=%an%x00%B", commit)
    author, _, msg = text.partition("\x00")
    for m in re.finditer(r"^co-authored-by:\s*(.+?)\s*(?:<[^>]*>)?\s*$", msg, re.I | re.M):
        if B.canon_agent(m.group(1), strict_unknown=True):
            return m.group(1).strip()
    return author.strip() if B.canon_agent(author, strict_unknown=True) else None


def is_ancestor(repo, older, newer):
    return _git(repo, "merge-base", "--is-ancestor", older, newer, check=False).returncode == 0


# ---------------------------------------------------------------- seal (owner approval)
def seal_state():
    if _bytes(_p("checks.json")) is None:
        return {"ok": False, "reason": "no checks defined yet"}
    s = _json(_p("seal.json"), None)
    if not isinstance(s, dict):
        return {"ok": False, "reason": "checks are not approved in the window yet"}
    if _sha(_bytes(_p("checks.json"))) != s.get("checks_sha"):
        return {"ok": False, "reason": "checks.json changed outside the window; approve it again"}
    if _sha(_bytes(_p("policy.json"))) != s.get("policy_sha"):
        return {"ok": False, "reason": "policy.json changed outside the window; approve it again"}
    return {"ok": True, "approved_at": s.get("approved_at"), "pins": s.get("pins", {})}


def owner_approve(now=None):
    """Window click 'Approve checks': seal checks.json + policy.json and pin the test paths at each repo's HEAD."""
    now = time.time() if now is None else now
    checks = load_checks()
    if not checks["jobs"]:
        raise GateError("checks.json has no job types")
    pins, heads = {}, {}
    for job, spec in checks["jobs"].items():
        repo = spec.get("repo") or ""
        head = _git(repo, "rev-parse", "HEAD")
        ids = pin_ids(repo, head, spec.get("pinned", []))
        missing = [p for p, v in ids.items() if not v]
        if missing:
            raise GateError("%s: pinned path not in the repo: %s" % (job, ", ".join(missing)))
        pins[job], heads[job] = ids, head
    if _bytes(_p("policy.json")) is None:
        _atomic_json(_p("policy.json"), DEFAULT_POLICY)
    seal = {"checks_sha": _sha(_bytes(_p("checks.json"))), "policy_sha": _sha(_bytes(_p("policy.json"))),
            "pins": pins, "pin_commits": heads, "approved_at": round(now, 3)}
    _atomic_json(_p("seal.json"), seal)
    _log({"event": "seal", "ts": round(now, 3), "checks_sha": seal["checks_sha"], "policy_sha": seal["policy_sha"], "jobs": sorted(pins)})
    return seal


def owner_set_mode(live, now=None):
    """Window switch: go live or back to dry-run. Only from a valid seal; re-seals the policy."""
    now = time.time() if now is None else now
    st = seal_state()
    if not st["ok"]:
        raise GateError(st["reason"])
    pol = _json(_p("policy.json"), {}) or {}
    pol["dry_run"] = not live
    _atomic_json(_p("policy.json"), {**DEFAULT_POLICY, **pol})
    s = _json(_p("seal.json"), {})
    s["policy_sha"] = _sha(_bytes(_p("policy.json")))
    _atomic_json(_p("seal.json"), s)
    _log({"event": "mode", "ts": round(now, 3), "mode": "live" if live else "dry"})
    return {"mode": "live" if live else "dry-run"}


# ---------------------------------------------------------------- log
def decisions():
    """Every decision with its current status, oldest first (the log is append-only; later events change status)."""
    out, by_id = [], {}
    b = _bytes(_p("gate.jsonl")) or b""
    for line in b.decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("event") == "decision" and e.get("id"):
            d = dict(e)
            by_id[d["id"]] = d
            out.append(d)
        elif e.get("id") in by_id:
            d = by_id[e["id"]]
            status = {"reverted": "reverted", "clawed_back": "clawed_back", "would_claw_back": "would_claw_back",
                      "approved": "awarded", "declined": "declined"}.get(e.get("event"))
            if status:
                d["status"] = status
                d.setdefault("history", []).append({"event": e["event"], "ts": e.get("ts"), "why": e.get("why", "")})
    return out


def owner_totals():
    """Scores from rows the owner gave (gate rows never count toward rank)."""
    B = brain()
    totals = {}
    for r in B.read_ledger():
        if GATE_MARK.search(r.get("event", "")):
            continue
        totals[r["agent"]] = totals.get(r["agent"], 0) + r["eff"]
    return totals


def rank_threshold(name):
    for n, frm, _perks in brain().framework()["ranks"]:
        if n.lower() == (name or "").lower() and frm is not None:
            return frm
    return 100


# ---------------------------------------------------------------- identity and usage
def same_identity(a, b):
    """Two labels are one runner when they share a runner name, a model family or a program."""
    B = brain()
    ca, cb_ = B.canon_agent(a), B.canon_agent(b)
    if ca and ca == cb_:
        return True
    ma, mb = B.model_of(a), B.model_of(b)
    if ma and mb and ma.split()[0].lower() == mb.split()[0].lower():
        return True
    pa, pb = B.program_of(a), B.program_of(b)
    return bool(pa and pa == pb)


def transcripts_root():
    return os.environ.get("CB_TRANSCRIPTS") or os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _model_name(mid):
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", mid or "")
    return ("%s %s.%s" % (m.group(1).capitalize(), m.group(2), m.group(3))) if m else ""


def measure_usage(path, now=None):
    """Tokens of the current turn (since the last real user message) and the model, from a Claude Code transcript.
    Returns (usage or None, why-not). Measured only: a file outside the transcripts folder or a stale file gives None."""
    now = time.time() if now is None else now
    if not path:
        return None, "no transcript given"
    root = os.path.realpath(transcripts_root())
    real = os.path.realpath(path)
    if not real.lower().startswith(root.lower() + os.sep):
        return None, "transcript is not in the Claude Code transcripts folder"
    try:
        if now - os.path.getmtime(real) > 1800:
            return None, "transcript is older than 30 minutes"
        with open(real, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4 * 1024 * 1024))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None, "transcript unreadable"
    turn, model, started, t0 = {}, "", False, None
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        if not isinstance(msg, dict) or rec.get("isSidechain"):
            continue
        if rec.get("type") == "user":
            c = msg.get("content")
            real_prompt = isinstance(c, str) or (isinstance(c, list) and not any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c))
            if real_prompt and not rec.get("isMeta") and not rec.get("isCompactSummary"):
                turn, model, started, t0 = {}, "", True, _iso(rec.get("timestamp"))
        elif rec.get("type") == "assistant" and started:
            u = msg.get("usage") or {}
            try:
                turn[msg.get("id") or len(turn)] = int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
            except (TypeError, ValueError):
                continue
            model = _model_name(msg.get("model")) or model
    if not started or not turn:
        return None, "no measured usage in this turn"
    return {"tokens": sum(turn.values()), "model": model, "started": t0}, ""


def _iso(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- running checks
def _limit_self(cores):
    """Idle priority and at most `cores` cores for this process; every check it starts inherits both."""
    if os.name != "nt":
        try:
            os.nice(19)
            os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:cores]))
        except (AttributeError, OSError):
            pass
        return
    import ctypes
    k = ctypes.windll.kernel32
    h = k.GetCurrentProcess()
    k.SetPriorityClass(h, IDLE_PRIORITY)
    k.SetProcessAffinityMask(h, ctypes.c_size_t((1 << max(1, int(cores))) - 1))


def _kill_tree(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass


def _rmtree(path):
    def onerr(fn, p, _exc):
        try:
            os.chmod(p, 0o700)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerr)


def checkout(repo, commit, dest):
    """A clean copy of exactly that commit: no working-tree edits, no untracked files, no git metadata."""
    data = _git(repo, "archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest, filter="data")


def tree_hash(root, rel):
    h = hashlib.sha256()
    base = os.path.join(root, rel) if rel else root
    if os.path.isfile(base):
        return _sha(_bytes(base))
    for d, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(d, name)
            h.update(os.path.relpath(p, base).replace("\\", "/").encode() + b"\0" + (_bytes(p) or b"") + b"\0")
    return h.hexdigest()


def run_checks(spec, repo, commit, policy):
    """Run every check of a job type on a clean checkout. The gate builds the commands; nothing comes from the agent."""
    tmp = tempfile.mkdtemp(prefix="cb_gate_run_")
    root = os.path.join(tmp, "src")
    results, artifact = [], None
    try:
        checkout(repo, commit, root)
        if spec.get("artifact"):
            artifact = tree_hash(root, spec["artifact"])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for c in spec.get("checks", []):
            argv = [sys.executable if a == "{python}" else str(a).replace("{root}", root) for a in c.get("run", [])]
            timeout = int(c.get("timeout") or policy["check_timeout"])
            t0 = time.time()
            try:
                p = subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                     creationflags=NO_WINDOW | IDLE_PRIORITY, start_new_session=os.name != "nt")
            except OSError as e:
                results.append({"name": c.get("name", "check"), "cmd": argv, "exit": None, "ok": False, "secs": 0,
                                "required": c.get("required", True), "out_sha": "", "tail": "could not start: %s" % e})
                continue
            try:
                out, _ = p.communicate(timeout=timeout)
                code = p.returncode
            except subprocess.TimeoutExpired:
                _kill_tree(p.pid)
                out, _ = p.communicate()
                code = None
            results.append({"name": c.get("name", "check"), "cmd": argv, "exit": code, "ok": code == 0,
                            "timeout": code is None, "secs": round(time.time() - t0, 2), "required": c.get("required", True),
                            "out_sha": _sha(out), "tail": (out or b"")[-600:].decode("utf-8", "replace")})
    except GateError as e:
        results.append({"name": "checkout", "cmd": ["git", "archive", commit], "exit": None, "ok": False, "secs": 0,
                        "required": True, "out_sha": "", "tail": str(e)})
    finally:
        _rmtree(tmp)
    return results, artifact


# ---------------------------------------------------------------- the claim
def _short(c):
    return (c or "")[:7]


def _failed(results):
    return [r for r in results if r.get("required", True) and not r["ok"]]


def _fail_words(r):
    return "'%s' %s" % (r["name"], "timed out" if r.get("timeout") else "failed (exit %s)" % r["exit"])


def claim(job, commit, transcript=None, for_name=None, now=None, _lock=True):
    """Score one finished job. Returns the decision (also appended to gate.jsonl)."""
    now = time.time() if now is None else now
    pol = load_policy()
    mode = "dry" if pol.get("dry_run", True) else "live"
    d = {"event": "decision", "id": "g-" + uuid.uuid4().hex[:10], "ts": round(now, 3), "job": job, "commit": commit,
         "mode": mode, "points": 0, "status": "blocked"}

    def done(status, reason, **extra):
        d.update(status=status, reason=reason, **extra)
        d["explain"] = explain(d)
        _log(d)
        return d

    st = seal_state()
    if not st["ok"]:
        return done("blocked", "gate stopped: " + st["reason"])
    spec = load_checks()["jobs"].get(job)
    if not spec:
        return done("blocked", "no job type '%s' in the owner's checks" % job)
    repo = spec.get("repo") or ""
    d["repo"] = repo
    try:
        commit = d["commit"] = resolve_commit(repo, commit)
    except GateError as e:
        return done("blocked", str(e))
    for old in decisions():
        if old.get("job") == job and old.get("commit") == commit and old.get("checks") is not None:
            return done("duplicate", "this commit was already scored (%s)" % old["id"], dup_of=old["id"])
    runner = commit_runner(repo, commit)
    if not runner:
        return done("blocked", "the commit names no runner (author or Co-Authored-By)")
    B = brain()
    d.update(runner=B.canon_agent(runner), runner_raw=runner)
    usage, why_no_usage = measure_usage(transcript, now) if transcript else (None, "no transcript given")
    awarder = (usage or {}).get("model") or runner
    if for_name and not same_identity(for_name, runner):
        return done("blocked", "--for names %s but the commit was made by %s" % (for_name, B.canon_agent(runner)))
    kind = "self" if same_identity(awarder, runner) else "peer"
    d.update(by=B.canon_agent(awarder), kind=kind)
    if for_name and not transcript:
        return done("blocked", "a peer award needs your own transcript to show who you are")
    if kind == "peer":
        need = rank_threshold(pol["peer_rank"])
        have = owner_totals().get(d["by"], 0)
        if have < need:
            return done("blocked", "%s has %+d owner-given points; awarding others needs %s (%+d)" % (d["by"], have, pol["peer_rank"], need))
        if _closes_cycle(d["by"], d["runner"], mode, now, pol):
            return done("blocked", "%s and %s would be awarding each other (reciprocal or circular)" % (d["by"], d["runner"]))
    pins = st["pins"].get(job, {})
    changed = changed_pins(repo, commit, pins)
    if changed:
        return done("blocked", "test files changed in this commit (%s); needs owner re-approval" % ", ".join(changed))
    if _lock and not _take_lock(now):
        return done("busy", "another gate run is in progress; try again in a minute")
    try:
        results, artifact = run_checks(spec, repo, commit, pol)
    finally:
        if _lock:
            _drop_lock()
    ev_path = _p("evidence", d["id"] + ".json")
    _atomic_json(ev_path, {"id": d["id"], "job": job, "repo": repo, "commit": commit, "artifact_sha": artifact,
                           "pins": pins, "checks": results, "ts": round(now, 3)})
    d.update(evidence=ev_path, artifact_sha=artifact, all_pass=not _failed(results),
             checks=[{"name": r["name"], "exit": r["exit"], "ok": r["ok"], "secs": r["secs"]} for r in results])
    if not results:
        return done("blocked", "the job type has no checks")
    failed = _failed(results)
    if not failed and not all(r["ok"] for r in results):   # optional checks fail: base points only, never a usage bonus
        usage, why_no_usage = None, "an optional check failed, so no usage bonus"
    if failed:
        d["clawbacks"] = _regressions(job, spec, commit, results, mode, now, pol)
        return done("blocked", ", ".join(_fail_words(r) for r in failed) + " at " + _short(commit))
    # quality passed: base points, plus a usage bonus only when usage was measured for this runner's own turn
    base = int(spec.get("base", 5))
    bonus, base_tokens, runs = 0, None, 0
    tokens = usage["tokens"] if (usage and kind == "self") else None
    if usage and kind == "self":
        prior = [x["tokens"] for x in decisions() if x.get("job") == job and x.get("all_pass") and x.get("tokens")
                 and x.get("status") in COUNTED[mode] + ("waiting", "would_wait")]
        runs = len(prior)
        if runs >= int(pol["bonus_min_runs"]):
            base_tokens = statistics.median(prior)
            share = max(0.0, min(1.0, (base_tokens - tokens) / base_tokens)) if base_tokens else 0.0
            bonus = int(round(base * float(pol["bonus_ceiling"]) * share))
        else:
            why_no_usage = "only %d earlier passing run%s, %d needed for a baseline" % (runs, "" if runs == 1 else "s", int(pol["bonus_min_runs"]))
    elif usage:
        why_no_usage = "usage is only counted for the runner's own turn"
    pts = base + bonus
    d.update(base=base, bonus=bonus, tokens=tokens, baseline=base_tokens, baseline_runs=runs, no_bonus=why_no_usage if not bonus else "", points=pts)
    over = _over_cap(d["runner"], pts, mode, now, pol)
    if mode == "dry":
        return done("would_wait" if over else "would_award", over or "all checks passed")
    if over:
        return done("waiting", over)
    _write_ledger(d, pts, "award")
    return done("awarded", "all checks passed")


def _over_cap(runner, pts, mode, now, pol):
    if pts > int(pol["self_cap"]):
        return "over the %+d per-award cap" % int(pol["self_cap"])
    recent = [x for x in decisions() if x.get("runner") == runner and x.get("status") in COUNTED[mode] and now - float(x.get("ts", 0)) < 86400]
    if len(recent) >= int(pol["awards_per_24h"]):
        return "already %d gate awards in 24 h" % len(recent)
    got = sum(int(x.get("points", 0)) for x in recent)
    if got + pts > int(pol["daily_cap"]):
        return "would pass the %+d daily cap (%+d already today)" % (int(pol["daily_cap"]), got)
    return ""


def _closes_cycle(awarder, beneficiary, mode, now, pol):
    edges = {}
    for x in decisions():
        if x.get("kind") == "peer" and x.get("status") in EDGES[mode] and now - float(x.get("ts", 0)) < 86400 * int(pol["cycle_days"]):
            edges.setdefault(x["by"], set()).add(x["runner"])
    seen, todo = set(), [beneficiary]
    while todo:
        n = todo.pop()
        if n == awarder:
            return True
        if n not in seen:
            seen.add(n)
            todo.extend(edges.get(n, ()))
    return False


def _write_ledger(d, pts, what, why=None):
    """One ledger entry through the window's append_ledger (backup first). The marker keeps gate points out of rank."""
    B = brain()
    clean = lambda s: re.sub(r"[|\r\n]+", " / ", s or "").strip()   # noqa: E731  (a markdown ledger row stays one row)
    reason = clean(why or d.get("explain") or explain(dict(d, status="awarded"))) + " [gate %s %s]" % (what, d["id"])
    bak, _lines = B.append_ledger([(clean(d.get("runner_raw") or d["runner"]), int(pts), "gate: " + clean(d["job"]), reason)])
    return bak


def _regressions(job, spec, commit, results, mode, now, pol):
    """This commit fails a check. Recheck earlier awarded commits it builds on: one that now fails the same check never
    really passed it, so its points come back. One that still passes is fine; then this commit is what broke it."""
    repo = spec.get("repo") or ""
    failing = {r["name"] for r in _failed(results)}
    out = []
    olds = [x for x in reversed(decisions()) if x.get("job") == job and x.get("status") in COUNTED[mode] and x.get("commit") != commit
            and now - float(x.get("ts", 0)) < 86400 * int(pol["recheck_days"])]
    for x in olds[:3]:
        if is_ancestor(repo, x["commit"], commit):
            out += recheck_one(x, spec, pol, now, only=failing)
    return out


def recheck_one(x, spec, pol, now, only=None):
    st = seal_state()
    pins = st.get("pins", {}).get(x["job"], {})
    if not st["ok"] or changed_pins(spec["repo"], x["commit"], pins):
        return []    # checks were re-approved since; this commit is judged by the old tests, so it is not rechecked
    res, _art = run_checks(spec, spec["repo"], x["commit"], pol)
    bad = [r for r in _failed(res) if not only or r["name"] in only]
    if not bad:
        return []
    why = "regression: %s at %s, which passed when awarded" % (", ".join(_fail_words(r) for r in bad), _short(x["commit"]))
    if x.get("mode") == "live":
        _write_ledger(x, -int(x.get("points", 0)), "clawback", why)
        _log({"event": "clawed_back", "id": x["id"], "ts": round(now, 3), "why": why, "points": -int(x.get("points", 0))})
    else:
        _log({"event": "would_claw_back", "id": x["id"], "ts": round(now, 3), "why": why, "points": -int(x.get("points", 0))})
    return [x["id"]]


def recheck(days=None, now=None):
    now = time.time() if now is None else now
    pol = load_policy()
    days = pol["recheck_days"] if days is None else days
    jobs = load_checks()["jobs"]
    out = []
    for x in decisions():
        if x.get("status") in ("awarded", "would_award") and now - float(x.get("ts", 0)) < 86400 * days and x.get("job") in jobs:
            out += recheck_one(x, jobs[x["job"]], pol, now)
    return out


def _take_lock(now):
    path = _p("run.lock")
    os.makedirs(gate_dir(), exist_ok=True)
    try:
        if os.path.exists(path) and now - os.path.getmtime(path) > 3600:
            os.remove(path)
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except OSError:
        return False


def _drop_lock():
    try:
        os.remove(_p("run.lock"))
    except OSError:
        pass


# ---------------------------------------------------------------- owner actions on decisions (window clicks)
def _find(did):
    d = next((x for x in decisions() if x["id"] == did), None)
    if not d:
        raise GateError("no such gate decision")
    return d


def owner_revert(did, now=None):
    now = time.time() if now is None else now
    d = _find(did)
    if d.get("status") != "awarded":
        raise GateError("only a written award can be reverted (this one is %s)" % d.get("status"))
    bak = _write_ledger(d, -int(d["points"]), "revert", "reverted by the owner: %s" % d.get("explain", ""))
    _log({"event": "reverted", "id": did, "ts": round(now, 3), "why": "reverted by the owner"})
    return {"ok": True, "backup": bak}


def owner_decide(did, approve, now=None):
    now = time.time() if now is None else now
    d = _find(did)
    if d.get("status") != "waiting":
        raise GateError("that award is not waiting (it is %s)" % d.get("status"))
    if not seal_state()["ok"]:
        raise GateError(seal_state()["reason"])
    bak = None
    if approve:
        bak = _write_ledger(d, int(d["points"]), "approved", "%s (approved by the owner)" % explain(dict(d, status="awarded")))
    _log({"event": "approved" if approve else "declined", "id": did, "ts": round(now, 3)})
    return {"ok": True, "backup": bak}


# ---------------------------------------------------------------- plain words
def explain(d):
    who = d.get("runner") or "the runner"
    st = d.get("status")
    if st in ("blocked", "busy", "duplicate"):
        return ("No points for %s: %s." % (d["runner"], d.get("reason", ""))) if d.get("runner") else "No points: %s." % d.get("reason", "")
    names = [c["name"] for c in d.get("checks", []) if c.get("ok")]
    line = "%+d to %s%s: %d/%d checks passed (%s) at %s; base %+d" % (
        d.get("points", 0), who, "" if d.get("kind") != "peer" else " from %s" % d.get("by"), len(names), len(d.get("checks", [])),
        ", ".join(names), _short(d.get("commit")), d.get("base", 0))
    if d.get("bonus"):
        cut = 100 * (d["baseline"] - d["tokens"]) / d["baseline"]
        line += " + %d for %d%% fewer tokens than the median of %d passing runs" % (d["bonus"], round(cut), d["baseline_runs"])
    else:
        line += ", no usage bonus (%s)" % (d.get("no_bonus") or "usage not below the median")
    line += "."
    if st == "would_award":
        return "Dry-run, nothing written: would give " + line
    if st == "would_wait":
        return "Dry-run, nothing written: would wait for your click (%s): %s" % (d.get("reason"), line)
    if st == "waiting":
        return "Waits for your click (%s): %s" % (d.get("reason"), line)
    return line


def window_view(now=None, days=3):
    """What the window shows: mode, seal, and recent decisions in plain words (waiting ones always)."""
    now = time.time() if now is None else now
    pol, st = load_policy(), seal_state()
    jobs = load_checks()["jobs"]
    items = []
    for d in reversed(decisions()):
        if d.get("status") == "waiting" or now - float(d.get("ts", 0)) < 86400 * days:
            if d.get("status") == "duplicate":
                continue
            hist = d.get("history") or []
            items.append({"id": d["id"], "status": d.get("status"), "runner": d.get("runner") or "", "by": d.get("by") or "",
                          "kind": d.get("kind") or "self", "points": int(d.get("points", 0)), "commit": _short(d.get("commit")),
                          "job": d.get("job", ""), "ts": d.get("ts", 0),
                          "explain": d.get("explain") or explain(d), "after": hist[-1]["why"] if hist and hist[-1].get("why") else "",
                          "can_revert": d.get("status") == "awarded", "can_decide": d.get("status") == "waiting"})
    items = items[:30]
    events = []
    b = _bytes(_p("gate.jsonl")) or b""
    for line in b.decode("utf-8", "replace").splitlines()[-400:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("event") in OWNER_EVENTS and now - float(e.get("ts", 0)) < 86400 * 7:
            what = OWNER_EVENTS[e["event"]]
            if e["event"] == "mode":
                what = "switched to " + ("live" if e.get("mode") == "live" else "dry-run")
            events.append({"ts": e.get("ts", 0), "text": what + ((" " + e["id"]) if e.get("id") else "")})
    return {"events": events[::-1][:12],
            "configured": bool(jobs) or bool(items), "mode": "dry-run" if pol.get("dry_run", True) else "live",
            "seal": {"ok": st["ok"], "reason": st.get("reason", ""), "approved_at": st.get("approved_at")},
            "jobs": sorted(jobs), "items": items,
            "waiting": sum(1 for i in items if i["status"] == "waiting")}


# ---------------------------------------------------------------- automatic: a finished turn with a fresh commit
def hook_target(payload, now=None):
    """(job, commit, transcript) when THIS finished turn committed in an owner job's repo, by the same runner, unscored.
    Self-claims only: peer awards stay explicit (claim --for)."""
    now = time.time() if now is None else now
    cwd = os.path.normcase(os.path.abspath(payload.get("cwd") or ""))
    if not payload.get("cwd"):
        return None
    for job, spec in load_checks()["jobs"].items():
        repo = os.path.normcase(os.path.abspath(spec.get("repo") or ""))
        if not spec.get("repo") or not (cwd == repo or cwd.startswith(repo + os.sep)):
            continue
        try:
            head = _git(spec["repo"], "rev-parse", "HEAD")
            when = float(_git(spec["repo"], "log", "-1", "--format=%ct", "HEAD"))
        except (GateError, ValueError):
            return None
        usage, _why = measure_usage(payload.get("transcript_path"), now)
        if not usage:
            return None      # no measured turn: the hook does not guess who worked
        started = usage.get("started") or now - 1800
        if when < started - 60:
            return None      # HEAD is older than this turn: not this session's commit
        runner = commit_runner(spec["repo"], head)
        if not runner or not same_identity(runner, usage["model"]):
            return None      # another runner's commit (e.g. a parallel session): only an explicit --for may award it
        if any(x.get("job") == job and x.get("commit") == head and x.get("checks") is not None for x in decisions()):
            return None
        return job, head, payload.get("transcript_path")
    return None


def hook(payload, now=None):
    """Start the claim in the background (idle priority, no window) so the agent's session never waits on checks."""
    t = hook_target(payload, now)
    if not t:
        return None
    job, head, transcript = t
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "python.exe" and os.path.isfile(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    argv = [exe, os.path.abspath(__file__), "claim", "--job", job, "--commit", head] + (["--transcript", transcript] if transcript else [])
    flags = (NO_WINDOW | IDLE_PRIORITY | 0x00000008 | 0x00000200) if os.name == "nt" else 0   # + DETACHED, NEW_PROCESS_GROUP
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    p.returncode = 0     # detached on purpose: never waited on (keeps Popen from warning that it still runs)
    return argv


# ---------------------------------------------------------------- CLI (what agents may call)
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["claim", "recheck", "status", "hook"])
    ap.add_argument("--job", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--transcript", default="")
    ap.add_argument("--for", dest="for_name", default="")
    ap.add_argument("--days", type=float, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "hook":    # Claude Code Stop hook: never fails the session, never prints, never waits for the checks
        try:
            hook(json.loads(sys.stdin.read() or "{}") if sys.stdin and not sys.stdin.isatty() else {})
        except Exception:
            pass
        return 0
    if a.cmd == "status":
        v = window_view()
        print("Gate: %s; seal %s; job types: %s" % (v["mode"], "ok" if v["seal"]["ok"] else "NOT OK (" + v["seal"]["reason"] + ")", ", ".join(v["jobs"]) or "none"))
        for i in v["items"]:
            print("%-14s %-12s %s" % (i["id"], i["status"], i["explain"]))
        return 0
    _limit_self(load_policy()["cores"])
    if a.cmd == "recheck":
        ids = recheck(a.days)
        print("rechecked; taken back: %s" % (", ".join(ids) or "none"))
        return 0
    if not a.job or not a.commit:
        ap.error("claim needs --job and --commit")
    d = claim(a.job, a.commit, a.transcript or None, a.for_name or None)
    print("%s %s: %s" % (d["id"], d["status"], d["explain"]))
    return 0 if d["status"] in ("awarded", "would_award", "waiting", "would_wait") else 1


if __name__ == "__main__":
    sys.exit(main())
