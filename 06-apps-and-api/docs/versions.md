# The three versions

One app runs all three: `python -m sw.dtgc app`. Pick your version, then press a button.

Nothing on the board has been run on hardware yet. Board speeds below are simulation results or estimates, and they say which.

| | This PC only | Board, HDMI out | Board, USB out |
|---|---|---|---|
| What you need | Nothing extra | Tang Nano 20K, HDMI cable, monitor | Tang Nano 20K |
| Who draws | The PC's own graphics card | The FPGA | The FPGA |
| Where the picture goes | A window on the PC, scaled to fit | A monitor | A window on the PC, scaled to fit |
| Command | `python -m sw.dtgc laptop --demo cube` | `python -m sw.dtgc spin` | `python -m sw.dtgc view --demo cube` |
| FPGA design | none | `top_gpu`, `top_gpu_hd`, `top_gpu_1080` | `top_gpu_usb` |
| With the backpack PCB | not used | `top_gpu_ft`, `top_gpu_hd_ft`, `top_gpu_1080_ft` | `top_gpu_usb_ft` |

## This PC only
It uses OpenGL on the graphics card you already have. Add `--exact` to see what the real hardware would draw, pixel for pixel, scaled up.

Measured on this PC (graphics card RTX 5080, window about 1920x1080, `--no-vsync`):

| Demo | Mode | Frames per second |
|---|---|---|
| Cube | sharp | 1065 |
| Field of 196 cubes | sharp | 75.9 |
| Dodge | sharp | 560 |
| Cube | exact | 60.1 |
| Field of 196 cubes | exact | 8.4 |

## Board, HDMI out
The picture is 340x340 inside the FPGA. The output can be 640x480, 720p or 1080p. In the two larger modes a small circuit scales the picture up as it goes out.

| Design | Screen | Picture on screen |
|---|---|---|
| `top_gpu` | 640x480 at 60 Hz | 340x340 |
| `top_gpu_hd` | 1280x720 at 60 Hz | 680x680 |
| `top_gpu_1080` | 1920x1080 at 50 Hz, reduced blanking | 1020x1020 |

True 1080p at 60 Hz is not available on this chip. [hd-limits.md](hd-limits.md) explains why.

## Board, USB out
The FPGA draws, then the PC reads each finished picture back and shows it. There is no scan-out circuit and no HDMI cable.

A full 340x340 picture is 115,600 bytes, plus 8 bytes for each row's DATA packet header. So the link decides the frame rate:

| Link | Speed | Full pictures per second |
|---|---|---|
| Tang Nano's USB serial | 3 Mbaud assumed (VERIFY), about 0.3 MB/s | about 2.6, estimated |
| Backpack FT2232H | about 40 MB/s from the chip's documents (VERIFY); the frame reader is estimated at 17.5 MB/s at 25.2 MHz | about 150, estimated, before drawing time |

Nothing is compressed yet. This is the version where the backpack matters most.

## Why there are no raw 1080p pictures over USB
A 1080p picture at one byte per pixel is about 2 MB, so 60 per second needs about 124 MB/s. USB 2.0 High-Speed cannot reach that, and the board has no USB 3 link. The PC scales the 340x340 picture up instead.
