"""The laptop version of DTGC: no extra hardware. The PC's own graphics card draws, and the picture fits any screen.

Usage: python -m sw.dtgc laptop [--demo cube|field|bars|kart|pong|maze|dodge] [--exact] [--fullscreen] [--frames N] [--no-vsync]
       With no --demo it serves the emulator's TCP port, so any other command can draw into its window.
       python -m sw.dtgc view [--demo cube|field|bars|kart|pong|maze|dodge] [--fullscreen] [--frames N]
       The USB-output version: the board draws, sends every finished picture back, and this window shows it.

Two ways to draw:
  sharp (default)  Triangles go straight to the graphics card at the window's full resolution, with 24-bit colour and
                   smoothed edges. It looks better than the real DTGC and is NOT bit-exact with it.
  --exact          Every pixel comes from the emulator, which matches the Verilog bit for bit, so this is what the real
                   hardware would draw. The graphics card only scales the finished picture to fit.
Either way, the picture keeps its shape and is as large as the window allows. F11 switches full screen.
"""
import colorsys
import math
import time

import numpy as np

from . import emulator
from . import protocol as p
from . import raster
from .api import Canvas, Mesh
from .client import Dtgc

try:
    from . import glwindow
    from .glwindow import gl
except ImportError:  # not Windows: the demos and scenes still work, and tkwindow.py shows them
    glwindow = gl = None

GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT = 0x4000, 0x0100
GL_TEXTURE_2D, GL_DEPTH_TEST, GL_SCISSOR_TEST = 0x0DE1, 0x0B71, 0x0C11
GL_TRIANGLES, GL_QUADS, GL_FLOAT, GL_UNSIGNED_BYTE = 0x0004, 0x0007, 0x1406, 0x1401
GL_RGB, GL_RGB8, GL_RGBA, GL_RGBA8 = 0x1907, 0x8051, 0x1908, 0x8058
GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_NEAREST, GL_LINEAR = 0x2801, 0x2800, 0x2600, 0x2601
GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_REPEAT, GL_CLAMP_TO_EDGE = 0x2802, 0x2803, 0x2901, 0x812F
GL_MODELVIEW, GL_PROJECTION, GL_LESS, GL_UNPACK_ALIGNMENT = 0x1700, 0x1701, 0x0201, 0x0CF5
GL_VERTEX_ARRAY, GL_COLOR_ARRAY, GL_TEXTURE_COORD_ARRAY = 0x8074, 0x8076, 0x8078
GL_BACK, GL_SMOOTH, GL_FLAT = 0x0405, 0x1D01, 0x1D00

gl.glOrtho.argtypes = [glwindow.ctypes.c_double] * 6
gl.glClearColor.argtypes = [glwindow.ctypes.c_float] * 4
gl.glClearDepth.argtypes = [glwindow.ctypes.c_double]
gl.glColor3f.argtypes = [glwindow.ctypes.c_float] * 3
gl.glTexCoord2f.argtypes = [glwindow.ctypes.c_float] * 2
gl.glVertex2f.argtypes = [glwindow.ctypes.c_float] * 2
gl.glVertexPointer.argtypes = [glwindow.ctypes.c_int, glwindow.ctypes.c_uint, glwindow.ctypes.c_int, glwindow.ctypes.c_void_p]
gl.glColorPointer.argtypes = gl.glVertexPointer.argtypes
gl.glTexCoordPointer.argtypes = gl.glVertexPointer.argtypes
gl.glTexImage2D.argtypes = [glwindow.ctypes.c_uint, glwindow.ctypes.c_int, glwindow.ctypes.c_int, glwindow.ctypes.c_int,
                            glwindow.ctypes.c_int, glwindow.ctypes.c_int, glwindow.ctypes.c_uint, glwindow.ctypes.c_uint,
                            glwindow.ctypes.c_void_p]
