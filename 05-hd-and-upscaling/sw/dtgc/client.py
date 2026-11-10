"""Drawing library for DTGC: sends commands, watches the replies, and repeats anything lost.

Usage:
    from sw.dtgc.client import Dtgc, connect_auto
    gpu = connect_auto()
    gpu.clear(0); gpu.rect(10, 10, 50, 50, 0xE0); gpu.swap(); gpu.flush()

Up to WINDOW_BYTES can be on the way at once, which keeps the GPU's 1024-byte receive buffer from
filling. Lost packets are found from a NACK or a timeout, then resent from the first one missing.
"""
import struct
import time
from collections import deque

from . import protocol as p
from . import raster
from .transport import SerialTransport, TcpTransport

WINDOW_BYTES = 1024
WINDOW_PACKETS = 64
RETRY_SECONDS = 0.25
READ_ATTEMPTS = 4
GIVE_UP_SECONDS = 5.0


LIST_CHUNK = (p.MAX_PAYLOAD - 2) // 6  # entries of 6 bytes that fit one packet


class LinkError(Exception):
    """The GPU stopped answering."""


class CommandError(Exception):
    """The GPU refused a command."""


class Dtgc:
    def __init__(self, transport, retry_seconds=RETRY_SECONDS, give_up_seconds=GIVE_UP_SECONDS):
        self.transport = transport
        self.retry_seconds = retry_seconds
        self.give_up_seconds = give_up_seconds
        self.parser = p.Parser()
        self.seq = 0
        self.pending = deque()  # (seq, encoded packet) not yet acknowledged, oldest first
        self.in_flight = 0
        self.errors = []
        self._rows = None  # rows of a READ_RECT on their way in
        self.colors_set = {}  # palette entries sent, since the GPU sends back colour numbers and not colours
        self.last_progress = time.monotonic()
        self.last_send = time.monotonic()
        self.stats = {"packets": 0, "bytes": 0, "resent_packets": 0, "nacks": 0, "timeouts": 0}
        self.hello()

    # Drawing commands ---------------------------------------------------------------------------
    def hello(self):
        self.pending.clear()
        self.in_flight = 0
        self.parser.reset()
        self.seq = 0
        self._send(p.HELLO)
        self.flush()

    def ping(self):
        self._send(p.PING)
        self.flush()

    def clear(self, color):
        self._send(p.CLEAR, p.clear_payload(color))
        self.flush()  # filling a whole frame is slow: wait, rather than fill the receive buffer

    def span(self, x, y, pixels):
        """Writes one row of pixels, split up into as many packets as it needs."""
        chunk = p.MAX_PAYLOAD - 4
        for i in range(0, len(pixels), chunk):
            self._send(p.SPAN, p.span_payload(x + i, y, pixels[i:i + chunk]))

    def rect(self, x, y, w, h, color):
        self._send(p.RECT, p.rect_payload(x, y, w, h, color))

    def image(self, pixels):
        """Writes a whole 340x340 picture from bytes."""
        for y in range(p.HEIGHT):
            self.span(0, y, pixels[y * p.WIDTH:(y + 1) * p.WIDTH])

    def palette(self, first, colors):
        self.colors_set.update(zip(range(first, first + len(colors)), map(tuple, colors)))
        chunk = (p.MAX_PAYLOAD - 1) // 3
        for i in range(0, len(colors), chunk):
            self._send(p.PALETTE, p.palette_payload(first + i, colors[i:i + chunk]))

    def tile(self, x, y, w, h, pixels):
        """Writes a block of raw pixels. Must fit one packet: at most 1016 pixels."""
        self._send(p.TILE, p.tile_payload(x, y, w, h, pixels))

    def rle(self, x, y, w, h, pairs):
        """Writes a block from protocol.rle_pairs() output. Must fit one packet: at most 1016 bytes."""
        self._send(p.RLE, p.rle_payload(x, y, w, h, pairs))

    def triangle(self, triangle):
        """Draws a raster.Triangle."""
        self._send(p.TRIANGLE, raster.payload(triangle))

    def vertices(self, first, points):
        """Stores corners in the GPU's 256 slots, for triangle_list. See protocol.vertices_payload."""
        for i in range(0, len(points), LIST_CHUNK):
            self._send(p.VERTICES, p.vertices_payload(first + i, points[i:i + LIST_CHUNK]))

    def triangle_list(self, mode, records):
        """Draws flat-coloured triangles from stored corners. See protocol.triangle_list_payload."""
        for i in range(0, len(records), LIST_CHUNK):
            self._send(p.TRIANGLE_LIST, p.triangle_list_payload(mode, records[i:i + LIST_CHUNK]))

    def clear_depth(self, value=0xFFFF):
        self._send(p.CLEAR_DEPTH, bytes([value & 0xFF, value >> 8]))

    def depth_rect(self, x, y, w, h, value=0xFFFF):
        self._send(p.DEPTH_RECT, struct.pack("<HHHHH", x, y, w, h, value))
        self.flush()  # as slow as clear

    def texture_rows(self, first_row, width, pixels):
        """Uploads pixels to texture memory, one row per width bytes, at most 256 wide."""
        for i in range(0, len(pixels), width):
            self._send(p.TEX_SPAN, p.tex_span_payload(first_row + i // width, 0, pixels[i:i + width]))

    def swap(self):
        """Shows what has been drawn. The hidden buffer then holds the frame before last."""
        self._send(p.SWAP)

    def read_rect(self, x, y, w, h, hidden=False):
        """Reads pixels back from the GPU, left to right and top to bottom. Parts off the picture are left out."""
        self.flush()
        x_end, y_end = min(x + w, p.WIDTH), min(y + h, p.HEIGHT)
        if x >= x_end or y >= y_end:
            return b""
        wanted = range(y, y_end)
        for _ in range(READ_ATTEMPTS):
            # A row with a damaged checksum is simply absent, so the whole area is asked for again as a new command.
            self._rows = {}
            self._send(p.READ_RECT, p.read_rect_payload(x, y, w, h, hidden))
            self.flush()
            rows, self._rows = self._rows, None
            if all(line in rows and len(rows[line]) == x_end - x for line in wanted):
                return b"".join(rows[line] for line in wanted)
            self.stats["read_retries"] = self.stats.get("read_retries", 0) + 1
        raise LinkError(f"could not read the picture back in {READ_ATTEMPTS} tries")

    def read_frame(self, hidden=False):
        """The whole 340x340 picture as bytes."""
        return self.read_rect(0, 0, p.WIDTH, p.HEIGHT, hidden)

    def flush(self):
        """Waits until the GPU has confirmed everything sent so far."""
        while self.pending:
            self._service()
        self._raise_errors()

    def close(self):
        self.transport.close()

    # Reliability --------------------------------------------------------------------------------
    def _send(self, kind, payload=b""):
        packet = p.encode(kind, self.seq, payload)
        while self.pending and (self.in_flight + len(packet) > WINDOW_BYTES
                                or len(self.pending) >= WINDOW_PACKETS):
            self._service()
        self._raise_errors()
        if not self.pending:
            self.last_progress = time.monotonic()
        self.pending.append((self.seq, packet))
        self.in_flight += len(packet)
        self.seq = (self.seq + 1) & 0xFF
        self.transport.send(packet)
        self.last_send = time.monotonic()
        self.stats["packets"] += 1
        self.stats["bytes"] += len(packet)

    def _service(self):
        """Handles whatever has arrived, and resends if the link has gone quiet."""
        data = self.transport.receive(0.01)
        for byte in data:
            packet = self.parser.feed(byte)
            if not packet or not packet.crc_ok:
                continue
            if packet.kind == p.DATA:
                self._on_row(packet.payload)
            elif len(packet.payload) == 2:
                self._on_reply(packet.kind, packet.payload[0], packet.payload[1])

        now = time.monotonic()
        if self.pending and now - self.last_progress > self.give_up_seconds:
            raise LinkError(f"no progress for {self.give_up_seconds} s")
        if self.pending and now - self.last_send > self.retry_seconds:
            self.stats["timeouts"] += 1
            self._resend_from(self.pending[0][0])

    def _on_row(self, payload):
        if self._rows is not None and len(payload) >= 2:
            self._rows[payload[0] | (payload[1] << 8)] = payload[2:]
        # Rows arriving means the link is alive and busy, so this is no time to send anything again.
        self.last_progress = self.last_send = time.monotonic()

    def _on_reply(self, kind, arg, detail):
        if kind == p.ACK:
            if not any(seq == arg for seq, _ in self.pending):
                return  # an old or repeated reply
            while self.pending:
                seq, packet = self.pending.popleft()
                self.in_flight -= len(packet)
                if seq == arg:
                    break
            self.last_progress = time.monotonic()
            if detail != p.STATUS_OK:
                self.errors.append((arg, detail))
        elif kind == p.NACK:
            self.stats["nacks"] += 1
            if detail == p.NACK_CRC:
                self._resend_from(arg)
            elif self.pending and time.monotonic() - self.last_send > 0.02:
                # Every packet behind a lost one gets a NACK too: one resend answers them all.
                self._resend_from(arg)

    def _resend_from(self, seq):
        start = next((i for i, (s, _) in enumerate(self.pending) if s == seq), 0)
        for _, packet in list(self.pending)[start:]:
            self.transport.send(packet)
            self.stats["resent_packets"] += 1
        self.last_send = time.monotonic()

    def _raise_errors(self):
        if self.errors:
            seq, status = self.errors.pop(0)
            raise CommandError(f"packet {seq} refused with status {status}")


def connect_auto(emulator_port=7654, baud=3000000, serial_port=None):
    """Finds a GPU on a serial port by saying hello, then falls back on a running emulator."""
    ports = [serial_port] if serial_port else _serial_ports()
    for name in ports:
        transport = None
        try:
            transport = SerialTransport(name, baud)
            return Dtgc(transport, give_up_seconds=0.5)
        except Exception:
            if transport:
                transport.close()
    try:
        return Dtgc(TcpTransport(port=emulator_port))
    except OSError as error:
        raise LinkError(
            f"no GPU found on {ports or 'any serial port'} and no emulator on port {emulator_port}. "
            "Start one with: python -m sw.dtgc emulator") from error


def _serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return usb_ports(list_ports.comports())


def usb_ports(ports):
    """Only real USB serial ports. Bluetooth ones have no USB id, and writing to them can block.

    The Tang's own USB id is not known yet (docs/verify.md), so any USB serial device gets a HELLO.
    Name the port with --serial on a PC with other USB serial devices attached.
    """
    return [port.device for port in ports if port.vid is not None]
