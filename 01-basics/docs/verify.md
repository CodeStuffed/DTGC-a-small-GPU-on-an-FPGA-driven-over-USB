# Open VERIFY items

Check each against the official schematic or datasheet before relying on it. Move to "Resolved" with the source when done.
"Resolved" means the documents agree. It does not mean the item has been tested on hardware.

## Open

### Check when the board arrives
- [ ] Board version number, printed on the bottom of the board (decides which schematic in `docs/board/` applies)
- [ ] HDMI connector size by eye. The schematic symbol and pin numbering indicate Type A (full size)
- [ ] Whether `openFPGALoader --detect` sees the board on Windows without changing a USB driver. A driver tool is not on the shopping list, so explain why before asking for one
- [ ] Flashing to external flash with `openFPGALoader -f -b tangnano20k`. openFPGALoader's board table and the Apicula Makefile support it; its Gowin page does not list this board for `-f`. Test in Milestone 1
- [ ] BL616 firmware version. The Sipeed wiki links a 4x baud rate error to old firmware
- [ ] Maximum reliable UART baud rate. No Sipeed document states one, so measure it in Milestone 4 (design-plan's 3 Mbaud is still an assumption)

### Check before Milestone 2 (HDMI)
- [ ] TMDS resistors R32-R39 differ by board version: 49.9R to +3V3 on 3921, 499R to GND on 3923. Same pins, different circuit
- [ ] Which FPGA bank pins 33-40 are in. Apicula issue #534 reports a TLVDS output in bank 0 freezing a design on the Tang Primer 20K (different board)
- [ ] rPLL settings for the 25.2 MHz pixel clock. 27 x 14 / 3 = 126 MHz, then divide by 5, is from memory of the formula: check Gowin UG286, then confirm on hardware. Use the GW2A device value, not the `GW1N-9C` in Apicula's `pll480.v`
- [ ] Open toolchain bugs: Apicula #514 (adders computing wrong results on the Tang Nano 20K) and #541 (results change with placement seed on GW2A-18C). Simulation will not catch these. Fallback for #514 is `synth_gowin -noalu`. Add on-hardware self-checks

### Check before Milestone 4 (UART)
- [ ] The Tang's USB id, so auto-detect can recognise it. Until then every USB serial device gets a HELLO packet, so use `--serial PORT` if other USB serial devices are attached
- [ ] Round-trip delay on the real USB link. At most 1024 bytes wait for a reply, so a long delay limits speed whatever the baud rate (`docs/protocol.md`). Measure with `selftest` ping timing, then reconsider the window for the FT2232H link
- [ ] 3 Mbaud in `rtl/top_gpu.v` and `sw/dtgc` is an assumption. Change `PHASE_INC` and `--baud` together once the real maximum is measured
- [ ] One third-party project reports true LVDS taking over banks 4 and 5 and moved its UART to pins 71/72. The schematic has the BL616 UART on 69/70. Check the bank of these pins, and test UART and HDMI together

### Only if used, or later
- [ ] microSD pins: the FPGA sheet and the peripherals sheet disagree on the 3920 and 3923 schematics. Continuity test before use (see `docs/board/pins-needed.md`)
- [ ] SDRAM internal port names and locations in `constraints/framebuffer.cst`. They come from one third-party project (ArthurHeymans tang_20k_spi_flash), since the SDRAM is inside the FPGA package and not on the schematics. They pass the build; only hardware can confirm them. Another project reports an SDRAM clock fault with the open flow (Milestone 3)
- [ ] The exact SDRAM chip and its datasheet. `rtl/sdram_ctrl.v` and `sim/sdram_model.v` assume typical values: CAS latency 2 allowed at 25.2 MHz, 4096 refreshes per 64 ms, tRCD and tRP 20 ns, tRC 63 ns, tAC 6 ns. The design uses 3 refreshes per line, a longest 4096-refresh span of 43.4 ms in simulation
- [ ] SDRAM pin timing is not checked by nextpnr, and the inverted SDRAM clock uses general routing (build warning). If the picture is corrupted on hardware, look here first
- [ ] Whether holding S1 or S2 at power-up changes how the FPGA boots (they are also MODE0 and MODE1)
- [ ] FPGA maximum input voltage. Assume not 5 V tolerant until checked in the Gowin datasheet (Stage 2)
- [ ] FT2232H: clock-capable FPGA pin for the 60 MHz FIFO clock. Pin 77 is chosen (GCLKT_1 in Apicula's chip database). SPI pin names changed on 3923, so check it there too

### Faster core clock (added 2026-11-01)
- [ ] The HD builds now run the core and SDRAM at 46.41 and 48 MHz. Half a clock is about 10.5 ns, against about 6 ns of read access time assumed in `sim/sdram_model.v`. Check T_AC, tRAS, tRC, tRP, tRCD and tWR against the SDRAM section of Gowin's GW2AR data (DS226). If reads fail on the board, use the `gpu_hd_safe` build at 26.52 MHz
- [ ] Hard multipliers: the HD builds use 2 MULT18X18 through Apicula. We have not seen its multiplier bitstream on a real GW2A chip. If triangles draw wrongly and `gpu_hd_nodsp` draws correctly, this is the cause

### Windows device (added 2026-11-01)
- [ ] `build/device/dtgc_device.exe` has only been run without admin rights, where Windows refused it (`0x80070005`). See `docs/windows-device.md`
- [ ] Whether FTDI's driver shows the name written by `sw/ft_setup.py`. Needs the real FT2232H

### Project
- [ ] Check name availability for DTGC and xDTGC (trademarks, domain, GitHub) before publishing

### Check before high resolution output
- [ ] 1080p30 and 720p60: `build/top_bars_hd.fs` builds and its timing passes in simulation, but the 371.25 MHz serial clock and 742.5 Mbit/s lanes are untested. nextpnr does not check them against the chip's limits. Check PLL and IO limits in Gowin's GW2A datasheet and UG286
- [ ] Whether the monitor accepts 1080p at 30 Hz
- [ ] 1080p at 50 Hz reduced blanking: 576 MHz serial, 1.152 Gb/s lanes, VCO 1152 MHz. Below the figures found so far (VCO 1250 MHz, 1.25 Gb/s), but check Gowin DS226. Then whether the monitor accepts it. Test: `docs/first-hardware.md`, section G
- [ ] 1080p60 (1485 Mbit/s lanes) is over the figures found, so it is not built. 1440p30 (1188 Mbit/s lanes) is also close to them, and has no picture design. A clean build would prove nothing here

### Check before ordering the backpack PCB
- [ ] FT2232H breakout jumper test passes (Milestone 11). This is a hard requirement
- [ ] FIFO pin map works on hardware. `build/top_gpu_ft.fs` builds with `gowin_pack --sspi_as_gpio --cpu_as_gpio` on data pins 52-56. That proves the tools accept it, not that the pins are free at run time
- [ ] FPGA pin timing on the FT2232H bus. nextpnr checks inside the chip only (ft_clk reaches 88.65 MHz against the 60 MHz needed), never the pins. Budget from those numbers: FPGA clock pin to data out within 8.67 ns, and clock pin to capture within 9.5 ns minus setup. Neither is measured. If bytes are wrong on hardware, look here first
- [ ] That the FT2232H's CLKOUT only runs after software starts FIFO mode (forum evidence). The design is safe either way in simulation, since its pins power up released
- [ ] FT2232H start-up sequence in `Ft2232hTransport`: mode 0x00, wait, mode 0x40, latency 2 ms, 64 KB transfers, RTS/CTS flow control, from AN_130 and a Numato example. One forum report describes a chip lockup until replug in some setting
- [ ] Both channels set to 245 FIFO in the EEPROM (`sw/ft_setup.py`). The `ftd2xx` field names come from its source on GitHub (`IFAIsFifo7` and so on), and the code has only run against a stand-in. Also check the package still loads on Python 3.14, since its newest release is from 2024
- [ ] Which breakout module to buy, and that it has an EEPROM
- [ ] Parser timeout against real USB pauses. A half-received packet is dropped after 65535 clocks of silence, 2.6 ms at 25.2 MHz. If Windows pauses mid-packet for longer, the packet is lost and has to be sent again. Count retries in the benchmark
- [ ] FIFO pins are shared with onboard parts. Pins 54-56 go to I2S audio, 51 PA_EN, 52/53 DCD, 48/49 LCD_DE and LCD_BL, 27-31 LCD. Check nothing onboard fights the bus at 60 MHz
- [ ] Real row spacing on your board: 20.32 mm comes from the 3921 3D model, the only one I have found. Measure with calipers: pin 1 to pin 1 across the two rows
- [ ] Whether the Tang comes with its pins soldered, and which way they point
- [ ] Stack height. Part heights are not measured yet: the 3921 model spans z -9.4 to +8.5 mm including pins, which does not separate parts from pins. Measure the tallest part on the real board, then check the sockets give enough clearance and an HDMI plug fits under the backpack's overhang
- [ ] The backpack covers buttons S1, S2 and UPDATE and the LEDs. Decide whether that is acceptable
- [ ] Two USB cables at once. Tang schematic 3921 p.7: USB VBUS goes through fuse FU1 (6 V 2 A) to `+5V`, with no diode, so D2 on the backpack is the only separation. Measure it: `docs/pcb-home-test.md`, "Two USB cables at once". Board versions 3850, 3920 and 3923 also list FU1; I only looked at the drawing for 3921, so check yours
- [ ] Flashing needs the Tang's own USB port. D2 leaves the FT2232H unpowered in that case while the FPGA can drive its pins. FT2232H datasheet v2.3 says nothing about driving pins while unpowered, so this stays open: power the backpack first or take it off
- [ ] USB power budget against the 500 mA fuse: measure the Tang and backpack together
- [ ] 5 V drop through D2 (B5819W, up to 0.6 V at 1 A) against what the Tang's regulators need
- [ ] USB pair impedance from the fab's own calculator. Width 0.25 mm, gap 0.25 mm comes to about 93 ohm (target 90) by hand formula, using PCBWay's published 4-layer stack (prepreg about 0.18 mm, Dk 4.74). The formula ignores the ground fill beside the pair, and the pair narrows to 0.2 mm near J1
- [ ] Via and hole limits with PCBWay directly. 0.20 mm drill and 0.15 mm ring pass their published limits, with the ring exactly at the limit. The quote message asks them to confirm
- [ ] Ferrite beads FB1 and FB2 are 600 ohm at 100 MHz. The FT2232H datasheet shows beads but gives no value, so this value is a common choice, not a sourced one. Check FTDI's reference schematics if available
- [ ] Crystal Y1 tolerance against the datasheet's 12 MHz +/-30 ppm. Its load value (20 pF) with C14 and C15 is also unconfirmed against the crystal's own datasheet
- [ ] AP2114H-3.3 input stays under its limit: VIN 2.5 to 6 V recommended, 6.5 V absolute. Fed from USB 5 V, so only a faulty charger would matter
- [ ] J2/J3 sockets are 8.5 mm tall (Kinghelm KH-2.54FH-1X20P-H8.5, C2905423). Check they clear the Tang's tallest part and its pins once you can measure the board
- [ ] Part stock and numbers on order day. Cached JLC data only so far: FT2232HL C27882, 93LC56B C6164, MF-NSMF050-2 C75464, B5819W C8598, CL10A335KP8NNNC C51412, KH-2.54FH-1X20P-H8.5 C2905423, AP2114H-3.3TRG1 C150716, 0402WGF1001TCE C11702

### Later
- [ ] FT601 (USB 3.0) option: everything about it

## Resolved
- [x] FT2232H FIFO timing: period 16.67 ns, clock to output 1 to 7.15 ns, write setup 8 ns, hold 0 ns. These match `sim/ft2232h_model.v`. Source: FT2232H datasheet v2.3, seller's copy on Octopart, since FTDI's site refused the download. The older v2.08 says 11 ns setup; v2.3 is used. Pin timing on the real FPGA is still open above
- [x] FT2232H support parts: 3.3 uF on VREGOUT, 12k 1% on REF, TEST to GND, SIWU to VCCIO through R8, 7 x 100 nF, EEPROM 93LC56B pins 6 and 7 not connected. Source: datasheet v2.3
- [x] Schematic faults found by that check and fixed on 2026-11-02: C17 and C18 moved after their beads, R6 moved to the EEDO side of the EEPROM link, RESET# through new R9 1k, regulator changed to AP2114H-3.3 because the AMS1117 datasheets call for tantalum capacitors. Source: datasheet v2.3 and the AP2114 datasheet. See `docs/lessons.md`
- [x] FT2232H default USB ID 0403:6010. Source: datasheet v2.3
- [x] PCBWay's published limits: drill 0.15 to 6.0 mm (extra charge only below 0.2 mm), annular ring minimum 0.15 mm, track and space minimum 4/4 mil. The board uses 0.20 mm, 0.15 mm and about 5/6 mil. Source: PCBWay capabilities page. The final word is theirs when they review the files
- [x] Tang Nano 20K physical pin order: pin 1 of J5 and J6 both at the USB end, J5 on the right with USB at the top. Source: Sipeed `tang_nano_20k_pinlabel.png`
- [x] Header row spacing 20.32 mm, pitch 2.54 mm, 1.0 mm holes. Source: Sipeed 3D model v3921 (board version 3921 only; see the caliper check above)
Pins below come from the schematics in `docs/board/`, and Sipeed's example constraint files match. Full table and sources: `docs/board/pins-needed.md`.
- [x] Open-source support for the Tang Nano 20K: the board is listed by Apicula and openFPGALoader (`tangnano20k`), with build targets for DVI, OSER10, CLKDIV and BSRAM. Upstream's hardware test list does not include these, so "supported" is not "tested". Sources: Apicula README and `examples/Makefile`, openFPGALoader board table
- [x] Place-and-route tool name: `nextpnr-himbaechel`, not `nextpnr-gowin`, which is not in OSS CAD Suite 2026-10-31. Sources: installed suite, Apicula Makefile
- [x] TMDS pins (+/-): clock 33/34, lane 0 35/36, lane 1 37/38, lane 2 39/40. Leave LCD connector J2 empty, since it shares these pins. Do not drive pins 25 or 26 (CEC and hot-plug detect)
- [x] Onboard clock: 27 MHz on pin 4
- [x] LEDs: pins 15-20, active low. Sipeed's `hdmi.cst` numbers them in reverse; the pins still match
- [x] Buttons: S1 pin 88, S2 pin 87, active high with 1K pull-down
- [x] UART: FPGA TX pin 69 (to BL616 RX), FPGA RX pin 70 (from BL616 TX)
- [x] Header I/O voltage: 3.3 V on banks 0, 1, 3, 5, 6. J5 pin 1 is +5 V. Source: Sipeed datasheet p.7

## Windows detection
- Does an indirect display driver show on Task Manager's Performance tab as a GPU? Unconfirmed. Check on a test PC.
- Microsoft's current driver signing rules and certificate cost. Check Microsoft's driver signing documentation.
- Which FT2232H EEPROM tool is free and open source, and whether it sets the Device Manager name. Check the tool's documentation and test on the breakout module.

## Open SDRAM rows
- `rtl/sdram_ctrl.v` now keeps rows open, so it relies on more chip timing: minimum and maximum row-open time, the gap between opening two banks, and how soon a write may follow a read. The model uses typical values. Check them against the SDRAM datasheet once the exact chip is known. Refresh closes every row about every 32 us, which should stay far under any maximum.

## Burst reads
- `rtl/sdram_ctrl.v` now reads 8 depth words on consecutive clocks, then waits 3 clocks before the next command. Line reads already use consecutive reads. Check the gap against the SDRAM datasheet once the exact chip is known. A burst can also delay a line request by up to about 8 clocks; the simulation checks that scan-out does not run out of pixels, and hardware must confirm it.
