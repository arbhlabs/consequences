"""Built-in Claude Code session detector for the Consequences Brain (no hooks, no polling, no AI calls).

Every Claude Code session (CLI, desktop app, IDE) appends to its transcript ~/.claude/projects/<project>/<id>.jsonl as it
works. One thread blocks in ReadDirectoryChangesW on that folder tree; Windows wakes it with the names of the files that
changed. It reads only the newly appended bytes, follows each session's last assistant/user record and writes a beacon
only when a session's state changes:
  user prompt / tool result / assistant stop_reason "tool_use"  -> working (task = last prompt, model from the record)
  assistant stop_reason "end_turn"                               -> idle + one points ask per finished turn
                                                                    (with the "Suggested: +N (why)" line if present)
  "[Request interrupted by user"                                 -> idle
A session that stops writing mid-turn expires through the beacon TTL (crash, closed window).
"""
import datetime
import json
import os
import re
import threading
import time

import cb_activity

ROOT = os.environ.get("CB_CLAUDE_PROJECTS") or os.path.join(os.path.expanduser("~"), ".claude", "projects")
KEY = "Claude Code"
TTL = 15 * 60            # working beacon lifetime; refreshed while the transcript keeps growing
REFRESH = 120            # refresh at most every 2 min
FIRST_READ = 1 << 20
TYPE_RX = re.compile(r'"type":\s*"(?:assistant|user)"')     # first look at a transcript: its last 1 MB is plenty to find the state


def _model_name(mid):
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", mid or "")
    return "%s %s.%s" % (m.group(1).capitalize(), m.group(2), m.group(3)) if m else ""


def _when(iso):
    """Epoch seconds of a transcript record's ISO timestamp (0 if absent or unreadable)."""
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _prompt_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
            return None
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return None


class Session:
    __slots__ = ("path", "sid", "offset", "state", "model", "task", "cwd", "last_write", "turn", "ask_text", "started")

    def __init__(self, path):
        self.path, self.sid = path, os.path.splitext(os.path.basename(path))[0]
        self.offset, self.state, self.model, self.task, self.cwd = 0, "", "", "", ""
        self.last_write, self.turn, self.ask_text, self.started = 0.0, "", "", 0.0

    @property
    def agent(self):
        return "%s (%s)" % (KEY, self.model) if self.model else KEY

    def feed(self, text):
        """Update state from newly appended JSONL lines. Returns the 'finished turn' uuid if one just ended."""
        ended = None
        for line in text.splitlines():
            if not TYPE_RX.search(line):   # cheap pre-filter before json.loads
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("isSidechain"):
                continue
            msg = r.get("message") or {}
            self.cwd = r.get("cwd") or self.cwd
            if r.get("type") == "assistant":
                self.model = _model_name(msg.get("model")) or self.model
                sr = msg.get("stop_reason")
                if sr == "end_turn":
                    self.state = "idle"
                    parts = msg.get("content") if isinstance(msg.get("content"), list) else []
                    self.ask_text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
                    ended = r.get("uuid") or str(time.time())
                else:
                    self.state = "working"
            else:
                c = msg.get("content")
                t = _prompt_text(c)
                if t is not None and "[Request interrupted by user" in t:
                    self.state = "idle"
                    continue
                self.state = "working"
                if t:   # a real prompt (not a tool result): becomes the task, and the turn starts here
                    self.started = _when(r.get("timestamp")) or time.time()
                    t = cb_activity.clean_task(t)
                    where = cb_activity.project_name(self.cwd)
                    if t or where:
                        self.task = where + (": " if where and t else "") + t
        return ended


