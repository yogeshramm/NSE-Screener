#!/usr/bin/env python3
"""
Generate MONEYSTX app icon for Electron.
Draws the MX monogram (M + arrow) in #FF8C00 on #050505 obsidian with
rounded corners, then converts to .icns via macOS iconutil.
Run: python3 create_icon.py
"""
import os, shutil, math
from pathlib import Path
from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Background: rounded rectangle ────────────────────────────────
    radius = max(4, int(size * 0.18))
    draw.rounded_rectangle([0, 0, size - 1, size - 1],
                           radius=radius, fill="#050505")

    # ── MX logo — SVG viewBox is 0 0 64 64 ───────────────────────────
    # M path: M14 48 V20 L24 36 L34 20 V48
    # X half: M40 48 V20 L50 36
    # stroke-width 4, stroke-linecap round, stroke-linejoin round
    def p(x, y):
        """Scale SVG coord (0-64) to pixel."""
        return (x * size / 64, y * size / 64)

    orange = "#FF8C00"
    sw = max(2, int(size * 4 / 64))   # stroke width proportional to size

    m_path = [p(14,48), p(14,20), p(24,36), p(34,20), p(34,48)]
    x_path = [p(40,48), p(40,20), p(50,36)]

    def draw_polyline(pts, colour, width):
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i+1]], fill=colour, width=width)
        # Round caps at each vertex
        r = width / 2
        for px, py in pts:
            draw.ellipse([px-r, py-r, px+r, py+r], fill=colour)

    draw_polyline(m_path, orange, sw)
    draw_polyline(x_path, orange, sw)

    return img


def make_iconset(base: Image.Image, out_dir: Path) -> Path:
    iconset = out_dir / "icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for sz in sizes:
        icon = base.resize((sz, sz), Image.LANCZOS)
        icon.save(str(iconset / f"icon_{sz}x{sz}.png"))
        if sz <= 512:
            icon2 = base.resize((sz*2, sz*2), Image.LANCZOS)
            icon2.save(str(iconset / f"icon_{sz}x{sz}@2x.png"))
    return iconset


if __name__ == "__main__":
    assets = Path(__file__).parent / "assets"
    assets.mkdir(exist_ok=True)

    print("Rendering icon at 1024×1024…")
    base = draw_icon(1024)
    png_path = assets / "icon.png"
    base.save(str(png_path))
    print(f"  Saved {png_path}")

    print("Building iconset…")
    iconset = make_iconset(base, assets)

    icns_path = assets / "icon.icns"
    print("Running iconutil…")
    ret = os.system(f'iconutil -c icns "{iconset}" -o "{icns_path}"')
    if ret == 0:
        print(f"  Saved {icns_path}")
    else:
        print("  iconutil failed — .icns not created")

    shutil.rmtree(str(iconset))
    print("Done.")
