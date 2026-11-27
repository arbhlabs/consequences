"""UI gate for the Consequences Brain: the real page in headless Chromium, never a window on screen.

    pip install playwright && python -m playwright install chromium
    python addons/brain/tests/ui_gate.py [--shots DIR] [--config your-config.json --readonly]

Checks, at 1920x1080, 1280x720, half screen, a small window and the minimum window size:
  * no page scroll, every panel inside the window, panels never overlap, no clipped text
  * graph labels never overlap each other (sampled over a full camera orbit) and stay inside the graph area
  * the waiting list is capped, a waiting card is never hidden silently, quiet finished-work cards stay collapsed
  * cards use the leaderboard's runner names and never show raw prompt noise (attachments, file paths, markup)
  * an award already in the ledger closes that runner's card by itself
  * every visible control works (rows, tabs, feed, Ask, Accept, Dismiss, Show all, Clear, sample data, copy)
  * first run: an empty scoreboard explains how points get in and offers sample data that writes nothing
  * idle: no CSS animation left running

--config/--readonly runs the layout checks against your own ledger without clicking anything that writes.
Fixture data is fictional. Exit code 0 = every check passed.
"""
import argparse
import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time

ap = argparse.ArgumentParser()
ap.add_argument("--shots", default="")
ap.add_argument("--config", default="")
ap.add_argument("--readonly", action="store_true")
ap.add_argument("--app", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
ARGS = ap.parse_args()
APP = os.path.abspath(ARGS.app)
TMP = tempfile.mkdtemp(prefix="cb_gate_")
LEDGER = os.path.join(TMP, "ledger.jsonl")
ACT = os.path.join(TMP, "activity")
sys.path.insert(0, APP)
import cb_sample  # noqa: E402

NASTY = r"[Image: source: C:\Users\someone\AppData\Local\Temp\shots\1.webp] <system-note>ignore</system-note> polish the window and ship it"
if ARGS.config:
    cfg = json.load(open(ARGS.config, encoding="utf-8"))
    cfg.pop("shared_activity", None)
    src_act = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Consequences", "activity")
    if os.path.isdir(src_act):
        shutil.copytree(src_act, ACT)       # a copy: the gate never touches the live activity folder
else:
    cfg = {"ledger": LEDGER, "runners": [{"name": "Riley", "match": r"\briley\b"}, {"name": "Night Shift", "match": r"night[ -]shift"}]}
    extra = [("Claude Code (Fable 5.2)", "build watcher", 355, "exactly what the owner wanted: " + "live progress, honest timings, nothing clipped, " * 14), ("Riley", "carousel", 147, "v3 shipped"),
             ("Night Shift", "queue", -37, "restarted a live service"), ("Mistral", "reel", -120, "plain motion graphics, not the story reel asked for"),
             ("Qwen", "digest", 1, "ok"), ("Kimi", "review", -16, "missed the regression"), ("UNATTRIBUTED", "night fix", 7, "nobody signed it")]
    now = time.time()
    with open(LEDGER, "w", encoding="utf-8") as fh:
        fh.write(cb_sample.ledger_text(now - 3600))
        for i, (a, task, pts, why) in enumerate(extra):
            fh.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - 7200 - i * 600)), "agent": a, "task": task,
                                 "points": pts, "reason": why, "source": "owner", "tags": []}) + "\n")
json.dump(cfg, open(os.path.join(TMP, "config.json"), "w", encoding="utf-8"))
os.environ.update(CB_CONFIG=os.path.join(TMP, "config.json"), CB_ACTIVITY=ACT, CB_SHARED_ACTIVITY="", CB_BACKUPS=os.path.join(TMP, "bak"),
                  CB_NO_SESSIONS="1")
