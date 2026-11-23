"""Doom on DTGC: the real open-source Doom engine draws each frame, and the board shows it.

Usage: python -m sw.dtgc doom [--wad FILE] [--engine FILE] [--scale N] [--frames N]

Run "python scripts/get_doom.py" once first. It fetches and builds the engine (doomgeneric) and tells you where to put a
game file. The game file is a **WAD**: the levels, pictures and sounds. Freedoom is a free one.

How it fits together: the engine runs on the PC as its own program and works out every frame, 320x200 pixels with one
byte each, a number into a table of 256 colours. That is the form DTGC stores, so nothing is converted. This module
sends the colour table and the frame to the board, where only the squares that changed are sent, and passes the keys
from its window back to the engine. The board is the screen here: it does not run the game's code.

Keys: arrows move, Ctrl fires, Space opens doors, Shift runs, Alt or , and . step sideways, Esc is the menu.
There is no sound. Keep this window selected while playing.

The picture must be at least 320x200 to show the whole frame: 384x216 (the 5x build) suits it best, and 340x340,
480x270, 640x360 and 960x540 hold it too. On a smaller picture the frame is shrunk to fit.
"""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import protocol as p
from .emulator import default_palette
from .stream import FrameStreamer

PORT_VARIABLE = "DTGC_DOOM_PORT"
ENGINES = ("dtgc_doom.exe", "dtgc_doom")
WADS = ("freedoom1.wad", "freedoom2.wad", "doom1.wad", "doom.wad", "doom2.wad", "tnt.wad", "plutonia.wad", "freedm.wad")

# Key numbers sent to the engine. Below 128 a number is the plain character. sw/doom/doomgeneric_dtgc.c holds the same list.
LEFT, RIGHT, UP, DOWN, FIRE, USE, STRAFE_LEFT, STRAFE_RIGHT, RUN, STRAFE, ESCAPE, ENTER, TAB, BACKSPACE, PAUSE, F1 = range(128, 144)
NAMED_KEYS = {
    "Left": LEFT, "Right": RIGHT, "Up": UP, "Down": DOWN, "Control_L": FIRE, "Control_R": FIRE, "space": USE,
    "comma": STRAFE_LEFT, "period": STRAFE_RIGHT, "Shift_L": RUN, "Shift_R": RUN, "Alt_L": STRAFE, "Alt_R": STRAFE,
    "Escape": ESCAPE, "Return": ENTER, "KP_Enter": ENTER, "Tab": TAB, "BackSpace": BACKSPACE, "Pause": PAUSE,
    "minus": ord("-"), "equal": ord("="), "plus": ord("+"), "slash": ord("/"), "asterisk": ord("*"),
    **{f"F{n}": F1 + n - 1 for n in range(1, 13)},
}


def key_number(keysym):
    """The number to send for a key, from the name tkinter gives it. None for a key the game has no use for."""
    if keysym in NAMED_KEYS:
        return NAMED_KEYS[keysym]
    if len(keysym) == 1 and 32 < ord(keysym) < 127:
        return ord(keysym.lower())
    return None


def folders():
    """Where the engine and game files are looked for."""
    places = [Path.cwd() / "build" / "doom", Path(__file__).resolve().parents[2] / "build" / "doom"]
    if os.environ.get("DTGC_EXE"):
        places.append(Path(os.environ["DTGC_EXE"]).parent / "doom")
    return places


def find_engine():
    for folder in folders():
        for name in ENGINES:
            if (folder / name).exists():
                return folder / name
    return None


def find_wad():
    for folder in folders():
        if folder.is_dir():
            present = {path.name.lower(): path for path in folder.iterdir()}
            for name in WADS:
                if name in present:
                    return present[name]
    return None


