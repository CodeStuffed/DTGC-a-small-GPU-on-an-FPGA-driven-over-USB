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

Written by `python scripts/report_builds.py --write`. No DSP blocks are used. Fmax is the tool's estimate, not a hardware measurement.

| Design | LUT4 | DFF | ALU | BSRAM | Clock Fmax in MHz |
|---|---|---|---|---|---|
| `top_gpu` | 11672 / 20736 | 4346 / 15552 | 3474 / 15552 | 6 / 46 | `clk_pixel` 54.32 (needs 25.2) |
| `top_gpu_ft` | 11733 / 20736 | 4442 / 15552 | 3484 / 15552 | 7 / 46 | `clk_pixel` 58.04 (needs 25.2); `link.ft_clk` 99.54 (needs 60) |
| `top_gpu_usb` | 11055 / 20736 | 3952 / 15552 | 3224 / 15552 | 4 / 46 | `clk_pixel` 56.91 (needs 25.2) |
| `top_gpu_usb_ft` | 11127 / 20736 | 4048 / 15552 | 3240 / 15552 | 5 / 46 | `clk_pixel` 63.20 (needs 25.2); `link.ft_clk` 100.49 (needs 60) |
| `top_gpu_hd` | 12594 / 20736 | 5218 / 15552 | 3932 / 15552 | 6 / 46 | `clk_core` 56.29 (needs 46.41); `clk_video` 145.26 (needs 74.25) |
| `top_gpu_hd_safe` | 13625 / 20736 | 5216 / 15552 | 3920 / 15552 | 6 / 46 | `clk_core` 56.24 (needs 26.52); `clk_video` 156.99 (needs 74.25) |
| `top_gpu_hd_nodsp` | 13002 / 20736 | 5256 / 15552 | 4126 / 15552 | 6 / 46 | `clk_core` 57.36 (needs 46.41); `clk_video` 124.73 (needs 74.25) |
| `top_gpu_hd_ft` | 12856 / 20736 | 5312 / 15552 | 3918 / 15552 | 7 / 46 | `clk_core` 59.10 (needs 46.41); `clk_video` 128.57 (needs 74.25); `link.ft_clk` 95.32 (needs 60) |
| `top_gpu_1080p30` | 12740 / 20736 | 5445 / 15552 | 3852 / 15552 | 10 / 46 | `clk_core` 54.52 (needs 46.41); `clk_video` 163.51 (needs 74.25) |
| `top_gpu_1080p30_ft` | 12800 / 20736 | 5539 / 15552 | 3866 / 15552 | 11 / 46 | `clk_core` 60.43 (needs 46.41); `clk_video` 161.63 (needs 74.25); `link.ft_clk` 100.19 (needs 60) |
| `top_gpu_1080` | 13115 / 20736 | 5342 / 15552 | 4078 / 15552 | 6 / 46 | `clk_core` 58.13 (needs 48); `clk_video` 142.13 (needs 115.2) |
| `top_gpu_1080_ft` | 12879 / 20736 | 5460 / 15552 | 4122 / 15552 | 7 / 46 | `clk_core` 54.82 (needs 48); `clk_video` 137.23 (needs 115.2); `link.ft_clk` 97.22 (needs 60) |
| `bars_720p` | 359 / 20736 | 172 / 15552 | 184 / 15552 | 0 / 46 | `clk_pixel` 207.00 (needs 74.25) |
| `bars_1080p30` | 354 / 20736 | 172 / 15552 | 182 / 15552 | 0 / 46 | `clk_pixel` 210.84 (needs 74.25) |
| `bars_1080p50` | 346 / 20736 | 172 / 15552 | 174 / 15552 | 0 / 46 | `clk_pixel` 226.96 (needs 115.2) |

## What these timing numbers do not cover
- **SDRAM pin timing.** There are no input or output delay constraints, so nextpnr does not check the path to and from the SDRAM. The half-cycle margin is checked only against the simulation model. See `docs/verify.md`.
- **The inverted SDRAM clock.** The build warns that `clk_pixel` reaches that logic over general routing, so the SDRAM clock is not exactly opposite the pixel clock.
