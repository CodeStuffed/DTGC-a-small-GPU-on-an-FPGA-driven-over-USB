# Loading a design onto the board, and drivers

**Status:** written and tested with no board. The flasher was run against a stand-in for the loader, and against the real loader with nothing plugged in. Nobody has loaded a DTGC design onto a real Tang Nano 20K yet, so every "Expected" below is what the documents say should happen.

## The short version

A **bitstream** is the file that tells the FPGA what circuit to be. Ours end in `.fs` and sit in `build/`. **openFPGALoader** is the free program that sends one to the board. It comes with the OSS CAD Suite from `docs/setup.md`, so there is nothing new to install.

The flasher is a thin wrapper around it. It knows the board's name and the file names, and it explains the common failures in plain words.

```bash
python -m sw.dtgc check
```

```bash
python -m sw.dtgc flash
```

```bash
python -m sw.dtgc flash blink
```

The first says what is ready on this PC. The second lists the designs. The third loads one. In the app, the same things are the "Check my setup" button and the "FPGA design to load" list with its "Load onto the board" button.

## Do I need drivers?

A **driver** is the piece of Windows that speaks to a USB device. The board has one USB plug, and behind it a small chip (a BL616) that shows Windows two ports: a programming port for the loader and a serial port for the app.

| What you want to do | Driver needed | How sure |
|---|---|---|
| Use the app with the board (serial link) | Windows should set up a serial port by itself. If no new COM port appears, Sipeed's wiki says to install FTDI's driver | VERIFY on the real board |
| Load a design with openFPGALoader | Probably a change on the programming port only, described below | VERIFY. openFPGALoader's own pages do not say. A university guide for the same loader on Windows says the swap is needed |
| The xDTGC backpack's fast link (FT2232H) | FTDI's D2XX driver and the `ftd2xx` Python package | VERIFY. Not needed until the backpack exists |
| Seeing DTGC named in Device Manager | Nothing to install, see `docs/windows-device.md` | Untested |

So the plain answer: **for the app, probably no. For loading designs, probably one small change, and only if the loader cannot open the board.** Do not change anything before step 4 below has failed. `python -m sw.dtgc check` reads the driver names from Windows and tells you which case you are in.

### If the loader cannot open the board

openFPGALoader talks to the programming port through a library that needs a plain USB driver (WinUSB) on that port. Windows may give the port FTDI's driver instead, and then the loader prints `unable to open ftdi device` even though Device Manager shows the board.

The usual fix is a free program called Zadig, which swaps the driver for one port. It is not on `docs/shopping-list.md` or in `docs/setup.md`, because we do not know yet that it is needed. It changes a system driver, so it is your step, and I will not ask for it until `check` shows the problem. If it comes to that:

1. Run `python -m sw.dtgc check` and copy what it prints under "USB devices" into `docs/test-log.md`.
2. Tell me. I will confirm from those lines which port is the programming port before anything is changed.
3. In Zadig, the change goes on **interface 0 only**. Interface 1 is the serial port the app uses. Changing that one would take the COM port away.
4. Run `python -m sw.dtgc flash --detect` again.

The change can be undone in Device Manager: right-click the device, "Uninstall device", tick the box to remove the driver, then replug the board.

## First time with a real board

Do these in order and stop at the first step that does not match. Send me the step number and the exact text.

1. Plug nothing in yet. Run:
   ```bash
   python -m sw.dtgc check
   ```
   **Expected:** `ok` beside pyserial and numpy, `ok` beside openFPGALoader, `Designs built: 28 of 28`, and "No board is plugged in".
2. Plug the board into the PC with a USB-C data cable, straight into the PC with no hub. Wait ten seconds.
   **Expected:** Windows plays its "device connected" sound.
3. Run the check again:
   ```bash
   python -m sw.dtgc check
   ```
   **Expected:** a new line under "Serial ports" with a USB id, and two or three lines under "USB devices" with driver names. Copy this whole output into `docs/test-log.md`, whatever it says. It settles three open items in `docs/verify.md`.
4. Ask the FPGA to say what it is:
   ```bash
   python -m sw.dtgc flash --detect
   ```
   **Expected:** a chip name containing `GW2A`. If it says `unable to open ftdi device`, go to "If the loader cannot open the board" above.
5. Load the first design:
   ```bash
   python -m sw.dtgc flash blink
   ```
   **Expected:** the loader's progress line reaches 100%, the flasher says "The loader finished without an error", and the 6 LEDs count in binary.
6. Carry on with `docs/first-hardware.md` from step 6. Wherever it says `openFPGALoader -b tangnano20k build/NAME.fs`, `python -m sw.dtgc flash NAME` does the same thing.

## The designs

`python -m sw.dtgc flash` prints this list with only the ones that are built. They are in the order to try them on a new board.

| Name | Picture the PC sends | What it is |
|---|---|---|
| `blink` | none | LEDs count in binary |
| `colorbars` | none | 8 colour bars at 640x480 |
| `framebuffer` | none | a test picture from the memory |
| `gpu` | 340x340 | the GPU at 640x480 |
| `gpu_usb` | 340x340 | the picture goes back to the PC |
| `bars_720p`, `bars_1080p30`, `bars_1080p50` | none | colour bars at the higher resolutions |
| `hd`, `hd_safe` | 340x340 | the GPU at 1280x720 |
| `1080p30` | 960x540 | 1920x1080 at 30 Hz, scaled 2x |
| `1080p30x3` to `1080p30x7` | 640x360, 480x270, 384x216, 320x180, 274x154 | the same, scaled 3x to 7x |
| the same names ending in `dd` | same as above | with the dither pattern smoothed out |
| `1080p50` | 340x340 | 1920x1080 at 50 Hz, scaled 3x |
| names ending in `_ft` | as the plain one | for the xDTGC backpack |

The PC has to send the picture size the design draws. From the command line that is the `DTGC_PICTURE` setting, which the flasher prints after loading. In the app, picking a design sets it for you.

## Keeping a design after power-off

```bash
python -m sw.dtgc flash blink --keep
```

Without `--keep` the design lives in the FPGA's own memory and is gone when the power goes off, which makes it safe to try things. `--keep` writes the board's flash chip. That has not been tried on a real board (`docs/verify.md`), so use it only after the plain load has worked, and with `blink` first.

## Where things are

- `sw/dtgc/flash.py`: the flasher. Tests in `sw/tests/test_flash.py` use a stand-in loader.
- `sw/dtgc/check.py`: the setup check. It only reads; it changes nothing.
- The loader is found on the `PATH`, then at `C:\tools\oss-cad-suite\bin`. Set `DTGC_LOADER` to point at another copy.

## Sources for the driver section

- openFPGALoader documentation: https://trabucayre.github.io/openFPGALoader/ (board `tangnano20k`; nothing on Windows drivers)
- Sipeed Tang Nano 20K wiki: https://wiki.sipeed.com/hardware/en/tang/tang-nano-20k/nano-20k.html (BL616 debugger with JTAG and UART)
- MIT 6.205 openFPGALoader guide, Windows section: https://fpga.mit.edu/6205/F25/documentation/openFPGA (Zadig, WinUSB)
- openFPGALoader issue 454, `ftdi_usb_reset failed` on this board: https://github.com/trabucayre/openFPGALoader/issues/454
