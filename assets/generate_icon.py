"""Render NetAudit.icns from a Pillow-drawn 1024x1024 base image.

Aesthetic: dark charcoal rounded square (~22% corner radius — matches Big Sur+
icon grid) with three concentric Wi-Fi arcs in the app's accent green, plus a
small status dot at origin. Mirrors the UI: green = "this network is safe".
"""
from pathlib import Path
from PIL import Image, ImageDraw

SIZE = 1024
BG = (20, 23, 28, 255)          # var(--panel) #14171c
BG_DEEP = (11, 13, 16, 255)     # var(--bg) #0b0d10
ACCENT = (110, 231, 183, 255)   # var(--accent) #6ee7b7
WHITE = (240, 245, 247, 255)

ICONSET = Path(__file__).parent / "NetAudit.iconset"
ICNS = Path(__file__).parent.parent / "NetAudit.icns"


def make_base(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # Subtle vertical gradient bg via two stacked rounded rectangles
    radius = int(size * 0.225)
    d.rounded_rectangle((0, 0, size, size), radius=radius, fill=BG)
    # Darker bottom half overlay for depth
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay, "RGBA")
    od.rounded_rectangle(
        (0, size // 2, size, size), radius=0, fill=(0, 0, 0, 35)
    )
    img = Image.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img, "RGBA")

    # Three Wi-Fi arcs (concentric, bottom-anchored), emanating from a dot.
    origin = (size // 2, int(size * 0.74))
    arc_color = ACCENT
    # Outermost → innermost
    for i, r in enumerate([int(size * 0.46), int(size * 0.34), int(size * 0.22)]):
        bbox = (origin[0] - r, origin[1] - r, origin[0] + r, origin[1] + r)
        # PIL arc angles: 0 = 3 o'clock, sweeping clockwise. Top arc = 180..360.
        # We want an arc covering ~140° centered on top (270°), so 200°..340°.
        width = max(28, int(size * (0.045 - i * 0.005)))
        d.arc(bbox, start=200, end=340, fill=arc_color, width=width)

    # Center dot at the origin
    dot_r = int(size * 0.038)
    d.ellipse(
        (origin[0] - dot_r, origin[1] - dot_r, origin[0] + dot_r, origin[1] + dot_r),
        fill=arc_color,
    )

    return img


def main():
    ICONSET.mkdir(exist_ok=True)
    base = make_base(SIZE)
    base.save(ICONSET / "icon_512x512@2x.png")

    # All the sizes Apple wants in an .iconset
    targets = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        # 1024 (icon_512x512@2x.png) already saved above
    ]
    for size, name in targets:
        base.resize((size, size), Image.LANCZOS).save(ICONSET / name)

    print(f"✅ Wrote {len(targets) + 1} PNGs to {ICONSET.name}/")


if __name__ == "__main__":
    main()
