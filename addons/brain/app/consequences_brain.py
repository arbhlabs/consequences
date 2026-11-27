#!/usr/bin/env python3
"""Consequences Brain: a live 3D window for the Consequences skill's points ledger.

Settings live in config.json (%APPDATA%/Consequences/config.json, or $CB_CONFIG), never in the code:
  ledger           Scoreboard.md (markdown table) or ledger.jsonl (the points add-on); default: the add-on's ledger
  notes            optional folder with Decisions.md / STRIKES.md / Inbox.md / Jobs (default: the ledger's folder)
  skill            the consequences SKILL.md that holds the Promotion ranks table and rules (optional)
  shared_activity  an optional synced folder where other machines drop activity beacons
  runners          extra names to recognise: [{"name": "Riley", "match": "riley"}, ...]
  brand            optional text before CONSEQUENCES in the header

pywebview (Edge WebView2) window, run with pythonw (no console). The UI (ui/index.html)
pulls data through the pywebview js_api (Api.data). A Watcher thread blocks on Windows
change notifications (0 CPU idle), rebuilds on change and pushes window.__cbChanged(v).
Single instance (named mutex; a second launch focuses the window). Created hidden and
shown once the dark page and caption are ready (no white flash). Read-only on the vault
except Inbox.md (append, backup first). Quits fully on close. No autostart, no tray, no network.
"""
import os
import re
import sys
import json
import time
import shutil
import hashlib
import threading
import datetime

VERSION = "1.8.0"
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)          # bundled resources (ui/, icon) in the packaged app
_APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
_LOCAL = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
CONFIG_PATH = os.environ.get("CB_CONFIG") or next((p for p in (os.path.join(APP_DIR, "config.json"),   # portable / dev copy
                                                      os.path.join(_APPDATA, "Consequences", "config.json")) if os.path.isfile(p)),
                                                    os.path.join(_APPDATA, "Consequences", "config.json"))


def _load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            c = json.load(f)
            return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


CFG = _load_config()
if os.environ.get("CB_VAULT"):                       # tests / explicit override: a folder holding Scoreboard.md
    SCOREBOARD = os.path.join(os.environ["CB_VAULT"], "Scoreboard.md")
    VAULT = os.environ["CB_VAULT"]
else:
    _legacy = os.path.join(os.environ.get("SHIP_GATE_DATA_DIR") or os.path.join(_LOCAL, "ship-gate"), "ledger.jsonl")
    SCOREBOARD = CFG.get("ledger") or (_legacy if os.environ.get("SHIP_GATE_DATA_DIR") or os.path.isfile(_legacy)
                                       else os.path.join(_LOCAL, "Consequences", "ledger.jsonl"))
    VAULT = CFG.get("notes") or os.path.dirname(SCOREBOARD)
SKILLS_DIR = os.environ.get("CB_SKILLS") or os.path.join(os.path.expanduser("~"), ".claude", "skills")
BACKUP_DIR = os.environ.get("CB_BACKUPS") or os.path.join(_LOCAL, "Consequences", "backups")
DECISIONS = os.path.join(VAULT, "Decisions.md")
STRIKES = os.path.join(VAULT, "STRIKES.md")
INBOX = os.path.join(VAULT, "Inbox.md")
JOBS_DIR = os.path.join(VAULT, "Jobs")
CONSEQ_SKILL = next((p for p in ([] if os.environ.get("CB_SKILLS") else [CFG.get("skill")]) + [
    os.path.join(SKILLS_DIR, "consequences", "SKILL.md"), os.path.join(SKILLS_DIR, "consequences-points", "SKILL.md")]
    if p and os.path.isfile(p)), os.path.join(SKILLS_DIR, "consequences", "SKILL.md"))
BRAND = CFG.get("brand", "")
LEDGER_IS_JSONL = SCOREBOARD.lower().endswith(".jsonl")
sys.path.insert(0, APP_DIR)
import cb_activity  # noqa: E402  (who is working now: push beacons, see cb_activity.py)
import cb_sample    # noqa: E402  (fictional data for "Show sample data"; never written to disk)
import cb_gate      # noqa: E402  (gated point delegation: checks the owner defined, run by the gate itself)
import cb_referee   # noqa: E402  (deterministic verdicts on open asks: computed in memory, never written, never paid)
import cb_refwork   # noqa: E402  (the referee's slow part: evidence, hearing, learning; its own idle process, rules only, no AI)
DEMO = {"on": False, "extra": [], "asks": None}  # sample mode: this session only, the real ledger is untouched
ACTIVITY_DIR = cb_activity.activity_dir()
# beacons from other machines (e.g. an OpenCode server's bridge) arrive through a synced folder, if configured
SHARED_ACTIVITY_DIR = os.environ.get("CB_SHARED_ACTIVITY") or CFG.get("shared_activity") or ""
ACTIVITY_DIRS = {"local": ACTIVITY_DIR, **({"shared": SHARED_ACTIVITY_DIR} if SHARED_ACTIVITY_DIR else {})}
for _d in ACTIVITY_DIRS.values():
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

MAX_POINTS, MAX_DECISIONS, MAX_JOBS, MAX_NOTES, MAX_SKILLS, FILLER_SKILLS = 600, 60, 12, 15, 24, 5
TEXT_CAP = 4000

# ---------------------------------------------------------------- agents
# model families everyone has; your own agent names come from config "runners"
AGENT_PATTERNS = [
    ("Opus", r"\bopus\b"), ("Sonnet", r"\bsonnet\b"), ("Haiku", r"\bhaiku\b"), ("Fable", r"\bfable\b"),
    ("GPT", r"\b(?:chat)?gpt\b"), ("Codex", r"\bcodex\b"), ("Gemini", r"\bgemini\b"), ("DeepSeek", r"deepseek"),
    ("Grok", r"\bgrok\b(?! bot)"), ("Llama", r"\bllama\b"), ("Qwen", r"\bqwen\b"), ("Mistral", r"\bmistral\b"),
    ("Kimi", r"\bkimi\b"), ("Copilot", r"\bcopilot\b"), ("Cursor", r"\bcursor\b"),
] + [(r.get("name"), r.get("match") or re.escape(r.get("name", ""))) for r in CFG.get("runners", [])
     if isinstance(r, dict) and r.get("name")] + [(r, re.escape(r)) for r in CFG.get("runners", []) if isinstance(r, str)]
AGENT_RX = [(n, re.compile(p, re.I)) for n, p in AGENT_PATTERNS]


def canon_agent(s, strict_unknown=False):
    """Earliest-named known agent in s. Unknown runner -> cleaned label (unless strict)."""
    s = (s or "").strip()
    if not s:
        return None
    if re.match(r"unattributed", s, re.I):
        return "UNATTRIBUTED"
    best = None
    for name, rx in AGENT_RX:
        m = rx.search(s)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    if best:
        return best[1]
    if strict_unknown:
        return None
    clean = re.sub(r"\(.*?\)", "", s).strip(" -/")[:24] or "UNATTRIBUTED"
    return _LABELS.setdefault(clean.lower(), clean)   # "All agents" and "ALL agents" are one runner


DEFAULT_RANKS = [  # used when no skill with a "Promotion ranks" table is found
    ("Lead", 100, "May suggest points for other agents' finished work; the owner decides. Hardest briefs, most autonomy."),
    ("Senior", 50, "More autonomy on reversible work; may review others' work."),
    ("Trusted", 20, "Fewer confirmations on reversible work."),
    ("Good standing", 0, "Normal work."),
    ("Note", -10, "Fix and log the rule."),
    ("Warning", -30, "Lesson goes into the skill; next brief is smaller."),
    ("Probation", None, "Every change needs a verified dry run and owner-visible proof.")]
_fw_cache = {"sig": None, "fw": None}


def framework():
    """Ranks + standing rules, parsed live from the consequences skill (cached by mtime). Editing the skill updates
    the window in place: the watcher wakes on the skill folder, the next build carries the new framework."""
    sig = _sig(CONSEQ_SKILL)
    if _fw_cache["sig"] == sig and _fw_cache["fw"]:
        return _fw_cache["fw"]
    text = _read(CONSEQ_SKILL)
    ranks = []
    m = re.search(r"^## Promotion ranks[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if m:
        for row in m.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0] and not cells[0].startswith(("Rank", "---")):
                fm = re.search(r"([+\-\u2212]?\s*\d+)", cells[1])
                frm = None if re.search(r"below", cells[1], re.I) or not fm else int(re.sub(r"[\s+]", "", fm.group(1)).replace("\u2212", "-"))
                ranks.append((re.sub(r"\*", "", cells[0]), frm, cells[2]))
    if not ranks:
        ranks = list(DEFAULT_RANKS)
    ranks.sort(key=lambda r: -10**9 if r[1] is None else -r[1])
    ranks = [r for r in ranks if r[1] is not None] + [r for r in ranks if r[1] is None]
    rules = []
    for ln in text.splitlines():
        mm = re.match(r"^- (?:\*\*)?(Standing rule[^:]*|RULE[^:]*):\s*(.+)$", ln.strip())
        if mm:
            when = re.search(r"\d{4}-\d{2}-\d{2}", mm.group(1))
            rules.append({"date": when.group(0) if when else "", "text": mm.group(2).strip()[:900]})
    for mm in re.finditer(r"^## ([^\n]*\([^)]*\d{4}-\d{2}-\d{2}[^)]*\))\n([^\n#][^\n]*)", text, re.M):
        when = re.search(r"\d{4}-\d{2}-\d{2}", mm.group(1))
        rules.append({"date": when.group(0), "text": re.sub(r"\s*\([^)]*\d{4}-\d{2}-\d{2}[^)]*\)", "", mm.group(1)).strip() + ": " + mm.group(2).strip()[:700]})
    rules.sort(key=lambda r: r["date"], reverse=True)
    fw = {"ranks": ranks, "rules": rules[:40], "skill": os.path.basename(os.path.dirname(CONSEQ_SKILL)) + "/SKILL.md"}
    _fw_cache.update(sig=sig, fw=fw)
    return fw


