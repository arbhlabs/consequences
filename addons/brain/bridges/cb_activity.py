#!/usr/bin/env python3
"""Consequences activity beacons: who is working right now, and who finished and is waiting for points.
Standard library only, any OS.

Push, not poll: each agent/session writes ONE small JSON file into an activity folder (atomic temp + rename). The
Consequences Brain window wakes on the OS change notification for that folder and shows the agent pulsing. A beacon
expires on its own after `ttl` seconds, so a crashed agent never stays "working" forever.

Finishing work raises a points ask ("ask--*.json", one open ask per session, latest task). The window shows it until
The owner awards points or dismisses it, so finished work is never forgotten. Agents ask for a verdict; they never name or
claim an amount (see the consequences skill).

Folders: local = $CB_ACTIVITY, else %LOCALAPPDATA%/Consequences/activity (Windows) or ~/.consequences/activity.
Shared (other machines, e.g. a synced folder) = $CB_SHARED_ACTIVITY or the window's config "shared_activity".

CLI (what hooks and agents call):
  cb_activity.py working "Opus 5.5" --task "3D brain window"      # start / refresh (heartbeat)
  cb_activity.py done "Opus 5.5" --task "3D brain window"         # finished: idle + ask for points
  cb_activity.py idle "Opus 5.5"                                   # stopped without finishing (no ask)
  cb_activity.py hook working --agent "Claude Code"               # Claude Code hook: reads the hook JSON on stdin
  cb_activity.py hook done --agent "Claude Code"                  #   (Stop) -> idle + points ask
  cb_activity.py hook end --agent "Claude Code"                   #   (SessionEnd) -> idle, keeps an open ask
  cb_activity.py list
"""
import argparse
import json
import os
import re
import sys
import time

DEFAULT_TTL = 20 * 60  # a heartbeat older than this counts as idle
ASK_TTL = 3 * 24 * 3600  # an unanswered ask stays visible for 3 days


def activity_dir():
    d = os.environ.get("CB_ACTIVITY")
    if not d:
        base = os.environ.get("LOCALAPPDATA")
        d = os.path.join(base, "Consequences", "activity") if base else os.path.join(os.path.expanduser("~"), ".consequences", "activity")
    return d


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "agent"


def _atomic(path, rec):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, path)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def beacon_path(agent, session="", folder=None, key=None):
    folder = folder or activity_dir()
    return os.path.join(folder, _slug(key or agent) + (("--" + _slug(session)[:12]) if session else "") + ".json")


def write(agent, state="working", task="", session="", ttl=DEFAULT_TTL, folder=None, min_interval=0, key=None):
    """min_interval: skip the write when the same state was written less than that many seconds ago (heartbeats).
    An empty task keeps the previous task (so 'done' still knows what was finished)."""
    folder = folder or activity_dir()
    os.makedirs(folder, exist_ok=True)
    path = beacon_path(agent, session, folder, key)
    old = _load(path) or {}
    if min_interval and old.get("state") == state and time.time() - float(old.get("ts", 0)) < min_interval:
        return None
    rec = {"agent": agent[:80], "state": state, "task": (task or old.get("task") or "")[:160],
           "session": (session or "")[:40], "ts": round(time.time(), 3), "ttl": int(ttl)}
    _atomic(path, rec)
    return path


SUGGEST_RX = re.compile(r"Suggested:\s*([+\-−]?\s*\d{1,3})(?!\d)\s*(?:\(([^)\n]{0,160})\))?", re.I)


def suggestion(text):
    """(points, why) from the LAST 'Suggested: +N (why)' line in an agent's final message, else (None, '')."""
    m = None
    for m in SUGGEST_RX.finditer(text or ""):
        pass
    if not m:
        return None, ""
    n = int(re.sub(r"[\s+]", "", m.group(1)).replace("−", "-"))
    return (max(-500, min(500, n)) or None), (m.group(2) or "").strip()


