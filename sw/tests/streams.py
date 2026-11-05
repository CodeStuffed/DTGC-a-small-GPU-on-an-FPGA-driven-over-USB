"""Random test streams shared by the protocol tests and the Verilog comparison.

Usage: from sw.tests.streams import make_stream. A stream is a list of ints: 0-255 are bytes, and
IDLE stands for a silence long enough to trigger the parser's timeout.
"""
import random
import struct

from sw.dtgc import protocol as p
from sw.dtgc import raster

IDLE = 0x100
TEXTURE_ROWS = 32
TEXTURE_COLUMNS = 16
W, H = p.WIDTH, p.HEIGHT


def random_triangle(rng):
    """Mostly small, to keep simulation quick, with big, off-screen, thin and flat ones as well."""
    kind = rng.randrange(10)
    if kind <= 4:
        cx, cy = rng.randrange(-200, W * 16 + 160), rng.randrange(-200, H * 16 + 160)
        spread = rng.choice([8, 40, 200, 500])
        points = [(cx + rng.randrange(-spread, spread), cy + rng.randrange(-spread, spread)) for _ in range(3)]
    elif kind == 5:  # way off the picture, or crossing it from far away
        points = [(rng.randrange(-16384, 16384), rng.randrange(-16384, 16384)) for _ in range(3)]
    elif kind == 6:  # no area at all: a line and a point
        x, y = rng.randrange(W * 16), rng.randrange(H * 16)
        points = rng.choice([[(x, y)] * 3, [(x, y), (x + 80, y + 80), (x + 160, y + 160)]])
    elif kind == 7:  # needle thin
        x, y = rng.randrange(W * 16 - 440), rng.randrange(H * 16 - 440)
        points = [(x, y), (x + 400, y + 1), (x + 200, y + rng.randrange(1, 3))]
    elif kind == 8:  # on exact pixel centres and edges
        x, y = rng.randrange(W - 10) * 16 + 8, rng.randrange(H - 10) * 16 + 8
        points = [(x, y), (x + 80, y), (x, y + 80)]
    else:  # tiny, so colour steps are large and hit the limits
        x, y = rng.randrange(W * 16 - 440), rng.randrange(H * 16 - 440)
        points = [(x, y), (x + rng.randrange(1, 6), y + rng.randrange(0, 3)), (x + rng.randrange(0, 3), y + rng.randrange(1, 6))]
    mode = rng.randrange(8)
    tex_size = rng.randrange(5)  # up to 16 x 16, all inside the known part of texture memory
    tex_row = rng.randrange(TEXTURE_ROWS - 15)
    vertices = [raster.Vertex(x, y, rng.choice([0, 65535, rng.randrange(65536)]),
                              rng.randrange(256), rng.randrange(256), rng.randrange(256),
                              rng.randrange(256), rng.randrange(256)) for x, y in points]
    return raster.Triangle(mode, tex_row, tex_size, *vertices)


