#!/usr/bin/env python3
"""Usage: python scripts/package_windows.py

Makes build/package/DTGC-windows-x64.zip: a folder that runs on a Windows PC with nothing installed. Inside are dtgc.exe, a
private copy of this PC's Python with only the libraries the app uses, the app, the device tool and the FPGA builds.
Needs Visual Studio's compiler. Downloads nothing. The programs are not code-signed, so Windows may warn before running them.
"""
import compileall
import py_compile
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_common import copy_app, copy_doom, copy_firmware, make_icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build/package"
OUT = BUILD / "DTGC"
VCVARS = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat"
LIBRARIES = ("numpy", "numpy.libs", "serial", "PIL", "pillow.libs")
LICENCES = ("numpy", "pyserial", "pillow")
LEFT_OUT_OF_LIB = {"site-packages", "test", "idlelib", "ensurepip", "turtledemo", "venv", "pydoc_data", "__phello__"}
README = """DTGC for Windows

Double-click dtgc.exe. The window opens straight away. It comes to the front on its own when it finds a board.
Nothing is installed, and you can move this folder anywhere or delete it. Tick "Open when a board is plugged in" and it also
starts minimised when you log in. Clear the box before deleting the folder.

Windows may warn that the program is from an unknown publisher, because it is not code-signed. Choose "More info", then
"Run anyway", only if you got this folder from your own build.

With no board, choose "This PC only": your graphics card draws, and the picture fits any screen.
To try the board versions with no board, press "Pretend board (emulator)" first, then "Test the link".

firmware\\      FPGA builds. In the app, pick one under "FPGA design to load" and press "Load onto the board". Picking a
                design also sets the picture size it draws. docs\\flash.md in the project says which to load, in what order.
                Tick "Keep it on the board after unplugging" to write it to the board's flash chip: the board then starts
                that design by itself at every power-on, on any PC or a plain USB charger.
loader\\        openFPGALoader and its libraries, so this folder loads designs on a PC that has nothing else installed.
device\\        dtgc_device.exe, which lists DTGC in Device Manager while it runs. It is a software device, not a display driver.
doom\\          only there if the Doom engine was built on the PC that made this folder. Put a .wad game file in it.
dtgc-cli.exe    the same program for the command line: dtgc-cli selftest, dtgc-cli check, dtgc-cli flash, dtgc-cli --help

Drivers: each new PC needs them once. Press "Check my setup" with the board plugged in. It lists which driver each USB port
of the board uses, and says if the loader can reach the board. On the first PC tried (2026-11-12) Windows installed none:
port 1 (the app's serial link) needed FTDI's VCP driver, and port 0 (loading designs) needed WinUSB, set with Zadig.
A board that already keeps its design needs no driver to show a picture, only to be drawn on from a PC.
The real board link through the FT2232H also needs FTDI's D2XX driver and the ftd2xx Python package, which are not in this
folder.

Status: on 2026-11-12 one real board loaded the blink and colour bar designs, and ran Doom slowly. The rest is tested
against the emulator only.
Python and its libraries are included with their licences, in runtime\\.
"""


def compile_launcher(icon):
    work = BUILD / "launcher"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(icon, work / "dtgc.ico")
    (work / "dtgc.rc").write_text('1 ICON "dtgc.ico"\n')
    source = ROOT / "sw/launcher/dtgc_launcher.cpp"
    script = work / "build.bat"
    flags = "/nologo /std:c++17 /EHsc /O2 /MT /DUNICODE /D_UNICODE"
    script.write_text(f"""@call "{VCVARS}" x64 >nul
cd /d "{work}"
rc /nologo dtgc.rc || exit /b 1
cl {flags} "{source}" dtgc.res /Fe:dtgc.exe /link /SUBSYSTEM:WINDOWS user32.lib || exit /b 1
cl {flags} /DCONSOLE_VERSION "{source}" dtgc.res /Fe:dtgc-cli.exe /link /SUBSYSTEM:CONSOLE user32.lib || exit /b 1
""")
    subprocess.run(["cmd", "/c", str(script)], check=True, stdout=subprocess.DEVNULL)
    return work / "dtgc.exe", work / "dtgc-cli.exe"


