"""Measures how many bytes each game sends per frame, over a scripted game on the emulator.

Usage: python scripts/game_bytes.py [--link-bytes-per-second N]

The bytes are real, because they are exactly what the protocol would send. The frame rate column is only
what the link would allow at the rate given. It ignores the time the GPU takes to draw, and the default
rate is the unmeasured assumption from docs/benchmarks.md.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sw.dtgc import games  # noqa: E402
from sw.dtgc.api import Canvas  # noqa: E402
from sw.dtgc.client import Dtgc  # noqa: E402
from sw.dtgc.emulator import Device, LocalTransport  # noqa: E402

FRAMES = 300


def measure(name):
    gpu = Dtgc(LocalTransport(Device()))
    game, canvas = games.GAMES[name](), Canvas(gpu)
    worst, start = 0, gpu.stats["bytes"]
    for frame in range(FRAMES):
        before = gpu.stats["bytes"]
        game.step({"up"} if frame % 50 < 30 else {"left"})
        game.draw(canvas)
        canvas.show()
        canvas.finish()
        worst = max(worst, gpu.stats["bytes"] - before)
    return (gpu.stats["bytes"] - start) / FRAMES, worst


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--link-bytes-per-second", type=float, default=300000)
    args = parser.parse_args()
    print(f"{'game':8} {'average bytes':>14} {'worst bytes':>12} {'link limit fps (worst frame)':>30}")
    for name in games.GAMES:
        average, worst = measure(name)
        print(f"{name:8} {average:14.0f} {worst:12d} {args.link_bytes_per_second / worst:30.0f}")
    print(f"Link rate assumed: {args.link_bytes_per_second:.0f} bytes/s. Emulator only, not measured on hardware.")


if __name__ == "__main__":
    main()
