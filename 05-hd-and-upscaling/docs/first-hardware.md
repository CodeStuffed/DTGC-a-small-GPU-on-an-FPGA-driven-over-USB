# First hardware test: the day the Tang Nano 20K arrives

Nothing in this project has run on a real board yet. This is the moment we find out how much of it is right. A failure here is normal and useful, so don't worry if a step doesn't match.

Do the steps in order and stop at the first one that gives a different result. Then tell me the step number and exactly what you saw: the full error text, or a photo of the screen or board.

## What you need

- Tang Nano 20K
- USB-C data cable (some cables only charge, so if the PC sees nothing, try another)
- HDMI cable and a monitor or TV with an HDMI input
- This PC, with the project in `C:\Users\User\Documents\tinygpu`

Open a terminal in the project folder and run this once in each new terminal:

```bash
export PATH="/c/tools/oss-cad-suite/bin:/c/tools/oss-cad-suite/lib:$PATH"
```

## A. Look at the board, before plugging in

1. Read the version number printed on the bottom of the board, which looks like `3921` or `3923`. Tell me the number, because it decides which schematic applies.
   **Expected:** a clear version number.
2. Check the board for bent pins or damage, and whether the pin headers are already soldered on.
   **Expected:** no damage. Tell me whether the pins are soldered and which way they point.

## B. Milestone 1: blink

3. Build all the designs from the current code. This takes a few minutes:
   ```bash
   python scripts/build_all.py
   ```
   **Expected:** the last line starts with `All built:`.
4. Plug the board into the PC, then ask the loader to find it:
   ```bash
   openFPGALoader --detect
   ```
   **Expected:** it prints a chip name containing `GW2A`. If it can't find a device, send me the exact text. Don't install any driver tool yet.
5. Load the blink design into the FPGA's temporary memory:
   ```bash
   openFPGALoader -b tangnano20k build/blink.fs
   ```
   **Expected:** the loader finishes with no error, and the 6 LEDs count in binary. One LED changes every half second, so it blinks once per second, and the others change more slowly.

**Report:** the version number, the `--detect` output, and whether the LEDs counted.

## C. Milestone 2: picture on a monitor

6. Connect HDMI from the board to the monitor, and switch the monitor to that input. Then load the colour bars:
   ```bash
   openFPGALoader -b tangnano20k build/top_colorbars.fs
   ```
   **Expected:** 8 vertical colour bars at 640x480, steady, with no flicker or sparkling dots.

**Report:** a photo of the screen. If there's no picture, say what the monitor shows, such as "no signal".

## D. Milestone 3: memory

7. Load the framebuffer test:
   ```bash
   openFPGALoader -b tangnano20k build/top_framebuffer.fs
   ```
   **Expected:** a moving diagonal pattern in a 340x340 square in the middle of the screen. Of the three LEDs this design uses, one stays on (first picture drawn), one stays off (ran out of pixels), and one flickers (each new frame). Tell me which LED does which, since I don't know their order on the board.
8. Watch it for one full minute.
   **Expected:** no corrupted lines or blocks appear, and the off LED stays off. If it comes on, the screen ran out of pixels at some point.

**Report:** a short phone video if you can, and the state of all three LEDs after one minute.

## E. Milestone 4: talking to the PC

9. Load the GPU:
   ```bash
   openFPGALoader -b tangnano20k build/top_gpu.fs
   ```
   **Expected:** the loader finishes. The screen may show random colours, because memory has not been cleared yet.
10. List the serial ports:
    ```bash
    python -m serial.tools.list_ports -v
    ```
    **Expected:** at least one port for the board. Send me this list. It may show two ports, so the next step might need trying each.
11. Run the self-test, putting your port name in place of `COM5`:
    ```bash
    python -m sw.dtgc --serial COM5 selftest
    ```
    **Expected:** 8 lines, each starting with `PASS`, and the "reply sent" LED turns on. If any line says `FAIL`, send the full output. 3 Mbaud is my untested assumption, so a failure here may only mean the speed needs lowering.
12. Draw colour bars:
    ```bash
    python -m sw.dtgc --serial COM5 bars
    ```
    **Expected:** colour bars in the 340x340 square, with the two warning LEDs off (ran out of pixels, and receive error).

**Report:** the self-test output.

## F. Milestones 5 and 6: real speed and 3D

13. Measure the link:
    ```bash
    python -m sw.dtgc --serial COM5 benchmark
    ```
    **Expected:** it finishes with no link error. Send me the whole table, because these become the first real numbers in the project.