_LABELS = {"all agents": "ALL agents", "unattributed": "UNATTRIBUTED"}


POOL_RX = re.compile(r"^(unattributed|all agents|everyone|team)$|\bsession\b", re.I)


def is_pool(label):
    """Ledger labels that are not a runner/model: the unattributed pool, company-wide penalties, unnamed sessions.
    They are counted honestly but never drawn as an agent or ranked."""
    return bool(POOL_RX.search(label or ""))


def ladder(total):
    for name, frm, _perks in framework()["ranks"]:
        if frm is None or total >= frm:
            return name
    return "Probation"


def can_suggest_for_others(rank):
    for name, _frm, perks in framework()["ranks"]:
        if name == rank:
            return bool(re.search(r"suggest points for other", perks, re.I))
    return False


# ---------------------------------------------------------------- helpers
def _read(path, limit=None, tail=False):
    try:
        with open(path, "rb") as f:
            if limit and tail:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - limit))
            data = f.read(limit) if (limit and not tail) else f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _sig(path):
    try:
        st = os.stat(path)
        # st_ino catches Syncthing's temp-file + rename writes that keep the remote mtime
        return (st.st_mtime_ns, st.st_size, st.st_ino)
    except Exception:
        return None


def _h(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:10]


def _norm_ts(ts):
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[ T~]+(\d{2}:\d{2}))?", ts or "")
    if not m:
        return ""
    return m.group(1) + " " + (m.group(2) or "00:00")


# ---------------------------------------------------------------- parsers
PTS_RX = re.compile(r"^[+\-\u2212]?\s*\d+")


def parse_scoreboard(text):
    rows, seen = [], {}
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        # some awards were appended as bullets: "- 2026-01-05 09:00 | Riley | +10 | ..."
        if re.match(r"^- \d{4}-\d{2}-\d{2}.*\|", line):
            line = "| " + line[2:]
        if not line.startswith("|") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4 or not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            continue
        ts, runner = parts[0], parts[1]
        rest = parts[2:]
        pts_cell = next((p for p in rest if PTS_RX.match(p)), None)
        if pts_cell is None:
            continue
        event = " | ".join(p for p in rest if p is not pts_cell and p)
        m = re.match(r"([+\-\u2212])?\s*(\d+)", pts_cell)
        pts = int(m.group(2)) * (-1 if m.group(1) in ("-", "\u2212") else 1)
        waived = "waived" in pts_cell.lower()
        base = _h(raw)
        seen[base] = seen.get(base, 0) + 1
        rows.append({
            "id": "p:" + base + ("" if seen[base] == 1 else "-%d" % seen[base]),
            "ts": _norm_ts(ts), "runner": runner, "agent": canon_agent(runner) or "UNATTRIBUTED",
            "pts": pts, "eff": 0 if waived else pts, "waived": waived,
            "event": event, "pts_cell": pts_cell, "line": i,
        })
    return rows


def parse_ledger_jsonl(text):
    """The points add-on ledger: one JSON event per line {timestamp, agent, task, points, reason, source, tags}."""
    rows, seen = [], {}
    for i, raw in enumerate(text.splitlines(), 1):
        try:
            e = json.loads(raw)
            pts = int(e["points"])
            when = datetime.datetime.fromisoformat(str(e["timestamp"]).replace("Z", "+00:00")).astimezone()
        except (ValueError, KeyError, TypeError):
            continue
        base = _h(raw)
        seen[base] = seen.get(base, 0) + 1
        event = ": ".join(x for x in (str(e.get("task") or "").strip(), str(e.get("reason") or "").strip()) if x)
        rows.append({"id": "p:" + base + ("" if seen[base] == 1 else "-%d" % seen[base]), "ts": when.strftime("%Y-%m-%d %H:%M"),
                     "runner": str(e.get("agent", "")), "agent": canon_agent(str(e.get("agent", ""))) or "UNATTRIBUTED",
                     "pts": pts, "eff": pts, "waived": False, "event": event, "pts_cell": "%+d" % pts, "line": i})
    return rows


def read_ledger():
    if DEMO["on"]:
        return parse_ledger_jsonl(cb_sample.ledger_text() + "".join(DEMO["extra"]))
    text = _read(SCOREBOARD)
    return parse_ledger_jsonl(text) if LEDGER_IS_JSONL else parse_scoreboard(text)


def _row_time(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M")) if ts and not ts.endswith(" 00:00") else None
    except ValueError:
        return None


def gate_decisions():
    try:
        return cb_gate.decisions()
    except Exception:
        return []


def referee_verdict(k, rows, gate, now, evidence=None, peers=None):
    """The referee's verdict on one raw open ask, or None (sample mode, pool claims, suggestions for someone else,
    or any referee error: the window must keep working without it). Nothing is written anywhere."""
    if DEMO["on"] or k.get("kind") == "claim" or (k.get("by") and k.get("by") != k.get("agent")):
        return None
    try:
        return cb_referee.judge(k, rows, gate, now, canon=canon_agent, evidence=evidence, peers=peers)
    except Exception:
        return None


def referee_state():
    """The worker's last pass (local app data), or {} in sample mode or before its first pass."""
    if DEMO["on"]:
        return {}
    try:
        return cb_refwork.read_state()
    except Exception:
        return {}


def tie_rows(rows, rstate):
    """Clock-robust times on every row, and the session a row belongs to when the worker saw it written or heard there."""
    cb_referee.true_times(rows)
    sessions = (rstate or {}).get("row_sessions") or {}
    for r in rows:
        m = re.search(r"\bs:([0-9a-f-]{8,})", r.get("event") or "")
        s = m.group(1) if m else sessions.get(cb_refwork.cb_evidence.row_key(r.get("runner"), r.get("pts"), r.get("event")))
        if s:
            r["session"] = s
    return rows


def settle_asks(rows, now=None):
    """Close asks the owner already answered in the ledger, e.g. an award given in chat that the agent logged itself.
    Deliberately narrow: the ledger row must be for the same runner, must not be one this window wrote, and must fall
    inside that ask's last finished turn; if two open asks of that runner fit, neither is closed."""
    now = time.time() if now is None else now
    open_asks = {}
    for folder in ACTIVITY_DIRS.values():
        for k in cb_activity.read_asks(folder):
            if k.get("kind") == "claim" or (k.get("by") and k.get("by") != k.get("agent")):
                continue
            try:
                end = float(k.get("ts", 0))
                start = float(k.get("started") or k.get("since") or end - 20 * 60)
            except (TypeError, ValueError):
                continue
            open_asks.setdefault(canon_agent(k.get("agent", "")), []).append((start, end, folder, k["file"], str(k.get("session") or "")))
    closed = 0
    for r in rows:
        t = r["t"] if r.get("t") is not None else _row_time(r["ts"])
        if t is None or now - t > cb_activity.ASK_TTL or re.search(r"awarded in the Consequences Brain|\(Consequences Brain\)", r["event"]) \
                or cb_gate.GATE_MARK.search(r["event"]):   # a gate award never closes (or doubles) the owner's open ask
            continue
        fit = [a for a in open_asks.get(r["agent"], []) if a[0] - 90 <= t + 59 and t <= a[1] + 120]
        if r.get("session"):   # a row tied to a session closes only that session's ask (parallel sessions never cross)
            fit = [a for a in fit if a[4] and (a[4].startswith(r["session"]) or r["session"].startswith(a[4]))]
        if len(fit) == 1:
            try:
                rec = cb_activity.resolve_ask(fit[0][2], fit[0][3], "awarded", r["pts"])
                rec["via"] = "ledger"
                cb_activity._atomic(os.path.join(fit[0][2], fit[0][3]), rec)
                open_asks[r["agent"]].remove(fit[0])
                closed += 1
            except (OSError, ValueError):
                pass
    return closed


_HOME_NAME = os.path.basename(os.path.expanduser("~").rstrip("\\/")).lower()


def ask_view(k):
    """What a card shows: the runner under the same name as the leaderboard, where it ran, and a clean headline.
    The agent's own one-line reason is the headline; the owner's raw prompt is never used as a title."""
    raw = k.get("agent", "")
    agent = canon_agent(raw) or "UNATTRIBUTED"
    task = cb_activity.clean_task(k.get("task", ""))
    project = k.get("project") or ""
    m = re.match(r"^([\w.\- ]{1,40}):\s*(.*)$", task)
    if m and (not project or m.group(1) == project):     # older beacons carried "folder: prompt" in one string
        project, task = project or m.group(1), m.group(2)
    if project.lower() == _HOME_NAME:
        project = ""
    if task.lower() in ("work finished", "working", ""):
        task = ""
    via = re.sub(r"\s+", " ", raw).strip()
    return {"agent": agent, "raw": raw, "via": "" if via.lower() == agent.lower() else via, "project": project, "task": task}


def append_ledger(entries):
    """entries: [(runner, points, task, reason)]. Markdown table rows or add-on jsonl events (backup first)."""
    bak = _backup(SCOREBOARD)
    os.makedirs(os.path.dirname(SCOREBOARD) or ".", exist_ok=True)
    if LEDGER_IS_JSONL:
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (time.time() % 1 * 1000)
        lines = [json.dumps({"timestamp": now, "agent": r, "task": t or "work", "points": int(p), "reason": why or t or "awarded",
                             "source": "owner", "tags": []}) for r, p, t, why in entries]
    else:
        stamp = time.strftime("%Y-%m-%d %H:%M")
        lines = ["| %s | %s | %+d | %s |" % (stamp, r, int(p), (t + (" - " + why if why and why != t else "")).strip()) for r, p, t, why in entries]
    nl_missing = False
    if os.path.exists(SCOREBOARD) and os.path.getsize(SCOREBOARD):
        with open(SCOREBOARD, "rb") as f:
            f.seek(-1, 2)
            nl_missing = f.read(1) != b"\n"
    with open(SCOREBOARD, "a", encoding="utf-8", newline="\n") as f:
        f.write(("\n" if nl_missing else "") + "\n".join(lines) + "\n")
    return bak, lines


def parse_bullets(text, tail_only=0):
    """Dated bullet entries ('- 2026-11-26 04:07 ...'), continuation lines folded in."""
    entries, cur = [], None
    for raw in text.splitlines():
        if re.match(r"^- \d{4}-\d{2}-\d{2}", raw):
            if cur:
                entries.append(cur)
            cur = raw[2:].rstrip()
        elif cur is not None and raw.strip() and not raw.startswith(("#", "- ", "|")):
            cur += "\n" + raw.rstrip()
        elif cur is not None and not raw.strip():
            entries.append(cur)
            cur = None
    if cur:
        entries.append(cur)
    return entries


def parse_decisions(text):
    # the tail read may begin mid-line: drop the first partial entry
    ents = parse_bullets(text)
    out, seen = [], {}
    for e in ents:
        m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[ T]+~?(\d{2}:\d{2}))?\s*[:|\-]?\s*(.*)", e, re.S)
        if not m:
            continue
        ts = _norm_ts(m.group(1) + " " + (m.group(2) or ""))
        body = m.group(3).strip()
        tm = re.match(r"\|?\s*([A-Za-z0-9][\w.\-]{2,40})", body)
        tag = tm.group(1).lower() if tm else ""
        base = _h(e[:200])
        seen[base] = seen.get(base, 0) + 1
        out.append({"id": "d:" + base + ("" if seen[base] == 1 else "-%d" % seen[base]),
                    "ts": ts, "tag": tag, "text": e[:TEXT_CAP],
                    "agent": canon_agent(e[:160], strict_unknown=True)})
    return out


