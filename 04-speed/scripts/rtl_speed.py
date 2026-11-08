#!/usr/bin/env python3
"""Usage: python scripts/rtl_speed.py

Measures how fast the simulated Verilog GPU can take in a frame, with the byte link removed as a
limit (one byte every 2 clocks). Includes refresh and scan-out taking turns at the SDRAM, using the
simulation's SDRAM model. These are simulation numbers, not a hardware measurement.
"""
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sw.dtgc import protocol as p  # noqa: E402
from sw.dtgc.stream import tiles_for  # noqa: E402
from sw.tests import test_rtl_match as match  # noqa: E402

CLOCK_HZ = 25_200_000
FOLDER = Path("build/sim/speed")


def stream_of(packets):
    """Clears both buffers first, so the comparison with the emulator knows every memory location."""
    stream = list(p.encode(p.HELLO, 0))
    seq = 0
    textures = [(p.TEX_SPAN, p.tex_span_payload(row, 0, bytes(match.TEXTURE_COLUMNS))) for row in range(match.TEXTURE_ROWS)]
    for kind, payload in [(p.CLEAR, b"\x00"), (p.SWAP, b""), (p.CLEAR, b"\x00"), (p.CLEAR_DEPTH, b"\xff\xff"), *textures, *packets]:
        seq = (seq + 1) & 0xFF
        stream.extend(p.encode(kind, seq, payload))
    return stream


def noise_tiles():
    rng = random.Random(1)
    return [(p.TILE, p.tile_payload(x, y, w, h, rng.randbytes(w * h))) for x, y, w, h in tiles_for(340, 340, 20)]


def flat_tiles():
    return [(p.RLE, p.rle_payload(x, y, w, h, p.rle_pairs(bytes([9]) * (w * h)))) for x, y, w, h in tiles_for(340, 340, 20)]


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    vvp = FOLDER / "tb.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), *match.SOURCES], check=True)
    empty = stream_of([])
    cases = [("raw tiles, every pixel", noise_tiles()), ("run-length tiles, flat colour", flat_tiles()),
             ("CLEAR command", [(p.CLEAR, b"\x09")])]
    baseline = run(vvp, "empty", empty)
    print("| Full 340 x 340 frame | Clocks | Time | Most frames per second |\n|---|---|---|---|")
    for name, packets in cases:
        tag = name.split()[0].replace(",", "")
        problems = match.compare(tag, stream_of(packets), vvp, FOLDER)
        if problems:
            print(f"FAIL {name}: {problems[:2]}")
            sys.exit(1)
        clocks = clocks_for(tag) - baseline
        seconds = clocks / CLOCK_HZ
        print(f"| {name} | {clocks:,} | {seconds * 1000:.1f} ms | {1 / seconds:.1f} |")


def clocks_for(tag):
    state = dict(line.split() for line in (FOLDER / f"seed{tag}.state").read_text().splitlines())
    return int(state["stream_clocks"])


def run(vvp, tag, stream):
    match.run_verilog(tag, stream, vvp, FOLDER)
    return clocks_for(tag)


if __name__ == "__main__":
    main()
