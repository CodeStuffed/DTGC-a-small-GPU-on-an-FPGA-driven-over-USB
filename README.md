# DTGC: a small GPU on an FPGA, driven over USB

DTGC is a graphics chip I am building on the Sipeed Tang Nano 20K FPGA board. A PC sends drawing commands over USB, the FPGA draws into memory, and the picture goes out over HDMI to a monitor.

**Status: nothing has run on real hardware yet.** Every result here comes from simulation (running the Verilog on a PC) or from the emulator (a Python copy of the GPU). "Passes simulation" never means "works on the board". Real results go in [docs/test-log.md](docs/test-log.md).

## The plan

1. **Basics.** Install free open-source FPGA tools, read the board's schematic, blink an LED, show colour bars over HDMI, and keep a picture in the board's SDRAM memory.
2. **Talk to a PC.** A USB protocol with checksums and retries, a parser on the FPGA, and a Python emulator of the GPU so software can be tested without a board.
3. **Draw in 3D.** A triangle rasterizer with depth test, colour blending and textures, then a spinning cube demo.
4. **Make it fast.** Measure a frame in simulation and remove the slowest parts one at a time.
5. **HD output.** 720p and 1080p, with an upscaler so 1080p fits the board's memory and speed. Target: 1080p at 30 fps.
6. **Make it useful.** An app window, small games, a graphics API, and a small Direct3D 9 bridge for old programs.
7. **Faster USB.** Windows and Linux app packages, and a link through an FT2232H USB 2.0 chip, much faster than the board's own serial port.
8. **A board for the fast link.** A small 4-layer "backpack" PCB with the FT2232H that plugs on top of the Tang Nano 20K.
9. **Ready to order.** A 3D-printed case, the files an assembly service needs, and a line-by-line check of the schematic against the chip's datasheet.
10. **Wrap up.** How to run and test everything, then real hardware tests.

Rules for the whole project: free tools only, every Verilog module gets a testbench, and no pin or voltage is guessed. Anything not yet confirmed is marked VERIFY.

## Progress log

Each update below was added when that step was finished. Older updates stay as they were written.

<!-- part 1 -->
### Update 1: Tools, first blink, colour bars and memory

The starting point: free tools, a check that they support this board, and the first three pieces of hardware design.

- **Tools.** Only free open-source tools: Yosys, nextpnr-himbaechel with Apicula, openFPGALoader and Icarus Verilog, all from the OSS CAD Suite. No vendor tools. Install steps are in [docs/setup.md](docs/setup.md), installed versions in [tools/versions.md](tools/versions.md), and what to buy in [docs/shopping-list.md](docs/shopping-list.md).
- **Board research.** Pins come from Sipeed's schematic, not from guesses. Any pin, voltage or timing not yet confirmed is marked VERIFY in [docs/verify.md](docs/verify.md). The pins used are in [docs/board/pins-needed.md](docs/board/pins-needed.md).
- **Blink an LED** (`rtl/blink.v`). The smallest test that the build and flash chain works. Passes simulation and the bitstream builds.
- **640x480 HDMI colour bars** (`rtl/video_timing.v`, `rtl/tmds_encoder.v`, `rtl/hdmi_out.v`). Screen timing plus TMDS, the encoding HDMI uses for each colour wire. Passes simulation and the bitstream builds.
- **SDRAM framebuffer** (`rtl/sdram_ctrl.v`, `rtl/fb_scanout.v`). The picture is kept in the board's SDRAM memory and read out to the screen. A memory model fails the test on any broken timing rule. Writing it found two mistakes: too few memory refreshes in the first plan, and stray pixels after reset.

The overall plan is in [docs/design-plan.md](docs/design-plan.md) and the milestone list in [docs/roadmap.md](docs/roadmap.md).

Next: get commands from a PC into the GPU, and a way to test without a board.

<!-- part 2 -->
### Update 2: USB protocol, emulator and tests

The GPU learns to take commands from a PC, and everything gets a test.

- **Protocol** ([docs/protocol.md](docs/protocol.md)). Binary packets with checksums, sequence numbers and retries. On the FPGA, `rtl/uart_rx.v` receives, `rtl/pkt_parser.v` checks each packet and `rtl/cmd_exec.v` runs it. The first UART version cut the stop bit short; the tests caught it.
- **Emulator** (`sw/dtgc/emulator.py`). A Python copy of the GPU that speaks the same protocol over TCP. It matches the Verilog bit for bit on random command streams, so software can be written and tested with no board.
- **Library and command line** (`sw/dtgc/`). Finds the board, or falls back on the emulator. Has a self-test, and record and replay.
- **Tests.** `python scripts/run_tests.py --quick` runs everything. [scripts/mutation_check.py](scripts/mutation_check.py) plants one bug at a time in the Verilog and checks that some test fails.
- **Saving link bandwidth.** Only changed tiles are sent, with run-length compression. A benchmark mode measures it: from 9 bytes per frame for a still picture up to 120,522 bytes for noise ([docs/benchmarks.md](docs/benchmarks.md)).

Next: draw triangles.
