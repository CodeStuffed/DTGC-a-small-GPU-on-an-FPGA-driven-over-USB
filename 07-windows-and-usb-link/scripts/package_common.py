"""What the Windows and Linux packages share: the app's files, the FPGA builds and the icon. Used by scripts/package_*.py."""
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sw.dtgc import flash  # noqa: E402

# Every design the app's "Load onto the board" list knows, so the list in the packaged app is complete.
FIRMWARE = tuple(stem for _name, stem, _picture, _link, _text in flash.BUILDS)


def copy_app(target):
    """The Python package, with nothing the app does not run."""
    ignore = shutil.ignore_patterns("__pycache__", "tests", "d3d9", "device", "launcher")
    shutil.copytree(ROOT / "sw", target / "sw", ignore=ignore)


def copy_firmware(target):
    target.mkdir(parents=True)
    for name in FIRMWARE:
        built = ROOT / "build" / f"{name}.fs"
        if not built.exists():
            raise SystemExit(f"{built} is missing. Run: python scripts/build_all.py")
        shutil.copy(built, target)


def copy_doom(target):
    """The Doom engine program, when scripts/get_doom.py has built one on this PC. Returns True when it was copied.

    Game files (.wad) are left out: each has its own licence, and the owner of this folder puts their own in.
    """
    built = [path for path in (ROOT / "build/doom/dtgc_doom.exe", ROOT / "build/doom/dtgc_doom") if path.exists()]
    if not built:
        return False
    target.mkdir(parents=True)
    shutil.copy(built[0], target)
    (target / "README.txt").write_text(
        "dtgc_doom is the Doom engine (doomgeneric, https://github.com/ozkl/doomgeneric) built with DTGC's own\n"
        "sw/doom/doomgeneric_dtgc.c. Licence: GNU GPL version 2. If you pass this folder on, pass on that source too.\n"
        "Put a game file here, such as doom1.wad or freedoom1.wad, then press Play Doom in the app.\n")
    return True


def make_icon(folder):
    """A small chip, drawn here so the icon needs no art files. Returns the paths of the .ico and the .png."""
    folder.mkdir(parents=True, exist_ok=True)
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), 44, fill=(20, 23, 28, 255))
    for step in range(4):
        spot = 70 + step * 39
        draw.rectangle((spot - 8, 28, spot + 8, size - 28), fill=(57, 197, 160, 255))
        draw.rectangle((28, spot - 8, size - 28, spot + 8), fill=(57, 197, 160, 255))
    draw.rounded_rectangle((54, 54, size - 54, size - 54), 16, fill=(32, 37, 44, 255), outline=(57, 197, 160, 255), width=8)
    draw.polygon([(128, 86), (172, 164), (84, 164)], fill=(232, 234, 237, 255))
    ico, png = folder / "dtgc.ico", folder / "dtgc.png"
    image.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(png)
    return ico, png