gl.glTexSubImage2D.argtypes = [glwindow.ctypes.c_uint, glwindow.ctypes.c_int, glwindow.ctypes.c_int, glwindow.ctypes.c_int,
                               glwindow.ctypes.c_int, glwindow.ctypes.c_int, glwindow.ctypes.c_uint, glwindow.ctypes.c_uint,
                               glwindow.ctypes.c_void_p]
gl.glReadPixels.argtypes = [glwindow.ctypes.c_int, glwindow.ctypes.c_int, glwindow.ctypes.c_int, glwindow.ctypes.c_int,
                            glwindow.ctypes.c_uint, glwindow.ctypes.c_uint, glwindow.ctypes.c_void_p]


def fit_picture(width, height):
    """Where the picture goes in a window: as large as fits, centred, in its own shape. Returns (x, y, width, height)."""
    if width * p.HEIGHT <= height * p.WIDTH:
        shown_width, shown_height = max(1, width), max(1, width * p.HEIGHT // p.WIDTH)
    else:
        shown_width, shown_height = max(1, height * p.WIDTH // p.HEIGHT), max(1, height)
    return (width - shown_width) // 2, (height - shown_height) // 2, shown_width, shown_height


class SharpDevice(emulator.Device):
    """The emulator's Device, except that triangles are kept for the graphics card rather than filled on the CPU.

    Everything drawn before the first triangle of a frame lands in the normal picture buffer and becomes the background.
    Rectangles after it (such as text over a 3D scene) join the triangles, to stay in drawing order.
    """

    def __init__(self, on_swap=None):
        super().__init__(on_swap=on_swap)
        self.batches = []       # the frame being drawn: each is [mode, tex_row, tex_size, vertex list]
        self.shown_batches = []
        self.layer_version = 0
        self.texture_version = 0
        self.palette_version = 0

    def draw_triangle(self, tri):
        self.add_triangle(tri)

    def add_triangle(self, tri):
        mode = tri.mode & (raster.MODE_DEPTH | raster.MODE_TEXTURE)
        tex_row, tex_size = (tri.tex_row, tri.tex_size) if mode & raster.MODE_TEXTURE else (0, 0)
        last = self.batches[-1] if self.batches else None
        if last is None or last[0] != mode or last[1] != tex_row or last[2] != tex_size:
            last = [mode, tex_row, tex_size, []]
            self.batches.append(last)
        for v in (tri.v0, tri.v1, tri.v2):
            last[3].append((v.x, v.y, v.z, v.r, v.g, v.b, v.u, v.v))

    def _add_rect(self, x, y, w, h, color):
        x_end, y_end = min(x + w, p.WIDTH) * 16, min(y + h, p.HEIGHT) * 16
        x, y = x * 16, y * 16
        r, g, b = self.palette[color]
        corners = [(x, y), (x_end, y), (x_end, y_end), (x, y), (x_end, y_end), (x, y_end)]
        if not self.batches or self.batches[-1][0] != -1:
            self.batches.append([-1, 0, 0, []])
        self.batches[-1][3].extend((cx, cy, 0, r, g, b, 0, 0) for cx, cy in corners)

    def execute(self, kind, data):
        if kind == p.TRIANGLE:
            if len(data) != raster.PAYLOAD_SIZE:
                return p.STATUS_BAD_LENGTH
            tri = raster.parse(data)
            if not raster.valid(tri):
                return p.STATUS_BAD_VALUE
            self.add_triangle(tri)
            return p.STATUS_OK
        if kind == p.RECT and self.batches and len(data) == 9:
            x, y, w, h, color = p.struct.unpack("<HHHHB", data)
            if x < p.WIDTH and y < p.HEIGHT and w and h:
                self._add_rect(x, y, w, h, color)
            return p.STATUS_OK
        if kind == p.SWAP and not data:
            self.shown_batches, self.batches = self.batches, []
        status = super().execute(kind, data)
        if kind == p.PALETTE:
            self.palette_version += 1
            self.layer_version += 1
        elif kind == p.TEX_SPAN:
            self.texture_version += 1
        elif kind in (p.CLEAR, p.SPAN, p.RECT, p.TILE, p.RLE, p.SWAP):
            self.layer_version += 1
        return status


class LocalGpu(Dtgc):
    """The same drawing library as the real link, wired straight to a Device, with no packets or checksums to slow it down."""

    def __init__(self, device):
        self.device = device
        self.errors = []
        self.stats = {"packets": 0, "bytes": 0, "resent_packets": 0, "nacks": 0, "timeouts": 0}
        self.colors_set = {}

    def read_rect(self, x, y, w, h, hidden=False):
        """The picture buffer, straight from memory. Sharp triangles are not in it, as the graphics card keeps those."""
        buffer = self.device.back if hidden else self.device.buffers[self.device.front]
        return b"".join(bytes(buffer[line * p.WIDTH + x:line * p.WIDTH + min(x + w, p.WIDTH)])
                        for line in range(y, min(y + h, p.HEIGHT)) if x < p.WIDTH)

    def hello(self):
        pass

    def _send(self, kind, payload=b""):
        status = self.device.execute(kind, payload)
        self.stats["packets"] += 1
        if status != p.STATUS_OK:
            self.errors.append((0, status))

    def triangle(self, triangle):
        if isinstance(self.device, SharpDevice) and raster.valid(triangle):
            self.device.add_triangle(triangle)
        else:
            self._send(p.TRIANGLE, raster.payload(triangle))

    def flush(self):
        self._raise_errors()

    def close(self):
        pass


class Renderer:
    """Draws a Device's current picture into the window, fitted to whatever size the window is."""

    def __init__(self, device, smooth_scaling=False):
        self.device = device
        self.smooth_scaling = smooth_scaling
        self.layer = self._new_texture(GL_RGB8, p.WIDTH, p.HEIGHT, GL_RGB, GL_LINEAR if smooth_scaling else GL_NEAREST, GL_CLAMP_TO_EDGE)
        self.layer_seen = -1
        self.textures = {}
        self.textures_seen = -1
        self.palette_lookup = None
        self.palette_seen = -1
        self.frame_arrays = []
        self.frame_source = None
        gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        gl.glDepthFunc(GL_LESS)
        gl.glShadeModel(GL_SMOOTH)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)

    @staticmethod
    def _new_texture(internal, width, height, data_format, scaling, wrap, pixels=None):
        name = glwindow.ctypes.c_uint(0)
        gl.glGenTextures(1, glwindow.ctypes.byref(name))
        gl.glBindTexture(GL_TEXTURE_2D, name.value)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, scaling)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, scaling)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, internal, width, height, 0, data_format, GL_UNSIGNED_BYTE,
                        None if pixels is None else pixels.ctypes.data)
        return name.value

    def _lookup(self):
        """The palette as an array, rebuilt only when it changes."""
        version = getattr(self.device, "palette_version", None)
        if self.palette_lookup is None or version is None or version != self.palette_seen:
            self.palette_lookup = np.array(self.device.palette, dtype=np.uint8)
            self.palette_seen = version
        return self.palette_lookup

    def _update_layer(self):
        version = getattr(self.device, "layer_version", None)
        if version is not None and version == self.layer_seen:
            return
        self.layer_seen = version
        indices = np.frombuffer(self.device.buffers[self.device.front], dtype=np.uint8)
        rgb = self._lookup()[indices]
        gl.glBindTexture(GL_TEXTURE_2D, self.layer)
        gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, p.WIDTH, p.HEIGHT, GL_RGB, GL_UNSIGNED_BYTE, rgb.ctypes.data)

    def _texture_for(self, row, size):
        """A DTGC texture block as a graphics card texture. It wraps like the hardware's address mask does."""
        if self.textures_seen != self.device.texture_version:
            for name in self.textures.values():
                gl.glDeleteTextures(1, glwindow.ctypes.byref(glwindow.ctypes.c_uint(name)))
            self.textures = {}
            self.textures_seen = self.device.texture_version
        key = (row, size)
        if key not in self.textures:
            side = 1 << size
            store = np.frombuffer(self.device.texture, dtype=np.uint8).reshape(2048, 256)
            rows = np.arange(row, row + side) & 0x7FF
            rgb = self._lookup()[store[rows, :side]]
            self.textures[key] = self._new_texture(GL_RGB8, side, side, GL_RGB, GL_NEAREST, GL_REPEAT, rgb)
        return self.textures[key]

    def _arrays(self, batches):
        """Turns the kept triangles into the arrays OpenGL wants. Only done once for each new frame."""
        if batches is self.frame_source:
            return self.frame_arrays
        self.frame_source = batches
        out = []
        for mode, row, size, vertices in batches:
            data = np.array(vertices, dtype=np.float32)
            xyz = np.empty((len(data), 3), dtype=np.float32)
            xyz[:, :2] = data[:, :2] / 16.0
            # The projection below turns this into window depth 0 for z = 0 and 1 for z = 65535.
            xyz[:, 2] = 1.0 - data[:, 2] / 32767.5
            colors = data[:, 3:6].astype(np.uint8)
            uvs = data[:, 6:8] / float(1 << size)
            out.append((mode, row, size, xyz, colors, uvs))
        self.frame_arrays = out
        return out

    def draw(self, width, height):
        x, y, shown_width, shown_height = fit_picture(width, height)
        gl.glViewport(0, 0, width, height)
        gl.glDisable(GL_SCISSOR_TEST)
        gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        gl.glViewport(x, y, shown_width, shown_height)
        gl.glEnable(GL_SCISSOR_TEST)
        gl.glScissor(x, y, shown_width, shown_height)
        gl.glMatrixMode(GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0.0, float(p.WIDTH), float(p.HEIGHT), 0.0, -1.0, 1.0)
        gl.glMatrixMode(GL_MODELVIEW)
        gl.glLoadIdentity()

        self._update_layer()
        gl.glDisable(GL_DEPTH_TEST)
        gl.glEnable(GL_TEXTURE_2D)
        gl.glBindTexture(GL_TEXTURE_2D, self.layer)
        gl.glColor3f(1.0, 1.0, 1.0)
        gl.glBegin(GL_QUADS)
        for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
            gl.glTexCoord2f(float(u), float(v))
            gl.glVertex2f(float(u * p.WIDTH), float(v * p.HEIGHT))
        gl.glEnd()

        batches = getattr(self.device, "shown_batches", None)
        if not batches:
            return
        gl.glEnableClientState(GL_VERTEX_ARRAY)
        gl.glEnableClientState(GL_COLOR_ARRAY)
        for mode, row, tex_size, xyz, colors, uvs in self._arrays(batches):
            depth = mode > 0 and mode & raster.MODE_DEPTH
            textured = mode > 0 and mode & raster.MODE_TEXTURE
            (gl.glEnable if depth else gl.glDisable)(GL_DEPTH_TEST)
            gl.glVertexPointer(3, GL_FLOAT, 0, xyz.ctypes.data)
            if textured:
                gl.glDisableClientState(GL_COLOR_ARRAY)
                gl.glColor3f(1.0, 1.0, 1.0)
                gl.glEnable(GL_TEXTURE_2D)
                gl.glBindTexture(GL_TEXTURE_2D, self._texture_for(row, tex_size))
                gl.glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                gl.glTexCoordPointer(2, GL_FLOAT, 0, uvs.ctypes.data)
            else:
                gl.glDisable(GL_TEXTURE_2D)
                gl.glEnableClientState(GL_COLOR_ARRAY)
                gl.glColorPointer(3, GL_UNSIGNED_BYTE, 0, colors.ctypes.data)
            gl.glDrawArrays(GL_TRIANGLES, 0, len(xyz))
            if textured:
                gl.glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        gl.glDisableClientState(GL_VERTEX_ARRAY)
        gl.glDisableClientState(GL_COLOR_ARRAY)


