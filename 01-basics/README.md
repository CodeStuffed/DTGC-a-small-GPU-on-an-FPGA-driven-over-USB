# DTGC code and design, after change 04

Each change adds a section at the top. Older sections stay as they were written. Nothing here has run on real hardware yet.

## 04. SDRAM framebuffer

A 340x340 picture does not fit in block RAM, so the picture lives in the SDRAM inside the FPGA package. Memory controller, scan-out with a sticky "ran out of pixels" flag, and a memory model that enforces chip timing.

Files: [rtl/sdram_ctrl.v](rtl/sdram_ctrl.v), [rtl/fb_scanout.v](rtl/fb_scanout.v), [rtl/fb_core.v](rtl/fb_core.v), [rtl/fb_pattern.v](rtl/fb_pattern.v), [rtl/top_framebuffer.v](rtl/top_framebuffer.v), [sim/sdram_model.v](sim/sdram_model.v), [sim/sdram_ctrl_tb.v](sim/sdram_ctrl_tb.v), [sim/fb_core_tb.v](sim/fb_core_tb.v), [constraints/framebuffer.cst](constraints/framebuffer.cst)

Tested: Random testbench with 30 seeds; framebuffer testbench compares every pixel and saves the real output as a PNG.

Result: Passes simulation. Found too few refreshes in the first plan and stray pixels after reset (see docs/lessons.md).

## 03. 640x480 HDMI colour bars

Screen timing, the TMDS encoder that turns pixels into the HDMI (DVI) signal, and a colour bar picture.

Files: [rtl/video_timing.v](rtl/video_timing.v), [rtl/tmds_encoder.v](rtl/tmds_encoder.v), [rtl/hdmi_out.v](rtl/hdmi_out.v), [rtl/top_colorbars.v](rtl/top_colorbars.v), [sim/video_timing_tb.v](sim/video_timing_tb.v), [sim/tmds_encoder_tb.v](sim/tmds_encoder_tb.v), [constraints/hdmi.cst](constraints/hdmi.cst)

Tested: Timing testbench counts every line and pixel. Encoder testbench checks the DVI encoding rules.

Result: Passes simulation, bitstream builds.

## 02. Blink an LED

The smallest possible design, to prove the tools can build a bitstream for this chip.

Files: [rtl/blink.v](rtl/blink.v), [sim/blink_tb.v](sim/blink_tb.v), [constraints/blink.cst](constraints/blink.cst)

Tested: Testbench checks the LED toggles at the expected count.

Result: Passes simulation, bitstream builds. Not flashed yet.

## 01. Tools installed and board researched

Installed the free FPGA tools (OSS CAD Suite: Yosys, nextpnr, Apicula, openFPGALoader, Icarus Verilog) and checked open-source support for the Tang Nano 20K. Collected the board's schematics and pin list, and started the list of facts still to confirm.

Files: [tools/versions.md](tools/versions.md), [docs/setup.md](docs/setup.md), [docs/shopping-list.md](docs/shopping-list.md), [docs/design-plan.md](docs/design-plan.md), [docs/roadmap.md](docs/roadmap.md), [docs/verify.md](docs/verify.md), [docs/board/pins-needed.md](docs/board/pins-needed.md), [sim/smoke/](sim/smoke/)

Tested: A counter testbench runs in Icarus Verilog and through cocotb.

Result: Passes simulation.
