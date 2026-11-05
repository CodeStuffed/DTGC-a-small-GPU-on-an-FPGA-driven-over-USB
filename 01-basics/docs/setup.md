# Setup Guide

## 1. Hardware design software (all free and open source, no accounts)

The easiest way is the **OSS CAD Suite**, one download that bundles most of the tools below. Find the current release on the YoSys HQ GitHub page (search "OSS CAD Suite"). It works on Windows, Linux and Mac.

| Software | What it is for | Included in OSS CAD Suite? |
|---|---|---|
| Yosys | Turns Verilog into a circuit (synthesis) | Yes |
| nextpnr-himbaechel (with Project Apicula; replaces the old `nextpnr-gowin` command) | Places and routes the circuit on the Gowin FPGA in the Tang Nano 20K | Yes |
| openFPGALoader | Flashes the board over USB | Yes |
| Icarus Verilog (`iverilog`) and Verilator | Simulating the GPU on your PC before flashing | Yes |
| GTKWave | Viewing waveforms from simulations | Yes |
| Python 3 + `pyserial` + `cocotb` | PC-side GPU code and Python-based tests | Python is separate; install `pyserial` and `cocotb` with pip |
| KiCad | Designing the Stage 2 PCB (later) | No, separate download |

No Gowin EDA is used anywhere in this project.

**Windows note:** winget has no OSS CAD Suite package. Download the Windows archive from the YosysHQ release page and extract it (this project uses `C:\tools\oss-cad-suite`). Add its `bin` and `lib` folders to your PATH, or the tools fail with a missing DLL error. Installed versions are in `tools/versions.md`.

**Known risk:** open-source support for the Tang Nano 20K's chip (Gowin GW2A-18) is less mature than for smaller Gowin chips. The features we need have upstream build targets, but open bugs can make logic compute wrong results on this chip even when simulation passes. See `docs/verify.md`.
Check each tool's website for the current download for your system; versions change.

## 2. Hardware to buy (Stage 1)
- Sipeed Tang Nano 20K board
- USB-C data cable (not a charge-only cable)
- HDMI cable and a monitor or TV
- Optional: microSD card

## 3. Skills you will use
You do not need to be an expert. These are the ideas you will pick up as you go.

| Skill | Where it comes up |
|---|---|
| Verilog / SystemVerilog basics | Everything in `rtl/` |
| Digital logic: clocks, registers, state machines | Timing generator, command decoder |
| Simulation and waveform reading | Debugging in `sim/` |
| Video timing (sync, porches, pixel clock) | Milestone 2 |
| TMDS/DVI encoding | HDMI output |
| Serial/UART and FIFO interfaces | Milestones 4-5, Stage 2 |
| Python scripting | `sw/` |
| Reading datasheets and schematics | VERIFY items, Stage 2 |
| KiCad, soldering (LQFP, SMD) | Stage 2 only |

## 4. Working habits that make this succeed
- One milestone at a time; test before moving on.
- When something fails on hardware, copy the exact error text (or describe exactly what you see) into `docs/test-log.md`.
- Commit your work often if you use git.
