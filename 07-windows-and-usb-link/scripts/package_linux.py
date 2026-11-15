#!/usr/bin/env python3
"""Usage: python scripts/package_linux.py

Makes build/package/dtgc-linux.tar.gz: the app as one .pyz file, a launcher, a desktop entry, USB rules and an install script.
Runs on any PC, as nothing is compiled. The result needs Python 3 with tkinter, numpy, pyserial and Pillow on the Linux PC.
Not yet run on Linux, as this project has no Linux machine.
"""
import io
import shutil
import sys
import tarfile
import zipapp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_common import copy_app, copy_firmware, make_icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build/package"
NAME = "dtgc-linux"

LAUNCHER = """#!/bin/sh
# Starts DTGC. With no arguments it opens the app. "--watch" opens it minimised until a board is plugged in.
here="$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)"
python3 -c "import tkinter, numpy, serial, PIL" 2>/dev/null || {
    echo "DTGC needs Python 3 with tkinter, numpy, pyserial and Pillow. On Debian or Ubuntu:"
    echo "    sudo apt install python3-tk python3-numpy python3-serial python3-pil"
    exit 1
}
export PYTHONPATH="$here/dtgc.pyz${PYTHONPATH:+:$PYTHONPATH}"
export DTGC_EXE="$here/dtgc"
case "$1" in
    "") exec python3 -m sw.dtgc app ;;
    --watch) exec python3 -m sw.dtgc app --watch ;;
    *) exec python3 -m sw.dtgc "$@" ;;
esac
"""

INSTALL = """#!/bin/sh
# Copies DTGC to your home folder and adds it to the applications menu. Needs no administrator rights.
# The USB rules are a separate step that does need them, shown at the end.
set -e
here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
target="$HOME/.local/share/dtgc"
mkdir -p "$target" "$HOME/.local/share/applications" "$HOME/.local/bin"
cp -r "$here/dtgc" "$here/dtgc.pyz" "$here/dtgc.png" "$here/firmware" "$here/README.txt" "$target/"
sed "s|@HOME@|$target|g" "$here/dtgc.desktop" > "$HOME/.local/share/applications/dtgc.desktop"
ln -sf "$target/dtgc" "$HOME/.local/bin/dtgc"
echo "Installed. Find DTGC in your applications menu, or run: dtgc"
echo "To use a board without sudo, add the USB rules once:"
echo "    sudo cp '$here/60-dtgc.rules' /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger"
echo "and for the serial link: sudo usermod -aG dialout \\$USER, then log out and back in."
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=DTGC
Comment=Run the DTGC graphics board, or its demos on this PC
Exec=@HOME@/dtgc
Icon=@HOME@/dtgc.png
Terminal=false
Categories=Development;Electronics;
"""

# 0403:6010 is FTDI's default id for the FT2232H (docs/verify.md). The Tang's own USB id is not known yet.
RULES = """# Lets a logged-in user reach the FT2232H on the xDTGC board without sudo.
SUBSYSTEM=="usb", ATTR{idVendor}=="0403", ATTR{idProduct}=="6010", TAG+="uaccess", MODE="0660"
"""

BUILD_BINARY = """#!/bin/sh
# Optional, for a single program with no Python needed on the target PC. Run on Linux. Downloads PyInstaller.
# Not yet tried: this project has no Linux machine.
set -e
here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python3 -m venv "$here/.binary-env"
"$here/.binary-env/bin/pip" install pyinstaller numpy pyserial pillow
cd "$here"
mkdir -p src && (cd src && python3 -m zipfile -e ../dtgc.pyz .)
printf 'import sys\\nfrom sw.dtgc import __main__ as m\\nif len(sys.argv) == 1:\\n    sys.argv.append("app")\\nm.main()\\n' > src/start.py
"$here/.binary-env/bin/pyinstaller" --onefile --name dtgc --paths src src/start.py
echo "Built: dist/dtgc"
"""

README = """DTGC for Linux

Run ./dtgc for the app, or ./install.sh to add it to your applications menu. It needs Python 3 with tkinter, numpy, pyserial
and Pillow, and tells you the command if any are missing.

The window comes to the front on its own when it finds a board. Ticking "Open when a board is plugged in" adds an entry to
~/.config/autostart, which starts it minimised at login. Clearing the box removes the entry.

The OpenGL window is Windows only, so demos on Linux are drawn on the CPU and shown in a plain, slower window.
build-binary.sh makes one program with Python inside. Run it on Linux. It downloads PyInstaller.

firmware/ holds the FPGA builds. top_gpu_1080p30.fs is a 960x540 picture scaled up to 1920x1080 at 30 Hz: choose 960 x 540 in
the app for it. The real board link through the FT2232H also needs FTDI's D2XX library and the ftd2xx Python package.

Status: NOT yet run on Linux, as this project has no Linux machine. The contents were checked on Windows, and the app was run
from the .pyz file there against the emulator. None of this has run on real hardware yet.
"""


def add_text(archive, name, text, mode):
    data = text.encode()
    info = tarfile.TarInfo(f"{NAME}/{name}")
    info.size = len(data)
    info.mode = mode
    archive.addfile(info, io.BytesIO(data))


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    work = BUILD / "linux"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    copy_app(work / "app")
    zipapp.create_archive(work / "app", work / "dtgc.pyz", interpreter="/usr/bin/env python3", main="sw.dtgc.__main__:main")
    copy_firmware(work / "firmware")
    _, icon = make_icon(BUILD)
    archive_path = BUILD / f"{NAME}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, text, mode in (("dtgc", LAUNCHER, 0o755), ("install.sh", INSTALL, 0o755), ("build-binary.sh", BUILD_BINARY, 0o755),
                                 ("dtgc.desktop", DESKTOP, 0o644), ("60-dtgc.rules", RULES, 0o644), ("README.txt", README, 0o644)):
            add_text(archive, name, text, mode)
        archive.add(work / "dtgc.pyz", f"{NAME}/dtgc.pyz")
        archive.add(icon, f"{NAME}/dtgc.png")
        archive.add(work / "firmware", f"{NAME}/firmware")
    print(f"{archive_path}: {archive_path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