class ClaudeSessions(threading.Thread):
    def __init__(self, out=None, root=None):
        super().__init__(name="cb-claude-sessions", daemon=True)
        self.out, self.root = out or cb_activity.activity_dir(), root or ROOT
        self.sessions = {}
        self.wakeups = 0
        self.mode = "starting"

    # ------------------------------------------------------------ state -> beacons (only on change)
    def process(self, path):
        if not path.endswith(".jsonl") or os.sep + "subagents" + os.sep in path:
            return
        s = self.sessions.get(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if s is None:
            s = self.sessions[path] = Session(path)
            s.offset = max(0, size - FIRST_READ)
            first = True
        else:
            first = False
        if size < s.offset:          # rewritten / compacted
            s.offset = max(0, size - FIRST_READ)
        if size == s.offset:
            return
        with open(path, "rb") as f:
            f.seek(s.offset)
            data = f.read(size - s.offset)
        cut = data.rfind(b"\n") + 1  # only complete lines; the rest is read next time
        if cut == 0:
            return
        s.offset += cut
        before, label = s.state, s.agent
        ended = s.feed(data[:cut].decode("utf-8", "replace"))
        if first and s.state == "working" and time.time() - os.path.getmtime(path) > TTL:
            s.state = "idle"         # an old transcript that stopped mid-turn: not working now
        now = time.time()
        if s.state == "working" and (before != "working" or s.agent != label or now - s.last_write > REFRESH):
            cb_activity.write(s.agent, "working", s.task, s.sid[:12], TTL, folder=self.out, key=KEY)
            s.last_write = now
        elif s.state == "idle" and before != "idle":
            if not first or ended:
                cb_activity.write(s.agent, "idle", "", s.sid[:12], TTL, folder=self.out, key=KEY)
                s.last_write = now
        if ended and not first and ended != s.turn:
            s.turn = ended
            pts, why = cb_activity.suggestion(s.ask_text)
            cb_activity.ask_done(s.agent, s.task, s.sid[:12], folder=self.out, key=KEY, points=pts, why=why, turn=ended,
                                 started=s.started or None, project=cb_activity.project_name(s.cwd))
        elif ended:
            s.turn = ended           # history from before the window started: no ask

    def scan_recent(self, minutes=30):
        """At start: pick up sessions active in the last half hour (they may be mid-turn right now)."""
        cutoff = time.time() - minutes * 60
        try:
            projects = list(os.scandir(self.root))
        except OSError:
            return
        for p in projects:
            if not p.is_dir():
                continue
            try:
                for e in os.scandir(p.path):
                    if e.name.endswith(".jsonl") and e.stat().st_mtime > cutoff:
                        self.process(e.path)
            except OSError:
                pass

    # ------------------------------------------------------------ OS change notifications (blocking, 0 CPU idle)
    def run(self):
        try:
            self.scan_recent()
            self._run_native()
        except Exception:
            self.mode = "off"

    def _run_native(self):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        h = k32.CreateFileW(self.root, 0x0001, 0x7, None, 3, 0x02000000, None)  # LIST_DIRECTORY, share all, OPEN_EXISTING, BACKUP_SEMANTICS
        if not h or h == wintypes.HANDLE(-1).value:
            raise OSError("cannot watch %s" % self.root)
        buf = ctypes.create_string_buffer(64 * 1024)
        got = wintypes.DWORD()
        self.mode = "native"
        pending = set()
        while True:
            ok = k32.ReadDirectoryChangesW(h, buf, len(buf), True, 0x0001 | 0x0008 | 0x0010, ctypes.byref(got), None, None)
            if not ok:
                raise OSError("ReadDirectoryChangesW failed")
            self.wakeups += 1
            if got.value == 0:   # overflow: rescan what is recent
                self.scan_recent(10)
                continue
            off = 0
            while True:
                nxt, _act, ln = ctypes.cast(ctypes.byref(buf, off), ctypes.POINTER(wintypes.DWORD * 3)).contents
                name = ctypes.wstring_at(ctypes.addressof(buf) + off + 12, ln // 2)
                if name.endswith(".jsonl"):
                    pending.add(os.path.join(self.root, name))
                if not nxt:
                    break
                off += nxt
            time.sleep(0.3)      # coalesce a burst of appends into one read
            for p in list(pending):
                try:
                    self.process(p)
                except Exception:
                    pass
            pending.clear()
