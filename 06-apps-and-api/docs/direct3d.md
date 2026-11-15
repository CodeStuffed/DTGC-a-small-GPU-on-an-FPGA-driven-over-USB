# Direct3D on DTGC: what exists and what cannot

**Short version:** a small `d3d9.dll` lets some old fixed-function Direct3D 9 programs draw on DTGC. This is not DirectX support, and modern games will not run. It has passed tests against the emulator and against this PC's real graphics driver. It has not run on real DTGC hardware.

## What "DirectX" would need

| Version | What it requires | Possible on this FPGA? |
|---|---|---|
| Direct3D 12, 11, 10 | Programmable shaders, and a Windows kernel display driver (WDDM) | No. There is no shader processor, and USB cannot carry the traffic |
| Direct3D 9 with shaders | Vertex and pixel shader programs | No |
| Direct3D 9 fixed-function, a subset | Triangles, depth test, simple textures | Yes, by doing the vertex work on the PC. This is what was built |

A *fixed-function* program picks from built-in features (lights, matrices, textures) and does not supply shader programs of its own.

## How it works

1. You copy `build/d3d9/x64/d3d9.dll` (or `x86`, to match the program) next to that one program's `.exe`.
2. Windows loads our DLL for that program instead of the system one. Nothing is installed and no system file changes.
3. The DLL does the vertex work on the PC: matrices, lighting and clipping. It sends the resulting triangles to DTGC through the normal protocol.

The DLL reaches the GPU over TCP (`DTGC_PORT`, default 7654). The emulator listens there, and `python -m sw.dtgc bridge` forwards the traffic to real hardware.

## Limits

- The picture goes to the GPU's HDMI output. The program's own window stays empty.
- The picture is 340 × 340 with 8-bit colour, whatever size the program asks for.
- There are no shaders, blending or render-to-texture.
- Textures replace the colour and cannot be mixed with lighting. Sampling is nearest-pixel with no perspective correction.
- The depth test is always "less than", and dithering is always on.
- Points and lines are ignored.
- 71 of the device's methods refuse the call. Set `DTGC_D3D9_LOG` to a file path to see which ones a program uses.
- `Direct3DCreate9Ex` is refused.

Most real games will fail somewhere on this list. Expect small and old programs to work, and test each one.

## Test results

`python -m unittest sw.tests.test_d3d9` builds a test program with three frames: a triangle, a lit cube and a textured square. It draws them through our DLL and through this PC's real NVIDIA Direct3D 9 driver, then compares them.

| Frame | Shape overlap with the real driver | Mean colour difference (8×8 blocks, out of 255) |
|---|---|---|
| Triangle | 0.9984 | 0.4 |
| Lit cube | 0.9997 | 0.3 |
| Textured square | 0.9924 | 2.5 |

The comparison pictures are in `build/d3d9/compare/`. These figures come from the emulator and show how close the DLL's output is. They say nothing about speed on real hardware.

## Build

```
python sw/d3d9/build.py
```

This needs Visual Studio with the C++ tools and the Windows SDK, which are already on this PC.
