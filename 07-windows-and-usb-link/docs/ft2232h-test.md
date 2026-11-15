# FT2232H breakout test (Milestone 11)

This test must pass before any backpack PCB is ordered. It is not due yet: run it after the Tang Nano 20K has passed Milestones 1 to 4 on the UART link.

Nothing here has been run on real hardware. The design passes in simulation against a model of the chip that I wrote from FTDI's description, so a wrong reading of the datasheet would pass too.

**Synchronous FIFO mode** means the chip supplies a 60 MHz clock and moves one byte per clock. That is what makes this link faster than the UART.

## What you need

- A Tang Nano 20K
- An FT2232H breakout module that brings out channel A and has an EEPROM. Check the module's own schematic before buying (VERIFY), because without an EEPROM FIFO mode can't be set
- Jumper wires, as short as you can manage. 60 MHz over jumpers may be unreliable, and a failure here does not prove the PCB would fail
- `pip install ftd2xx`, plus FTDI's D2XX driver if Windows didn't install it

`ftd2xx` isn't on the shopping list. It's a free MIT-licensed Python package, and it's the part that lets Python talk to the chip. The D2XX driver is FTDI's: free of charge but closed source. It's only for the PC side and has nothing to do with building the FPGA design.

## Wiring

All of it is VERIFY. Check the FT2232H names against the datasheet and your module's schematic, and the Tang pins against the schematic for your board version.

| Signal | FT2232H pin | FT2232H name | Tang header | FPGA pin |
|---|---|---|---|---|
| D0 | 16 | ADBUS0 | J2-10 | 48 |
| D1 | 17 | ADBUS1 | J2-12 | 49 |
| D2 | 18 | ADBUS2 | J2-9 | 51 |
| D3 | 19 | ADBUS3 | J2-20 | 52 |
| D4 | 21 | ADBUS4 | J2-19 | 53 |
| D5 | 22 | ADBUS5 | J2-8 | 54 |
| D6 | 23 | ADBUS6 | J2-11 | 55 |
| D7 | 24 | ADBUS7 | J2-7 | 56 |
| RXF# | 26 | ACBUS0 | J3-8 | 27 |
| TXE# | 27 | ACBUS1 | J3-9 | 28 |
| RD# | 28 | ACBUS2 | J3-12 | 29 |
| WR# | 29 | ACBUS3 | J3-13 | 30 |
| CLKOUT | 32 | ACBUS5 | J3-5 | 77 |
| OE# | 33 | ACBUS6 | J3-14 | 31 |
| GND | | GND | any GND | |

Connect GND with several wires. Do **not** connect the two boards' 5 V or 3.3 V together: each one gets power from its own USB cable.

## Checklist

Do these in order. If a step gives a different result, stop and tell me the step number and exactly what you saw.

1. Build the design:
   ```bash
   python scripts/build.py top_gpu_ft constraints/gpu_ft.cst rtl/top_gpu_ft.v rtl/ft_link.v rtl/ft_bus.v rtl/async_fifo.v rtl/gpu_core.v rtl/cmd_exec.v rtl/raster.v rtl/pkt_parser.v rtl/reply_tx.v rtl/byte_fifo.v rtl/sdram_ctrl.v rtl/fb_scanout.v rtl/video_timing.v rtl/tmds_encoder.v rtl/hdmi_out.v rtl/video_clocks.v --freq 25.2 --seed 1 --sdc constraints/gpu_ft.sdc --pack-flag sspi_as_gpio --pack-flag cpu_as_gpio
   ```
   Expected: the last line is `Built build\top_gpu_ft.fs`.
2. With no jumpers attached, load it into RAM (not flash), so that power-cycling brings back the old design if the dual-use pins cause trouble:
   ```bash
   openFPGALoader -b tangnano20k build/top_gpu_ft.fs
   ```
   Expected: the loader finishes without an error, and the monitor shows a stable picture, which may be random colours because memory has not been cleared. The two warning LEDs stay off.
3. Plug in only the breakout module's USB cable, then show its settings:
   ```bash
   python sw/ft_setup.py
   ```
   Expected: a list of 8 settings. It ends with either `Already set for FIFO mode` or `Nothing changed. Add --write to change them.`
4. If it said `Nothing changed`, write the settings, then unplug and replug that USB cable:
   ```bash
   python sw/ft_setup.py --write
   ```
   Expected: `Written and read back correctly.` Running step 3 again then says `Already set for FIFO mode`.
5. Unplug both USB cables. Connect GND first, then the rest of the table. Plug in the Tang, load the design as in step 2, then plug in the module.
   Expected: same as step 2.
6. Ask the GPU to answer:
   ```bash
   python -m sw.dtgc --ft2232h 0 selftest
   ```
   Expected: 8 lines, each starting with `PASS`. The 340x340 square is black with a small coloured patch in its bottom-right corner, and the two warning LEDs stay off.
7. Run the spinning cube:
   ```bash
   python -m sw.dtgc --ft2232h 0 spin
   ```
   Expected: a spinning cube with no corrupted pixels for the whole run.
8. Measure the speed:
   ```bash
   python -m sw.dtgc --ft2232h 0 benchmark
   ```
   Expected: it finishes without a link error. Send me the whole output, because no real number exists yet.

The test passes only if steps 6 to 8 all pass. If FIFO mode fails on jumpers, the checks left to do are in `docs/verify.md`.
