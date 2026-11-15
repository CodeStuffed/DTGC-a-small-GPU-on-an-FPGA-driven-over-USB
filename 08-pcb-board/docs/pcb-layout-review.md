# Backpack layout review

Board: `pcb/backpack/tinygpu_backpack.kicad_pcb`. 54.04 x 25 mm outline, 39 parts, 4 layers: F.Cu signals, In1.Cu ground plane, In2.Cu +3V3 plane, B.Cu signals. F.Cu and B.Cu are also filled with ground.

KiCad's rule check (DRC) reports 0 errors and 0 unconnected nets (2026-11-02, after the datasheet fixes and a re-route). DRC checks spacing and connections. It does not check signal quality, and the board has never been built.

Rebuild it from the schematic:

```bash
kicad-cli sch export netlist --format kicadsexpr -o bp.net pcb/backpack/tinygpu_backpack.kicad_sch
"<KiCad>/bin/python.exe" scripts/pcb_place.py bp.net pcb/backpack/tinygpu_backpack.kicad_pcb
"<KiCad>/bin/python.exe" scripts/pcb_route.py pcb/backpack/tinygpu_backpack.kicad_pcb
```

These scripts replace the board file, so any hand edits in KiCad are lost if you re-run them.

## How it fits the Tang Nano 20K
- Sockets J2 and J3 sit under the backpack and plug onto the Tang's pins. J2 = Tang J5, J3 = Tang J6.
- Seen from above with USB on the left, J2 is the top row and J3 the bottom row. Pin 1 of both is at the USB end. Source: Sipeed pin label image.
- Row spacing is 20.32 mm, measured from Sipeed's 3D model v3921. Pitch is 2.54 mm.
- The backpack is 25 mm wide, 2.45 mm wider than the Tang, so the socket pads clear the board edge.

## What was measured on this layout
| Item | Result |
|---|---|
| USB D+ total copper | 17.53 mm, 2 vias |
| USB D- total copper | 17.68 mm, 2 vias |
| FIFO clock | 24.76 mm, 2 vias |
| FIFO data D0-D7 | 20.15 mm to 61.39 mm (D3 longest, 4 vias) |
| REF (U1 pin 6 to R1) | 2.34 mm, no vias |
| Crystal OSCI / OSCO | 11.73 / 10.89 mm, 2 vias each |
| Vias in total | 122, none inside a pad |

The USB totals include short branches to the ESD diode and the connector's second row. The main run of each line is a straight 13.7 mm.

## Human review checklist
Open the board in KiCad and look at each item.
1. **USB pair:** D+ and D- run side by side from J1, between D1's pads, to U1 pins 7 and 8, without changing layer on the main run.
2. **Power:** follow VBUS_IN from J1 to F1, then VBUS to D2, D1 and U2, then TANG_5V from D2 to J2 pin 1. The VBUS track should look wide and unbroken.
3. **Decoupling:** each small capacitor sits next to the U1 power pin named in `scripts/pcb_place.py`.
4. **Crystal:** Y1, C14 and C15 are close to U1 pins 2 and 3. Each crystal line is about 11 mm with 2 vias. Shorter is better; look whether Y1 can move closer.
5. **Datasheet fixes (2026-11-02):** C17 sits after FB1 on VPLL and C18 after FB2 on VPHY. R6 pulls up the EEDO side of the EEPROM link. R9 (1k) feeds RESET# from 3.3 V. U2 is now an AP2114H-3.3, same SOT-223 pin order (1 GND, 2 VOUT, 3 VIN).
6. **REF:** R1 (12k) sits right beside U1 pin 6 with a short direct track.

## Known weak spots
- **Data lengths differ by up to 41 mm**, because D3 goes to a pin at the far end of J2. At about 6-7 ps per mm that is roughly 0.3 ns of skew, small against the 16.67 ns clock period (VERIFY on hardware).
- **USB impedance is estimated, not controlled.** The pair is 0.25 mm wide with a 0.25 mm gap, 0.2 mm wide by J1. By hand formula on PCBWay's published stack that is about 93 ohm against a 90 ohm target. Get the fab's own figure before ordering (VERIFY).
- **Routing was done by a script.** The USB pair is laid out by hand in that script; the other nets come from an automatic maze router, so some paths are longer than a person would draw.
- **Vias are 0.5 mm with a 0.2 mm hole, clearance is 0.127 mm.** That meets PCBWay's published minimums (0.15 mm ring) exactly; get their confirmation.
- **Remaining DRC warnings (2):** J1's outline marks cross the board edge where the plug enters. 39 schematic comparison notes are an empty Description field on each footprint, with no effect on connections.
