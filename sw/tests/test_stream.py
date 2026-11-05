"""Tests of dirty-tile streaming and the asset cache.

Usage: python -m unittest sw.tests.test_stream
"""
import random
import unittest

from sw.dtgc import emulator
from sw.dtgc import protocol as p
from sw.dtgc import raster
from sw.dtgc.assets import AssetCache, CacheFull, TextureCache
from sw.dtgc.client import Dtgc
from sw.dtgc.stream import FrameStreamer
from sw.dtgc.transport import TcpTransport

SIZE = p.WIDTH * p.HEIGHT


class Streaming(unittest.TestCase):
    def setUp(self):
        self.server = emulator.Server(0).start()
        self.gpu = Dtgc(TcpTransport(port=self.server.port))

    def tearDown(self):
        self.gpu.close()
        self.server.stop()

    def shown(self):
        return bytes(self.server.device.buffers[self.server.device.front])

    def test_every_frame_arrives_exact(self):
        """The important one: deltas are compared with the frame before last, not the last one."""
        rng = random.Random(1)
        frame = bytearray(rng.randbytes(SIZE))
        stream = FrameStreamer(self.gpu)
        for _ in range(12):
            for _ in range(rng.randrange(6)):  # small changes in random places
                x, y = rng.randrange(330), rng.randrange(330)
                for row in range(y, y + rng.randrange(1, 10)):
                    frame[row * p.WIDTH + x] = rng.randrange(256)
            stream.send_frame(bytes(frame))
            self.assertEqual(self.shown(), bytes(frame))

    def test_unchanged_frames_send_no_tiles(self):
        stream = FrameStreamer(self.gpu)
        frame = bytes(SIZE)
        self.assertEqual(stream.send_frame(frame), 289)
        self.assertEqual(stream.send_frame(frame), 289)  # the other buffer is still unknown
        self.assertEqual(stream.send_frame(frame), 0)

    def test_one_pixel_sends_one_tile_twice(self):
        stream = FrameStreamer(self.gpu)
        frame = bytearray(SIZE)
        stream.send_frame(bytes(frame))
        stream.send_frame(bytes(frame))
        frame[5 * p.WIDTH + 5] = 9
        self.assertEqual(stream.send_frame(bytes(frame)), 1)
        self.assertEqual(stream.send_frame(bytes(frame)), 1)  # the other buffer needs it too
        self.assertEqual(stream.send_frame(bytes(frame)), 0)
        self.assertEqual(self.shown(), bytes(frame))

    def test_tile_sizes_that_do_not_divide_evenly(self):
        for size in (1 * 7, 16, 31):
            stream = FrameStreamer(self.gpu, tile_size=size)
            frame = random.Random(size).randbytes(SIZE)
            stream.send_frame(frame)
            self.assertEqual(self.shown(), frame)

    def test_compression_off_still_exact(self):
        stream = FrameStreamer(self.gpu, compress=False)
        frame = bytes(SIZE)
        stream.send_frame(frame)
        self.assertEqual(self.shown(), frame)

    def test_compression_saves_on_flat_pictures(self):
        frame = bytes([3]) * SIZE
        before = self.gpu.stats["bytes"]
        FrameStreamer(self.gpu).send_frame(frame)
        coded = self.gpu.stats["bytes"] - before
        before = self.gpu.stats["bytes"]
        FrameStreamer(self.gpu, compress=False).send_frame(frame)
        self.assertLess(coded * 10, self.gpu.stats["bytes"] - before)

    def test_invalidate_sends_everything_again(self):
        stream = FrameStreamer(self.gpu)
        frame = bytes(SIZE)
        stream.send_frame(frame)
        stream.send_frame(frame)
        stream.invalidate()
        self.assertEqual(stream.send_frame(frame), 289)

    def test_bad_frame_size_refused(self):
        with self.assertRaises(ValueError):
            FrameStreamer(self.gpu).send_frame(bytes(10))


class StreamingOverBadLink(unittest.TestCase):
    def test_exact_with_lost_and_damaged_bytes(self):
        faults = emulator.LinkFaults(drop=0.0002, corrupt=0.0002, seed=7)
        server = emulator.Server(0, faults).start()
        gpu = Dtgc(TcpTransport(port=server.port), retry_seconds=0.05, give_up_seconds=60)  # time, not bytes: a busy PC must not fail it
        try:
            stream = FrameStreamer(gpu)
            for number in range(4):
                frame = random.Random(number).randbytes(SIZE)
                stream.send_frame(frame)
                self.assertEqual(bytes(server.device.buffers[server.device.front]), frame)
            self.assertGreater(gpu.stats["resent_packets"], 0)
        finally:
            gpu.close()
            server.stop()


