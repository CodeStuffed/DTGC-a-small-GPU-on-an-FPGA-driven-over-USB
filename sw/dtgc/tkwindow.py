"""A plain window for the demos and the USB-output version, where the OpenGL window (glwindow.py, Windows only) is missing.

Usage:
    python -m sw.dtgc laptop --demo cube --tk
    python -m sw.dtgc view --demo cube --tk

The picture is drawn on the CPU exactly as the hardware would, then shown by tkinter, which comes with Python on every
system. The picture grows by whole numbers to fit the window, so it stays sharp. It is much slower than the OpenGL window.
"""
import time

from . import emulator
from . import protocol as p
from .api import Canvas

KEY_NAMES = {"Up": "up", "Down": "down", "Left": "left", "Right": "right", "space": "space", "Return": "enter"}


def whole_scale(width, height):
    """The largest whole number the picture can grow by and still fit in this size, at least 1."""
    return max(1, min(width // p.WIDTH, height // p.HEIGHT))


def ppm(rgb):
    """RGB bytes of the picture as a PPM image, which tkinter can read with no other library."""
    return f"P6 {p.WIDTH} {p.HEIGHT} 255 ".encode() + rgb


def run(name, gpu=None, fullscreen=False, frames=None, size=(1280, 800), out=print):
    """Runs a demo or game. With gpu, the board draws and each picture comes back. Returns (frames, seconds, fps)."""
    import tkinter

    from . import laptop

    device = emulator.Device()
    screen = laptop.ReadBackScreen()
    canvas = Canvas(gpu or laptop.LocalGpu(device))
    game, steps_per_second = laptop._make_demo(name)
    keys = set()

    root = tkinter.Tk()
    root.title(f"DTGC - {name}")
    root.geometry(f"{size[0]}x{size[1]}")
    root.configure(bg="black")
    root.attributes("-fullscreen", fullscreen)
    label = tkinter.Label(root, bg="black", borderwidth=0)
    label.pack(expand=True, fill="both")
    root.bind("<KeyPress>", lambda event: keys.add(KEY_NAMES.get(event.keysym, event.keysym)))
    root.bind("<KeyRelease>", lambda event: keys.discard(KEY_NAMES.get(event.keysym, event.keysym)))
    root.bind("<F11>", lambda _: root.attributes("-fullscreen", not root.attributes("-fullscreen")))
    root.bind("<Escape>", lambda _: root.attributes("-fullscreen", False))

    state = {"frames": 0, "stepped": 0, "image": None}
    started = time.perf_counter()

    def tick():
        wanted = int((time.perf_counter() - started) * steps_per_second) + 1
        for _ in range(min(wanted - state["stepped"], 8) if frames is None else 1):
            game.step(keys)
        state["stepped"] = wanted
        game.draw(canvas)
        canvas.show()
        if gpu:
            screen.show(gpu.read_frame(), gpu.colors_set)
            lookup = [bytes(c) for c in screen.palette]
            rgb = b"".join(lookup[v] for v in screen.buffers[0])
        else:
            rgb = device.window_rgb()
        image = tkinter.PhotoImage(data=ppm(rgb), format="PPM")
        scale = whole_scale(root.winfo_width(), root.winfo_height())
        state["image"] = image.zoom(scale) if scale > 1 else image
        label.configure(image=state["image"])
        state["frames"] += 1
        if frames is not None and state["frames"] >= frames:
            root.destroy()
        else:
            root.after(1, tick)

    root.after(1, tick)
    root.mainloop()
    seconds = time.perf_counter() - started
    rate = state["frames"] / seconds if seconds else 0.0
    out(f"{state['frames']} frames in {seconds:.2f} s, {rate:.1f} fps, drawn on the CPU and shown by tkinter")
    return state["frames"], seconds, rate