def front_matter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for ln in m.group(1).splitlines():
        k = re.match(r"^([A-Za-z_]+):\s*(.*)$", ln)
        if k:
            fm[k.group(1)] = k.group(2).strip().strip('"')
    # folded description (>-)
    if fm.get("description") in (">-", ">", "|"):
        desc = re.search(r"description:\s*[>|]-?\s*\n((?:[ \t]+.*\n?)+)", m.group(1) + "\n")
        fm["description"] = " ".join(x.strip() for x in desc.group(1).splitlines()) if desc else ""
    return fm, m.group(2)


_skill_cache = {"t": 0, "items": []}


def load_skills():
    """name -> {path, desc, mtime}; cached 120 s."""
    if time.time() - _skill_cache["t"] < 120 and _skill_cache["items"]:
        return _skill_cache["items"]
    items = []
    try:
        for d in os.scandir(SKILLS_DIR):
            p = os.path.join(d.path, "SKILL.md")
            if d.is_dir() and os.path.isfile(p):
                head = _read(p, 6000)
                fm, body = front_matter(head)
                items.append({"name": d.name, "path": p, "desc": fm.get("description", ""),
                              "body": body, "mtime": os.path.getmtime(p)})
    except Exception:
        pass
    _skill_cache.update(t=time.time(), items=items)
    return items


# ---------------------------------------------------------------- experience (which tools and models have proven work)
MODEL_RX = re.compile(r"\b(fable|opus|sonnet|haiku|chatgpt|gpt|gemini|deepseek|grok(?! bot)|llama|qwen|mistral|kimi)\b(?! cli)"
                      r"(?:[ -]?v?(\d+(?:\.\d+)?[a-z]?)(?![\w.]))?", re.I)
_MODEL_NAMES = {"gpt": "GPT", "chatgpt": "GPT", "deepseek": "DeepSeek"}
PROGRAM_RX = [(n, re.compile(p, re.I)) for n, p in [
    ("Claude Code", r"claude[ -]code"), ("Codex", r"\bcodex\b"), ("Cursor", r"\bcursor\b"), ("OpenCode", r"open ?code"),
    ("Gemini CLI", r"gemini cli"), ("Antigravity", r"antigravity"), ("Copilot", r"\bcopilot\b"), ("Aider", r"\baider\b")]
    + [(n, re.escape(n)) for n in CFG.get("programs", []) if isinstance(n, str)]]


def model_of(runner):
    m = MODEL_RX.search(runner or "")
    if not m:
        return None
    name = _MODEL_NAMES.get(m.group(1).lower(), m.group(1).capitalize())
    return name + (" " + m.group(2) if m.group(2) else "")


def program_of(runner):
    hits = [(m.start(), n) for n, rx in PROGRAM_RX for m in [rx.search(runner or "")] if m]
    return min(hits)[1] if hits else None


def experience(rows):
    """Scored jobs per runner, model and program, from the ledger only. Proven XP = points gained x share of jobs that
    went well, so volume counts only when it is backed by good results. A model or program counts only when the ledger
    names it. Pool rows and reattributions (points moving, not work) are left out; waived rows count as a job only."""
    groups = {"agents": {}, "models": {}, "programs": {}}
    unnamed, total = {"models": 0, "programs": 0}, 0
    for r in rows:
        if is_pool(r["agent"]) or re.search(r"reattribution", r["runner"], re.I):
            continue
        total += 1
        model, program = model_of(r["runner"]), program_of(r["runner"])
        for kind, key in (("agents", r["agent"]), ("models", model), ("programs", program)):
            if not key:
                unnamed[kind] += 1
                continue
            g = groups[kind].setdefault(key, {"name": key, "jobs": 0, "good": 0, "bad": 0, "gained": 0, "lost": 0, "programs": {}})
            g["jobs"] += 1
            v = r["eff"]
            g["good"] += v > 0
            g["bad"] += v < 0
            g["gained"] += max(v, 0)
            g["lost"] += min(v, 0)
            if program:
                g["programs"][program] = g["programs"].get(program, 0) + 1
    out = {"jobs": total, "unnamed": unnamed}
    for kind, found in groups.items():
        for g in found.values():
            judged = g["good"] + g["bad"]
            g["rate"] = int(100 * g["good"] / judged + 0.5) if judged else None
            g["xp"] = int(g["gained"] * g["good"] / judged + 0.5) if judged else 0
            g["net"] = g["gained"] + g["lost"]
            g["top"] = max(g["programs"], key=g["programs"].get) if g["programs"] else None
            del g["programs"]
        out[kind] = sorted(found.values(), key=lambda g: (-g["xp"], -g["net"], -g["jobs"], g["name"]))
    return out


def lessons_for(name, text, limit=4):
    """Lesson lines that name this runner in the skill file: bullets that say "lesson", or sit under a heading about
    lessons or lost points. Dated lines come first, newest first."""
    who = re.compile(r"(?<![\w])%s(?![\w])" % re.escape(name), re.I)
    found, under = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            under = bool(re.search(r"lesson|lost points|never repeat|learned", s, re.I))
        elif (under or re.search(r"\blesson\b", s, re.I)) and re.match(r"(?:[-*]|\d+\.|\()", s) and who.search(s):
            found.append(re.sub(r"^(?:[-*]|\d+\.)\s*", "", s)[:400])
    found.sort(key=lambda s: (re.findall(r"20\d\d-\d\d-\d\d", s) or [""])[0], reverse=True)
    return found[:limit]


# ---------------------------------------------------------------- graph
def _gate_view():
    """The gate's mode, seal and recent decisions for the window (never in sample mode, never fatal)."""
    if DEMO["on"]:
        return None
    try:
        return cb_gate.window_view()
    except Exception as e:   # a broken gate file must not take the window down
        return {"configured": True, "mode": "dry-run", "seal": {"ok": False, "reason": "gate unreadable: %s" % type(e).__name__},
                "jobs": [], "items": [], "waiting": 0}


