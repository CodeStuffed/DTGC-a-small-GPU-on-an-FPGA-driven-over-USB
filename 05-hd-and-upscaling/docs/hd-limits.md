# HD output: what is known and what is not

Nothing here has been run on hardware.

## 1080p at 60 Hz on the Tang Nano 20K
Standard 1080p60 needs a 742.5 MHz serial clock (1.485 Gb/s per HDMI lane). The FPGA datasheet figures found so far point to about
625 MHz at most (1.25 Gb/s). VERIFY against Gowin DS226, Table "PLL Switching Characteristic". So 1080p60 is over the chip's
listed limits, and I do not provide a build for it. A true 1080p picture also does not fit: two buffers and depth need 8.3 MB, and the SDRAM has 8 MB.

| Mode | Picture | Serial clock | Status |
|---|---|---|---|
| 1280x720 60 Hz | 680x680 (x2) | 371.25 MHz | passes simulation, bit-exact with the Python scaler. FPGA build passes timing |
| 1920x1080 30 Hz | 960x540 (x2, edge-directed) | 371.25 MHz | passes simulation, every screen pixel matches the Python scaler. FPGA build passes timing. Field scene measured at 30.5 fps in simulation ([architecture-1080p30.md](architecture-1080p30.md)). Monitor acceptance VERIFY |
| 1920x1080 50 Hz reduced blanking | 1020x1020 (x3) | 576 MHz | passes simulation, bit-exact with the Python scaler. FPGA build passes timing. Monitor acceptance VERIFY |
| 1920x1080 60 Hz | none | 742.5 MHz | over the datasheet figures, not built |

Build figures are in [resources.md](resources.md). The output pins are not covered by those figures: nextpnr does not check them against
the 1.152 Gb/s the 1080p mode needs. Only a real monitor can answer that, so try the colour-bar ladder first (`docs/first-hardware.md`, section G).


## The fix that made HD builds pass
`clk_video` first reached only 51.40 MHz, because the TMDS encoder did all its work in one clock. It now takes four. In a one-off run, 2,000,000
random inputs gave the same output words as the old encoder, four clocks later instead of one.
