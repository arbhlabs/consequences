"""Consequences Brain learner: the referee's judgement, learned from the owner's own awards and kept readable.

Every finished turn the owner reacted to with points is a labelled case (cb_evidence). The scorer is additive, so
every verdict can list what drove it: a bias plus one weight per evidence feature gives the chance the owner would
call the turn a plus; the size comes from the most similar past cases. It improves itself without anyone asking:
  1. train a candidate on all but the newest 30 % of cases (time order, so it never peeks at the future);
  2. replay the held-out newest cases with both the current version and the candidate;
  3. adopt the candidate only if it is at least as right AND makes no more false deductions; keep every version;
  4. roll back by itself if live verdicts later agree with the owner much less than the backtest promised.
What it can never learn or loosen: the integrity limits and caps (cb_auto), which live outside the profile.
A fresh install starts from NEUTRAL below and learns only from its own owner's data, kept in local app data.
"""
import hashlib
import json
import math
import os
import time

import cb_evidence

LIMIT = 50
HOLDOUT = 0.30
MIN_CASES = 12             # fewer labelled cases than this: keep the neutral rules, say "learning"
K = 7                      # similar past cases used for the size and shown as reasons
CONFIDENT = 0.70           # below this chance either way the referee asks instead of guessing

# Neutral starting rules, the same for every install: proof helps, failures and extra work for the owner hurt.
NEUTRAL = {"version": 0, "bias": 0.0, "weights": {
    "tests_pass": 1.0, "tests_fail": -0.8, "tool_errors": -0.3, "commits": 0.4, "screen_checks": 0.6,
    "device_checks": 0.3, "edits": 0.1, "handed_to_owner": -1.0, "rework_before": -0.8, "asked_pos": 0.2,
    "asked_big": -0.3, "long_turn": -0.2, "recent_plus": 0.5, "recent_minus": -0.5}, "size": {"pos": 5, "neg": -5}, "cases": [], "metrics": None,
    "n": 0, "note": "neutral starting rules"}

WORDS = {"tests_pass": "tests passed", "tests_fail": "tests failed", "tool_errors": "tool errors", "commits": "committed",
         "screen_checks": "looked at the screen", "device_checks": "checked on the device", "edits": "edited files",
         "handed_to_owner": "handed the owner steps to do", "rework_before": "owner was already unhappy",
         "asked_pos": "asked for points", "asked_big": "asked for 20+", "long_turn": "took over 30 min",
         "recent_plus": "owner gave plus lately", "recent_minus": "owner gave minus lately"}


def _jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sig(z):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def _clamp(n):
    return max(-LIMIT, min(LIMIT, int(round(n))))


def examples_from(sessions):
    """[(time, features, points, short context)] for every turn the owner put a number on."""
    out = []
    for turns in sessions.values():
        for t in turns:
            lab = t.get("label") or {}
            if lab.get("points") is None or not lab["points"] or not t.get("end"):
                continue
            out.append({"t": t["end"], "x": cb_evidence.features(t), "y": _clamp(lab["points"]),
                        "said": (lab.get("said") or "")[:90], "model": t.get("model", ""), "session": t.get("session", "")})
    out.sort(key=lambda e: e["t"])
    return out


def _dist(a, b):
    return math.sqrt(sum((a.get(k, 0) - b.get(k, 0)) ** 2 for k in cb_evidence.FEATURES))


