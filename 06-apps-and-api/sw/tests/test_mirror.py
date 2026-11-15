"""Tests of screen mirroring, against the emulator.

Usage: python -m unittest sw.tests.test_mirror
"""
import unittest

from PIL import Image

from sw.dtgc import emulator
from sw.dtgc import mirror
from sw.dtgc import protocol as p
from sw.dtgc.client import Dtgc


def fake_screen(frame=0):
    """A desktop-like picture: a plain background, and a white window that moves."""
    image = Image.new("RGB", (1920, 1080), (20, 60, 120))
    image.paste((240, 240, 240), (200 + frame * 8, 200, 1000 + frame * 8, 800))
    return image


class Mirror(unittest.TestCase):
    def test_wide_screen_keeps_its_shape(self):
        frame = mirror.fit_to_frame(Image.new("RGB", (1920, 1080), (255, 255, 255)))
        self.assertEqual(frame.size, (p.WIDTH, p.HEIGHT))
        self.assertEqual(frame.getpixel((170, 0)), (0, 0, 0))             # bar above
        self.assertEqual(frame.getpixel((170, 170)), (255, 255, 255))     # picture
        self.assertEqual(frame.getpixel((170, 339)), (0, 0, 0))           # bar below

    def test_tall_screen_keeps_its_shape(self):
        frame = mirror.fit_to_frame(Image.new("RGB", (1080, 1920), (255, 255, 255)))
        self.assertEqual(frame.getpixel((0, 170)), (0, 0, 0))
        self.assertEqual(frame.getpixel((170, 170)), (255, 255, 255))

    def test_exact_colours(self):
        for dither in (False, True):
            for colour, want in (((0, 0, 0), 0x00), ((255, 255, 255), 0xFF), ((255, 0, 0), 0xE0),
                                 ((0, 255, 0), 0x1C), ((0, 0, 255), 0x03)):
                pixels = mirror.to_pixels(Image.new("RGB", (p.WIDTH, p.HEIGHT), colour), dither)
                self.assertEqual(set(pixels), {want}, (colour, dither))

    def test_dither_adds_levels_to_shading(self):
        ramp = Image.linear_gradient("L").resize((p.WIDTH, p.HEIGHT)).convert("RGB")
        plain = mirror.to_pixels(ramp, False)
        mixed = mirror.to_pixels(ramp, True)
        self.assertEqual(len(plain), p.WIDTH * p.HEIGHT)
        # Average brightness along a row should follow the ramp more closely with dithering.
        def error(pixels):
            total = 0
            for y in range(0, p.HEIGHT, 4):
                row = pixels[y * p.WIDTH:(y + 1) * p.WIDTH]
                total += abs(sum(v >> 5 for v in row) / p.WIDTH / 7 * 255 - ramp.getpixel((0, y))[0])
            return total
        self.assertLess(error(mixed), error(plain))

    def test_what_arrives_is_what_was_captured(self):
        device = emulator.Device()
        gpu = Dtgc(emulator.LocalTransport(device))
        frames = iter(range(6))
        current = [None]

        def grab():
            current[0] = fake_screen(next(frames))
            return current[0]

        for count in range(1, 7):
            if count == 1:
                stream = mirror.FrameStreamer(gpu)
            pixels = mirror.to_pixels(mirror.fit_to_frame(grab()))
            stream.send_frame(pixels)
            self.assertEqual(bytes(device.buffers[device.front]), pixels)
        gpu.close()

    def test_run_stops_after_the_frames_asked_for(self):
        device = emulator.Device()
        gpu = Dtgc(emulator.LocalTransport(device))
        lines = []
        done, sent = mirror.run(gpu, frames=4, fps=1000, grab=fake_screen, out=lines.append)
        self.assertEqual(done, 4)
        self.assertGreater(sent, 0)
        self.assertIn("Mirrored 4 frames", lines[-1])
        gpu.close()


if __name__ == "__main__":
    unittest.main()
