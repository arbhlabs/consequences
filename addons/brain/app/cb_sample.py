"""Fictional sample data for the Consequences Brain ("Show sample data" on an empty scoreboard, and the README
screenshots). Invented agents doing invented work: nothing here comes from a real ledger. Never written to disk."""
import json
import time

SAMPLE = [  # (agent, task, points, reason)
    ("Claude Code (Opus)", "checkout flow", 25, "shipped with a passing gate and screenshots"),
    ("Claude Code (Opus)", "search index", 10, "fixed the root cause, not the symptom"),
    ("Claude Code (Opus)", "release notes", 3, "clear and short"),
    ("Claude Code (Sonnet)", "unit tests", 8, "found two real bugs"),
    ("Claude Code (Sonnet)", "deploy", -5, "said done before the smoke test ran"),
    ("Codex", "api client", 12, "typed client and retries, proven against staging"),
    ("Codex", "migration", -10, "dropped a column without a backup"),
    ("Gemini", "design review", 6, "caught the contrast issues"),
    ("Gemini", "copy edit", 2, "tightened the onboarding text"),
    ("DeepSeek", "log parser", 4, "fast and correct"),
    ("DeepSeek", "flaky test", -3, "retried instead of fixing"),
    ("Grok", "data export", 15, "csv and json, verified row counts"),
    ("GPT", "email draft", -2, "invented a feature that does not exist"),
    ("Claude Code (Opus)", "dashboard", 40, "live data, resizes cleanly, the owner loved it"),
    ("Codex", "rollback script", 5, "one command, dry run first"),
    ("Claude Code (Sonnet)", "docs", 4, "a stranger could follow the README"),
    ("Grok", "load test", -4, "tested staging, reported production"),
]


def ledger_text(now=None):
    """The sample as points add-on ledger lines (jsonl), spread over the last three days."""
    t0 = (time.time() if now is None else now) - 3 * 86400
    step = 3 * 86400 / (len(SAMPLE) + 1)
    return "\n".join(json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + i * step)), "agent": a, "task": task,
        "points": pts, "reason": why, "source": "sample", "tags": []}) for i, (a, task, pts, why) in enumerate(SAMPLE)) + "\n"


def activity(now=None):
    now = time.time() if now is None else now
    return [{"agent": "Claude Code (Opus)", "state": "working", "task": "my-app: add dark mode to settings", "ts": now - 40,
             "expires": now + 3600, "active": True, "file": "sample-working.json"}]


def asks(now=None):
    now = time.time() if now is None else now
    return [{"agent": "Gemini", "by": "Gemini", "task": "accessibility pass", "project": "my-app", "ts": now - 180, "since": now - 900,
             "started": now - 900, "state": "open", "turns": 1, "suggested": 8, "why": "fixed 14 contrast issues, verified with axe",
             "quiet": False, "file": "ask--sample-gemini.json"}]