# Commands the GPU must refuse, or must skip without touching anything.
REFUSED = [
    (0x7F, b""), (p.CLEAR, b""), (p.CLEAR, b"ab"), (p.SPAN, b"abc"), (p.RECT, b"abc"),
    (p.PALETTE, b""), (p.PALETTE, b"abcd"), (p.SWAP, b"a"), (p.ACK, b"ab"),
    (p.TILE, b"abcdefg"), (p.RLE, b"abcdefg"), (p.RLE, b"abcdefghi"),
    (p.TRIANGLE, bytes(36)), (p.TRIANGLE, bytes(38)), (p.TEX_SPAN, b"ab"),
    (p.CLEAR_DEPTH, b"a"), (p.CLEAR_DEPTH, b"abc"), (p.DEPTH_RECT, bytes(9)), (p.DEPTH_RECT, bytes(11)),
    (p.READ_RECT, bytes(8)), (p.READ_RECT, bytes(10)), (p.READ_RECT, p.read_rect_payload(0, 0, 4, 4)[:-1] + b"\x02"),
    (p.READ_RECT, p.read_rect_payload(W, 0, 4, 4)), (p.READ_RECT, p.read_rect_payload(0, H, 4, 4)),
    (p.READ_RECT, p.read_rect_payload(5, 5, 0, 4)), (p.READ_RECT, p.read_rect_payload(5, 5, 4, 0)),
    # A coordinate out of range, and a texture too large
    (p.TRIANGLE, raster.payload(raster.Triangle(0, 0, 0, raster.Vertex(16384, 0, 0, 0, 0, 0, 0, 0),
                                                raster.Vertex(0, 0, 0, 0, 0, 0, 0, 0),
                                                raster.Vertex(0, 16, 0, 0, 0, 0, 0, 0)))),
    (p.TRIANGLE, raster.payload(raster.Triangle(0, 0, 9, raster.Vertex(0, 0, 0, 0, 0, 0, 0, 0),
                                                raster.Vertex(160, 0, 0, 0, 0, 0, 0, 0),
                                                raster.Vertex(0, 160, 0, 0, 0, 0, 0, 0)))),
    # Lists whose length does not match their count, and corners running past the last slot
    (p.VERTICES, b""), (p.VERTICES, b"a"), (p.VERTICES, bytes([0, 1]) + bytes(5)), (p.VERTICES, bytes([0, 1]) + bytes(7)),
    (p.VERTICES, bytes([0, 0]) + bytes(6)), (p.VERTICES, p.vertices_payload(255, [(1, 1, 1), (2, 2, 2)])),
    (p.VERTICES, p.vertices_payload(1, [(1, 1, 1)] * 170)[:1] + bytes([255]) + bytes(1020)),
    (p.TRIANGLE_LIST, b""), (p.TRIANGLE_LIST, b"a"), (p.TRIANGLE_LIST, bytes([0, 1]) + bytes(5)),
    (p.TRIANGLE_LIST, bytes([0, 1]) + bytes(7)), (p.TRIANGLE_LIST, bytes([0, 0]) + bytes(6)),
    # Texture rows past the end of memory, and a span running past the end of a row
    (p.TEX_SPAN, p.tex_span_payload(2048, 0, b"abcd")),
    (p.TEX_SPAN, p.tex_span_payload(5, 254, b"abcd")),
]


# Its last row is its widest, and ends on the row above y + 10, so a triangle starting there meets what it left held.
def flat_bottom_triangle(z, r, x, y):
    corners = [(16 * x, 16 * y), (16 * x + 160, 16 * y + 160), (16 * x, 16 * y + 160)]
    return raster.Triangle(raster.MODE_DEPTH, 0, 0, *[raster.Vertex(cx, cy, z, r, 0, 0, 0, 0) for cx, cy in corners])


def flat_triangle(z, r, mode=raster.MODE_DEPTH, x=100, y=100):
    corners = [(16 * x, 16 * y), (16 * x + 160, 16 * y), (16 * x, 16 * y + 160)]
    return raster.Triangle(mode, 0, 0, *[raster.Vertex(x, y, z, r, 0, 0, 0, 0) for x, y in corners])


# Thin triangles whose red plane rounds to just outside 0-255 at a covered pixel (found by search).
CLAMPED = [
    raster.Triangle(0, 0, 0, raster.Vertex(1625, 2064, 0, 255, 0, 0, 0, 0), raster.Vertex(1608, 2056, 0, 0, 0, 0, 0, 0),
                    raster.Vertex(1585, 2045, 0, 255, 0, 0, 0, 0)),
    raster.Triangle(0, 0, 0, raster.Vertex(2620, 2612, 0, 255, 0, 0, 0, 0), raster.Vertex(2584, 2632, 0, 0, 0, 0, 0, 0),
                    raster.Vertex(2609, 2642, 0, 255, 0, 0, 0, 0)),
]


# Thin triangles with a large depth or colour change, whose gradients only fit because of the limit (found by search).
STEEP = [
    ((2042, 1380, 65535, 255, 0, 0, 0, 0), (2427, 1415, 0, 0, 0, 0, 0, 0), (2234, 1383, 0, 0, 0, 0, 0, 0)),
    ((946, 1579, 65535, 255, 0, 0, 0, 0), (1641, 1618, 65535, 0, 0, 0, 0, 0), (1293, 1581, 0, 255, 0, 0, 0, 0)),
]


