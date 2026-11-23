#!/usr/bin/env python3
"""Usage: python scripts/make_videos.py [--ffmpeg PATH] [--frames N] [--only NAME ...]

Makes the MP4 videos in docs/paper/media/ from simulation, each with a caption saying where its pictures
came from. Nothing here was filmed: no hardware has run yet.

  cube, field, dodge, maze   the Python emulator (checked bit for bit against the Verilog by test_rtl_match)
  build_up                   the emulator, showing the back buffer as one frame of triangles goes in
  upscale                    the same frame at 1x, and scaled by the nearest pixel, bilinear and sharpened
  rtl_vs_python              Verilog simulation next to the emulator, with the count of differing pixels
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, ".")
from sw.dtgc import demo, emulator, games, laptop, raster, upscale  # noqa: E402
from sw.dtgc import protocol as p  # noqa: E402
from sw.dtgc.api import Canvas  # noqa: E402
from sw.dtgc.client import Dtgc  # noqa: E402
from sw.tests.streams import TEXTURE_COLUMNS, TEXTURE_ROWS  # noqa: E402

OUT = Path("docs/paper/media")
SIDE = p.WIDTH
FPS = 30
CAPTION_HEIGHT = 56
INK = (235, 235, 235)
PANEL = (18, 18, 22)
FONT = ImageFont.load_default(size=15)
SMALL = ImageFont.load_default(size=12)


def find_ffmpeg(given):
    if given:
        return given
    found = shutil.which("ffmpeg")
    if found:
        return found
    packages = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WinGet/Packages"
    for path in packages.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
        return str(path)
    raise SystemExit("ffmpeg not found: give it with --ffmpeg")


class Video:
    """Takes RGB frames as arrays of height x width x 3 and pipes them to ffmpeg as H.264."""

    def __init__(self, ffmpeg, name, width, height, fps=FPS):
        OUT.mkdir(parents=True, exist_ok=True)
        self.path = OUT / f"{name}.mp4"
        self.shape = (height, width, 3)
        self.process = subprocess.Popen(
            [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
             "-movflags", "+faststart", str(self.path)], stdin=subprocess.PIPE)

    def add(self, frame):
        assert frame.shape == self.shape, frame.shape
        self.process.stdin.write(frame.tobytes())

    def close(self):
        self.process.stdin.close()
        if self.process.wait() != 0:
            raise SystemExit(f"ffmpeg failed on {self.path}")
        print(f"{self.path}: {self.path.stat().st_size // 1024} KB")


def picture(device):
    """The picture being shown, as a 340 x 340 x 3 array."""
    return np.frombuffer(device.window_rgb(), dtype=np.uint8).reshape(SIDE, SIDE, 3)


def back_picture(device):
    lookup = np.array(device.palette, dtype=np.uint8)
    return lookup[np.frombuffer(bytes(device.back), dtype=np.uint8).reshape(SIDE, SIDE)]


def grow(image, factor):
    return np.repeat(np.repeat(image, factor, axis=0), factor, axis=1)


def even(number):
    return number + number % 2


def with_caption(image, title, note):
    """Adds a strip under the picture with a title and the source of the picture."""
    height, width = image.shape[:2]
    frame = Image.new("RGB", (width, height + CAPTION_HEIGHT), PANEL)
    frame.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(frame)
    draw.text((10, height + 8), title, font=FONT, fill=INK)
    draw.text((10, height + 30), note, font=SMALL, fill=(170, 170, 170))
    return np.asarray(frame)


def dodge_keys(frame, _scene):
    """Weaves from side to side, as a player would."""
    return {"left" if math.sin(frame / 17) > 0 else "right"}


def maze_keys(frame, scene):
    """Walks until a wall is close, then turns."""
    x = scene.x + math.cos(scene.angle) * 0.6
    y = scene.y + math.sin(scene.angle) * 0.6
    return {"up"} if scene._free(x, y) else {"right"}


def scene_frames(make_scene, count, keys=lambda frame, scene: set()):
    """Yields (emulated picture, triangles in that frame) for a demo with step() and draw()."""
    shown = []
    device = emulator.Device(on_swap=lambda d: shown.append(picture(d).copy()))
    gpu = Dtgc(emulator.LocalTransport(device))
    gpu.hello()
    canvas = Canvas(gpu)
    scene = make_scene()
    for frame in range(count):
        scene.step(keys(frame, scene))
        scene.draw(canvas)
        canvas.show()
        gpu.flush()
        while shown:
            yield shown.pop(0)


def scene_video(ffmpeg, name, make_scene, count, title, keys=lambda frame, scene: set()):
    note = "Python emulator, checked bit for bit against the Verilog. Not filmed: no hardware has run yet."
    video = None
    for image in scene_frames(make_scene, count, keys):
        framed = with_caption(grow(image, 2), title, note)
        if video is None:
            video = Video(ffmpeg, name, framed.shape[1], framed.shape[0])
        video.add(framed)
    video.close()


def build_up(ffmpeg, _count):
    """One frame of the field going in, in the order the triangles are sent: this is what the back buffer does."""
    device = emulator.Device()
    gpu = Dtgc(emulator.LocalTransport(device))
    gpu.hello()
    canvas = Canvas(gpu)
    field = laptop.Field()
    field.frame = 40

    sent = []
    real_triangle = gpu.triangle
    gpu.triangle = lambda tri: (sent.append(tri), real_triangle(tri))
    field.draw(canvas)
    gpu.flush()
    total = len(sent)

    device = emulator.Device()
    gpu = Dtgc(emulator.LocalTransport(device))
    gpu.hello()
    canvas = Canvas(gpu)
    canvas.clear_scene(0x00)
    gpu.flush()
    video = None
    per_frame = max(1, total // 240)
    for i in range(0, total, per_frame):
        for tri in sent[i:i + per_frame]:
            gpu.triangle(tri)
        gpu.flush()
        framed = with_caption(grow(back_picture(device), 2), f"Back buffer filling: {min(i + per_frame, total)} of {total} triangles",
                              "Python emulator. Depth test and dithering are on. Slowed down to be watchable.")
        if video is None:
            video = Video(ffmpeg, "build_up", framed.shape[1], framed.shape[0])
        video.add(framed)
    for _ in range(FPS):
        video.add(framed)
    video.close()


def upscale_video(ffmpeg, count):
    scale = 2
    video = None
    for image in scene_frames(laptop.Spin, count):
        crop = image[60:280, 60:280]
        nearest = upscale.upscale(crop, scale, "nearest")
        smooth = upscale.upscale(crop, scale, "bilinear")
        sharp = upscale.upscale(crop, scale, "bilinear", sharpen=1)
        gap = np.full((nearest.shape[0], 6, 3), 40, dtype=np.uint8)
        row = np.concatenate([nearest, gap, smooth, gap, sharp], axis=1).astype(np.uint8)
        row = row[:even(row.shape[0]) - 0 or None]
        framed = with_caption(row, "2x upscale. Left: nearest pixel. Middle: bilinear. Right: bilinear with sharpening",
                              "Python model of the upscaler. The HD builds do bilinear in hardware (passes simulation); sharpening is PC side only.")
        if framed.shape[1] % 2:
            framed = framed[:, :-1]
        if framed.shape[0] % 2:
            framed = framed[:-1]
        if video is None:
            video = Video(ffmpeg, "upscale", framed.shape[1], framed.shape[0])
        video.add(framed)
    video.close()


def verilog_frame(index, angle, vvp, folder):
    """Simulates one cube frame in Verilog. Returns the pictures from Verilog and Python, as palette indexes."""
    from sw.tests.test_rtl_match import run_python, run_verilog
    seq = 0
    words = list(p.encode(p.HELLO, seq))
    for row in range(TEXTURE_ROWS):
        seq = (seq + 1) & 255
        words.extend(p.encode(p.TEX_SPAN, seq, p.tex_span_payload(row, 0, bytes(TEXTURE_COLUMNS))))
    frame = [(p.CLEAR, bytes([demo.BACKGROUND])), (p.CLEAR_DEPTH, bytes([255, 255]))]
    frame += [(p.TRIANGLE, raster.payload(t)) for t in demo.triangles(angle)]
    for kind, payload in frame:
        seq = (seq + 1) & 255
        words.extend(p.encode(kind, seq, payload))
    prefix, output = run_verilog(index, words, vvp, folder)
    if "PASS" not in output:
        raise SystemExit(f"frame {index}: simulation did not finish: {output[-300:]}")
    device, _ = run_python(words)
    state = dict(line.split() for line in Path(f"{prefix}.state").read_text().splitlines())
    memory = Path(f"{prefix}.memory").read_text().split()
    back = 1 - int(state["front"])
    rtl = bytearray()
    for y in range(SIDE):
        for column in range(SIDE // 4):
            rtl += bytes.fromhex(memory[(back * SIDE + y) * (SIDE // 4) + column])[::-1]
    return np.frombuffer(bytes(rtl), dtype=np.uint8).reshape(SIDE, SIDE), \
        np.frombuffer(bytes(device.back), dtype=np.uint8).reshape(SIDE, SIDE), int(state["stream_clocks"])


def rtl_vs_python(ffmpeg, count):
    from sw.tests.test_rtl_match import SOURCES
    folder = Path("build/sim/video")
    folder.mkdir(parents=True, exist_ok=True)
    vvp = folder / "gpu_core_tb.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), *SOURCES], check=True)
    lookup = np.array(emulator.default_palette(), dtype=np.uint8)
    angles = [i * 2 * math.pi / count for i in range(count)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: verilog_frame(job[0], job[1], vvp, folder), enumerate(angles)))
    video = None
    different = 0
    for rtl, python, clocks in results:
        wrong = int(np.count_nonzero(rtl != python))
        different += wrong
        gap = np.full((SIDE, 6, 3), 40, dtype=np.uint8)
        row = np.concatenate([lookup[rtl], gap, lookup[python]], axis=1)
        framed = with_caption(row, f"Left: Verilog simulation.  Right: Python emulator.  Pixels that differ: {wrong}",
                              f"Icarus Verilog of rtl/gpu_core.v with an SDRAM model. {clocks} clocks in this run. Passes in simulation only.")
        if video is None:
            video = Video(ffmpeg, "rtl_vs_python", framed.shape[1], framed.shape[0], fps=12)
        video.add(framed)
    video.close()
    print(f"rtl_vs_python: {count} frames, {different} pixels differ in total")
    if different:
        raise SystemExit("the Verilog and the emulator differ")


def main():
    parser = argparse.ArgumentParser(description="Make the videos from simulation.")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--frames", type=int, default=240, help="frames in each scene video")
    parser.add_argument("--only", nargs="*", help="cube field dodge maze build_up upscale rtl_vs_python")
    args = parser.parse_args()
    ffmpeg = find_ffmpeg(args.ffmpeg)
    jobs = {
        "cube": lambda n: scene_video(ffmpeg, "cube", laptop.Spin, n, "Spinning cube: depth test, shading, dithering"),
        "field": lambda n: scene_video(ffmpeg, "field", laptop.Field, n // 2, "Field of 196 cubes: 2352 triangles before hidden faces are dropped"),
        "dodge": lambda n: scene_video(ffmpeg, "dodge", games.GAMES["dodge"], n, "Dodge, a game written for the GPU's commands, with scripted keys", dodge_keys),
        "maze": lambda n: scene_video(ffmpeg, "maze", games.GAMES["maze"], n, "Maze, a ray-cast game drawn with rectangles, with scripted keys", maze_keys),
        "build_up": lambda n: build_up(ffmpeg, n),
        "upscale": lambda n: upscale_video(ffmpeg, n // 2),
        "rtl_vs_python": lambda n: rtl_vs_python(ffmpeg, 24),
    }
    for name in args.only or jobs:
        jobs[name](args.frames)


if __name__ == "__main__":
    main()
