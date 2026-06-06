"""Render NetAudit.icns from a Pillow-drawn base image.

Aesthetic: dark charcoal rounded square (~22% corner radius — matches Big Sur+
icon grid) with a vertical gradient + soft top sheen for depth, three concentric
Wi-Fi arcs in a green→teal gradient with a soft glow, and a green "verdict-safe"
checkmark badge at the signal source. Mirrors the UI: green = "this network is
safe", and the check echoes the plain-English safety verdict.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
SS = 4  # internal supersample factor for crisp, anti-aliased arcs

BG_TOP  = (32, 38, 46, 255)      # lifted charcoal (top of gradient)
BG_BOT  = (11, 13, 16, 255)      # var(--bg) #0b0d10 (bottom)
ACCENT  = (110, 231, 183, 255)   # var(--accent) #6ee7b7
TEAL    = (45, 212, 191, 255)    # cooler tail of the arc gradient

ICONSET = Path(__file__).parent / "NetAudit.iconset"
ICNS = Path(__file__).parent.parent / "NetAudit.icns"


def _vgrad(size, top, bot):
    """A vertical top→bottom linear gradient as an RGBA image."""
    col = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(4)))
    return col.resize((size, size))


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    return m


def _glow(size, xy, r, color, alpha):
    g = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse(
        (xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r), fill=color[:3] + (alpha,)
    )
    return g.filter(ImageFilter.GaussianBlur(r * 0.45))


def _base_bg(S, radius):
    bg = _vgrad(S, BG_TOP, BG_BOT).convert("RGBA")
    # Soft top sheen — a blurred bright ellipse, faded so there's no hard edge.
    sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse(
        (-S * 0.35, -S * 0.7, S * 1.35, S * 0.18), fill=(255, 255, 255, 22)
    )
    sheen = sheen.filter(ImageFilter.GaussianBlur(S * 0.06))
    bg = Image.alpha_composite(bg, sheen)
    bg.putalpha(_rounded_mask(S, radius))
    return bg


def _arc_layer(S, origin, radii, c_inner, c_outer):
    """Concentric Wi-Fi arcs, gradient-tinted from inner (warm) to outer (cool)."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    n = len(radii)
    for i, r in enumerate(radii):
        t = i / max(1, n - 1)  # 0 = outermost
        col = tuple(int(c_outer[j] + (c_inner[j] - c_outer[j]) * (1 - t)) for j in range(4))
        bbox = (origin[0] - r, origin[1] - r, origin[0] + r, origin[1] + r)
        width = max(int(S * 0.052 - i * S * 0.004), int(S * 0.03))
        d.arc(bbox, start=205, end=335, fill=col, width=width)
    return layer


def make_base(size: int) -> Image.Image:
    S = size * SS
    radius = int(S * 0.225)
    img = _base_bg(S, radius)

    origin = (S // 2, int(S * 0.72))

    # Green source glow behind the arcs.
    img = Image.alpha_composite(img, _glow(S, origin, int(S * 0.4), ACCENT, 70))

    # Wi-Fi arcs (green→teal) with a soft outer glow pass, then the crisp pass.
    arcs = _arc_layer(S, origin, [int(S * 0.46), int(S * 0.34), int(S * 0.22)], ACCENT, TEAL)
    img = Image.alpha_composite(img, arcs.filter(ImageFilter.GaussianBlur(S * 0.012)))
    img = Image.alpha_composite(img, arcs)

    # "Verdict: safe" check badge at the signal source.
    br = int(S * 0.085)
    d = ImageDraw.Draw(img)
    d.ellipse((origin[0] - br, origin[1] - br, origin[0] + br, origin[1] + br), fill=ACCENT)
    cw = int(S * 0.02)
    p1 = (origin[0] - br * 0.45, origin[1] + br * 0.02)
    p2 = (origin[0] - br * 0.08, origin[1] + br * 0.4)
    p3 = (origin[0] + br * 0.5, origin[1] - br * 0.38)
    d.line([p1, p2, p3], fill=BG_BOT, width=cw, joint="curve")

    return img.resize((size, size), Image.LANCZOS)


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
