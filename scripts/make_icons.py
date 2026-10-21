"""Draw the app icon and logo (needs Pillow, which is not a dependency of the app).

    python3 scripts/make_icons.py

Writes voice_assist_improver/icon.png (square) and logo.png (wide) for the Home Assistant app store.
An original, simple drawing: a microphone with a small spark.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "voice_assist_improver"
SCALE = 4  # draw big, shrink for smooth edges
TOP, BOTTOM = (59, 130, 246), (30, 64, 175)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM, strict=True))
        for x in range(size):
            px[x, y] = row
    return img


def spark(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color) -> None:
    """A four-point star."""
    pts = []
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.28
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    d.polygon(pts, fill=color)


def icon(size: int = 512) -> Image.Image:
    big = size * SCALE
    img = gradient(big)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=big // 5, fill=255)
    d = ImageDraw.Draw(img)
    white = (255, 255, 255)
    u = big / 100
    # capsule
    d.rounded_rectangle((38 * u, 18 * u, 62 * u, 56 * u), radius=12 * u, fill=white)
    # holder arc
    d.arc((28 * u, 34 * u, 72 * u, 72 * u), start=0, end=180, fill=white, width=int(4.5 * u))
    # stem and base
    d.rectangle((48 * u, 72 * u, 52 * u, 82 * u), fill=white)
    d.rounded_rectangle((38 * u, 81 * u, 62 * u, 86 * u), radius=2.5 * u, fill=white)
    # spark
    spark(d, 76 * u, 26 * u, 12 * u, (253, 224, 71))
    spark(d, 24 * u, 40 * u, 5.5 * u, (253, 224, 71))
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


def logo(height: int = 192) -> Image.Image:
    mark = icon(height)
    font = ImageFont.truetype(FONT, int(height * 0.27))
    lines = ("Voice Assist", "Improver")
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width = max(probe.textlength(line, font=font) for line in lines)
    canvas = Image.new("RGBA", (int(height + height * 0.18 + width + 8), height), (0, 0, 0, 0))
    canvas.paste(mark, (0, 0), mark)
    d = ImageDraw.Draw(canvas)
    y = height * 0.5 - font.size * 1.15
    for line in lines:
        d.text((height + height * 0.18, y), line, font=font, fill=(37, 99, 235))
        y += font.size * 1.25
    return canvas


if __name__ == "__main__":
    icon(256).save(OUT / "icon.png", optimize=True)
    logo().save(OUT / "logo.png", optimize=True)
    print("wrote icon.png and logo.png")
