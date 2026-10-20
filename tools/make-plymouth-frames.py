#!/usr/bin/env python3
# Builds the RudramOS boot animation frames from an animated GIF (needs Pillow):
#   python3 tools/make-plymouth-frames.py animation.gif system_files/usr/share/plymouth/themes/rudramos
# The script in that folder (rudramos.script) expects 40 frames at 70 ms; change FRAMES and
# TICKS_PER_FRAME there if a new animation has a different count or speed.
# GIF -> Plymouth frames: edges feathered into black (no visible rectangle on a black screen),
# then 8-bit PNGs sharing one palette (small initramfs, no colour flicker between frames).
import sys, os
from PIL import Image, ImageChops
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
gif = Image.open(src)
w, h = gif.size

def edge_mask(w, h, left=70, right=70, top=50, bottom=90):
    m = Image.new("L", (w, h), 0)
    px = m.load()
    def ramp(d, fade):
        t = max(0.0, min(1.0, d / fade))
        return t * t * (3 - 2 * t)  # smoothstep
    for y in range(h):
        vy = min(ramp(y, top), ramp(h - 1 - y, bottom))
        for x in range(w):
            px[x, y] = int(255 * min(vy, ramp(x, left), ramp(w - 1 - x, right)))
    return m

mask = edge_mask(w, h)
black = Image.new("RGB", (w, h), (0, 0, 0))
frames = []
for i in range(gif.n_frames):
    gif.seek(i)
    rgb = gif.convert("RGB")
    frames.append(Image.composite(rgb, black, mask))

# One palette for all frames, from a strip of every 8th frame
sample = Image.new("RGB", (w, h * 5))
for k, i in enumerate(range(0, len(frames), 8)):
    sample.paste(frames[i], (0, h * k))
palette = sample.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
total = 0
for i, f in enumerate(frames):
    q = f.quantize(palette=palette, dither=Image.Dither.NONE)
    path = os.path.join(out, f"frame-{i}.png")
    q.save(path, optimize=True)
    total += os.path.getsize(path)
print(f"{len(frames)} frames {w}x{h}, {total/1e6:.1f} MB total")