def read_window(width, height):
    """What was just drawn, as a height x width x 3 array with the top row first. Used by the tests."""
    gl.glReadBuffer(GL_BACK)
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    gl.glPixelStorei(0x0D05, 1)  # GL_PACK_ALIGNMENT
    gl.glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE, pixels.ctypes.data)
    return pixels[::-1]


class FrameCounter:
    def __init__(self, window, label):
        self.window, self.label = window, label
        self.started = time.perf_counter()
        self.count = 0
        self.total = 0
        self.rate = 0.0

    def tick(self):
        self.count += 1
        self.total += 1
        elapsed = time.perf_counter() - self.started
        if elapsed >= 0.5:
            self.rate = self.count / elapsed
            width, height = self.window.size()
            self.window.set_title(f"DTGC laptop - {self.label} - {self.window.renderer} - {width}x{height} - {self.rate:.0f} fps")
            self.started, self.count = time.perf_counter(), 0


# Demos ----------------------------------------------------------------------------------------------------------------
class Field:
    """A wave rolling through a field of small cubes, with the colours running across it. 2352 triangles a frame."""
    SIDE = 14

    def __init__(self):
        self.frame = 0
        self.meshes = {}
        for row in range(self.SIDE):
            for column in range(self.SIDE):
                red, green, blue = colorsys.hsv_to_rgb((row + column) / (2 * self.SIDE), 0.75, 1.0)
                color = (int(red * 255), int(green * 255), int(blue * 255))
                self.meshes[row, column] = Mesh.cube(0.3, [color] * 6)

    def step(self, _keys):
        self.frame += 1

    def draw(self, canvas):
        canvas.clear_scene(0x00)
        time_now = self.frame * 0.05
        for row in range(self.SIDE):
            for column in range(self.SIDE):
                x, z = (column - (self.SIDE - 1) / 2) * 0.72, row * 0.72 + 4.0
                wave = 0.45 * math.sin(math.hypot(x, z - 8.5) * 1.1 - time_now)
                canvas.draw_mesh(self.meshes[row, column], (x, 2.3 + wave - row * 0.21, z), 0.35 + wave, wave * 1.5, distance=0.0)


