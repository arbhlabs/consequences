"""Render the README screenshots and the demo clip of the Consequences Brain from a FICTIONAL sample ledger.

No real data and no window on screen: the real page runs in headless Chromium against a temp ledger built from
cb_sample.py (the same invented team as "Show sample data").

Needs: pip install playwright pillow  &&  python -m playwright install chromium  (and ffmpeg on PATH for the clip)
    python addons/brain/tests/make_screenshots.py [--no-clip]
Writes assets/brain-overview.png, brain-selected.png, brain-points-ask.png, brain-working.png, brain-half-screen.png,
and (unless --no-clip) assets/brain-demo.mp4 + assets/brain-demo.gif.
"""
import functools
import glob
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
APP = os.path.join(ROOT, "addons", "brain", "app")
ASSETS = os.path.join(ROOT, "assets")
TMP = tempfile.mkdtemp(prefix="cb_shots_")
LEDGER = os.path.join(TMP, "ledger.jsonl")
ACT = os.path.join(TMP, "act")
sys.path.insert(0, APP)
from cb_sample import SAMPLE  # noqa: E402  (the same fictional team as "Show sample data")
t0 = time.time() - 3 * 86400
with open(LEDGER, "w", encoding="utf-8") as f:
    for i, (a, task, pts, why) in enumerate(SAMPLE):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + i * 3600))
        f.write(json.dumps({"timestamp": ts, "agent": a, "task": task, "points": pts, "reason": why, "source": "owner", "tags": []}) + "\n")
with open(os.path.join(TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"ledger": LEDGER}, f)
os.environ.update(CB_CONFIG=os.path.join(TMP, "config.json"), CB_ACTIVITY=ACT, CB_SHARED_ACTIVITY="",
                  CB_BACKUPS=os.path.join(TMP, "bak"), CB_SKILLS=os.path.join(TMP, "skills"), CB_NO_SESSIONS="1",
                  CB_NO_REFEREE_WORKER="1", CB_REFEREE_DIR=os.path.join(TMP, "referee"), CB_GATE=os.path.join(TMP, "gate"),
                  CB_TRANSCRIPTS=os.path.join(TMP, "transcripts"))
import cb_activity  # noqa: E402
import consequences_brain as cb  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

http.server.ThreadingHTTPServer.request_queue_size = 128
API_METHODS = [m for m in dir(cb.Api) if not m.startswith("_") and callable(getattr(cb.Api, m))]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def open_page(browser, url, api, size, video_dir=None):
    ctx = browser.new_context(viewport=size, **({"record_video_dir": video_dir, "record_video_size": size} if video_dir else {}))
    p = ctx.new_page()
    for m in API_METHODS:
        p.expose_function("cb_" + m, functools.partial(lambda name, *a: getattr(api, name)(*a), m))
    p.add_init_script("window.pywebview={api:{}};%s" % "".join(
        "window.pywebview.api.%s=function(){return window.cb_%s.apply(null,arguments);};" % (m, m) for m in API_METHODS))
    p.goto(url)
    p.wait_for_function("window.CBScene && window.CBScene.ok && window.__cbTest.state().ready", timeout=30000)
    return ctx, p


def push(p):
    cb.STATE.refresh(force=True)
    p.evaluate("v => window.__cbChanged && window.__cbChanged(v)", cb.STATE.version)


def ffmpeg(args):
    keeper = os.environ.get("CB_HEAVY")   # optional: a wrapper that queues heavy jobs, e.g. "python heavy.py run --kind ffmpeg --"
    cmd = (keeper.split() if keeper else []) + ["ffmpeg", "-y", "-v", "error"] + args
    subprocess.run(cmd, check=True)


def main():
    clip = "--no-clip" not in sys.argv
    os.makedirs(ASSETS, exist_ok=True)
    cb_activity.write("Claude Code (Opus)", "working", "my-app: add dark mode to settings", "w1", folder=ACT)
    cb_activity.write("Codex", "working", "api: pagination for /orders", "w2", folder=ACT)
    cb_activity.ask_done("Gemini", "accessibility pass", "a1", folder=ACT, points=8, why="fixed 14 contrast issues, verified with axe")
    cb_activity.ask_done("Claude Code (Sonnet)", "flaky login test", "a2", folder=ACT, points=5,
                         why="found the race in the session cookie, 50 green runs")
    api = cb.Api()
    cb.STATE.refresh(force=True)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=os.path.join(APP, "ui")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/index.html" % httpd.server_address[1]
    vid_dir = os.path.join(TMP, "video")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--use-angle=d3d11", "--ignore-gpu-blocklist"])
        ctx, p = open_page(b, url, api, {"width": 1600, "height": 900})
        p.wait_for_timeout(4500)
        p.screenshot(path=os.path.join(ASSETS, "brain-overview.png"))
        p.locator("[data-panel=feed]").screenshot(path=os.path.join(ASSETS, "brain-points-ask.png"))
        p.locator("[data-panel=leaderboard]").screenshot(path=os.path.join(ASSETS, "brain-working.png"))
        top = p.evaluate("window.__cbTest.rows()[0].id")
        p.evaluate("id => window.__cbTest.select(id)", top)
        p.wait_for_timeout(2600)
        p.screenshot(path=os.path.join(ASSETS, "brain-selected.png"))
        p.evaluate("window.__cbTest.overview()")
        p.set_viewport_size({"width": 960, "height": 1000})
        p.wait_for_timeout(2200)
        p.screenshot(path=os.path.join(ASSETS, "brain-half-screen.png"))
        ctx.close()
        if clip:   # ~16 s: overview, a runner's detail, a new agent starts work, the owner accepts a points ask
            ctx, p = open_page(b, url, api, {"width": 1280, "height": 720}, video_dir=vid_dir)
            p.wait_for_timeout(3500)
            p.evaluate("id => window.__cbTest.select(id)", p.evaluate("window.__cbTest.rows()[0].id"))
            p.wait_for_timeout(3000)
            p.evaluate("window.__cbTest.overview()")
            p.wait_for_timeout(1500)
            cb_activity.write("Grok", "working", "data: nightly export check", "w3", folder=ACT)
            push(p)
            p.wait_for_timeout(2500)
            p.click(".ask-card button.accept >> nth=0")
            p.wait_for_timeout(3500)
            p.click("#lb-sort [data-sort=xp]")
            p.wait_for_timeout(2000)
            ctx.close()
        b.close()
    httpd.shutdown()
    if clip:
        webm = glob.glob(os.path.join(vid_dir, "*.webm"))[0]
        mp4, gif = os.path.join(ASSETS, "brain-demo.mp4"), os.path.join(ASSETS, "brain-demo.gif")
        # the first ~1.5 s of a recording is the page loading: skip it
        ffmpeg(["-ss", "1.5", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "slow",
                "-movflags", "+faststart", "-an", mp4])
        ffmpeg(["-ss", "1.5", "-i", webm, "-vf", "fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=4", gif])
    shutil.rmtree(TMP, ignore_errors=True)
    for n in ("brain-overview.png", "brain-selected.png", "brain-points-ask.png", "brain-working.png", "brain-half-screen.png") + \
            (("brain-demo.mp4", "brain-demo.gif") if clip else ()):
        print(n, os.path.getsize(os.path.join(ASSETS, n)) // 1024, "KB")


if __name__ == "__main__":
    main()
