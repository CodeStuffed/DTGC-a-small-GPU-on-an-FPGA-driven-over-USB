"""The HD scan-out against sw/dtgc/upscale.py: every pixel of the whole screen, bit for bit, through the real GPU.

Usage: python -m unittest sw.tests.test_upscale_rtl    (set DTGC_RTL_SEEDS=N for more streams)

The core and the video run on clocks that never line up, as on the board. Needs Icarus Verilog, and skips without it.
"""
import os
import random
import shutil
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from sw.dtgc import emulator
from sw.dtgc import protocol as p
from sw.dtgc import upscale
from sw.tests.streams import make_stream
from sw.tests.test_rtl_match import run_python

BUILD = Path("build/sim/hd")
SOURCES = ["sim/gpu_hd_tb.v", "sim/sdram_model.v", "rtl/gpu_core.v", "rtl/raster.v", "rtl/vertex_store.v", "rtl/depth_flags.v", "rtl/video_timing.v", "rtl/sdram_ctrl.v",
           "rtl/fb_scanout.v", "rtl/fb_scanout_hd.v", "rtl/fb_scanout_dd.v", "rtl/dedither.v", "rtl/upscale_filter.v", "rtl/upscale_edge.v", "rtl/byte_fifo.v", "rtl/pkt_parser.v",
           "rtl/cmd_exec.v", "rtl/reply_tx.v", "rtl/frame_reader.v"]

# 1080p30 from smaller pictures scaled further, all edge-directed: scale and the picture that fills the screen.
# 1920 and 1080 do not divide by 7, so x7 leaves a black border of 1 pixel each side.
SUPER = {3: (640, 360), 4: (480, 270), 5: (384, 216), 6: (320, 180), 7: (274, 154)}

# The modes using the edge-directed scaler, and those that de-dither first (fb_scanout_dd.v), whose names end in dd.
EDGE_MODES = ("720p60edge", "720p60x4", "1080p30", *(f"1080p30x{n}" for n in SUPER))
DD_MODES = ("1080p30dd", *(f"1080p30x{n}dd" for n in SUPER))

# name: scale, active and blanking across, active and blanking down, half a video clock and half a core clock in ns
MODES = {
    "720p60": (2, (1280, 110, 40, 220), (720, 5, 5, 20), 6.734, 10.775),
    "720p60edge": (2, (1280, 110, 40, 220), (720, 5, 5, 20), 6.734, 10.775),
    # 60 frames a second: a 320x180 picture four times the size is exactly 1280x720 (the kart race, the microSD player).
    "720p60x4": (4, (1280, 110, 40, 220), (720, 5, 5, 20), 6.734, 10.775),
    "1080p50rb": (3, (1920, 48, 32, 80), (1080, 3, 5, 20), 4.34, 10.417),
    "1080p30": (2, (1920, 88, 44, 148), (1080, 4, 5, 36), 6.734, 10.775),
}
MODES.update({f"1080p30x{n}": (n, (1920, 88, 44, 148), (1080, 4, 5, 36), 6.734, 10.775) for n in SUPER})
MODES.update({name: MODES[name[:-2]] for name in DD_MODES})


def method_of(mode):
    return "edge_dd" if mode in DD_MODES else "edge" if mode in EDGE_MODES else "bilinear"


