"""Reference triangle renderer. rtl/raster.v must match it bit for bit.

Usage: from sw.dtgc.raster import draw, Triangle. The rules are in docs/rasterizer.md.

Coordinates have 4 fractional bits (1/16 of a pixel). A pixel counts as inside when its centre is
inside all three edges. An **edge function** is a number that is positive on one side of an edge and
negative on the other, which needs only adds to update from one pixel to the next. Colour, depth and
texture coordinates are planes: they change by a fixed amount per pixel, held with 16 fractional bits.
"""
import struct
from collections import namedtuple

from . import protocol as p

Vertex = namedtuple("Vertex", "x y z r g b u v")
Triangle = namedtuple("Triangle", "mode tex_row tex_size v0 v1 v2")

MODE_DEPTH = 1
MODE_TEXTURE = 2
MODE_DITHER = 4
BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
PAYLOAD_SIZE = 37
COORD_LIMIT = 16384
GRADIENT_LIMIT = (1 << 31) - 1
_VERTEX = struct.Struct("<hhHBBBBB")
_HEADER = struct.Struct("<BHB")


def payload(tri):
    out = _HEADER.pack(tri.mode, tri.tex_row, tri.tex_size)
    return out + b"".join(_VERTEX.pack(*v) for v in (tri.v0, tri.v1, tri.v2))


def parse(data):
    mode, tex_row, tex_size = _HEADER.unpack_from(data)
    vertices = [Vertex(*_VERTEX.unpack_from(data, 4 + i * 11)) for i in range(3)]
    return Triangle(mode, tex_row, tex_size, *vertices)


def valid(tri):
    """Coordinates must be within 1024 pixels of the origin, and textures at most 256 wide."""
    if tri.tex_size > 8:
        return False
    return all(-COORD_LIMIT <= v.x < COORD_LIMIT and -COORD_LIMIT <= v.y < COORD_LIMIT
               for v in (tri.v0, tri.v1, tri.v2))


def _gradient(numerator, area):
    """numerator << 20 / area, rounded towards zero and limited to 32 bits. area is positive."""
    magnitude = (abs(numerator) << 20) // area
    magnitude = min(magnitude, GRADIENT_LIMIT)
    return -magnitude if numerator < 0 else magnitude


def _clamp(value, top):
    whole = value >> 16
    return 0 if whole < 0 else top if whole > top else whole


def _pack_color(r, g, b):
    return (r & 0xE0) | ((g >> 3) & 0x1C) | (b >> 6)


def _pack_dithered(r, g, b, x, y):
    level = BAYER[y & 3][x & 3]
    # Scaling by 7/8 (3/4 for blue) makes the average match the palette, and white can no longer overflow.
    return _pack_color(r - (r >> 3) + level * 2, g - (g >> 3) + level * 2, b - (b >> 2) + level * 4)


def pixels(tri, width=p.WIDTH, height=p.HEIGHT):
    """Yields (x, y, color, z, u, v) for each covered pixel, in the order the hardware visits them."""
    v0, v1, v2 = tri.v0, tri.v1, tri.v2
    area = (v1.x - v0.x) * (v2.y - v0.y) - (v2.x - v0.x) * (v1.y - v0.y)
    if area == 0:
        return
    if area < 0:
        v1, v2 = v2, v1
        area = -area

    min_x = max(0, min(v0.x, v1.x, v2.x) >> 4)
    max_x = min(width - 1, max(v0.x, v1.x, v2.x) >> 4)
    min_y = max(0, min(v0.y, v1.y, v2.y) >> 4)
    max_y = min(height - 1, max(v0.y, v1.y, v2.y) >> 4)
    if min_x > max_x or min_y > max_y:
        return
    start_x, start_y = min_x * 16 + 8, min_y * 16 + 8

    # Edges. Pixels exactly on an edge belong to it only if it is a top or left edge, so triangles
    # sharing an edge never both draw, and never both miss, a pixel on it.
    row_edges, step_x, step_y = [], [], []
    for a, b in ((v0, v1), (v1, v2), (v2, v0)):
        dx, dy = b.x - a.x, b.y - a.y
        top_left = dy < 0 or (dy == 0 and dx > 0)
        row_edges.append(dx * (start_y - a.y) - dy * (start_x - a.x) - (0 if top_left else 1))
        step_x.append(-dy * 16)
        step_y.append(dx * 16)

    # Planes for red, green, blue, depth, u and v.
    dx1, dy1 = v1.x - v0.x, v1.y - v0.y
    dx2, dy2 = v2.x - v0.x, v2.y - v0.y
    row_values, grad_x, grad_y = [], [], []
    for name in ("r", "g", "b", "z", "u", "v"):
        c0 = getattr(v0, name)
        dc1, dc2 = getattr(v1, name) - c0, getattr(v2, name) - c0
        gx = _gradient(dc1 * dy2 - dc2 * dy1, area)
        gy = _gradient(dc2 * dx1 - dc1 * dx2, area)
        row_values.append((c0 << 16) + ((gx * (start_x - v0.x) + gy * (start_y - v0.y)) >> 4))
        grad_x.append(gx)
        grad_y.append(gy)

    for y in range(min_y, max_y + 1):
        e0, e1, e2 = row_edges
        r, g, b, z, u, v = row_values
        for x in range(min_x, max_x + 1):
            if e0 >= 0 and e1 >= 0 and e2 >= 0:
                red, green, blue = _clamp(r, 255), _clamp(g, 255), _clamp(b, 255)
                color = (_pack_dithered(red, green, blue, x, y) if tri.mode & MODE_DITHER
                         else _pack_color(red, green, blue))
                yield (x, y, color, _clamp(z, 65535), _clamp(u, 255), _clamp(v, 255))
            e0 += step_x[0]
            e1 += step_x[1]
            e2 += step_x[2]
            r += grad_x[0]
            g += grad_x[1]
            b += grad_x[2]
            z += grad_x[3]
            u += grad_x[4]
            v += grad_x[5]
        row_edges = [value + step for value, step in zip(row_edges, step_y)]
        row_values = [value + step for value, step in zip(row_values, grad_y)]


def draw(tri, color_buffer, depth, texture, width=p.WIDTH):
    """Draws into a bytes-like colour buffer, a list of depth values and a 2048 x 256 byte texture store."""
    use_depth = tri.mode & MODE_DEPTH
    use_texture = tri.mode & MODE_TEXTURE
    mask = (1 << tri.tex_size) - 1
    for x, y, color, z, u, v in pixels(tri):
        at = y * width + x
        if use_depth and z >= depth[at]:
            continue
        if use_texture:
            row = (tri.tex_row + (v & mask)) & 0x7FF
            color = texture[row * 256 + (u & mask)]
        color_buffer[at] = color
        if use_depth:
            depth[at] = z
