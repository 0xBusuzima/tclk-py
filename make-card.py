# -*- coding: utf-8 -*-
"""Render the tweet card as a real 1600x900 PNG.

The browser pane caps screenshots at its own resolution, which is too soft for
a timeline image. Drawing it directly gives full control over the pixels.
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
F = "C:/Windows/Fonts/"

GROUND  = (15, 19, 23)
SURFACE = (23, 29, 35)
SUNK    = (27, 35, 42)
INK     = (230, 236, 242)
MUTED   = (141, 154, 168)
HAIR    = (42, 51, 60)
ACCENT  = (107, 169, 212)
SIGNAL  = (217, 128, 95)
OK      = (121, 189, 154)


def font(name, size):
    return ImageFont.truetype(F + name, size)


serif      = lambda s: font("georgia.ttf", s)
serif_it   = lambda s: font("georgiai.ttf", s)
sans       = lambda s: font("segoeui.ttf", s)
sans_b     = lambda s: font("segoeuib.ttf", s)
mono       = lambda s: font("consola.ttf", s)
mono_b     = lambda s: font("consolab.ttf", s)


img = Image.new("RGB", (W, H), GROUND)
d = ImageDraw.Draw(img)


def tracked(xy, text, fnt, fill, spacing=0):
    """Draw text with extra letter spacing, which Pillow has no setting for."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + spacing
    return x


def wrap(text, fnt, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if d.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


PAD = 72

# ---------------------------------------------------------------- eyebrow --
tracked((PAD, 58), "TCLK/1  ·  TECHNOCORE LOCK PROTOCOL", sans_b(16), MUTED, spacing=3.4)

# --------------------------------------------------------------- headline --
d.text((PAD - 4, 92), "Neither can", font=serif(78), fill=INK)
d.text((PAD - 4, 176), "go first.", font=serif_it(78), fill=ACCENT)

# ---------------------------------------------------------------- summary --
body = serif(25)
y = 288
for line in wrap(
        "One agent wants work done. The other wants paying. Pay first and the work "
        "may never arrive; work first and the payment may never arrive. A hash lock "
        "and a deadline settle it, over a room both already reach.",
        body, 840):
    d.text((PAD, y), line, font=body, fill=MUTED)
    y += 37

# ------------------------------------------------------------------ badge --
big = sans_b(58)
tw = d.textlength("4 / 4", font=big)
d.text((W - PAD - tw, 62), "4 / 4", font=big, fill=OK)
cap = sans_b(14)
label = "REFERENCE VECTORS PASS"
x_end = W - PAD
x = x_end - (d.textlength(label, font=cap) + 3.0 * (len(label) - 1))
tracked((x, 136), label, cap, MUTED, spacing=3.0)
for i, line in enumerate(("30 conformance tests", "zero dependencies")):
    m = mono(17)
    d.text((x_end - d.textlength(line, font=m), 168 + i * 27), line, font=m, fill=MUTED)

# ------------------------------------------------------- the five frames --
steps = [
    ("01", "offer",  "The payer states terms and two deadlines.", ACCENT),
    ("02", "accept", "The payee mints a secret, publishes only its hash.", ACCENT),
    ("03", "lock",   "The payer escrows, payable to whoever opens the hash.", ACCENT),
    ("04", "reveal", "Publishing the secret is the claim.", ACCENT),
    ("\u2022", "refund", "Or the deadline passes and the money goes back.", SIGNAL),
]
gap, top, box_h = 16, 470, 190
box_w = (W - 2 * PAD - gap * 4) / 5
for i, (n, verb, txt, colour) in enumerate(steps):
    x0 = PAD + i * (box_w + gap)
    d.rounded_rectangle([x0, top, x0 + box_w, top + box_h], 6, fill=SURFACE, outline=HAIR)
    d.rectangle([x0 + 1, top, x0 + box_w - 1, top + 3], fill=colour)
    d.text((x0 + 22, top + 24), n, font=mono(16), fill=MUTED)
    d.text((x0 + 22, top + 50), verb, font=mono_b(29), fill=colour)
    yy = top + 100
    for line in wrap(txt, serif(18), box_w - 44):
        d.text((x0 + 22, yy), line, font=serif(18), fill=INK)
        yy += 26

# --------------------------------------------------------- golden vector --
vy = top + box_h + 26
d.rounded_rectangle([PAD, vy, W - PAD, vy + 56], 6, fill=SUNK, outline=HAIR)
tracked((PAD + 22, vy + 21), "GOLDEN OFFER ID", sans_b(13), MUTED, spacing=2.6)
d.line([PAD + 190, vy + 14, PAD + 190, vy + 42], fill=HAIR)
d.text((PAD + 210, vy + 17),
       "0xd001fbbf4fa36d9ab8ea88df02a8b3303539e9d59f7ff9d9bfeb679318e9ce75",
       font=mono(19), fill=ACCENT)

# ----------------------------------------------------------------- footer --
fy = vy + 56 + 34
d.line([PAD, fy, W - PAD, fy], fill=HAIR)
d.text((PAD, fy + 24), "github.com/0xBusuzima/tclk-py", font=mono_b(25), fill=INK)
note = sans(15)
for i, line in enumerate((
        "An independent Python port. Protocol, spec and reference implementation by Flop Labs.",
        "Not affiliated. Protocol is alpha, testnet only.")):
    d.text((W - PAD - d.textlength(line, font=note), fy + 22 + i * 22),
           line, font=note, fill=MUTED)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tclk-py-card.png")
img.save(out, "PNG", optimize=True)
print("yazildi:", out, "%dx%d" % img.size, "%.0f KB" % (os.path.getsize(out) / 1024))
