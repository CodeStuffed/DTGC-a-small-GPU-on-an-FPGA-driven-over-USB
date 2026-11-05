# Roadmap

Tick each box only when it is really done. "By hand" items need a person or real hardware.
Names: **DTGC** is the GPU design on the Tang Nano 20K. **xDTGC** is the external box: custom USB backpack PCB plus case.
Rules: USB only (one cable for power and data), HDMI out, no PCIe. "Passes simulation" never means "works on hardware".

## Stage 1: DTGC on the Tang Nano 20K

### Milestone 0: Setup
- [x] By hand: install the free open-source software in `docs/setup.md` (versions in `tools/versions.md`)
- [x] Check open-source support for the Tang Nano 20K and report (`docs/verify.md`)
- [ ] By hand: order the Tang Nano 20K, USB-C cable, HDMI cable (and microSD card, optional)
- [x] Confirm the simulator runs (`sim/smoke/`, passes simulation)
- [x] Collect the board schematic and pinout (`docs/board/`)

### Milestone 1: Blink an LED (proves toolchain and flashing)
- [x] `rtl/blink.v`, testbench, constraints (passes simulation, bitstream builds, not yet flashed)
- [ ] By hand: flash and report in `docs/test-log.md`

### Milestone 2: 640x480 timing, DVI/TMDS, colour bars
- [x] `rtl/video_timing.v`, with testbench (passes simulation)
- [x] `rtl/tmds_encoder.v` and `rtl/hdmi_out.v`, with testbench (encoder passes simulation)
- [x] `rtl/top_colorbars.v` (bitstream builds)
- [ ] By hand: flash, connect a monitor, report what is on screen

### Milestone 3: Framebuffer
- [x] SDRAM controller and scan-out with a sticky "ran out of pixels" flag (`rtl/sdram_ctrl.v`, `rtl/fb_scanout.v`), passes simulation with the flag never set. Went straight to SDRAM, because one 340x340 frame (925 Kbit) does not fit in block RAM (828 Kbit)
- [x] SDRAM model with rule checks, random testbench (30 seeds), framebuffer testbench with every pixel compared, PNG of simulated output
- [x] `rtl/top_framebuffer.v` bitstream builds (`docs/resources.md`)
- [ ] Small tile cache (moved to Milestone 7, where the rasterizer needs it)
- [ ] By hand: flash and report

### Milestone 4: Protocol, transport and emulator
- [x] Versioned binary protocol with checksums, sequence numbers and recovery (`docs/protocol.md`), fuzz-tested
- [ ] One transport interface with serial, TCP and FT2232H backends (TCP tested; serial and FT2232H written but never run against a device)
- [x] UART and packet parser in RTL, with testbenches; emulator matches the Verilog bit for bit on random streams; `rtl/top_gpu.v` bitstream builds
- [x] Emulator speaking the same protocol over TCP: PNGs, simulated slow USB, drops and disconnects
- [x] Emulator's live window (tested: pixels read back from a real tkinter window)
- [x] Python library and CLI that auto-detects the device or falls back on the emulator; self-test PASS/FAIL
- [x] Record and replay (tested: replay gives the same picture, over the emulator)
- [x] One-command test script `scripts/run_tests.py`, plus `scripts/mutation_check.py`, which checks the tests catch planted bugs. GitHub automation in `.github/workflows/tests.yml` (not yet run: no repository exists)
- [ ] By hand: confirm the serial port and real maximum baud rate; run a demo and report

### Milestone 5: Frames, tiles and streaming
- [x] Tile and delta updates, dirty tiles, double buffering, run-length compression (`sw/dtgc/stream.py`, TILE and RLE commands in the Verilog)
- [x] Host-side asset cache with prefetch and eviction, latency limits documented (`sw/dtgc/assets.py`). The GPU cannot read from that memory until Milestone 6
- [x] Benchmark mode (`docs/benchmarks.md`), with a CPU baseline for the fractal. The triangle baseline comes with Milestone 6
- [ ] By hand: report real frames per second. 340x340 at 15 fps needs from under 0.01 MB/s to 1.8 MB/s depending on the picture, so full-motion pictures need Stage 2

### Milestone 6: Triangle rasterizer
- [x] Python reference renderer
- [x] One correct unit: fixed-point edge functions, bounding box, colour interpolation, then depth, then textures. Bit-exact against the reference, with edge cases (off-screen, degenerate, overlaps, overflow)
- [x] Emulator matches Verilog bit for bit (tested)
- [x] Record LUT, BRAM, DSP use and timing in `docs/` after every build
- [x] Dither for smoother colour (`docs/windows-and-color-options.md`)
- [x] Indexed triangle lists (VERTICES, TRIANGLE_LIST), matching the emulator bit for bit; the field scene needs 3.43 times fewer bytes
- [x] Spinning 3D cube demo, `python -m sw.dtgc spin`. Simulated picture in `docs/images/spin_simulated.png`, matches the emulator bit for bit
- [x] Texture cache connected to texture rows (`TextureCache` in `sw/dtgc/assets.py`), and a CPU baseline for triangles
- [ ] By hand: flash the spinning 3D demo and report