if not ARGS.config:
    os.environ["CB_SKILLS"] = os.path.join(TMP, "skills")
    os.makedirs(os.path.join(TMP, "skills", "consequences"))
    with open(os.path.join(TMP, "skills", "consequences", "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write("# Consequences\n\n## What lost points (never repeat)\n- Night Shift restarted a live service (2026-01-04, -37). "
                 "Ask first; see `C:\\Users\\someone\\notes\\rule.md` {\"a\": 1}.\n")
import cb_activity  # noqa: E402
import consequences_brain as cb  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

if not ARGS.config:
    A = dict(folder=ACT)
    cb_activity.write("Claude Code (Fable 5.2)", "working", "Home: " + NASTY, "w1", **A)
    cb_activity.write("Claude Code (Fable 5.2)", "working", "my-app: add dark mode", "w2", **A)
    for i, (agent, why) in enumerate([("Claude Code (Opus 5.5)", "0.7.1 on the phone with 393/393 tests and a reusable live install window; the tablet chat test is still open"),
                                      ("Codex", "typed client, retries, proven against staging"), ("Gemini", "fixed 14 contrast issues"),
                                      ("Riley", "v4 carousel"), ("DeepSeek", "log parser twice as fast"), ("Grok", "export verified")]):
        cb_activity.ask_done(agent, "my-app: " + NASTY, "l%d" % i, points=(10, 5, 8, 20, 3, -5)[i], why=why, project="my-app", started=time.time() - 60, **A)
    for i in range(9):
        cb_activity.ask_done("Claude Code (Sonnet 5.5)", ("Reply with the single word ok." if i % 2 else NASTY), "q%d" % i, project="scratch", started=time.time() - 60, **A)
    cb_activity.claim("Riley", 3, "the night fix was mine: commit abc123", **A)

SIZES = [(1920, 1080), (1280, 720), (960, 1040), (700, 560), (520, 420)]
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (("  -> " + str(detail)[:400]) if (detail and not ok) else ""), flush=True)


LAYOUT_JS = r"""() => {
  const vis = (e) => { if (!e || e.hidden) return false; const s = getComputedStyle(e); if (s.display === 'none' || s.visibility === 'hidden') return false;
    for (let p = e; p; p = p.parentElement) { if (p.hidden || getComputedStyle(p).display === 'none') return false; } const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const W = innerWidth, H = innerHeight, out = { scroll: [document.documentElement.scrollWidth > W + 1, document.documentElement.scrollHeight > H + 1], off: [], overlap: [], clipped: [], spill: [], wasted: [] };
  const panels = [...document.querySelectorAll('[data-panel]')].filter((e) => vis(e) && e.dataset.panel !== 'graph' && e.dataset.panel !== 'onboard');
  const R = (e) => e.getBoundingClientRect();
  panels.forEach((p) => { const r = R(p); if (r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1) out.off.push(p.dataset.panel + ' ' + [r.left, r.top, r.right, r.bottom].map(Math.round)); });
  for (let i = 0; i < panels.length; i++) for (let j = i + 1; j < panels.length; j++) { const a = R(panels[i]), b = R(panels[j]);
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) out.overlap.push(panels[i].dataset.panel + '/' + panels[j].dataset.panel); }
  const sel = '.brand h1,.brand p,.stat b,.stat span,.stamp,.work-pill,.ask-pill,.panel-head h2,.panel-head span,.row .name,.row .standing,.row .score,.rank,.tabs button,.mtabs button,' +
              '.ask-card,.ask-card button,.ask-more,.ask-more button,.feed-row,.tl-item,.rank-row,#detail-title,.kicker,.meta,.bigscore,.ask input,.ask button,#ask-answer,.onboard,.onboard code,.onboard button,.sample-tag,.hint,.panel-foot,.more';
  document.querySelectorAll(sel).forEach((e) => { if (!vis(e)) return;
    const r = R(e), box = e.closest('[data-panel]') || document.body, b = R(box), cs = getComputedStyle(e);
    if (e.scrollWidth > e.clientWidth + 1 && cs.overflowX !== 'visible' && !e.classList.contains('onboard')) out.clipped.push((e.id || e.className) + ': ' + e.textContent.trim().slice(0, 40));
    const inScroll = !!e.closest('.scroll,.onboard');
    if (r.left < b.left - 1 || r.right > b.right + 1 || (!inScroll && (r.top < b.top - 1 || r.bottom > b.bottom + 1))) out.spill.push((e.id || e.className) + ' out of ' + (box.dataset ? box.dataset.panel : 'body') + ': ' + e.textContent.trim().slice(0, 30));
    for (let p = e.parentElement; p && p !== box.parentElement; p = p.parentElement) { const ps = getComputedStyle(p);
      const scrolls = ps.overflowY === 'auto' || ps.overflowY === 'scroll';   // a scrolling list may run past its bottom edge; nothing else may
      if (ps.overflowY === 'hidden' || ps.overflowX === 'hidden') { const q = R(p); if ((!scrolls && !inScroll && r.bottom > q.bottom + 1.5) || r.right > q.right + 1.5) { out.clipped.push('cut by ' + (p.id || p.className) + ': ' + e.textContent.trim().slice(0, 40)); break; } } }
  });
  const fl = document.getElementById('feed-list');
  if (vis(fl)) { const kids = [...fl.children], last = kids.filter((k) => !k.hidden).pop(), free = last ? R(fl).bottom - R(last).bottom : 0, firstHidden = kids.find((k) => k.hidden);
    if (firstHidden && free > 110) out.wasted.push('feed: ' + Math.round(free) + 'px free while rows are hidden'); }
  const tl = document.getElementById('timeline');
  if (vis(document.querySelector('[data-panel=detail]')) && !document.querySelector('.detail.compact') && tl.children.length && ![...tl.children].some(vis))
    out.wasted.push('detail: the timeline has ' + tl.children.length + ' lines and shows none');
  return out;
}"""

