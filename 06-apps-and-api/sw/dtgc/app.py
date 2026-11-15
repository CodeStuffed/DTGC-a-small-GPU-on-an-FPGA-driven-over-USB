"""The DTGC app: pick which version you have, then press a button. Nobody needs the command line.

Usage: python -m sw.dtgc app [--watch]

Three versions, one app:
  This PC only       no extra hardware. The PC's own graphics card draws, and the picture fits any screen.
  Board, HDMI out    the board draws to a monitor.
  Board, USB out     the board draws, sends each finished picture back, and a window here shows it, scaled to fit.

Each button runs the matching command as its own program, and its messages appear in the box below.

"Load onto the board" sends the chosen FPGA design to the board with openFPGALoader (sw/dtgc/flash.py), and picking a
design also picks the picture size that design draws. "Write a microSD card" records the games and saves DTGC.BIN on the
card you pick, for the 720p60x4_sd design to play with no PC (docs/sdcard.md). "Check my setup" says what this PC has and which USB drivers
the board is using (sw/dtgc/check.py). "Play Doom" needs the engine set up once with scripts/get_doom.py.

The window comes to the front when a board is plugged in, and Windows shows a notification. It looks for a new USB serial
port every 2 seconds and says hello on it, and only a device that answers like a DTGC counts. With --watch it starts
minimised and waits for that. The box "Open when a board is plugged in" adds it to what starts when you log in, and
clearing the box takes it out again.
"""
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

VERSIONS = (("laptop", "This PC only (no board)"), ("hdmi", "DTGC board, HDMI out"), ("usb", "DTGC board, USB out"))
# The picture the board draws, before it is scaled up to the monitor. It has to match the design loaded on the board.
PICTURES = (
    ("340x340", "340 x 340    first builds, 720p and 1080p50"),
    ("960x540", "960 x 540    1080p30, scaled 2x"),
    ("640x360", "640 x 360    1080p30, scaled 3x"),
    ("480x270", "480 x 270    1080p30, scaled 4x"),
    ("384x216", "384 x 216    1080p30, scaled 5x"),
    ("320x180", "320 x 180    1080p30 scaled 6x, 720p60 scaled 4x"),
    ("274x154", "274 x 154    1080p30, scaled 7x"),
)

ACTIONS = (
    ("Test the link", "test"),
    ("Colour bars", "bars"),
    ("Spinning cube", "cube"),
    ("Cube field", "field"),
    ("Measure speed", "speed"),
    ("Mirror my screen", "mirror"),
    ("Play Kart Sprint", "kart"),
    ("Play Pong", "pong"),
    ("Play Maze", "maze"),
    ("Play Dodge", "dodge"),
    ("Play Doom", "doom"),
    ("Write a microSD card", "sdcard"),
    ("Pretend board (emulator)", "emulator"),
    ("Check my setup", "check"),
)

BACKGROUND, PANEL, TEXT, MUTED, ACCENT = "#14171c", "#20252c", "#e8eaed", "#9aa3ad", "#39c5a0"
WATCH_SECONDS = 2.0
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def arguments_for(version, action, fullscreen=False, exact=False):
    """The command for a button, or None when that version cannot do it."""
    window_options = ["--fullscreen"] if fullscreen else []
    if action == "check":
        return ["check"]
    if action == "sdcard":
        return ["sdcard", "write"]       # the app asks where the card is when the button is pressed
    if action == "doom":
        # USB out has no monitor on the board, and Doom's frames are made on the PC anyway, so there it has no use.
        return {"laptop": ["doom", "--window"], "hdmi": ["doom"]}.get(version)
    if action == "emulator":
        return None if version == "laptop" else ["emulator", "--window"]
    if version == "laptop":
        if action in ("test", "mirror"):
            return None
        if action == "speed":
            return ["laptop", "--demo", "field", "--frames", "600", "--no-vsync", *window_options]
        return ["laptop", "--demo", action, *window_options, *(["--exact"] if exact else [])]
    if action == "test":
        return ["selftest"]
    if action == "speed":
        return ["benchmark"]
    if version == "usb":
        return None if action == "mirror" else ["view", "--demo", action, *window_options]
    if action == "bars":
        return ["bars"]
    if action == "cube":
        return ["spin"]
    if action == "field":
        return ["spin", "--scene", "field"]
    if action == "mirror":
        return ["mirror", "--frames", "300"]
    return ["play", action]