def copy_runtime(target):
    prefix = Path(sys.prefix)
    version = f"{sys.version_info.major}{sys.version_info.minor}"
    target.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe", "python3.dll", f"python{version}.dll", "vcruntime140.dll", "vcruntime140_1.dll",
                 "LICENSE.txt"):
        shutil.copy2(prefix / name, target / name)
    shutil.copytree(prefix / "DLLs", target / "DLLs", ignore=shutil.ignore_patterns("*.pdb", "*_test*", "*.cat", "py*.ico"))
    shutil.copytree(prefix / "tcl", target / "tcl", ignore=shutil.ignore_patterns("demos", "*.lib", "tzdata"))

    def left_out(folder, names):
        top = Path(folder) == prefix / "Lib"
        return [n for n in names if n == "__pycache__" or (top and n in LEFT_OUT_OF_LIB)]
    shutil.copytree(prefix / "Lib", target / "Lib", ignore=left_out)
    for path in (prefix / "Lib/site-packages").iterdir():
        licence = path.name.endswith(".dist-info") and path.name.split("-")[0].lower() in LICENCES
        if path.is_dir() and (path.name in LIBRARIES or licence):
            shutil.copytree(path, target / "Lib/site-packages" / path.name, ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyi"))
    # This file alone decides where this Python looks, so whatever Python the PC may have cannot get mixed in.
    (target / f"python{version}._pth").write_text("Lib\nDLLs\nLib\\site-packages\n..\\app\n")
    compileall.compile_dir(target / "Lib", quiet=2, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH, workers=0)


SUITE = Path(r"C:\tools\oss-cad-suite")  # where docs/setup.md puts the OSS CAD Suite
# The libraries openFPGALoader.exe needs, found by reading its import names (it runs alone with exactly these).
LOADER_DLLS = ("libftdi1", "libgcc_s_seh-1", "libhidapi", "libstdc++-6", "libusb-1.0", "libwinpthread-1", "zlib1")
LOADER_NOTE = """openFPGALoader (https://github.com/trabucayre/openFPGALoader, Apache License 2.0) and the libraries it needs,
copied from the OSS CAD Suite: libftdi1 and libusb-1.0 (LGPL 2.1), hidapi, zlib, and the MinGW runtime (libgcc, libstdc++,
winpthreads). Their sources are at the projects' own sites. DTGC's app uses this copy when it runs from this folder.
"""


def copy_loader(target):
    """openFPGALoader and its libraries, so the folder can load designs on a PC without the OSS CAD Suite. False if absent."""
    exe = SUITE / "bin/openFPGALoader.exe"
    if not exe.exists():
        return False
    target.mkdir()
    shutil.copy2(exe, target / "openFPGALoader.exe")
    for name in LOADER_DLLS:
        shutil.copy2(SUITE / "lib" / f"{name}.dll", target)
    (target / "LICENCES.txt").write_text(LOADER_NOTE, newline="\r\n")
    return True


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    icon, _ = make_icon(BUILD)
    for program in compile_launcher(icon):
        shutil.copy(program, OUT / program.name)
    copy_runtime(OUT / "runtime")
    copy_app(OUT / "app")
    shutil.copy(icon, OUT / "app/sw/dtgc/dtgc.ico")
    compileall.compile_dir(OUT / "app", quiet=2, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH, workers=0)
    copy_firmware(OUT / "firmware")
    (OUT / "device").mkdir()
    shutil.copy(ROOT / "build/device/dtgc_device.exe", OUT / "device")
    copy_doom(OUT / "doom")
    if not copy_loader(OUT / "loader"):
        print("openFPGALoader not found in the OSS CAD Suite: the folder cannot load designs on its own.")
    (OUT / "README.txt").write_text(README, newline="\r\n")
    archive = BUILD / "DTGC-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as folder:
        for path in sorted(OUT.rglob("*")):
            if path.is_file():
                folder.write(path, Path("DTGC") / path.relative_to(OUT))
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"{archive}: {archive.stat().st_size / 1e6:.0f} MB, {size / 1e6:.0f} MB unpacked")


if __name__ == "__main__":
    main()
