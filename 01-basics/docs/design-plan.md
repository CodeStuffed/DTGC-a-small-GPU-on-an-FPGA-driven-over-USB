# TinyGPU-USB: Build Plan

A very simple USB-connected GPU that outputs small video to a monitor over HDMI.
Built in two stages so you get something working fast and only then risk a custom PCB.

Assumptions: video shows on a monitor via HDMI; the PC sends data over USB.
Items marked VERIFY are from memory and must be checked against the datasheet or board schematic before you order or wire anything.

---

## Stage 1: Working GPU on a ready-made board (no PCB, about $30-60)

### Parts
| Part | Why | Approx. cost |
|---|---|---|
| Sipeed Tang Nano 20K (Gowin GW2AR-18 FPGA) | Has HDMI out, USB-C, onboard SDRAM, microSD slot (VERIFY exact connector type and pinout on the board schematic) | $25-35 |
| USB-C cable | Programming + PC link | $5 |
| HDMI cable + any monitor/TV | Display | have one |
| microSD card (optional) | Store a small video clip on the board | $5 |

### Software (all free)
- Open-source toolchain only: Yosys + nextpnr-himbaechel (Apicula) + openFPGALoader (via OSS CAD Suite). No Gowin EDA
- Python 3 + pyserial on the PC

### What the GPU does in this stage
1. Video timing generator: 640x480 @ 60 Hz (simplest, widely supported)
2. TMDS/DVI encoder so the HDMI port works (video only, no audio)
3. Framebuffer in the onboard SDRAM (or block RAM for a tiny 160x120 buffer first)
4. Command interface over the USB serial link: set pixel, fill rect, draw line, blit sprite, upload frame
5. Optional: play a clip stored on the microSD card, with no PC needed

### Bandwidth reality check
The Tang Nano 20K's USB-C goes through an on-board bridge chip that shows up as a serial port (VERIFY the maximum baud rate).
Assuming roughly 3 Mbaud, that is about 300 KB/s:

| Frame format | Bytes per frame | Approx. fps at 300 KB/s |
|---|---|---|
| 320x240 RGB565 | 153,600 | ~2 |
| 160x120 8-bit palette | 19,200 | ~15 |
| Commands only (draw shapes) | tiny | limited by your code |

So: send drawing commands or small paletted frames over USB, or store the clip on the microSD card and play it locally. This is the main limit of Stage 1, and it is what Stage 2 fixes.

### Build order
1. Blink an LED (proves the toolchain works)
2. Color bars on HDMI
3. Framebuffer + draw a pixel from the PC
4. Add fill, line, rectangle commands
5. Upload a 160x120 paletted frame and animate it
6. (Optional) microSD playback

---

## Stage 2: Custom PCB, a USB 2.0 High-Speed backpack

Goal: replace the slow serial link with USB 2.0 High-Speed (about 30 MB/s usable), which allows 320x240 RGB565 at 30+ fps.

### Block diagram
```
PC --USB-C--> [USB-C connector + ESD protection]
                  |
              [FTDI FT2232H]  (USB 2.0 HS to 8-bit synchronous FIFO, 60 MHz clock)
                  |  8 data + control + 60 MHz clock
              [pin headers] ---> Tang Nano 20K (FPGA I/O)
                                  |
                                HDMI --> monitor
```

### Parts (all hand-solderable, no BGAs)
| Part | Purpose |
|---|---|
| FTDI FT2232HL (LQFP-64) | USB HS to synchronous FIFO (use Channel A in 245 sync FIFO mode) |
| 12 MHz crystal + 2 load capacitors | FT2232H clock |
| 93C46 EEPROM (optional) | Sets FT2232H mode |
| USB-C receptacle + 5.1k resistors on CC1/CC2 | Connector |
| USB ESD protection diode array | Protects the port |
| 3.3 V LDO regulator | Powers the board (or take 3.3 V from the Tang Nano) |
| Decoupling caps (0.1 uF, 10 uF), ferrite bead for the FT2232H analog supply | Required by the FT2232H datasheet |
| 2x header strips (to match the Tang Nano 20K) | Connects to the FPGA board |

Design rules to follow:
- 4-layer is nicer for USB, but 2-layer works for this short, single USB 2.0 link if you keep D+/D- as a routed pair of equal length, over a solid ground plane, with no stubs
- Follow the FT2232H datasheet reference schematic exactly for power, reset, and crystal
- Check the FPGA header I/O voltage is 3.3 V and that the FPGA can accept the FT2232H 60 MHz clock on a clock-capable pin (VERIFY on the board pinout)

### Order for Stage 2
1. Get Stage 1 fully working first
2. Buy an FT2232H breakout module (about $15-25) and wire it to the Tang Nano with jumper wires. This tests the whole FIFO design with no PCB at all
3. Only after that works, design the backpack PCB (KiCad), order from JLCPCB or PCBWay (about $5-30 for 5 boards), and solder it

---

## Stage 3 (optional, advanced)
A fully custom board with its own FPGA. Needs BGA or fine-pitch parts, DDR or SDRAM routing, and HDMI differential pairs. Not recommended until Stages 1-2 are done.

---

## What can be built next
- Verilog for the video timing, TMDS encoder, framebuffer, and command decoder (Stage 1)
- Python scripts for the PC side
- FT2232H FIFO interface in Verilog (Stage 2)
- KiCad schematic for the backpack, plus a BOM with part numbers, once Stage 1 works

## What needs you
- Buying the board and parts, flashing, and testing on real hardware
- Reading back errors so the code can be fixed (first-time hardware rarely works instantly)
- A final review of the layout in KiCad
