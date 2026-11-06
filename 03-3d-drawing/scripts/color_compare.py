"""Usage: python scripts/color_compare.py  (writes docs/images/color_compare.png and prints PSNR figures)

Compares plain 8-bit, dithered 8-bit and a 16-bit model against the ideal 24-bit picture. The 8-bit
pictures come from the real reference renderer. The 16-bit one is only a sum: the GPU cannot do it yet.
PSNR measures closeness to the ideal picture in decibels (dB); higher is closer. "Blurred" compares after
a 4 x 4 average, roughly what the eye does at a distance, which is where dithering is meant to help.
"""
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from sw.dtgc import raster
from sw.dtgc.emulator import default_palette

SIZE = 340
LOW, HIGH = np.array((20, 40, 90)), np.array((120, 160, 230))  # a slow sky-like gradient, the hardest case for banding


def render(mode):
    """Draws the gradient as two triangles with the reference renderer and returns an RGB array."""
    top, bottom = tuple(int(c) for c in LOW), tuple(int(c) for c in HIGH)
    corners = [raster.Vertex(0, 0, 0, *top, 0, 0), raster.Vertex(SIZE * 16, 0, 0, *top, 0, 0),
               raster.Vertex(SIZE * 16, SIZE * 16, 0, *bottom, 0, 0), raster.Vertex(0, SIZE * 16, 0, *bottom, 0, 0)]
    picture = bytearray(SIZE * SIZE)
    depth = [0xFFFF] * (SIZE * SIZE)
    for a, b, c in ((0, 1, 2), (0, 2, 3)):
        raster.draw(raster.Triangle(mode, 0, 0, corners[a], corners[b], corners[c]), picture, depth, bytes(256))
    palette = np.array(default_palette(), dtype=np.uint8).reshape(256, 3)
    return palette[np.frombuffer(bytes(picture), dtype=np.uint8)].reshape(SIZE, SIZE, 3)


def ideal():
    rows = (np.arange(SIZE)[:, None] + 0.5) / SIZE
    line = LOW + (HIGH - LOW) * rows
    return np.repeat(line[:, None, :], SIZE, axis=1)


def model_16_bit(picture):
    """RGB565: keeps 5, 6 and 5 bits, repeating the top bits to fill out 8."""
    p = picture.astype(np.uint8)
    r, g, b = p[..., 0] >> 3, p[..., 1] >> 2, p[..., 2] >> 3
    return np.stack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)), axis=-1)


def psnr(a, b):
    error = np.mean((a.astype(float) - b.astype(float)) ** 2)
    return 10 * np.log10(255 ** 2 / error)


def blur(picture):
    kept = SIZE // 4 * 4
    return picture[:kept, :kept].astype(float).reshape(kept // 4, 4, kept // 4, 4, 3).mean(axis=(1, 3))


def main():
    best = ideal()
    plain, dithered, deep = render(0), render(raster.MODE_DITHER), model_16_bit(best)
    panels = [("Ideal 24-bit", best), ("8-bit (today)", plain), ("8-bit with dither (new)", dithered), ("16-bit (sum only)", deep)]
    figure, axes = plt.subplots(1, 4, figsize=(16, 4.6))
    for axis, (title, picture) in zip(axes, panels):
        axis.imshow(picture.astype(np.uint8), interpolation="nearest")
        axis.axis("off")
        line = title
        if picture is not best:
            line += f"\n{psnr(best, picture):.1f} dB, blurred {psnr(blur(best), blur(picture)):.1f} dB"
            print(f"{title}: {psnr(best, picture):.2f} dB, blurred {psnr(blur(best), blur(picture)):.2f} dB")
        axis.set_title(line, fontsize=12)
    figure.tight_layout()
    figure.savefig("docs/images/color_compare.png", dpi=110)


if __name__ == "__main__":
    main()