def stale_runners(rows, agents, now=None):
    """Runners that cannot work right now, folded to the bottom of the board: the owner's list in config "stale"
    (names, or {"runners": [...], "why": "..."}), plus anyone with no scored event for "stale_after_days" (default 7).
    A runner that is working right now is never stale."""
    if DEMO["on"]:
        return {}
    now = time.time() if now is None else now
    cfg = CFG.get("stale") or []
    names, why = (cfg.get("runners", []), cfg.get("why", "")) if isinstance(cfg, dict) else (cfg, "")
    out = {}
    for n in names if isinstance(names, list) else []:
        a = canon_agent(str(n))
        if a in agents:
            out[a] = why or "marked stale in settings"
    days = float(CFG.get("stale_after_days", 7) or 0)
    if days:
        last = {}
        for r in rows:
            t = _row_time(r["ts"]) or 0
            last[r["agent"]] = max(last.get(r["agent"], 0), t)
        for a in agents:
            if a not in out and not is_pool(a) and last.get(a) and now - last[a] > days * 86400:
                out[a] = "no points for %d days" % ((now - last[a]) // 86400)
    working = {canon_agent(b.get("agent", "")) for f in ACTIVITY_DIRS.values() for b in cb_activity.read(f) if b.get("active")}
    return {a: w for a, w in out.items() if a not in working}


def referee_view(st):
    """What the window shows about the referee itself: what it learned, what it heard, who should take the next job,
    whether it may pay by itself, and whether anything changed its rules. Plain numbers, no transcript text."""
    if not st:
        return {"ready": False, "text": "Rules only, no AI. Reading evidence for the first time." if not DEMO["on"] else "Sample data."}
    lr, hr = st.get("learn") or {}, st.get("hear") or {}
    m = lr.get("metrics") or {}
    return {"ready": True, "at": st.get("at"), "version": lr.get("version", 0), "cases": lr.get("cases_n", 0),
            "status": lr.get("status"), "autonomy": bool(lr.get("autonomy_ok")), "metrics": m,
            "notes": [n.get("text", "") for n in (lr.get("notes") or [])][-3:], "last": lr.get("last", ""),
            "heard": hr.get("logged") or [], "needs_you": hr.get("needs_you") or [], "gaps": hr.get("history_gaps", 0),
            "delegation": st.get("delegation") or [], "integrity": st.get("integrity") or {}, "clock": st.get("clock") or {},
            "auto": st.get("auto") or {}, "never_auto": st.get("never_auto") or []}


def build_graph():
    nodes, links, ids = [], [], {}

    def add(n):
        if n["id"] in ids:
            return ids[n["id"]]
        ids[n["id"]] = n
        nodes.append(n)
        return n

    def link(a, b, kind="ref", strength=1.0, length=70):
        if a in ids and b in ids and a != b:
            links.append({"s": a, "t": b, "kind": kind, "k": strength, "len": length})

    add({"id": "hub", "type": "hub", "label": "CONSEQUENCES", "ts": "",
         "text": "The Consequences brain: points, strikes, decisions, jobs and skills.\n"
                 "Standing rules live in the consequences skill; the ledger is Scoreboard.md.",
         "path": CONSEQ_SKILL})

    # --- points / strikes
    all_rows = read_ledger()
    rstate = referee_state()
    try:
        tie_rows(all_rows, rstate)
    except Exception:
        pass
    if not DEMO["on"]:
        try:
            settle_asks(all_rows)
        except Exception:
            pass
    rows = sorted(all_rows, key=lambda r: (r["ts"], r["line"]))[-MAX_POINTS:]
    totals, counts = {}, {}
    for r in all_rows:
        totals[r["agent"]] = totals.get(r["agent"], 0) + r["eff"]
        counts[r["agent"]] = counts.get(r["agent"], 0) + 1

    # --- strikes file (optional)
    strikes = []
    for e in parse_bullets(_read(STRIKES)) + [l.strip("- ").strip() for l in _read(STRIKES).splitlines()
                                              if l.strip().startswith("|") and re.search(r"\d{4}-\d{2}-\d{2}", l)]:
        strikes.append(e)

    dtxt = _read(DECISIONS, 260000, tail=True)
    decisions = parse_decisions(dtxt[_first_nl(dtxt):])
    decisions.sort(key=lambda d: d["ts"])
    decisions = decisions[-MAX_DECISIONS:]

    agents = set(totals)   # runners = who is on the ledger (plus whoever is working right now, below)
    # live activity beacons -> scoreboard runner names ("Claude Code (Opus 5.5)" -> "Opus")
    activity = []
    asks = []
    if DEMO["on"] and DEMO["asks"] is None:
        DEMO["asks"] = cb_sample.asks()
    ref_now, ref_gate = time.time(), ([] if DEMO["on"] else gate_decisions())
    ref_ev = rstate.get("asks") or {}
    raw_asks = [(where, k) for where, folder in ([("sample", None)] if DEMO["on"] else ACTIVITY_DIRS.items())
                for k in (DEMO["asks"] if DEMO["on"] else cb_activity.read_asks(folder))]
    ref_peers = [k for _, k in raw_asks if k.get("kind") != "claim"]
    for where, k in raw_asks:
        if k.get("kind") == "claim":   # take points from the UNATTRIBUTED pool
            pool = totals.get("UNATTRIBUTED", 0)
            want = int(k.get("suggested") or 0)
            asks.append({"kind": "claim", "agent": canon_agent(k.get("agent", "")) or "UNATTRIBUTED", "raw": k.get("agent", ""),
                         "task": k.get("task", ""), "ts": k.get("ts", 0), "turns": 1, "suggested": want if 0 < want <= pool else None,
                         "why": k.get("why", ""), "by": "", "pool": pool,
                         "note": "" if 0 < want <= pool else "asks for %+d but the pool holds %+d" % (want, pool),
                         "dir": where, "file": k.get("file")})
            continue
        by = k.get("by") or k.get("agent", "")
        peer = canon_agent(by) != canon_agent(k.get("agent", ""))
        sug, note = k.get("suggested"), ""
        if peer:   # suggesting for someone else is a privilege of rank, checked against the live score
            by_rank = ladder(totals.get(canon_agent(by) or "", 0))
            if not can_suggest_for_others(by_rank):
                note = "%s is %s; suggesting points for others unlocks at %s" % (canon_agent(by), by_rank, next(
                    (r[0] for r in framework()["ranks"] if re.search(r"suggest points for other", r[2], re.I)), "Lead"))
                sug = None
            else:
                note = "%s (%s) suggests" % (canon_agent(by), by_rank)
        asks.append({**ask_view(k), "ts": k.get("ts", 0), "turns": k.get("turns", 1),
                     "suggested": sug, "why": k.get("why", "") if sug is not None else "", "by": by if peer else "",
                     "quiet": bool(k.get("quiet")) and not peer,
                     "referee": None if peer else referee_verdict(k, all_rows, ref_gate, ref_now, ref_ev.get("%s/%s" % (where, k.get("file"))), ref_peers),
                     "note": note, "dir": where, "file": k.get("file")})
    asks.sort(key=lambda k: -float(k["ts"] or 0))
    for b in (cb_sample.activity() if DEMO["on"] else [x for f in ACTIVITY_DIRS.values() for x in cb_activity.read(f)]):  # noqa: E501 (several sessions per runner are counted in the UI)
        a = canon_agent(b.get("agent", "")) or "UNATTRIBUTED"
        v = ask_view(b)
        activity.append({"agent": a, "raw": b.get("agent", ""), "task": (v["project"] + (": " if v["project"] and v["task"] else "") + v["task"]),
                         "ts": b.get("ts", 0),
                         "expires": b.get("expires", 0), "active": bool(b.get("active"))})
        if b.get("active"):
            agents.add(a)
    for s in strikes:
        a = canon_agent(s, True)
        if a:
            agents.add(a)
    pools = {a: totals.get(a, 0) for a in sorted(agents) if is_pool(a)}
    lesson_text = "" if DEMO["on"] else _read(CONSEQ_SKILL)
    stale = stale_runners(rows, agents)
    for a in sorted(agents):
        if is_pool(a):
            continue
        t = totals.get(a, 0)
        add({"id": "a:" + a, "type": "agent", "label": a, "ts": "", "val": t,
             "text": "Agent / model: %s\nScore: %+d over %d event(s)\nStanding: %s" % (a, t, counts.get(a, 0), ladder(t)),
             "path": SCOREBOARD, "standing": ladder(t), "lessons": lessons_for(a, lesson_text), "stale": stale.get(a, "")})
        link("hub", "a:" + a, "hub", 0.45, 150)

    for r in rows:
        typ = "strike" if r["pts"] < 0 else "point"
        txt = "%s  %s\nRunner: %s\nPoints: %s%s\n\n%s\n\nSource: Scoreboard.md line %d" % (
            r["ts"], typ.upper(), r["runner"], r["pts_cell"], " (waived, counts 0)" if r["waived"] else "",
            r["event"], r["line"])
        add({"id": r["id"], "type": typ, "label": "%+d" % r["pts"], "ts": r["ts"], "val": r["pts"],
             "agent": r["agent"], "text": txt[:TEXT_CAP], "path": SCOREBOARD,
             "title": r["event"][:TEXT_CAP]})
        link("a:" + r["agent"], r["id"], "points", 1.0, 42)

    for i, s in enumerate(strikes[-20:]):
        sid = "s:" + _h(s)
        a = canon_agent(s, True) or "UNATTRIBUTED"
        if "a:" + a not in ids:
            add({"id": "a:" + a, "type": "agent", "label": a, "ts": "", "val": 0, "text": "Agent: " + a,
                 "path": STRIKES, "standing": ladder(0)})
            link("hub", "a:" + a, "hub", 0.45, 150)
        m = re.search(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?", s)
        add({"id": sid, "type": "strike", "label": "STRIKE", "ts": _norm_ts(m.group(0)) if m else "",
             "val": -1, "agent": a, "text": ("STRIKES.md\n\n" + s)[:TEXT_CAP], "path": STRIKES, "title": s[:140]})
        link("a:" + a, sid, "points", 1.0, 42)

    # --- jobs
    jobs = []
    try:
        for f in os.scandir(JOBS_DIR):
            if f.is_file() and f.name.endswith(".md") and ".bak" not in f.name and f.name != "Index.md":
                jobs.append((f.stat().st_mtime, f.path, f.name))
    except Exception:
        pass
    jobs.sort(reverse=True)
    jobinfo = []
    for mt, p, name in jobs[:MAX_JOBS]:
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name[:-3])
        body = _read(p, TEXT_CAP)
        jid = "j:" + name
        dup = sum(1 for _m, _p, nm in jobs[:MAX_JOBS] if re.sub(r"^\d{4}-\d{2}-\d{2}-", "", nm[:-3]) == slug) > 1
        add({"id": jid, "type": "job", "label": slug + (" " + name[5:10] if dup else ""), "ts": datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M"),
             "text": body, "path": p, "title": name})
        jobinfo.append((jid, slug, body))
        link("hub", jid, "hub", 0.1, 200)

    # --- skills referenced anywhere (+ consequences + newest few)
    skills = load_skills()
    names = [s["name"] for s in skills if ("-" in s["name"] or len(s["name"]) >= 10)]
    rx = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))) if names else None
    corpus = {}
    for r in rows:
        corpus[r["id"]] = r["event"]
    for d in decisions:
        corpus[d["id"]] = d["text"]
    for jid, slug, body in jobinfo:
        corpus[jid] = body
    refs, mentioned = {}, {}
    if rx:
        for nid, txt in corpus.items():
            for m in set(rx.findall(txt)):
                refs.setdefault(m, []).append(nid)
    by_name = {s["name"]: s for s in skills}
    chosen = ["consequences"] if "consequences" in by_name else []
    chosen += [n for n in sorted(refs, key=lambda n: -len(refs[n])) if n not in chosen]
    filler = 0
    for s in sorted(skills, key=lambda s: -s["mtime"]):
        if len(chosen) >= MAX_SKILLS or filler >= FILLER_SKILLS:
            break
        if s["name"] not in chosen:
            chosen.append(s["name"])
            filler += 1
    for n in chosen[:MAX_SKILLS]:
        s = by_name[n]
        add({"id": "k:" + n, "type": "skill", "label": n, "ts": "",
             "text": ("Skill: %s\n\n%s\n\n%s" % (n, s["desc"], s["body"].strip()))[:TEXT_CAP],
             "path": s["path"], "title": s["desc"][:140]})
        if n == "consequences":
            link("hub", "k:" + n, "hub", 0.5, 70)
        elif n not in refs:
            link("hub", "k:" + n, "hub", 0.05, 260)
        for nid in refs.get(n, [])[:6]:
            link("k:" + n, nid, "ref", 0.5, 80)

    # --- decisions
    last_by_tag = {}
    for d in decisions:
        body0 = re.sub(r"^\d{4}-\d{2}-\d{2}[ T~\d:]*[:|\-]?\s*\|?\s*", "", d["text"])
        label = d["tag"] if "-" in d["tag"] else (body0[:22].strip() or "decision")
        add({"id": d["id"], "type": "decision", "label": label[:22], "ts": d["ts"], "text": d["text"],
             "agent": d["agent"], "path": DECISIONS, "title": d["text"][:140]})
        linked = False
        if d["agent"]:
            link("a:" + d["agent"], d["id"], "ref", 0.7, 95)
            linked = True
        for jid, slug, _b in jobinfo:
            if d["tag"] == slug or (len(slug) > 5 and slug in d["text"]):
                link(jid, d["id"], "ref", 0.8, 70)
                linked = True
        if d["tag"] and "-" in d["tag"] and not canon_agent(d["tag"], True):
            if d["tag"] in last_by_tag:
                link(last_by_tag[d["tag"]], d["id"], "chain", 0.6, 50)
                linked = True
            last_by_tag[d["tag"]] = d["id"]
        if not linked:
            link("hub", d["id"], "hub", 0.1, 190)

    # --- notes (Inbox.md)
    for e in parse_bullets(_read(INBOX))[-MAX_NOTES:]:
        m = re.match(r"(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)", e)
        nid = "n:" + _h(e)
        add({"id": nid, "type": "note", "label": "note", "ts": _norm_ts(m.group(1)) if m else "",
             "text": ("Inbox note\n\n" + e)[:TEXT_CAP], "path": INBOX, "title": e[:140]})
        link("hub", nid, "hub", 0.3, 90)

    # drop dangling job/skill nodes? keep; compute degree-less guard
    # agents that shared one award (delegator splits / reattributions at the same minute) are linked in the 3D view
    shared = {}
    for r in all_rows:
        if re.search(r"split of|reattribution", r["runner"], re.I):
            shared.setdefault(r["ts"], set()).add(r["agent"])
    splits = sorted({(a, b) for g in shared.values() for a in g for b in g if a < b})
    return {"nodes": nodes, "links": links, "totals": totals, "event_total": len(all_rows),
            "agent_counts": counts, "splits": [["a:" + a, "a:" + b] for a, b in splits],
            "activity": activity, "asks": asks, "now": time.time(), "gate": _gate_view(), "referee": referee_view(rstate),
            "pools": pools, "experience": experience(rows), "net": sum(v for k, v in totals.items() if k != "ALL agents"), "brand": BRAND,
            "ledger_name": "sample data" if DEMO["on"] else os.path.basename(SCOREBOARD), "sample": DEMO["on"], "app_version": VERSION,
            "setup": {"empty": not all_rows and not asks and not activity, "ledger": SCOREBOARD, "cli": cli_prefix()},
            "framework": {"ranks": [{"name": n, "from": f, "perks": pk,
                                     "members": sorted((a for a in totals if not is_pool(a) and ladder(totals[a]) == n),
                                                       key=lambda a: -totals[a])}
                                    for n, f, pk in framework()["ranks"]],
                          "rules": framework()["rules"], "skill": framework()["skill"]},
            "counts": {t: sum(1 for n in nodes if n["type"] == t) for t in
                       ("agent", "skill", "decision", "point", "strike", "job", "note")}}


