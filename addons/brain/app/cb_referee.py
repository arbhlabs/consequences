"""Consequences Brain referee: a deterministic verdict on every open points ask. Rules only, no AI.

The referee reads what it is handed (the ask, the ledger rows, the gate decisions, and optionally the evidence of
this exact turn) and returns a verdict. It writes nothing and calls nothing: no file, network, process or model.
Every runner is judged by the same rules; no runner is named in this file.

Rules, first match decides (same runner only, inside the ask's window):
  1. a positive ledger row or an awarded gate decision      ->  0  already_paid
  2. a negative ledger row                                  ->  0  own_miss
  3. a blocked gate decision and the agent asked for > 0    -> -3  overclaim
  4. a gate dry-run pass or a waiting gate decision         -> its points  gate_proven
  E. evidence of this turn, judged confidently like past cases (learned, see cb_learn)  -> its points  evidence
  5. the agent asked for n > 0, nothing proves it           -> min(n, 3)  unproven (or unclear, with mixed evidence)
  6. the agent asked for n < 0                              ->  n  self_penalty
  7. nothing asked, nothing found                           ->  0  no_evidence (ambiguous / unclear when that applies)

Clocks: ledger rows can come from machines whose clocks differ. true_times() places each row on one time line using
the ledger's append order, and clock_check() reports a local clock that is behind. A row tied to a session (written
or heard there) only counts for that session's ask. When two asks of the same runner overlap in time, rows and gate
decisions not tied to a session are not counted for either: ambiguous, the owner decides.
"""
import re
import time

LEDGER_BEFORE, LEDGER_AFTER = 90, 120      # ledger window = [started - 90 s, ts + 120 s]
GATE_BEFORE, GATE_AFTER = 90, 1800         # gate window   = [started - 90 s, ts + 1800 s]
DEFAULT_TURN = 20 * 60                     # a turn with no recorded start is taken as 20 minutes long
UNPROVEN_CAP = 3
OVERCLAIM = -3
LIMIT = 50
TRACK_ROWS = 20                            # "recent" for the track-record note
PROOF = ("would_award", "would_wait", "waiting")


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _int(v):
    f = _num(v)
    return None if f is None else int(f)


def _clamp(n):
    return max(-LIMIT, min(LIMIT, int(n)))


def plain_name(label):
    """Fallback runner identity when the caller passes no canon function: the name inside brackets if there is
    one, without version numbers, lower case. "Tool (Name 1.2)", "Name 1.2" and "name" are one runner."""
    s = str(label or "").strip()
    m = re.search(r"\(([^)]*)\)", s)
    if m and m.group(1).strip():
        s = m.group(1)
    return " ".join(w for w in re.split(r"[\s/_-]+", s) if w and not re.search(r"\d", w)).lower()


def _keyer(canon):
    def key(label):
        try:
            got = (canon or plain_name)(label)
        except Exception:
            got = plain_name(label)
        return str(got or "").strip().lower()
    return key


def row_time(ts):
    """Start of the ledger row's minute (local time), or None when the row carries no time of day."""
    ts = str(ts or "")
    if not ts or ts.endswith(" 00:00"):
        return None
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M"))
    except (ValueError, OverflowError):
        return None


