"""Emulator of the DTGC hardware, speaking the real protocol over TCP.

Usage: python -m sw.dtgc emulator [--port 7654] [--window] [--png-dir DIR] [--rate BYTES_PER_S]
       [--drop P] [--corrupt P] [--disconnect-after BYTES] [--seed N]

Device is the model itself. Its results must match rtl/gpu_core.v bit for bit, which
sw/tests/test_rtl_match.py checks. The emulator is not a speed benchmark of the hardware, except
through the --rate limit you give it.
"""
import random
import socket
import struct
import threading
import time
import zlib
from pathlib import Path

from . import protocol as p
from . import raster


def default_palette():
    """Same RRRGGGBB mapping that rtl/fb_scanout.v loads after reset."""
    colors = []
    for i in range(256):
        r, g, b = i >> 5, (i >> 2) & 7, i & 3
        colors.append(((r << 5) | (r << 2) | (r >> 1),
                       (g << 5) | (g << 2) | (g >> 1),
                       (b << 6) | (b << 4) | (b << 2) | b))
    return colors


def _rle_pixels(pairs):
    for i in range(0, len(pairs), 2):
        for _ in range(pairs[i] + 1):
            yield pairs[i + 1]


class Device:
    """Framebuffers, palette and command handling. Takes bytes, returns reply bytes."""

    def __init__(self, on_swap=None):
        self.buffers = [bytearray(p.WIDTH * p.HEIGHT), bytearray(p.WIDTH * p.HEIGHT)]
        self.palette = default_palette()
        self.depth = [0] * (p.WIDTH * p.HEIGHT)
        self.texture = bytearray(2048 * 256)
        self.vertices = [(0, 0, 0)] * 256  # the GPU leaves slots unknown until written
        self.front = 0
        self.expected = 0
        self.parser = p.Parser()
        self.on_swap = on_swap

    @property
    def back(self):
        return self.buffers[1 - self.front]

    def idle(self):
        self.parser.idle()

    def feed(self, data):
        replies = bytearray()
        for byte in data:
            packet = self.parser.feed(byte)
            if packet:
                replies += self.handle(packet)
        return bytes(replies)

    def handle(self, packet):
        if not packet.crc_ok:
            return p.encode(p.NACK, 0, bytes([self.expected, p.NACK_CRC]))
        if packet.kind == p.HELLO:
            self.expected = (packet.seq + 1) & 0xFF
            return p.encode(p.ACK, 0, bytes([packet.seq, p.STATUS_OK]))
        if packet.seq == (self.expected - 1) & 0xFF:
            return p.encode(p.ACK, 0, bytes([packet.seq, p.STATUS_OK]))  # already done: do not redo
        if packet.seq != self.expected:
            return p.encode(p.NACK, 0, bytes([self.expected, p.NACK_SEQ]))
        self.expected = (self.expected + 1) & 0xFF
        if packet.kind == p.READ_RECT:
            rows, status = self.read_rect(packet.seq, packet.payload)
            return rows + p.encode(p.ACK, 0, bytes([packet.seq, status]))
        return p.encode(p.ACK, 0, bytes([packet.seq, self.execute(packet.kind, packet.payload)]))

    def read_rect(self, seq, data):
        """The DATA packets for a READ_RECT, one for each row, and the status for the ACK that follows them."""
        if len(data) != 9:
            return b"", p.STATUS_BAD_LENGTH
        x, y, w, h, hidden = struct.unpack("<HHHHB", data)
        if hidden > 1:
            return b"", p.STATUS_BAD_VALUE
        if x >= p.WIDTH or y >= p.HEIGHT or not w or not h:
            return b"", p.STATUS_OK
        buffer = self.back if hidden else self.buffers[self.front]
        x_end, y_end = min(x + w, p.WIDTH), min(y + h, p.HEIGHT)
        rows = bytearray()
        for line in range(y, y_end):
            rows += p.encode(p.DATA, seq, struct.pack("<H", line) + bytes(buffer[line * p.WIDTH + x:line * p.WIDTH + x_end]))
        return bytes(rows), p.STATUS_OK

    def execute(self, kind, data):
        if kind == p.PING:
            return p.STATUS_OK
        if kind == p.CLEAR:
            if len(data) != 1:
                return p.STATUS_BAD_LENGTH
            self.back[:] = bytes([data[0]]) * len(self.back)
        elif kind == p.SPAN:
            if len(data) < 4:
                return p.STATUS_BAD_LENGTH
            x, y = struct.unpack_from("<HH", data)
            if y < p.HEIGHT and x < p.WIDTH:
                pixels = data[4:4 + p.WIDTH - x]  # off-picture pixels are skipped, never wrapped
                start = y * p.WIDTH + x
                self.back[start:start + len(pixels)] = pixels
        elif kind == p.RECT:
            if len(data) != 9:
                return p.STATUS_BAD_LENGTH
            x, y, w, h, color = struct.unpack("<HHHHB", data)
            if x < p.WIDTH and y < p.HEIGHT and w and h:
                x_end, y_end = min(x + w, p.WIDTH), min(y + h, p.HEIGHT)
                row = bytes([color]) * (x_end - x)
                for line in range(y, y_end):
                    self.back[line * p.WIDTH + x:line * p.WIDTH + x_end] = row
        elif kind == p.PALETTE:
            if len(data) < 1 or (len(data) - 1) % 3:
                return p.STATUS_BAD_LENGTH
            for i in range((len(data) - 1) // 3):
                if data[0] + i < 256:
                    self.palette[data[0] + i] = tuple(data[1 + i * 3:4 + i * 3])
        elif kind == p.SWAP:
            if data:
                return p.STATUS_BAD_LENGTH
            self.front = 1 - self.front
            if self.on_swap:
                self.on_swap(self)
        elif kind in (p.TILE, p.RLE):
            if len(data) < 8 or (kind == p.RLE and len(data) % 2):
                return p.STATUS_BAD_LENGTH
            x, y, w, h = struct.unpack_from("<HHHH", data)
            if w and h:
                self._fill_area(x, y, w, h, data[8:] if kind == p.TILE else _rle_pixels(data[8:]))
        elif kind == p.TRIANGLE:
            if len(data) != raster.PAYLOAD_SIZE:
                return p.STATUS_BAD_LENGTH
            triangle = raster.parse(data)
            if not raster.valid(triangle):
                return p.STATUS_BAD_VALUE
            raster.draw(triangle, self.back, self.depth, self.texture)
        elif kind == p.VERTICES:
            if len(data) < 2 or len(data) != 2 + 6 * data[1]:
                return p.STATUS_BAD_LENGTH
            if data[0] + data[1] > 256:
                return p.STATUS_BAD_VALUE
            for i in range(data[1]):
                self.vertices[data[0] + i] = struct.unpack_from("<hhH", data, 2 + 6 * i)
        elif kind == p.TRIANGLE_LIST:
            if len(data) < 2 or len(data) != 2 + 6 * data[1]:
                return p.STATUS_BAD_LENGTH
            status = p.STATUS_OK
            for i in range(data[1]):
                a, b, c, red, green, blue = data[2 + 6 * i:8 + 6 * i]
                corners = [raster.Vertex(*self.vertices[slot], red, green, blue, 0, 0) for slot in (a, b, c)]
                triangle = raster.Triangle(data[0], 0, 0, *corners)
                if raster.valid(triangle):
                    self.draw_triangle(triangle)
                else:
                    status = p.STATUS_BAD_VALUE
            return status
        elif kind == p.TEX_SPAN:
            if len(data) < 3:
                return p.STATUS_BAD_LENGTH
            row, u = struct.unpack_from("<HB", data)
            if row < 2048:
                pixels = data[3:3 + 256 - u]  # past the end of the row is skipped
                self.texture[row * 256 + u:row * 256 + u + len(pixels)] = pixels
        elif kind == p.CLEAR_DEPTH:
            if len(data) != 2:
                return p.STATUS_BAD_LENGTH
            self.depth = [data[0] | (data[1] << 8)] * (p.WIDTH * p.HEIGHT)
        elif kind == p.DEPTH_RECT:
            if len(data) != 10:
                return p.STATUS_BAD_LENGTH
            x, y, w, h, value = struct.unpack("<HHHHH", data)
            if x < p.WIDTH and y < p.HEIGHT and w and h:
                x_end, y_end = min(x + w, p.WIDTH), min(y + h, p.HEIGHT)
                for line in range(y, y_end):
                    self.depth[line * p.WIDTH + x:line * p.WIDTH + x_end] = [value] * (x_end - x)
        else:
            return p.STATUS_UNKNOWN
        return p.STATUS_OK

    def draw_triangle(self, triangle):
        raster.draw(triangle, self.back, self.depth, self.texture)

    def _fill_area(self, x, y, w, h, pixels):
        """Pixels run left to right, row by row. They stop when the area is full or they run out.

        Pixels off the picture are skipped, and still use up their place in the area.
        """
        back = self.back
        cur_x, cur_y = x, y
        for value in pixels:
            if cur_x < p.WIDTH and cur_y < p.HEIGHT:
                back[cur_y * p.WIDTH + cur_x] = value
            cur_x += 1
            if cur_x == x + w:
                cur_x = x
                cur_y += 1
                if cur_y == y + h:
                    return

    def window_rgb(self):
        """The picture on screen as RGB bytes."""
        lookup = [bytes(c) for c in self.palette]
        return b"".join(lookup[v] for v in self.buffers[self.front])

    def screen_rgb(self):
        """The full 640x480 video frame, picture centred on black, as the hardware outputs it."""
        window = self.window_rgb()
        rows = bytearray(640 * 480 * 3)
        for y in range(p.HEIGHT):
            start = (y + 70) * 640 * 3 + 150 * 3
            rows[start:start + p.WIDTH * 3] = window[y * p.WIDTH * 3:(y + 1) * p.WIDTH * 3]
        return bytes(rows)


class LocalTransport:
    """Connects a client straight to a Device in the same program, with no sockets and no delay."""

    def __init__(self, device):
        self.device = device
        self.replies = bytearray()

    def send(self, data):
        self.replies += self.device.feed(data)

    def receive(self, _timeout):
        data = bytes(self.replies)
        self.replies.clear()
        return data

    def close(self):
        pass


def write_png(path, width, height, rgb):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\0" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows, 6))
                + chunk(b"IEND", b""))


