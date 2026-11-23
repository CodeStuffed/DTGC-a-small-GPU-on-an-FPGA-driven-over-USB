# FPGA resource use and timing

One row per build. Numbers come from the nextpnr log for GW2AR-LV18QN88C8/I7. "Fmax" is what the tool estimates, not a hardware measurement.

| Date | Design | LUT4 | DFF | ALU | BSRAM | DSP | Pixel clock Fmax | Target |
|---|---|---|---|---|---|---|---|---|
| 2026-11-01 | `top_framebuffer` | 977 / 20736 | 403 / 15552 | 362 / 15552 | 2 / 46 | 0 | 65.53 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu` | 1953 / 20736 | 944 / 15552 | 812 / 15552 | 4 / 46 | 0 | 39.73 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu` with triangles, seed 1 | 7495 / 20736 | 3370 / 15552 | 2620 / 15552 | 4 / 46 | 0 | 40.05 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu` with triangles and dither, seed 1 | 7476 / 20736 | 3371 / 15552 | 2644 / 15552 | 4 / 46 | 0 | 40.29 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu` with open SDRAM rows, seed 1 | 7638 / 20736 | 3430 / 15552 | 2660 / 15552 | 4 / 46 | 0 | 36.71 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu` with one pixel per clock and held words, seed 1 | 8079 / 20736 | 3630 / 15552 | 2652 / 15552 | 4 / 46 | 0 | 39.40 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu` with burst depth tile, seed 1 | 9353 / 20736 | 3875 / 15552 | 2706 / 15552 | 4 / 46 | 0 | 39.75 MHz | 25.2 MHz, passes |
| 2026-11-01 | `top_gpu_ft` (FT2232H link), seed 1 | 9400 / 20736 | 3971 / 15552 | 2724 / 15552 | see below | 0 | 38.04 MHz; `ft_clk` 88.65 MHz | 25.2 MHz and 60 MHz, passes |

## Latest builds

Written by `python scripts/report_builds.py --write`. MULT18X18 and MULT9X9 are the chip's hard multipliers. Fmax is the tool's estimate, not a hardware measurement.

