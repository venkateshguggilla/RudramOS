#!/usr/bin/env python3
"""RudramOS branding: the trishul emblem (SVG + PNG), wallpapers, login and boot-menu images.

Needs Pillow. Run from the repo root:
    python3 tools/make-branding.py

The emblem is defined once below as vector paths; the SVG files and every PNG are drawn from
the same paths. The artwork (Shiva's eyes and the trishul) comes from the boot animation's
frames in system_files/usr/share/plymouth/themes/rudramos (see make-plymouth-frames.py).
"""
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYS = os.path.join(ROOT, "system_files")
ART = os.path.join(SYS, "usr/share/plymouth/themes/rudramos/frame-20.png")

CRIMSON = (224, 38, 44)
EMBER = (255, 92, 60)

# ---------------------------------------------------------------- Emblem geometry (512 x 512)
# Paths as SVG-like commands: ("M", x, y), ("L", x, y), ("C", x1, y1, x2, y2, x, y), ("Z",)


def mirror(path):
    out = []
    for cmd in path:
        if cmd[0] == "Z":
            out.append(cmd)
        else:
            vals = list(cmd[1:])
            for i in range(0, len(vals), 2):
                vals[i] = 512 - vals[i]
            out.append((cmd[0], *vals))
    return out


def circle(cx, cy, r):
    k = 0.5523 * r
    return [("M", cx + r, cy),
            ("C", cx + r, cy + k, cx + k, cy + r, cx, cy + r),
            ("C", cx - k, cy + r, cx - r, cy + k, cx - r, cy),
            ("C", cx - r, cy - k, cx - k, cy - r, cx, cy - r),
            ("C", cx + k, cy - r, cx + r, cy - k, cx + r, cy), ("Z",)]


BLADE = [("M", 256, 34), ("C", 272, 88, 284, 150, 277, 212), ("L", 268, 268), ("L", 244, 268),
         ("L", 235, 212), ("C", 228, 150, 240, 88, 256, 34), ("Z",)]
PRONG_L = [("M", 236, 288), ("C", 186, 292, 142, 268, 134, 220), ("C", 128, 182, 132, 132, 146, 82),
           ("C", 150, 130, 154, 178, 172, 210), ("C", 188, 240, 210, 256, 240, 262), ("Z",)]
PRONG_R = mirror(PRONG_L)
CROSSBAR = [("M", 186, 276), ("C", 220, 254, 292, 254, 326, 276), ("C", 292, 298, 220, 298, 186, 276), ("Z",)]
SHAFT = [("M", 247, 290), ("L", 265, 290), ("L", 262, 468), ("L", 256, 494), ("L", 250, 468), ("Z",)]
DAMARU = [("M", 222, 318), ("L", 290, 318), ("L", 264, 342), ("L", 290, 366), ("L", 222, 366),
          ("L", 248, 342), ("Z",)]
BINDU = circle(256, 276, 9)

SHAPES = [BLADE, PRONG_L, PRONG_R, CROSSBAR, SHAFT, DAMARU]  # BINDU is cut out of the crossbar


def to_polygons(path, scale=1.0, dx=0.0, dy=0.0, steps=24):
    polys, cur, pos = [], [], (0, 0)
    for cmd in path:
        op = cmd[0]
        if op == "M":
            if cur:
                polys.append(cur)
            pos = (cmd[1], cmd[2])
            cur = [pos]
        elif op == "L":
            pos = (cmd[1], cmd[2])
            cur.append(pos)
        elif op == "C":
            p0, p1, p2, p3 = pos, (cmd[1], cmd[2]), (cmd[3], cmd[4]), (cmd[5], cmd[6])
            for s in range(1, steps + 1):
                t = s / steps
                u = 1 - t
                cur.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
            pos = p3
        elif op == "Z":
            polys.append(cur)
            cur = []
    if cur:
        polys.append(cur)
    return [[(x * scale + dx, y * scale + dy) for x, y in p] for p in polys]


def svg_d(path):
    parts = []
    for cmd in path:
        parts.append(cmd[0] + " ".join(f"{v:g}" for v in cmd[1:]) if cmd[0] != "Z" else "Z")
    return " ".join(parts)