class Engine:
    """The link to the engine program. A thread reads what the engine sends and keeps only the newest frame."""

    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.connection = None
        self.process = None
        self.lock = threading.Lock()
        self.palette = None       # a colour table not yet taken
        self.frame = None         # (width, height, pixels) not yet taken
        self.title = None
        self.frames_drawn = 0
        self.closed = threading.Event()

    def start(self, command):
        """Starts the engine program and waits for it to connect, in the background."""
        environment = {**os.environ, PORT_VARIABLE: str(self.port)}
        self.process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, cwd=str(Path(command[0]).parent))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        self.listener.settimeout(0.5)
        while self.connection is None:
            try:
                self.connection, _ = self.listener.accept()
            except socket.timeout:
                if self.process and self.process.poll() is not None:  # the engine stopped before it connected
                    self.closed.set()
                    return
            except OSError:
                self.closed.set()
                return
        try:
            while True:
                kind = self._exactly(1)
                if kind == b"P":
                    data = self._exactly(768)
                    with self.lock:
                        self.palette = [tuple(data[i:i + 3]) for i in range(0, 768, 3)]
                elif kind == b"D":
                    with self.lock:
                        self.palette = default_palette()
                elif kind == b"F":
                    size = self._exactly(4)
                    width, height = size[0] | size[1] << 8, size[2] | size[3] << 8
                    pixels = self._exactly(width * height)
                    with self.lock:
                        self.frame = (width, height, pixels)
                        self.frames_drawn += 1
                elif kind == b"T":
                    length = self._exactly(2)
                    self.title = self._exactly(length[0] | length[1] << 8).decode("latin-1")
                else:
                    raise ConnectionError(f"the engine sent a message this does not know: {kind!r}")
        except (ConnectionError, OSError):
            self.closed.set()

    def _exactly(self, count):
        data = bytearray()
        while len(data) < count:
            piece = self.connection.recv(count - len(data))
            if not piece:
                raise ConnectionError("the engine closed the link")
            data += piece
        return bytes(data)

    def take(self):
        """The colour table and the frame that arrived since the last call. Either may be None."""
        with self.lock:
            palette, frame = self.palette, self.frame
            self.palette = self.frame = None
        return palette, frame

    def key(self, pressed, number):
        if self.connection is not None and not self.closed.is_set():
            try:
                self.connection.sendall(bytes((ord("K"), 1 if pressed else 0, number)))
            except OSError:
                self.closed.set()

    def close(self):
        self.closed.set()
        for link in (self.connection, self.listener):
            if link is not None:
                try:
                    link.close()
                except OSError:
                    pass
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()