| Design | LUT4 | DFF | ALU | BSRAM | MULT18X18 | MULT9X9 | Clock Fmax in MHz |
|---|---|---|---|---|---|---|---|
| `top_gpu` | 12111 / 20736 | 4444 / 15552 | 3626 / 15552 | 6 / 46 | 2 / 48 | 0 / 96 | `clk_pixel` 59.79 (needs 25.2) |
| `top_gpu_ft` | 12766 / 20736 | 4540 / 15552 | 3648 / 15552 | 7 / 46 | 2 / 48 | 0 / 96 | `clk_pixel` 53.63 (needs 25.2); `link.ft_clk` 95.27 (needs 60) |
| `top_gpu_usb` | 11391 / 20736 | 4050 / 15552 | 3374 / 15552 | 4 / 46 | 2 / 48 | 0 / 96 | `clk_pixel` 57.64 (needs 25.2) |
| `top_gpu_usb_ft` | 12141 / 20736 | 4146 / 15552 | 3412 / 15552 | 5 / 46 | 2 / 48 | 0 / 96 | `clk_pixel` 58.73 (needs 25.2); `link.ft_clk` 91.21 (needs 60) |
| `top_gpu_hd` | 12867 / 20736 | 5321 / 15552 | 4104 / 15552 | 6 / 46 | 2 / 48 | 0 / 96 | `clk_core` 53.79 (needs 46.41); `clk_video` 155.81 (needs 74.25) |
| `top_gpu_hd_safe` | 12964 / 20736 | 5319 / 15552 | 4104 / 15552 | 6 / 46 | 2 / 48 | 0 / 96 | `clk_core` 56.08 (needs 26.52); `clk_video` 132.71 (needs 74.25) |
| `top_gpu_hd_nodsp` | 13626 / 20736 | 5359 / 15552 | 4314 / 15552 | 6 / 46 | 0 / 48 | 0 / 96 | `clk_core` 56.53 (needs 46.41); `clk_video` 147.30 (needs 74.25) |
| `top_gpu_hd_ft` | 12923 / 20736 | 5415 / 15552 | 4086 / 15552 | 7 / 46 | 2 / 48 | 0 / 96 | `clk_core` 54.93 (needs 46.41); `clk_video` 149.61 (needs 74.25); `link.ft_clk` 85.97 (needs 60) |
| `top_gpu_1080p30` | 13205 / 20736 | 5405 / 15552 | 3934 / 15552 | 10 / 46 | 2 / 48 | 12 / 96 | `clk_core` 58.94 (needs 46.41); `clk_video` 153.23 (needs 74.25) |
| `top_gpu_1080p30_ft` | 13742 / 20736 | 5499 / 15552 | 3958 / 15552 | 11 / 46 | 2 / 48 | 12 / 96 | `clk_core` 55.26 (needs 46.41); `clk_video` 138.72 (needs 74.25); `link.ft_clk` 106.50 (needs 60) |
| `top_gpu_1080p30x3` | 12936 / 20736 | 5398 / 15552 | 3966 / 15552 | 8 / 46 | 5 / 48 | 12 / 96 | `clk_core` 54.94 (needs 46.41); `clk_video` 156.08 (needs 74.25) |
| `top_gpu_1080p30x4` | 13492 / 20736 | 5299 / 15552 | 3944 / 15552 | 6 / 46 | 2 / 48 | 12 / 96 | `clk_core` 52.28 (needs 46.41); `clk_video` 137.87 (needs 74.25) |
| `top_gpu_1080p30x5` | 12768 / 20736 | 5332 / 15552 | 3978 / 15552 | 6 / 46 | 5 / 48 | 12 / 96 | `clk_core` 56.72 (needs 46.41); `clk_video` 132.54 (needs 74.25) |
| `top_gpu_1080p30x6` | 13633 / 20736 | 5319 / 15552 | 3972 / 15552 | 6 / 46 | 5 / 48 | 12 / 96 | `clk_core` 52.68 (needs 46.41); `clk_video` 142.76 (needs 74.25) |
| `top_gpu_1080p30x7` | 13096 / 20736 | 5308 / 15552 | 4008 / 15552 | 6 / 46 | 5 / 48 | 12 / 96 | `clk_core` 59.07 (needs 46.41); `clk_video` 155.38 (needs 74.25) |
| `top_gpu_1080p30dd` | 16401 / 20736 | 6375 / 15552 | 5760 / 15552 | 17 / 46 | 2 / 48 | 12 / 96 | `clk_core` 60.23 (needs 46.41); `clk_video` 90.46 (needs 74.25) |
| `top_gpu_1080p30x3dd` | 17148 / 20736 | 6368 / 15552 | 5764 / 15552 | 15 / 46 | 5 / 48 | 12 / 96 | `clk_core` 53.94 (needs 46.41); `clk_video` 90.08 (needs 74.25) |
| `top_gpu_1080p30x4dd` | 16232 / 20736 | 6269 / 15552 | 5774 / 15552 | 10 / 46 | 2 / 48 | 12 / 96 | `clk_core` 56.37 (needs 46.41); `clk_video` 94.54 (needs 74.25) |
| `top_gpu_1080p30x5dd` | 16333 / 20736 | 6302 / 15552 | 5794 / 15552 | 10 / 46 | 5 / 48 | 12 / 96 | `clk_core` 55.70 (needs 46.41); `clk_video` 95.46 (needs 74.25) |
| `top_gpu_1080p30x6dd` | 16412 / 20736 | 6289 / 15552 | 5802 / 15552 | 10 / 46 | 5 / 48 | 12 / 96 | `clk_core` 57.41 (needs 46.41); `clk_video` 90.22 (needs 74.25) |
| `top_gpu_1080p30x7dd` | 16387 / 20736 | 6278 / 15552 | 5842 / 15552 | 10 / 46 | 5 / 48 | 12 / 96 | `clk_core` 54.43 (needs 46.41); `clk_video` 90.79 (needs 74.25) |
| `top_gpu_1080` | 13466 / 20736 | 5446 / 15552 | 4264 / 15552 | 6 / 46 | 2 / 48 | 0 / 96 | `clk_core` 51.61 (needs 48); `clk_video` 147.65 (needs 115.2) |
| `top_gpu_1080_ft` | 13403 / 20736 | 5564 / 15552 | 4292 / 15552 | 7 / 46 | 2 / 48 | 0 / 96 | `clk_core` 51.93 (needs 48); `clk_video` 146.16 (needs 115.2); `link.ft_clk` 94.28 (needs 60) |
| `bars_720p` | 359 / 20736 | 172 / 15552 | 184 / 15552 | 0 / 46 | 0 / 48 | 0 / 96 | `clk_pixel` 207.00 (needs 74.25) |
| `bars_1080p30` | 354 / 20736 | 172 / 15552 | 182 / 15552 | 0 / 46 | 0 / 48 | 0 / 96 | `clk_pixel` 210.84 (needs 74.25) |
| `bars_1080p50` | 346 / 20736 | 172 / 15552 | 174 / 15552 | 0 / 46 | 0 / 48 | 0 / 96 | `clk_pixel` 226.96 (needs 115.2) |

## What these timing numbers do not cover
- **SDRAM pin timing.** There are no input or output delay constraints, so nextpnr does not check the path to and from the SDRAM. The half-cycle margin is checked only against the simulation model. See `docs/verify.md`.
- **The inverted SDRAM clock.** The build warns that `clk_pixel` reaches that logic over general routing, so the SDRAM clock is not exactly opposite the pixel clock.