def emblem_svg(fill):
    d = " ".join(svg_d(p) for p in SHAPES)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n'
            f'  <path fill="{fill}" fill-rule="evenodd" d="{d} {svg_d(BINDU)}"/>\n</svg>\n')


def emblem_mask(size, margin=0.04):
    """The emblem as an anti-aliased mask, size x size (drawn 4x and scaled down)."""
    ss = 4
    big = size * ss
    scale = big * (1 - 2 * margin) / 512
    off = big * margin
    m = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(m)
    for shape in SHAPES:
        for poly in to_polygons(shape, scale, off, off):
            d.polygon(poly, fill=255)
    for poly in to_polygons(BINDU, scale, off, off):
        d.polygon(poly, fill=0)
    return m.resize((size, size), Image.LANCZOS)


def emblem(size, color=CRIMSON, glow=False):
    m = emblem_mask(size)
    img = Image.new("RGBA", (size, size), color + (0,))
    img.putalpha(m)
    if glow:
        halo = Image.new("RGBA", (size, size), EMBER + (0,))
        halo.putalpha(m.filter(ImageFilter.GaussianBlur(size / 40)).point(lambda a: int(a * 0.8)))
        img = Image.alpha_composite(halo, img)
    return img


# ---------------------------------------------------------------- Helpers

def vignette(w, h, strength=0.85):
    """Radial darkening towards the edges (L mask: 255 centre .. dark edges)."""
    small = Image.new("L", (256, 144))
    px = small.load()
    for y in range(144):
        for x in range(256):
            dx, dy = (x - 127.5) / 128, (y - 71.5) / 72
            r = min(1.0, math.sqrt(dx * dx + dy * dy) / 1.25)
            px[x, y] = int(255 * (1 - strength * r ** 2.2))
    return small.resize((w, h), Image.BICUBIC)


