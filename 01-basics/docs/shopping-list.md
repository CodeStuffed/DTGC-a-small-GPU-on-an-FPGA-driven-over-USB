# Shopping List

Prices are rough guesses and vary by country and seller. Items marked VERIFY need checking before you buy.

## A. Stage 1 hardware (about $35-70 total)
| Item | Approx. cost | Notes |
|---|---|---|
| Sipeed Tang Nano 20K FPGA board, **quantity 1**. A spare is optional, and can wait until money allows | $25-45, check current price | Main board. Check the listing for which accessories are included (header pins, etc.) |
| USB-C cable that carries data | $5 | Many cables are charge-only; if the board is not detected, try another cable |
| HDMI cable | $5 | The schematic indicates a full-size (Type A) connector, so buy a standard HDMI cable. Not yet confirmed by eye on a real board |
| A monitor or TV with HDMI | have one | |
| microSD card, 8-32 GB (optional) | $5 | Only for the SD playback milestone |

Listing checked on 2026-11-01: [Sipeed Store on AliExpress](https://th.aliexpress.com/item/1005005581148230.html), option "Tang Nano 20K", shown as board with soldered pin header plus USB-C data cable, ฿582.21 before tax as a new-buyer price (about ฿1,114 otherwise). Other options on that page include screens and accessories without the board. Prices change.

## B. Free open-source software to install (Stage 1, no accounts needed)
| Software | Purpose |
|---|---|
| OSS CAD Suite (one download) | Bundles Yosys, nextpnr-himbaechel (Apicula), openFPGALoader, Icarus Verilog, Verilator and GTKWave: build, flash, simulate and view waveforms |
| Python 3, plus `pyserial` and `cocotb` (via pip) | PC-side GPU software and tests |
| Git (optional but recommended) | Saves versions of your work |

## C. Nice-to-have debugging gear (about $10-30)
| Item | Approx. cost | Why |
|---|---|---|
| Cheap 8-channel USB logic analyzer (Saleae-compatible clone) | $10-15 | See what the signals are actually doing when something fails |
| Dupont jumper wires (male-female and male-male) | $5 | Wiring modules together |
| Small breadboard | $5 | Same |

## D. Stage 2 (buy only after Stage 1 works)
| Item | Approx. cost | Notes |
|---|---|---|
| FT2232H breakout module (e.g. FT2232H mini module or similar) | $15-30 | Tests the fast USB link with no PCB; VERIFY the pinout |
| Basic soldering iron, solder, flux | $15-30 | Only for through-hole parts such as pin headers, and for fixing mistakes. An assembly service places the small SMD parts |
| Multimeter | $15 | Check power and continuity |
| KiCad (free software) | free | PCB design |
| Assembled PCBs from JLCPCB, PCBWay or Seeed Fusion (board + parts + SMT assembly + shipping) | roughly $20-60 for 5 boards, VERIFY on their calculator | Upload Gerbers, BOM and CPL files made by `scripts/pcb_quote_pack.py`. Setup fees, per-part fees and shipping to Thailand vary |
| Tweezers, magnifier (optional) | $10-30 | Only if you hand-solder or rework |

Hand-soldering everything yourself instead of using an assembly service would need a fine-tip iron, flux, tweezers and a microscope or magnifier, and is harder for the LQFP FT2232H chip.

## Suggested order of purchase
1. Install the free software (section B).
2. Order the Tang Nano 20K, cables and the optional logic analyzer (A and C).
3. Do Milestones 0-4.
4. Only then order Stage 2 items (D): first the FT2232H breakout module, and only after that tests well, the assembled PCBs.
