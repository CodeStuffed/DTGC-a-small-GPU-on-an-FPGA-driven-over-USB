"""Usage: python scripts/upscale_compare.py  (prints a table, writes docs/images/upscale_compare.png)

Scores DT-Upscale with test pictures made by code, so no picture comes from anyone else: each large
reference is shrunk, scaled back up, and compared with the original. This is the Python model.
"""
import pathlib
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from sw.dtgc import upscale as u

HEIGHT, WIDTH = 720, 1296  # divides evenly by 2, 3 and 4


def fractal():
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    c = (x - WIDTH / 2) * 0.0009 - 0.745 + 1j * ((y - HEIGHT / 2) * 0.0009 + 0.113)
    z = np.zeros_like(c)
    count = np.zeros(c.shape, dtype=np.int32)
    for _ in range(64):
        keep = np.abs(z) < 4
        z[keep] = z[keep] ** 2 + c[keep]
        count[keep] += 1
    return np.stack([count * 7 % 256, count * 3 % 256, 255 - count * 4 % 256], axis=2).astype(np.uint8)


def shapes():
    """Flat colours and hard edges, the kind of picture a simple game draws."""
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    picture = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    picture[..., 0] = 40 + y * 60 // HEIGHT
    picture[..., 2] = 90
    for cx, cy, radius, colour in ((300, 250, 170, (230, 60, 50)), (800, 400, 240, (60, 200, 90))):
        picture[(x - cx) ** 2 + (y - cy) ** 2 < radius ** 2] = colour
    picture[(x + y > 1100) & (x + y < 1130)] = (250, 240, 40)
    picture[(x - y > 500) & (x - y < 540) & (y > 40)] = (240, 240, 240)
    picture[600:690, 100:1200] = (20, 20, 30)
    # Small blocks, about the size of text.
    blocks = ((x // 12 + y // 12) % 2 == 0) & (y >= 615) & (y < 675) & (x >= 150) & (x < 1150)
    picture[blocks] = (230, 230, 230)
    return picture


def gradient():
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    return np.stack([x * 255 // WIDTH, y * 255 // HEIGHT, (x + y) * 255 // (WIDTH + HEIGHT)], axis=2).astype(np.uint8)


PICTURES = {"fractal": fractal(), "shapes": shapes(), "gradient": gradient()}
CHOICES = [("nearest", 0), ("bilinear", 0), ("bicubic", 0), ("bicubic", 1), ("bicubic", 2), ("edge", 0), ("edge", 1), ("edge", 2)]


def main():
    print("| Picture | Scale | Method | Sharpen | PSNR (dB) | SSIM |")
    print("|---|---|---|---|---|---|")
    for name, reference in PICTURES.items():
        for scale in (2, 3):
            small = u.downscale(reference, scale)
            for method, sharpen in CHOICES:
                big = u.upscale(small, scale, method, sharpen)
                print(f"| {name} | {scale} | {method} | {sharpen} | {u.psnr(reference, big):.2f} | {u.ssim(reference, big):.4f} |")
    # A close-up, so the difference shows at normal viewing size.
    reference = PICTURES["shapes"]
    small = u.downscale(reference, 2)
    crop = (slice(150, 330), slice(380, 700))
    panels = [reference[crop]]
    for method, sharpen in (("nearest", 0), ("bilinear", 0), ("bicubic", 1), ("edge", 1)):
        panels.append(u.upscale(small, 2, method, sharpen)[crop])
    sheet = np.concatenate(panels, axis=1)
    Image.fromarray(sheet).save("docs/images/upscale_compare.png")


if __name__ == "__main__":
    main()