def art_on_black(w, h, art_height, y_shift=0.0, brightness=1.0):
    art = Image.open(ART).convert("RGB")
    scale = art_height / art.height
    a = art.resize((int(art.width * scale), int(art.height * scale)), Image.LANCZOS)
    a = a.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    if brightness != 1.0:
        a = a.point(lambda v: int(v * brightness))
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(a, ((w - a.width) // 2, int((h - a.height) / 2 + h * y_shift)))
    return canvas


def save(img, rel, **kw):
    path = os.path.join(SYS, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, **kw)
    print(f"{rel}  {os.path.getsize(path) / 1024:.0f} KB")


def write(rel, text):
    path = os.path.join(SYS, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(rel)


# ---------------------------------------------------------------- Outputs

def make_logo():
    write("usr/share/icons/hicolor/scalable/apps/rudramos-logo.svg", emblem_svg("#e0262c"))
    write("usr/share/icons/hicolor/symbolic/apps/rudramos-logo-symbolic.svg", emblem_svg("#bebebe"))
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        save(emblem(s), f"usr/share/icons/hicolor/{s}x{s}/apps/rudramos-logo.png", optimize=True)
    save(emblem(256, glow=True), "usr/share/pixmaps/rudramos-logo.png", optimize=True)
    # Login screen logo, shown under the user list (GDM draws it at its own size)
    save(emblem(64, color=(232, 230, 234), glow=True), "usr/share/pixmaps/rudramos-gdm-logo.png", optimize=True)
    # Top-bar menu icon (white, the shell tints nothing on its own)
    write("usr/share/pixmaps/rudramos-logo-white.svg", emblem_svg("#ffffff"))


def make_wallpapers():
    w, h = 3840, 2160
    # Default: the artwork large on black, edges falling into darkness
    art = art_on_black(w, h, art_height=int(h * 0.92), y_shift=0.0)
    art = Image.composite(art, Image.new("RGB", (w, h)), vignette(w, h, 0.55))
    save(art, "usr/share/backgrounds/rudramos/rudramos-trishul.jpg", quality=92, optimize=True)

    # Emblem: crisp vector trishul glowing on a deep red-black gradient with embers
    bg = Image.new("RGB", (w, h))
    px = bg.load()
    grad = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        grad.putpixel((0, y), (int(10 + 26 * t), int(4 + 2 * t), int(6 + 2 * t)))
    bg = grad.resize((w, h), Image.BICUBIC)
    glow = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((w * 0.3, h * 0.2, w * 0.7, h * 0.95), fill=(64, 6, 9))
    glow = glow.filter(ImageFilter.GaussianBlur(h * 0.18))
    bg = ImageChops.add(bg, glow)
    import random
    rnd = random.Random(7)
    sparks = Image.new("RGB", (w, h))
    sd = ImageDraw.Draw(sparks)
    for _ in range(220):
        x, y = rnd.uniform(0, w), rnd.uniform(h * 0.2, h)
        r = rnd.uniform(1.5, 5.5)
        c = rnd.choice([(255, 70, 40), (255, 120, 60), (220, 30, 30)])
        sd.ellipse((x - r, y - r, x + r, y + r), fill=c)
    bg = ImageChops.add(bg, sparks.filter(ImageFilter.GaussianBlur(1.6)))
    size = int(h * 0.62)
    e = emblem(size, color=(232, 230, 234), glow=True)  # silver, like the trishul in the art
    bg = bg.convert("RGBA")
    bg.alpha_composite(e, ((w - size) // 2, int(h * 0.17)))
    bg = Image.composite(bg.convert("RGB"), Image.new("RGB", (w, h)), vignette(w, h, 0.5))
    save(bg, "usr/share/backgrounds/rudramos/rudramos-emblem.jpg", quality=92, optimize=True)

    write("usr/share/gnome-background-properties/rudramos.xml", """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">
<wallpapers>
  <wallpaper deleted="false">
    <name>RudramOS Trishul</name>
    <filename>/usr/share/backgrounds/rudramos/rudramos-trishul.jpg</filename>
    <filename-dark>/usr/share/backgrounds/rudramos/rudramos-trishul.jpg</filename-dark>
    <options>zoom</options>
    <shade_type>solid</shade_type>
    <pcolor>#000000</pcolor>
    <scolor>#000000</scolor>
  </wallpaper>
  <wallpaper deleted="false">
    <name>RudramOS Emblem</name>
    <filename>/usr/share/backgrounds/rudramos/rudramos-emblem.jpg</filename>
    <filename-dark>/usr/share/backgrounds/rudramos/rudramos-emblem.jpg</filename-dark>
    <options>zoom</options>
    <shade_type>solid</shade_type>
    <pcolor>#0a0406</pcolor>
    <scolor>#0a0406</scolor>
  </wallpaper>
</wallpapers>
""")


def make_grub():
    """Boot menu background (1920x1080): the art dimmed, room for the menu below it."""
    w, h = 1920, 1080
    bg = art_on_black(w, h, art_height=int(h * 0.62), y_shift=-0.13, brightness=0.55)
    bg = Image.composite(bg, Image.new("RGB", (w, h)), vignette(w, h, 0.6))
    save(bg, "usr/share/pcos/grub/rudramos/background.png", optimize=True)
    for name, fill, border in (("select", (90, 10, 14, 230), (224, 38, 44, 255)),
                               ("menu", (8, 4, 6, 170), (70, 18, 20, 255))):
        # 9-slice box pieces: GRUB stretches the _c (centre) and edge images
        ss = 3
        size = 24 * ss
        box = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(box).rounded_rectangle((ss, ss, size - ss, size - ss), radius=8 * ss,
                                              fill=fill, outline=border, width=2 * ss)
        box = box.resize((24, 24), Image.LANCZOS)
        cut = {"nw": (0, 0, 8, 8), "n": (8, 0, 16, 8), "ne": (16, 0, 24, 8),
               "w": (0, 8, 8, 16), "c": (8, 8, 16, 16), "e": (16, 8, 24, 16),
               "sw": (0, 16, 8, 24), "s": (8, 16, 16, 24), "se": (16, 16, 24, 24)}
        for k, r in cut.items():
            save(box.crop(r), f"usr/share/pcos/grub/rudramos/{name}_{k}.png")
    save(emblem(48), "usr/share/pcos/grub/rudramos/logo.png", optimize=True)


if __name__ == "__main__":
    what = sys.argv[1:] or ["logo", "wallpapers", "grub"]
    if "logo" in what:
        make_logo()
    if "wallpapers" in what:
        make_wallpapers()
    if "grub" in what:
        make_grub()
