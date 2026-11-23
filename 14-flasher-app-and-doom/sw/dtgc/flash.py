"""Loads a DTGC design onto the Tang Nano 20K, using openFPGALoader.

Usage: python -m sw.dtgc flash                    list the designs that are built
       python -m sw.dtgc flash NAME               load one into the FPGA. It stays until the power goes off
       python -m sw.dtgc flash NAME --keep        write it to the board's flash chip, so it starts at every power-on
       python -m sw.dtgc flash --detect           only ask the FPGA to say what it is
       python -m sw.dtgc flash NAME --dry-run     print the command and run nothing

NAME is a name from the list (1080p30x5), a file name (top_gpu_1080p30x5) or a path to a .fs file.

A **bitstream** is the file that tells the FPGA what circuit to be. Loading one into the FPGA's own memory is quick and
safe to repeat: pull the plug and the board is back to whatever its flash chip holds. --keep overwrites the flash chip,
which has not been tried on a real board yet (docs/verify.md), so start without it.

Nothing here has run against a real board. What openFPGALoader prints is passed on unchanged, and the common failures get
a plain explanation after it.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

BOARD = "tangnano20k"  # openFPGALoader's own name for this board
KNOWN_LOADER = r"C:\tools\oss-cad-suite\bin\openFPGALoader.exe"  # where docs/setup.md puts the OSS CAD Suite on Windows

# name, file, picture the PC should send (None: no PC link), link, what it is. In the order to try them on a new board.
BUILDS = (
    ("blink", "blink", None, None, "LEDs count in binary. The first test, no monitor needed"),
    ("colorbars", "top_colorbars", None, None, "8 colour bars at 640x480"),
    ("framebuffer", "top_framebuffer", None, None, "a test picture from the memory, 640x480"),
    ("gpu", "top_gpu", "340x340", "usb", "the GPU at 640x480"),
    ("gpu_usb", "top_gpu_usb", "340x340", "usb", "USB-output version: the picture goes back to the PC"),
    ("bars_720p", "bars_720p", None, None, "colour bars at 1280x720, 60 Hz"),
    ("bars_1080p30", "bars_1080p30", None, None, "colour bars at 1920x1080, 30 Hz"),
    ("bars_1080p50", "bars_1080p50", None, None, "colour bars at 1920x1080, 50 Hz"),
    ("hd", "top_gpu_hd", "340x340", "usb", "the GPU at 1280x720, picture scaled 2x"),
    ("hd_safe", "top_gpu_hd_safe", "340x340", "usb", "the same with a slower memory clock, if hd shows speckles"),
    ("1080p30", "top_gpu_1080p30", "960x540", "usb", "1920x1080 at 30 Hz, picture scaled 2x"),
    ("1080p30x3", "top_gpu_1080p30x3", "640x360", "usb", "1080p30, picture scaled 3x"),
    ("1080p30x4", "top_gpu_1080p30x4", "480x270", "usb", "1080p30, picture scaled 4x"),
    ("1080p30x5", "top_gpu_1080p30x5", "384x216", "usb", "1080p30, picture scaled 5x. The one for Doom"),
    ("1080p30x6", "top_gpu_1080p30x6", "320x180", "usb", "1080p30, picture scaled 6x"),
    ("1080p30x7", "top_gpu_1080p30x7", "274x154", "usb", "1080p30, picture scaled 7x"),
    ("1080p30dd", "top_gpu_1080p30dd", "960x540", "usb", "1080p30 2x with the dither pattern smoothed out"),
    ("1080p30x3dd", "top_gpu_1080p30x3dd", "640x360", "usb", "1080p30 3x, smoothed"),
    ("1080p30x4dd", "top_gpu_1080p30x4dd", "480x270", "usb", "1080p30 4x, smoothed"),
    ("1080p30x5dd", "top_gpu_1080p30x5dd", "384x216", "usb", "1080p30 5x, smoothed"),
    ("1080p30x6dd", "top_gpu_1080p30x6dd", "320x180", "usb", "1080p30 6x, smoothed"),
    ("1080p30x7dd", "top_gpu_1080p30x7dd", "274x154", "usb", "1080p30 7x, smoothed"),
    ("1080p50", "top_gpu_1080", "340x340", "usb", "1920x1080 at 50 Hz, picture scaled 3x"),
    ("720p60x4", "top_gpu_720p60x4", "320x180", "usb", "1280x720 at 60 Hz, picture scaled 4x. Made for the kart race"),
    ("720p60x4_sd", "top_gpu_720p60x4_sd", "320x180", "usb", "the same, and plays the microSD card with no PC (docs/sdcard.md)"),
    ("gpu_ft", "top_gpu_ft", "340x340", "ft", "640x480, for the xDTGC backpack (FT2232H link)"),
    ("gpu_usb_ft", "top_gpu_usb_ft", "340x340", "ft", "USB-output version, for the backpack"),
    ("hd_ft", "top_gpu_hd_ft", "340x340", "ft", "1280x720, for the backpack"),
    ("1080p30_ft", "top_gpu_1080p30_ft", "960x540", "ft", "1080p30 2x, for the backpack"),
    ("1080p50_ft", "top_gpu_1080_ft", "340x340", "ft", "1080p50, for the backpack"),
)

# Text openFPGALoader prints when it fails, and what to do about it. The first match is shown.
HELP = (
    ("unable to open ftdi device",
     "The loader did not find the board.\n"
     "  1. Use a USB-C cable that carries data, plugged straight into the PC, with no hub.\n"
     "  2. Run: python -m sw.dtgc check     It lists what Windows sees and which driver each part has.\n"
     "  3. If the board is listed but the loader still cannot open it, see \"Drivers\" in docs/flash.md."),
    ("JTAG init failed",
     "The loader could not talk to the board's programming port. Plug the board straight into the PC, with no hub,\n"
     "then run: python -m sw.dtgc check"),
    ("ftdi_usb_reset failed",
     "Others have reported this text with a Tang Nano 20K (openFPGALoader issue 454). Unplug the board, plug it straight\n"
     "into the PC and try again. If it comes back, copy the whole message into docs/test-log.md."),
    ("IDCODE", "The loader reached a chip but did not get the answer it expected. Copy the whole message into docs/test-log.md."),
)


def find_loader():
    """The path of openFPGALoader, or None. DTGC_LOADER names one directly, which the tests use."""
    named = os.environ.get("DTGC_LOADER")
    if named:
        return named
    # The portable app (USB stick) carries its own copy in loader\ beside dtgc.exe.
    if os.environ.get("DTGC_EXE"):
        packaged = Path(os.environ["DTGC_EXE"]).parent / "loader" / "openFPGALoader.exe"
        if packaged.exists():
            return str(packaged)
    found = shutil.which("openFPGALoader")
    if found:
        return found
    return KNOWN_LOADER if Path(KNOWN_LOADER).exists() else None


def folders():
    """Where bitstreams may be: a folder named in DTGC_FIRMWARE, build/ in a source tree, firmware/ beside the packaged app."""
    places = []
    if os.environ.get("DTGC_FIRMWARE"):
        places.append(Path(os.environ["DTGC_FIRMWARE"]))
    places.append(Path.cwd() / "build")
    places.append(Path(__file__).resolve().parents[2] / "build")
    if os.environ.get("DTGC_EXE"):
        places.append(Path(os.environ["DTGC_EXE"]).parent / "firmware")
    return places


def find_file(stem):
    for folder in folders():
        path = folder / f"{stem}.fs"
        if path.exists():
            return path
    return None


def available():
    """The known designs that have been built, as (name, path, picture, link, text)."""
    found = []
    for name, stem, picture, link, text in BUILDS:
        path = find_file(stem)
        if path:
            found.append((name, path, picture, link, text))
    return found


def resolve(name):
    """Turns what was typed into (path, build row or None). Raises ValueError with advice when nothing fits."""
    path = Path(name)
    if path.suffix == ".fs":
        if not path.exists():
            raise ValueError(f"{name} does not exist")
        return path, next((row for row in BUILDS if row[1] == path.stem), None)
    for row in BUILDS:
        if name in (row[0], row[1]):
            path = find_file(row[1])
            if not path:
                raise ValueError(f"{row[1]}.fs has not been built. Run: python scripts/build_all.py")
            return path, row
    raise ValueError(f"no design is called {name}. Run this with no name to see the list")


def command(loader, path=None, keep=False):
    """The loader command. With no path it only asks the chip what it is."""
    if path is None:
        return [loader, "-b", BOARD, "--detect"]
    return [loader, "-b", BOARD, *(["-f"] if keep else []), str(path)]


def explain(output):
    """Advice for a failed run, or an empty string when the text is not one of the known failures."""
    lowered = output.lower()
    for text, advice in HELP:
        if text.lower() in lowered:
            return advice
    return ""


def run(arguments, say=print):
    """Runs the loader, passing on each line. Returns (exit code, everything it printed)."""
    say("> " + " ".join(arguments))
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   text=True, errors="replace")
    except OSError as error:
        return 127, f"could not start {arguments[0]}: {error}"
    lines = []
    with process.stdout:
        for line in process.stdout:
            lines.append(line.rstrip())
            say(lines[-1])
    return process.wait(), "\n".join(lines)


def after_loading(row):
    """What to do next, which depends on the design."""
    if row is None:
        return ""
    name, _stem, picture, link, _text = row
    if picture is None:
        return "Next: look at the board and the monitor. docs/first-hardware.md says what this design should show."
    option = "--ft2232h 0" if link == "ft" else "(it finds the serial port on its own)"
    lines = [f"Next: python -m sw.dtgc selftest {option}".rstrip()]
    if picture != "340x340":
        lines.append(f"This design takes a {picture} picture. In the app choose that picture size, or set DTGC_PICTURE={picture} first.")
    return "\n".join(lines)


def show_list(say=print):
    built = available()
    if not built:
        say("No designs are built yet. Run: python scripts/build_all.py")
        return
    say("Designs that are built, in the order to try them on a new board:")
    for name, _path, picture, _link, text in built:
        say(f"  {name:14} {(picture or '-'):9} {text}")
    say("Load one with: python -m sw.dtgc flash NAME")


def main(args, say=print):
    """Returns the exit code. args has name, keep, detect and dry_run."""
    if not args.name and not args.detect:
        show_list(say)
        return 0
    try:
        path, row = (None, None) if args.detect else resolve(args.name)
    except ValueError as error:
        say(f"Error: {error}")
        return 2
    loader = find_loader()
    if not loader:
        say("Error: openFPGALoader was not found. It comes with the OSS CAD Suite (docs/setup.md). Add its bin folder to PATH,")
        say("or set DTGC_LOADER to the full path of openFPGALoader.")
        return 2
    arguments = command(loader, path, args.keep)
    if args.dry_run:
        say(" ".join(arguments))
        return 0
    if args.keep:
        say("Writing to the board's flash chip. This replaces what the board starts with, and has not been tried on a")
        say("real board yet (docs/verify.md). Leave out --keep to load into memory only.")
    code, output = run(arguments, say)
    if code == 0 and "fail" not in output.lower():
        say("The loader finished without an error." if path else "The loader reached the board.")
        advice = after_loading(row)
        if advice:
            say(advice)
        return 0
    say(f"The loader stopped with exit code {code}.")
    say(explain(output) or "Copy the text above into docs/test-log.md, exactly as it is.")
    return code or 1


if __name__ == "__main__":
    sys.exit("Run: python -m sw.dtgc flash")