def run_command(arguments, on_line, picture=None):
    """Runs one command and passes each line it prints to on_line. Returns its exit code."""
    environment = {**os.environ, "DTGC_PICTURE": picture} if picture else None
    no_console = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen([sys.executable, "-m", "sw.dtgc", *arguments], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, text=True, env=environment, creationflags=no_console)
    with process.stdout:
        for line in process.stdout:
            on_line(line.rstrip())
    return process.wait()


def designs():
    """The built FPGA designs the loader can send, as (name, picture or None, text). Empty when none are built."""
    from . import flash
    return [(name, picture, text) for name, _path, picture, _link, text in flash.available()]


def flash_arguments(name, keep=False):
    """keep: write the design to the board's flash chip, so it starts by itself at every power-on."""
    return ["flash", name, *(["--keep"] if keep else [])]


_BALLOON = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
            "$n.Visible = $true; $n.ShowBalloonTip(5000, $env:DTGC_NOTE_TITLE, $env:DTGC_NOTE_TEXT, 'Info'); "
            "Start-Sleep -Seconds 6; $n.Dispose()")


def notification_command(title, text):
    """(command, extra environment) that shows a notification from the system, or None when there is no way to.

    The words travel in the environment, so nothing in them is ever read as part of the command.
    """
    import shutil
    if sys.platform == "win32":
        return (["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _BALLOON],
                {"DTGC_NOTE_TITLE": title, "DTGC_NOTE_TEXT": text})
    if shutil.which("notify-send"):
        return ["notify-send", "--", title, text], {}
    return None


def notify(title, text):
    """Shows a notification and does not wait for it. Returns the started program, or None. Never raises."""
    found = notification_command(title, text)
    if not found:
        return None
    command, extra = found
    try:
        return subprocess.Popen(command, env={**os.environ, **extra}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except OSError:
        return None


class BoardWatcher:
    """Notices a board arriving. Ports it has already tried wait until they are unplugged, so nothing gets hello twice."""

    def __init__(self, list_ports, says_hello):
        self.list_ports = list_ports
        self.says_hello = says_hello
        self.tried = set()

    def poll(self):
        """Returns the name of a port that has just answered, or None."""
        ports = set(self.list_ports())
        self.tried &= ports
        for port in sorted(ports - self.tried):
            self.tried.add(port)
            if self.says_hello(port):
                return port
        return None


def _usb_serial_ports():
    from serial.tools import list_ports

    from .client import usb_ports
    return usb_ports(list_ports.comports())


def _says_hello(port):
    from .client import Dtgc
    from .transport import SerialTransport
    transport = None
    try:
        transport = SerialTransport(port, 3000000)
        Dtgc(transport, give_up_seconds=0.5)
        return True
    except Exception:
        return False
    finally:
        if transport:
            transport.close()


def autostart_file():
    """Where the login entry goes outside Windows."""
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "dtgc.desktop"


def autostart_command():
    """What to run at login: the packaged app, set by its launcher. None when running from source."""
    program = os.environ.get("DTGC_EXE")
    return f'"{program}" --watch' if program else None


def autostart_enabled():
    if sys.platform != "win32":
        return autostart_file().exists()
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, "DTGC")
        return True
    except OSError:
        return False


def set_autostart(enabled):
    """Adds or removes the login entry for this user only. Nothing needs administrator rights."""
    command = autostart_command()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, "DTGC", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "DTGC")
                except FileNotFoundError:
                    pass
    elif enabled:
        autostart_file().parent.mkdir(parents=True, exist_ok=True)
        autostart_file().write_text(f"[Desktop Entry]\nType=Application\nName=DTGC\nExec={command}\n")
    else:
        autostart_file().unlink(missing_ok=True)


def bring_to_front(root):
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    root.after(600, lambda: root.attributes("-topmost", False))
    root.focus_force()


