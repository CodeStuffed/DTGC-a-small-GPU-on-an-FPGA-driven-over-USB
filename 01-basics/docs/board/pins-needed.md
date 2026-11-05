# Tang Nano 20K: pins we need

FPGA: GW2AR-LV18QN88C8/I7 (88-pin package). The schematic is the authority. Vendor `.cst` files (pin constraint files) are supporting evidence only.

**Status: nothing here has been tested on hardware.** These values come from documents only.

## Which schematic applies
Sipeed prints the board version on the bottom of the board. **VERIFY: read that number when the board arrives.** Every pin in the main table is the same in all four schematics, so buying and the first constraints do not depend on it.

| File | Title block says | Date | FPGA sheet |
|---|---|---|---|
| `Tang_Nano_20K_3923_Schematics.pdf` | 3923, Rev 1.3 | 2025-08-28 | PDF p.1 |
| `Tang_Nano_20K_3921_Schematics.pdf` | 3921, Rev 1.30 | 2023-07-11 | PDF p.2 |
| `Tang_Nano_20K_3920_Schematic.pdf` | 3920 | not read | PDF p.1 |
| `Tang_Nano_20K_3850_Schematics.pdf` | **3921**, Rev 1.22 (see disagreement 1) | 2023-06-13 | PDF p.2 |

Also saved: `Sipeed_Tang_nano_20K_Datasheet_V1.3-en_US.pdf`, dated June 2023, so it predates version 3923. All files came from `dl.sipeed.com/fileList/TANG/Nano_20K/`.

## Sheet page numbers
| Sheet | 3923 PDF page | 3921 PDF page |
|---|---|---|
| FPGA (main) | 1 | 2 |
| Display and HDMI | 4 | 3 |
| Peripherals (LEDs, buttons, SD, MS5351) | 6 | 5 |
| Power | 2 | 6 |
| USB and BL616 | 3 | 7 |

## Main table
| Function | FPGA pin | Direction from FPGA | Notes | Source |
|---|---|---|---|---|
| 27 MHz clock | 4 | In | U3 `OSC_27MHz` through R10 22R. Pin function `IOL7A/LPLL1_T_in` | 3923 p.1, 3921 p.2 |
| LED0 | 15 | Out | **Active low**: drive 0 to light | 3923 p.1 and p.6, 3921 p.2 and p.5 |
| LED1 | 16 | Out | Active low | same |
| LED2 | 17 | Out | Active low | same |
| LED3 | 18 | Out | Active low | same |
| LED4 | 19 | Out | Active low | same |
| LED5 | 20 | Out | Active low | same |
| Button S1 (`KEY1`) | 88 | In | **Active high**: pressed reads 1. 1K pull-down, 330R to 3V3. Also `MODE0` | same |
| Button S2 (`KEY2`) | 87 | In | Active high, as S1. Also `MODE1` | same |
| TMDS clock + / - | 33 / 34 | Out | `DVI_TXC_P` / `_N` | 3923 p.1, 3921 p.2 |
| TMDS lane 0 + / - | 35 / 36 | Out | `DVI_TX0_P` / `_N` | same |
| TMDS lane 1 + / - | 37 / 38 | Out | `DVI_TX1_P` / `_N` | same |
| TMDS lane 2 + / - | 39 / 40 | Out | `DVI_TX2_P` / `_N` | same |
| UART TX | 69 | **Out** (to BL616) | `PIN69_SYS_TX` goes to `BL616_UART_RX` | 3923 p.1, 3921 p.2 |
| UART RX | 70 | **In** (from BL616) | `PIN70_SYS_RX` comes from `BL616_UART_TX` | same |

Terms:
- **TMDS**: the differential signalling that DVI and HDMI use for video.
- **Active low**: the signal is "on" when the wire is at 0 V.

## Connector and voltage
| Item | Value | Source |
|---|---|---|
| HDMI connector | Type A (full size). Symbol `DVI_TX_A` with Type A pin numbering (D2+ on 1, HPD on 19). In the pinout photo it is about 15 mm wide on the 22.55 mm board, which fits Type A. **VERIFY by eye on arrival** | 3923 p.4, 3921 p.3, datasheet p.7 |
| TMDS bank voltage | Bank 4 and bank 5 each have their own `ME6211C33` regulator (U4, U11). Sipeed's `hdmi.cst` states `BANK_VCCIO=3.3` | 3923 p.2, 3921 p.6 |
| Header I/O voltage | 3.3 V on banks 0, 1, 3, 5 and 6 | Datasheet p.7 (pinout legend) |
| Header power pins | J5 pin 1 is **+5 V**. J5 pin 16 and J6 pin 19 are 3V3 | 3923 p.1, 3921 p.2 |

## microSD (only for optional Milestone 6)
Use the FPGA sheet values. See disagreement 3.

| Signal | Pin |
|---|---|
| D2 | 80 |
| D3 | 81 |
| CMD | 82 |
| CLK | 83 |
| D0 | 84 |
| D1 | 85 |

## SDRAM (only for optional Milestone 6)
The SDRAM is inside the FPGA package (datasheet p.1), so these schematics do not show its pins. **VERIFY** the internal port names in the Gowin GW2AR documents in Sipeed's `6_Chip_manual` folder.

