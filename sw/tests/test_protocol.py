"""Tests of the protocol, the emulator and the client's recovery from a bad link.

Usage: python -m unittest sw.tests.test_protocol
"""
import random
import unittest
from collections import namedtuple

from sw.dtgc import emulator, protocol as p
from sw.dtgc.client import CommandError, Dtgc, LinkError, usb_ports
from sw.dtgc.transport import TcpTransport


class Checksums(unittest.TestCase):
    def test_known_values(self):
        # Published check values for these two CRC settings, on the ASCII digits 1 to 9.
        self.assertEqual(p.crc8(b"123456789"), 0xF4)
        self.assertEqual(p.crc16(b"123456789"), 0x29B1)


class ParserFuzz(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(1)
        parser = p.Parser()
        for _ in range(2000):
            payload = rng.randbytes(rng.choice([0, 1, 2, 50, 1024]))
            kind, seq = rng.randrange(256), rng.randrange(256)
            found = [r for r in (parser.feed(b) for b in p.encode(kind, seq, payload)) if r]
            self.assertEqual(found, [p.Packet(kind, seq, payload, True)])

    def test_random_bytes_never_crash(self):
        rng = random.Random(2)
        device = emulator.Device()
        for _ in range(200):
            device.feed(rng.randbytes(rng.randrange(5000)))
            if rng.random() < 0.2:
                device.idle()

    def test_any_one_bit_flip_is_caught(self):
        original = p.encode(p.SPAN, 3, p.span_payload(1, 2, bytes(range(40))))
        for bit in range(len(original) * 8):
            damaged = bytearray(original)
            damaged[bit // 8] ^= 1 << (bit % 8)
            parser = p.Parser()
            found = [r for r in (parser.feed(b) for b in damaged) if r]
            self.assertFalse([r for r in found if r.crc_ok], f"bit {bit} was not caught")

    def test_over_long_length_rejected(self):
        parser = p.Parser()
        header = bytes([p.VERSION, p.SPAN, 0, 0x01, 0x04])  # 1025 bytes
        for byte in bytes([p.SYNC]) + header + bytes([p.crc8(header)]):
            parser.feed(byte)
        self.assertEqual(parser.state, "sync")

    def test_encode_refuses_too_long(self):
        with self.assertRaises(ValueError):
            p.encode(p.SPAN, 0, bytes(1025))


class Commands(unittest.TestCase):
    def setUp(self):
        self.device = emulator.Device()
        self.seq = 0
        self.device.feed(p.encode(p.HELLO, 0))

    def send(self, kind, payload=b""):
        self.seq += 1
        reply = p.Parser()
        return [r for r in (reply.feed(b) for b in self.device.feed(p.encode(kind, self.seq, payload))) if r]

    def test_span_clips_and_does_not_wrap(self):
        self.send(p.SPAN, p.span_payload(338, 0, b"\x01\x02\x03\x04"))
        back = self.device.back
        self.assertEqual(bytes(back[338:342]), b"\x01\x02\x00\x00")

    def test_rect_clips(self):
        self.send(p.RECT, p.rect_payload(339, 339, 100, 100, 9))
        self.assertEqual(self.device.back[-1], 9)
        self.assertEqual(self.device.back[-2], 0)

    def test_swap_flips_buffers(self):
        self.send(p.CLEAR, b"\x05")
        self.assertEqual(self.device.buffers[self.device.front][0], 0)
        self.send(p.SWAP)
        self.assertEqual(self.device.buffers[self.device.front][0], 5)

    def test_repeat_is_acknowledged_but_not_redone(self):
        self.send(p.SPAN, p.span_payload(0, 0, b"\x07"))
        self.device.back[0] = 0
        replies = p.Parser()
        again = p.encode(p.SPAN, self.seq, p.span_payload(0, 0, b"\x07"))
        found = [r for r in (replies.feed(b) for b in self.device.feed(again)) if r]
        self.assertEqual(found[0].kind, p.ACK)
        self.assertEqual(self.device.back[0], 0)

    def test_gap_is_nacked(self):
        replies = p.Parser()
        found = [r for r in (replies.feed(b) for b in self.device.feed(p.encode(p.PING, 50))) if r]
        self.assertEqual(found[0].kind, p.NACK)
        self.assertEqual(found[0].payload, bytes([1, p.NACK_SEQ]))


def picture(seed=9):
    return random.Random(seed).randbytes(p.WIDTH * p.HEIGHT)


class BadLink(unittest.TestCase):
    """The whole path: client, TCP, faults, emulator. The final picture must always be exact."""

    def run_link(self, frames=1, **faults):
        """Draws frames in order, reconnecting and redrawing the current one after a failure."""
        server = emulator.Server(0, emulator.LinkFaults(**faults)).start()
        try:
            done = 0
            stats = {"reconnects": -1, "resent_packets": 0}
            while done < frames:
                stats["reconnects"] += 1
                self.assertLess(stats["reconnects"], 40, "gave up reconnecting")
                transport = None
                try:
                    transport = TcpTransport(port=server.port)
                    gpu = Dtgc(transport, retry_seconds=0.05, give_up_seconds=3.0)
                    while done < frames:
                        pixels = picture(done)
                        gpu.clear(0)
                        gpu.image(pixels)
                        gpu.swap()
                        gpu.flush()
                        done += 1
                        shown = bytes(server.device.buffers[server.device.front])
                        self.assertEqual(shown, pixels, f"frame {done} is wrong")
                    stats["resent_packets"] += gpu.stats["resent_packets"]
                except (OSError, LinkError):
                    pass
                finally:
                    if transport:
                        transport.close()
            return stats
        finally:
            server.stop()

    def test_clean(self):
        stats = self.run_link()
        self.assertEqual(stats["resent_packets"], 0)

    def test_lost_bytes(self):
        stats = self.run_link(drop=0.0002, seed=3)
        self.assertGreater(stats["resent_packets"], 0)

    def test_damaged_bytes(self):
        stats = self.run_link(corrupt=0.0002, seed=4)
        self.assertGreater(stats["resent_packets"], 0)

    def test_disconnects(self):
        stats = self.run_link(frames=4, disconnect_after=200000, seed=5)
        self.assertGreater(stats["reconnects"], 0)


class PortSearch(unittest.TestCase):
    def test_bluetooth_ports_are_left_alone(self):
        Port = namedtuple("Port", "device vid")
        found = usb_ports([Port("COM3", None), Port("COM4", None), Port("COM7", 0x1234)])
        self.assertEqual(found, ["COM7"])


class Refusal(unittest.TestCase):
    def test_refused_command_raises(self):
        server = emulator.Server(0).start()
        try:
            gpu = Dtgc(TcpTransport(port=server.port))
            gpu._send(0x7F)
            with self.assertRaises(CommandError):
                gpu.flush()
            gpu.close()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
