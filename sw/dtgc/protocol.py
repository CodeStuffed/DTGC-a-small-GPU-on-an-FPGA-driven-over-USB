"""DTGC packet protocol version 1: constants, checksums, packet building and the parser.

Usage: from sw.dtgc import protocol. The format is in docs/protocol.md. The parser's rules must stay
the same as rtl/pkt_parser.v; sw/tests/test_rtl_match.py compares the two.
"""
import os
import struct
from collections import namedtuple

SYNC = 0xD7
VERSION = 1
MAX_PAYLOAD = 1024
# The picture the GPU was built for: 340x340, or 960x540 for the 1080p30 build. Set before this module is first imported.
WIDTH, HEIGHT = map(int, os.environ.get("DTGC_PICTURE", "340x340").split("x"))

HELLO = 0x01
PING = 0x02
CLEAR = 0x10
SPAN = 0x11
RECT = 0x12
PALETTE = 0x13
SWAP = 0x14
TILE = 0x15
RLE = 0x16
TRIANGLE = 0x17
TEX_SPAN = 0x18
CLEAR_DEPTH = 0x19
DEPTH_RECT = 0x1A
READ_RECT = 0x1B
VERTICES = 0x1C
TRIANGLE_LIST = 0x1D
ACK = 0x80
NACK = 0x81
DATA = 0x82

STATUS_OK = 0
STATUS_UNKNOWN = 1
STATUS_BAD_LENGTH = 2
STATUS_BAD_VALUE = 3
NACK_CRC = 1
NACK_SEQ = 2

Packet = namedtuple("Packet", "kind seq payload crc_ok")


def crc8(data, crc=0):
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc16(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(kind, seq, payload=b""):
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload of {len(payload)} bytes is over the {MAX_PAYLOAD} limit")
    header = bytes([VERSION, kind, seq & 0xFF, len(payload) & 0xFF, len(payload) >> 8])
    body = header + bytes([crc8(header)]) + bytes(payload)
    return bytes([SYNC]) + body + struct.pack("<H", crc16(body))


def clear_payload(color):
    return bytes([color])


def span_payload(x, y, pixels):
    return struct.pack("<HH", x, y) + bytes(pixels)


def read_rect_payload(x, y, w, h, hidden=False):
    return struct.pack("<HHHHB", x, y, w, h, 1 if hidden else 0)


def rect_payload(x, y, w, h, color):
    return struct.pack("<HHHHB", x, y, w, h, color)


def palette_payload(first, colors):
    """colors is a list of (red, green, blue) tuples."""
    return bytes([first]) + b"".join(bytes(c) for c in colors)


def tile_payload(x, y, w, h, pixels):
    return struct.pack("<HHHH", x, y, w, h) + bytes(pixels)


def rle_pairs(pixels):
    """Run-length encodes bytes as (length - 1, value) pairs. A run holds at most 256 pixels."""
    out = bytearray()
    i = 0
    while i < len(pixels):
        value = pixels[i]
        run = 1
        while run < 256 and i + run < len(pixels) and pixels[i + run] == value:
            run += 1
        out += bytes([run - 1, value])
        i += run
    return bytes(out)


def rle_payload(x, y, w, h, pairs):
    return struct.pack("<HHHH", x, y, w, h) + bytes(pairs)


def tex_span_payload(row, u, pixels):
    return struct.pack("<HB", row, u) + bytes(pixels)


def vertices_payload(first, points):
    """points is a list of (x, y, z): x and y in sixteenths of a pixel, z from 0 to 65535."""
    return bytes([first, len(points)]) + b"".join(struct.pack("<hhH", *point) for point in points)


def triangle_list_payload(mode, records):
    """records is a list of (slot, slot, slot, red, green, blue)."""
    return bytes([mode, len(records)]) + b"".join(bytes(record) for record in records)


class Parser:
    """Finds packets in a byte stream. feed() returns a Packet when one is complete, else None.

    A packet with a good header and a bad body comes back with crc_ok False, so the sender can be
    told. A bad header is dropped silently and the search restarts at the following byte.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = "sync"
        self.header = bytearray()
        self.payload = bytearray()
        self.crc_low = 0

    def idle(self):
        """The link has been silent long enough for the parser's timeout."""
        self.reset()

    def feed(self, byte):
        if self.state == "sync":
            if byte == SYNC:
                self.state = "header"
                self.header = bytearray()
                self.payload = bytearray()
        elif self.state == "header":
            self.header.append(byte)
            if len(self.header) == 6:
                length = self.header[3] | (self.header[4] << 8)
                if byte != crc8(self.header[:5]) or self.header[0] != VERSION or length > MAX_PAYLOAD:
                    self.state = "sync"
                else:
                    self.length = length
                    self.state = "payload" if length else "crc0"
        elif self.state == "payload":
            self.payload.append(byte)
            if len(self.payload) == self.length:
                self.state = "crc0"
        elif self.state == "crc0":
            self.crc_low = byte
            self.state = "crc1"
        else:
            received = self.crc_low | (byte << 8)
            ok = received == crc16(bytes(self.header) + bytes(self.payload))
            self.state = "sync"
            return Packet(self.header[1], self.header[2], bytes(self.payload), ok)
        return None