def cli_prefix():
    """How this copy of the app is called from a terminal (shown in the window's "how points get in" help)."""
    if getattr(sys, "frozen", False):
        return '& "%s"' % sys.executable
    return 'python "%s"' % os.path.abspath(__file__)


def _first_nl(s):
    i = s.find("\n")
    return 0 if i < 0 else i + 1


# ---------------------------------------------------------------- state / api
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.sig = None
        self.version = 0
        self.graph = {"nodes": [], "links": [], "totals": {}, "counts": {}}
        self.updated = 0.0

    def current_sig(self):
        try:
            jobs = tuple(sorted((e.name, e.stat().st_mtime_ns) for e in os.scandir(JOBS_DIR)
                                if e.name.endswith(".md") and ".bak" not in e.name))
        except Exception:
            jobs = ()
        try:
            act = tuple(sorted((e.name, e.stat().st_mtime_ns) for d in ACTIVITY_DIRS.values() if os.path.isdir(d)
                               for e in os.scandir(d) if e.name.endswith(".json")))
        except Exception:
            act = ()
        gate = tuple(_sig(os.path.join(cb_gate.gate_dir(), n)) for n in ("gate.jsonl", "checks.json", "policy.json", "seal.json"))
        ref = _sig(os.path.join(cb_refwork.data_dir(), "state.json"))
        return (_sig(SCOREBOARD), _sig(DECISIONS), _sig(STRIKES), _sig(INBOX), _sig(CONSEQ_SKILL), hash(jobs), hash(act), gate, ref, DEMO["on"])

    def refresh(self, force=False):
        s = self.current_sig()
        with self.lock:
            if not force and s == self.sig:
                return False
            try:
                g = build_graph()
            except Exception as e:  # keep the last good graph; surface the error in the UI
                self.graph["error"] = "%s: %s" % (type(e).__name__, e)
                self.sig = s
                self.version += 1
                return True
            self.graph = g
            self.sig = s
            self.version += 1
            self.updated = time.time()
            return True


STATE = State()


# ---------------------------------------------------------------- update in place
UI_DIR = os.environ.get("CB_UI_DIR") or os.path.join(APP_DIR, "ui")          # tests point these at temp copies
CODE_FILES = os.environ["CB_CODE_FILES"].split(os.pathsep) if os.environ.get("CB_CODE_FILES") else [
    os.path.join(APP_DIR, "consequences_brain.py"), os.path.join(APP_DIR, "cb_activity.py"), os.path.join(APP_DIR, "cb_gate.py"),
    os.path.join(APP_DIR, "cb_referee.py"), os.path.join(APP_DIR, "cb_refwork.py"), os.path.join(APP_DIR, "cb_learn.py"),
    os.path.join(APP_DIR, "cb_evidence.py")]
STATE_FILE = os.path.join(os.path.dirname(cb_activity.activity_dir()), "window.json")


def ui_sig():
    try:
        return tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size) for e in os.scandir(UI_DIR)
                            if e.is_file() and e.name.endswith((".html", ".js", ".css"))))
    except OSError:
        return ()


def code_sig():
    return tuple(_sig(f) for f in CODE_FILES)


REFEREE_EVERY = 120


