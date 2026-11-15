# PCB Assembly Service Guide (Stage 2)

Services that build the board and solder the parts on: JLCPCB (parts from LCSC), PCBWay, Seeed Fusion. Prices, fees and lead times change; VERIFY on each site before ordering.

## Files you upload
1. **Gerbers** (zip): the board layout, exported from KiCad
2. **BOM** (bill of materials): list of parts with the service's part numbers (for JLCPCB, the LCSC part number)
3. **CPL** (component placement list, also called pick-and-place): where and how each part is placed

`python scripts/pcb_quote_pack.py` makes the Gerbers, BOM and CPL in the service's format.

## Steps
1. Finish the design and get the FT2232H test with the breakout module and jumper wires working first
2. Choose parts the service stocks and note the LCSC part numbers (VERIFY stock the day you order)
3. Run a design-for-assembly check: part orientation, footprints, spacing, USB differential pair, decoupling capacitors, missing connections
4. You export the files, upload them, and look at the preview
5. Check the parts list the service shows, and the rotation of each part, against the board
6. Order about 5 boards (the minimum is usually 5)
7. When they arrive, solder on any through-hole parts (pin headers), then follow the test checklist in `docs/pcb-home-test.md`

## Cost and time notes (VERIFY)
- Rough total for the backpack: about $190-420 for 5 assembled boards including shipping. See `docs/pcbway-quote.md`
- "Basic" parts avoid an extra per-part fee at JLCPCB; "extended" parts cost more
- Allow 1-3 weeks including delivery to Thailand, plus possible customs fees

## Risks
- The service does not check that the design is correct. A schematic mistake gets copied onto every board
- Parts can go out of stock between design and order; one may need swapping and its footprint re-checking
- Expect a possible second revision
