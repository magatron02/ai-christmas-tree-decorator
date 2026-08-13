"""Generate frontend/icon.ico — the app's only icon, used as both the favicon and the
Desktop shortcut's icon (setup.bat).

    python scripts/make_icon.py

A plain geometric tree, not a photo or a font glyph: it has to read at 16px. Colours are the
three from tokens.css (DESIGN.md), not re-picked here — --fill-primary for the ground,
--fill-gold-block for the tree, --surface-0 for the star, so the icon stays in sync if the
palette ever changes.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "icon.ico"

WINE = (0x7A, 0x2E, 0x2E)
GOLD = (0xB0, 0x8D, 0x57)
CREAM = (0xF7, 0xF1, 0xE8)

SIZE = 256  # drawn once at full size; Pillow downsamples for the smaller ICO frames


def draw():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    pad = 10
    draw.rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad], radius=48, fill=WINE)

    cx = SIZE // 2
    tiers = [
        (0.30, 0.46, 0.62),
        (0.42, 0.60, 0.76),
        (0.54, 0.74, 0.90),
    ]
    for top_frac, bottom_frac, half_width_frac in tiers:
        top = SIZE * top_frac
        bottom = SIZE * bottom_frac
        half = SIZE * half_width_frac / 2
        draw.polygon([(cx, top), (cx - half, bottom), (cx + half, bottom)], fill=GOLD)

    trunk_w = SIZE * 0.10
    draw.rectangle(
        [cx - trunk_w / 2, SIZE * 0.90, cx + trunk_w / 2, SIZE * 0.96], fill=GOLD
    )

    star = SIZE * 0.05
    draw.ellipse([cx - star, SIZE * 0.24 - star, cx + star, SIZE * 0.24 + star], fill=CREAM)

    return image


def main():
    image = draw()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
