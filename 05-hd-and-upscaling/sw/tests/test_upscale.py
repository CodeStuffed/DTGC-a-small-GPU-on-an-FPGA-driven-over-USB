"""Usage: python -m unittest sw.tests.test_upscale"""
import unittest

import numpy as np

from sw.dtgc import upscale as u


def noise(height=24, width=32, seed=1):
    return np.random.default_rng(seed).integers(0, 256, (height, width, 3), dtype=np.uint8)


class Weights(unittest.TestCase):
    def test_always_sum_to_one(self):
        for scale in (2, 3, 4):
            for phase in range(scale):
                self.assertEqual(sum(u.catmull_rom_weights(phase, scale)), u.ONE)

    def test_phase_zero_is_the_pixel_itself(self):
        self.assertEqual(u.catmull_rom_weights(0, 3), [0, 256, 0, 0])

    def test_halfway_is_symmetrical(self):
        self.assertEqual(u.catmull_rom_weights(1, 2), [-16, 144, 144, -16])


class Upscale(unittest.TestCase):
    def test_size_and_type(self):
        for method in u.METHODS:
            for scale in (1, 2, 3):
                out = u.upscale(noise(), scale, method)
                self.assertEqual(out.shape, (24 * scale, 32 * scale, 3))
                self.assertEqual(out.dtype, np.uint8)

    def test_flat_colour_stays_flat(self):
        flat = np.full((16, 16, 3), 123, dtype=np.uint8)
        for method in u.METHODS:
            for sharpen in (0, 2):
                self.assertTrue((u.upscale(flat, 3, method, sharpen) == 123).all(), method)

    def test_centre_pixels_survive(self):
        # At 3 times, the middle output pixel of each block sits exactly on its input pixel.
        small = noise()
        for method in u.METHODS:
            big = u.upscale(small, 3, method)
            self.assertTrue((big[1::3, 1::3] == small).all(), method)

    def test_block_average_comes_back_from_a_smooth_picture(self):
        # Shrinking what was scaled up should nearly return the input. A half-pixel shift would not.
        y, x = np.mgrid[0:64, 0:64]
        ramp = np.stack([x * 2, y * 2, x + y], axis=2).astype(np.uint8)
        for method in u.METHODS:
            for scale in (2, 3):
                back = u.downscale(u.upscale(ramp, scale, method), scale)
                self.assertLessEqual(int(np.abs(back[4:-4, 4:-4].astype(int) - ramp[4:-4, 4:-4]).max()), 1, method)

    def test_smoothing_beats_repeating_on_a_smooth_picture(self):
        y, x = np.mgrid[0:240, 0:240]
        smooth = (128 + 100 * np.stack([np.sin(x / 15), np.sin(y / 11), np.sin((x + y) / 19)], axis=2)).astype(np.uint8)
        small = u.downscale(smooth, 2)
        repeated = u.psnr(smooth, u.upscale(small, 2, "nearest"))
        for method in ("bilinear", "bicubic", "edge"):
            self.assertGreater(u.psnr(smooth, u.upscale(small, 2, method)), repeated, method)

    def test_scale_one_changes_nothing(self):
        small = noise()
        for method in u.METHODS:
            self.assertTrue((u.upscale(small, 1, method) == small).all(), method)

    def test_extremes_clamp_instead_of_wrapping(self):
        # Black next to white makes the bicubic overshoot, and that must stop at 0 and 255.
        bars = np.zeros((8, 8, 3), dtype=np.uint8)
        bars[:, 4:] = 255
        big = u.upscale(bars, 3, "bicubic", 4)
        row = big[10, :, 0].astype(int)
        self.assertTrue((np.diff(row) >= 0).all(), row)

    def test_edge_follows_a_diagonal(self):
        # A diagonal edge: the edge method must blend along it, so there is no wrong-way blend across it.
        size = 12
        picture = np.zeros((size, size, 3), dtype=np.uint8)
        for y in range(size):
            picture[y, y:] = 200
        big = u.upscale(picture, 2, "edge")
        self.assertEqual(int(big[8, 14, 0]), 200)   # upper-right side of the line stays bright
        self.assertEqual(int(big[14, 8, 0]), 0)     # lower-left side of the line stays dark

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            u.upscale(noise(), 2, "magic")
        with self.assertRaises(ValueError):
            u.upscale(noise(), 0)


class Scores(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(u.psnr(noise(), noise()), float("inf"))
        self.assertAlmostEqual(u.ssim(noise(), noise()), 1.0)

    def test_worse_picture_scores_lower(self):
        reference = noise()
        slightly = np.clip(reference.astype(int) + 4, 0, 255).astype(np.uint8)
        self.assertGreater(u.psnr(reference, slightly), u.psnr(reference, noise(seed=2)))
        self.assertGreater(u.ssim(reference, slightly), u.ssim(reference, noise(seed=2)))

    def test_known_psnr(self):
        a = np.zeros((8, 8, 3), dtype=np.uint8)
        b = np.full((8, 8, 3), 255, dtype=np.uint8)
        self.assertAlmostEqual(u.psnr(a, b), 0.0)

    def test_downscale_averages(self):
        tile = np.array([[[0, 0, 0], [100, 100, 100]], [[100, 100, 100], [200, 200, 200]]], dtype=np.uint8)
        self.assertEqual(u.downscale(tile, 2).tolist(), [[[100, 100, 100]]])


if __name__ == "__main__":
    unittest.main()
