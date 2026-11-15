# What failed and what I learned

A running log of real mistakes, found in simulation so far. Nothing here has been on hardware yet.

## FPGA design
- **Too few SDRAM refreshes.** The first plan used 2 per video line, about 62,900 per second. Typical chips need 4096 per 64 ms, or 64,000 per second. The design now uses 3 per line, and the model fails any design that goes stale.
- **Stray pixels after reset.** `visible` is high during reset, so 2 extra pixels leaked out and shifted the whole picture. Found by the framebuffer test.
- **UART stop bit cut short.** The transmitter reported ready as soon as the stop bit started, so the next start bit overwrote it. Fixed by staying busy until the stop bit ends.

- **A route failure that was only bad luck.** The build used a random seed each run, and one run failed to route at 36% LUT use. Seeds 1 to 4 all routed. Builds now use a fixed seed so they repeat.
- **Dither that made pictures worse.** The first version scored 19.3 dB blurred against 21.8 dB with no dither. The default palette spreads 8 levels evenly up to 255, so a stored level stands for about 14% more than the plain cut-off suggests. Scaling colours down first gave 42.1 dB. The tests passed either way, because hardware and Python agreed on the same wrong rule. Only measuring the picture showed it.
- **The biggest speedup was not new hardware.** Measuring showed the memory controller opening and closing a row for every word. Keeping rows open made a cube frame about 3 times faster in simulation, and added about 2% more logic.
- **A speed figure that told me nothing.** All four cube frames took exactly the same clocks, because SWAP waits for the screen. Draw time has to be measured without it.

- **Optimizing the wrong thing.** I guessed triangle setup was the slow part and spent a first patch there, for a 3.3% saving. A clock-by-clock profile then showed setup under 2% of a simple frame, with memory stalls and empty pixels taking most of the time. Going after those halved the frame.
- **An idea the numbers rejected.** Keeping the depth tile between triangles sounded obvious. It saved nothing, because a tile covers one scanline and rows change constantly, and it left depth out of memory. The comparison test caught that immediately. Removed.
- **A counter too small for a bigger number.** Raising the SDRAM power-up wait to 10,000 overflowed a 13-bit counter, so the wait became shorter. The SDRAM model reported thousands of rule errors, and I first thought the faster clock was to blame.

## Tests that were themselves wrong
- **A saved picture that proved nothing.** The first framebuffer testbench wrote the expected values to the PNG, not the design's output. It would have looked right whatever the design did. It now captures the real output pixels.
- **Tests with blind spots.** Planted bugs showed that writes outside the picture were invisible, and that no stream tested a length just over the limit. Both are now tested. `scripts/mutation_check.py` keeps this check.
- **Rare cases left to luck.** Adding triangles spread the random streams thinner, and 9 of 40 planted bugs got through 6 seeds. The cases they need now run in every stream. Twice more the check dropped: once because a later clear wiped the depth values under test, and once because random drawing covered the evidence. So the colour cases now run last, and the depth cases run after the last clear.
- **Tests that could never pass.** The first disconnect test pulled the plug more often than one frame could finish. The UART bad-stop-bit test released the line mid-frame, where a garbled byte is correct behaviour.

## Games and pictures
- **An upscaler scoring worse than doing nothing.** Plain pixel repeating first beat every smoothing method. The cause was a half-pixel shift between how the test picture was shrunk and how it was enlarged. Lining up the centres fixed it, and two tests now guard it.
- **A background that was never there.** Pong and Dodge used a dark blue of `rgb(0, 0, 60)`. Blue has 2 bits, so that rounds to black. Every test passed. I only saw it by looking at a saved picture.
- **A CPU player that could not lose.** A bot playing Pong through the keys never finished a game in 50,000 frames. The CPU paddle moved as fast as the ball almost ever did, despite my comment calling it beatable. Testing "can a player actually win" found what the rules tests could not.
- **Walking into a wall.** The maze let the player stand exactly on a wall, so the whole screen went one colour. The player now has a body width, and walls have stripes.