LABELS_JS = r"""async () => {
  if (!window.CBScene || !window.CBScene.ok) return { skipped: true };
  const v0 = window.CBScene.getView(), bad = [], area = document.querySelector('[data-panel=graph]').getBoundingClientRect();
  let seen = 0;
  const t = v0.t, d = [v0.p[0] - t[0], v0.p[1] - t[1], v0.p[2] - t[2]];
  for (let k = 0; k < 36; k++) { const a = (k / 36) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
    window.CBScene.setView({ t, p: [t[0] + d[0] * c + d[2] * s, t[1] + d[1], t[2] - d[0] * s + d[2] * c] });
    const L = window.CBScene.labels(); seen += L.length;
    for (let i = 0; i < L.length; i++) { const x = L[i];
      if (x.x < area.left - 1 || x.y < area.top - 1 || x.x + x.w > area.right + 1 || x.y + x.h > area.bottom + 1) bad.push('outside@' + k + ': ' + x.text);
      for (let j = i + 1; j < L.length; j++) { const y = L[j];
        if (x.x < y.x + y.w + 6 && y.x < x.x + x.w + 6 && x.y < y.y + y.h && y.y < x.y + x.h) bad.push('overlap@' + k + ': ' + x.text + ' | ' + y.text); } } }
  window.CBScene.setView(v0);
  return { bad: bad.slice(0, 6), count: bad.length, seen };
}"""


def main():
    api = cb.Api()
    copied = []
    api.copy = lambda text: (copied.append(text), {"ok": True})[1]      # the gate never touches the real clipboard
    cb.STATE.refresh(force=True)
    http.server.ThreadingHTTPServer.request_queue_size = 128

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *x):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=os.path.join(APP, "ui")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/index.html" % httpd.server_address[1]
    names = ["data", "stats", "award", "dismiss_ask", "dismiss_quiet", "sample", "copy", "ask", "add_note", "open_path"]
    if ARGS.shots:
        os.makedirs(ARGS.shots, exist_ok=True)
    gl = os.environ.get("CB_GATE_GL", "d3d11")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--use-angle=" + gl, "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"])

        def page(w, h):
            p = b.new_page(viewport={"width": w, "height": h})
            p.errs = []
            p.on("pageerror", lambda e: p.errs.append(str(e)))
            for n in names:
                p.expose_function("cb_" + n, getattr(api, n))
            p.add_init_script("window.pywebview={api:{}};%s.forEach(function(n){window.pywebview.api[n]=function(){return window['cb_'+n].apply(null,arguments);};});" % json.dumps(names))
            p.goto(url)
            p.wait_for_function("window.__cbTest && window.__cbTest.state().ready", timeout=30000)
            p.wait_for_timeout(3800)
            return p

        def layout(p, tag):
            r = p.evaluate(LAYOUT_JS)
            bad = [k + ": " + "; ".join(v[:3]) for k, v in r.items() if k != "scroll" and v]
            check("%s layout: no scroll, overlap, clipping or wasted space" % tag, not any(r["scroll"]) and not bad, bad or r["scroll"])
            if ARGS.shots:
                p.screenshot(path=os.path.join(ARGS.shots, tag.replace(" ", "-") + ".png"))

        for w, h in SIZES:
            p = page(w, h)
            tag = "%dx%d" % (w, h)
            scene_ok = p.evaluate("!!(window.CBScene && window.CBScene.ok)")
            layout(p, tag)
            if w <= 640 or h <= 520:                       # tabbed layout: check every tab
                for m in ("detail", "feed", "ask", "board"):
                    p.click('#mtabs [data-m="%s"]' % m)
                    p.wait_for_timeout(250)
                    layout(p, "%s tab-%s" % (tag, m))
            lab = p.evaluate(LABELS_JS)
            if lab.get("skipped"):
                check("%s labels (skipped: no WebGL here)" % tag, True)
            else:
                check("%s graph labels never overlap or leave the graph area (36 camera angles, %d labels seen)" % (tag, lab["seen"]),
                      lab["count"] == 0 and lab["seen"] > 0, lab["bad"])
            av = p.evaluate("window.__cbTest.asksView()")
            rows = {r["name"] for r in p.evaluate("window.__cbTest.rows()")}
            if w > 640 and h > 520:
                check("%s waiting list: capped, quiet group collapsed, nothing hidden silently" % tag,
                      av["cards"] <= 5 or av["scroll"], av)
            noise = [t for t in av["text"] if "[Image" in t or ":\\" in t or "<" in t]
            check("%s cards show no raw prompt noise" % tag, not noise, noise[:2])
            if not ARGS.config:
                check("%s card runner names match the leaderboard" % tag, set(av["names"]) <= rows, sorted(set(av["names"]) - rows))
            idle = p.evaluate("window.__cbTest.idle()")
            check("%s idle: no CSS animation left running" % tag, idle["runningAnimations"] == 0, idle)
            check("%s no script errors" % tag, not p.errs, p.errs[:2])
            if (w, h) == (1920, 1080) and not ARGS.readonly:
                colour_scale(p, scene_ok)
                pos = runner_view(p, "Fable", "runner view positive")
                check("runner view: a working runner shows its task; no lesson says so", "Working on" in pos and "No lessons recorded yet" in pos, pos)
                neg = runner_view(p, "Night Shift", "runner view negative")
                check("runner view: idle, single event, lesson from the skill file",
                      "Idle." in neg and "Only one scored event" in neg and "restarted a live service (2026-01-04" in neg, neg)
                p.keyboard.press("Escape")
                p.wait_for_timeout(500)
                controls(p, scene_ok)
            p.close()

        if not ARGS.readonly:
            first_run(page, layout, copied)
        b.close()
    httpd.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    bad = [r for r in RESULTS if not r[1]]
    print("\nUI GATE %s  %d/%d" % ("PASS" if not bad else "FAIL", len(RESULTS) - len(bad), len(RESULTS)))
    return 1 if bad else 0


