"""rtl/shade_pipe.v against sw/dtgc/shade.py, bit for bit, on random pixels and on the extremes.

Usage: python -m unittest sw.tests.test_shade_rtl

Needs Icarus Verilog, and skips without it.
"""
import random
import shutil
import subprocess
import unittest
from pathlib import Path

from sw.dtgc import shade

FOLDER = Path("build/sim/shade")
COUNT = 40000


def signed16(rng):
    return rng.choice([-32768, 32767, -4096, 4096, 0, rng.randrange(-4096, 4097), rng.randrange(-32768, 32768)])


def colour(rng):
    return tuple(rng.choice([0, 255, rng.randrange(256)]) for _ in range(3))


def vector(rng):
    return ((signed16(rng), signed16(rng), signed16(rng)), (signed16(rng), signed16(rng), signed16(rng)),
            rng.choice([0, 256, 511, rng.randrange(512)]), rng.choice([0, 255, rng.randrange(256)]),
            rng.randrange(256), rng.randrange(256), colour(rng), colour(rng), rng.choice([0, 1, 255, 256, rng.randrange(257)]))


def pack(normal, direction, ambient, amount, x, y, base, dst, alpha):
    value = 0
    for number, bits in [*[(n & 0xFFFF, 16) for n in (*normal, *direction)], (ambient, 9), (amount, 8), (x, 8), (y, 8),
                         *[(c, 8) for c in (*base, *dst)], (alpha, 9)]:
        value = (value << bits) | number
    return value


def difference(sources, folder=FOLDER):
    """Runs the testbench on these Verilog files. Returns the first difference from the model, or None."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(1)
    vectors = [vector(rng) for _ in range(COUNT)]
    (folder / "in.hex").write_text("\n".join(f"{pack(*v):x}" for v in vectors) + "\n")
    vvp = folder / "shade.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), *sources], check=True, capture_output=True)
    result = subprocess.run(["vvp", str(vvp), f"+in={folder / 'in.hex'}", f"+out={folder / 'out.hex'}", f"+words={COUNT}"],
                            capture_output=True, text=True, timeout=600)
    if "PASS" not in result.stdout:
        return (result.stdout + result.stderr)[-200:]
    for index, (word, inputs) in enumerate(zip((folder / "out.hex").read_text().split(), vectors)):
        want = "".join(f"{c:02x}" for c in shade.shade(*inputs))
        if word != want:
            return f"pixel {index}: got {word}, want {want}"
    return None


@unittest.skipUnless(shutil.which("iverilog"), "Icarus Verilog is not on the PATH")
class ShaderMatchesTheModel(unittest.TestCase):
    def test_every_pixel(self):
        self.assertIsNone(difference(["sim/shade_pipe_tb.v", "rtl/shade_pipe.v"]))
        print(f"{COUNT} pixels match the model exactly")


if __name__ == "__main__":
    unittest.main()
