"""Shows the PC's screen on the GPU's HDMI output: USB in, HDMI out, with no display driver.

Usage: python -m sw.dtgc [--ft2232h 0] mirror [--frames N] [--fps N] [--no-dither]

It takes a screenshot, shrinks it to fit 340 x 340, reduces it to the GPU's 256 colours, and sends only the
tiles that changed. This copies the screen. It is not a second monitor, and Windows does not see a new display.

**Dithering** mixes neighbouring pixels of nearby colours, so that smooth shading doesn't turn into stripes.
"""
import time

import numpy as np
from PIL import Image

from . import protocol as p
from .stream import FrameStreamer

# Ordered dither pattern. Values run from 0 to 15, so they are scaled to one colour step before use.
BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.int32)


def fit_to_frame(image):
    """Shrinks a picture to fit the frame without changing its shape, with black bars in the spare space."""
    scale = min(p.WIDTH / image.width, p.HEIGHT / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    frame = Image.new("RGB", (p.WIDTH, p.HEIGHT))
    frame.paste(image.convert("RGB").resize(size, Image.Resampling.BILINEAR),
                ((p.WIDTH - size[0]) // 2, (p.HEIGHT - size[1]) // 2))
    return frame


def to_pixels(image, dither=True):
    """Turns a 340 x 340 RGB picture into bytes for the default palette, RRRGGGBB."""
    rgb = np.asarray(image, dtype=np.int32)
    if dither:
        ys, xs = np.indices(rgb.shape[:2])
        pattern = BAYER[ys % 4, xs % 4]
        # A red or green step is 255/7 and a blue step is 255/3.
        red_green = (pattern * 255) // (16 * 7)
        blue = (pattern * 255) // (16 * 3)
    else:
        red_green = blue = np.int32(0)
    red = np.minimum((rgb[:, :, 0] + red_green) * 7 // 255, 7)
    green = np.minimum((rgb[:, :, 1] + red_green) * 7 // 255, 7)
    blue = np.minimum((rgb[:, :, 2] + blue) * 3 // 255, 3)
    return ((red << 5) | (green << 2) | blue).astype(np.uint8).tobytes()


def grab_screen():
    from PIL import ImageGrab
    return ImageGrab.grab()


def run(gpu, frames=None, fps=15, dither=True, grab=grab_screen, out=print):
    """Mirrors until stopped, or for a number of frames. Returns the frames and bytes sent."""
    stream = FrameStreamer(gpu)
    start_bytes = gpu.stats["bytes"]
    start = time.perf_counter()
    done = 0
    try:
        while frames is None or done < frames:
            began = time.perf_counter()
            stream.send_frame(to_pixels(fit_to_frame(grab()), dither))
            done += 1
            spare = 1 / fps - (time.perf_counter() - began)
            if spare > 0:
                time.sleep(spare)
            if done % 30 == 0:
                out(f"{done} frames, {done / (time.perf_counter() - start):.1f} fps")
    except KeyboardInterrupt:
        pass
    sent = gpu.stats["bytes"] - start_bytes
    seconds = time.perf_counter() - start
    out(f"Mirrored {done} frames in {seconds:.1f} s, {sent:,} bytes sent")
    return done, sent
