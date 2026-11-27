"""Consequences Brain referee worker: the slow part of the referee, run in its own low-priority process.

Rules only, no AI: it reads local files and does arithmetic. No network, no model calls, no subprocess.
One pass (python cb_refwork.py, started by the window every couple of minutes at idle priority):
  1. update the transcript index (cb_evidence), only bytes added since the last pass;
  2. hear the owner: points he typed in a session are logged to the ledger once, for the runner of that session,
     after the runner had time to log them itself. Offers, take-backs and group awards are not written: they wait
     for him in the window ("needs you");
  3. learn (cb_learn): retrain, replay held-out cases, adopt only a better version, roll back on bad live results;
  4. delegation: which runner has earned the next job, from the owner's own awards;
  5. autonomy: pay or deduct by itself ONLY when the backtest clears the fixed bar, within fixed caps, never for
     runners on the local never_auto list, marked [referee], revertible, overridden by anything the owner says;
  6. integrity: a seal over the referee's code, caps and never_auto list; any change shows in the window.
Everything it keeps lives in local app data. It writes the ledger only through the window's own append_ledger.
"""
import hashlib
import json
import os
import re
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
import cb_activity  # noqa: E402
import cb_evidence  # noqa: E402
import cb_learn  # noqa: E402
import cb_referee  # noqa: E402

# ---- fixed limits: never learned, never loosened by the learner (changing them breaks the seal, which shows)
AUTO_ROW_CAP = 5            # one automatic row is at most +/-5
AUTO_DAY_CAP = 10           # and at most +/-10 per runner per day
HEAR_DELAY = 10 * 60        # give the runner 10 minutes to log the owner's award itself
HEAR_MATCH = 45 * 60        # an existing row for the same runner and amount within 45 min is the same award
AUTO_MARK = "[referee]"
REVERT_MARK = "[referee revert]"
HEARD_MARK = "[heard]"
SEALED = ("cb_referee.py", "cb_learn.py", "cb_evidence.py", "cb_refwork.py")
_GROUP = re.compile(r"\ball (?:the |my |our )?(?:agents|models|of you|claude)\b|\beveryone\b|\bboth of you\b", re.I)
_TAKEBACK = re.compile(r"\btake (?:it |that |them )?back\b|\btook back\b|\bswitch that\b|\bmake (?:that|it)\b|\bno,? (?:minus|plus)\b|\binstead\b|\btoo harsh\b|\bi just gave\b", re.I)


def _jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def data_dir():
    d = os.environ.get("CB_REFEREE_DIR") or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share"), "Consequences", "referee")
    os.makedirs(d, exist_ok=True)
    return d


def _load(path, default):
    try:
        return _jload(path)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def runner_label(turn):
    """'Claude Opus 5.5 (Claude Code, project)': the session's model, the tool and where it ran."""
    proj = os.path.basename((turn.get("cwd") or "").rstrip("\\/")) or "session"
    return "%s (Claude Code, %s)" % (cb_evidence.model_label(turn.get("model")) or "Claude", proj)


# ---------------------------------------------------------------- 2. hear the owner
def recommend_ok(profile):
    """Learned amounts are offered on the cards only when the backtest beats guessing and made no confident false
    deduction. Below that the evidence is shown as information and the fixed rules decide."""
    m = profile.get("metrics") or {}
    return bool(m.get("n") and m.get("sign_acc", 0) > m.get("majority_baseline", 1) and not m.get("confident_false_ded"))


def heard_candidates(sessions):
    """Every owner message with points: [{uuid, t, session, runner, awards[(pts)], offer, takeback, group, said}].
    The runner is the model that did the work he is reacting to (the turn before his message)."""
    out = []
    for sid, turns in sessions.items():
        for i, t in enumerate(turns):
            pts = t.get("owner_pts") or []
            if not pts or not t.get("start"):
                continue
            prev = turns[i - 1] if i else None
            who = prev if prev and prev.get("model") else t
            if not who.get("model"):
                continue
            said = t.get("owner") or ""
            out.append({"uuid": t.get("uuid"), "t": t["start"], "session": sid, "runner": runner_label(who),
                        "awards": [p for p, k in pts if k == "award"], "offer": any(k == "offer" for _, k in pts),
                        "takeback": bool(_TAKEBACK.search(said)), "group": bool(_GROUP.search(said)), "said": said[:140]})
    return sorted(out, key=lambda c: c["t"])


