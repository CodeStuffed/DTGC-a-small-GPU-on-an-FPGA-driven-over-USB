#!/usr/bin/env python3
"""Usage: python scripts/link_bytes.py

Counts the bytes one frame of the 3D field scene sends over the link, with single triangles and with indexed lists,
and checks both draw the same picture. Runs in the emulator. Frame rates printed are bytes alone at the given speed,
which leaves out the time the GPU spends drawing. The link speed on real hardware is not measured yet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sw.dtgc import laptop  # noqa: E402
from sw.dtgc.api import Canvas  # noqa: E402
from sw.dtgc.client import Dtgc  # noqa: E402
from sw.dtgc.emulator import Device, LocalTransport  # noqa: E402

LINK_SPEEDS = {"3 Mbit/s serial, 0.3 MB/s assumed": 300_000, "FT2232H, 40 MB/s assumed": 40_000_000}


class SingleTriangles:
    """Hides the list commands, so Canvas falls back to one packet per triangle."""

    def __init__(self, gpu):
        self._gpu = gpu

    def __getattr__(self, name):
        if name in ("vertices", "triangle_list"):
            raise AttributeError(name)
        return getattr(self._gpu, name)


def frame(wrap):
    device = Device()
    gpu = Dtgc(LocalTransport(device))
    canvas = Canvas(wrap(gpu))
    field = laptop.Field()
    field.frame = 40
    start = gpu.stats["bytes"]
    field.draw(canvas)
    canvas.finish()
    return gpu.stats["bytes"] - start, canvas.triangles_sent, bytes(device.back), list(device.depth)


def main():
    single = frame(SingleTriangles)
    lists = frame(lambda gpu: gpu)
    if single[2:] != lists[2:]:
        sys.exit("the two ways drew different pictures")
    print(f"{single[1]} triangles, same picture and depth both ways")
    print(f"single triangles {single[0]} bytes, lists {lists[0]} bytes, {single[0] / lists[0]:.2f} times fewer")
    for name, speed in LINK_SPEEDS.items():
        print(f"{name}: {speed / single[0]:.1f} -> {speed / lists[0]:.1f} frames per second, bytes alone")


if __name__ == "__main__":
    main()