def start_referee_worker():
    """Run cb_refwork.py every couple of minutes in its own process at idle priority, one at a time, no window.
    It is plain Python over local files (rules only, no AI); the window never waits for it."""
    if os.environ.get("CB_NO_REFEREE_WORKER") == "1" or getattr(sys, "frozen", False):
        return

    def loop():
        import subprocess
        exe = sys.executable
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            exe = w
        flags = (0x00000040 | 0x08000000) if os.name == "nt" else 0     # IDLE_PRIORITY_CLASS | CREATE_NO_WINDOW
        while True:
            if not DEMO["on"]:
                try:
                    subprocess.run([exe, os.path.join(APP_DIR, "cb_refwork.py")], cwd=APP_DIR, creationflags=flags,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
                except Exception:
                    pass
            time.sleep(REFEREE_EVERY)
    threading.Thread(target=loop, daemon=True, name="referee-worker").start()


# ---------------------------------------------------------------- live watcher
class Watcher(threading.Thread):
    """Blocks in WaitForMultipleObjects on OS change notifications (0 CPU while idle).

    Wakes only when a watched directory changes, waits for a quiet gap (debounce,
    capped by max_wait so bursts cannot delay past ~1 s), compares file signatures,
    rebuilds once and calls on_change(version). Falls back to a 1 s stat poll only
    if no directory can be watched. Counters are the idle proof: wakeups stays flat
    while nothing changes.
    """

    WAIT_OBJECT_0, WAIT_TIMEOUT, INFINITE = 0, 0x102, 0xFFFFFFFF
    FLAGS = 0x1 | 0x8 | 0x10  # FILE_NAME | SIZE | LAST_WRITE

    def __init__(self, state, on_change, dirs=None, debounce=0.15, max_wait=0.5, on_code=None):
        super().__init__(name="cb-watcher", daemon=True)
        self.state, self.on_change, self.on_code = state, on_change, on_code
        self._ui, self._code = ui_sig(), code_sig()
        self.dirs = dirs or [VAULT, JOBS_DIR, os.path.dirname(CONSEQ_SKILL), ACTIVITY_DIR, SHARED_ACTIVITY_DIR, cb_gate.gate_dir()] + (
            [UI_DIR] + sorted({os.path.dirname(f) for f in CODE_FILES}) if on_code else [])
        self.debounce, self.max_wait = debounce, max_wait
        self.wakeups = self.refreshes = 0
        self.mode = "starting"
        self._stop_evt = threading.Event()
        self._k32 = None
        self._stop_handle = None

    def stop(self):
        self._stop_evt.set()
        if self._k32 and self._stop_handle:
            self._k32.SetEvent(self._stop_handle)

    def _changed(self):
        if self.on_code:   # the app's own files: UI -> reload in place, backend -> restart in place
            u, c = ui_sig(), code_sig()
            if c != self._code:
                self._code, self._ui = c, u
                try:
                    self.on_code("backend")
                except Exception:
                    pass
            elif u != self._ui:
                self._ui = u
                try:
                    self.on_code("ui")
                except Exception:
                    pass
        if self.state.refresh():
            self.refreshes += 1
            try:
                self.on_change(self.state.version)
            except Exception:
                pass

    def run(self):
        try:
            self._run_native()
        except Exception:
            self._run_poll()

    def _run_poll(self):
        self.mode = "poll"
        while not self._stop_evt.wait(1.0):
            self._changed()

    def _run_native(self):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        k32.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        k32.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
        k32.CreateEventW.restype = wintypes.HANDLE
        k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k32.SetEvent.argtypes = [wintypes.HANDLE]
        k32.WaitForMultipleObjects.restype = wintypes.DWORD
        k32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
        invalid = wintypes.HANDLE(-1).value
        self._k32 = k32
        self._stop_handle = k32.CreateEventW(None, True, False, None)
        if self._stop_evt.is_set():
            return
        handles = [self._stop_handle]
        for d in dict.fromkeys(os.path.normcase(os.path.abspath(x)) for x in self.dirs):
            if os.path.isdir(d):
                h = k32.FindFirstChangeNotificationW(d, False, self.FLAGS)
                if h and h != invalid:
                    handles.append(h)
        if len(handles) == 1:
            raise OSError("no watchable directory")
        self.mode = "native:%d" % (len(handles) - 1)
        arr = (wintypes.HANDLE * len(handles))(*handles)
        n = len(handles)
        self._changed()  # catch anything written between the first build and arming
        def rearm(i):
            # a failed re-arm (e.g. watched folder replaced) would leave the handle signalled and spin:
            # raise so run() drops to the 1 s stat poll instead
            if not k32.FindNextChangeNotification(handles[i]):
                raise OSError("re-arm failed")
            self.wakeups += 1

        while True:
            r = k32.WaitForMultipleObjects(n, arr, False, self.INFINITE)
            if r == self.WAIT_OBJECT_0:
                return
            if r >= n:  # WAIT_FAILED / abandoned
                raise OSError("wait failed: %#x" % r)
            rearm(r)
            t0 = time.monotonic()
            while True:  # trailing debounce, capped
                left = self.max_wait - (time.monotonic() - t0)
                if left <= 0:
                    break
                r = k32.WaitForMultipleObjects(n, arr, False, int(min(self.debounce, left) * 1000))
                if r == self.WAIT_TIMEOUT:
                    break
                if r == self.WAIT_OBJECT_0:
                    return
                if r >= n:
                    raise OSError("wait failed: %#x" % r)
                rearm(r)
            self._changed()


# ---------------------------------------------------------------- single instance + window chrome
MUTEX_NAME = os.environ.get("CB_MUTEX", "Local\\Consequences.Brain")  # tests use their own name
WINDOW_TITLE = "Consequences Brain"
ICON_PATH = os.path.join(RES_DIR, "consequences.ico")
_MUTEX = None


def acquire_single_instance(name=MUTEX_NAME):
    """True if this process is the only instance (keeps the mutex for the process lifetime)."""
    global _MUTEX
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, False, name)
    if not h:
        return True  # cannot tell: never block the launch
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        k32.CloseHandle(ctypes.c_void_p(h))
        return False
    _MUTEX = h
    return True


