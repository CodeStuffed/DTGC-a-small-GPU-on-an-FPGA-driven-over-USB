#!/usr/bin/env python3
"""Usage: python -m unittest sw.tests.test_raster_speed

Keeps the drawing speed from slipping. The other tests compare pictures, and a change that only wastes clocks draws the
same picture, so none of them would notice it. This one draws the spinning cube in the Verilog simulation and counts
the clocks its triangles take. Fewer clocks than the budget is fine: lower the budget to the new number then.

Simulation only. Clock counts say nothing about the clock speed a real board can run at.
"""
import subprocess
import unittest
from pathlib import Path

from sw.dtgc import demo, raster
from sw.dtgc import protocol as p
from sw.tests.streams import TEXTURE_COLUMNS, TEXTURE_ROWS
from sw.tests.test_rtl_match import SOURCES, run_verilog

FOLDER = Path("build/sim/speed")
BUDGET = {(340, 340): 47321}  # clocks for the cube's 12 triangles, measured 2026-11-11 after the drawing speed-up


def stream_clocks(tag, packets, vvp, folder):
    seq = 0
    words = list(p.encode(p.HELLO, seq))
    for row in range(TEXTURE_ROWS):
        seq = (seq + 1) & 255
        words.extend(p.encode(p.TEX_SPAN, seq, p.tex_span_payload(row, 0, bytes(TEXTURE_COLUMNS))))
    for kind, payload in packets:
        seq = (seq + 1) & 255
        words.extend(p.encode(kind, seq, payload))
    prefix, output = run_verilog(tag, words, vvp, folder)
    if "PASS" not in output:
        raise AssertionError(f"{tag}: {output[-400:]}")
    state = dict(line.split() for line in Path(f"{prefix}.state").read_text().splitlines())
    return int(state["stream_clocks"])


def cube_clocks(sources=SOURCES, folder=FOLDER):
    """Clocks the cube's 12 triangles take, with the depth clear before them taken off."""
    folder.mkdir(parents=True, exist_ok=True)
    vvp = folder / "speed.vvp"
    size = [] if p.WIDTH == 340 else ["-Pgpu_core_tb.SCANOUT=0", f"-Pgpu_core_tb.WIDTH={p.WIDTH}", f"-Pgpu_core_tb.HEIGHT={p.HEIGHT}"]
    subprocess.run(["iverilog", "-g2005", *size, "-o", str(vvp), *sources], check=True, capture_output=True)
    depth = (p.CLEAR_DEPTH, b"\xff\xff")
    triangles = [(p.TRIANGLE, raster.payload(t)) for t in demo.triangles(0.4)]
    return stream_clocks("cube", [depth, *triangles], vvp, folder) - stream_clocks("depth", [depth], vvp, folder)


class CubeStaysFast(unittest.TestCase):
    def test_cube_triangles_fit_the_budget(self):
        budget = BUDGET.get((p.WIDTH, p.HEIGHT))
        if not budget:
            self.skipTest(f"no budget measured for {p.WIDTH}x{p.HEIGHT}")
        clocks = cube_clocks()
        self.assertLessEqual(clocks, budget, f"the cube now takes {clocks} clocks, {clocks - budget} more than before")


if __name__ == "__main__":
    print(cube_clocks())