def _row_t(r):
    return r.get("t") if r.get("t") is not None else cb_referee.row_time(r.get("ts"))


def already_logged(c, pts, rows, canon, row_sessions):
    who = canon(c["runner"])
    for r in rows:
        if (canon(r.get("runner") or r.get("agent") or "") != who and r.get("agent") != who) or int(r.get("pts") or 0) != pts:
            continue
        if c["uuid"] and c["uuid"][:8] in (r.get("event") or ""):
            return True
        if row_sessions.get(r.get("key")) == c["session"]:
            return True
        # compare on the row's corrected time AND its raw stamp: a message and a row written by the same wrong clock
        # agree on the raw stamp, a row from another machine agrees on the corrected one
        for t in {_row_t(r), cb_referee.row_time(r.get("ts"))}:
            if t is not None and abs(t - c["t"]) <= HEAR_MATCH:
                return True
    return False


def hear(sessions, rows, canon, row_sessions, state, now, write):
    """Log new owner awards once. Returns {logged, needs_you, history_gaps}. `state` keeps the cursor and seen ids."""
    seen = set(state.setdefault("seen", []))
    names = {r.get("agent") for r in rows if r.get("agent") and r.get("agent") != "UNATTRIBUTED" and len(r.get("agent")) > 2}
    since = state.setdefault("since", now)          # first run: never backfill history, only report it
    logged, needs, gaps = [], [], 0
    for c in heard_candidates(sessions):
        if c["uuid"] in seen or not c["awards"]:
            continue
        if c["t"] < since:
            gaps += sum(1 for p in c["awards"] if not already_logged(c, p, rows, canon, row_sessions))
            continue
        if now - c["t"] < HEAR_DELAY:
            continue
        new = [p for p in c["awards"] if not already_logged(c, p, rows, canon, row_sessions)]
        # partly logged already: the runner wrote down its reading of a mixed message, so the rest is his call
        named = {n for n in names if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", c["said"], re.I)}
        other = bool(named) and canon(c["runner"]) not in named       # he named a different runner than this session's
        unclear = c["offer"] or c["takeback"] or c["group"] or other or len(new) < len(c["awards"])
        if new and unclear:
            needs.append({"runner": c["runner"], "points": new, "said": c["said"], "t": c["t"]})
        elif new:
            entries = [(c["runner"], p, "%s m:%s s:%s" % (HEARD_MARK, (c["uuid"] or "")[:8], c["session"][:8]),
                        "owner said: " + re.sub(r"\s+", " ", c["said"])[:110].replace("|", "/")) for p in new]
            write(entries)
            logged += [{"runner": e[0], "points": e[1]} for e in entries]
        seen.add(c["uuid"])
    state["seen"] = sorted(seen)[-5000:]
    return {"logged": logged, "needs_you": needs[-10:], "history_gaps": gaps}


# ---------------------------------------------------------------- 4. delegation
def delegation(rows, canon, now, days=14):
    """Who has earned the next job: plus-rate over the owner's last `days` of awards (smoothed), with n shown."""
    stats = {}
    for r in rows:
        t = _row_t(r)
        if t is None or now - t > days * 86400 or not r.get("pts") or re.search(r"\[(referee|heard)\]|gate award", r.get("event") or ""):
            continue
        a = r.get("agent") or canon(r.get("runner") or "")
        if not a or a == "UNATTRIBUTED" or re.search(r"\ball\b", a, re.I):
            continue
        s = stats.setdefault(a, {"runner": a, "n": 0, "plus": 0, "net": 0})
        s["n"] += 1
        s["plus"] += r["pts"] > 0
        s["net"] += r["pts"]
    out = []
    for s in stats.values():
        s["score"] = round((s["plus"] + 1) / (s["n"] + 2), 3)
        out.append(s)
    out.sort(key=lambda s: (-s["score"], -s["n"]))
    return [s for s in out if s["n"] >= 3][:3]


# ---------------------------------------------------------------- 5. autonomy (dormant until the backtest clears the bar)
def auto_rows(pending, rows, canon, profile, never_auto, now):
    """pending: [{key, runner, learned, session}] open asks with a learned verdict. Returns ledger entries to write
    and the reasons the rest were left to the owner. Fixed caps; never for never_auto runners; never below the bar."""
    if not profile.get("autonomy_ok"):
        return [], [{"key": p["key"], "why": "backtest has not cleared the bar"} for p in pending]
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    used = {}
    for r in rows:
        if AUTO_MARK in (r.get("event") or "") and str(r.get("ts", "")).startswith(day):
            used[r.get("agent")] = used.get(r.get("agent"), 0) + int(r.get("pts") or 0)
    blocked = {canon(n) for n in never_auto}
    out, left = [], []
    for p in pending:
        who, lv = canon(p["runner"]), p.get("learned") or {}
        if who in blocked:
            left.append({"key": p["key"], "why": "never auto-scored: it builds or changes the referee"})
            continue
        if not lv.get("confident") or not lv.get("points"):
            left.append({"key": p["key"], "why": "not sure enough: asks the owner"})
            continue
        pts = max(-AUTO_ROW_CAP, min(AUTO_ROW_CAP, int(lv["points"])))
        room = AUTO_DAY_CAP - used.get(who, 0) if pts > 0 else -AUTO_DAY_CAP - used.get(who, 0)
        pts = min(pts, room) if pts > 0 else max(pts, room)
        if not pts or (pts > 0) != (lv["points"] > 0):
            left.append({"key": p["key"], "why": "daily cap reached"})
            continue
        used[who] = used.get(who, 0) + pts
        out.append((p["runner"], pts, "%s k:%s v:%s" % (AUTO_MARK, hashlib.sha1(p["key"].encode()).hexdigest()[:8], profile.get("version")),
                    "learned verdict, %d%% sure" % (max(lv["p_plus"], 1 - lv["p_plus"]) * 100)))
    return out, left


def revert_entry(row):
    """The one-click undo for an automatic row: an equal and opposite row (the ledger is append-only)."""
    return (row.get("runner") or row.get("agent"), -int(row.get("pts") or 0), REVERT_MARK + " " + (row.get("id") or ""),
            "owner reverted the referee's automatic row")


# ---------------------------------------------------------------- 6. integrity
def seal_now(never_auto):
    h = hashlib.sha256()
    for n in SEALED:
        try:
            with open(os.path.join(APP_DIR, n), "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"missing:" + n.encode())
    h.update(json.dumps({"row": AUTO_ROW_CAP, "day": AUTO_DAY_CAP, "never_auto": sorted(never_auto),
                         "bar": "n>=15 conf_n>=8 conf_acc>=0.8 conf_fd=0 acc>=base+0.1"}, sort_keys=True).encode())
    return h.hexdigest()


def integrity(folder, never_auto, now):
    """{'ok', 'changed_at', 'text'}: the first seal is taken on the first run; any later change to the referee's code,
    caps or never_auto list is shown in the window (with when) until the owner accepts it there."""
    path = os.path.join(folder, "seal.json")
    seal = _load(path, None)
    cur = seal_now(never_auto)
    if not seal:
        _save(path, {"sha": cur, "at": now, "history": []})
        return {"ok": True, "text": "Sealed: referee code, caps and never-auto list."}
    if seal.get("sha") == cur:
        return {"ok": True, "text": "Unchanged since %s." % time.strftime("%d %b %H:%M", time.localtime(seal.get("at", now)))}
    if seal.get("pending") != cur:
        seal["pending"], seal["changed_at"] = cur, now
        _save(path, seal)
    return {"ok": False, "changed_at": seal.get("changed_at"),
            "text": "The referee's code, caps or never-auto list changed at %s. Shown until you accept it." % time.strftime("%d %b %H:%M", time.localtime(seal.get("changed_at") or now))}


def accept_seal(folder, never_auto):
    path = os.path.join(folder, "seal.json")
    seal = _load(path, {"history": []})
    seal.setdefault("history", []).append({"sha": seal.get("sha"), "until": time.time()})
    seal.update(sha=seal_now(never_auto), at=time.time(), pending=None, changed_at=None)
    _save(path, seal)


# ---------------------------------------------------------------- one pass
def run_once(cb, now=None, budget_s=90):
    """cb is the window module (consequences_brain): its ledger reader/writer, runner names and ask folders."""
    now = time.time() if now is None else now
    folder = data_dir()
    lock = os.path.join(folder, "worker.lock")
    try:
        if time.time() - os.path.getmtime(lock) < 600:
            return None
    except OSError:
        pass
    open(lock, "w").close()
    try:
        ix = cb_evidence.Index(folder)
        ix.update(budget_s=budget_s)
        sessions = ix.sessions()
        rows = cb.read_ledger()
        cb_referee.true_times(rows)
        row_sessions = {}
        for sid, turns in sessions.items():
            for t in turns:
                mine = cb.canon_agent(cb_evidence.model_label(t.get("model")))
                for item in t.get("rows_written") or []:
                    k, who = (item if isinstance(item, list) else [item, ""])[:2]
                    if who and cb.canon_agent(who) == mine:   # a row it wrote about someone else is not its own
                        row_sessions.setdefault(k, sid)
        for r in rows:
            r["key"] = cb_evidence.row_key(r.get("runner"), r.get("pts"), r.get("event"))
        cfg = (getattr(cb, "CFG", {}) or {}).get("referee") or {}
        never_auto = list(cfg.get("never_auto") or [])
        state = _load(os.path.join(folder, "state.json"), {})
        hstate = state.get("hear_state") or {}

        def write(entries):
            if cfg.get("hear", True) and not getattr(cb, "DEMO", {}).get("on"):
                cb.append_ledger(entries)
        heard = hear(sessions, rows, cb.canon_agent, row_sessions, hstate, now, write)

        store = cb_learn.Store(folder)
        cases = cb_learn.examples_from(sessions)
        learn = state.get("learn") or {}
        if len(cases) != learn.get("cases") or now - (learn.get("at") or 0) > 6 * 3600:
            res = cb_learn.improve(store, cases)
            learn = {"cases": len(cases), "at": now, "last": res.get("text")}
        outcomes = []
        vlog = state.get("verdicts") or {}
        profile, pstatus = store.load()

        asks_out, pending = {}, []
        for where, fold in cb.ACTIVITY_DIRS.items():
            for k in cb_activity.read_asks(fold):
                key = "%s/%s" % (where, k.get("file"))
                if k.get("state") == "awarded" and key in vlog and k.get("points"):
                    outcomes.append((vlog[key]["v"], vlog[key]["p"], int(k["points"])))
                if k.get("kind") == "claim" or k.get("state") not in (None, "open"):
                    continue
                turn = cb_evidence.turn_for_ask(sessions, k)
                ev = cb_evidence.evidence_of(turn)
                if not ev:
                    continue
                lv = cb_learn.predict(profile, ev["features"])
                asks_out[key] = {"evidence": ev, "learned": lv, "version": profile.get("version", 0), "autonomy_ok": bool(profile.get("autonomy_ok")),
                                 "recommend_ok": recommend_ok(profile)}
                vlog[key] = {"v": profile.get("version", 0), "p": lv["points"]}
                pending.append({"key": key, "runner": k.get("agent", ""), "learned": lv, "session": ev["session"]})
        rolled = cb_learn.live_check(store, outcomes)
        if rolled:
            profile, pstatus = store.load()
        entries, left = auto_rows(pending, rows, cb.canon_agent, profile, never_auto, now)
        if entries and cfg.get("auto", True) and not getattr(cb, "DEMO", {}).get("on"):
            cb.append_ledger(entries)
        seal = integrity(folder, never_auto, now)
        m = profile.get("metrics") or {}
        out = {"at": now, "pass_secs": round(time.time() - now, 1), "row_sessions": row_sessions, "asks": asks_out,
               "hear": heard, "hear_state": hstate, "verdicts": dict(list(vlog.items())[-400:]),
               "learn": dict(learn, status=pstatus, version=profile.get("version", 0), metrics=m,
                             autonomy_ok=bool(profile.get("autonomy_ok")), notes=store.notes(6), cases_n=len(cases)),
               "delegation": delegation(rows, cb.canon_agent, now), "auto": {"written": [list(e) for e in entries], "left": left[-20:]},
               "integrity": seal, "never_auto": never_auto, "clock": cb_referee.clock_check(rows, now)}
        _save(os.path.join(folder, "state.json"), out)
        return out
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def read_state():
    return _load(os.path.join(data_dir(), "state.json"), {})


if __name__ == "__main__":
    import consequences_brain as CB
    if "--accept-seal" in sys.argv:
        accept_seal(data_dir(), ((CB.CFG or {}).get("referee") or {}).get("never_auto") or [])
    else:
        r = run_once(CB)
        if "--print" in sys.argv and r:
            print(json.dumps({k: r[k] for k in ("hear", "learn", "delegation", "integrity", "clock")}, indent=1, default=str)[:4000])
