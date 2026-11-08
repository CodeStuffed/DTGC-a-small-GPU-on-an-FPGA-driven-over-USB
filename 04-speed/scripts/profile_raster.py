#!/usr/bin/env python3
"""Usage: python scripts/profile_raster.py [--define NAME ...] [--scene cube|field] [--video MODE]

Set DTGC_PICTURE=960x540 in the environment for the large picture. --video 1080p30 runs that scan-out at the same time, so
the clocks include the memory time the video takes, which is what a frame costs on a screen.

Simulates one frame in Verilog and prints the clocks it takes, split by what the rasterizer is doing. These are clock
counts from simulation with an SDRAM model, which leave out the refreshes' effect on real timing margins but include
their clocks. Time on real hardware depends on the clock that passes timing.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from sw.dtgc import demo, laptop, raster  # noqa: E402
from sw.dtgc import protocol as p  # noqa: E402
from sw.dtgc.api import Canvas  # noqa: E402
from sw.dtgc.emulator import Device, LocalTransport  # noqa: E402
from sw.dtgc.client import Dtgc  # noqa: E402
from sw.tests.streams import TEXTURE_COLUMNS, TEXTURE_ROWS  # noqa: E402
from sw.tests.test_rtl_match import SOURCES, run_verilog  # noqa: E402
from sw.tests.test_upscale_rtl import EDGE_MODES, MODES  # noqa: E402
from sw.tests.test_upscale_rtl import SOURCES as HD_SOURCES  # noqa: E402

FOLDER = Path("build/sim/profile")
NAMES = {0: "idle", 1: "load", 2: "load", 3: "setup", 4: "setup", 5: "setup", 6: "setup", 7: "setup", 8: "setup", 9: "setup",
         10: "setup", 11: "setup", 12: "setup", 13: "multiply", 14: "divide", 15: "pixel loop", 16: "finish",
         17: "depth read", 18: "depth read", 19: "texture read", 20: "texture read", 21: "colour write", 22: "depth write", 23: "finish",
         24: "depth clear", 25: "depth flags", 26: "depth flags", 27: "resolve", 28: "resolve", 29: "resolve"}


def cube_frame():
    return [(p.TRIANGLE, raster.payload(t)) for t in demo.triangles(0.4)]


def field_frame():
    sent = []
    device = Device()
    gpu = Dtgc(LocalTransport(device))
    canvas = Canvas(gpu)
    real = gpu._send
    gpu._send = lambda kind, payload=b"": (sent.append((kind, payload)), real(kind, payload))
    field = laptop.Field()
    field.frame = 40
    field.draw(canvas)
    canvas.finish()
    return [packet for packet in sent if packet[0] in (p.TRIANGLE, p.VERTICES, p.TRIANGLE_LIST)]


def clocks_of(tag, packets, vvp, extra=()):
    seq = 0
    words = list(p.encode(p.HELLO, seq))
    for row in range(TEXTURE_ROWS):
        seq = (seq + 1) & 255
        words.extend(p.encode(p.TEX_SPAN, seq, p.tex_span_payload(row, 0, bytes(TEXTURE_COLUMNS))))
    for kind, payload in packets:
        seq = (seq + 1) & 255
        words.extend(p.encode(kind, seq, payload))
    prefix, output = run_verilog(tag, words, vvp, FOLDER, extra)
    if "PASS" not in output:
        sys.exit(f"{tag}: {output[-400:]}")
    state = dict(line.split() for line in Path(f"{prefix}.state").read_text().splitlines())
    return int(state["stream_clocks"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--define", action="append", default=[])
    parser.add_argument("--scene", choices=("cube", "field"), default="cube")
    parser.add_argument("--video", choices=tuple(MODES))
    args = parser.parse_args()
    FOLDER.mkdir(parents=True, exist_ok=True)
    vvp = FOLDER / "profile.vvp"
    defines = [f"-D{name}" for name in args.define]
    size = [f"-Pgpu_core_tb.WIDTH={p.WIDTH}", f"-Pgpu_core_tb.HEIGHT={p.HEIGHT}"]
    if p.WIDTH != 340:
        size.append("-Pgpu_core_tb.SCANOUT=0")
    settings, top, sources, run = size, "gpu_core_tb", SOURCES, ()
    if args.video:
        scale, h, v, half, core_half = MODES[args.video]
        names = ("H_VISIBLE", "H_FRONT", "H_SYNC", "H_BACK")
        settings = [f"-Pgpu_hd_tb.{n}={value}" for n, value in zip(names, h)]
        settings += [f"-Pgpu_hd_tb.{n.replace('H_', 'V_')}={value}" for n, value in zip(names, v)]
        settings += [f"-Pgpu_hd_tb.WIDTH={p.WIDTH}", f"-Pgpu_hd_tb.HEIGHT={p.HEIGHT}", f"-Pgpu_hd_tb.LINE_WORDS={(p.WIDTH + 3) // 4}",
                     f"-Pgpu_hd_tb.SCALE={scale}", f"-Pgpu_hd_tb.EDGE={int(args.video in EDGE_MODES)}", f"-Pgpu_hd_tb.VIDEO_HALF_NS={half}", f"-Pgpu_hd_tb.CORE_HALF_NS={core_half}", "-DPROFILE_TB=gpu_hd_tb"]
        top, sources, run = "gpu_hd_tb", HD_SOURCES, ("+no_screen",)
    subprocess.run(["iverilog", "-g2005", *defines, *settings, "-s", top, "-s", "raster_profile", "-o", str(vvp),
                    *sources, "sim/raster_profile.v"], check=True)
    triangles = cube_frame() if args.scene == "cube" else field_frame()
    depth = (p.CLEAR_DEPTH, b"\xff\xff")
    base = clocks_of("base", [], vvp, run)
    clear = clocks_of("clear", [(p.CLEAR, b"\x25")], vvp, run) - base
    clear_depth = clocks_of("depth", [depth], vvp, run) - base
    report = FOLDER / "report.txt"
    total = clocks_of("all", [depth, *triangles], vvp, (f"+profile={report}", *run)) - base - clear_depth
    numbers = dict(line.split() for line in report.read_text().splitlines())
    groups = {}
    for key, count in numbers.items():
        if key.startswith("state"):
            name = NAMES.get(int(key[5:]), key)
            groups[name] = groups.get(name, 0) + int(count)
    groups.pop("idle", None)
    print(f"{args.scene}: {len(triangles)} packets, {total} clocks for the triangles")
    print(f"colour clear {clear}, depth clear {clear_depth}")
    for name, count in sorted(groups.items(), key=lambda item: -item[1]):
        print(f"  {name:14} {count:8}  {100 * count / total:5.1f}%")
    print(f"  of the pixel loop, outside the triangle: {numbers['outside_pixels']}")


if __name__ == "__main__":
    main()
