#!/usr/bin/env python3
"""OpenCode -> Consequences activity beacons (runs next to an `opencode serve` instance, e.g. on a home server).

Push, not poll: holds ONE Server-Sent-Events connection to the local OpenCode server (/api/event) and sleeps in a socket
read until an event arrives. It turns session executions into beacons in a synced folder:
  session.execution.started   -> "<Model> (OpenCode, <machine>)" working, task = session title
  session.execution.succeeded -> idle + one open points ask for that session
  session.execution.failed / interrupted -> idle (no ask)
Automatic sessions are skipped: metadata.ephemeral, archived at creation, untitled, or a title matching $CB_SKIP_TITLES
(default "^health check"). Point CB_SHARED_ACTIVITY at a folder your PC syncs (Syncthing, OneDrive, a share) and set the
window's config "shared_activity" to the same folder on the PC.

Auth: OPENCODE_SERVER_PASSWORD comes from systemd's EnvironmentFile; it is never logged or written anywhere.
  python3 oc_beacon_bridge.py            # run (see opencode-beacon-bridge.service)
  python3 oc_beacon_bridge.py --probe 60 # print event types + data keys for 60 s (no content, no beacons)
"""
import base64
import http.client
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cb_activity  # noqa: E402  (same beacon format as the window's own writer)

HOST, PORT = os.environ.get("OC_HOST", "127.0.0.1"), int(os.environ.get("OC_PORT", "4097"))
OUT = os.environ.get("CB_SHARED_ACTIVITY") or os.path.join(os.path.expanduser("~"), ".consequences", "activity")
MACHINE = os.environ.get("CB_MACHINE") or __import__("socket").gethostname()  # shown in the agent label
TTL = 15 * 60            # working only while real progress keeps refreshing it; a hung run expires in 15 min
REFRESH = 120            # refresh a busy session's beacon at most every 2 min while its events keep coming
SKIP_TITLE = re.compile(os.environ.get("CB_SKIP_TITLES") or r"^(health check)", re.I)


def auth_header():
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    return {"Authorization": "Basic " + base64.b64encode(("opencode:" + pw).encode()).decode()} if pw else {}


def get_json(path):
    c = http.client.HTTPConnection(HOST, PORT, timeout=10)
    try:
        c.request("GET", path, headers=dict(auth_header(), Accept="application/json"))
        r = c.getresponse()
        return json.loads(r.read().decode("utf-8", "replace")) if r.status == 200 else None
    except Exception:
        return None
    finally:
        c.close()


def model_label(model):
    mid = (model or {}).get("id") or ""
    if not mid:
        return "OpenCode"
    words = [w for w in re.split(r"[-_]", mid) if w]
    nice = []
    for w in words:
        if w.lower() == "deepseek":
            nice.append("DeepSeek")
        elif re.match(r"^v?\d", w):
            nice.append(w.upper() if w.lower().startswith("v") else w)
        else:
            nice.append(w.capitalize())
    return " ".join(nice)


class Sessions:
    def __init__(self):
        self.info = {}       # sid -> {"agent", "title", "skip"}
        self.last = {}       # sid -> last beacon write (monotonic) while we show it as working
        self.text = {}       # sid -> last assistant text part (for the "Suggested: +N (why)" line)

    def learn(self, d):
        sid = d.get("sessionID") or d.get("id")
        if not sid:
            return None
        meta = d.get("metadata") or {}
        title = d.get("title") or ""
        tm = d.get("time") or {}
        skip = bool(meta.get("ephemeral") or SKIP_TITLE.match(title) or tm.get("archived"))
        prev = self.info.get(sid, {})
        self.info[sid] = {"agent": "%s (OpenCode, %s)" % (model_label(d.get("model")), MACHINE) if d.get("model") else prev.get("agent", "OpenCode (%s)" % MACHINE),
                          "title": title or prev.get("title", ""), "skip": skip or prev.get("skip", False)}
        return sid

    def get(self, sid):
        if sid not in self.info:  # started before we connected: ask the server once
            d = get_json("/api/session/%s" % sid)
            if isinstance(d, dict):
                self.learn(dict(d.get("data", d), sessionID=sid))
        return self.info.get(sid)


def sid_of(d):
    for k in ("sessionID", "sessionId", "session_id"):
        if d.get(k):
            return d[k]
    for k in ("session", "part", "info", "message"):
        v = d.get(k)
        if isinstance(v, dict):
            for kk in ("sessionID", "sessionId"):
                if v.get(kk):
                    return v[kk]
    return None


def _write(s, state, sid, task=""):
    cb_activity.write(s["agent"], state, task, sid[-12:], TTL, folder=OUT, key="opencode")


