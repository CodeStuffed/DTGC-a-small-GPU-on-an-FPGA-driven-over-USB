"""Tests of record, replay and the emulator's live window.

Usage: python -m unittest sw.tests.test_cli

The window test opens a real window for a moment, and skips if this PC cannot.
"""
import tempfile
import unittest
from pathlib import Path

from sw.dtgc import emulator
from sw.dtgc import protocol as p
from sw.dtgc.__main__ import draw_bars, replay, selftest
from sw.dtgc.client import Dtgc
from sw.dtgc.transport import RecordingTransport, TcpTransport


class RecordReplay(unittest.TestCase):
    def test_replay_gives_the_same_picture(self):
        first = emulator.Server(0).start()
        second = emulator.Server(0).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "bars.dtgc"
                gpu = Dtgc(TcpTransport(port=first.port))
                gpu.transport = RecordingTransport(gpu.transport, path)
                gpu.hello()
                draw_bars(gpu)
                gpu.close()

                transport = TcpTransport(port=second.port)
                answered = replay(transport, path.read_bytes())
                transport.close()
            self.assertEqual(answered, 1 + 8 + 1)  # hello, eight bars, swap
            shown = second.device.buffers[second.device.front]
            self.assertEqual(shown, first.device.buffers[first.device.front])
            self.assertEqual(shown[0], 0xFF)
        finally:
            first.stop()
            second.stop()


class Window(unittest.TestCase):
    def test_window_shows_the_picture(self):
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception as error:
            self.skipTest(f"no window available: {error}")
        server = emulator.Server(0).start()
        try:
            gpu = Dtgc(TcpTransport(port=server.port))
            gpu.rect(0, 0, p.WIDTH, p.HEIGHT, 0x03)      # blue with the default palette
            gpu.rect(10, 20, 1, 1, 0xE0)                 # one red pixel
            gpu.swap()
            gpu.flush()
            gpu.close()
            seen = {}

            def look(root, image):
                seen["background"] = image.get(0, 0)
                seen["dot"] = image.get(10, 20)
                root.destroy()

            emulator.show_window(server, look)
            self.assertEqual(tuple(seen["background"]), (0, 0, 255))
            self.assertEqual(tuple(seen["dot"]), (255, 0, 0))
        finally:
            server.stop()


class ReadBack(unittest.TestCase):
    def setUp(self):
        self.device = emulator.Device()
        self.gpu = Dtgc(emulator.LocalTransport(self.device))

    def test_reads_what_was_drawn(self):
        self.gpu.rect(10, 20, 3, 2, 0x55)
        self.gpu.swap()
        self.assertEqual(self.gpu.read_rect(9, 20, 5, 1), bytes([0, 0x55, 0x55, 0x55, 0]))
        self.assertEqual(self.gpu.read_rect(10, 21, 3, 2), bytes([0x55] * 3 + [0] * 3))

    def test_hidden_buffer(self):
        self.gpu.rect(0, 0, 1, 1, 9)
        self.gpu.flush()
        self.assertEqual(self.gpu.read_rect(0, 0, 1, 1, hidden=True), b"\x09")
        self.assertEqual(self.gpu.read_rect(0, 0, 1, 1), b"\x00")

    def test_clipped_and_empty(self):
        self.assertEqual(len(self.gpu.read_rect(338, 338, 100, 100)), 4)
        self.assertEqual(self.gpu.read_rect(340, 0, 4, 4), b"")
        self.assertEqual(self.gpu.read_rect(0, 0, 0, 4), b"")
        self.assertEqual(len(self.gpu.read_frame()), p.WIDTH * p.HEIGHT)

    def test_bad_buffer_number_refused_with_no_rows(self):
        replies = self.device.feed(p.encode(p.READ_RECT, 1, p.read_rect_payload(0, 0, 4, 4)[:-1] + b"\x02"))
        parser = p.Parser()
        found = [r for r in (parser.feed(b) for b in replies) if r]
        self.assertEqual([r.kind for r in found], [p.ACK])
        self.assertEqual(found[0].payload[1], p.STATUS_BAD_VALUE)

    def test_survives_a_bad_link(self):
        faults = emulator.LinkFaults(None, 0.0, 0.00005, None, 1)
        server = emulator.Server(0, faults).start()
        try:
            gpu = Dtgc(TcpTransport(port=server.port), retry_seconds=0.05)
            gpu.rect(0, 0, p.WIDTH, p.HEIGHT, 0x2A)
            gpu.swap()
            self.assertEqual(gpu.read_frame(), bytes([0x2A]) * (p.WIDTH * p.HEIGHT))
            gpu.close()
        finally:
            server.stop()

    def test_selftest_checks_the_memory(self):
        self.assertTrue(selftest(self.gpu))


class NewCommands(unittest.TestCase):
    def setUp(self):
        self.device = emulator.Device()
        self.seq = 0
        self.device.feed(p.encode(p.HELLO, 0))

    def send(self, kind, payload):
        self.seq += 1
        return self.device.feed(p.encode(kind, self.seq, payload))

    def test_tile_wraps_inside_its_area(self):
        self.send(p.TILE, p.tile_payload(2, 3, 2, 2, b"\x01\x02\x03\x04\x05"))
        back = self.device.back
        self.assertEqual(bytes(back[3 * 340 + 2:3 * 340 + 4]), b"\x01\x02")
        self.assertEqual(bytes(back[4 * 340 + 2:4 * 340 + 4]), b"\x03\x04")
        self.assertEqual(back[5 * 340 + 2], 0)  # the fifth pixel is past the area

    def test_tile_off_the_edge_does_not_shift_later_rows(self):
        self.send(p.TILE, p.tile_payload(339, 0, 2, 2, b"\x01\x02\x03\x04"))
        back = self.device.back
        self.assertEqual(back[339], 1)
        self.assertEqual(back[340 + 339], 3)
        self.assertEqual(back[340], 0)  # never wraps to the left edge

    def test_rle_round_trip(self):
        pixels = bytes([7] * 300 + [8, 9] + [7] * 98)
        self.send(p.RLE, p.rle_payload(20, 20, 20, 20, p.rle_pairs(pixels)))
        back = self.device.back
        got = b"".join(bytes(back[(20 + y) * 340 + 20:(20 + y) * 340 + 40]) for y in range(20))
        self.assertEqual(got, pixels)

    def test_rle_longest_run_stops_at_the_area(self):
        self.send(p.RLE, p.rle_payload(0, 0, 3, 1, bytes([255, 6])))
        back = self.device.back
        self.assertEqual(bytes(back[:4]), b"\x06\x06\x06\x00")

    def test_rle_odd_length_refused(self):
        reply = p.Parser()
        found = [r for r in (reply.feed(b) for b in self.send(p.RLE, bytes(9))) if r]
        self.assertEqual(found[0].payload[1], p.STATUS_BAD_LENGTH)


if __name__ == "__main__":
    unittest.main()
