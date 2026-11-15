"""Draws each game on the emulator and saves a picture of it, to look at without playing.

Usage: python scripts/game_pics.py    (writes docs/images/games.png)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sw.dtgc import games, protocol as p  # noqa: E402
from sw.dtgc.api import Canvas  # noqa: E402
from sw.dtgc.client import Dtgc  # noqa: E402
from sw.dtgc.emulator import Device, LocalTransport  # noqa: E402


def snapshot(name, frames):
    device = Device()
    gpu = Dtgc(LocalTransport(device))
    game, canvas = games.GAMES[name](), Canvas(gpu)
    for frame in range(frames):
        game.step({"up"} if name == "maze" and frame < 12 else set())
        game.draw(canvas)
        canvas.show()
        canvas.finish()
    return np.frombuffer(device.window_rgb(), dtype=np.uint8).reshape(p.HEIGHT, p.WIDTH, 3)


def main():
    sheet = np.hstack([snapshot(name, frames) for name, frames in (("pong", 25), ("maze", 1), ("dodge", 60))])
    path = ROOT / "docs" / "images" / "games.png"
    Image.fromarray(sheet).save(path)
    print(f"wrote {path} (emulator output, not hardware)")


if __name__ == "__main__":
    main()
