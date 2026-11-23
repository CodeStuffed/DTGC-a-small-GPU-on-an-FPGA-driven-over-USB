# Doom on DTGC

**Status:** our side of the link is written and tested against a stand-in for the engine, in the emulator. The real Doom engine has not been fetched, built or run on this project's PC, and nothing has run on a real board. The first real run is yours, with the checklist below.

## How it works

The board does not run Doom's code. The real open-source Doom engine runs on the PC as its own program and works out each frame. The board is the screen.

```
Doom engine (dtgc_doom.exe)  --frames-->  python -m sw.dtgc doom  --DTGC commands-->  board  -->  HDMI monitor
                             <--keys----  (a small window that takes the keyboard)
```

- The engine is **doomgeneric**, a version of Doom's source made to be moved to new screens. To move it you write one small file with six functions. Ours is `sw/doom/doomgeneric_dtgc.c`.
- Doom draws 320x200 pixels with one byte each. Each byte is a number into a table of 256 colours. DTGC stores its picture the same way, so nothing is converted: the colour table goes to the board with `PALETTE`, and the pixels go as they are.
- Only the squares of the picture that changed are sent (`sw/dtgc/stream.py`).
- The game file is a **WAD**: the levels, pictures and sounds. The engine has none of its own. Freedoom is a free one. The shareware `doom1.wad` and the files from a bought copy of Doom work too.
- There is no sound.

## Set it up, once

You run this, not me, because it fetches other people's code from the internet. It prints what it will fetch and waits for you to type `y`.

```bash
python scripts/get_doom.py --freedoom
```

It does three things:

1. Fetches doomgeneric's source with git into `build/doom/doomgeneric`. From https://github.com/ozkl/doomgeneric, licence GNU GPL version 2.
2. Compiles it with our file into `build/doom/dtgc_doom.exe`. This needs Visual Studio's C++ tools, which this PC has.
3. With `--freedoom`: downloads Freedoom 0.13.0 (24,143,781 bytes) from the Freedoom project's releases on GitHub and puts `freedoom1.wad` and `freedoom2.wad` in `build/doom`. Leave the option off if you have a WAD of your own, and copy that into `build/doom` instead.

## Play

With no board, to see it work in a window on the PC:

```bash
python -m sw.dtgc doom --window
```

On the board, load the 5x design first. Its 384x216 picture holds Doom's 320x200 frame with a thin border.

```bash
python -m sw.dtgc flash 1080p30x5
```

Then, in PowerShell:

```powershell
$env:DTGC_PICTURE = "384x216"; python -m sw.dtgc doom
```

In the app it is two clicks: pick `1080p30x5` under "FPGA design to load" and press "Load onto the board", then press "Play Doom".

### Keys

Keep the small DTGC window selected while you play. It takes the keyboard.

| Key | Does |
|---|---|
| Arrows | move and turn |
| Ctrl | fire |
| Space | open doors, press switches |
| Shift | run |
| Alt, or `,` and `.` | step sideways |
| Esc | menu |
| Enter | choose in the menu |
| Tab | map |
| `-` and `=` | make the view smaller or larger |
| F1 to F12 | Doom's own function keys (F5 is low detail) |
| letters and numbers | pass straight through (numbers pick weapons, `y` answers yes) |

## How fast it will be

The game itself always runs at full speed on the PC. What the link limits is how many of its frames reach the screen: the newest frame is sent, and frames that arrive while it is going out are skipped.

Bytes per frame, measured in the emulator with test pictures the size of a Doom frame. The bytes are exact, because the same packets would go to the board. The frames per second are only a division by an assumed link speed.

| Picture on the board | Every pixel new (worst case) | Whole view scrolling | Only the status bar changes | Nothing changes |
|---|---|---|---|---|
| 384x216 (5x build) | about 76,000 | about 51,000 | about 19,000 | 9 |
| 340x340 | about 79,000 | about 51,000 | about 20,000 | 9 |
| 274x154 (7x build, frame shrunk to 246x154) | about 41,000 | about 37,500 | about 9,000 | 9 |

- **Onboard serial link:** the project assumes 300,000 bytes per second (3 Mbaud), which is not measured (`docs/verify.md`). At that speed a moving view on the 5x build is about 4 to 6 frames per second. That is enough to see it is Doom, and slow to play.
- **To get more frames on the serial link:** press `-` a few times to shrink the view, since the border around it stops changing and stops being sent. Or use the 7x build, which sends about half the bytes for a coarser picture.
- **xDTGC backpack (FT2232H):** should carry far more, but its real speed is not measured either. Until it is, no frame rate is claimed for it.

The board's own drawing time is not the limit here. Copying squares of pixels is the cheapest thing the GPU does.

## First real run: checklist

Stop at the first step that does not match and send me the step number and the exact text.

1. Run `python scripts/get_doom.py --freedoom` and type `y`.
   **Expected:** it ends with `Built ...dtgc_doom.exe`, then `Game files in build/doom: freedoom1.wad, freedoom2.wad`, then `Play with: python -m sw.dtgc doom`.
   If the compiler stops, the script says so and prints the compiler's last lines. That is the most likely place for a first failure, because our file has only been compiled against a stand-in for the engine. Copy the lines into `docs/test-log.md`.
2. Run `python -m sw.dtgc doom --window`.
   **Expected:** a window with Doom's title screen within a few seconds, then the demo playing.
3. Press Enter, pick a new game, and walk with the arrow keys.
   **Expected:** the view moves. Ctrl fires.
4. Close the window.
   **Expected:** the terminal prints how many frames were shown and how many bytes each took on average. Send me that line.
5. Only after the board has passed `docs/first-hardware.md` up to the 1080p30 section: load `1080p30x5` and play on the board as shown above.
   **Expected:** the same picture on the monitor, at a few frames per second on the serial link.

## What was tested, and how

- `sw/tests/test_doom.py`, 19 tests, all pass. A stand-in engine (`sw/tests/doom_standin`, a moving test pattern, not Doom) is compiled with the real `doomgeneric_dtgc.c` and run. The tests check that its frames and its colour table reach the emulator's picture unchanged, that each key arrives at the engine as the engine's own key number, that the fallback build without the one-byte-per-pixel option works, and that the engine stops when the window goes.
- The stand-in's headers were written from doomgeneric's real ones, read on GitHub on 2026-11-11. If the real engine has changed since, step 1 above shows it.
- Not tested: the real engine, a real WAD, a real board, the Linux build.

## Licences

- doomgeneric and the Doom engine: GNU GPL version 2. `sw/doom/doomgeneric_dtgc.c` is compiled into the same program, so the program you build is under the GPL too. That matters only if you pass the built program on to someone else: pass on the source with it.
- Freedoom: its own short licence, which allows copying with the licence text kept. The script copies that text into `build/doom` beside the WADs.
- The WADs from the original Doom are not free to share. Use your own copy.
