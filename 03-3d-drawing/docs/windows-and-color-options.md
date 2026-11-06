# Windows detection, colour and memory decisions

## Showing up in Windows

| Where | What it takes | Status |
|---|---|---|
| Task Manager, Processes tab | Run our app under the name DTGC. No driver needed | Can do now |
| Device Manager, with our name | Set the name in the backpack's EEPROM (a small settings chip, U3). The Tang Nano's own USB chip keeps its own name | Planned with the backpack. FT2232H EEPROM tool is a VERIFY item |
| Programs using DTGC through OpenGL | A per-program `opengl32.dll` that sends drawing to the GPU. No Windows driver or signing | Planned, Milestone 10 |
| Task Manager, Performance tab, as a GPU | A Windows display driver (WDDM, Microsoft's display driver model) | Not started. Needs approval first, see below |

### What a real display driver would involve
- **Effort:** this is by far the largest software job in the project, larger than the app and the OpenGL layer together. Windows expects a driver to work in ways this GPU has no hardware for, so much of it would be emulated on the PC.
- **Signing:** normal Windows 11 will not load an unsigned kernel driver. Public release needs Microsoft's signing process and a paid company-level certificate (exact rules and price: VERIFY on Microsoft's site). On your own PC only, Windows test mode can load it, and shows a watermark on the desktop.
- **Risk:** a bug in a kernel driver can crash all of Windows with a blue screen, which is a real risk while developing it. Test it on a spare PC or a virtual machine.
- **Payoff:** games still would not run on it, because modern DirectX and Vulkan are out of scope. It would mainly add the Task Manager entry and a Windows screen.
- **A lighter route to check:** Windows has a user-mode "indirect display" driver type that could make DTGC a real extra monitor. It is much safer, as a bug crashes less. Whether it shows on the Performance tab as a GPU is unconfirmed: VERIFY on a test PC before relying on it.

**Decision:** build the app and OpenGL layer first. Start a driver only with explicit approval.

## A colour chip on the backpack: no
The HDMI signal goes straight from the FPGA to the Tang Nano's HDMI connector. The backpack does not touch it, so a chip there cannot change the colours on screen. The limit is inside the FPGA design: each pixel is stored in 8 bits. Fixing that costs no extra parts.

Measured on a slow gradient with `scripts/color_compare.py`, against an ideal 24-bit picture. "Blurred" averages 4 x 4 blocks, roughly what the eye does from a distance. These figures come from Python, and the dithered output matches the Verilog in simulation.

| Method | PSNR | Blurred PSNR | Status |
|---|---|---|---|
| 8-bit | 21.8 dB | 21.8 dB | Built |
| 8-bit with dither | 20.5 dB | 42.1 dB | Built, passes in simulation |
| 16-bit (RGB565) | 39.4 dB | 40.3 dB | Arithmetic only, not built |

Dithered pixels look grainy up close, and scaling up (Milestone 8) can make that more visible.

**Next colour steps, in order:**
1. Pick the best 256 colours for each picture with a PC tool, using the existing palette command.
2. A 16-bit framebuffer, after Milestone 7 speeds up memory. Scan-out would read twice the data per line, so it must be tested against the rule that the screen never runs out of pixels.

## Laptop RAM: no
- **A laptop memory stick on the backpack (SO-DIMM):** it needs far more pins than the Tang Nano's headers have, and much faster and more delicate signals than headers can carry. It also needs a special low-voltage memory interface. Whether the open-source tools support that on this chip is unconfirmed (VERIFY), and the pin count rules it out anyway.
- **The laptop's own memory over USB:** already used. `sw/dtgc/assets.py` keeps textures on the PC and sends them when needed. USB is far too slow to use as the GPU's live memory.
- **Modular:** the Tang Nano plugs into the backpack's sockets, so a board can be swapped without soldering. That is the modular part, and it needs no new design.

## External RAM: not now
The Tang Nano's chip has 8 MB of memory built in. Even a 16-bit 1080p picture would need about 4 MB per buffer, so size is not the limit. The limit is speed, and the free fix is to run the memory on a faster clock in Milestone 7. External RAM would also use many of the pins the USB link needs, and the backpack's connection through the headers is a poor path for fast memory.

**Decision:** add none. Look again only if a real program runs out of texture space.

## Two or more GPUs
Idea: several boards, one connected to the monitor, the others helping and showing up as GPUs. Nothing here is built.

- **BIOS:** no. A BIOS lists graphics cards on PCIe, and this project is USB only. At most it might list a USB device, depending on the PC.
- **Task Manager:** needs the same Windows display driver described above, for each board.
- **The PC seeing several boards:** easy. Each board has its own USB link, and an app can talk to each one.
- **Two monitors:** each Tang Nano has its own HDMI, so this needs only app changes.
- **A second board helping draw:** the finished pixels must reach the board driving the monitor, and the GPU has no way to send pixels back yet. A 340 x 340 picture is 115,600 bytes.
  - Through the PC on the assumed 0.3 MB/s serial link: about 385 ms per picture, far too slow for full frames. Sending a small part, or a result computed in the background, could still be useful.
  - Direct wires between the boards: an 8-bit link at 25.2 MHz could carry at most 25 MB/s, about 5 ms per picture. It would need spare pins, and the backpack already uses many. Pins and signal quality: VERIFY.

**Decision:** first add parallel drawing units inside one chip in Milestone 7, since it costs no parts and about 64% of the logic is still free. Shared memory may limit the gain, which that milestone will measure. Try several GPUs in the emulator before buying a second board.
