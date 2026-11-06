# Benchmarks

**No number here comes from real hardware yet.** Each table says where its numbers come from. Real measurements get added with `python -m sw.dtgc --serial PORT benchmark`.

## Bytes needed per frame (measured on the emulator, 2026-11-01)
From `python -m sw.dtgc benchmark --frames 4`. Bytes are exact, because the same packets go to the hardware. Times only describe this PC, and the emulator is not a model of hardware speed. "Link needed" is bytes x 15.

| Scene | Bytes per frame | Link needed for 15 fps | Bytes without tiles | Make frame (Python) | Send on this link |
|---|---|---|---|---|---|
| static | 9 | 0.000 MB/s | 120,020 | 3.2 ms | 0.7 ms |
| sprite | 414 | 0.006 MB/s | 120,020 | 0.0 ms | 1.7 ms |
| scroll | 6,868 | 0.103 MB/s | 120,020 | 0.1 ms | 34.7 ms |
| fractal | 30,947 | 0.464 MB/s | 120,020 | 121.9 ms | 57.7 ms |
| noise | 120,522 | 1.808 MB/s | 120,020 | 0.1 ms | 166.5 ms |

What it means:
- The 1.73 MB/s estimate holds only when every pixel changes. Noise is slightly worse than sending rows, because each of the 289 tiles carries its own packet overhead.
- The onboard serial link's assumed 0.3 MB/s (3 Mbaud, unmeasured) would carry sprite and scroll scenes at 15 fps, but not the fractal or noise. Those need the FT2232H.
- These scenes change little or compress well. A real game's bytes per frame will differ.

## CPU baseline (this PC, plain Python)
The fractal scene takes about 122 ms to compute one frame in plain Python, or about 8 fps before anything is sent. This is a baseline for that one program, not a comparison with the GPU, which cannot draw fractals. A triangle-drawing baseline comes with Milestone 6.

One spinning cube frame takes about 16.5 ms in plain Python on this PC, measured while other simulations were running, and without the clears. That was about the same as the simulated GPU at 25.2 MHz when it was measured, before the later pixel loop speedups. This PC is much faster than the GPU will ever be, so the GPU's value is learning, HDMI output and taking the work off the PC, not beating a modern computer.

## How fast the GPU can take in a frame (Verilog simulation, 2026-11-01)
From `python scripts/rtl_speed.py`. The link is removed as a limit (one byte every 2 clocks). Includes refresh and scan-out sharing the SDRAM, on the simulation's SDRAM model at 25.2 MHz.

| Full 340 x 340 frame | Clocks | Time | Most frames per second |
|---|---|---|---|
| raw tiles, every pixel | 772,026 | 30.6 ms | 32.6 |
| run-length tiles, flat colour | 417,155 | 16.6 ms | 60.4 |
| CLEAR command | 35,899 | 1.4 ms | 702.0 |

Before memory rows were kept open, these were 1,019,063, 904,497 and 222,144 clocks.

Spinning cube, one frame (colour clear, depth clear, up to 6 triangles, about 18,000 pixels), from `python scripts/sim_spin_pic.py`:

| Memory controller | Clocks | Time | Most frames per second |
|---|---|---|---|
| Opens and closes a row for every word | about 1,160,000 | about 46 ms | about 21 |
| Keeps a row open in each bank | 389,000 to 416,000 | 15.4 to 16.5 ms | 60 to 65 |
| Also one pixel per clock when memory isn't needed, one held word each of colour, depth and texture, and each row ended once the triangle is left | 255,000 to 271,000 | 10.1 to 10.7 ms | 93 to 99 |
| Also 8 depth words read as one burst and held as a 16-pixel tile | 197,000 to 214,000 | 7.8 to 8.5 ms | 118 to 128 |
| Also clearing only the area earlier frames drew on, a word at a time (`clear_scene`) | 118,000 to 135,000 | 4.7 to 5.4 ms | 187 to 213 |

The last row depends on the picture: a scene covering the whole screen clears the whole screen.

So in simulation the write path would not be what limits 15 fps. A swap also waits for the next vertical blank, which this table does not include.

## Where the clocks go in a frame (Verilog simulation, 2026-11-01)
From `python scripts/profile_raster.py --scene cube` and `--scene field`. Whole frame: colour clear, depth clear and triangles. Counts move by about 1% between runs, as refreshes fall at different moments. The time columns divide simulated clocks by the target clock. They ignore the link, the wait for vertical blank and SDRAM pin limits, and they are not hardware measurements.

| Scene | Before, clocks | After, clocks | Before, at 26.52 MHz | After, at 46.41 MHz | Speedup |
|---|---|---|---|---|---|
| Cube, 6 triangles | 205,978 | 88,314 | 7.77 ms | 1.90 ms | 4.1 |
| Field, 1148 triangles | 1,198,190 | 885,213 | 45.2 ms | 19.1 ms | 2.4 |

What changed: fast depth clear (63,238 clocks down to 363), posted colour writes, an 8-pixel jump over empty space, and no maths for flat colours. The full breakdown is in the paper, `docs/paper/paper.html`.

On the onboard serial link, a 1148-triangle frame is 52,808 bytes, about 176 ms at the assumed 0.3 MB/s. So the link would limit that scene to about 5.7 fps however fast the GPU draws.

## 1080p30 frame time (Verilog simulation, 2026-11-02)
A 960x540 picture at 46.41 MHz with scan-out reading memory: `DTGC_PICTURE=960x540 python scripts/profile_raster.py --scene field --video 1080p30`.
GPU only. The time to receive commands is not included.

| Scene | Triangles (clocks) | With clears (clocks) | Time | Rate |
|---|---|---|---|---|
| Cube | 118,942 | 255,780 | 5.51 ms | 181 fps |
| Field | 1,384,598 | 1,521,436 | 32.8 ms | 30.5 fps |

The field's biggest costs are the pixel loop (37.8%), depth reads (27.6%) and depth writes (13.8%). Before reading only the depth words a
triangle can reach it was 1,680,098 clocks, 36.2 ms, 27.6 fps.

Link: the field needs 15,387 bytes per frame with indexed lists against 52,829 with single triangles. Over the serial link, at an assumed
0.3 MB/s, that limits it to about 19.5 fps. So 30 fps needs the FT2232H link. Neither speed has been measured.

## Bytes per frame for the games (measured on the emulator, 2026-11-01)
From `scripts/game_bytes.py`. Bytes are exact, because the same packets go to the hardware. "Link limit" assumes 300,000 bytes per second, which is the unmeasured 3 Mbaud figure, and counts bytes only: the GPU's drawing time and the wait for vertical blank come on top.

| Game | Average bytes per frame | Worst frame | Link limit |
|---|---|---|---|
| Pong | 484 | 523 | 574 fps |
| Maze | 1,567 | 1,567 | 191 fps |
| Dodge | 3,214 | 3,682 | 81 fps |

## Not measured yet
- Real link speed, round-trip delay and frame rate on hardware
- Whether the 1024-byte window limits speed on a real link (`docs/protocol.md`)