class Bars:
    """The same colour bars as the bars command, for checking colours and the way the picture fits the screen."""

    def step(self, _keys):
        pass

    def draw(self, canvas):
        colors = [0xFF, 0xFC, 0x1F, 0x1C, 0xE3, 0xE0, 0x03, 0x00]
        width = p.WIDTH // len(colors)
        for i, color in enumerate(colors):
            canvas.gpu.rect(i * width, 0, width if i < 7 else p.WIDTH - i * width, p.HEIGHT, color)


class Spin:
    def __init__(self):
        self.frame = 0

    def step(self, _keys):
        self.frame += 1

    def draw(self, canvas):
        from . import demo
        canvas.clear_scene(demo.BACKGROUND)
        for triangle in demo.triangles(self.frame * 0.04):
            canvas.draw(triangle)


def _make_demo(name):
    from . import games
    if name == "cube":
        return Spin(), 60
    if name == "field":
        return Field(), 60
    if name == "bars":
        return Bars(), 60
    game = games.GAMES[name]()
    return game, getattr(game, "FPS", 30)  # most games were made for 30 steps a second, the kart race for 60


def run_demo(name, exact=False, fullscreen=False, frames=None, vsync=True, size=(1280, 800), out=print):
    """Runs a demo or game in the window. Returns (frames drawn, seconds, the window's fps, graphics card name)."""
    window = glwindow.Window(f"DTGC laptop - {name}", *size, fullscreen=fullscreen, vsync=vsync)
    device = emulator.Device() if exact else SharpDevice()
    renderer = Renderer(device, smooth_scaling=exact)
    canvas = Canvas(LocalGpu(device))
    game, steps_per_second = _make_demo(name)
    counter = FrameCounter(window, "exact" if exact else "sharp")
    out(f"Drawing with: {window.renderer} (OpenGL {window.gl_version}), {window.samples}x smoothing, vsync {'on' if window.vsync else 'off'}")
    started = time.perf_counter()
    stepped = 0
    while window.poll() and (frames is None or counter.total < frames):
        # Game speed follows the clock, however fast the screen refreshes.
        wanted = int((time.perf_counter() - started) * steps_per_second) + 1
        if frames is not None:
            wanted = counter.total + 1
        if wanted > stepped:
            stepped = wanted
            game.step(window.keys)
            game.draw(canvas)
            canvas.show()
        renderer.draw(*window.size())
        window.present()
        counter.tick()
    seconds = time.perf_counter() - started
    result = (counter.total, seconds, counter.total / seconds if seconds else 0.0, window.renderer)
    out(f"{result[0]} frames in {seconds:.2f} s, {result[2]:.1f} fps on this PC's graphics card")
    window.close()
    return result