def scan_stream(seed):
    """A test stream, then a picture made to catch scan-out mistakes, shown on screen.

    The pictures the streams leave are mostly flat, so they cannot tell whether the last pixels of a line or the first
    and last rows are right, or whether a neighbour was counted as close when it was not. This adds, on top of whatever
    is there: noise down both sides and along the top and bottom, and bands of dither-like noise, where each pixel is
    one of two palette steps in each colour, with some stray pixels in it. Even seeds also put the default palette back,
    since the dither-like pixels only sit one step apart with that palette.
    """
    rng = random.Random(seed + 1000)
    stream = list(make_stream(seed))
    seq = 0
    stream.extend(p.encode(p.HELLO, seq))   # a new connection restarts the numbering

    def add(kind, payload=b""):
        nonlocal seq
        seq = (seq + 1) & 0xFF
        stream.extend(p.encode(kind, seq, payload))

    def tiles(x, y, w, h, pixel):
        step = max(1, 1000 // w)
        for top in range(y, y + h, step):
            rows = min(step, y + h - top)
            add(p.TILE, p.tile_payload(x, top, w, rows, bytes(pixel() for _ in range(w * rows))))

    def noise(x, y, w, h):
        tiles(x, y, w, h, lambda: rng.randrange(256))

    def dither_like(x, y, w, h):
        red, green, blue = rng.randrange(7), rng.randrange(7), rng.randrange(3)
        tiles(x, y, w, h, lambda: rng.randrange(256) if rng.random() < 0.05 else
              ((red + rng.randrange(2)) << 5) | ((green + rng.randrange(2)) << 2) | (blue + rng.randrange(2)))

    if seed % 2 == 0:
        palette = emulator.default_palette()
        for first in range(0, 256, 32):
            add(p.PALETTE, p.palette_payload(first, palette[first:first + 32]))
    wide, high = p.WIDTH, p.HEIGHT
    noise(0, 0, 6, high)
    noise(wide - 6, 0, 6, high)
    noise(0, 0, wide, 4)
    noise(0, high - 4, wide, 4)
    dither_like(0, high // 3, wide, 12)
    dither_like(wide // 2 - 20, 0, 40, high)
    dither_like(0, 0, 24, 24)
    dither_like(wide - 24, high - 24, 24, 24)
    add(p.SWAP)
    return stream


def wanted_screen(device, scale, width, height, method="bilinear"):
    """What should be on the screen: the shown buffer through the palette, scaled, in the middle of black."""
    indices = np.frombuffer(bytes(device.buffers[device.front]), dtype=np.uint8).reshape(p.HEIGHT, p.WIDTH)
    small = np.array(device.palette, dtype=np.uint8)[indices]
    big = upscale.upscale(small, scale, method)
    screen = np.zeros((height, width, 3), dtype=np.uint8)
    x, y = (width - big.shape[1]) // 2, (height - big.shape[0]) // 2
    screen[y:y + big.shape[0], x:x + big.shape[1]] = big
    return screen


def build(mode, folder):
    scale, h, v, half, core_half = MODES[mode]
    folder.mkdir(parents=True, exist_ok=True)
    vvp = folder / "tb.vvp"
    names = ("H_VISIBLE", "H_FRONT", "H_SYNC", "H_BACK")
    settings = [f"-Pgpu_hd_tb.{n}={value}" for n, value in zip(names, h)]
    settings += [f"-Pgpu_hd_tb.{n.replace('H_', 'V_')}={value}" for n, value in zip(names, v)]
    settings.append(f"-Pgpu_hd_tb.EDGE={2 if mode in DD_MODES else int(mode in EDGE_MODES)}")
    subprocess.run(["iverilog", "-g2005", f"-Pgpu_hd_tb.WIDTH={p.WIDTH}", f"-Pgpu_hd_tb.HEIGHT={p.HEIGHT}", f"-Pgpu_hd_tb.LINE_WORDS={(p.WIDTH + 3) // 4}",
                    f"-Pgpu_hd_tb.SCALE={scale}", f"-Pgpu_hd_tb.VIDEO_HALF_NS={half}", f"-Pgpu_hd_tb.CORE_HALF_NS={core_half}", *settings,
                    "-o", str(vvp), *SOURCES], check=True)
    return vvp


def compare(mode, seed, stream, vvp, folder):
    scale, h, v, _, _ = MODES[mode]
    prefix = folder / f"seed{seed}"
    stream_file = folder / f"seed{seed}.hex"
    stream_file.write_text("\n".join(f"{w:03x}" for w in stream) + "\n")
    result = subprocess.run(["vvp", str(vvp), f"+stream={stream_file}", f"+words={len(stream)}", f"+out={prefix}"],
                            capture_output=True, text=True, timeout=2400)
    if "PASS" not in result.stdout:
        return [f"simulation did not finish: {(result.stdout + result.stderr)[-400:]}"]
    problems = []
    state = dict(line.split() for line in Path(f"{prefix}.state").read_text().splitlines())
    for name in ("rule_errors", "overflow", "underrun"):
        if state[name] != "0":
            problems.append(f"{name} {state[name]}")
    words = Path(f"{prefix}.screen").read_text().split()
    if any("x" in w for w in words):
        problems.append(f"{sum('x' in w for w in words)} screen pixels unknown")
        return problems
    got = np.frombuffer(bytes.fromhex("".join(words)), dtype=np.uint8).reshape(v[0], h[0], 3)
    device, _ = run_python(stream)
    want = wanted_screen(device, scale, h[0], v[0], method_of(mode))
    wrong = np.argwhere((got != want).any(axis=2))
    if len(wrong):
        y, x = wrong[0]
        problems.append(f"{len(wrong)} screen pixels differ, first at x {x} y {y}: {got[y, x]} vs {want[y, x]}")
    return problems


@unittest.skipUnless(shutil.which("iverilog"), "Icarus Verilog is not on the PATH")
class HdScanoutMatchesTheModel(unittest.TestCase):
    def check(self, mode):
        seeds = range(1, int(os.environ.get("DTGC_RTL_SEEDS", "2")) + 1)
        folder = BUILD / mode
        vvp = build(mode, folder)
        # Only the last stage of a longer stream decides the picture, so short streams give the same test faster.
        streams = {seed: scan_stream(seed) for seed in seeds}
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = dict(zip(seeds, pool.map(lambda s: compare(mode, s, streams[s], vvp, folder), seeds)))
        for seed, problems in results.items():
            print(f"{mode} seed {seed}: {'exact match' if not problems else problems}")
        self.assertEqual({s: r for s, r in results.items() if r}, {})

    @unittest.skipUnless(p.WIDTH == 340, "the 340x340 picture only")
    def test_720p60_twice_the_size(self):
        self.check("720p60")

    @unittest.skipUnless(p.WIDTH == 340, "the 340x340 picture only")
    def test_720p60_edge_directed(self):
        self.check("720p60edge")

    @unittest.skipUnless(p.WIDTH == 340, "the 340x340 picture only")
    def test_1080p50_three_times_the_size(self):
        self.check("1080p50rb")

    @unittest.skipUnless((p.WIDTH, p.HEIGHT) == (320, 180), "run with DTGC_PICTURE=320x180 in the environment")
    def test_720p60_four_times_the_size(self):
        self.check("720p60x4")

    @unittest.skipUnless(p.WIDTH == 960, "run with DTGC_PICTURE=960x540 in the environment")
    def test_1080p30_filling_the_screen(self):
        self.check("1080p30")

    def test_1080p30_super_upscale(self):
        """Run with DTGC_PICTURE set to one of the SUPER pictures, for example 480x270 for x4."""
        scales = [n for n, size in SUPER.items() if size == (p.WIDTH, p.HEIGHT)]
        if not scales:
            self.skipTest("set DTGC_PICTURE to " + ", ".join(f"{w}x{h}" for w, h in SUPER.values()))
        self.check(f"1080p30x{scales[0]}")

    @unittest.skipUnless(p.WIDTH == 960, "run with DTGC_PICTURE=960x540 in the environment")
    def test_1080p30_dedither(self):
        self.check("1080p30dd")

    def test_1080p30_super_upscale_dedither(self):
        """Run with DTGC_PICTURE set to one of the SUPER pictures, for example 480x270 for x4."""
        scales = [n for n, size in SUPER.items() if size == (p.WIDTH, p.HEIGHT)]
        if not scales:
            self.skipTest("set DTGC_PICTURE to " + ", ".join(f"{w}x{h}" for w, h in SUPER.values()))
        self.check(f"1080p30x{scales[0]}dd")


if __name__ == "__main__":
    unittest.main()