def main(close_after_ms=None, watch=False, announce=True):
    import tkinter

    root = tkinter.Tk()
    root.title("DTGC")
    root.configure(bg=BACKGROUND)
    icon = Path(__file__).with_name("dtgc.ico")
    if sys.platform == "win32" and icon.exists():
        root.iconbitmap(str(icon))
    messages = queue.Queue()
    arrivals = queue.Queue()
    version = tkinter.StringVar(root, "laptop")
    picture = tkinter.StringVar(root, PICTURES[0][0])
    fullscreen = tkinter.BooleanVar(root, False)
    exact = tkinter.BooleanVar(root, False)
    autostart = tkinter.BooleanVar(root, autostart_enabled())
    keep = tkinter.BooleanVar(root, False)
    running = [0]
    stopping = threading.Event()

    def choice(kind, parent, **options):
        return kind(parent, bg=PANEL, fg=TEXT, activebackground=PANEL, activeforeground=TEXT, selectcolor=BACKGROUND,
                    anchor="w", **options)

    header = tkinter.Frame(root, bg=BACKGROUND)
    header.pack(fill="x", padx=14, pady=(12, 4))
    tkinter.Label(header, text="DTGC", bg=BACKGROUND, fg=TEXT, font=("Segoe UI", 20, "bold")).pack(side="left")
    status = tkinter.Label(header, text="No board found yet", bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 10))
    status.pack(side="right")

    panel = tkinter.Frame(root, bg=PANEL)
    panel.pack(fill="x", padx=14, pady=6)
    buttons = {}
    exact_box = None

    def refresh():
        for action, button in buttons.items():
            button.configure(state="normal" if arguments_for(version.get(), action) else "disabled")
        exact_box.configure(state="normal" if version.get() == "laptop" else "disabled")

    tkinter.Label(panel, text="Which version?", bg=PANEL, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 0))
    for name, label in VERSIONS:
        choice(tkinter.Radiobutton, panel, text=label, value=name, variable=version, command=refresh).pack(fill="x", padx=10)
    def menu(parent, variable, labels, on_pick=None):
        """A drop-down list in the app's colours. variable holds the label shown."""
        box = tkinter.OptionMenu(parent, variable, *labels, command=on_pick)
        box.configure(bg=BACKGROUND, fg=TEXT, activebackground=ACCENT, activeforeground=BACKGROUND, relief="flat",
                      highlightthickness=1, highlightbackground=MUTED, anchor="w", font=("Consolas", 9))
        box["menu"].configure(bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BACKGROUND, font=("Consolas", 9))
        return box

    picture_labels = {label: name for name, label in PICTURES}
    picture_shown = tkinter.StringVar(root, PICTURES[0][1])
    tkinter.Label(panel, text="Picture the board draws (must match the design on the board)", bg=PANEL, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 0))
    menu(panel, picture_shown, list(picture_labels), lambda label: picture.set(picture_labels[label])).pack(fill="x", padx=10, pady=(2, 0))

    built = designs()
    design_labels = {f"{name:12} {text}": (name, size) for name, size, text in built}
    design_shown = tkinter.StringVar(root, next(iter(design_labels), "No designs built yet: python scripts/build_all.py"))

    def pick_design(label):
        size = design_labels[label][1]
        if size:  # the picture has to match the design, so choosing one sets the other
            picture.set(size)
            picture_shown.set(dict(PICTURES)[size])

    tkinter.Label(panel, text="FPGA design to load", bg=PANEL, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 0))
    flash_row = tkinter.Frame(panel, bg=PANEL)
    flash_row.pack(fill="x", padx=10, pady=(2, 0))
    flash_button = tkinter.Button(flash_row, text="Load onto the board", bg=BACKGROUND, fg=TEXT, activebackground=ACCENT,
                                  activeforeground=BACKGROUND, disabledforeground="#5a626b", relief="flat", padx=10, pady=4,
                                  state="normal" if built else "disabled",
                                  command=lambda: start(f"Load {design_labels[design_shown.get()][0]} onto the board", None,
                                                        flash_arguments(design_labels[design_shown.get()][0], keep.get())))
    flash_button.pack(side="right", padx=(6, 0))
    menu(flash_row, design_shown, list(design_labels) or [design_shown.get()], pick_design if built else None).pack(side="left", fill="x", expand=True)
    choice(tkinter.Checkbutton, panel, text="Keep it on the board after unplugging", variable=keep).pack(fill="x", padx=10)
    tkinter.Label(panel, text="Options", bg=PANEL, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 0))
    choice(tkinter.Checkbutton, panel, text="Full screen (F11 also works, Esc leaves)", variable=fullscreen).pack(fill="x", padx=10)
    exact_box = choice(tkinter.Checkbutton, panel, text="Show exactly what the real hardware would draw", variable=exact)
    exact_box.pack(fill="x", padx=10)
    auto_box = choice(tkinter.Checkbutton, panel, text="Open when a board is plugged in", variable=autostart,
                      command=lambda: set_autostart(autostart.get()))
    auto_box.pack(fill="x", padx=10, pady=(0, 8))
    if not autostart_command():
        auto_box.configure(state="disabled")

    def start(label, action, arguments=None):
        arguments = arguments or arguments_for(version.get(), action, fullscreen.get(), exact.get())
        chosen = picture.get()
        if action == "sdcard":
            from tkinter import filedialog
            where = filedialog.askdirectory(parent=root, title="Pick the microSD card (formatted FAT32)")
            if not where:
                return
            arguments = [*arguments, where]
            chosen = "320x180"           # the size the card design draws

        def work():
            messages.put(f"--- {label}")
            running[0] += 1
            try:
                code = run_command(arguments, messages.put, chosen)
            finally:
                running[0] -= 1
            messages.put("--- finished" if code == 0 else f"--- stopped with exit code {code}")
        threading.Thread(target=work, daemon=True).start()

    grid = tkinter.Frame(root, bg=BACKGROUND)
    grid.pack(fill="x", padx=14, pady=4)
    for index, (label, action) in enumerate(ACTIONS):
        buttons[action] = tkinter.Button(grid, text=label, bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BACKGROUND,
                                         disabledforeground="#5a626b", relief="flat", padx=6, pady=7,
                                         command=lambda l=label, a=action: start(l, a))
        buttons[action].grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)
    grid.columnconfigure(0, weight=1, uniform="buttons")
    grid.columnconfigure(1, weight=1, uniform="buttons")
    log = tkinter.Text(root, width=70, height=10, state="disabled", bg=PANEL, fg=TEXT, relief="flat", font=("Consolas", 9))
    log.pack(padx=14, pady=(6, 14), fill="both", expand=True)
    refresh()

    def watch_for_boards():
        watcher = BoardWatcher(_usb_serial_ports, _says_hello)
        while not stopping.wait(WATCH_SECONDS):
            try:
                # A running command may own the port, and a hello would disturb it.
                port = None if running[0] else watcher.poll()
            except Exception:  # no serial library, or the port list failed: the buttons all still work
                return
            if port:
                arrivals.put(port)

    def show_messages():
        # Only this thread may touch the window, so the worker threads leave their lines in a queue.
        while not messages.empty():
            log.configure(state="normal")
            log.insert("end", messages.get() + "\n")
            log.configure(state="disabled")
            log.see("end")
        while not arrivals.empty():
            port = arrivals.get()
            status.configure(text=f"Board found on {port}", fg=ACCENT)
            if version.get() == "laptop":
                version.set("hdmi")
                refresh()
            messages.put(f"--- A DTGC board answered on {port}")
            bring_to_front(root)
            if announce:
                notify("DTGC board found", f"A DTGC board answered on {port}.")
        timer[0] = root.after(100, show_messages)

    def close():
        stopping.set()
        root.after_cancel(timer[0])
        root.destroy()

    timer = [None]
    show_messages()
    root.protocol("WM_DELETE_WINDOW", close)
    threading.Thread(target=watch_for_boards, daemon=True).start()
    if watch:
        root.iconify()
    else:
        bring_to_front(root)
    if close_after_ms is not None:
        root.after(close_after_ms, close)
    root.mainloop()
