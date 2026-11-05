"""Measures how many bytes each kind of picture needs, and how fast the path from the PC runs.

Usage: python -m sw.dtgc benchmark [--frames N]            uses a built-in emulator
       python -m sw.dtgc --serial PORT benchmark           uses real hardware

On the emulator, bytes per frame are real measurements, but seconds only describe this PC: the
emulator is not a model of hardware speed. "Link for 15 fps" is arithmetic from the bytes.
"""
import random
import time

from . import demo, raster
from . import protocol as p
from .stream import FrameStreamer

TARGET_FPS = 15
SIZE = p.WIDTH * p.HEIGHT


def scene_static(_frame):
    return bytes(i % 256 for i in range(SIZE))


def scene_sprite(frame, _background=bytearray(y * 170 // p.HEIGHT for y in range(p.HEIGHT) for _ in range(p.WIDTH))):
    """A 32 x 32 square moving over a still background."""
    pixels = bytearray(_background)
    x, y = 20 + frame * 3 % 280, 40 + frame * 2 % 260
    for row in range(y, y + 32):
        pixels[row * p.WIDTH + x:row * p.WIDTH + x + 32] = b"\xE0" * 32
    return bytes(pixels)


def scene_scroll(frame):
    """Stripes moving one row a frame, so every tile changes but runs stay long."""
    rows = [bytes([(y + frame) // 8 * 37 % 256]) * p.WIDTH for y in range(p.HEIGHT)]
    return b"".join(rows)


def scene_fractal(frame):
    """A Mandelbrot zoom, written in plain Python. Slow on purpose: this is the CPU baseline."""
    scale = 3.0 * 0.93 ** frame / p.WIDTH
    center_x, center_y = -0.745, 0.113
    out = bytearray(SIZE)
    for py in range(p.HEIGHT):
        ci = center_y + (py - p.HEIGHT / 2) * scale
        for px in range(p.WIDTH):
            cr = center_x + (px - p.WIDTH / 2) * scale
            zr = zi = 0.0
            n = 0
            while n < 32 and zr * zr + zi * zi < 4.0:
                zr, zi = zr * zr - zi * zi + cr, 2 * zr * zi + ci
                n += 1
            out[py * p.WIDTH + px] = n * 8 % 256
    return bytes(out)


def scene_noise(frame):
    """The worst case: every pixel random, every frame. Nothing compresses."""
    return random.Random(frame).randbytes(SIZE)


SCENES = [("static", scene_static), ("sprite", scene_sprite), ("scroll", scene_scroll),
          ("fractal", scene_fractal), ("noise", scene_noise)]


def run_scene(gpu, scene, frames, tile_size=20, compress=True):
    """Two frames are sent first, because both buffers have to be filled before deltas can start."""
    stream = FrameStreamer(gpu, tile_size, compress)
    for warm_up in range(2):
        stream.send_frame(scene(warm_up))
    made = sent = total_bytes = 0
    for number in range(2, 2 + frames):
        start = time.perf_counter()
        pixels = scene(number)
        middle = time.perf_counter()
        before = gpu.stats["bytes"]
        stream.send_frame(pixels)
        made += middle - start
        sent += time.perf_counter() - middle
        total_bytes += gpu.stats["bytes"] - before
    return {"bytes": total_bytes / frames, "make_ms": made / frames * 1000, "send_ms": sent / frames * 1000}


def cube_cpu_ms(frames=10):
    """The spinning cube's triangles in plain Python, which is what the GPU is there to replace."""
    start = time.perf_counter()
    for frame in range(frames):
        picture = bytearray(SIZE)
        depth = [0xFFFF] * SIZE
        for triangle in demo.triangles(frame * 0.3):
            raster.draw(triangle, picture, depth, b"")
    return (time.perf_counter() - start) / frames * 1000


def report(gpu, frames, out=print):
    """Prints a table. Frames are compared with the frame before last, as the hardware needs."""
    results = {}
    out("| Scene | Bytes per frame | Link needed for 15 fps | Bytes without tiles | Make frame (Python) | Send on this link |")
    out("|---|---|---|---|---|---|")
    full_frame = SIZE + p.HEIGHT * 13  # one SPAN per row
    for name, scene in SCENES:
        result = run_scene(gpu, scene, frames)
        results[name] = result
        out(f"| {name} | {result['bytes']:,.0f} | {result['bytes'] * TARGET_FPS / 1e6:.3f} MB/s | {full_frame:,} "
            f"| {result['make_ms']:.1f} ms | {result['send_ms']:.1f} ms |")
    out("")
    out(f"CPU baseline: one cube frame drawn in plain Python takes {cube_cpu_ms():.1f} ms on this PC.")
    return results