class LinkFaults:
    """A bad cable, on demand: slow link, lost bytes, damaged bytes, and pulled plugs."""

    def __init__(self, rate=None, drop=0.0, corrupt=0.0, disconnect_after=None, seed=1):
        self.rate = rate
        self.drop = drop
        self.corrupt = corrupt
        self.disconnect_after = disconnect_after
        self.random = random.Random(seed)
        self.total = 0

    def apply(self, data):
        """Returns the bytes that survive. Raises ConnectionError when the plug gets pulled."""
        if self.rate:
            time.sleep(len(data) / self.rate)
        out = bytearray()
        for byte in data:
            self.total += 1
            if self.disconnect_after and self.total >= self.disconnect_after:
                self.total = 0
                raise ConnectionError("simulated disconnect")
            if self.random.random() < self.drop:
                continue
            if self.random.random() < self.corrupt:
                byte ^= 1 << self.random.randrange(8)
            out.append(byte)
        return bytes(out)


class Server:
    """Serves one Device over TCP. The Device keeps its state across reconnects, as hardware does."""

    def __init__(self, port=7654, faults=None, png_dir=None, on_swap=None):
        self.png_dir = Path(png_dir) if png_dir else None
        self.frames = 0
        self.external_swap = on_swap
        self.device = Device(on_swap=self._swapped)
        self.faults = faults or LinkFaults()
        self.lock = threading.Lock()
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.running = True

    def _swapped(self, device):
        self.frames += 1
        if self.png_dir:
            self.png_dir.mkdir(parents=True, exist_ok=True)
            write_png(self.png_dir / f"frame_{self.frames:05d}.png", 640, 480, device.screen_rgb())
        if self.external_swap:
            self.external_swap(device)

    def serve_forever(self):
        while self.running:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve_one, args=(connection,), daemon=True).start()

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.running = False
        self.listener.close()

    def _serve_one(self, connection):
        with connection:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                while True:
                    data = connection.recv(4096)
                    if not data:
                        break
                    surviving = self.faults.apply(data)
                    with self.lock:
                        replies = self.device.feed(surviving)
                    if replies:
                        connection.sendall(replies)
            except OSError:
                pass  # ConnectionError is an OSError: a pulled plug just ends this connection
            with self.lock:
                self.device.idle()


def show_window(server, on_drawn=None):
    """Shows the picture live in a window. Uses tkinter from the Python standard library.

    on_drawn(root, image), if given, is called after each new picture. The tests use it.
    """
    import tkinter

    root = tkinter.Tk()
    root.title("DTGC emulator")
    image = tkinter.PhotoImage(width=p.WIDTH, height=p.HEIGHT)
    tkinter.Label(root, image=image).pack()
    shown = [-1]

    def refresh():
        if server.frames != shown[0]:
            shown[0] = server.frames
            with server.lock:
                rgb = server.device.window_rgb()
            header = f"P6 {p.WIDTH} {p.HEIGHT} 255 ".encode()
            image.configure(data=header + rgb, format="PPM")
            if on_drawn:
                on_drawn(root, image)
        root.after(16, refresh)

    refresh()
    root.mainloop()