SCALE = {"green": "rgb(79, 224, 138)", "yellow": "rgb(255, 225, 77)", "orange": "rgb(255, 159, 67)", "red": "rgb(255, 93, 115)"}


def contrast(rgb, back=(22, 42, 61)):   # WCAG ratio against the navy the 3D view renders
    def lum(c):
        v = [x / 255 for x in c]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    return (lum(rgb) + 0.05) / (lum(back) + 0.05)


def colour_scale(p, scene_ok):
    got = p.evaluate("""Array.prototype.map.call(document.querySelectorAll('[data-leader]'),function(r){
        return {name:r.querySelector('.name').textContent,val:Number(r.getAttribute('data-val')),tier:r.getAttribute('data-tier'),
        score:getComputedStyle(r.querySelector('.score')).color,dot:getComputedStyle(r.querySelector('.sw')).color,bar:getComputedStyle(r.querySelector('.bar')).color};})""")
    bad = []
    for i, r in enumerate(got):
        want = "red" if r["val"] < 0 else ("green" if i < 3 else ("yellow" if r["val"] >= 20 else "orange"))
        if r["tier"] != want or {r["score"], r["dot"], r["bar"]} != {SCALE[want]}:
            bad.append((r, want))
    check("colour scale: leaderboard dots, scores and bars follow green/yellow/orange/red (%d runners)" % len(got), got and not bad, bad[:3])
    check("colour scale: legend states the rule", all(w in p.inner_text(".panel-foot") for w in ("top 3", "+20", "0 to +19", "below 0")))
    ratios = {k: round(contrast([int(x) for x in v[4:-1].split(",")]), 2) for k, v in SCALE.items()}
    check("colour scale: every step reads on the navy background (4.5:1)", min(ratios.values()) >= 4.5, ratios)
    if scene_ok:
        want = {r["name"]: SCALE[r["tier"]] for r in got}
        lab = p.evaluate("Array.prototype.map.call(document.querySelectorAll('#labels .lbl.hub'),function(e){return [e.textContent,getComputedStyle(e).color,e.style.display];})")
        seen = [(t.split("  ")[0], c) for t, c, d in lab if d != "none" and t.split("  ")[0] in want]
        check("colour scale: graph labels match the leaderboard (%d seen)" % len(seen), seen and all(want[n] == c for n, c in seen), seen[:5])


