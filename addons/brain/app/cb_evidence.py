"""Consequences Brain evidence: what a runner actually did in one turn, read from its own session transcript.

Local and read-only. No model calls, no network. An incremental index of Claude Code transcripts
(~/.claude/projects/**/*.jsonl, or CB_TRANSCRIPTS) splits every session into turns. A turn starts at a message the
owner typed and ends before the next one. For each turn it keeps counts the referee can check, never the raw text:
tests that passed or failed, tool errors, commits, screen grabs, device checks, edits, whether the owner was handed
steps to do himself, the runner's own suggested points, and ledger rows the runner wrote. The owner's next message
is kept only as its parsed points and tone, which become the label for this turn (what the owner thought of it).

Index files live in local app data (never in the repo): one small JSON per transcript, rebuilt from where it left off.
"""
import glob
import hashlib
import json
import os
import re
import time
import calendar

FEATURES = ("tests_pass", "tests_fail", "tool_errors", "commits", "screen_checks", "device_checks", "edits",
            "handed_to_owner", "rework_before", "asked_pos", "asked_big", "long_turn", "recent_plus", "recent_minus")
INDEX_VERSION = 6

# ---------------------------------------------------------------- owner's words
_SIGNED = re.compile(r"(?<![\w.\d])(plus|minus|\+|-|−)\s?(\d{1,3})(?![\d.,]\d)(?:\s*(points?|pts?)\b)?", re.I)
_GIVE = re.compile(r"\b(?:get|gets|give|giving|award|awarding|earns?|earned)\s+(?:you\s+|him\s+|them\s+)?(\d{1,3})\s*(?:points?|pts)\b", re.I)
_OFFER = re.compile(r"\b(if|once|when (?:i|it|you)|after (?:i|it)|will award|offer(?:ed|ing)?|promise[sd]?|up for grabs|could (?:get|earn)|can (?:get|earn)|bounty|"
                    r"split (?:between|among)|to be split|would (?:get|give|earn)|potential(?:ly)?|worth)\b", re.I)
_PRAISE = re.compile(r"\b(nice|great|perfect|beautiful(?:ly)?|awesome|works? (?:now|great|perfect|beautifully)|thank(?:s| you)|love it|good job|well done|flawless(?:ly)?)\b", re.I)
_ANGER = re.compile(r"\b(still (?:not|broken|doesn'?t|isn'?t)|again\b|not work(?:ing)?|doesn'?t work|didn'?t work|broken|wrong|"
                    r"ridiculous|wtf|fuck|dumbass|annoy|pissing|why (?:is|did|does|are)|not okay|crash(?:ed|es)?)\b", re.I)


def _jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def owner_points(text):
    """[(points, kind)] stated in one owner message; kind is 'award' or 'offer'. Decimals, dates, flags are ignored.
    Long pasted briefs and context dumps are not reactions: they carry no points."""
    out = []
    text = text or ""
    if len(text) > 1500 or re.match(r"\s*(CONTEXT\b|#|[A-Z][A-Z &\u2014-]{12,})", text) or re.search(r"^\s*MODEL:", text, re.M):
        return out
    tiny = len(text.strip()) <= 24
    asks_work = bool(re.search(r"\?|\b(please|can you|could you|i want you|go ahead and)\b", text, re.I))
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        future = bool(re.search(r"\b(i'?ll|i will|gonna|going to)\b", sentence, re.I))
        kind = "offer" if _OFFER.search(sentence) or (future and asks_work) else "award"
        short = len(sentence.strip()) <= 24
        for m in _SIGNED.finditer(sentence):
            word = m.group(1).lower()
            if not (m.group(3) or word in ("plus", "minus") or (short and tiny)):
                continue
            n = int(m.group(2))
            if n == 0 or n > 500:
                continue
            out.append((-n if word in ("minus", "-", "−") else n, kind))
        if not _SIGNED.search(sentence):
            for m in _GIVE.finditer(sentence):
                out.append((int(m.group(1)), kind))
    return out


def tone(text):
    return {"praise": len(_PRAISE.findall(text or "")), "anger": len(_ANGER.findall(text or ""))}


# ---------------------------------------------------------------- runner's work
_TEST_OK = [re.compile(p, re.I) for p in (r"\bRan (\d+) tests?\b[\s\S]{0,80}?\bOK\b", r"\b(\d+) passed\b", r"\b(\d+)/\1 (?:checks? )?pass",
                                          r"\bPASS(?:ED)?\b", r"acceptance: PASS", r"\btests? passed\b", r"\ball checks passed\b")]