def shown_size(width, height, scale=1):
    """How large a frame is drawn in the board's picture: whole multiples when it fits, shrunk to fit when it does not."""
    if width <= p.WIDTH and height <= p.HEIGHT:
        factor = max(1, min(scale, p.WIDTH // width, p.HEIGHT // height))
        return width * factor, height * factor
    ratio = min(p.WIDTH / width, p.HEIGHT / height)
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def fit(pixels, width, height, scale=1):
    """Puts a frame in the middle of the board's picture, with colour 0 around it. Returns WIDTH x HEIGHT bytes."""
    new_width, new_height = shown_size(width, height, scale)
    columns = [x * width // new_width for x in range(new_width)]
    left, top = (p.WIDTH - new_width) // 2, (p.HEIGHT - new_height) // 2
    picture = bytearray(p.WIDTH * p.HEIGHT)
    same_columns = new_width == width
    last_row, last_bytes = None, None
    for y in range(new_height):
        source = y * height // new_height
        if source != last_row:
            row = pixels[source * width:(source + 1) * width]
            last_row, last_bytes = source, row if same_columns else bytes(map(row.__getitem__, columns))
        start = (top + y) * p.WIDTH + left
        picture[start:start + new_width] = last_bytes
    return bytes(picture)


class Player:
    """Moves frames from the engine to the GPU. step() is one turn of that, so tests can drive it without a window."""

    def __init__(self, engine, gpu, scale=1):
        self.engine = engine
        self.gpu = gpu
        self.scale = scale
        self.stream = FrameStreamer(gpu)
        self.frames_shown = 0
        self.tiles_sent = 0
        self.bytes_at_start = gpu.stats["bytes"]
        self.started = time.monotonic()

    def step(self):
        """Sends a new colour table and a new frame if there is one. Returns True when a frame went out."""
        palette, frame = self.engine.take()
        if palette:
            self.gpu.palette(0, palette)
        if not frame:
            if palette:
                self.gpu.flush()
            return False
        width, height, pixels = frame
        self.tiles_sent += self.stream.send_frame(fit(pixels, width, height, self.scale))
        self.frames_shown += 1
        return True

    def summary(self):
        seconds = max(time.monotonic() - self.started, 1e-9)
        sent = self.gpu.stats["bytes"] - self.bytes_at_start
        each = sent // self.frames_shown if self.frames_shown else 0
        return (f"{self.frames_shown} frames shown of {self.engine.frames_drawn} the engine drew, in {seconds:.1f} s. "
                f"{each} bytes a frame on average over the link.")


def command_for(engine_path, wad, extra=()):
    """The engine runs in its own folder, where it keeps its settings and saved games, so the game file is named in full."""
    return [str(engine_path), *(["-iwad", str(Path(wad).resolve())] if wad else []), *extra]


def missing_message(engine_path, wad):
    """What to tell someone who has not set Doom up yet, or None when both parts are there."""
    lines = []
    if not engine_path:
        lines.append("The Doom engine has not been built yet. Run this once: python scripts/get_doom.py")
    if not wad:
        lines.append("No game file found. Put a WAD such as freedoom1.wad or doom1.wad in build/doom, or name one with --wad FILE.")
        lines.append("python scripts/get_doom.py --freedoom fetches the free one.")
    return "\n".join(lines) or None


def run(gpu, device, engine_path, wad, extra=(), frames=None, scale=1):
    """Plays in a window that takes the keys. With device set (the private emulator) the window also shows the picture."""
    import tkinter

    engine = Engine()
    engine.start(command_for(engine_path, wad, extra))
    player = Player(engine, gpu, scale)
    root = tkinter.Tk()
    root.title("DTGC Doom")
    held = set()
    zoom = 2 if device and p.WIDTH <= 480 else 1
    picture = tkinter.PhotoImage(width=p.WIDTH, height=p.HEIGHT) if device else None
    shown = [None]
    if picture:
        label = tkinter.Label(root, bd=0)
        label.pack()
    else:
        tkinter.Label(root, text="Keep this window selected. The game is on the HDMI screen.\n"
                                 "Arrows move, Ctrl fires, Space opens doors, Shift runs, Esc is the menu.").pack(padx=20, pady=20)

    def press(event):
        number = key_number(event.keysym)
        if number is not None and number not in held:  # holding a key repeats the press here; the game wants it once
            held.add(number)
            engine.key(True, number)

    def release(event):
        number = key_number(event.keysym)
        if number in held:
            held.discard(number)
            engine.key(False, number)

    root.bind("<KeyPress>", press)
    root.bind("<KeyRelease>", release)

    def turn():
        if engine.closed.is_set() or (frames is not None and player.frames_shown >= frames):
            root.destroy()
            return
        if player.step() and picture:
            picture.configure(data=f"P6 {p.WIDTH} {p.HEIGHT} 255 ".encode() + device.window_rgb(), format="PPM")
            shown[0] = picture.zoom(zoom) if zoom > 1 else picture
            label.configure(image=shown[0])
        if engine.title:
            root.title(f"DTGC Doom: {engine.title}")
        root.after(2, turn)

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.after(0, turn)
    try:
        root.mainloop()
    finally:
        engine.close()
    print(player.summary())


if __name__ == "__main__":
    sys.exit("Run: python -m sw.dtgc doom")