## HD output
- **Colour bars made the output look fast.** The bars had constant colours, so the tool simplified the TMDS encoder away and reported about 200 MHz. With real pictures it reached 51 MHz, under the 74.25 MHz needed. Splitting the encoder into four stages fixed it.
- **A clock limit that was never applied.** The rule for the FT2232H's 60 MHz clock named a port, and the tool accepted it, but the net had a different name after synthesis. So that clock was being checked against the wrong speed, and it took a failed 1080p build to show it. `scripts/report_builds.py` now checks each clock against the speed it really needs.
- **A planted bug that survived can mean the logic is not needed.** After the speed work, 138 of 148 planted bugs were caught. Four survivors could not change any result, because something else already covered them: the mark walk after reset, a jump guard, a wait in the last state, and clearing marks after a resolve. I removed that logic and those planted bugs instead of writing tests that could never fail.
- **My first test for a real gap did not test it.** Held depth is only reused if the next triangle starts on the row where the last one ended, and my first case started back at the top instead. The planted bug showed that, so the case now uses a flat-bottomed triangle followed by one starting on its last row.
- **Simulator unknowns hid a missed row.** Once the reset walk was gone, a depth clear stopping one row short went unnoticed, because an unknown mark reads as "marked". The test now fills that memory with random values at the start, as real block RAM may wake up holding anything. All 144 planted bugs are now caught with 12 seeds, which says the tests notice these bugs, not that no others exist.
- **A build seed that stopped routing.** After those removals, `top_gpu` failed to route on seed 1 even though it fits easily. `scripts/build_all.py` now tries seeds 1 to 5 and reports any seed other than 1. Each seed still repeats exactly.

- **Surviving planted bugs at 960x540.** At the bigger picture 5 of 9 planted bugs survived. Four were real test gaps: nothing read depth past x=512 where the wrong row gave a different answer, a cleared tile at the end of a row was never checked under its far half, rows 20 and 532 never met, and no wide triangle skipped 512 pixels between two colour writes. Fixed test cases now catch all of them. The fifth, and three more at 340x340, cannot change any result because held depth is dropped at each new triangle, so they were removed from the list with the reason written next to it.
- **A test that depended on time.** The bad-link stream test failed once, with "no progress for 5.0 s", only while the PC was also building FPGAs. Run alone it passes in 3 seconds. The test now allows 60 s.
- **Reading only what a triangle can reach.** Depth was read in whole tiles, including words no pixel would use. Reading only those words took the field scene from 36.2 to 32.8 ms, which is what brought it under 33.3 ms.

## Datasheet review
- **A clean rule check missed four real mistakes.** ERC and DRC passed, yet reading the FT2232H datasheet against the schematic found: the VPLL and VPHY 4.7 uF capacitors before their beads instead of after, the EEPROM pull-up on the wrong side of its series resistor (about 0.6 V for a low bit), and RESET# tied straight to 3.3 V instead of through a resistor. The AMS1117 regulator's datasheets also call for tantalum capacitors, and this board uses ceramic, so it became an AP2114H-3.3.
- **My own fix broke a net.** While making that change I relabelled the wrong +3V3 label, on VREGIN instead of RESET#. A net-by-net diff of old and new caught it. Check every schematic edit that way.
- **A helper file broke Python.** A scratch file called `inspect.py` hid Python's own module of that name. Never name a script after a standard module.

## PC software
- **Auto-detect hung forever.** It opened every serial port, and this PC has Bluetooth serial ports that can block on write. It now tries only USB ports, and writes have a timeout. A good reminder that the first real run finds what unit tests miss.

## PCB
- **Header rows swapped** in the first placement. Fixed after reading Sipeed's pin image.
- **Rule settings that reset themselves.** The project file went back to KiCad's default rules at some point, so a board that had passed showed over 500 errors. It looked like my via edit had broken it until the saved copy from before the edit failed the same way. The quote pack now runs the rule check first and stops on any error.
- **A clean rule check on a poor layout.** The first route passed DRC with USB lengths 2.5 mm apart and a 110 mm power track. DRC checks rules, not quality, so lengths are now measured separately.
- **48 vias inside pads that DRC allowed.** The plane fan-out put ground and 3.3 V vias inside chip pads, which can draw solder away from the joint. DRC does not flag that, so a separate script counts them. The fan-out now tries beside the pad first, and the board has none.
- **One net failed on every seed.** With vias out of the pads, REF failed on all eight random seeds. More seeds would never have fixed it: R1 was placed with its GND end facing the chip, so the REF pad sat behind a GND via, walled in by the USB pair. Turning R1 round fixed it and made REF a 2.3 mm direct track. When every seed fails the same way, look at placement.
- **A via joined on one side only.** The router could start a path from an already-joined pad without drawing the short stub into it, then a clean-up step deleted the via the path relied on. DRC caught it as a dangling track on VPHY. Fixed by adding the stub for whichever pad the path starts from.

## Writing things down
- **Unsourced claims in the docs.** I wrote "8.5 mm tallest part" and "no 3D model exists for 3923" without a source. Checking showed the first was a coordinate range including pins, and the second had no support at all. Both corrected.
