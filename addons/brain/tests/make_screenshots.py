"""Render README screenshots + a short demo GIF of the Consequences Brain from a FICTIONAL sample ledger (no real data).
Needs: pip install playwright pillow  &&  python -m playwright install chromium
    python addons/brain/tests/make_screenshots.py  -> assets/brain-*.png, assets/brain-demo.gif
"""
import functools
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
APP = os.path.join(ROOT, "addons", "brain", "app")
ASSETS = os.path.join(ROOT, "assets")
TMP = tempfile.mkdtemp(prefix="cb_shots_")
LEDGER = os.path.join(TMP, "ledger.jsonl")
SAMPLE = [  # fictional team, fictional work
    ("Claude Code (Opus)", "checkout flow", 25, "shipped with a passing gate and screenshots"),
    ("Claude Code (Opus)", "search index", 10, "fixed the root cause, not the symptom"),
    ("Claude Code (Opus)", "release notes", 3, "clear and short"),
    ("Claude Code (Sonnet)", "unit tests", 8, "found two real bugs"),
    ("Claude Code (Sonnet)", "deploy", -5, "said done before the smoke test ran"),
    ("Codex", "api client", 12, "typed client + retries, proven against staging"),
    ("Codex", "migration", -10, "dropped a column without a backup"),
    ("Gemini", "design review", 6, "caught the contrast issues"),
    ("Gemini", "copy edit", 2, "tightened the onboarding text"),
    ("DeepSeek", "log parser", 4, "fast and correct"),
    ("DeepSeek", "flaky test", -3, "retried instead of fixing"),
    ("Grok", "data export", 15, "csv + json, verified row counts"),
    ("GPT", "email draft", -2, "invented a feature that does not exist"),
    ("Claude Code (Opus)", "dashboard", 40, "live data, resizes cleanly, owner loved it"),
    ("Codex", "rollback script", 5, "one command, dry-run first"),
]
t0 = time.time() - 3 * 86400
with open(LEDGER, "w", encoding="utf-8") as f:
    for i, (a, task, pts, why) in enumerate(SAMPLE):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + i * 4200))
        f.write(json.dumps({"timestamp": ts, "agent": a, "task": task, "points": pts, "reason": why, "source": "owner", "tags": []}) + "\n")
with open(os.path.join(TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"ledger": LEDGER}, f)
os.environ.update(CB_CONFIG=os.path.join(TMP, "config.json"), CB_ACTIVITY=os.path.join(TMP, "act"), CB_SHARED_ACTIVITY="",
                  CB_BACKUPS=os.path.join(TMP, "bak"), CB_SKILLS=os.path.join(TMP, "skills"), CB_NO_SESSIONS="1")
sys.path.insert(0, APP)
import cb_activity  # noqa: E402
import consequences_brain as cb  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from PIL import Image  # noqa: E402

http.server.ThreadingHTTPServer.request_queue_size = 128


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main():
    os.makedirs(ASSETS, exist_ok=True)
    cb_activity.write("Claude Code (Opus)", "working", "my-app: add dark mode to settings", "w1", folder=os.environ["CB_ACTIVITY"])
    cb_activity.write("Codex", "working", "api: pagination for /orders", "w2", folder=os.environ["CB_ACTIVITY"])
    cb_activity.ask_done("Gemini", "accessibility pass", "a1", folder=os.environ["CB_ACTIVITY"], points=8,
                         why="fixed 14 contrast issues, verified with axe")
    api = cb.Api()
    cb.STATE.refresh(force=True)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=os.path.join(APP, "ui")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/index.html" % httpd.server_address[1]
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--use-angle=d3d11", "--ignore-gpu-blocklist"])
        p = b.new_page(viewport={"width": 1600, "height": 900})
        p.expose_function("cbData", lambda: api.data())
        p.expose_function("cbStats", lambda: api.stats())
        p.add_init_script("window.pywebview={api:{data:function(){return window.cbData();},stats:function(){return window.cbStats();}}};")
        p.goto(url)
        p.wait_for_function("window.CBScene && window.CBScene.ok && window.__cbTest.state().ready", timeout=30000)
        p.wait_for_timeout(4500)
        p.screenshot(path=os.path.join(ASSETS, "brain-overview.png"))
        top = p.evaluate("window.__cbTest.rows()[0].id")
        p.evaluate("id => window.__cbTest.select(id)", top)
        p.wait_for_timeout(2600)
        p.screenshot(path=os.path.join(ASSETS, "brain-selected.png"))
        p.evaluate("window.__cbTest.overview()")
        p.set_viewport_size({"width": 960, "height": 1000})
        p.wait_for_timeout(2200)
        p.screenshot(path=os.path.join(ASSETS, "brain-half-screen.png"))
        # demo gif: 1200x675, ~6 s at 10 fps, a points award lands half way
        p.set_viewport_size({"width": 1200, "height": 675})
        p.wait_for_timeout(2500)
        frames = []
        for i in range(45):
            if i == 18:
                p.click(".ask-card button.accept")
            img = Image.open(io.BytesIO(p.screenshot())).convert("RGB").resize((640, 360), Image.LANCZOS)
            frames.append(img.quantize(colors=96, method=Image.Quantize.MEDIANCUT))
            p.wait_for_timeout(70)
        frames[0].save(os.path.join(ASSETS, "brain-demo.gif"), save_all=True, append_images=frames[1:], duration=100, loop=0, optimize=True)
        b.close()
    httpd.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    for n in ("brain-overview.png", "brain-selected.png", "brain-half-screen.png", "brain-demo.gif"):
        print(n, os.path.getsize(os.path.join(ASSETS, n)) // 1024, "KB")


if __name__ == "__main__":
    main()