_TEST_BAD = [re.compile(p, re.I) for p in (r"\bFAILED \((?:failures|errors)=\d+", r"\b(\d+) failed\b", r"\bFAIL\b", r"AssertionError",
                                           r"Traceback \(most recent call last\)", r"\bBUILD FAILED\b", r"\berror: ")]
_COMMIT = re.compile(r"\[[\w./-]+(?: \(root-commit\))? [0-9a-f]{7,40}\]")
_SCREEN = re.compile(r"screenshot|screen ?grab|screencap|zoom|ui_gate|capture", re.I)
_DEVICE = re.compile(r"\badb\b|\bssh\b|\bscp\b", re.I)
_TESTCMD = re.compile(r"unittest|pytest|gradle\w* test|npm (?:run )?test|ctest|cargo test|go test|selftest|acceptance|_gate\b|gate\.py|check", re.I)
_HANDED = re.compile(r"(?:^|\n)\s*(?:run this|please run|you(?:'ll)? need to|click (?:on )?|open .{0,30} and click|paste (?:this|the)|"
                     r"go to .{0,30}(?:settings|menu)|type the following)", re.I)
_SUGGEST = re.compile(r"Points for this\?\s*Suggested:\s*([+\-−]?\d{1,3})", re.I)
_LEDGER_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)\s*\|\s*([^|\n]+?)\s*\|\s*([+\-−]?\d+)\s*\|\s*([^|\n]{0,200})", re.M)
_SKIP_USER = ("<", "[Request interrupted", "Another Claude session sent a message", "Caveat:", "This session is being continued")


def _epoch(iso):
    try:
        return calendar.timegm(time.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S")) + (float("0." + str(iso)[20:23]) if len(str(iso)) > 20 and str(iso)[19] == "." else 0.0)
    except (ValueError, TypeError):
        return None


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return str(c or "")


def owner_message(e):
    """The owner's typed text, or None for tool results, hooks, injected notes and other sessions' messages."""
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain") or e.get("toolUseResult") is not None:
        return None
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
        return None
    t = _text_of(c).strip()
    if not t or t.startswith(_SKIP_USER):
        return None
    return t


def model_label(model_id):
    """claude-opus-5-5 -> 'Claude Opus 5.5' (a neutral display label; the app maps it to its runner name)."""
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d+))?", str(model_id or ""))
    if not m:
        return str(model_id or "")
    return "Claude %s %s" % (m.group(1).capitalize(), m.group(2) + ("." + m.group(3) if m.group(3) and len(m.group(3)) <= 2 else ""))


def _new_turn(e, text, prev):
    return {"uuid": e.get("uuid"), "start": _epoch(e.get("timestamp")), "end": _epoch(e.get("timestamp")),
            "owner": text[:240], "owner_pts": owner_points(text), "owner_tone": tone(text),
            "rework_before": int(bool(prev and tone(text)["anger"])), "cwd": e.get("cwd") or "",
            "models": {}, "ids": [], "n_tools": 0, "edits": 0, "tool_errors": 0, "tests_pass": 0, "tests_fail": 0,
            "test_cmds": 0, "commits": 0, "screen_checks": 0, "device_checks": 0, "handed_to_owner": 0,
            "suggested": None, "rows_written": [], "last_text": ""}