def predict(profile, x):
    """{points, p_plus, confident, drivers[(feature words, contribution)], similar[cases]} for one turn's features."""
    w, b = profile["weights"], profile["bias"]
    contrib = [(k, w.get(k, 0.0) * x.get(k, 0.0)) for k in cb_evidence.FEATURES]
    p = _sig(b + sum(c for _, c in contrib))
    sign = 1 if p >= 0.5 else -1
    near = sorted(profile.get("cases") or [], key=lambda c: _dist(c["x"], x))[:K]
    same = sorted(c["y"] for c in near if (c["y"] > 0) == (sign > 0))
    size = same[len(same) // 2] if same else profile["size"]["pos" if sign > 0 else "neg"]
    drivers = sorted([(WORDS[k], round(c, 2)) for k, c in contrib if abs(c) >= 0.05], key=lambda d: -abs(d[1]))[:4]
    return {"points": _clamp(size), "p_plus": round(p, 3), "confident": max(p, 1 - p) >= CONFIDENT,
            "drivers": drivers, "similar": [{"y": c["y"], "said": c.get("said", "")} for c in near[:3]]}


def train(cases, prior):
    """Logistic regression on the sign, pulled toward the prior weights (so few cases cannot swing it wildly)."""
    w = dict(prior["weights"])
    b = prior["bias"]
    lam, lr = 0.15, 0.4
    data = [(c["x"], 1.0 if c["y"] > 0 else 0.0) for c in cases if c["y"]]
    for _ in range(400):
        gw = {k: 0.0 for k in w}
        gb = 0.0
        for x, y in data:
            e = _sig(b + sum(w[k] * x.get(k, 0.0) for k in w)) - y
            gb += e
            for k in w:
                gw[k] += e * x.get(k, 0.0)
        n = max(1, len(data))
        b -= lr * gb / n
        for k in w:
            w[k] -= lr * (gw[k] / n + lam * (w[k] - prior["weights"][k]))
    pos = sorted(c["y"] for c in cases if c["y"] > 0)
    neg = sorted(c["y"] for c in cases if c["y"] < 0)
    return {"version": prior.get("version", 0), "bias": round(b, 4), "weights": {k: round(v, 4) for k, v in w.items()},
            "size": {"pos": pos[len(pos) // 2] if pos else 5, "neg": neg[len(neg) // 2] if neg else -5},
            "cases": [{"x": c["x"], "y": c["y"], "said": c.get("said", ""), "t": c["t"]} for c in cases][-400:],
            "n": len(cases), "metrics": None}


def evaluate(profile, cases):
    """Replay held-out cases: sign accuracy, size error, false deductions, and the same on confident calls only."""
    n = ok = fd = 0
    err = 0.0
    cn = cok = cfd = 0
    for c in cases:
        if not c["y"]:
            continue
        v = predict(profile, c["x"])
        n += 1
        right = (v["points"] > 0) == (c["y"] > 0)
        ok += right
        err += abs(v["points"] - c["y"])
        false_ded = v["points"] < 0 < c["y"]
        fd += false_ded
        if v["confident"]:
            cn += 1
            cok += right
            cfd += false_ded
    pos = sum(1 for c in cases if c["y"] > 0)
    base = max(pos, n - pos) / n if n else 0.0
    return {"n": n, "sign_acc": round(ok / n, 3) if n else 0.0, "size_err": round(err / n, 1) if n else 0.0,
            "false_deductions": fd, "false_ded_rate": round(fd / n, 3) if n else 0.0, "majority_baseline": round(base, 3),
            "confident_n": cn, "confident_acc": round(cok / cn, 3) if cn else 0.0, "confident_false_ded": cfd,
            "coverage": round(cn / n, 3) if n else 0.0}


def autonomy_ok(m):
    """The bar for paying without the owner: clearly better than guessing, nearly always right when it is sure,
    and no false deductions on confident calls. Never learned, never loosened by the learner."""
    return bool(m and m["n"] >= 15 and m["confident_n"] >= 8 and m["confident_acc"] >= 0.8
                and m["confident_false_ded"] == 0 and m["sign_acc"] >= m["majority_baseline"] + 0.1)


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


class Store:
    """Profile versions in local app data: profile.json (current), versions/vN.json, learn_log.jsonl."""

    def __init__(self, folder):
        self.dir = folder
        os.makedirs(os.path.join(folder, "versions"), exist_ok=True)
        self.path = os.path.join(folder, "profile.json")
        self.log = os.path.join(folder, "learn_log.jsonl")

    def _write(self, path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)

    def versions(self):
        out = []
        for name in os.listdir(os.path.join(self.dir, "versions")):
            if name.startswith("v") and name.endswith(".json"):
                try:
                    out.append(int(name[1:-5]))
                except ValueError:
                    pass
        return sorted(out)

    def load(self):
        """(profile, status). status 'ok', 'neutral' or 'tampered': a profile.json that is not one of the learner's
        own saved versions is ignored (neutral rules are used) and the window says so."""
        try:
            prof = _jload(self.path)
        except (OSError, ValueError):
            return dict(NEUTRAL), "neutral"
        try:
            saved = _jload(os.path.join(self.dir, "versions", "v%d.json" % prof.get("version", -1)))
        except (OSError, ValueError):
            return dict(NEUTRAL), "tampered"
        return (prof, "ok") if _sha(saved) == _sha(prof) else (dict(NEUTRAL), "tampered")

    def save(self, prof, entry):
        vs = self.versions()
        prof = dict(prof, version=(vs[-1] + 1) if vs else 1, saved=time.time())
        self._write(os.path.join(self.dir, "versions", "v%d.json" % prof["version"]), prof)
        self._write(self.path, prof)
        self.note(dict(entry, version=prof["version"]))
        return prof

    def note(self, entry):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(entry, at=time.time())) + "\n")

    def notes(self, n=8):
        try:
            with open(self.log, encoding="utf-8") as f:
                lines = f.read().splitlines()[-n:]
        except OSError:
            return []
        out = []
        for l in lines:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
        return out

    def rollback(self, why):
        cur, _ = self.load()
        vs = [v for v in self.versions() if v < cur.get("version", 0)]
        if not vs:
            return None
        prev = _jload(os.path.join(self.dir, "versions", "v%d.json" % vs[-1]))
        self._write(self.path, prev)
        self.note({"kind": "rollback", "from": cur.get("version"), "to": prev["version"], "text": why})
        return prev


def _changes(old, new):
    d = sorted(((k, new["weights"][k] - old["weights"].get(k, 0.0)) for k in new["weights"]), key=lambda kv: -abs(kv[1]))
    return ["%s %s" % (WORDS[k], "counts more" if v > 0 else "counts less") for k, v in d[:3] if abs(v) >= 0.05]


def improve(store, cases):
    """One self-improvement step. Returns the log entry (adopted or not). Safe to call often: it only adopts
    a candidate that wins the held-out replay."""
    cur, status = store.load()
    if len(cases) < MIN_CASES:
        return {"kind": "skip", "text": "Learning: %d of %d labelled cases needed." % (len(cases), MIN_CASES), "n": len(cases)}
    cut = max(1, int(len(cases) * (1 - HOLDOUT)))
    train_part, held = cases[:cut], cases[cut:]
    base = cur if status == "ok" else NEUTRAL
    cand = train(train_part, base)
    before, after = evaluate(base, held), evaluate(cand, held)
    better = (after["sign_acc"] > before["sign_acc"] or after["size_err"] < before["size_err"]) \
        and after["sign_acc"] >= before["sign_acc"] and after["false_deductions"] <= before["false_deductions"]
    if not better:
        if not cur.get("metrics"):   # first run and the retrain lost: keep the neutral rules, but record how they score
            keep = dict(base, metrics=dict(before, neutral=before), n=len(cases), cases=train(cases, base)["cases"])
            keep["autonomy_ok"] = autonomy_ok(before)
            text = "Kept the neutral rules: a retrain on %d cases was not better on the %d newest (%d%% vs %d%% right)." % (
                len(train_part), len(held), after["sign_acc"] * 100, before["sign_acc"] * 100)
            store.save(dict(keep, weights=dict(base["weights"]), bias=base["bias"]), {"kind": "kept", "text": text, "n": len(cases), "before": before, "after": after})
            return {"kind": "kept", "text": text}
        return {"kind": "kept", "n": len(cases), "held": len(held), "before": before, "after": after,
                "text": "Kept version %d: a retrain on %d cases did not beat it on the %d newest (%d%% vs %d%% right)." % (
                    cur.get("version", 0), len(train_part), len(held), after["sign_acc"] * 100, before["sign_acc"] * 100)}
    final = train(cases, base)
    final["metrics"] = after if better else evaluate(final, held)
    final["metrics"]["neutral"] = evaluate(NEUTRAL, held)
    final["autonomy_ok"] = autonomy_ok(final["metrics"])
    m = final["metrics"]
    text = "Learned from %d cases: %s. On the %d newest it was right %d%% of the time (before %d%%), size off by %s, " \
           "%d false deductions." % (len(cases), ", ".join(_changes(base, final)) or "small tweaks", m["n"],
                                     m["sign_acc"] * 100, before["sign_acc"] * 100, m["size_err"], m["false_deductions"])
    return {"kind": "adopted", "profile": store.save(final, {"kind": "adopted", "text": text, "n": len(cases),
                                                            "before": before, "after": m}), "text": text}


def live_check(store, outcomes):
    """outcomes: [(version, referee points, owner points)] for verdicts the owner later answered. If the current
    version's last 8+ live calls agree with him far less than its backtest promised, roll back by itself."""
    cur, status = store.load()
    mine = [o for o in outcomes if o[0] == cur.get("version") and o[1] and o[2]][-12:]
    if status != "ok" or len(mine) < 8 or not cur.get("metrics"):
        return None
    acc = sum((a > 0) == (b > 0) for _, a, b in mine) / len(mine)
    if acc < cur["metrics"]["sign_acc"] - 0.2:
        return store.rollback("Live results dropped: %d%% right on the last %d calls vs %d%% in the backtest." % (
            acc * 100, len(mine), cur["metrics"]["sign_acc"] * 100))
    return None