def true_times(rows, step=3600, slack=600):
    """Give each ledger row r["t"] (epoch or None). Rows are appended in real order, so a row stamped hours before the
    row above it on the same day came from a clock that was behind: shift it by the smallest whole number of hours
    that puts it back in order (clocks off by whole hours or zones). A row for an earlier day is a backdated entry
    and is left alone. Returns rows (each dict gets "t", shifted ones also "shifted")."""
    last, last_day = None, None
    for r in rows:
        t = row_time(r.get("ts"))
        day = str(r.get("ts") or "")[:10]
        if t is not None and last is not None and day == last_day and t < last - 2 * step:
            shift = -(-(last - slack - t) // step) * step      # ceil to whole hours
            if shift <= 14 * step:
                t += shift
                r["shifted"] = int(shift)
        r["t"] = t
        if t is not None:
            if last is None or t >= last:
                last, last_day = t, time.strftime("%Y-%m-%d", time.localtime(t)) if "shifted" in r else day
    return rows


def clock_check(rows, now):
    """{'behind': seconds, 'text'}: rows stamped well in the future mean this machine's clock is behind."""
    ahead = [t - now for t in (row_time(r.get("ts")) for r in rows[-200:]) if t is not None and t - now > 600]
    if not ahead:
        return {"behind": 0, "text": "Clock agrees with the ledger."}
    b = max(ahead)
    return {"behind": int(b), "text": "This PC clock looks about %.1f h behind the ledger; times will not match until it is fixed." % (b / 3600.0)}


def _verdict(points, verdict, why, checks):
    return {"points": _clamp(points), "verdict": verdict, "why": why[:160], "checks": checks}


def judge(ask, rows, gate, now, canon=None, evidence=None, peers=None):
    """Verdict for one open ask: {"points", "verdict", "why", "checks"}. Pure: reads its arguments, changes nothing.
    canon (optional) maps a runner label to its canonical name; rows are parse_scoreboard rows (optionally with "t"
    from true_times and "session" when tied to one), gate is the list of gate decisions with their current status.
    evidence (optional): {"evidence", "learned", "version"} for this exact turn. peers (optional): other open asks."""
    key = _keyer(canon)
    who = key(ask.get("agent"))
    end = _num(ask.get("ts"))
    end = float(now) if end is None else end
    start = _num(ask.get("started")) or _num(ask.get("since")) or end - DEFAULT_TURN
    asked = _int(ask.get("suggested"))
    sess = str(ask.get("session") or "")
    lo, hi = start - LEDGER_BEFORE, end + LEDGER_AFTER

    ambiguous = False
    for p in peers or []:
        if not isinstance(p, dict) or p is ask or not who or key(p.get("agent")) != who or str(p.get("session") or "") == sess:
            continue
        pe = _num(p.get("ts")) or 0.0
        ps = _num(p.get("started")) or _num(p.get("since")) or pe - DEFAULT_TURN
        if ps - LEDGER_BEFORE <= hi and pe + LEDGER_AFTER >= lo:
            ambiguous = True

    def tied(r):    # True: tied to this ask's session; False: tied to another one; None: not tied to any
        s = str(r.get("session") or "")
        return None if not s else bool(sess) and (s.startswith(sess) or sess.startswith(s))

    mine = [r for r in rows or [] if isinstance(r, dict) and who and key(r.get("agent") or r.get("runner")) == who
            and tied(r) is not False and not (ambiguous and tied(r) is None)]
    plus = minus = 0
    for r in mine:
        t, pts = (_num(r["t"]) if "t" in r else row_time(r.get("ts"))), _int(r.get("pts")) or 0
        if t is None or t + 59 < lo or t > hi:      # a row is stamped to the minute: any second of it may fit
            continue
        plus += pts > 0
        minus += pts < 0

    glo, ghi = start - GATE_BEFORE, end + GATE_AFTER
    seen, proof = {}, None
    for i, d in enumerate(gate or []):
        if not isinstance(d, dict) or not who or ambiguous or key(d.get("runner")) != who:
            continue
        t = _num(d.get("ts"))
        if t is None or not glo <= t <= ghi:
            continue
        status = str(d.get("status") or "")
        seen[status] = seen.get(status, 0) + 1
        if status in PROOF and (proof is None or (t, i) >= proof[:2]):
            proof = (t, i, _clamp(_int(d.get("points")) or 0), status)

    recent = mine[-TRACK_ROWS:]
    up = sum(1 for r in recent if (_int(r.get("pts")) or 0) > 0)
    down = sum(1 for r in recent if (_int(r.get("pts")) or 0) < 0)
    checks = {"at": float(now), "asked": asked, "ledger_window": [lo, hi], "gate_window": [glo, ghi],
              "ledger_plus": plus, "ledger_minus": minus, "gate": dict(sorted(seen.items())),
              "track_record": {"plus": up, "minus": down, "rows": len(recent),
                               "note": "last %d ledger rows: %d plus, %d minus (information only)" % (len(recent), up, down)}}
    ev = evidence.get("evidence") if isinstance(evidence, dict) else None
    lv = evidence.get("learned") if isinstance(evidence, dict) else None
    if ambiguous:
        checks["ambiguous"] = True
    if ev:
        checks["evidence"] = {"counts": ev.get("counts"), "handed_to_owner": ev.get("handed_to_owner"),
                              "rework_before": ev.get("rework_before"), "session": ev.get("session")}
    if lv:
        checks["learned"] = {"p_plus": lv.get("p_plus"), "confident": bool(lv.get("confident")), "points": lv.get("points"),
                             "drivers": lv.get("drivers"), "similar": lv.get("similar"), "version": evidence.get("version")}

    # kept short: the card shows the reason on one line next to the agent's own number
    if plus or seen.get("awarded"):
        return _verdict(0, "already_paid", "Already in the ledger or awarded by the gate.", checks)
    if minus:
        return _verdict(0, "own_miss", "A penalty landed during this work: making up for its own miss.", checks)
    if seen.get("blocked") and asked is not None and asked > 0:
        return _verdict(OVERCLAIM, "overclaim", "The gate ran the checks on this work and blocked it.", checks)
    if proof:
        return _verdict(proof[2], "gate_proven", "The gate ran the checks on this work: %+d." % proof[2], checks)
    trusted = bool(evidence.get("recommend_ok")) if isinstance(evidence, dict) else False
    if lv:
        checks["learned"]["trusted"] = trusted
    if lv and trusted and lv.get("confident") and _int(lv.get("points")):
        p = _clamp(_int(lv["points"]))
        drv = ", ".join(str(d[0]) for d in (lv.get("drivers") or [])[:2]) or "similar past cases"
        return _verdict(p, "evidence", "Judged like your past awards (%s): %+d." % (drv, p), checks)
    likely = round(100 * float((lv or {}).get("p_plus") or 0))
    if asked is not None and asked > 0:
        if lv:
            return _verdict(min(asked, UNPROVEN_CAP), "unclear", "Evidence is mixed (%d%% likely a plus), so at most %+d. Your call." % (likely, UNPROVEN_CAP), checks)
        return _verdict(min(asked, UNPROVEN_CAP), "unproven", "No gate proof, so at most %+d." % UNPROVEN_CAP, checks)
    if asked is not None and asked < 0:
        return _verdict(asked, "self_penalty", "Reports its own miss.", checks)
    if ambiguous:
        return _verdict(0, "ambiguous", "Two sessions of this runner overlapped; rows not tied to one are not counted.", checks)
    if lv:
        return _verdict(0, "unclear", "Evidence is mixed (%d%% likely a plus). Your call." % likely, checks)
    return _verdict(0, "no_evidence", "Nothing asked, nothing in the ledger or the gate.", checks)
