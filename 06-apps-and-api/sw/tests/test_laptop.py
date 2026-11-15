"""Tests of the laptop version: on the PC's real graphics card, so they open a small window for a moment.

Usage: python -m unittest sw.tests.test_laptop

Without a graphics driver (a GitHub runner, or not Windows) the tests that need a window are skipped.
"""
import sys
import unittest

import numpy as np

from sw.dtgc import emulator
from sw.dtgc import protocol as p
from sw.dtgc import raster
from sw.dtgc.api import Canvas, Mesh
from sw.dtgc.client import Dtgc

try:
    from sw.dtgc import glwindow, laptop
    WINDOW_ERROR = None
except ImportError as error:
    WINDOW_ERROR = str(error)


@unittest.skipIf(WINDOW_ERROR, WINDOW_ERROR or "")
class Fit(unittest.TestCase):
    def test_picture_fills_the_short_side_on_any_screen(self):
        self.assertEqual(laptop.fit_picture(1920, 1080), (420, 0, 1080, 1080))
        self.assertEqual(laptop.fit_picture(3840, 2160), (840, 0, 2160, 2160))
        self.assertEqual(laptop.fit_picture(7680, 4320), (1680, 0, 4320, 4320))
        self.assertEqual(laptop.fit_picture(800, 1280), (0, 240, 800, 800))
        self.assertEqual(laptop.fit_picture(0, 0)[2:], (1, 1))


@unittest.skipIf(WINDOW_ERROR, WINDOW_ERROR or "")
class SharpWithoutWindow(unittest.TestCase):
    def test_rect_before_triangles_goes_to_the_picture_and_after_them_stays_on_top(self):
        device = laptop.SharpDevice()
        gpu = laptop.LocalGpu(device)
        gpu.rect(0, 0, 10, 10, 0xE0)
        self.assertEqual(device.back[0], 0xE0)
        vertex = raster.Vertex(0, 0, 0, 255, 255, 255, 0, 0)
        gpu.triangle(raster.Triangle(0, 0, 0, vertex, vertex._replace(x=320), vertex._replace(y=320)))
        gpu.rect(20, 20, 5, 5, 0x1C)
        self.assertEqual(device.back[20 * p.WIDTH + 20], 0)
        self.assertEqual([batch[0] for batch in device.batches], [0, -1])
        gpu.swap()
        self.assertEqual(device.batches, [])
        self.assertEqual(len(device.shown_batches), 2)

    def test_bad_triangles_and_lengths_are_refused_like_the_hardware(self):
        device = laptop.SharpDevice()
        self.assertEqual(device.execute(p.TRIANGLE, b"short"), p.STATUS_BAD_LENGTH)
        vertex = raster.Vertex(20000, 0, 0, 0, 0, 0, 0, 0)
        tri = raster.Triangle(0, 0, 0, vertex, vertex, vertex)
        self.assertEqual(device.execute(p.TRIANGLE, raster.payload(tri)), p.STATUS_BAD_VALUE)

    def test_speaks_the_real_protocol(self):
        device = laptop.SharpDevice()
        replies = device.feed(p.encode(p.HELLO, 0) + p.encode(p.RECT, 1, p.rect_payload(0, 0, 4, 4, 9)) + p.encode(p.SWAP, 2))
        parser = p.Parser()
        statuses = [packet.payload[1] for packet in (parser.feed(b) for b in replies) if packet]
        self.assertEqual(statuses, [p.STATUS_OK] * 3)
        self.assertEqual(device.buffers[device.front][0], 9)


