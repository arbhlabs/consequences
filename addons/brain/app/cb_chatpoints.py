"""Claude Code UserPromptSubmit hook: points the owner types in chat are logged the moment the prompt is sent.

"minus 20 points", "plus 3", "+5 pts", "-20 points" and a bare "+3" in a short reaction become ledger rows for the
model of that session, so the Consequences Brain shows them at once. Only explicit signed amounts count:
promised points ("I will award you 200 points") carry no sign and are ignored, and ranges like "5-10" are not
points. One row per prompt (a hash in a small state file). It never blocks the prompt and stays silent on failure.

The ledger is the same one the window reads: config.json "ledger" (a Scoreboard.md table or a ledger.jsonl), else
the add-on's own ledger.jsonl. Set CB_CHATPOINTS_LEDGER to override (tests).
"""
import datetime
import hashlib
import json
import os
import re
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
_APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
_LOCAL = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
NUM = r"(\d{1,4})"
PAT = re.compile(
    r"(?:(?P<word>\bplus|\bminus)\s+" + NUM + r"(?:\s*(?:points?|pts?)\b)?"
    r"|(?<![\w.])(?P<sign>[+\-−])\s?" + NUM + r"\s*(?:points?|pts?)?\b)",
    re.I)
NAMES = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5",
         "claude-fable-5-2": "Fable 5.2"}


def amounts(text):
    """Signed point amounts in the owner's prompt, in order. [] when there are none."""
    out = []
    for m in PAT.finditer(text or ""):
        word, sign = (m.group("word") or "").lower(), m.group("sign")
        n = int(m.group(2) or m.group(4))
        if sign and not re.search(r"\d\s*(?:points?|pts?)\b", m.group(0), re.I) and len(text.strip()) > 60:
            continue  # a bare "+3" counts in a short reaction ("+3", "nice work +5"); in long text only "-20 points"
        neg = word == "minus" or sign in ("-", "−")
        if 0 < n <= 1000:
            out.append(-n if neg else n)
    return out


def _config():
    path = os.environ.get("CB_CONFIG") or next((p for p in (os.path.join(APP_DIR, "config.json"),
                                                            os.path.join(_APPDATA, "Consequences", "config.json"))
                                                if os.path.isfile(p)), "")
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def ledger_path():
    return os.environ.get("CB_CHATPOINTS_LEDGER") or _config().get("ledger") or os.path.join(_LOCAL, "Consequences", "ledger.jsonl")


def state_path():
    return os.environ.get("CB_CHATPOINTS_STATE") or os.path.join(_LOCAL, "Consequences", "chatpoints-seen.json")


def model_of(transcript):
    """The model of the session's last assistant turn, as a short label."""
    try:
        with open(transcript, encoding="utf-8") as fh:
            lines = fh.readlines()[-400:]
    except OSError:
        return "Claude Code"
    for line in reversed(lines):
        try:
            m = (json.loads(line).get("message") or {}).get("model")
        except (ValueError, AttributeError):
            continue
        if m and m != "<synthetic>":
            return NAMES.get(m, m)
    return "Claude Code"


def rows_for(pts, runner, prompt, ledger, now=None):
    """The lines to append: Scoreboard.md table rows or add-on jsonl events."""
    now = now or datetime.datetime.now()
    quote = re.sub(r"\s+", " ", prompt).strip().replace("|", "/")[:220]
    if ledger.lower().endswith(".jsonl"):
        ts = now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return [json.dumps({"timestamp": ts, "agent": runner, "task": "chat", "points": p,
                            "reason": 'owner in chat: "%s"' % quote, "source": "owner", "tags": ["chat"]}) for p in pts]
    stamp = now.strftime("%Y-%m-%d %H:%M")
    return ['| %s | %s | %+d | owner (chat, logged instantly by hook): "%s" |' % (stamp, runner, p, quote) for p in pts]


def handle(d):
    """One hook call. Returns the message for the model, or None when nothing was logged."""
    prompt = d.get("prompt") or ""
    pts = amounts(prompt)
    if not pts:
        return None
    key = hashlib.sha1((d.get("session_id", "") + prompt).encode("utf-8", "ignore")).hexdigest()
    sp = state_path()
    try:
        with open(sp, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = []
    if key in seen:
        return None
    runner = "%s (Claude Code, %s)" % (model_of(d.get("transcript_path") or ""), os.path.basename(d.get("cwd") or "") or "chat")
    ledger = ledger_path()
    os.makedirs(os.path.dirname(ledger) or ".", exist_ok=True)
    nl_missing = False
    if os.path.exists(ledger) and os.path.getsize(ledger):
        with open(ledger, "rb") as f:
            f.seek(-1, 2)
            nl_missing = f.read(1) != b"\n"
    with open(ledger, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(("\n" if nl_missing else "") + "\n".join(rows_for(pts, runner, prompt, ledger)) + "\n")
    os.makedirs(os.path.dirname(sp) or ".", exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump((seen + [key])[-500:], f)
    return "Points logged to the Consequences Brain: %s for %s. Do not log them again." % (", ".join("%+d" % p for p in pts), runner)


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return
    msg = handle(d if isinstance(d, dict) else {})
    if msg:
        print(msg)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
