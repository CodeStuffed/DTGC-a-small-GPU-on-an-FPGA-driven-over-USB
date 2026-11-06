"""Tests of the reference triangle renderer against rules worked out separately from its code.

Usage: python -m unittest sw.tests.test_raster

If the reference were wrong, the Verilog could match it perfectly and still be wrong, so these tests
compare it with plain floating-point maths and with properties any correct renderer must have.
"""
import random
import unittest

from sw.dtgc import raster
from sw.dtgc.raster import MODE_DEPTH, MODE_TEXTURE, Triangle, Vertex, draw, pixels, valid
from sw.tests.streams import random_triangle


def vertex(x, y, z=0, r=0, g=0, b=0, u=0, v=0):
    """x and y in whole pixels; the renderer's 1/16 pixel units are handled here."""
    return Vertex(round(x * 16), round(y * 16), z, r, g, b, u, v)


def flat(a, b, c):
    return Triangle(0, 0, 0, vertex(*a), vertex(*b), vertex(*c))


def covered(triangle):
    return {(x, y) for x, y, *_ in pixels(triangle)}


def float_inside(tri, px, py):
    """Exact-enough float test of a pixel centre. None if it is too close to an edge to call."""
    points = [(tri.v0.x / 16, tri.v0.y / 16), (tri.v1.x / 16, tri.v1.y / 16), (tri.v2.x / 16, tri.v2.y / 16)]
    cx, cy = px + 0.5, py + 0.5
    results = []
    for i in range(3):
        ax, ay = points[i]
        bx, by = points[(i + 1) % 3]
        results.append((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    if any(abs(r) < 1e-9 for r in results):
        return None
    return all(r > 0 for r in results) or all(r < 0 for r in results)


class Coverage(unittest.TestCase):
    def test_matches_float_geometry(self):
        rng = random.Random(1)
        for _ in range(300):
            tri = flat(*[(rng.uniform(-20, 120), rng.uniform(-20, 120)) for _ in range(3)])
            got = covered(tri)
            for y in range(0, 100):
                for x in range(0, 100):
                    want = float_inside(tri, x, y)
                    if want is not None:
                        self.assertEqual((x, y) in got, want, f"{tri} at {x},{y}")

    def test_shared_edge_has_no_gaps_or_double_draws(self):
        """A fan of triangles fills a rectangle. Every vertex sits on a pixel centre, so many edges
        run exactly through pixel centres, the hardest case. Each pixel must be drawn exactly once."""
        rng = random.Random(2)
        for _ in range(100):
            x0, y0 = rng.randrange(0, 150), rng.randrange(0, 150)
            x1, y1 = x0 + rng.randrange(20, 150), y0 + rng.randrange(20, 150)
            center = (rng.randrange(x0 + 1, x1) + 0.5, rng.randrange(y0 + 1, y1) + 0.5)
            top = [(x, y0) for x in sorted(rng.sample(range(x0 + 1, x1), 3))]
            right = [(x1, y) for y in sorted(rng.sample(range(y0 + 1, y1), 3))]
            bottom = [(x, y1) for x in sorted(rng.sample(range(x0 + 1, x1), 3), reverse=True)]
            left = [(x0, y) for y in sorted(rng.sample(range(y0 + 1, y1), 3), reverse=True)]
            rim = [(x0, y0), *top, (x1, y0), *right, (x1, y1), *bottom, (x0, y1), *left]
            rim = [(x + 0.5, y + 0.5) for x, y in rim]
            seen = {}
            for a, b in zip(rim, rim[1:] + rim[:1]):
                # Mixed winding too, as an application might send them.
                triangle = flat(center, a, b) if rng.random() < 0.5 else flat(center, b, a)
                for spot in covered(triangle):
                    seen[spot] = seen.get(spot, 0) + 1
            self.assertEqual(set(seen.values()), {1}, "a pixel was drawn twice")
            self.assertEqual(set(seen), {(x, y) for x in range(x0, x1) for y in range(y0, y1)},
                             "the fan left a gap or went outside the rectangle")

    def test_square_of_two_triangles(self):
        a = covered(flat((10, 10), (20, 10), (20, 20)))
        b = covered(flat((10, 10), (20, 20), (10, 20)))
        self.assertFalse(a & b)
        self.assertEqual(a | b, {(x, y) for x in range(10, 20) for y in range(10, 20)})

    def test_winding_does_not_change_coverage(self):
        self.assertEqual(covered(flat((3, 4), (50, 9), (20, 60))), covered(flat((3, 4), (20, 60), (50, 9))))

    def test_nothing_from_degenerate_or_off_screen(self):
        self.assertEqual(covered(flat((5, 5), (5, 5), (5, 5))), set())
        self.assertEqual(covered(flat((0, 0), (10, 10), (20, 20))), set())
        self.assertEqual(covered(flat((-50, -50), (-10, -50), (-10, -10))), set())
        self.assertEqual(covered(flat((400, 10), (500, 10), (400, 100))), set())

    def test_clipped_exactly_to_the_picture(self):
        big = flat((-1000, -400), (1000, -400), (170, 1000))  # contains the whole picture
        got = covered(big)
        self.assertEqual(len(got), 340 * 340)

    def test_no_pixel_ever_outside_the_picture(self):
        rng = random.Random(3)
        for _ in range(500):
            for x, y, *_ in pixels(random_triangle(rng)):
                self.assertTrue(0 <= x < 340 and 0 <= y < 340)

    def test_range_limits(self):
        good = flat((0, 0), (1, 0), (0, 1))
        self.assertTrue(valid(good))
        self.assertFalse(valid(good._replace(v0=good.v0._replace(x=16384))))
        self.assertTrue(valid(good._replace(v0=good.v0._replace(x=-16384))))
        self.assertFalse(valid(good._replace(v2=good.v2._replace(y=-16385))))
        self.assertFalse(valid(good._replace(tex_size=9)))


class Interpolation(unittest.TestCase):
    def float_plane(self, tri, name, px, py):
        """Barycentric value at a pixel centre, the textbook way."""
        x0, y0 = tri.v0.x / 16, tri.v0.y / 16
        x1, y1 = tri.v1.x / 16, tri.v1.y / 16
        x2, y2 = tri.v2.x / 16, tri.v2.y / 16
        denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        a = ((y1 - y2) * (px + 0.5 - x2) + (x2 - x1) * (py + 0.5 - y2)) / denominator
        b = ((y2 - y0) * (px + 0.5 - x2) + (x0 - x2) * (py + 0.5 - y2)) / denominator
        c = 1 - a - b
        return a * getattr(tri.v0, name) + b * getattr(tri.v1, name) + c * getattr(tri.v2, name)

    def test_planes_match_float_maths(self):
        rng = random.Random(4)
        tested = 0
        for _ in range(200):
            points = [(rng.uniform(0, 340), rng.uniform(0, 340)) for _ in range(3)]
            tri = Triangle(0, 0, 0, *[vertex(x, y, rng.randrange(65536), *rng.randbytes(5)) for x, y in points])
            area = abs((tri.v1.x - tri.v0.x) * (tri.v2.y - tri.v0.y) - (tri.v2.x - tri.v0.x) * (tri.v1.y - tri.v0.y))
            if area < 16 * 16 * 200:
                continue  # thin triangles have larger rounding: checked for limits elsewhere
            for x, y, color, z, u, v in pixels(tri):
                self.assertAlmostEqual(z, self.float_plane(tri, "z", x, y), delta=2.0)
                self.assertAlmostEqual(u, self.float_plane(tri, "u", x, y), delta=1.5)
                self.assertAlmostEqual(v, self.float_plane(tri, "v", x, y), delta=1.5)
                self.assertAlmostEqual(color >> 5, self.float_plane(tri, "r", x, y) / 32, delta=1.1)
                tested += 1
        self.assertGreater(tested, 100000)

    def test_flat_colour_is_exact(self):
        tri = Triangle(0, 0, 0, vertex(0, 0, 500, 200, 100, 50), vertex(300, 7, 500, 200, 100, 50),
                       vertex(30, 300, 500, 200, 100, 50))
        want_color = (200 & 0xE0) | ((100 >> 3) & 0x1C) | (50 >> 6)
        for _, _, color, z, _, _ in pixels(tri):
            self.assertEqual(color, want_color)
            self.assertEqual(z, 500)

    def test_dither_follows_the_pattern_and_stops_at_white(self):
        tri = Triangle(raster.MODE_DITHER, 0, 0, vertex(0, 0, 0, 100, 100, 100), vertex(320, 0, 0, 100, 100, 100),
                       vertex(0, 320, 0, 100, 100, 100))
        for x, y, color, _, _, _ in pixels(tri):
            level = raster.BAYER[y & 3][x & 3]
            near = 100 - (100 >> 3) + level * 2
            self.assertEqual(color, (near & 0xE0) | ((near >> 3) & 0x1C) | ((100 - (100 >> 2) + level * 4) >> 6))
        tri = Triangle(raster.MODE_DITHER, 0, 0, vertex(0, 0, 0, 255, 255, 255), vertex(320, 0, 0, 255, 255, 255),
                       vertex(0, 320, 0, 255, 255, 255))
        self.assertEqual({color for _, _, color, _, _, _ in pixels(tri)}, {255})

    def test_dither_pattern_uses_each_level_once(self):
        self.assertEqual(sorted(sum(raster.BAYER, ())), list(range(16)))

    def test_values_stay_in_range_on_tiny_triangles(self):
        rng = random.Random(5)
        for _ in range(2000):
            x, y = rng.randrange(5000), rng.randrange(5000)
            v0 = Vertex(x, y, 65535, 255, 0, 255, 0, 255)
            v1 = Vertex(x + rng.randrange(1, 6), y + rng.randrange(0, 3), 0, 0, 255, 0, 255, 0)
            v2 = Vertex(x + rng.randrange(0, 3), y + rng.randrange(1, 6), 30000, 9, 9, 9, 9, 9)
            for _, _, color, z, u, v in pixels(Triangle(0, 0, 0, v0, v1, v2)):
                self.assertTrue(0 <= color <= 255 and 0 <= z <= 65535 and 0 <= u <= 255 and 0 <= v <= 255)


class DepthAndTexture(unittest.TestCase):
    def setUp(self):
        self.color = bytearray(340 * 340)
        self.depth = [65535] * (340 * 340)
        self.texture = bytearray(2048 * 256)

    def square(self, z, color, mode=MODE_DEPTH):
        r, g, b = color
        corners = [(10, 10), (60, 10), (60, 60), (10, 60)]
        for a, c in ((1, 2), (2, 3)):
            tri = Triangle(mode, 0, 0, vertex(*corners[0], z, r, g, b), vertex(*corners[a], z, r, g, b),
                           vertex(*corners[c], z, r, g, b))
            draw(tri, self.color, self.depth, self.texture)

    def test_nearer_wins_in_either_order(self):
        self.square(100, (255, 0, 0))
        self.square(200, (0, 255, 0))
        self.assertEqual(self.color[20 * 340 + 20], 0xE0)
        self.square(50, (0, 0, 255))
        self.assertEqual(self.color[20 * 340 + 20], 0x03)

    def test_equal_depth_keeps_the_first(self):
        self.square(100, (255, 0, 0))
        self.square(100, (0, 255, 0))
        self.assertEqual(self.color[20 * 340 + 20], 0xE0)

    def test_depth_off_ignores_depth(self):
        self.square(100, (255, 0, 0))
        self.square(200, (0, 255, 0), mode=0)
        self.assertEqual(self.color[20 * 340 + 20], 0x1C)
        self.assertEqual(self.depth[20 * 340 + 20], 100)

    def test_texture_lookup(self):
        for row in range(16):
            for column in range(16):
                self.texture[(5 + row) * 256 + column] = row * 16 + column
        tri = Triangle(MODE_TEXTURE, 5, 4,
                       Vertex(0, 0, 0, 0, 0, 0, 0, 0),
                       Vertex(320, 0, 0, 0, 0, 0, 20, 0),
                       Vertex(0, 320, 0, 0, 0, 0, 0, 20))
        draw(tri, self.color, self.depth, self.texture)
        # u and v rise by one per pixel, so pixel (3, 2) shows texel (3, 2).
        self.assertEqual(self.color[2 * 340 + 3], 2 * 16 + 3)

    def test_texture_size_masks_coordinates(self):
        self.texture[0] = 7
        tri = Triangle(MODE_TEXTURE, 0, 0,
                       Vertex(0, 0, 0, 0, 0, 0, 200, 200),
                       Vertex(320, 0, 0, 0, 0, 0, 200, 200),
                       Vertex(0, 320, 0, 0, 0, 0, 200, 200))
        draw(tri, self.color, self.depth, self.texture)
        self.assertEqual(self.color[0], 7)


if __name__ == "__main__":
    unittest.main()