@unittest.skipIf(WINDOW_ERROR, WINDOW_ERROR or "")
class OnTheGraphicsCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.window = glwindow.Window("DTGC test", 700, 500, vsync=False, samples=0)
        except OSError as error:
            raise unittest.SkipTest(str(error))
        cls.width, cls.height = cls.window.size()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def _draw(self, device, width=None, height=None):
        self.window.poll()
        renderer = laptop.Renderer(device)
        width, height = width or self.width, height or self.height
        renderer.draw(width, height)
        return laptop.read_window(width, height)

    def test_exact_picture_is_the_emulators_picture_at_one_to_one(self):
        device = emulator.Device()
        gpu = laptop.LocalGpu(device)
        rng = np.random.default_rng(1)
        gpu.image(rng.integers(0, 256, p.WIDTH * p.HEIGHT, dtype=np.uint8).tobytes())
        gpu.swap()
        pixels = self._draw(device, p.WIDTH, p.HEIGHT)
        # Read from the bottom-left corner, which is where a viewport smaller than the window starts.
        wanted = np.frombuffer(device.window_rgb(), dtype=np.uint8).reshape(p.HEIGHT, p.WIDTH, 3)
        self.assertTrue(np.array_equal(pixels, wanted))

    def test_picture_is_centred_with_black_bars(self):
        device = emulator.Device()
        gpu = laptop.LocalGpu(device)
        gpu.clear(0xFF)
        gpu.swap()
        pixels = self._draw(device)
        x, y, size, _ = laptop.fit_picture(self.width, self.height)
        self.assertTrue((pixels[y:y + size, x:x + size] == 255).all())
        if x:
            self.assertTrue((pixels[:, :x] == 0).all())
            self.assertTrue((pixels[:, x + size:] == 0).all())

    def test_sharp_triangles_cover_almost_the_same_pixels_as_the_exact_ones(self):
        # The two ways of drawing are not meant to match bit for bit, but they must show the same shapes.
        exact, sharp = emulator.Device(), laptop.SharpDevice()
        for device in (exact, sharp):
            canvas = Canvas(laptop.LocalGpu(device))
            canvas.clear_scene(0)
            canvas.draw_mesh(Mesh.cube(1.0), angle_x=0.5, angle_y=0.7, distance=4.0)
            canvas.show()
        first = self._draw(exact, p.WIDTH, p.HEIGHT).any(axis=2)
        second = self._draw(sharp, p.WIDTH, p.HEIGHT).any(axis=2)
        self.assertGreater(first.sum(), 5000)
        self.assertLess((first != second).mean(), 0.01)

    def test_depth_keeps_the_nearer_triangle_whatever_order_they_come(self):
        def triangle(z, r, g, b):
            vertex = raster.Vertex(0, 0, z, r, g, b, 0, 0)
            return raster.Triangle(raster.MODE_DEPTH, 0, 0, vertex, vertex._replace(x=5440), vertex._replace(y=5440))

        near, far = triangle(1000, 255, 0, 0), triangle(50000, 0, 255, 0)
        for order in ((near, far), (far, near)):
            device = laptop.SharpDevice()
            gpu = laptop.LocalGpu(device)
            for tri in order:
                gpu.triangle(tri)
            gpu.swap()
            pixels = self._draw(device, p.WIDTH, p.HEIGHT)
            self.assertEqual(tuple(pixels[50, 50]), (255, 0, 0))

    def test_textured_triangle_shows_the_texture(self):
        device = laptop.SharpDevice()
        gpu = laptop.LocalGpu(device)
        gpu.texture_rows(0, 4, bytes([0xE0] * 16))
        vertex = raster.Vertex(0, 0, 0, 0, 0, 0, 0, 0)
        gpu.triangle(raster.Triangle(raster.MODE_TEXTURE, 0, 2, vertex, vertex._replace(x=1600), vertex._replace(y=1600)))
        gpu.swap()
        pixels = self._draw(device, p.WIDTH, p.HEIGHT)
        self.assertEqual(tuple(pixels[10, 10]), tuple(device.palette[0xE0]))

    def test_usb_output_window_shows_what_the_board_drew(self):
        device = emulator.Device()
        gpu = Dtgc(emulator.LocalTransport(device))
        gpu.palette(0x40, [(1, 2, 3)])
        gpu.rect(0, 0, p.WIDTH, p.HEIGHT, 0x03)
        gpu.rect(5, 6, 1, 1, 0x40)
        gpu.swap()
        screen = laptop.ReadBackScreen()
        screen.show(gpu.read_frame(), gpu.colors_set)
        pixels = self._draw(screen, p.WIDTH, p.HEIGHT)
        self.assertEqual(tuple(pixels[0, 0]), tuple(device.palette[0x03]))
        self.assertEqual(tuple(pixels[6, 5]), (1, 2, 3))

    def test_the_card_is_a_real_driver_name(self):
        self.assertTrue(self.window.renderer)
        print(f"\n  graphics card: {self.window.renderer}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
