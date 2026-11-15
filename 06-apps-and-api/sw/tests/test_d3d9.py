"""Tests the Direct3D 9 layer (sw/d3d9) with an ordinary Direct3D program, against the emulator.

Usage: python -m unittest sw.tests.test_d3d9    (run python sw/d3d9/build.py first, Windows only)

The same program also runs on this PC's real driver when it can, and the pictures are compared. That checks the
layer's maths against a real Direct3D 9, not against my own reading of the rules. Saves side by side pictures in
build/d3d9/compare/. Passing says nothing about real DTGC hardware.
"""
import os
import shutil
import socket
import subprocess
import threading
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from sw.dtgc import bridge, emulator, raster
from sw.dtgc import protocol as p
from sw.dtgc.transport import TcpTransport

BUILD = Path("build/d3d9")
SIDE = p.WIDTH
BACKGROUND = (0, 0, 85)


def run_on_emulator(arch):
    frames = []
    server = emulator.Server(port=0, on_swap=lambda d: frames.append(bytes(d.buffers[d.front])))
    log = BUILD / f"unsupported_{arch}.log"
    log.unlink(missing_ok=True)
    server.start()
    try:
        env = dict(os.environ, DTGC_PORT=str(server.port), DTGC_D3D9_LOG=str(log))
        result = subprocess.run([str(BUILD / arch / "test_app.exe")], env=env, capture_output=True, text=True, timeout=120)
    finally:
        server.stop()
    return result, frames, server.device, log


def read_ppm(path):
    data = Path(path).read_bytes()
    return np.frombuffer(data[-SIDE * SIDE * 3:], dtype=np.uint8).reshape(SIDE, SIDE, 3)


def run_on_real_driver(arch):
    """Returns 3 pictures, or None if this PC cannot do it."""
    folder = (BUILD / f"real_{arch}").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(BUILD / arch / "test_app.exe", folder / "test_app.exe")
    (folder / "d3d9.dll").unlink(missing_ok=True)
    for old in folder.glob("*.ppm"):
        old.unlink()
    result = subprocess.run([str(folder / "test_app.exe"), str(folder)], capture_output=True, text=True, timeout=120, cwd=folder)
    if result.returncode != 0 or "PASS" not in result.stdout or "DTGC" in result.stdout:
        return None
    return [read_ppm(folder / f"frame_{i}.ppm") for i in range(3)]


def as_rgb(indexes):
    lookup = np.array(emulator.default_palette(), dtype=np.uint8)
    return lookup[np.frombuffer(indexes, dtype=np.uint8).reshape(SIDE, SIDE)]


def coverage(picture):
    """True where a pixel is not the background: the shape, whatever its colours."""
    return np.abs(picture.astype(int) - np.array(BACKGROUND)).sum(axis=2) > 60


def box_mean(picture, size=8):
    """The average over small squares, which is what dithering is meant to preserve."""
    height = picture.shape[0] // size * size
    blocks = picture[:height, :height].reshape(height // size, size, height // size, size, 3)
    return blocks.mean(axis=(1, 3))


@unittest.skipUnless(os.name == "nt" and (BUILD / "x64" / "d3d9.dll").exists(), "build with python sw/d3d9/build.py first")
class Layer(unittest.TestCase):
    def check_arch(self, arch):
        result, frames, device, log = run_on_emulator(arch)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DTGC", result.stdout, "the program did not load the DTGC layer")
        self.assertEqual(len(frames), 3)
        self.assertFalse(log.exists() and log.read_text(), "the test program should use supported calls only")

        # Frame 0: exact. Direct3D 9 puts a pixel centre on the whole number, so 40 is 40.5 in the GPU's terms.
        expected = emulator.Device()
        corners = [((40, 30), (255, 0, 0)), ((300, 90), (0, 255, 0)), ((120, 310), (0, 0, 255))]
        vertices = [raster.Vertex(x * 16 + 8, y * 16 + 8, 32768, *color, 0, 0) for (x, y), color in corners]
        triangle = raster.Triangle(raster.MODE_DEPTH | raster.MODE_DITHER, 0, 0, *vertices)
        seq = 0
        for kind, payload in ((p.HELLO, b""), (p.CLEAR, bytes([0x01])), (p.CLEAR_DEPTH, b"\xff\xff"),
                              (p.TRIANGLE, raster.payload(triangle)), (p.SWAP, b"")):
            expected.feed(p.encode(kind, seq, payload))
            seq += 1
        self.assertEqual(frames[0], bytes(expected.buffers[expected.front]), "frame 0 is not the exact expected picture")
        return frames

    def test_x64(self):
        self.check_arch("x64")

    def test_x86(self):
        self.check_arch("x86")

    def test_through_the_bridge(self):
        """Program, then bridge, then emulator: the same picture as going straight to the emulator."""
        _, direct, _, _ = run_on_emulator("x64")
        frames = []
        server = emulator.Server(port=0, on_swap=lambda d: frames.append(bytes(d.buffers[d.front]))).start()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def serve():
            connection, _ = listener.accept()
            bridge.serve_one(connection, TcpTransport(port=server.port))

        threading.Thread(target=serve, daemon=True).start()
        env = dict(os.environ, DTGC_PORT=str(listener.getsockname()[1]))
        result = subprocess.run([str(BUILD / "x64" / "test_app.exe")], env=env, capture_output=True, text=True, timeout=120)
        listener.close()
        server.stop()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(frames, direct)

    def test_same_picture_as_a_real_driver(self):
        _, frames, _, _ = run_on_emulator("x64")
        real = run_on_real_driver("x64")
        if real is None:
            self.skipTest("this PC could not run the program on its own driver")
        out = BUILD / "compare"
        out.mkdir(parents=True, exist_ok=True)
        for i, (ours, theirs) in enumerate(zip(frames, real)):
            ours = as_rgb(ours)
            gap = np.full((SIDE, 6, 3), 40, dtype=np.uint8)
            Image.fromarray(np.concatenate([theirs, gap, ours], axis=1)).save(out / f"frame_{i}.png")
            a, b = coverage(theirs), coverage(ours)
            overlap = float((a & b).sum()) / float((a | b).sum())
            difference = np.abs(box_mean(ours) - box_mean(theirs)).mean()
            print(f"frame {i}: shape overlap {overlap:.4f}, mean colour difference over 8 x 8 squares {difference:.1f} of 255")
            self.assertGreater(overlap, 0.985, f"frame {i}")
            self.assertLess(difference, 14.0, f"frame {i}")


if __name__ == "__main__":
    unittest.main()