### Milestone 7: Tile binning and parallel units
- [ ] Tile binning, N rasterizers (a parameter) with a scheduler; report how many fit
- [x] Keep SDRAM rows open, which made a cube frame about 3 times faster in simulation
- [x] One pixel per clock while memory isn't needed, held colour and texture words, burst depth tile: a cube frame went from about 16 ms to about 8 ms in simulation
- [x] Faster clears: word-wide RECT, DEPTH_RECT and `clear_scene`, which took a cube frame from about 8 ms to about 5 ms in simulation
- [x] Fast depth clear, posted colour writes, 8-pixel jump over empty space, no maths for flat colours: a whole cube frame from 205,978 to about 88,000 clocks in simulation
- [x] Faster clock: the HD versions' drawing and memory clock went from about 26 MHz to 46.41 and 48 MHz (passes timing estimate and simulation; SDRAM pins unchecked, so `gpu_hd_safe` stays as a fallback).

- [ ] Optional, after the above: several GPUs, tried in the emulator first (`docs/windows-and-color-options.md`)

### Milestone 8: DT-Upscale
- [x] Edge-directed x2 upscaler (`rtl/upscale_edge.v`), bit-exact with the model at 720p and 1080p30. No neural networks. Bicubic and sharpening not built
- [x] 1080p30 output from a 960x540 picture (`top_gpu_1080p30`, `docs/architecture-1080p30.md`). Passes simulation and build; field scene measured at 30.5 fps in simulation
- [x] Fixed-point shader (`rtl/shade_pipe.v`), bit-exact with its model. Not connected to the GPU, for the reason in that document
- [x] Python model with PSNR and SSIM scores, `docs/upscale.md`
- [x] Bilinear upscaler Verilog matching the model bit for bit in simulation, at 720p and 1080p. Resource use in `docs/resources.md`

### Milestone 9 (optional): DT-RT ray-tracing demo
- [ ] A few spheres and triangles at low resolution, only if resources and timing allow. Labelled a demo

### Milestone 10: Games, phased
Modern DirectX and Vulkan games are out of scope for this chip and link.
- [x] 10a: our own simple games: Pong, Maze, Dodge (`python -m sw.dtgc play pong`), plus a button launcher (`python -m sw.dtgc app`). Tested on the emulator only
- [ ] By hand: play them on the board with a monitor and report the frame rate and whether they are any fun
- [x] 10b: documented DTGC graphics API (`docs/api.md`)
- [x] Windows and Linux app packages with a pop-up window (`docs/driver-app.md`). Windows tested from a clean folder with the emulator. Linux not run on Linux
- [ ] 10c: port open-source games whose licences allow it. No commercial assets, no copy-protection bypass
- [ ] 10d: MiniGL-style OpenGL 1.x subset (replacement opengl32.dll per program), tested against the emulator first
- [ ] 10e: real Windows display driver. Research only: effort, signing and risks are written up first, and nothing starts without approval

## Stage 2: xDTGC backpack (FT2232H, USB High-Speed)

### Milestone 11: FT2232H on a breakout module
- [x] Sync FIFO interface in Verilog with constraints and a build check of the dual-use pins, with testbench (`rtl/ft_link.v`, `rtl/top_gpu_ft.v`). The whole GPU matches the emulator bit for bit through the link in simulation, against my own model of the chip
- [x] EEPROM setup method and FT2232H transport backend (`sw/ft_setup.py`, `Ft2232hTransport`). Tested against a stand-in only
- [ ] By hand: buy an FT2232H breakout module, wire it with jumpers, follow `docs/ft2232h-test.md`, report. **This must pass before any PCB is ordered**

### Milestone 12: Backpack PCB
- [x] Schematic in `pcb/backpack/`, ERC 0 errors, 0 warnings
- [x] 4-layer placement and routing (`scripts/pcb_place.py`, `scripts/pcb_route.py`). DRC 0 errors, 0 unconnected. Rules only, not proof it works
- [ ] By hand: review the layout using `docs/pcb-layout-review.md`
- [x] Datasheet review of the schematic against FT2232H datasheet v2.3 (4 faults fixed), re-route with no vias in pads, DRC 0 errors, 0 unconnected (2026-11-02)
- [x] LCSC part numbers in the schematic, BOM, CPL, Gerbers (`pcb/backpack/quote/`, `python scripts/pcb_quote_pack.py`), design-for-assembly check against PCBWay's published limits
- [ ] Check stock on order day (cached database prices only so far)
- [x] Home test checklist for assembled boards (`docs/pcb-home-test.md`)
- [ ] By hand: order after Milestone 11 passes; test and report. Expect a possible second revision

### Milestone 13: Case
- [x] 3D-printable case with USB and HDMI cutouts (`docs/case.md`). Closed-surface check passes. Its connector positions are placeholders until measured on real boards
- [ ] By hand: measure the boards, then print and test the fit

### Later option: FT601 (USB 3.0). Everything about it is VERIFY

## Stage 3: Publish
- [x] Formal technical paper with maths, design choices, PCB layout and simulation videos (`docs/paper/paper.html`). Not peer reviewed. All results are from simulation
- [ ] README with diagrams, architecture, protocol, real measured benchmarks, and what is and is not supported
- [ ] Technical write-up, "what failed and what I learned" log
- [ ] By hand: check name availability (`docs/verify.md`), then publish