def ask_done(agent, task="", session="", folder=None, key=None, points=None, why="", by=None, turn=None):
    """Raise (or refresh) the one open points ask for this session. points/why = the agent's suggested amount;
    by = who suggests (default: the agent itself; a promoted agent may suggest for another agent)."""
    folder = folder or activity_dir()
    os.makedirs(folder, exist_ok=True)
    by = (by or agent)[:80]
    base = os.path.basename(beacon_path(agent, session, folder, key))
    if by != agent:
        base = base[:-5] + "--by-" + _slug(by)[:30] + ".json"
    path = os.path.join(folder, "ask--" + base)
    old = _load(path) or {}
    if turn and old.get("turn") == turn:      # this finished turn already raised its ask
        return path
    reopen = old.get("state") in ("awarded", "dismissed")
    rec = {"agent": agent[:80], "by": by, "turn": turn or old.get("turn"), "task": (task or old.get("task") or "work finished")[:160], "session": (session or "")[:40],
           "ts": round(time.time(), 3), "state": "open",
           "turns": 1 if (reopen or not old) else int(old.get("turns", 1)) + 1,
           "suggested": int(points) if points not in (None, "") else (None if reopen else old.get("suggested")),
           "why": (why or ("" if reopen else old.get("why", "")))[:160]}
    _atomic(path, rec)
    return path


def claim(agent, points, why, folder=None):
    """Ask the owner to move points from the UNATTRIBUTED pool to `agent` (with evidence). One open claim per agent."""
    folder = folder or activity_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "ask--claim--" + _slug(agent)[:50] + ".json")
    rec = {"kind": "claim", "agent": agent[:80], "by": agent[:80], "task": "claim from the UNATTRIBUTED pool",
           "ts": round(time.time(), 3), "state": "open", "turns": 1, "suggested": int(points), "why": (why or "")[:300]}
    _atomic(path, rec)
    return path


def resolve_ask(folder, name, state, points=None):
    """Mark an ask awarded/dismissed (called by the window when the owner clicks)."""
    if not re.fullmatch(r"ask--[a-z0-9\-]+\.json", name or ""):
        raise ValueError("bad ask name")
    path = os.path.join(folder, name)
    rec = _load(path)
    if rec is None:
        raise FileNotFoundError(name)
    rec.update(state=state, resolved=round(time.time(), 3))
    if points is not None:
        rec["points"] = points
    _atomic(path, rec)
    return rec


def read(folder=None, now=None):
    """All beacons, newest first, each with 'active' (working and not expired), 'expires' and 'file'."""
    folder = folder or activity_dir()
    now = time.time() if now is None else now
    out = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return out
    for e in entries:
        if not e.name.endswith(".json") or e.name.startswith("ask--"):
            continue
        r = _load(e.path)
        if not isinstance(r, dict):
            continue
        try:
            ts, ttl = float(r.get("ts", 0)), float(r.get("ttl", DEFAULT_TTL))
        except (TypeError, ValueError):
            continue
        r.update(expires=ts + ttl, active=r.get("state") == "working" and now < ts + ttl, file=e.name)
        out.append(r)
    out.sort(key=lambda r: -float(r.get("ts", 0)))
    return out


def read_asks(folder=None, now=None):
    """Open points asks, newest first."""
    folder = folder or activity_dir()
    now = time.time() if now is None else now
    out = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return out
    for e in entries:
        if not (e.name.startswith("ask--") and e.name.endswith(".json")):
            continue
        r = _load(e.path)
        if isinstance(r, dict) and r.get("state") == "open" and now - float(r.get("ts", 0)) < ASK_TTL:
            r["file"] = e.name
            out.append(r)
    out.sort(key=lambda r: -float(r.get("ts", 0)))
    return out


def prune(folder=None, older_than=24 * 3600):
    """Delete old beacons and resolved/expired asks (keeps the folder tiny)."""
    folder = folder or activity_dir()
    now = time.time()
    for e in list(os.scandir(folder)) if os.path.isdir(folder) else []:
        if not e.name.endswith(".json"):
            continue
        age = now - e.stat().st_mtime
        if e.name.startswith("ask--"):
            r = _load(e.path) or {}
            if (r.get("state") != "open" and age > older_than) or age > ASK_TTL:
                _rm(e.path)
        elif age > older_than:
            _rm(e.path)


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _tail(path, n=65536):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _suggestion_from_transcript(path):
    """Suggested points from the last assistant text in a Claude Code transcript (JSONL)."""
    for line in reversed(_tail(path, 131072).splitlines()):
        if '"assistant"' not in line or "Suggested" not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") or {}
        parts = msg.get("content") if isinstance(msg.get("content"), list) else []
        text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
        pts, why = suggestion(text)
        if pts is not None:
            return pts, why
    return None, ""


