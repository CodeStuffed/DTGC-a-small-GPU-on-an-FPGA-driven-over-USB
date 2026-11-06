"""Spinning 3D cube, drawn with TRIANGLE commands.

Usage: python -m sw.dtgc spin [--frames N]    (uses a connected GPU, or a running emulator)

Each corner gets its own colour, brightened by how directly its face points at a light. The GPU blends
those colours across each triangle, tests depth and dithers. All the 3D maths runs on the PC.
"""
import math
import time

from . import protocol as p
from . import raster
from .api import Canvas

MODE = raster.MODE_DEPTH | raster.MODE_DITHER
BACKGROUND = 0x25
CENTRE_X, CENTRE_Y = p.WIDTH // 2, p.HEIGHT // 2
CAMERA = 4.2  # distance from the viewer to the middle of the cube
FOCAL = 220.0 * p.HEIGHT / 340  # larger makes the cube look bigger on screen
AMBIENT = 0.3  # brightness of a face turned away from the light
LIGHT = (-0.45, -0.6, -0.66)  # direction towards the light

CORNERS = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def rotate(point, angle):
    x, y, z = point
    x, z = x * math.cos(angle) + z * math.sin(angle), -x * math.sin(angle) + z * math.cos(angle)
    tilt = angle * 0.6 + 0.5
    y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
    return x, y, z


def _cross(a, b):
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _minus(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def triangles(angle):
    """The triangles of one frame. Faces turned away from the viewer are left out."""
    moved = [rotate(c, angle) for c in CORNERS]
    out = []
    for face in FACES:
        points = [moved[i] for i in face]
        normal = _cross(_minus(points[1], points[0]), _minus(points[2], points[0]))
        length = math.sqrt(sum(n * n for n in normal))
        normal = [n / length for n in normal]
        middle = [sum(p[i] for p in points) / 4 for i in range(3)]
        to_viewer = (-middle[0], -middle[1], -CAMERA - middle[2])
        if sum(n * v for n, v in zip(normal, to_viewer)) <= 0:
            continue
        light = AMBIENT + (1 - AMBIENT) * max(0.0, sum(n * l for n, l in zip(normal, LIGHT)))
        vertices = []
        for index in face:
            x, y, z = moved[index]
            scale = FOCAL / (CAMERA + z)
            # Corner colours run from dark to bright on each axis, so every face is a smooth blend.
            r, g, b = [round(255 * light * (c + 1) / 2 * 0.8 + 255 * light * 0.2) for c in CORNERS[index]]
            depth = max(0, min(65535, round((z + 2) / 4 * 65535)))
            vertices.append(raster.Vertex(round((CENTRE_X + x * scale) * 16), round((CENTRE_Y + y * scale) * 16),
                                          depth, r, g, b, 0, 0))
        out.append(raster.Triangle(MODE, 0, 0, vertices[0], vertices[1], vertices[2]))
        out.append(raster.Triangle(MODE, 0, 0, vertices[0], vertices[2], vertices[3]))
    return out


def draw_frame(canvas, angle):
    canvas.clear_scene(BACKGROUND)
    for triangle in triangles(angle):
        canvas.draw(triangle)
    canvas.show()


def draw_field_frame(canvas, field):
    field.draw(canvas)
    field.step(None)
    canvas.show()


def run(gpu, frames=150, step=0.08, scene="cube"):
    """Draws the frames, then prints the rate. On the emulator the rate only describes this PC."""
    gpu.hello()
    canvas = Canvas(gpu)
    if scene == "field":
        from .laptop import Field
        field = Field()
    start = time.monotonic()
    for frame in range(frames):
        if scene == "field":
            draw_field_frame(canvas, field)
        else:
            draw_frame(canvas, frame * step)
    gpu.flush()
    seconds = time.monotonic() - start
    print(f"{frames} frames in {seconds:.2f} s, {frames / seconds:.1f} frames per second")
