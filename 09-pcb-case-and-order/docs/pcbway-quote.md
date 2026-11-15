# PCBWay quote sheet: xDTGC backpack

For getting a price only. **Do not pay yet.** The open items at the bottom must be closed first.

Files: `pcb/backpack/quote/` (rebuild with `python scripts/pcb_quote_pack.py`)
- `tinygpu_backpack_gerbers.zip`: Gerbers and drill file
- `tinygpu_backpack_bom.csv`: parts list
- `tinygpu_backpack_centroid.csv`: part positions

## PCB form
| Field | Enter | Source |
|---|---|---|
| Board type | Single pieces | |
| Size | 54.1 x 25.1 mm | Board file: outline 54.04 x 25, plus line width |
| Quantity | 5 | |
| Layers | 4 | Board file |
| Material | FR-4, their standard | |
| Thickness | 1.6 mm | Board file |
| Min track / spacing | 5/5 mil | Tracks 0.15 mm (6 mil), the rule check allows spacing down to 0.127 mm (5 mil). PCBWay publishes 4/4 mil as their minimum |
| Min hole size | 0.2 mm | 122 vias at 0.20 mm drill, 0.50 mm pad. PCBWay charges extra only below 0.2 mm |
| Solder mask / silkscreen | Green / white | My choice |
| Surface finish | Immersion gold (ENIG) | My choice: flatter pads for the 0.5 mm pitch chip and USB-C. Lead-free HASL is the cheaper option to price |
| Finished copper | 1 oz outer, 1 oz inner | My choice |
| Via process | Tented | My choice |
| Impedance control | No, but ask for their 4-layer stack-up | Needed to check the USB pair |

## Assembly form
| Field | Enter |
|---|---|
| Service | Turnkey |
| Boards to assemble | Ask for two prices: 5 and 2 |
| Sides | Top side SMT. J2 and J3 are through-hole sockets fitted on the bottom |
| SMT parts | 37 parts, 18 BOM lines |
| Through-hole | J2 and J3, 40 pins. J1 also has 4 through-hole legs |
| Total parts | 39 parts, 20 BOM lines |
| Fine pitch | Yes, 0.5 mm (U1 LQFP-64, J1 USB-C) |
| BGA | No |

## Message to paste into the quote notes
> Please quote 5 boards with assembly for 5, and also assembly for 2. Please confirm: (1) vias are 0.20 mm drill with 0.50 mm pad, a 0.15 mm ring, which I read as your published minimum. Is this acceptable without extra cost? (2) every BOM line has a part number; please tell me about any you can't source. (3) The USB pair is 0.25 mm tracks with a 0.25 mm gap on the top layer over a ground plane. Please tell me its differential impedance on your standard 4-layer 1.6 mm stack-up; the target is 90 ohm. This is a quote only; the design may change before ordering.

## Rough cost estimate
These are planning figures, not PCBWay prices. PCBWay publishes no fixed assembly rate that I could find, so only their quote counts.

| Item | Estimate, USD | Basis |
|---|---|---|
| 5 bare boards | 40-90 | My estimate |
| Assembly labour, setup, stencil | 50-150 | My estimate |
| Parts for 5 boards | 80-130 | About 13 per board at database prices, plus a possible markup |
| Shipping to Thailand | 20-50 | My estimate |
| **Total, 5 assembled** | **about 190-420** | |
| **Total, 2 assembled** | **about 130-340** | Same, with parts for 2 at 30-50 and less labour |

Customs or import tax may be extra. Allow roughly 2-4 weeks, which is also an estimate.

Priced parts total USD 12.86 per board in the cached JLCPCB database (all 20 lines have a price). The FT2232HL is USD 10.61 of that, and other sellers listed roughly USD 5-11, so it moves the total most. Stock and prices change daily: check on order day.

## Must be closed before paying
1. FT2232H breakout jumper test passes (Milestone 11).
2. Measure the real Tang: row spacing, whether pins are fitted, and stack height. See `docs/verify.md`.
3. Via drill 0.20 mm with a 0.15 mm ring meets PCBWay's published limits exactly. Get their written confirmation in the quote reply.
4. Silkscreen: only 2 warnings left, J1's outline marks crossing the board edge where the plug enters. Harmless, but PCBWay may trim them.
5. USB pair impedance: about 93 ohm by hand formula. Get PCBWay's figure from item (3) of the message.
6. Sockets are 8.5 mm tall. Confirm that clears the real Tang, from item 2.
7. Check part rotations in PCBWay's preview, above all U1 pin 1, U3 pin 1, D1, D2 and the USB-C connector. The support values were checked against FT2232H datasheet v2.3 on 2026-11-02.
8. Human review of the final layout: `docs/pcb-layout-review.md`.
9. Part stock on order day, every line.