## Agreement with vendor constraint files
- Sipeed `hdmi/src/hdmi.cst` matches the schematic: clock 4, TMDS 33-40, LEDs 15-20, buttons 87 and 88.
- Sipeed `uart/src/top.cst` matches the schematic: `uart_tx` 69, `uart_rx` 70, clock 4.
- Naming trap: `hdmi.cst` numbers its LEDs backwards. `O_led[0]` is pin 19 (schematic LED4) and `O_led[4]` is pin 15 (LED0). `running` is pin 20 (LED5). The pins agree and only the names differ. We use the schematic numbering.
- Sipeed wiki MS5351 pins (10, 11, 13) match the schematic.

## Disagreements found
1. **File name and title differ.** The file named `3850` has the title `Tang_Nano_20K_3921_Schematics`, Rev 1.22. Do not treat it as confirmed 3850 documentation.
2. **The TMDS resistors changed between versions (R32-R39).** The pin numbers stay the same, but the circuit does not. In 3921 they are 49.9R, with D3 on the path to +3V3. In 3923 they are 499R/1% to GND. The 3850 and 3920 files also list 49.9R. **VERIFY** whether this affects the TMDS output settings, and check the Gowin I/O guide before Milestone 2 if the board is 3923.
3. **SD pins conflict inside the 3920 and 3923 schematics.** The FPGA sheet gives the table above. The 3923 peripherals sheet (p.6) labels D2=86, D3=85, CMD=84, CLK=83, D0=83, D1=82. That has two signals on pin 83, and pin 86 is `SPI_DIR` on the FPGA sheet, so those labels look like errors. Datasheet p.7 agrees with the FPGA sheet for the two SD pins it shows (D1=85, D2=80). **VERIFY with a continuity test before using SD.**
4. **LED labels on the display sheet differ in older files.** The 3850, 3920 and 3921 files use `PIN73`-`PIN76_SYS_LEDx` labels on the display sheet. The FPGA and peripherals sheets, the 3923 file, the datasheet and `hdmi.cst` all use 15-18. We use 15-18.
5. **Pins 25 and 26 are swapped in the 3920 file.** Its FPGA sheet shows `PIN26_LCD_VS` on pin 25 and `PIN25_LCD_HS` on pin 26. The other files show 25=HS and 26=VS. This only matters if we read hot-plug detect or drive CEC, below.
6. **SPI pin names changed.** Datasheet V1.3 and 3921 say pin 75=`HSPI_DIR`, 76=`HSPI_DAT`, 86=`HSPI_CSN`. 3923 says 75=`SPI_MISO`, 76=`SPI_MOSI`, 86=`SPI_DIR`. We do not need these pins in Stage 1. They connect to the BL616, which matters when choosing Stage 2 pins.

## Shared pins to remember
- **The TMDS pins are also the LCD connector pins.** Pins 33-40 go to J2 (the 40-pin LCD connector) as well as HDMI. Leave J2 empty while using HDMI.
- **LEDs 0-3 (pins 15-18) also go to J2** pins 37-40.
- **LEDs 2-5 (pins 17-20) are labelled as joystick pins** on J6.
- **Pin 26 also sees HDMI hot-plug detect** through R47 2.2K (3923 p.4, 3921 p.3). Hot-plug detect is the monitor's "I am connected" signal.
- **Pin 25 connects to HDMI CEC** through R51 100R (3923 p.4). Leave pins 25 and 26 unused as outputs on the HDMI build.
- **Buttons 87 and 88 are also FPGA `MODE` pins.** **VERIFY** in the GW2AR datasheet whether holding a button during power-up changes how the FPGA boots.

## Open VERIFY items
| Item | What to check |
|---|---|
| Board version | Number printed on the bottom of the board |
| HDMI connector size | Look at the board when it arrives |
| **Maximum reliable UART baud rate** | No Sipeed document read here states one. Test it on the board in Milestone 4. One third-party project runs this link at 3,000,000 baud, but that is not a Sipeed specification |
| BL616 firmware version | The Sipeed wiki says a wrong baud rate (actual rate 4x the set rate) or garbled output is fixed by updating the firmware. Check before trusting any baud test |
| TMDS resistor difference | Disagreement 2 |
| SD pins | Disagreement 3 |
| Boot effect of buttons | Gowin GW2AR datasheet, `MODE` pins |
| Maximum input voltage on I/O | Gowin GW2AR datasheet. Assume headers are not 5 V tolerant until checked |
| SDRAM ports | Gowin GW2AR documents in `6_Chip_manual` |
| MS5351 power-up frequencies | Not stated in the documents read. Not needed if we use the 27 MHz clock on pin 4 |

## How these were read
No PDF tools were installed and none were added. A small script drew the schematic linework to images, and the sheets were read from those.
- Main table: read on the 3921 and 3923 sheets.
- 3850 and 3920: only the FPGA sheet's lower section (TMDS pins, clock) was read by eye. The other values are confirmed by matching label text, not by tracing wires.
- Datasheet: the pinout is a picture on p.7.
