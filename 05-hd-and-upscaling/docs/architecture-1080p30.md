# The 1080p30 design

Everything here passes simulation. None of it has run on a real board.

**Honest summary:** the HDMI output is a real 1920x1080 at 30 Hz signal. The picture the GPU draws is 960x540, and the upscaler
doubles it. A true 1920x1080 render does not fit: the two colour buffers and depth need 8.29 MB of the 8.39 MB SDRAM, and 2 million
pixels at one pixel per clock takes 43 ms against the 33 ms budget.

## Module hierarchy

```
top_gpu_hd (UART link)  or  top_gpu_hd_ft (FT2232H link: ft_link, ft_bus, async_fifo)
├── video_clocks        27 MHz in; 371.25 MHz serial, 74.25 MHz video, 46.41 MHz core
├── uart_rx, uart_tx
├── gpu_core            everything below runs on clk_core, except scan-out's output side
│   ├── byte_fifo, pkt_parser, reply_tx      packets in, replies out
│   ├── cmd_exec        one command at a time
│   ├── vertex_store    256 corners, for indexed triangle lists
│   ├── raster          one pixel per clock while its held words last
│   │   └── depth_flags one "cleared" mark per depth tile, so a clear costs 563 clocks
│   ├── frame_reader    reads the picture back to the PC
│   ├── sdram_ctrl      32-bit SDRAM, rows kept open, burst reads
│   └── fb_scanout_hd   the crossing between the two clocks
│       ├── line buffers in block RAM
│       ├── video_timing  the 1920x1080 frame
│       └── upscale_edge  the x2 scaler (upscale_filter is the plain bilinear one)
└── hdmi_out            TMDS encoders and serialisers, on clk_video and the serial clock
```

`rtl/shade_pipe.v` is **not** in this tree. See below.

## Clocks

| Clock | MHz | Used for |
|---|---|---|
| Serial | 371.25 | HDMI bits, 742.5 Mbit/s per lane (double data rate) |
| `clk_video` | 74.25 | Screen pixels. H 1920, 88, 44, 148; V 1080, 4, 5, 36 |
| `clk_core` | 46.41 (371.25 / 8) | Command handling, drawing, SDRAM |

Screen time at 30 Hz is 33.33 ms, which is 1,547,000 core clocks.

## Measured frame time (Verilog simulation, scan-out reading memory at the same time)

| Scene | Clocks per frame | Time | GPU-only rate |
|---|---|---|---|
| Cube | 255,780 | 5.51 ms | 181 fps |
| Cube field | 1,521,436 | 32.8 ms | 30.5 fps |

## Build (nextpnr's estimate, no pin timing)

`top_gpu_1080p30`: 12,740 of 20,736 LUT4 (61%), 5,445 of 15,552 DFF (35%), 10 of 46 BSRAM, 2 of 48 MULT18X18 (4%). `clk_core` reaches
54.52 MHz, `clk_video` 163.51 MHz. Every build is in [resources.md](resources.md).

## Upscaler: `rtl/upscale_edge.v`

Each new pixel is a mix of its neighbours, leaning along an edge instead of across it, using a small table of weights. Scale 2 only,
same 8-clock delay as the bilinear filter, no multipliers. Every screen pixel matched the Python model at 720p and 1080p30, and a
direct testbench passes 200,000 pixels.

Line storage uses block RAM. A brief for this design suggested shift-register line buffers. A 960-pixel line of 24-bit colour is 23,040 bits,
more than the chip's 15,552 flip-flops, against a few BSRAMs here, so block RAM is the only choice that fits.

## Shader: `rtl/shade_pipe.v`

Five stages: Q4.12 normal and light dot product, Q8.8 ambient, noise from a stateless xorshift, then alpha blend (alpha 0 to 256). In
40,000 random pixels it matches `sw/dtgc/shade.py` bit for bit.

Alone it uses 293 LUT4, 424 DFF and 10 DSP blocks (6 MULT18X18, 4 MULT9X9). With the core's 2 that makes 12 of 48, about 25%, under the
70% limit. It reaches 129.17 MHz (`sim/shade_pipe_wrap.v` puts flip-flops on its pins so this is a fair number).

**It is not connected to the GPU.** The GPU stores 8-bit palette colours, and blending needs one extra memory read per pixel, which
would break the 30.5 fps measured above. Connecting it means a 16-bit colour buffer, or a blend that only runs on some triangles.
That is a separate piece of work with a new measurement.

## Timing tips for this flow (Yosys and nextpnr, no vendor tools)

1. Write `a * b` in plain Verilog with a register on both sides. Yosys maps it to a hard multiplier without any vendor primitive.
2. Split long sums over clocks. The TMDS encoder went from 51 to over 140 MHz by taking four clocks instead of one.
3. Give every clock its own constraint, as in `constraints/gpu_hd.sdc`. Otherwise nextpnr tests all logic against the fastest clock.
4. Cross clocks only through a FIFO or a block RAM with gray-coded or handshaked pointers.
5. Read the Fmax of each clock from the final block of the log. `scripts/report_builds.py` does this.
6. Results change with seed. `scripts/build_all.py` tries seeds 1 to 5 and says when seed 1 failed.
7. nextpnr does not check SDRAM or FT2232H pins. A passing number says nothing about them, so treat the first hardware run as the real test.

## What can still stop this on the board
- Whether a monitor accepts 1080p at 30 Hz.
- 742.5 Mbit/s on the HDMI pins, not checked by the tools.
- SDRAM at 46.41 MHz, with half a clock of read margin. `gpu_hd_safe` is the slow fallback for 720p.

These are listed in [verify.md](verify.md). The order to try them is in [first-hardware.md](first-hardware.md), section G.
