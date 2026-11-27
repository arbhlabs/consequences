"""Generate consequences.ico for Consequences Brain v2 ("Quiet Constellation").

Dark tile, one brass leader circle, satellites in brass / rose, hairline links.
Each size is drawn from its own 8x supersampled master; 16-24 px use a simplified mark.
Reproducible: python gen_icon.py -> consequences.ico (16..256 px) + consequences-preview.png
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

APP = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(APP, "consequences.ico")
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

BG_TOP, BG_BOT = (22, 26, 32), (9, 11, 14)
EDGE = (60, 66, 76)
BRASS = (217, 182, 108)
BRASS_DEEP = (120, 98, 54)
ROSE = (199, 143, 137)
LINE = (120, 112, 96)


def tile(S):
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / (S - 1)
        d.line([(0, y), (S, y)], fill=tuple(round(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
    # warm glow behind the leader
    glow = Image.new("RGB", (S, S), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy, r = S * 0.44, S * 0.46, S * 0.42
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(70, 56, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.12))
    return Image.blend(img, Image.composite(glow, img, glow.convert("L").point(lambda v: 255 if v else 0)), 0.55)


def mask(S, inset=0):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle([inset, inset, S - 1 - inset, S - 1 - inset], radius=S * 0.22, fill=255)
    return m


def render(px):
    S = px * 8
    simple = px <= 24
    base = tile(S).convert("RGBA")
    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    lead = (S * 0.43, S * 0.47)
    lr = S * (0.25 if simple else 0.21)
    if simple:
        sats = [((S * 0.78, S * 0.24), S * 0.10, BRASS)]
    else:
        sats = []
        for ang, rr, col in ((-38, 0.075, BRASS), (28, 0.058, ROSE), (118, 0.050, BRASS), (205, 0.042, ROSE)):
            a = math.radians(ang)
            dist = S * 0.36
            sats.append(((lead[0] + dist * math.cos(a), lead[1] + dist * math.sin(a)), S * rr, col))
    lw = max(1, int(S * (0.03 if simple else 0.014)))
    for (p, r, col) in sats:
        d.line([lead, p], fill=LINE + (200,), width=lw)
    # leader: soft brass fill + crisp ring (same language as the score map)
    d.ellipse([lead[0] - lr, lead[1] - lr, lead[0] + lr, lead[1] + lr], fill=BRASS_DEEP + (255,))
    ring_w = max(2, int(S * (0.06 if simple else 0.035)))
    d.ellipse([lead[0] - lr, lead[1] - lr, lead[0] + lr, lead[1] + lr], outline=BRASS + (255,), width=ring_w)
    core = lr * 0.38
    d.ellipse([lead[0] - core, lead[1] - core, lead[0] + core, lead[1] + core], fill=BRASS + (255,))
    for (p, r, col) in sats:
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col + (255,))
    if not simple:
        d.rounded_rectangle([S * 0.012, S * 0.012, S * 0.988, S * 0.988], radius=S * 0.22,
                            outline=EDGE + (220,), width=max(2, S // 160))
    out = Image.alpha_composite(base, lay)
    out.putalpha(mask(S))
    return out.resize((px, px), Image.LANCZOS)


def main():
    frames = {px: render(px) for px in SIZES}
    big = frames[256]
    big.save(OUT, format="ICO", sizes=[(p, p) for p in SIZES],
             append_images=[frames[p] for p in SIZES if p != 256])
    big.save(os.path.join(APP, "consequences-preview.png"))
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
