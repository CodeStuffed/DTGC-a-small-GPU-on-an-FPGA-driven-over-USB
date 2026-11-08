"""The DTGC graphics API: what a game or program draws with. Guide: docs/api.md.

Usage:
    from sw.dtgc.api import Canvas, Mesh, rgb
    canvas = Canvas(gpu)
    canvas.clear(rgb(0, 0, 85))
    canvas.text(10, 10, "SCORE 3", rgb(255, 255, 255))
    canvas.draw_mesh(Mesh.cube(), angle_y=0.5, distance=4)
    canvas.show()

The picture is 340 x 340 with 256 colours. All the 3D maths runs on the PC, and the GPU fills the triangles.
"""
import math
from collections import namedtuple

from . import protocol as p
from . import raster

WIDTH, HEIGHT = p.WIDTH, p.HEIGHT
_FOCAL = 220.0 * HEIGHT / 340  # scenes fill the same part of a picture of any height
_NEAR = 0.2
_FAR = 40.0

# Capital letters and digits, 3 pixels wide and 5 tall. Each number is one row, top row first.
_FONT = {
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (7, 1, 7, 4, 7), "3": (7, 1, 3, 1, 7), "4": (5, 5, 7, 1, 1),
    "5": (7, 4, 7, 1, 7), "6": (7, 4, 7, 5, 7), "7": (7, 1, 2, 2, 2), "8": (7, 5, 7, 5, 7), "9": (7, 5, 7, 1, 7),
    "A": (2, 5, 7, 5, 5), "B": (6, 5, 6, 5, 6), "C": (3, 4, 4, 4, 3), "D": (6, 5, 5, 5, 6), "E": (7, 4, 6, 4, 7),
    "F": (7, 4, 6, 4, 4), "G": (3, 4, 5, 5, 3), "H": (5, 5, 7, 5, 5), "I": (7, 2, 2, 2, 7), "J": (1, 1, 1, 5, 2),
    "K": (5, 5, 6, 5, 5), "L": (4, 4, 4, 4, 7), "M": (5, 7, 7, 5, 5), "N": (6, 5, 5, 5, 5), "O": (2, 5, 5, 5, 2),
    "P": (6, 5, 6, 4, 4), "Q": (2, 5, 5, 6, 3), "R": (6, 5, 6, 5, 5), "S": (3, 4, 2, 1, 6), "T": (7, 2, 2, 2, 2),
    "U": (5, 5, 5, 5, 7), "V": (5, 5, 5, 5, 2), "W": (5, 5, 7, 7, 5), "X": (5, 5, 2, 5, 5), "Y": (5, 5, 2, 2, 2),
    "Z": (7, 1, 2, 4, 7), "-": (0, 0, 7, 0, 0), ".": (0, 0, 0, 0, 2), ":": (0, 2, 0, 2, 0), " ": (0, 0, 0, 0, 0),
}


def rgb(r, g, b):
    """A colour from 0-255 parts, as an index into the default palette (3 bits red and green, 2 blue).

    Parts round down: red or green under 32 and blue under 64 come out as none at all.
    """
    return (r & 0xE0) | ((g >> 3) & 0x1C) | (b >> 6)


def text_width(text, size=2):
    return len(text) * 4 * size - size


