# DT-Upscale

DT-Upscale makes a small drawn picture bigger for the screen, without neural networks.
The Python model is [sw/dtgc/upscale.py](../sw/dtgc/upscale.py). Two methods are also in Verilog and match the model bit for bit in simulation: bilinear ([rtl/upscale_filter.v](../rtl/upscale_filter.v)) and edge-directed x2 ([rtl/upscale_edge.v](../rtl/upscale_edge.v)). Resource numbers are in [resources.md](resources.md). **None of it has been near hardware.**

It uses whole-number scales and integer maths, and each output pixel needs only a small window of input pixels, so it can later become a pipeline of adders and small line memories.

## Methods

| Method | How it works | Pixels read per output pixel |
|---|---|---|
| nearest | Repeats pixels. The baseline | 1 |
| bilinear | Blends the nearest pixels | 4 |
| bicubic | Blends with Catmull-Rom weights, which keeps edges crisper | 16 |
| edge | Splits each square of 4 pixels along the diagonal with the smaller difference, then blends inside the triangle | 4 |

`sharpen` adds back part of the difference between a pixel and its neighbours.

## Scores

Each test shrinks a large picture by averaging, enlarges it again, and compares the result with the original.
PSNR is closeness in decibels, and higher is better. SSIM is a score for how well shapes are kept, where 1 is identical. Regenerate these with `python scripts/upscale_compare.py`, which also writes [images/upscale_compare.png](images/upscale_compare.png).

Fractal picture, scale 2:

| Method | PSNR (dB) | SSIM |
|---|---|---|
| nearest | 28.10 | 0.9720 |
| bilinear | 27.88 | 0.9678 |
| bicubic | 28.23 | 0.9715 |
| bicubic, sharpen 2 | 28.40 | 0.9742 |

Fractal picture, scale 3, PSNR only: nearest 26.85, bilinear 26.93, bicubic 27.10, bicubic with sharpen 2 27.18.

Flat shapes, scale 2: nearest 30.65 dB, SSIM 0.9884. Bilinear 28.02 dB. Bicubic 29.27 dB. Bicubic with sharpen 2 30.81 dB, SSIM 0.9621. Edge 28.36 dB.

Smooth gradient: about 57 dB without sharpening, and about 51 dB with it.

## What these numbers do and do not say

- **Bicubic with a little sharpening is the best all-round choice on these pictures, by a small margin.** The gap from nearest on the fractal is about 0.3 dB.
- **Nearest wins SSIM on flat shapes, and that is partly the test's doing.** Shrinking by averaging leaves flat blocks that repeating pixels restores exactly. A real game frame is drawn at the low size with hard edges, so this test cannot say which looks better there.
- **The edge method did not beat bicubic on any score.** It may still look better on diagonal edges, or it may not. Nobody has judged that by eye on a real screen.
- **Sharpening hurts smooth pictures**, as the gradient shows, so it should be something the program can switch off.
- These scores measure closeness, not how pleasant the picture looks.

## Plan for hardware

1. Decide after seeing real output on a monitor. Bilinear is the cheapest real step up from nearest, and the first candidate for Verilog.
2. Write it to match this model bit for bit, as the rasterizer matches its model.
3. Record resources in [resources.md](resources.md), which will decide whether bicubic fits.

Going above 640x480 also needs the HD video path, which is still open in [roadmap.md](roadmap.md). Which output modes this chip can reach is a `VERIFY` item in [verify.md](verify.md).