class Cache(unittest.TestCase):
    def setUp(self):
        self.memory = bytearray(1000)
        self.uploads = []

        def upload(address, data):
            self.uploads.append(len(data))
            self.memory[address:address + len(data)] = data

        self.cache = AssetCache(1000, upload)

    def test_second_use_does_not_upload(self):
        self.cache.begin_frame()
        first = self.cache.use("a", lambda: b"x" * 100)
        second = self.cache.use("a", lambda: self.fail("loaded twice"))
        self.assertEqual(first, second)
        self.assertEqual(self.uploads, [100])

    def test_evicts_longest_unused(self):
        self.cache.begin_frame()
        self.cache.use("old", lambda: b"o" * 400)
        self.cache.use("recent", lambda: b"r" * 400)
        self.cache.begin_frame()
        self.cache.use("old", lambda: b"")  # old is now the more recent one
        self.cache.begin_frame()
        self.cache.use("new", lambda: b"n" * 400)
        self.assertIn("old", self.cache.entries)
        self.assertNotIn("recent", self.cache.entries)

    def test_never_evicts_what_this_frame_uses(self):
        self.cache.begin_frame()
        self.cache.use("a", lambda: b"a" * 600)
        with self.assertRaises(CacheFull):
            self.cache.use("b", lambda: b"b" * 600)
        self.assertIn("a", self.cache.entries)

    def test_too_big_refused(self):
        self.cache.begin_frame()
        with self.assertRaises(CacheFull):
            self.cache.use("huge", lambda: bytes(1001))

    def test_prefetch_counts_as_hit_and_respects_budget(self):
        self.cache.begin_frame()
        load = lambda name: bytes(300)
        self.cache.prefetch(["a", "b", "c"], load, budget_bytes=650)
        self.assertEqual(sorted(self.cache.entries), ["a", "b"])
        self.cache.use("a", lambda: self.fail("should already be there"))
        self.assertEqual(self.cache.stats["hits"], 1)

    def test_prefetch_never_evicts(self):
        self.cache.begin_frame()
        self.cache.use("a", lambda: bytes(900))
        self.cache.begin_frame()
        self.cache.prefetch(["b"], lambda name: bytes(200), budget_bytes=500)
        self.assertEqual(list(self.cache.entries), ["a"])

    def test_random_use_never_overlaps_or_corrupts(self):
        rng = random.Random(3)
        assets = {f"asset{i}": bytes([i]) * rng.randrange(1, 300) for i in range(30)}
        for _ in range(300):
            self.cache.begin_frame()
            for name in rng.sample(sorted(assets), 3):
                try:
                    address = self.cache.use(name, lambda: assets[name])
                except CacheFull:
                    continue
                self.assertEqual(bytes(self.memory[address:address + len(assets[name])]), assets[name])
            spans = sorted((a, a + s) for a, s, _ in self.cache.entries.values())
            spans += sorted((a, a + s) for a, s in self.cache.free)
            spans.sort()
            self.assertEqual(spans[0][0], 0)
            self.assertEqual(spans[-1][1], 1000)
            for (_, end), (start, _) in zip(spans, spans[1:]):
                self.assertEqual(end, start)  # no gaps and no overlaps
        self.assertGreater(self.cache.stats["evictions"], 0)


class FakeTextureGpu:
    """Stores uploads the way the GPU does, so raster.draw can read them back."""
    def __init__(self):
        self.texture = bytearray(2048 * 256)
        self.uploaded = 0

    def texture_rows(self, first_row, width, pixels):
        self.uploaded += len(pixels)
        for i in range(0, len(pixels), width):
            at = (first_row + i // width) * 256
            self.texture[at:at + width] = pixels[i:i + width]


class Textures(unittest.TestCase):
    def setUp(self):
        self.gpu = FakeTextureGpu()
        self.textures = TextureCache(self.gpu)

    def drawn_colors(self, row, size, side):
        corners = [(0, 0, 0, 0), (160, 0, side - 1, 0), (0, 160, 0, side - 1)]
        vertices = [raster.Vertex(x, y, 0, 0, 0, 0, u, v) for x, y, u, v in corners]
        tri = raster.Triangle(raster.MODE_TEXTURE, row, size, *vertices)
        picture = bytearray(340 * 340)
        raster.draw(tri, picture, [0xFFFF] * (340 * 340), self.gpu.texture)
        return picture

    def test_textured_triangle_reads_the_cached_pixels(self):
        self.textures.use("first", lambda: bytes([9]) * 64)
        row, size = self.textures.use("second", lambda: bytes([77]) * 256)
        self.assertEqual((row, size), (8, 4))
        self.assertEqual(self.drawn_colors(row, size, 16)[340 * 2 + 2], 77)

    def test_only_real_pixels_are_sent_and_a_hit_sends_nothing(self):
        self.textures.use("a", lambda: bytes(64))
        self.assertEqual(self.gpu.uploaded, 64)
        self.textures.begin_frame()
        self.textures.use("a", lambda: self.fail("a hit must not load"))
        self.assertEqual(self.gpu.uploaded, 64)

    def test_rows_never_overlap_after_eviction(self):
        rng = random.Random(3)
        contents = {f"t{i}": bytes([i + 1]) * (1 << (2 * rng.randrange(4, 9))) for i in range(40)}
        for _ in range(300):
            self.textures.begin_frame()
            name = rng.choice(sorted(contents))
            row, size = self.textures.use(name, lambda: contents[name])
            side = 1 << size
            for r in range(side):
                self.assertEqual(self.gpu.texture[(row + r) * 256:(row + r) * 256 + side], contents[name][:side])
        self.assertGreater(self.textures.cache.stats["evictions"], 0)

    def test_bad_shapes_are_refused(self):
        for pixels in (bytes(10), bytes(36), bytes(512 * 512), b""):
            with self.assertRaises(ValueError):
                self.textures.use(f"bad{len(pixels)}", lambda: pixels)


if __name__ == "__main__":
    unittest.main()