def runner_view(p, name, tag):
    rid = [r for r in p.evaluate("window.__cbTest.rows()") if r["name"] == name]
    if not rid:
        check(tag + ": runner present", False, name)
        return ""
    p.evaluate("window.__cbTest.select(%s)" % json.dumps(rid[0]["id"]))
    p.wait_for_timeout(900)
    body = p.inner_text('[data-panel="detail"] .body')
    low = body.lower()
    check(tag + ": says what it is doing, its standing, latest points, lessons and waiting work",
          all(w in low for w in ("right now", "waiting for points", "latest points", "what it learned", "rank ")), body[:400])
    check(tag + ": plain words (no paths or JSON)", not any(w in body for w in (":\\", "{", "}", "`", "AppData")), body)
    over = p.evaluate("(function(){var b=document.querySelector('.detail .body');return [b.scrollWidth-b.clientWidth,getComputedStyle(b).overflowY];})()")
    check(tag + ": nothing cut sideways, long content scrolls", over[0] <= 1 and over[1] == "auto", over)
    if ARGS.shots:
        p.screenshot(path=os.path.join(ARGS.shots, tag.replace(" ", "-") + ".png"))
    return body


def controls(p, scene_ok):
    T = "window.__cbTest"
    rows = p.evaluate(T + ".rows()")
    p.click('[data-leader="%s"]' % rows[1]["id"])
    p.wait_for_timeout(300)
    check("click: leaderboard row selects the runner", p.evaluate(T + ".state().selected") == rows[1]["id"])
    check("click: detail shows that runner", rows[1]["name"] in p.inner_text("#detail-title"))
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)
    check("key: Esc returns to the overview", p.evaluate(T + ".state().selected") is None)
    for tab, word in (("ranks", "promotion ranks"), ("rules", "standing rules"), ("moves", "biggest moves")):
        p.click('#detail-tabs [data-tab="%s"]' % tab)
        p.wait_for_timeout(150)
        check("click: %s tab" % tab, word in p.inner_text("#detail-kicker").lower(), p.inner_text("#detail-kicker"))
    p.click("#timeline .tl-item >> nth=0")
    p.wait_for_timeout(250)
    check("click: a timeline line opens that event", (p.evaluate(T + ".state().selected") or "").startswith("p:"))
    p.click("#brand")
    p.wait_for_timeout(200)
    check("click: brand returns to the overview", p.evaluate(T + ".state().selected") is None)
    p.fill("#ask-input", "who leads?")
    p.click("#ask-submit")
    p.wait_for_timeout(300)
    check("ask: 'who leads?' answers with the top runner", rows[0]["name"] in p.inner_text("#ask-answer"), p.inner_text("#ask-answer"))
    p.click("#ask-answer .answer-link")
    p.wait_for_timeout(200)
    check("click: 'Show in map' selects", p.evaluate(T + ".state().selected") is not None)
    p.keyboard.press("Escape")
    # waiting list
    av = p.evaluate(T + ".asksView()")
    check("waiting list: 7 waiting, 9 quiet, at most 4 cards shown, none cut off", (av["loud"], av["quiet"]) == (7, 9) and 1 <= av["cards"] <= 4 and not av["scroll"], av)
    check("header pill counts only real asks", "7 waiting" in p.inner_text("#ask-pill").lower(), p.inner_text("#ask-pill"))
    p.click("[data-asks-toggle]")
    p.wait_for_timeout(200)
    av = p.evaluate(T + ".asksView()")
    check("click: Show all lists every waiting card and scrolls", av["cards"] == 7 and av["scroll"], av)
    p.click("[data-asks-toggle]")
    p.click("[data-quiet-toggle]")
    p.wait_for_timeout(200)
    av = p.evaluate(T + ".asksView()")
    check("click: Show opens the quiet group", av["cards"] >= 10 and av["scroll"], av)
    quiet_text = " ".join(t for t in av["text"] if "Suggests" not in t and "asks to take" not in t)
    check("quiet cards have a clean title (project, no prompt text as headline)", "finished in scratch" in quiet_text and "[Image" not in quiet_text, quiet_text[:200])
    p.click("[data-quiet-toggle]")
    before = sum(1 for _ in open(LEDGER, encoding="utf-8"))
    p.click('.ask-card button.accept:has-text("Accept") >> nth=0')
    p.wait_for_timeout(900)
    lines = open(LEDGER, encoding="utf-8").read().splitlines()
    last = json.loads(lines[-1])
    check("click: Accept writes one ledger entry with the agent's own reason", len(lines) == before + 1 and "[Image" not in last["task"] and last["points"] != 0, last)
    check("ledger was backed up before the write", os.path.isdir(os.path.join(TMP, "bak")) and os.listdir(os.path.join(TMP, "bak")))
    check("the awarded card is gone", p.evaluate(T + ".asksView()")["loud"] == 6, p.evaluate(T + ".asksView()"))
    p.click('.ask-card:has(button.accept:has-text("Accept")) [data-dismiss] >> nth=0')
    p.wait_for_timeout(700)
    check("click: Dismiss closes a card and writes nothing", p.evaluate(T + ".asksView()")["loud"] == 5 and len(open(LEDGER, encoding="utf-8").read().splitlines()) == before + 1)
    p.click("[data-quiet-clear]")
    p.wait_for_timeout(900)
    check("click: Clear removes the quiet group", p.evaluate(T + ".asksView()")["quiet"] == 0, p.evaluate(T + ".asksView()"))
    # an award the owner gave in chat, logged in the ledger by the agent itself, closes that runner's card
    cb_activity.ask_done("Mistral", "reel v2", "chat1", points=5, why="story reel", folder=ACT, started=time.time() - 120)
    cb.STATE.refresh(force=True)
    p.evaluate("window.__cbChanged(-2)")
    p.wait_for_timeout(700)
    had = any("Mistral" in n for n in p.evaluate(T + ".asksView()")["names"]) or p.evaluate(T + ".asksView()")["loud"] == 6
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "agent": "Mistral", "task": "reel v2",
                             "points": 5, "reason": "owner said plus 5 in chat", "source": "owner", "tags": []}) + "\n")
    cb.STATE.refresh(force=True)
    p.evaluate("window.__cbChanged(-3)")
    p.wait_for_timeout(900)
    check("an award already in the ledger closes that runner's card", had and p.evaluate(T + ".asksView()")["loud"] == 5, p.evaluate(T + ".asksView()"))
    if scene_ok:
        st = p.evaluate("window.CBScene.stats()")
        check("3D scene is rendering", st["renders"] > 10 and st["nodes"] > 5, st)


