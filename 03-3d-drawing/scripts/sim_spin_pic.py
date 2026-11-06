"""Usage: python scripts/sim_spin_pic.py  (writes docs/images/spin_simulated.png)

Runs cube frames through the real Verilog GPU in simulation, checks each against the Python emulator bit
for bit, then saves what the simulated video output shows. This is simulation, not a photo of hardware.
"""
import pathlib
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from sw.dtgc import demo, raster
from sw.dtgc.api import Canvas
from sw.dtgc import protocol as p
from sw.tests.streams import TEXTURE_COLUMNS, TEXTURE_ROWS
from sw.tests.test_rtl_match import SOURCES, compare, run_verilog

FOLDER = pathlib.Path("build/sim/spin")
ANGLES = [0.4, 1.1, 1.9, 2.7]


class Recorder:
    """Stands in for the GPU and keeps the packets a Canvas would send."""

    def __init__(self):
        self.packets = []

    def clear(self, color):
        self.packets.append((p.CLEAR, bytes([color])))

    def clear_depth(self):
        self.packets.append((p.CLEAR_DEPTH, bytes([255, 255])))

    def rect(self, x, y, w, h, color):
        self.packets.append((p.RECT, p.rect_payload(x, y, w, h, color)))

    def depth_rect(self, x, y, w, h):
        self.packets.append((p.DEPTH_RECT, struct.pack("<HHHHH", x, y, w, h, 0xFFFF)))

    def triangle(self, triangle):
        self.packets.append((p.TRIANGLE, raster.payload(triangle)))

    def swap(self):
        self.packets.append((p.SWAP, b""))


def scene_frames(angle):
    """The packets of each frame leading up to a spinning cube at this angle, using clear_scene."""
    recorder = Recorder()
    canvas = Canvas(recorder)
    frames = []
    for step in (-4, -3, -2, -1, 0):
        recorder.packets = []
        demo.draw_frame(canvas, angle + step * 0.08)
        frames.append(recorder.packets)
    return frames


def scene_stream(angle):
    """Several frames with clear_scene, for the bit-for-bit check."""
    seq = 0
    words = list(p.encode(p.HELLO, seq))
    textures = [(p.TEX_SPAN, p.tex_span_payload(row, 0, bytes(TEXTURE_COLUMNS))) for row in range(TEXTURE_ROWS)]
    for kind, payload in [*textures, *[packet for frame in scene_frames(angle) for packet in frame], (p.PING, b"")]:
        seq = (seq + 1) & 0xFF
        words.extend(p.encode(kind, seq, payload))
    return words


def stream_for(angle):
    """One complete frame drawn into both buffers, so the dump compares two known pictures."""
    seq = 0
    words = list(p.encode(p.HELLO, seq))

    def add(kind, payload=b""):
        nonlocal seq
        seq = (seq + 1) & 0xFF
        words.extend(p.encode(kind, seq, payload))

    # The bit-for-bit check also compares texture memory, so give it known contents.
    for row in range(TEXTURE_ROWS):
        add(p.TEX_SPAN, p.tex_span_payload(row, 0, bytes(TEXTURE_COLUMNS)))
    for _ in range(2):
        add(p.CLEAR, bytes([demo.BACKGROUND]))
        add(p.CLEAR_DEPTH, bytes([255, 255]))
        for triangle in demo.triangles(angle):
            add(p.TRIANGLE, raster.payload(triangle))
        add(p.SWAP)
    add(p.PING)
    return words


def draw_time(angle, vvp):
    """Clocks for clearing and drawing one frame, without SWAP, which waits for the screen and hides the real cost."""
    def clocks(tag, frame):
        seq = 0
        words = list(p.encode(p.HELLO, seq))
        for row in range(TEXTURE_ROWS):
            seq = (seq + 1) & 0xFF
            words.extend(p.encode(p.TEX_SPAN, seq, p.tex_span_payload(row, 0, bytes(TEXTURE_COLUMNS))))
        for kind, payload in frame:
            seq = (seq + 1) & 0xFF
            words.extend(p.encode(kind, seq, payload))
        prefix, _ = run_verilog(tag, words, vvp, FOLDER)
        state = dict(line.split() for line in pathlib.Path(f"{prefix}.state").read_text().splitlines())
        return int(state["stream_clocks"])

    frame = [(p.CLEAR, bytes([demo.BACKGROUND])), (p.CLEAR_DEPTH, bytes([255, 255]))]
    frame += [(p.TRIANGLE, raster.payload(t)) for t in demo.triangles(angle)]
    # Measured with memory holding a full frame, to keep the opening and closing of rows comparable.
    scene = [packet for packet in scene_frames(angle)[-1] if packet[0] != p.SWAP]
    base = clocks("base", [])
    return clocks(f"t{angle}", frame) - base, clocks(f"s{angle}", scene) - base


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    vvp = FOLDER / "gpu_core_tb.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), *SOURCES], check=True)
    streams = {i: stream_for(angle) for i, angle in enumerate(ANGLES)}
    scene = {f"scene{i}": scene_stream(angle) for i, angle in enumerate(ANGLES)}
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda i: compare(i, streams[i], vvp, FOLDER), streams))
    with ThreadPoolExecutor(4) as pool:
        scene_results = list(pool.map(lambda tag: compare(tag, scene[tag], vvp, FOLDER), scene))
    failed = any(scene_results)
    print("clear_scene frames:", "match the emulator bit for bit" if not failed else scene_results)
    for i, problems in enumerate(results):
        state = dict(line.split() for line in (FOLDER / f"seed{i}.state").read_text().splitlines())
        print(f"angle {ANGLES[i]}: {'matches the emulator bit for bit' if not problems else problems}, "
              f"stream took {int(state['stream_clocks'])} clocks")
        failed = failed or bool(problems)
    pictures = []
    for i in streams:
        values = pathlib.Path(FOLDER / f"seed{i}.screen").read_text().split()
        rgb = np.array([[int(v[j:j + 2], 16) for j in (0, 2, 4)] for v in values], dtype=np.uint8).reshape(480, 640, 3)
        pictures.append(rgb[70:410, 150:490])
    sheet = np.concatenate(pictures, axis=1)
    Image.fromarray(sheet).resize((sheet.shape[1] * 2, sheet.shape[0] * 2), Image.NEAREST).save("docs/images/spin_simulated.png")
    for angle in ANGLES:
        whole, partial = draw_time(angle, vvp)
        for name, used in (("whole-screen clears", whole), ("clear_scene", partial)):
            print(f"angle {angle}, {name}: {used} clocks to clear and draw, {used / 25.2e6 * 1000:.1f} ms at 25.2 MHz, "
                  f"at most {25.2e6 / used:.1f} frames per second")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