class ReadBackScreen:
    """What the Renderer needs to show pictures that came back from the board."""

    def __init__(self):
        self.buffers = [bytearray(p.WIDTH * p.HEIGHT)]
        self.front = 0
        self.palette = emulator.default_palette()
        self.shown_batches = []

    def show(self, pixels, colors_set):
        self.buffers[0][:] = pixels
        for number, color in colors_set.items():
            self.palette[number] = color


def view(gpu, name="cube", fullscreen=False, frames=None, vsync=False, size=(1280, 800), out=print):
    """The USB-output version. The board draws each frame, then the whole picture comes back to be shown here."""
    window = glwindow.Window(f"DTGC USB output - {name}", *size, fullscreen=fullscreen, vsync=vsync, samples=0)
    screen = ReadBackScreen()
    renderer = Renderer(screen, smooth_scaling=True)
    canvas = Canvas(gpu)
    game, steps_per_second = _make_demo(name)
    counter = FrameCounter(window, "USB output")
    started = time.perf_counter()
    stepped = 0
    out(f"Scaling with: {window.renderer}. Each frame moves {p.WIDTH * p.HEIGHT} pixels over the link.")
    while window.poll() and (frames is None or counter.total < frames):
        # A slow link cannot show every step, but the game still runs at its proper speed.
        wanted = int((time.perf_counter() - started) * steps_per_second) + 1
        for _ in range(min(wanted - stepped, 8) if frames is None else 1):
            game.step(window.keys)
        stepped = wanted
        game.draw(canvas)
        canvas.show()
        screen.show(gpu.read_frame(), gpu.colors_set)
        renderer.draw(*window.size())
        window.present()
        counter.tick()
    seconds = time.perf_counter() - started
    rate = counter.total / seconds if seconds else 0.0
    out(f"{counter.total} pictures back in {seconds:.2f} s: {rate:.1f} fps, {rate * p.WIDTH * p.HEIGHT / 1e6:.1f} MB/s of pixels")
    window.close()
    return counter.total, seconds, rate


def serve(port=7654, exact=False, fullscreen=False, frames=None, vsync=True, size=(1280, 800), out=print):
    """Acts as the GPU for other commands: anything that can reach the emulator now draws into this window."""
    window = glwindow.Window("DTGC laptop", *size, fullscreen=fullscreen, vsync=vsync)
    server = emulator.Server(port)
    if not exact:
        server.device = SharpDevice(on_swap=server._swapped)
    server.start()
    renderer = Renderer(server.device, smooth_scaling=exact)
    counter = FrameCounter(window, "exact" if exact else "sharp")
    out(f"Listening on port {server.port}, drawing with {window.renderer}. Close the window to stop.")
    shown = -1
    try:
        while window.poll() and (frames is None or counter.total < frames):
            with server.lock:
                if exact and server.frames != shown:
                    shown = server.frames
                    renderer.layer_seen = -1
                renderer.draw(*window.size())
            window.present()
            counter.tick()
    finally:
        server.stop()
        window.close()