class Mesh(namedtuple("Mesh", "vertices triangles")):
    """vertices: (x, y, z). triangles: (a, b, c, (r, g, b)), corners counter-clockwise seen from outside."""

    @staticmethod
    def cube(size=1.0, colors=None):
        s = size
        vertices = [(x, y, z) for x in (-s, s) for y in (-s, s) for z in (-s, s)]
        colors = colors or [(230, 70, 60), (70, 200, 90), (70, 110, 230), (230, 200, 60), (200, 80, 210), (70, 200, 210)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        triangles = []
        for face, color in zip(faces, colors):
            triangles.append((face[0], face[1], face[2], color))
            triangles.append((face[0], face[2], face[3], color))
        return Mesh(vertices, triangles)


def _turn(point, angle_x, angle_y):
    x, y, z = point
    x, z = x * math.cos(angle_y) + z * math.sin(angle_y), -x * math.sin(angle_y) + z * math.cos(angle_y)
    y, z = y * math.cos(angle_x) - z * math.sin(angle_x), y * math.sin(angle_x) + z * math.cos(angle_x)
    return x, y, z


_LIST_LIMIT = 170  # entries of 6 bytes in one packet, which keeps each VERTICES and TRIANGLE_LIST to one


class Canvas:
    def __init__(self, gpu):
        self._gpu = gpu
        self._points = []   # corners and records of draw_mesh, waiting to go out together
        self._records = []
        self.triangles_sent = 0
        # For clear_scene. Each buffer holds (background colour, area drawn over it), or None if unknown.
        self._buffers = [None, None]
        self._back = 0
        self._background = None
        self._drawn = None

    @property
    def gpu(self):
        """Anything else sent to the GPU has to come after the mesh triangles waiting to go."""
        self._send_list()
        return self._gpu

    @gpu.setter
    def gpu(self, gpu):
        self._send_list()
        self._gpu = gpu

    def _send_list(self):
        if self._records:
            self._gpu.vertices(0, self._points)
            self._gpu.triangle_list(raster.MODE_DEPTH | raster.MODE_DITHER, self._records)
            self._points, self._records = [], []

    def clear(self, color=0):
        self.gpu.clear(color)
        self._background = None

    def clear_depth(self):
        self.gpu.clear_depth()

    def clear_scene(self, color=0):
        """Clears picture and depth, sending only the areas earlier frames drew on.

        Much faster than clear and clear_depth when the scene covers part of the screen. It needs all
        drawing to go through this Canvas: anything sent straight to the GPU would not be cleared.
        """
        held = self._buffers[self._back]
        if held is None or held[0] != color:
            self.gpu.clear(color)
        elif held[1]:
            self.gpu.rect(*held[1], color)
        self.gpu.clear_depth()  # a whole-picture depth clear takes the GPU far less time than a rectangle
        self._background, self._drawn = color, None

    def rect(self, x, y, w, h, color):
        """Fills a rectangle. Parts off the picture are dropped, on all four sides."""
        if x < 0:
            x, w = 0, w + x
        if y < 0:
            y, h = 0, h + y
        if w > 0 and h > 0 and x < WIDTH and y < HEIGHT:
            self.gpu.rect(int(x), int(y), int(w), int(h), color)
            self._drawn = _union(self._drawn, (int(x), int(y), min(int(w), WIDTH - int(x)), min(int(h), HEIGHT - int(y))))

    def text(self, x, y, text, color, size=2):
        """Draws text with the built-in font. Unknown characters come out blank. Returns the width."""
        for index, character in enumerate(text.upper()):
            for row, bits in enumerate(_FONT.get(character, _FONT[" "])):
                for column in range(3):
                    if bits & (4 >> column):
                        self.rect(x + (index * 4 + column) * size, y + row * size, size, size, color)
        return text_width(text, size)

    def triangle(self, corners, colors, depth=False, dither=True):
        """corners: 3 (x, y, z) in pixels with z from 0 to 1. colors: 3 (r, g, b) from 0 to 255."""
        mode = (raster.MODE_DEPTH if depth else 0) | (raster.MODE_DITHER if dither else 0)
        vertices = [raster.Vertex(round(x * 16), round(y * 16), round(_limit(z) * 65535), *color, 0, 0)
                    for (x, y, z), color in zip(corners, colors)]
        self._send(raster.Triangle(mode, 0, 0, *vertices))

    def textured_triangle(self, corners, uvs, texture, depth=False):
        """texture is what TextureCache.use returned: (first row, log2 of the side). uvs: 3 (u, v) in texels."""
        mode = raster.MODE_TEXTURE | (raster.MODE_DEPTH if depth else 0)
        vertices = [raster.Vertex(round(x * 16), round(y * 16), round(_limit(z) * 65535), 0, 0, 0, u, v)
                    for (x, y, z), (u, v) in zip(corners, uvs)]
        self._send(raster.Triangle(mode, texture[0], texture[1], *vertices))

    def draw_mesh(self, mesh, position=(0, 0, 0), angle_x=0.0, angle_y=0.0, distance=4.0, light=(-0.45, -0.6, -0.66)):
        """Turns, lights and projects a mesh. Faces pointing away are skipped, so the GPU never sees them."""
        moved = [_turn(v, angle_x, angle_y) for v in mesh.vertices]
        moved = [(x + position[0], y + position[1], z + position[2] + distance) for x, y, z in moved]
        lists = hasattr(self._gpu, "triangle_list")
        slots = {}  # mesh corner to GPU slot, for corners already waiting to go
        for a, b, c, color in mesh.triangles:
            points = moved[a], moved[b], moved[c]
            if min(q[2] for q in points) < _NEAR:
                continue  # no clipping: a triangle reaching behind the viewer is dropped whole
            normal = _normal(*points)
            if sum(n * q for n, q in zip(normal, points[0])) >= 0:
                continue
            bright = 0.3 + 0.7 * max(0.0, sum(n * l for n, l in zip(normal, light)))
            shade = tuple(round(part * bright) for part in color)
            corners = [(WIDTH / 2 + q[0] * _FOCAL / q[2], HEIGHT / 2 + q[1] * _FOCAL / q[2], q[2] / _FAR) for q in points]
            if not all(_fits(corner) for corner in corners):
                continue
            if not lists:
                self.triangle(corners, [shade] * 3, depth=True)
                continue
            if len(self._points) + 3 > _LIST_LIMIT or len(self._records) == _LIST_LIMIT:
                self._send_list()
                slots.clear()
            for index, (x, y, z) in zip((a, b, c), corners):
                if index not in slots:
                    slots[index] = len(self._points)
                    self._points.append((round(x * 16), round(y * 16), round(_limit(z) * 65535)))
            self._records.append((slots[a], slots[b], slots[c], *shade))
            self.triangles_sent += 1
            box = _triangle_box(raster.Triangle(0, 0, 0, *[raster.Vertex(*self._points[slots[i]], 0, 0, 0, 0, 0) for i in (a, b, c)]))
            if box:
                self._drawn = _union(self._drawn, box)

    def show(self):
        """Puts what has been drawn on screen. The new back buffer holds the frame before last, not this one."""
        self.gpu.swap()
        self._buffers[self._back] = None if self._background is None else (self._background, self._drawn)
        self._back = 1 - self._back
        self._background = None

    def finish(self):
        self.gpu.flush()

    def draw(self, triangle):
        """Sends a triangle already in the GPU's own form (sw/dtgc/raster.py)."""
        self.gpu.triangle(triangle)
        self.triangles_sent += 1
        box = _triangle_box(triangle)
        if box:
            self._drawn = _union(self._drawn, box)

    _send = draw


def _union(a, b):
    """The smallest (x, y, w, h) holding both, where None means nothing."""
    if a is None or b is None:
        return a or b
    x, y = min(a[0], b[0]), min(a[1], b[1])
    return x, y, max(a[0] + a[2], b[0] + b[2]) - x, max(a[1] + a[3], b[1] + b[3]) - y


def _triangle_box(triangle):
    """Every pixel the triangle could touch, on the picture. Corners are in sixteenths of a pixel."""
    corners = triangle.v0, triangle.v1, triangle.v2
    left = max(0, min(v.x for v in corners) // 16)
    top = max(0, min(v.y for v in corners) // 16)
    right = min(WIDTH, max(v.x for v in corners) // 16 + 1)
    bottom = min(HEIGHT, max(v.y for v in corners) // 16 + 1)
    return (left, top, right - left, bottom - top) if left < right and top < bottom else None


def _limit(z):
    return max(0.0, min(1.0, z))


def _fits(corner):
    """The GPU refuses coordinates more than 1024 pixels from the origin."""
    return abs(corner[0]) < raster.COORD_LIMIT / 16 and abs(corner[1]) < raster.COORD_LIMIT / 16


def _normal(a, b, c):
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(part * part for part in n)) or 1.0
    return tuple(part / length for part in n)
