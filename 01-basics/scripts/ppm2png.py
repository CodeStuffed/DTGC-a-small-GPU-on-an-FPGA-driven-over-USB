#!/usr/bin/env python3
"""Usage: python scripts/ppm2png.py INPUT.ppm OUTPUT.png

Converts a plain-text (P3) PPM image from a testbench into a PNG. Standard library only.
"""
import struct
import sys
import zlib


def chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        tokens = f.read().split()
    if tokens[0] != "P3":
        sys.exit("not a P3 PPM file")
    width, height, maximum = int(tokens[1]), int(tokens[2]), int(tokens[3])
    if maximum != 255:
        sys.exit("only 8-bit images are supported")
    values = bytes(int(v) for v in tokens[4:])
    if len(values) != width * height * 3:
        sys.exit(f"expected {width * height * 3} values, found {len(values)}")
    rows = b"".join(b"\0" + values[y * width * 3:(y + 1) * width * 3] for y in range(height))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows, 9))
           + chunk(b"IEND", b""))
    with open(sys.argv[2], "wb") as f:
        f.write(png)
    print(f"Wrote {sys.argv[2]} ({width}x{height})")


if __name__ == "__main__":
    main()