def find_app_window(pid=None, visible_only=False):
    """HWND of our pywebview (WinForms) window, optionally owned by pid."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        if buf.value != WINDOW_TITLE:
            return True
        u.GetClassNameW(hwnd, buf, 256)
        if not buf.value.startswith("WindowsForms"):
            return True
        if visible_only and not u.IsWindowVisible(hwnd):
            return True
        if pid is not None:
            p = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value != pid:
                return True
        found.append(hwnd)
        return False

    u.EnumWindows(cb, 0)
    return found[0] if found else None


def focus_existing():
    import ctypes
    u = ctypes.windll.user32
    hwnd = find_app_window(visible_only=True)
    if not hwnd:
        return False
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    u.SetForegroundWindow(hwnd)
    return True


def style_window(hwnd):
    """Dark caption matching the page, plus the app icon (done while still hidden: no white flash)."""
    import ctypes
    from ctypes import wintypes
    if not hwnd:
        return False
    dwm = ctypes.windll.dwmapi
    for attr, val in ((20, 1), (35, 0x001D1209), (36, 0x00FFF6D8)):  # dark mode, caption #09121d (scene top), text #d8f6ff
        v = ctypes.c_int(val)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
    if os.path.isfile(ICON_PATH):
        u = ctypes.windll.user32
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        for which, metric in ((0, 49), (1, 11)):  # ICON_SMALL/SM_CXSMICON, ICON_BIG/SM_CXICON
            size = u.GetSystemMetrics(metric)
            hicon = u.LoadImageW(None, ICON_PATH, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if hicon:
                u.SendMessageW(wintypes.HWND(hwnd), 0x80, which, hicon)  # WM_SETICON
    return True


def _inside(path, roots):
    p = os.path.normcase(os.path.abspath(path))
    return any(p.startswith(os.path.normcase(os.path.abspath(r)) + os.sep) or p == os.path.normcase(os.path.abspath(r))
               for r in roots)


def _backup(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dst = os.path.join(BACKUP_DIR, os.path.basename(path) + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, dst)
    return dst


SEARCH_SKIP = (".bak", "sync-conflict", "\\.backups\\", "\\backup\\", "_backups", "\\.obsidian\\", "\\.git\\", "\\.trash\\", ".stversions", ".stfolder")
PRIORITY = {"Decisions.md": 3, "Scoreboard.md": 3, "Inbox.md": 2}


def search_vault(q, limit=8):
    terms = [t for t in re.findall(r"[\w.\-+]+", q.lower()) if len(t) >= 2]
    stop = {"the", "and", "for", "what", "who", "how", "did", "does", "was", "are", "is", "of", "to", "in", "a", "an", "on", "my", "me", "it", "about"}
    terms = [t for t in terms if t not in stop] or terms
    if not terms:
        return []
    hits = []
    files = []
    for root, dirs, fs in os.walk(VAULT):
        low = (root + os.sep).lower()
        if any(s in low for s in SEARCH_SKIP):
            dirs[:] = []
            continue
        for f in fs:
            if f.endswith(".md") and not any(s in f.lower() for s in (".bak", "sync-conflict")):
                files.append(os.path.join(root, f))
    if os.path.isfile(CONSEQ_SKILL):
        files.append(CONSEQ_SKILL)
    for p in files:
        try:
            txt = _read(p, 900000)
        except Exception:
            continue
        low = txt.lower()
        if not any(t in low for t in terms):
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            l = line.lower()
            n = sum(1 for t in terms if t in l)
            if n:
                score = n * 10 + PRIORITY.get(os.path.basename(p), 0)
                if n == len(terms):
                    score += 15
                hits.append((score, p, i, line.strip()))
    hits.sort(key=lambda h: (-h[0], h[1]))
    out, per_file = [], {}
    for score, p, i, line in hits:
        if per_file.get(p, 0) >= 2:
            continue
        per_file[p] = per_file.get(p, 0) + 1
        k = min((line.lower().find(t) for t in terms if t in line.lower()), default=0)
        a = max(0, k - 80)
        snip = ("…" if a else "") + line[a:a + 260] + ("…" if len(line) > a + 260 else "")
        out.append({"rel": os.path.relpath(p, VAULT) if _inside(p, [VAULT]) else p, "path": p,
                    "line": i, "text": snip, "score": score})
        if len(out) >= limit:
            break
    return out


class Api:
    """Exposed to the page as window.pywebview.api.*"""

    def poll(self):
        STATE.refresh()
        return {"version": STATE.version, "updated": STATE.updated}

    def data(self):
        STATE.refresh()
        g = dict(STATE.graph)
        # ship only what the window draws (agents + scored events); decisions/jobs/skills stay server-side for Ask
        g["nodes"] = [n for n in g.get("nodes", []) if n.get("type") in ("hub", "agent", "point", "strike")]
        g.pop("links", None)
        g["version"] = STATE.version
        g["updated"] = STATE.updated
        return g

    def stats(self):
        """Idle proof: watcher wakeups/refreshes only move when watched files change."""
        w = WATCHER
        sw = SESSIONS
        return {"version": STATE.version, "mode": w.mode if w else "off",
                "sessions_mode": sw.mode if sw else "off", "sessions_wakeups": sw.wakeups if sw else 0,
                "wakeups": w.wakeups if w else 0, "refreshes": w.refreshes if w else 0}

    def open_path(self, path, dry=False):
        roots = [VAULT, SKILLS_DIR]
        if not path or not _inside(path, roots) or not os.path.exists(path):
            return {"ok": False, "error": "not an allowed vault/skill file"}
        target = path
        if _inside(path, [VAULT]) and os.environ.get("CB_NO_OBSIDIAN") != "1":
            try:
                import winreg
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "obsidian"))
                from urllib.parse import quote
                rel = os.path.relpath(path, VAULT).replace("\\", "/")
                target = "obsidian://open?vault=%s&file=%s" % (quote(os.path.basename(VAULT)), quote(rel))
            except Exception:
                target = path
        if dry:
            return {"ok": True, "target": target}
        try:
            os.startfile(target)
            return {"ok": True, "target": target}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ask(self, q):
        q = (q or "").strip()[:300]
        if not q:
            return {"answer": "Type a question.", "results": [], "node_ids": []}
        res = search_vault(q)
        terms = [t for t in re.findall(r"[\w.\-+]+", q.lower()) if len(t) >= 2]
        ids = []
        for n in STATE.graph.get("nodes", []):
            tx = (n.get("text", "") + " " + n.get("label", "")).lower()
            if terms and all(t in tx for t in terms):
                ids.append(n["id"])
        files = len({r["path"] for r in res})
        ans = ("%d best match(es) across %d file(s); %d node(s) highlighted in the graph." % (len(res), files, len(ids))
               if res else "Nothing in the vault matches that. Try fewer or different words.")
        return {"answer": ans, "results": res, "node_ids": ids[:60]}

    def referee_accept_seal(self):
        """The owner accepts a change to the referee's code, caps or never-auto list (shown until he does)."""
        try:
            cb_refwork.accept_seal(cb_refwork.data_dir(), (CFG.get("referee") or {}).get("never_auto") or [])
            STATE.refresh(force=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def referee_revert(self, row_id):
        """One-click undo of an automatic [referee] row: appends an equal and opposite row (append-only ledger)."""
        row = next((r for r in read_ledger() if r.get("id") == row_id and cb_refwork.AUTO_MARK in (r.get("event") or "")), None)
        if not row or any(cb_refwork.REVERT_MARK + " " + row_id in (r.get("event") or "") for r in read_ledger()):
            return {"ok": False, "error": "not an automatic referee row, or already reverted"}
        append_ledger([cb_refwork.revert_entry(row)])
        STATE.refresh(force=True)
        return {"ok": True}

    def award(self, where, name, points):
        """The owner's click on a points ask: append one row to Scoreboard.md (backup first) and close the ask."""
        try:
            pts = int(points)
            if not pts or abs(pts) > 500:
                raise ValueError("points out of range")
            if where == "sample":          # sample mode: show what a click does, write nothing
                k = next((x for x in (DEMO["asks"] or []) if x.get("file") == name), None)
                if not DEMO["on"] or not k:
                    return {"ok": False, "error": "that ask is already closed"}
                DEMO["asks"].remove(k)
                DEMO["extra"].append(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "agent": k["agent"],
                                                 "task": k.get("task", "work"), "points": pts, "reason": k.get("why", ""), "source": "sample", "tags": []}) + "\n")
                STATE.refresh(force=True)
                return {"ok": True, "row": "sample only: nothing was written", "backup": None}
            folder = ACTIVITY_DIRS[where]
            ask = cb_activity._load(os.path.join(folder, os.path.basename(name or "")))
            if not ask or ask.get("state") != "open":
                return {"ok": False, "error": "that ask is already closed"}
            runner = re.sub(r"[|\r\n]+", " ", ask.get("agent") or "UNATTRIBUTED").strip()
            v = ask_view(ask)                  # the ledger gets the agent's own reason, not the owner's raw prompt
            what = (ask.get("why") or "").strip() or v["task"] or "work finished"
            task = re.sub(r"[|\r\n]+", " / ", (v["project"] + ": " if v["project"] else "") + what).strip()
            turns = int(ask.get("turns", 1))
            if ask.get("kind") == "claim":   # reattribution: two rows, the pool loses what the runner gains
                pool = sum(r["eff"] for r in read_ledger() if r["agent"] == "UNATTRIBUTED")
                if pts <= 0 or pts > pool:
                    return {"ok": False, "error": "the UNATTRIBUTED pool holds %+d" % pool}
                why = re.sub(r"[|\r\n]+", " / ", ask.get("why") or "").strip()
                if LEDGER_IS_JSONL:   # the points add-on ledger: same events its own CLI writes
                    entries = [("UNATTRIBUTED", -pts, "claim", "reattribution to %s: %s" % (runner, why)),
                               (runner, pts, "claim", "reattribution from UNATTRIBUTED: %s" % why)]
                else:
                    entries = [("UNATTRIBUTED (reattribution to %s)" % runner, -pts, "approved claim: %s (Consequences Brain)" % why, ""),
                               ("%s (reattribution from UNATTRIBUTED)" % runner, pts, "approved claim: %s (Consequences Brain)" % why, "")]
            elif LEDGER_IS_JSONL:
                entries = [(runner, pts, task, "awarded in the Consequences Brain" + (" (%d turns)" % turns if turns > 1 else ""))]
            else:
                entries = [(runner, pts, "%s%s (awarded in the Consequences Brain)" % (task, " (%d turns)" % turns if turns > 1 else ""), "")]
            bak, lines = append_ledger(entries)   # one write path for every award: backup first, both ledger formats
            cb_activity.resolve_ask(folder, os.path.basename(name), "awarded", pts)
            STATE.refresh(force=True)
            return {"ok": True, "row": "\n".join(lines), "backup": bak}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    # ---- gated point delegation: owner clicks only (agents use cb_gate.py claim, which cannot do any of these)
    def _gate(self, fn):
        if DEMO["on"]:
            return {"ok": False, "error": "sample mode: the gate is not shown"}
        try:
            out = fn()
            STATE.refresh(force=True)
            return {"ok": True, **(out if isinstance(out, dict) else {})}
        except (cb_gate.GateError, OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}

    def gate_approve_checks(self):
        return self._gate(lambda: {"approved_at": cb_gate.owner_approve()["approved_at"]})

    def gate_mode(self, live):
        return self._gate(lambda: cb_gate.owner_set_mode(bool(live)))

    def gate_revert(self, did):
        return self._gate(lambda: cb_gate.owner_revert(str(did)))

    def gate_decide(self, did, approve):
        return self._gate(lambda: cb_gate.owner_decide(str(did), bool(approve)))

    def dismiss_ask(self, where, name):
        try:
            if where == "sample":
                DEMO["asks"] = [x for x in (DEMO["asks"] or []) if x.get("file") != name]
                STATE.refresh(force=True)
                return {"ok": True}
            cb_activity.resolve_ask(ACTIVITY_DIRS[where], os.path.basename(name or ""), "dismissed")
            STATE.refresh(force=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def dismiss_quiet(self):
        """Clear every finished-work card that did not ask for points (one click; nothing is written to the ledger)."""
        n = 0
        try:
            rows, gate, now = ([] if DEMO["on"] else read_ledger()), gate_decisions(), time.time()
            for folder in ACTIVITY_DIRS.values():
                for k in cb_activity.read_asks(folder):
                    if k.get("quiet") and not (referee_verdict(k, rows, gate, now) or {}).get("points"):   # those show with the loud ones
                        cb_activity.resolve_ask(folder, k["file"], "dismissed")
                        n += 1
            STATE.refresh(force=True)
            return {"ok": True, "cleared": n}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def sample(self, on):
        """Show fictional sample data (this session only). The real ledger is neither read nor written while it is on."""
        DEMO.update(on=bool(on), extra=[], asks=None)
        STATE.refresh(force=True)
        return {"ok": True, "sample": DEMO["on"]}

    def copy(self, text):
        """Copy a help command to the clipboard (the page itself has no clipboard permission)."""
        try:
            import subprocess
            subprocess.run(["clip"], input=str(text or "")[:2000].encode("utf-16-le"), check=True, creationflags=0x08000000, timeout=5)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_note(self, text):
        text = re.sub(r"\s+", " ", (text or "")).strip()[:1000]
        if not text:
            return {"ok": False, "error": "empty note"}
        try:
            bak = _backup(INBOX)
            line = "- %s | Owner (Consequences Brain) | %s\n" % (time.strftime("%Y-%m-%d %H:%M"), text)
            if not os.path.exists(INBOX):
                with open(INBOX, "w", encoding="utf-8", newline="\n") as f:
                    f.write("---\ntype: inbox\n---\n# Inbox\n\nNotes added from the Consequences Brain window (append-only).\n\n")
            else:
                with open(INBOX, "rb") as f:
                    f.seek(0, 2)
                    nl_missing = False
                    if f.tell() > 0:
                        f.seek(-1, 2)
                        nl_missing = f.read(1) != b"\n"
                if nl_missing:
                    line = "\n" + line
            with open(INBOX, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
            STATE.refresh(force=True)
            return {"ok": True, "backup": bak}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------- window
WATCHER = None
SESSIONS = None   # built-in Claude Code session detector (cb_sessions.py)


def harden_http_server():
    """pywebview's bottle/wsgiref server listens with a backlog of 5; three.js asks for ~12 module files at once, so
    some got ERR_CONNECTION_REFUSED and the 3D view could stay blank. Raise the backlog before the server starts."""
    import socketserver
    socketserver.TCPServer.request_queue_size = 128


def save_window_state(hwnd):
    """Remember the window rectangle (restored on the next launch and after an in-place restart)."""
    import ctypes
    from ctypes import wintypes
    try:
        r = wintypes.RECT()
        u = ctypes.windll.user32
        if not hwnd or u.IsIconic(hwnd) or not u.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        st = {"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top, "max": bool(u.IsZoomed(hwnd))}
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f)
        return True
    except Exception:
        return False


def load_window_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
        if st["w"] >= 520 and st["h"] >= 420:
            return st
    except Exception:
        pass
    return None


def wait_for_exit(pid, timeout_ms=15000):
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(h, timeout_ms)
        k32.CloseHandle(h)


def start_watcher(on_change, **kw):
    global WATCHER
    WATCHER = Watcher(STATE, on_change, **kw)
    WATCHER.start()
    return WATCHER


def selftest():
    """--selftest: load config + ledger, build the model, print a summary, exit. Never opens a window."""
    STATE.refresh(force=True)
    g = STATE.graph
    report = json.dumps({"ok": "error" not in g, "version": VERSION, "ledger": SCOREBOARD,
                      "sample_rows": len(parse_ledger_jsonl(cb_sample.ledger_text())), "ledger_format": "jsonl" if LEDGER_IS_JSONL else "markdown",
                      "runners": sorted(n["label"] for n in g.get("nodes", []) if n.get("type") == "agent"),
                      "events": g.get("event_total", 0), "ui": os.path.isfile(os.path.join(RES_DIR, "ui", "index.html")),
                      "empty": not g.get("event_total"),
                      "three": os.path.isfile(os.path.join(RES_DIR, "ui", "vendor", "three-0.170.0", "three.module.min.js")),
                      "icon": os.path.isfile(ICON_PATH)})
    if sys.stdout:
        print(report, flush=True)
    out = os.environ.get("CB_SELFTEST_OUT")   # the windowed (packaged) app has no console
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(report)
    return 0


def cli_award(argv):
    """consequences_brain.py award "Runner" +5 "what it did" [--why "reason"]: one ledger entry, backup first."""
    import argparse
    ap = argparse.ArgumentParser(prog="award", description="Add points to the ledger (use a negative number to remove points).")
    ap.add_argument("runner")
    ap.add_argument("points", type=lambda s: int(s.replace("+", "").replace("\u2212", "-")))
    ap.add_argument("task", nargs="?", default="")
    ap.add_argument("--why", default="")
    a = ap.parse_args(argv)
    if not a.points or abs(a.points) > 500:
        ap.error("points must be between -500 and 500, and not 0")
    clean = lambda s: re.sub(r"[|\r\n]+", " / ", s or "").strip()   # noqa: E731
    if not LEDGER_IS_JSONL and not os.path.exists(SCOREBOARD):
        os.makedirs(os.path.dirname(SCOREBOARD) or ".", exist_ok=True)
        with open(SCOREBOARD, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# Scoreboard\n\n| When | Runner | Points | What |\n|---|---|---|---|\n")
    _bak, lines = append_ledger([(clean(a.runner), a.points, clean(a.task) or "work", clean(a.why))])
    if sys.stdout:
        print("%s <- %s" % (SCOREBOARD, lines[0]))
    return 0


def attach_stdio():
    """The packaged app is a windowed program, so Python starts it with no stdin/stdout. Reconnect the handles the caller
    passed (a pipe, a file, an agent hook), so command-line use can print its result and hooks can read their input."""
    if os.name != "nt" or (sys.stdout and sys.stdin and sys.stderr):
        return
    import ctypes
    import msvcrt
    get = ctypes.windll.kernel32.GetStdHandle
    get.restype = ctypes.c_void_p
    for name, number, mode in (("stdin", -10, "r"), ("stdout", -11, "w"), ("stderr", -12, "w")):
        if getattr(sys, name):
            continue
        try:
            handle = get(number)
            if handle and handle != ctypes.c_void_p(-1).value:
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY if mode == "r" else os.O_APPEND)
                setattr(sys, name, open(fd, mode, encoding="utf-8", errors="replace", buffering=1, closefd=False))
                continue
        except (OSError, ValueError):
            pass
        setattr(sys, name, open(os.devnull, mode, encoding="utf-8"))


def main():
    global WATCHER
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "working", "done", "idle", "list", "claim", "hook", "award", "gate"):
        attach_stdio()
    if "--version" in sys.argv:
        if sys.stdout:
            print(VERSION, flush=True)
        os._exit(0)
    if "--selftest" in sys.argv:
        os._exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] in ("working", "done", "idle", "list", "claim", "hook"):
        code = cb_activity.main(sys.argv[1:]) or 0        # the installed app doubles as the beacon command (no Python needed)
        sys.stdout and sys.stdout.flush()
        os._exit(code)
    if len(sys.argv) > 1 and sys.argv[1] == "gate":   # agents ask the gate for points: claim / recheck / status
        code = cb_gate.main(sys.argv[2:]) or 0
        sys.stdout and sys.stdout.flush()
        os._exit(code)
    if len(sys.argv) > 1 and sys.argv[1] == "award":
        code = cli_award(sys.argv[2:])
        sys.stdout and sys.stdout.flush()
        os._exit(code)
    if "--after" in sys.argv:   # in-place restart: wait for the old window's process to finish, then take over
        try:
            wait_for_exit(int(sys.argv[sys.argv.index("--after") + 1]))
        except (ValueError, IndexError):
            pass
    if not acquire_single_instance():
        focus_existing()
        os._exit(0)
    try:
        os.makedirs(cb_gate.gate_dir(), exist_ok=True)   # so the watcher can wake on gate decisions
    except OSError:
        pass
    try:  # own taskbar identity so the window icon is used, not python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Consequences.Brain")
    except Exception:
        pass
    import mimetypes
    mimetypes.add_type("text/javascript", ".js")
    harden_http_server()  # the 3D scene is an ES module: never let the registry say text/plain
    import webview
    hidden = os.environ.get("CB_HIDDEN") == "1"
    STATE.refresh(force=True)
    geo = load_window_state()
    # created hidden; shown only after the dark page and dark caption are in place (no white flash)
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=os.path.join(RES_DIR, "ui", "index.html"),
        js_api=Api(), resizable=True, background_color="#182d42", hidden=True, min_size=(520, 420),
        **({"x": geo["x"], "y": geo["y"], "width": geo["w"], "height": geo["h"]} if geo else {"width": 1200, "height": 680}),
    )
    page = {"loaded": False, "shown": False}
    show_lock = threading.Lock()

    def push(version):
        if page["loaded"]:
            try:
                window.evaluate_js("window.__cbChanged&&window.__cbChanged(%d)" % int(version))
            except Exception:
                pass

    def visible(flag):
        if page["loaded"]:
            try:
                window.evaluate_js("window.__cbVisible&&window.__cbVisible(%s)" % ("true" if flag else "false"))
            except Exception:
                pass

    def reveal():
        with show_lock:
            if page["shown"] or hidden:
                return
            page["shown"] = True
        try:
            style_window(find_app_window(os.getpid()))
        except Exception:
            pass
        window.show()
        if geo and geo.get("max"):
            try:
                window.maximize()
            except Exception:
                pass

    def on_code(kind):
        """New build on disk: UI files reload in place (state kept); backend files restart the window in place."""
        if kind == "ui":
            if page["loaded"]:
                try:
                    window.evaluate_js("window.__cbReload&&window.__cbReload()")
                except Exception:
                    pass
            return
        if page.get("restart_timer"):
            page["restart_timer"].cancel()          # still being edited: wait until the files are quiet
        t = threading.Timer(2.5, restart_in_place)
        t.daemon = True
        page["restart_timer"] = t
        t.start()

    def restart_in_place():
        import py_compile
        for f in CODE_FILES:                         # a broken build never replaces the running window
            try:
                py_compile.compile(f, doraise=True, cfile=os.path.join(os.environ.get("TEMP", APP_DIR), "cb_check.pyc"))
            except Exception:
                return
        if os.environ.get("CB_NO_RESTART") == "1":
            try:
                window.evaluate_js("window.__cbRestartRequested=1")
            except Exception:
                pass
            return
        save_window_state(find_app_window(os.getpid()))
        import subprocess
        exe = sys.executable.replace("python.exe", "pythonw.exe") if sys.executable.lower().endswith("python.exe") else sys.executable
        subprocess.Popen([exe, os.path.abspath(__file__), "--after", str(os.getpid())], cwd=APP_DIR,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            window.destroy()
        finally:
            threading.Timer(3.0, lambda: os._exit(0)).start()

    page["on_code"] = on_code
    window.events.closing += lambda *a: save_window_state(find_app_window(os.getpid()))
    window.events.minimized += lambda *a: visible(False)
    window.events.restored += lambda *a: visible(True)
    window.events.maximized += lambda *a: visible(True)
    # safety: never leave an invisible process behind if the page fails to load
    t = threading.Timer(6.0, reveal)
    t.daemon = True
    t.start()

    def on_loaded():
        page["loaded"] = True
        reveal()
        if WATCHER is None:
            start_watcher(push, on_code=None if getattr(sys, "frozen", False) else on_code)  # installed app: no self-update watch
            global SESSIONS
            if os.environ.get("CB_NO_SESSIONS") != "1" and SESSIONS is None:
                import cb_sessions
                SESSIONS = cb_sessions.ClaudeSessions(out=ACTIVITY_DIR)
                SESSIONS.start()
                start_referee_worker()   # same guard: tests set CB_NO_SESSIONS and never get a worker
        push(STATE.version)  # safety net if the page's own first load missed
        sel = os.environ.get("CB_DEMO_SELECT")
        if sel:
            def demo():
                time.sleep(2.5)
                try:
                    window.evaluate_js("window.__demoSelect && window.__demoSelect(%s)" % json.dumps(sel))
                except Exception:
                    pass
            threading.Thread(target=demo, daemon=True).start()
        hook = os.environ.get("CB_TEST_HOOK")
        if hook:
            import importlib.util
            spec = importlib.util.spec_from_file_location("cb_test_hook", hook)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            threading.Thread(target=mod.run, args=(window, sys.modules[__name__]), daemon=True).start()

    window.events.loaded += on_loaded
    webview.start()
    os._exit(0)  # quit fully on close


if __name__ == "__main__":
    main()