14. Run the spinning cube:
    ```bash
    python -m sw.dtgc --serial COM5 spin
    ```
    **Expected:** a spinning, shaded cube, and a frames-per-second figure at the end. Send me that figure. I can't predict it from here, since the serial link is probably what limits it.
15. Play a game:
    ```bash
    python -m sw.dtgc --serial COM5 play pong
    ```
    **Expected:** Pong on the monitor, controlled from a small window on the PC. Tell me whether it's playable and whether it's fun.

## G. HD output: try the modes in order
Colour bars first, because they use no memory and no link, so a failure can only be the video output or the monitor. Stop at the first step that fails and tell me what the monitor says. A mode the monitor refuses does no harm: the design disappears when you unplug.

16. Load 720p bars:
    ```bash
    openFPGALoader -b tangnano20k build/bars_720p.fs
    ```
    **Expected:** 8 steady colour bars. The monitor's info menu says 1280x720 at 60 Hz.
17. Load 1080p at 30 Hz bars:
    ```bash
    openFPGALoader -b tangnano20k build/bars_1080p30.fs
    ```
    **Expected:** 8 steady colour bars. The monitor says 1920x1080 at 30 Hz. Some monitors refuse this mode and show "no signal" or "out of range". Tell me if so, and carry on.
18. Load 1080p at 50 Hz bars:
    ```bash
    openFPGALoader -b tangnano20k build/bars_1080p50.fs
    ```
    **Expected:** 8 steady colour bars with no sparkling dots. The monitor says 1920x1080 at about 50 Hz. Sparkling dots or "no signal" mean the chip or the monitor can't take this mode. Skip step 21 if so.
19. Load the GPU at 720p:
    ```bash
    openFPGALoader -b tangnano20k build/top_gpu_hd.fs
    ```
    **Expected:** black or random pixels in a centred square, with black bars on both sides. The random pixels are just memory that hasn't been cleared yet.
20. Run the cube:
    ```bash
    python -m sw.dtgc --serial COM5 spin
    ```
    **Expected:** a spinning cube in a 680x680 square, smooth edges from the scaler, with led[1] and led[2] off. Send me the frames-per-second figure.

    **If the cube is garbled or has speckles:** the memory may not keep up with the fast 46.41 MHz clock. Repeat step 19 with `build/top_gpu_hd_safe.fs`, which is slower, and tell me if that fixes it. If the cube is still wrong in shape or colour, try `build/top_gpu_hd_nodsp.fs`, which avoids the chip's hard multipliers, and tell me which build was right.
21. Repeat steps 19 and 20 with `build/top_gpu_1080.fs`.
    **Expected:** the same cube in a 1020x1020 square on a 1080p screen. Send me the figure.
22. Try USB output, with the HDMI cable unplugged:
    ```bash
    openFPGALoader -b tangnano20k build/top_gpu_usb.fs
    python -m sw.dtgc --serial COM5 view --demo cube
    ```
    **Expected:** a window on the PC showing the cube, updating about 2 or 3 times a second over this slow link. Send me the figure.

## H. 1080p30 with the GPU
Only after the 1080p at 30 Hz bars in section G are steady.

1. Load the build:
   ```bash
   openFPGALoader -b tangnano20k build/top_gpu_1080p30.fs
   ```
   **Expected:** the monitor's info menu says 1920x1080 at 30 Hz, with the picture in memory showing, which may be random colours until the next step.
2. In the app, choose "DTGC board, HDMI out" and "960 x 540, for the 1080p30 board build", then press Test the link.
   **Expected:** every line says PASS.
3. Press Colour bars.
   **Expected:** steady bars with clean edges filling the screen.
4. Press Cube field. The app's bottom panel prints the frame rate when the demo ends, after 150 frames.
   **Expected:** the cubes draw with nothing flickering. Tell me the frame rate you see. Over the Tang's own USB port expect about 19 frames per second at best, since 30 needs the FT2232H link.

If the picture sparkles or shows wrong colours, tell me which step and what it looks like. That points to SDRAM timing at this speed.

## If something goes wrong

- **Unplug the USB cable** if anything gets hot or smells. That's the only step here with any real urgency.
- A design loaded this way disappears at power-off, so unplugging always brings back whatever was stored on the board.
- I've avoided writing to the board's permanent flash memory here, since nothing needs it yet.

After these pass, the next hardware test is the FT2232H breakout in `docs/ft2232h-test.md`, but only if you want the faster link. Don't order the PCB before that passes.