# A gradient that sweeps every colour level, then flat white, which dither must leave white.
DITHERED = [
    raster.Triangle(raster.MODE_DITHER, 0, 0, raster.Vertex(3200, 3200, 0, 0, 0, 0, 0, 0),
                    raster.Vertex(5400, 3200, 0, 255, 255, 255, 0, 0), raster.Vertex(3200, 5400, 0, 255, 128, 64, 0, 0)),
    raster.Triangle(raster.MODE_DITHER, 0, 0, raster.Vertex(800, 4800, 0, 255, 255, 255, 0, 0),
                    raster.Vertex(1600, 4800, 0, 255, 255, 255, 0, 0), raster.Vertex(800, 5400, 0, 255, 255, 255, 0, 0)),
]


def random_points(rng, count):
    """Corners close together, so most triangles made from them are small and quick to simulate."""
    cx, cy = rng.randrange(-100, W * 16 + 60), rng.randrange(-100, H * 16 + 60)
    spread = rng.choice([8, 40, 200])
    return [(cx + rng.randrange(-spread, spread), cy + rng.randrange(-spread, spread),
             rng.choice([0, 65535, rng.randrange(65536)])) for _ in range(count)]


def make_stream(seed, commands=40):
    """Starts with both buffers cleared, so every memory location has a known value."""
    rng = random.Random(seed)
    seq = 0
    stream = list(p.encode(p.HELLO, seq))

    def add(kind, payload=b""):
        nonlocal seq
        seq = (seq + 1) & 0xFF
        stream.extend(p.encode(kind, seq, payload))

    add(p.CLEAR, bytes([rng.randrange(256)]))
    add(p.SWAP)
    add(p.CLEAR, bytes([rng.randrange(256)]))

    # Depth and the part of texture memory the triangles use start known, as an application must do.
    add(p.CLEAR_DEPTH, bytes([255, 255]))
    for row in range(TEXTURE_ROWS):
        add(p.TEX_SPAN, p.tex_span_payload(row, 0, rng.randbytes(TEXTURE_COLUMNS)))

    # Every corner slot starts known, as an application must do.
    for first in range(0, 256, 32):
        add(p.VERTICES, p.vertices_payload(first, random_points(rng, 32)))

    for kind, payload in REFUSED:
        add(kind, payload)
    # Equal depth keeps the first colour.
    add(p.TRIANGLE, raster.payload(flat_triangle(100, 255)))
    add(p.TRIANGLE, raster.payload(flat_triangle(100, 0)))
    # Depth changed behind a triangle's back: what it left held must not decide the next one. Both of these pass.
    add(p.TRIANGLE, raster.payload(flat_bottom_triangle(50, 255, 240, 20)))
    add(p.CLEAR_DEPTH, struct.pack("<H", 200))
    add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=240, y=29)))
    add(p.TRIANGLE, raster.payload(flat_bottom_triangle(50, 255, 260, 20)))
    add(p.DEPTH_RECT, struct.pack("<HHHHH", 256, 16, 20, 30, 200))
    add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=260, y=29)))
    # A rectangle over a cleared buffer turns the marks into real depth. This one fails against the rectangle.
    add(p.RECT, p.rect_payload(276, 16, 24, 24, rng.randrange(256)))
    add(p.CLEAR_DEPTH, bytes([255, 255]))
    add(p.DEPTH_RECT, struct.pack("<HHHHH", 276, 16, 24, 24, 30))
    add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=280, y=20)))
    # Kept high so the steep triangles pass the depth test, and last so their depth values survive to the check.
    add(p.CLEAR_DEPTH, bytes([rng.randrange(256), rng.randrange(0xE0, 0x100)]))
    for vertices in STEEP:
        add(p.TRIANGLE, raster.payload(raster.Triangle(raster.MODE_DEPTH, 0, 0, *[raster.Vertex(*v) for v in vertices])))

    # Below where the steep triangles sit: odd and even edges, narrow ones, and past the picture's edge.
    for x, y, w, h in ((3, 200, 1, 3), (4, 204, 1, 3), (5, 208, 2, 3), (6, 212, 2, 3), (9, 216, 8, 3), (10, 220, 9, 3),
                       (W - 5, 300, 20, 2), (100, H - 5, 3, 20), (W - 2, H - 2, 65535, 65535), (20, 230, 0, 5), (20, 235, 5, 0),
                       (W, 240, 5, 5), (0, H, 5, 5)):
        add(p.DEPTH_RECT, struct.pack("<HHHHH", x, y, w, h, rng.randrange(65536)))
    # Rectangles whose ends fall on every position within a word.
    for offset in range(4):
        for width in range(1, 10):
            add(p.RECT, p.rect_payload(40 + offset + width * 12, 250 + offset, width, 2, rng.randrange(256)))

    # A wrong header checksum must drop the packet, even when the rest of it is good.
    packet = bytearray(p.encode(p.SPAN, (seq + 1) & 0xFF, p.span_payload(30, 30, rng.randbytes(20))))
    packet[6] ^= 0x01
    stream.extend(packet)
    stream.append(IDLE)

    for _ in range(commands):
        action = rng.randrange(24)
        if action >= 22:  # new corners, then triangles from them, and now and then from an old slot far away
            first, count = rng.randrange(250), rng.randrange(3, 7)
            add(p.VERTICES, p.vertices_payload(first, random_points(rng, count)))
            add(p.TRIANGLE_LIST, p.triangle_list_payload(
                rng.randrange(8), [(*[rng.randrange(first, first + count) if rng.random() < 0.97 else rng.randrange(256)
                                      for _ in range(3)], *rng.randbytes(3)) for _ in range(rng.randrange(5))]))
        elif action == 21:  # no entries at all
            add(rng.choice([p.VERTICES, p.TRIANGLE_LIST]), bytes([rng.randrange(256), 0]))
        elif action >= 19:  # read back, from anywhere, as far as off the picture, from either buffer
            x = rng.choice([0, rng.randrange(W), W - 4, W - 1])
            y = rng.choice([0, rng.randrange(H), H - 2, H - 1])
            w = rng.choice([1, 2, 3, 4, 5, 7, 8, 9, 31, 32, 33, 40, rng.randrange(1, 90), 65535])
            h = rng.choice([1, 2, rng.randrange(1, 6), 65535 if y >= H - 4 else 2])
            add(p.READ_RECT, p.read_rect_payload(x, y, w, h, rng.random() < 0.5))
        elif action >= 16:
            add(p.TRIANGLE, raster.payload(random_triangle(rng)))
        elif action == 14:  # raw tiles, some hanging off the picture or with too few or too many pixels
            x = rng.choice([0, rng.randrange(W), W - 10, W - 1, W, 65535])
            y = rng.choice([0, rng.randrange(H), H - 5, H - 1, H, 65535])
            w = rng.choice([0, 1, 4, 7, 20, rng.randrange(40), 65535])
            h = rng.choice([0, 1, 3, 20, rng.randrange(20), 65535])
            n = rng.choice([0, 1, w * h if w * h <= 1016 else 1016, rng.randrange(1017), 1016])
            add(p.TILE, p.tile_payload(x, y, w, h, rng.randbytes(n)))
        elif action == 15:  # run-length tiles, the same way, with short and very long runs
            x = rng.choice([0, rng.randrange(W), W - 10, W - 1, W, 65535])
            y = rng.choice([0, rng.randrange(H), H - 5, H - 1, H, 65535])
            w = rng.choice([0, 1, 4, 7, 20, rng.randrange(40), W, 65535])
            h = rng.choice([0, 1, 3, 20, rng.randrange(20), 65535])
            pairs = bytearray()
            for _ in range(rng.choice([0, 1, 2, 8, 40])):
                pairs += bytes([rng.choice([0, 1, 3, rng.randrange(256), 255]), rng.randrange(256)])
            add(p.RLE, p.rle_payload(x, y, w, h, pairs))
        elif action <= 3:  # spans, some of them hanging off the picture
            x = rng.choice([0, rng.randrange(W), W - 4, W - 1, W, W + 60, 65535])
            y = rng.choice([0, rng.randrange(H), H - 1, H, 65535])
            n = rng.choice([0, 1, 2, 3, 5, rng.randrange(60), rng.randrange(1, 1021), 1020])
            add(p.SPAN, p.span_payload(x, y, rng.randbytes(n)))
        elif action <= 5:  # small rectangles, some hanging off the picture
            x = rng.choice([rng.randrange(W), W - 10, W, 65535])
            y = rng.choice([rng.randrange(H), H - 5, H, 65535])
            w = rng.choice([0, 1, rng.randrange(40), 65535])
            h = rng.choice([0, 1, rng.randrange(12), 65535 if y >= H - 10 else 3])
            add(p.RECT, p.rect_payload(x, y, w, h, rng.randrange(256)))
        elif action == 6:  # palette, including entries running past 255
            first = rng.choice([0, rng.randrange(256), 250, 255])
            colors = [tuple(rng.randbytes(3)) for _ in range(rng.choice([0, 1, 3, 12, 40]))]
            add(p.PALETTE, p.palette_payload(first, colors))
        elif action == 7:
            add(p.SWAP)
        elif action == 8:  # commands the GPU must refuse
            kind, payload = rng.choice(REFUSED)
            add(kind, payload)
        elif action == 9:  # damage a byte somewhere in a packet
            packet = bytearray(p.encode(p.SPAN, (seq + 1) & 0xFF, p.span_payload(5, 5, rng.randbytes(20))))
            packet[rng.randrange(len(packet))] ^= 1 << rng.randrange(8)
            stream.extend(packet)
        elif action == 10 and rng.random() < 0.4:  # a valid header one byte over the length limit
            header = bytes([p.VERSION, p.SPAN, (seq + 1) & 0xFF, 0x01, 0x04])
            stream.extend(bytes([p.SYNC]) + header + bytes([p.crc8(header)]))
            stream.extend(rng.randbytes(1027))
            stream.append(IDLE)
        elif action == 10:  # noise between packets, including false sync bytes
            stream.extend(rng.choice([p.SYNC, rng.randrange(256)]) for _ in range(rng.randrange(1, 30)))
            stream.append(IDLE)
        elif action == 11:  # plug pulled part way through a packet
            packet = p.encode(p.SPAN, (seq + 1) & 0xFF, p.span_payload(7, 7, rng.randbytes(30)))
            stream.extend(packet[:rng.randrange(1, len(packet))])
            stream.append(IDLE)
        elif action == 12:  # the last packet again, then a wrong sequence number
            stream.extend(p.encode(p.PING, seq))
            stream.extend(p.encode(p.PING, (seq + rng.randrange(2, 200)) & 0xFF))
        else:  # a new connection restarts the numbering
            seq = rng.randrange(256)
            stream.extend(p.encode(p.HELLO, seq))

    # Cases that must never depend on luck. They come last so that nothing random draws over the result.
    # First, every area command hanging off each edge of the picture.
    color = rng.randrange(256)
    add(p.RECT, p.rect_payload(W - 5, 100, 20, 2, color))
    add(p.RECT, p.rect_payload(100, H - 5, 2, 20, color))
    add(p.RECT, p.rect_payload(W - 2, H - 2, 65535, 65535, color))
    add(p.TILE, p.tile_payload(W - 2, 200, 4, 2, rng.randbytes(8)))
    add(p.TILE, p.tile_payload(200, H - 2, 2, 4, rng.randbytes(8)))
    add(p.RLE, p.rle_payload(W - 2, 300, 4, 2, bytes([7, color])))
    add(p.RLE, p.rle_payload(300, H - 2, 2, 4, bytes([7, color])))
    add(p.SPAN, p.span_payload(W - 2, H - 1, rng.randbytes(4)))

    # Too many pixels for the area, no area at all, and a palette running past its last entry.
    add(p.TILE, p.tile_payload(50, 60, 2, 2, rng.randbytes(8)))
    add(p.RLE, p.rle_payload(50, 70, 2, 2, bytes([7, color, 7, color])))
    add(p.TILE, p.tile_payload(10, 20, 0, 3, rng.randbytes(4)))
    add(p.TILE, p.tile_payload(10, 30, 3, 0, rng.randbytes(4)))
    add(p.RLE, p.rle_payload(10, 40, 0, 3, bytes([3, color])))
    add(p.RLE, p.rle_payload(10, 50, 3, 0, bytes([3, color])))
    add(p.PALETTE, p.palette_payload(250, [tuple(rng.randbytes(3)) for _ in range(12)]))

    # Runs fully on the picture: exact lengths, then a payload that ends before the area is full.
    add(p.RLE, p.rle_payload(60, 80, 4, 2, bytes([3, color ^ 0x55, 3, color ^ 0xAA])))
    add(p.RLE, p.rle_payload(70, 90, 10, 2, bytes([3, color ^ 0x0F])))
    for triangle in CLAMPED + DITHERED:
        add(p.TRIANGLE, raster.payload(triangle))

    # Corners in the first and last slots, which a refused list must leave alone. Then several triangles in one list,
    # one of them with a corner out of range: it is skipped and the ones after it are still drawn.
    add(p.VERTICES, p.vertices_payload(255, [(160, 1760, 40)]))
    add(p.VERTICES, p.vertices_payload(0, [(480, 1760, 40), (160, 2080, 40), (1000, 1760, 40), (1320, 1760, 40), (1000, 2080, 40),
                                           (16384, 1760, 40), (1320, 2080, 40)]))
    add(p.VERTICES, p.vertices_payload(255, [(1, 1, 1), (2, 2, 2)]))
    add(p.TRIANGLE_LIST, p.triangle_list_payload(0, [(255, 0, 1, 11, 22, 33), (2, 3, 4, 44, 55, 66), (5, 3, 4, 1, 2, 3), (3, 6, 4, 77, 88, 99)]))
    # A later list in another mode keeps its own colour and takes the same corners. It leaves the triangle after
    # the skipped one alone, as that one shows the list went on.
    add(p.TRIANGLE_LIST, p.triangle_list_payload(raster.MODE_DEPTH, [(2, 3, 4, 200, 100, 50)]))

    # A triangle and a depth rectangle across the two SDRAM rows of a wide picture's depth, and the last tile of a row.
    add(p.DEPTH_RECT, struct.pack("<HHHHH", W - 40, 120, 40, 8, 500))
    add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=W - 20, y=119)))
    if W > 512:
        add(p.DEPTH_RECT, struct.pack("<HHHHH", 500, 130, 24, 8, 500))
        add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=505, y=129)))
        # Past x=512 depth lives in the second SDRAM row. The wrong row holds cleared depth and would let this through.
        add(p.CLEAR_DEPTH, bytes([255, 255]))
        add(p.DEPTH_RECT, struct.pack("<HHHHH", 600, 130, 16, 8, 50))
        add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=600, y=129)))
        # A cleared tile at the end of a row goes out whole, so old depth under its far half must not come back.
        add(p.DEPTH_RECT, struct.pack("<HHHHH", W - 16, 150, 16, 4, 5))
        add(p.CLEAR_DEPTH, bytes([255, 255]))
        add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=W - 16, y=150)))
        add(p.TRIANGLE, raster.payload(flat_triangle(100, 91, x=W - 6, y=150)))
        # Rows 20 and 532 share nothing, so using up the clear mark on one must leave the other marked.
        add(p.DEPTH_RECT, struct.pack("<HHHHH", 200, 532, 16, 8, 5))
        add(p.CLEAR_DEPTH, bytes([255, 255]))
        add(p.TRIANGLE, raster.payload(flat_triangle(100, 90, x=200, y=20)))
        add(p.TRIANGLE, raster.payload(flat_triangle(100, 91, x=200, y=531)))
        # A held colour word must not be taken for one 512 pixels along: the depth test skips all the pixels between.
        add(p.DEPTH_RECT, struct.pack("<HHHHH", 104, 180, 508, 1, 0))
        add(p.TRIANGLE, raster.payload(raster.Triangle(raster.MODE_DEPTH, 0, 0, *[raster.Vertex(16 * x, 16 * y, 100, 200, 0, 0, 0, 0)
                                                                                  for x, y in ((100, 180), (720, 180), (100, 190))])))

    # Every start and end position within a word and within a burst, then one whole row, on both buffers.
    for offset in range(5):
        for width in (1, 2, 3, 4, 5, 31, 32, 33, 34):
            add(p.READ_RECT, p.read_rect_payload(100 + offset, 150 + offset, width, 1, offset & 1))
    add(p.READ_RECT, p.read_rect_payload(0, H - 1, W, 1))
    add(p.READ_RECT, p.read_rect_payload(0, 0, W, 1, True))
    add(p.PING)
    stream.extend(p.encode(p.PING, (seq + 1) & 0xFF))
    return stream