def _model_from_transcript(path):
    """Model of the latest assistant message, read from the last 64 KB of the Claude Code transcript (no guessing)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            tail = f.read().decode("utf-8", "replace")
        ids = re.findall(r'"model":"(claude-[a-z0-9.\-]+)"', tail)
        if not ids:
            return ""
        m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", ids[-1])
        return ("%s %s.%s" % (m.group(1).capitalize(), m.group(2), m.group(3))) if m else ids[-1]
    except OSError:
        return ""


def _hook_agent(base, payload):
    """'Claude Code' + the model the session really used, e.g. 'Claude Code (Opus 5.5)'; base alone if unknown."""
    if "(" in base:
        return base
    model = _model_from_transcript(payload.get("transcript_path") or "") if payload.get("transcript_path") else ""
    return "%s (%s)" % (base, model) if model else base


def _hook_task(payload):
    cwd = payload.get("cwd") or ""
    prompt = re.sub(r"<[^>]{1,80}>[^<]{0,200}</[^>]{1,80}>|<[^>]{1,80}>", " ", str(payload.get("prompt") or ""))  # drop markup
    prompt = re.sub(r"\s+", " ", prompt).strip()
    where = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
    return (where + (": " if where and prompt else "") + prompt[:90]).strip() or "working"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["working", "done", "idle", "hook", "list", "claim"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--task", default="")
    ap.add_argument("--agent", default="")
    ap.add_argument("--session", default="")
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    ap.add_argument("--points", type=int, default=None, help="suggested amount for the finished work")
    ap.add_argument("--why", default="", help="one-line reason for the suggestion")
    ap.add_argument("--for", dest="for_agent", default="", help="(promoted agents) suggest points for another agent")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for r in read():
            print("%-8s %-34s %s" % ("WORKING" if r["active"] else r.get("state", "idle"), r.get("agent"), r.get("task", "")))
        for r in read_asks():
            sug = "" if r.get("suggested") is None else "  suggested %+d%s" % (r["suggested"], " by " + r["by"] if r.get("by") not in (None, r.get("agent")) else "")
            print("ASKS     %-34s %s (%d turn%s)%s" % (r.get("agent"), r.get("task", ""), r.get("turns", 1), "" if r.get("turns", 1) == 1 else "s", sug))
        return 0
    if a.cmd == "hook":  # Claude Code hook: never fail the session, never print
        try:
            state = a.rest[0] if a.rest else "working"
            payload = {}
            try:
                payload = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
            except Exception:
                payload = {}
            sess = str(payload.get("session_id", ""))[:12]
            key = a.agent or "Claude Code"
            agent = _hook_agent(key, payload)
            if state == "beat":  # keep a long turn alive without re-writing on every tool call
                write(agent, "working", "", sess, a.ttl, min_interval=120, key=key)
            elif state == "working":
                write(agent, "working", _hook_task(payload), sess, a.ttl, key=key)
            elif state == "done":   # turn finished: idle + one open points ask (with the agent's suggested amount)
                old = _load(beacon_path(agent, sess, key=key)) or {}
                write(agent, "idle", "", sess, a.ttl, key=key)
                pts, why = _suggestion_from_transcript(payload.get("transcript_path") or "") if payload.get("transcript_path") else (None, "")
                ask_done(agent, old.get("task", ""), sess, key=key, points=pts, why=why)
            elif state == "end":    # session closed: stop "working", keep any open ask
                old = _load(beacon_path(agent, sess, key=key)) or {}
                if old.get("state") == "working":
                    write(agent, "idle", "", sess, a.ttl, key=key)
            else:
                write(agent, "idle", "", sess, a.ttl, key=key)
            prune()
        except Exception:
            pass
        return 0
    agent = a.agent or (a.rest[0] if a.rest else "")
    if not agent:
        ap.error("agent name required")
    if a.cmd == "claim":     # ask to take points from the UNATTRIBUTED pool, with evidence in --why
        if not a.points or not a.why:
            ap.error("claim needs --points N and --why \"evidence\"")
        print(claim(agent, a.points, a.why))
        return 0
    if a.cmd == "done":
        if a.for_agent:   # a promoted agent suggesting points for someone else's work
            print(ask_done(a.for_agent, a.task, a.session, points=a.points, why=a.why, by=agent))
        else:
            print(write(agent, "idle", a.task, a.session, a.ttl))
            print(ask_done(agent, a.task, a.session, points=a.points, why=a.why))
    else:
        print(write(agent, a.cmd, a.task, a.session, a.ttl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
