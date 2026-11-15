# Testing assembled backpack boards at home (Milestone 12)

Run this on one board first. Keep the others in their bags until it passes, because a design mistake would be on every board.

No backpack has ever been built, so every expected value here comes from the design files. The net names (`+3V3`, `+1V8` and so on) are the ones in `pcb/backpack/`.

You need a multimeter. Do these in order and stop at the first different result. Tell me the step number and what you saw or measured.

## A. Before any power

1. Look at the board under good light for solder bridges on U1's fine pins, and for any part missing or crooked.
   **Expected:** clean joints, every part present, and U1's pin 1 mark where the assembly drawing shows it.
2. With the meter on continuity or resistance and nothing plugged in, test from each of these points to GND: `VBUS` at C12 pad 1, `TANG_5V` at J2 pin 1, `+3V3` at C13 pad 1, and `+1V8` at C1 pad 1.
   **Expected:** no beep on any of them. A beep means a short, so stop and do not apply power.

## B. Backpack alone, no Tang

3. Plug the backpack's USB-C into the PC, with the Tang **not** attached.
   **Expected:** nothing gets hot in the first 10 seconds. If anything does, unplug straight away.
4. Measure from GND to each rail.
   **Expected:** `VBUS` about 5 V, `+3V3` about 3.3 V (from U2, an AP2114H-3.3), `+1V8` about 1.8 V (from U1's own regulator, VERIFY against the FT2232H datasheet).
5. Open Device Manager on the PC.
   **Expected:** the FT2232H appears as two new USB devices, usually named `USB Serial Converter A` and `B` (VERIFY). If nothing appears, or it says "Unknown USB Device", send me a screenshot.
6. Check the EEPROM, which U3 provides:
   ```bash
   python sw/ft_setup.py
   ```
   **Expected:** a list of 8 settings, with no error. Then run it with `--write` as in `docs/ft2232h-test.md` step 4.

## C. With the Tang

7. Unplug everything. Take the backpack off, then load `build/top_gpu_ft.fs` into the Tang through **its own** USB port to prove the design loads, then unplug that cable.
8. Seat the backpack on the Tang's pins with the USB ends together. Check that no pin is off by one row.
   **Expected:** both rows fully seated, with pin 1 of J2 and J3 at the USB end.
9. Plug only the backpack's USB-C into the PC.
   **Expected:** the Tang's power LED comes on, and the 5 V measured at J2 pin 1 is about 4.4 to 5 V, because of the drop across D2.
10. Measure the current if you have a USB power meter. Tell me the number, since the USB power budget is still unmeasured.
11. The Tang forgets a design loaded into RAM at power-off, so this step needs the design written to its flash. Ask me first, because this flash step is untested (`docs/verify.md`).
12. Continue from step 6 of `docs/ft2232h-test.md`: selftest, spin, benchmark.

## Two USB cables at once

The Tang's schematic shows its USB 5 V going through only a fuse to `+5V` and header pin 1, with no diode. D2 on the backpack is what separates the two ports:

- **Tang's 5 V towards the backpack's port:** D2 blocks it.
- **Backpack's 5 V towards the Tang's port:** D2 lets it through if the backpack's port is more than about 0.3 V higher. That is the case to avoid.

Rules that follow from this:

- Never run a cable from the Tang's USB port to a PC or hub that is switched off. The backpack would feed 5 V into it.
- If only the Tang's USB is plugged in, the FT2232H has no power, while a loaded design drives pins into it. Plug the backpack's USB in first, or take the backpack off, before loading a design.
- Don't use two cables at once until the check below has passed.

The check, with both cables going to the same PC:

1. Plug in the backpack's USB. Then plug in the Tang's USB.
2. Measure from `VBUS` at C12 pad 1 (red probe) to `TANG_5V` at J2 pin 1 (black probe).
   **Expected:** between -0.5 V and +0.2 V, so D2 is not conducting. Above +0.2 V, unplug the Tang's cable and tell me the number.