def first_run(page, layout, copied):
    """A stranger's first launch: empty ledger, no activity."""
    for fn in os.listdir(ACT):
        os.remove(os.path.join(ACT, fn))
    open(LEDGER, "w").close()
    cb.STATE.refresh(force=True)
    for w, h in ((1920, 1080), (960, 1040), (520, 420)):
        p = page(w, h)
        tag = "first run %dx%d" % (w, h)
        su = p.evaluate("window.__cbTest.setup()")
        check(tag + ": the empty window explains how points get in", su["onboard"] and "Points for this? Suggested: +5" in p.inner_text("#onboard")
              and " done " in p.inner_text("#ob-done") and " award " in p.inner_text("#ob-award"), su)
        layout(p, tag)
        if (w, h) == (1920, 1080):
            p.click('[data-copy="ob-award"]')
            p.wait_for_timeout(300)
            check("first run: Copy hands over the award command", copied and " award " in copied[-1], copied[-1:])
            p.click("#ob-sample")
            p.wait_for_timeout(1500)
            su = p.evaluate("window.__cbTest.setup()")
            check("first run: Show sample data fills the board and says so", su["sample"] and not su["onboard"] and len(p.evaluate("window.__cbTest.rows()")) >= 5, su)
            layout(p, "sample data 1920x1080")
            body = runner_view(p, "Gemini", "runner view sample data")
            check("runner view works on sample data with no vault", "fixed 14 contrast issues" in body and "No lessons recorded yet" in body, body)
            p.evaluate("window.__cbTest.overview()")
            p.wait_for_timeout(500)
            p.click(".ask-card button.accept")
            p.wait_for_timeout(900)
            check("sample data: Accept shows the effect and writes nothing", os.path.getsize(LEDGER) == 0 and not os.listdir(ACT))
            p.click("#sample-exit")
            p.wait_for_timeout(900)
            su = p.evaluate("window.__cbTest.setup()")
            check("first run: Exit returns to your own (empty) scoreboard", su["onboard"] and not su["sample"], su)
        check(tag + ": no script errors", not p.errs, p.errs[:2])
        p.close()


if __name__ == "__main__":
    sys.exit(main())