def _absorb(turn, e, pending):
    turn["end"] = _epoch(e.get("timestamp")) or turn["end"]
    msg = e.get("message") or {}
    if e.get("type") == "assistant":
        if msg.get("model") and not str(msg["model"]).startswith("<"):
            turn["models"][msg["model"]] = turn["models"].get(msg["model"], 0) + 1
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text"):
                turn["last_text"] = b["text"][-1500:]
                if e.get("uuid") and len(turn["ids"]) < 40:
                    turn["ids"].append(e["uuid"])
            elif b.get("type") == "tool_use":
                turn["n_tools"] += 1
                name, inp = str(b.get("name") or ""), b.get("input") or {}
                blob = json.dumps(inp)[:4000]
                if name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
                    turn["edits"] += 1
                if _SCREEN.search(name) or _SCREEN.search(blob):
                    turn["screen_checks"] += 1
                if _DEVICE.search(blob):
                    turn["device_checks"] += 1
                shell = name in ("Bash", "PowerShell")
                istest = bool(_TESTCMD.search(blob)) and shell
                turn["test_cmds"] += istest
                pending[b.get("id")] = (istest, shell and "git commit" in blob)
                for m in _LEDGER_ROW.finditer(str(inp.get("content") or inp.get("new_string") or inp.get("command") or "")):
                    if len(turn["rows_written"]) < 20:
                        turn["rows_written"].append([row_key(m.group(2), m.group(3), m.group(4)), m.group(2).strip()[:60]])
    elif e.get("type") == "user":
        c = msg.get("content")
        for b in c if isinstance(c, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                txt = _result_text(b)[-6000:]
                if b.get("is_error"):
                    turn["tool_errors"] += 1
                istest, iscommit = pending.pop(b.get("tool_use_id"), (False, False))
                if _COMMIT.search(txt) or (iscommit and not b.get("is_error") and not re.search(r"nothing to commit|^error|fatal:", txt, re.M)):
                    turn["commits"] += 1
                if istest:
                    bad = any(p.search(txt) for p in _TEST_BAD) or bool(b.get("is_error"))
                    ok = any(p.search(txt) for p in _TEST_OK)
                    if bad or ok:
                        turn["tests_fail" if bad else "tests_pass"] += 1


def row_key(runner, pts, event):
    """A stable key for one ledger row, made from its runner, points and first words (time is not used: clocks differ)."""
    p = str(pts).replace("−", "-").lstrip("+")
    words = " ".join(re.findall(r"[a-z0-9]+", str(event).lower())[:8])
    return hashlib.sha1(("%s|%s|%s" % (re.sub(r"\W+", "", str(runner).lower())[:24], p, words)).encode()).hexdigest()[:12]


def _finish(turn):
    if turn is None:
        return None
    t = dict(turn)
    t["model"] = max(t["models"], key=t["models"].get) if t["models"] else ""
    sug = _SUGGEST.findall(t.get("last_text") or "")
    t["suggested"] = int(sug[-1].replace("−", "-")) if sug else None
    t["handed_to_owner"] = int(bool(_HANDED.search(t.get("last_text") or "")))
    t["last_text"] = (t.get("last_text") or "")[-300:]
    return t


def features(t):
    """The numbers the scorer sees for one turn, each in [0, 1]. Same names for every runner and every install."""
    sug = t.get("suggested")
    return {"tests_pass": min(t.get("tests_pass", 0), 3) / 3.0, "tests_fail": min(t.get("tests_fail", 0), 3) / 3.0,
            "tool_errors": min(t.get("tool_errors", 0), 6) / 6.0, "commits": min(t.get("commits", 0), 2) / 2.0,
            "screen_checks": min(t.get("screen_checks", 0), 2) / 2.0, "device_checks": min(t.get("device_checks", 0), 2) / 2.0,
            "edits": min(t.get("edits", 0), 10) / 10.0, "handed_to_owner": float(t.get("handed_to_owner", 0)),
            "rework_before": float(t.get("rework_before", 0)), "asked_pos": float(bool(sug and sug > 0)),
            "asked_big": float(bool(sug and sug >= 20)),
            "long_turn": float(((t.get("end") or 0) - (t.get("start") or 0)) > 1800),
            "recent_plus": min(t.get("hist_up", 0), 2) / 2.0, "recent_minus": min(t.get("hist_down", 0), 2) / 2.0}


def parse_file(path, state=None):
    """Turns of one transcript, continuing from a saved state {offset, turns, cur, prev, pending}."""
    st = state or {"offset": 0, "turns": [], "cur": None, "pending": {}}
    size = os.path.getsize(path)
    if size < st["offset"]:
        st = {"offset": 0, "turns": [], "cur": None, "pending": {}}
    with open(path, "rb") as f:
        f.seek(st["offset"])
        data = f.read()
    end = data.rfind(b"\n") + 1
    cur, pending = st["cur"], st["pending"]
    for raw in data[:end].splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        text = owner_message(e)
        if text is not None:
            if cur is not None:
                st["turns"].append(_finish(cur))
            cur, pending = _new_turn(e, text, st["turns"][-1] if st["turns"] else None), {}
        elif cur is not None and e.get("type") in ("assistant", "user"):
            _absorb(cur, e, pending)
    st["offset"] += end
    st["cur"], st["pending"] = cur, pending
    return st


def label_turns(turns):
    """Each turn's label is the owner's NEXT message: awarded points (offers do not count) and tone."""
    out = []
    for i, t in enumerate(turns):
        # the owner's last three reactions in this session, all said before this turn's work (no peeking at its label)
        said = [p for u in turns[max(0, i - 2):i + 1] for p, k in (u.get("owner_pts") or []) if k == "award"]
        t = dict(t, hist_up=sum(1 for p in said if p > 0), hist_down=sum(1 for p in said if p < 0))
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        if nxt and nxt.get("start") and t.get("end") and nxt["start"] - t["end"] < 6 * 3600:
            awards = [p for p, k in nxt.get("owner_pts") or [] if k == "award"]
            lab = {"points": sum(awards) if awards else None, "n_awards": len(awards), "tone": nxt.get("owner_tone"),
                   "said": (nxt.get("owner") or "")[:160], "at": nxt["start"]}
        else:
            lab = None
        out.append(dict(t, label=lab))
    return out


class Index:
    """Incremental transcript index in <cache>/index/. update() reads only bytes added since the last run."""

    def __init__(self, cache, roots=None):
        self.cache = cache
        self.dir = os.path.join(cache, "index")
        self.roots = roots or [os.environ.get("CB_TRANSCRIPTS") or os.path.join(os.path.expanduser("~"), ".claude", "projects")]
        os.makedirs(self.dir, exist_ok=True)

    def _state_path(self, path):
        return os.path.join(self.dir, hashlib.sha1(os.path.abspath(path).lower().encode()).hexdigest()[:16] + ".json")

    def files(self):
        out = []
        for r in self.roots:
            out += glob.glob(os.path.join(r, "**", "*.jsonl"), recursive=True)
        return [f for f in out if os.sep + "subagents" + os.sep not in f]

    def update(self, budget_s=None, max_age_days=None):
        t0, done = time.time(), 0
        for f in sorted(self.files(), key=lambda p: -os.path.getmtime(p)):
            if budget_s and time.time() - t0 > budget_s:
                break
            if max_age_days and time.time() - os.path.getmtime(f) > max_age_days * 86400:
                continue
            sp = self._state_path(f)
            try:
                old = _jload(sp)
                if old.get("v") != INDEX_VERSION:
                    old = None
            except (OSError, ValueError):
                old = None
            size = os.path.getsize(f)
            if old and old.get("offset") == size:
                continue
            try:
                st = parse_file(f, old)
            except OSError:
                continue
            st.update(v=INDEX_VERSION, path=f, session=os.path.splitext(os.path.basename(f))[0])
            tmp = sp + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(st, fh)
            os.replace(tmp, sp)
            done += 1
        return done

    def sessions(self):
        """{session id: [labelled turns]} (the open, unfinished turn of each session is included last)."""
        out = {}
        for sp in glob.glob(os.path.join(self.dir, "*.json")):
            try:
                st = _jload(sp)
            except (OSError, ValueError):
                continue
            turns = list(st.get("turns") or [])
            if st.get("cur"):
                turns.append(_finish(st["cur"]))
            for t in turns:
                t["session"] = st.get("session", "")
            out[st.get("session", "")] = label_turns(turns)
        return out


def turn_for_ask(sessions, ask):
    """The exact turn an ask is about: its `turn` id is a message id inside that session's transcript.
    Falls back to the last turn that ended by the ask's time in the session whose id starts with ask['session']."""
    sid = str(ask.get("session") or "")
    if len(sid) < 8:
        return None
    cands = [s for s in sessions if s.startswith(sid)]
    if len(cands) != 1:
        return None
    turns = sessions[cands[0]]
    tid = ask.get("turn")
    if tid:
        for t in turns:
            if tid == t.get("uuid") or tid in (t.get("ids") or []):
                return t
    try:
        ts = float(ask.get("ts") or 0)
    except (TypeError, ValueError):
        return None
    fit = [t for t in turns if (t.get("end") or 0) <= ts + 120]
    return fit[-1] if fit else None


def evidence_of(turn):
    """The plain facts the referee shows for a turn (no transcript text beyond the owner's first words)."""
    if not turn:
        return None
    return {"session": turn.get("session", ""), "turn": turn.get("uuid"), "model": turn.get("model", ""),
            "start": turn.get("start"), "end": turn.get("end"), "features": features(turn),
            "counts": {k: turn.get(k, 0) for k in ("tests_pass", "tests_fail", "test_cmds", "tool_errors", "commits",
                                                   "screen_checks", "device_checks", "edits", "n_tools")},
            "handed_to_owner": turn.get("handed_to_owner", 0), "rework_before": turn.get("rework_before", 0),
            "suggested": turn.get("suggested"), "rows_written": turn.get("rows_written") or []}
