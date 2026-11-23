# The DTGC app for Windows and Linux

These are user-space programs. **Neither package is a kernel or display driver.** Windows will not list DTGC as a display adapter from
this app. A real display driver needs code signing and your explicit approval (`docs/windows-device.md`, Milestone 10e).

## Windows: `build/package/DTGC-windows-x64.zip`

Unzip anywhere and double-click `dtgc.exe`. Nothing else needs installing. About 49 MB zipped, 270 MB unpacked. It carries its own openFPGALoader, so it can live on a USB stick and load designs on any Windows PC.

| Item | What it is |
|---|---|
| `dtgc.exe` | Opens the window |
| `dtgc-cli.exe` | The same app in a terminal: `dtgc-cli.exe --help` |
| `runtime/` | A private Python with tkinter, numpy, pyserial and Pillow |
| `app/` | The DTGC program |
| `device/` | The device tool (`docs/windows-device.md`) |
| `firmware/` | The FPGA builds |

The programs are not code-signed, so Windows SmartScreen may warn the first time. Choose "More info", then "Run anyway".

Rebuild it with `python scripts/package_windows.py`. That needs Visual Studio's compiler and downloads nothing.

## Linux: `build/package/dtgc-linux.tar.gz`

```bash
tar -xzf dtgc-linux.tar.gz
cd dtgc-linux
./dtgc
```

`./install.sh` adds it to the applications menu and prints the one `sudo` command for the USB rules, which you run yourself. `build-binary.sh` makes one program with Python inside
(run it on Linux; it downloads PyInstaller). The app needs Python 3 with tkinter, numpy, pyserial and Pillow. **It has not been run on Linux,
since this project has no Linux machine.**

## The pop-up

The window opens on launch. With "Open when a board is plugged in" ticked, the app starts minimised at login and comes to the front
when it finds a board. The board's USB id stays VERIFY: 0403:6010 is the FT2232H's default, from its datasheet, and the Tang's own id
has not been read from a real board.

## How it was tested

Windows, from a clean folder with a bare environment (only `C:\Windows\System32` on the path, no Python):
- `dtgc-cli.exe --help`, `emulator`, `selftest` (all PASS against the emulator), `benchmark`.
- `import numpy, tkinter, serial, PIL` inside the private runtime.
- `dtgc.exe` opened its window, which was captured and closed.

The board watcher has its own tests in `sw/tests/test_board_watcher.py`, using a stand-in for USB.

Linux, on Windows only:
- `bash -n` on each script, and the contents of the archive.
- `dtgc.pyz`: emulator and selftest PASS under Windows Python.

Nothing has been tried with a real board.

## Loading designs, the setup check and Doom (2026-11-12)

The window has three new things, and the Windows package now carries all 28 FPGA builds (about 49 MB zipped, 270 MB unpacked).

| In the window | What it runs | Notes |
|---|---|---|
| "FPGA design to load" and "Load onto the board" | `dtgc-cli flash NAME` | Needs openFPGALoader from the OSS CAD Suite, which is not in the package. Picking a design also sets the picture size it draws. Guide: [flash.md](flash.md) |
| "Check my setup" | `dtgc-cli check` | Lists Python packages, the loader, serial ports, and the Windows driver on each USB port of the board. It changes nothing |
| "Play Doom" | `dtgc-cli doom` | Needs the engine built once with `python scripts/get_doom.py`. Guide: [doom.md](doom.md) |

The picture list now has all seven sizes, from 340 x 340 to 960 x 540. When the watcher finds a board, Windows also shows a notification, so you see it even with the window minimised.

Tested: `sw/tests/test_app_buttons.py` and `sw/tests/test_flash.py`. From the unpacked package, with no board: `dtgc-cli flash` listed 28 designs, `dtgc-cli flash 1080p30x5 --dry-run` printed the loader command with the package's own file, `dtgc-cli check` reported "no board", and `dtgc-cli doom --window` said the engine is not built yet. The notification command exits without an error on this PC; the note on screen was not checked by eye.
