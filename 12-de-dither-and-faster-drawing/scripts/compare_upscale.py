#!/usr/bin/env python3
"""Usage: python scripts/compare_upscale.py

Draws the field scene in the emulator at each 1080p30 picture size (960x540 for x2 down to 274x154 for x7) and scales
each to the 1080p screen as the builds do, with the edge-directed scaler alone ("edge") and with de-dither in front of
it ("edge_dd"). Each result is scored against a reference: the same triangles drawn straight at screen size in full
colour, which is what a GPU with enough memory and time for true 1080p would show.

Prints the scores and saves two pictures in docs/images: upscale_x2_to_x7.png (the same crop at every scale, with
de-dither) and upscale_dedither.png (without, with, and the reference, at three scales).
Each size runs in its own Python, because the picture size is fixed at import.
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sw.dtgc import upscale  # noqa: E402

SIZES = {2: (960, 540), 3: (640, 360), 4: (480, 270), 5: (384, 216), 6: (320, 180), 7: (274, 154)}
IMAGES = Path("docs/images")
CROP = (380, 760, 320, 400)     # top, left, height, width: the same spot on every screen
SHOWN = (3, 4, 6)               # the scales in upscale_dedither.png

ONE = '''
import sys, numpy as np
sys.path.insert(0, ".")
from sw.dtgc import laptop
from sw.dtgc import protocol as p
from sw.dtgc.api import Canvas
from sw.dtgc.client import Dtgc
from sw.dtgc.emulator import Device, LocalTransport


class Recording(Device):
    """An emulator that also keeps every triangle it is asked to draw."""
    def __init__(self):
        super().__init__()
        self.seen = []

    def draw_triangle(self, triangle):
        self.seen.append(triangle)
        super().draw_triangle(triangle)


def reference(triangles, scale):
    """The triangles sampled at the centre of every screen pixel, in full colour, with the GPU's own edge rule."""
    height, width = p.HEIGHT * scale, p.WIDTH * scale
    picture = np.zeros((height, width, 3), dtype=np.float64)
    depth = np.full((height, width), 65535.0)
    for tri in triangles:
        v0, v1, v2 = tri.v0, tri.v1, tri.v2
        area = (v1.x - v0.x) * (v2.y - v0.y) - (v2.x - v0.x) * (v1.y - v0.y)
        if area == 0:
            continue
        if area < 0:
            v1, v2, area = v2, v1, -area
        # Corners are in 1/16 of a small pixel. Times scale they are in 1/16 of a screen pixel, whose centres are
        # at (2 X + 1) * 8.
        xs, ys = [v.x * scale for v in (v0, v1, v2)], [v.y * scale for v in (v0, v1, v2)]
        left, right = max(0, min(xs) // 16), min(width - 1, max(xs) // 16)
        top, bottom = max(0, min(ys) // 16), min(height - 1, max(ys) // 16)
        if left > right or top > bottom:
            continue
        gx, gy = np.meshgrid((2 * np.arange(left, right + 1) + 1) * 8, (2 * np.arange(top, bottom + 1) + 1) * 8)
        inside = np.ones(gx.shape, dtype=bool)
        weights = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            dx, dy = xs[j] - xs[i], ys[j] - ys[i]
            top_left = dy < 0 or (dy == 0 and dx > 0)
            edge = dx * (gy - ys[i]) - dy * (gx - xs[i])
            inside &= (edge >= 0) if top_left else (edge > 0)
            weights.append(edge / (area * scale * scale))
        # weights[0] belongs to the corner opposite edge 0-1, which is v2, and so on.
        z = weights[1] * v0.z + weights[2] * v1.z + weights[0] * v2.z
        behind = depth[top:bottom + 1, left:right + 1]
        show = inside & (z < behind)
        colour = np.stack([weights[1] * getattr(v0, c) + weights[2] * getattr(v1, c) + weights[0] * getattr(v2, c)
                           for c in "rgb"], axis=-1)
        picture[top:bottom + 1, left:right + 1][show] = colour[show]
        behind[show] = z[show]
    return np.clip(np.rint(picture), 0, 255).astype(np.uint8)


device = Recording()
canvas = Canvas(Dtgc(LocalTransport(device)))
field = laptop.Field()
field.frame = 40
field.draw(canvas)
canvas.finish()
canvas.gpu.swap()
indices = np.frombuffer(bytes(device.buffers[device.front]), dtype=np.uint8).reshape(p.HEIGHT, p.WIDTH)
small = np.array(device.palette, dtype=np.uint8)[indices]
np.savez_compressed(sys.argv[1], small=small, reference=reference(device.seen, int(sys.argv[2])))
'''


def capture(scale, path):
    """The emulator's small picture and the full-size reference for one scale."""
    width, height = SIZES[scale]
    env = dict(os.environ, DTGC_PICTURE=f"{width}x{height}")
    subprocess.run([sys.executable, "-c", ONE, str(path), str(scale)], env=env, check=True)
    data = np.load(path)
    return data["small"], data["reference"]


def on_screen(picture):
    """The picture in the middle of a black 1080p screen. Only x7 leaves a border, of one pixel."""
    screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
    y, x = (1080 - picture.shape[0]) // 2, (1920 - picture.shape[1]) // 2
    screen[y:y + picture.shape[0], x:x + picture.shape[1]] = picture
    return screen


def crop(picture):
    y, x, h, w = CROP
    return Image.fromarray(on_screen(picture)[y:y + h, x:x + w])


def grid(columns, rows, cells, labels):
    """cells and labels are lists in reading order."""
    _, _, h, w = CROP
    gap, label = 12, 28
    sheet = Image.new("RGB", (columns * w + (columns - 1) * gap, rows * (h + label) + (rows - 1) * gap), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (cell, text) in enumerate(zip(cells, labels)):
        left, top = (i % columns) * (w + gap), (i // columns) * (h + label + gap)
        sheet.paste(cell, (left, top + label))
        draw.text((left + 4, top + 8), text, fill="black")
    return sheet


def main():
    tmp = Path("build/compare")
    tmp.mkdir(parents=True, exist_ok=True)
    results = {}
    print("scale  picture     edge: PSNR  SSIM     edge_dd: PSNR  SSIM")
    for scale, (width, height) in SIZES.items():
        small, reference = capture(scale, tmp / f"x{scale}.npz")
        plain, smoothed = upscale.upscale(small, scale, "edge"), upscale.upscale(small, scale, "edge_dd")
        results[scale] = (plain, smoothed, reference)
        print(f"x{scale}     {width}x{height:<6} {upscale.psnr(reference, plain):9.2f}  {upscale.ssim(reference, plain):.4f}"
              f"     {upscale.psnr(reference, smoothed):11.2f}  {upscale.ssim(reference, smoothed):.4f}")
    IMAGES.mkdir(parents=True, exist_ok=True)
    grid(3, 2, [crop(results[s][1]) for s in SIZES],
         [f"x{s}: draws {SIZES[s][0]}x{SIZES[s][1]}" for s in SIZES]).save(IMAGES / "upscale_x2_to_x7.png")
    names = ("scaled only", "de-dither, then scaled", "drawn at 1080p in full colour")
    grid(3, len(SHOWN), [crop(results[s][i]) for s in SHOWN for i in range(3)],
         [f"x{s}: {name}" for s in SHOWN for name in names]).save(IMAGES / "upscale_dedither.png")
    print(IMAGES / "upscale_x2_to_x7.png")
    print(IMAGES / "upscale_dedither.png")


if __name__ == "__main__":
    main()