def _forget(sid, S):
    """An automated run: remove any beacon/ask it produced instead of leaving a false 'working'."""
    S.last.pop(sid, None)
    S.text.pop(sid, None)
    name = os.path.basename(cb_activity.beacon_path("", sid[-12:], OUT, key="opencode"))
    for n in (name, "ask--" + name):
        try:
            os.remove(os.path.join(OUT, n))
        except OSError:
            pass


STOP = ("session.execution.failed", "session.execution.interrupted", "session.deleted", "session.error", "session.step.failed")


def handle(ev, S):
    t, d = ev.get("type", ""), ev.get("data") or {}
    if t in ("session.created", "session.updated"):
        sid = S.learn(d)
        s = S.info.get(sid) if sid else None
        if s and s["skip"]:
            _forget(sid, S)                                   # title arrived late and says "automated": undo
        elif s and sid in S.last and s["title"]:
            _write(s, "working", sid, s["title"])             # title arrived after the run started
        return
    sid = sid_of(d)
    if not sid:
        return
    s = S.get(sid)
    status = ((d.get("status") or {}).get("type") if isinstance(d.get("status"), dict) else d.get("status")) or ""
    stop = t in STOP or (t == "session.status" and status == "retry")   # retry = rate limit / out of quota: not working
    if not s:
        return
    if s["skip"]:
        if sid in S.last:
            _forget(sid, S)
        return
    busy = t in ("session.execution.started", "session.step.started") or (t == "session.status" and status == "busy")
    done = t == "session.execution.succeeded" or t == "session.idle" or (t == "session.status" and status == "idle")
    part = d.get("part") if isinstance(d.get("part"), dict) else {}
    if t == "message.part.updated" and part.get("type") == "text" and sid in S.last:
        S.text[sid] = (part.get("text") or "")[-4000:]
    if stop and sid in S.last:                                # every stop signal clears "working"
        if os.path.exists(cb_activity.beacon_path("", sid[-12:], OUT, key="opencode")):
            _write(s, "idle", sid)
        S.last.pop(sid, None)
        S.text.pop(sid, None)
    elif busy and sid not in S.last:
        S.last[sid] = time.monotonic()
        if s["title"]:                                        # untitled = not yet provably human work: stay pending
            _write(s, "working", sid, s["title"])
    elif done and sid in S.last:                              # finished a run we saw start: idle + one points ask
        _write(s, "idle", sid)
        pts, why = cb_activity.suggestion(S.text.pop(sid, ""))
        cb_activity.ask_done(s["agent"], s["title"], sid[-12:], folder=OUT, key="opencode", points=pts, why=why)
        S.last.pop(sid, None)
    elif sid in S.last and t.startswith("message.") and time.monotonic() - S.last[sid] > REFRESH:
        _write(s, "working", sid)                             # real progress keeps a long run alive
        S.last[sid] = time.monotonic()


def stream(probe_until=None):
    c = http.client.HTTPConnection(HOST, PORT, timeout=300)   # server sends heartbeats; 300 s guards a dead socket
    c.request("GET", "/api/event", headers=dict(auth_header(), Accept="text/event-stream"))
    r = c.getresponse()
    if r.status != 200:
        raise ConnectionError("event stream HTTP %d" % r.status)
    S = Sessions()
    seed = get_json("/api/session")
    for d in (seed or {}).get("data", []) if isinstance(seed, dict) else []:
        S.learn(dict(d, sessionID=d.get("id")))
    buf = []
    while True:
        line = r.readline()
        if not line:
            raise ConnectionError("event stream closed")
        line = line.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("data:"):
            buf.append(line[5:].lstrip())
        elif line == "" and buf:
            try:
                ev = json.loads("\n".join(buf))
            except ValueError:
                ev = None
            buf = []
            if not isinstance(ev, dict):
                continue
            if probe_until is not None:
                print(ev.get("type"), sorted((ev.get("data") or {}).keys()), flush=True)
                if time.time() > probe_until:
                    return
                continue
            try:
                handle(ev, S)
            except OSError:
                pass


def main():
    if "--probe" in sys.argv:
        stream(time.time() + float(sys.argv[sys.argv.index("--probe") + 1]))
        return
    os.makedirs(OUT, exist_ok=True)
    cb_activity.prune(OUT)
    delay = 2
    while True:
        try:
            stream()
        except Exception as e:
            print("bridge: %s; reconnecting in %ds" % (type(e).__name__, delay), flush=True)
            time.sleep(delay)
            delay = min(60, delay * 2)
        else:
            delay = 2


if __name__ == "__main__":
    main()
