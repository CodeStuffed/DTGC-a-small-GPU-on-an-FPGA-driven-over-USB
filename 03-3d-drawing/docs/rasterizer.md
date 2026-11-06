# Triangle rasterizer rules

A **rasterizer** turns a triangle into the pixels it covers. These rules are shared by `sw/dtgc/raster.py` and `rtl/raster.v`, which must match bit for bit. All of this has passed in simulation only.

## Command
`TRIANGLE` (type 0x17) has a 37-byte payload:

| Bytes | Field | Notes |
|---|---|---|
| 1 | mode | Bit 0 depth test, bit 1 texture, bit 2 dither |
| 2 | tex_row | First texture row |
| 1 | tex_size | Log2 of the texture size, at most 8 |
| 11 x 3 | vertices | `x, y` int16, `z` uint16, then `r, g, b, u, v` bytes |

`x` and `y` are in 1/16 pixel units and must be from -16384 to 16383. A value out of range, or a tex_size above 8, gets ACK status 3 (bad value) and nothing is drawn.

## Coverage
1. Area `D = dx1*dy2 - dx2*dy1`. If `D` is 0, nothing is drawn. If `D` is negative, swap v1 and v2.
2. The bounding box is each vertex position `>> 4`, limited to the picture.
3. A pixel is sampled at its centre, `px*16 + 8`.
4. Each edge from a to b gives `E = dx*(sy-ay) - dy*(sx-ax)`. Subtract 1 unless it is a **top-left edge** (`dy < 0`, or `dy == 0` and `dx > 0`).
5. The pixel is inside when all three `E >= 0`. The top-left rule means two triangles sharing an edge never both draw, and never both miss, a pixel on it.

## Colour, depth and texture coordinates
Each value is a plane with 16 fractional bits.

- Gradient: `trunc((|n| << 20) / area)`, limited to 2^31 - 1, with the sign of `n`.
- Start: `(c0 << 16) + ((gx*ox + gy*oy) >> 4)`.
- Result: the whole part, limited to 0-255, or 0-65535 for depth. Rounding on thin triangles can step just outside the range, so this limit is needed.

## Writing a pixel
- **Colour** packs to RRRGGGBB.
- **Dither:** before packing, add a number from a repeating 4 x 4 pattern, so a smooth colour alternates between its two nearest stored values and looks in-between from a distance. `level = BAYER[y & 3][x & 3]`, with rows `0 8 2 10`, `12 4 14 6`, `3 11 1 9`, `15 7 13 5`. Red and green become `c - (c >> 3) + level * 2`, and blue becomes `c - (c >> 2) + level * 4`. The scaling makes the average of the shown colours match the true colour under the default palette, and white stays in range. Textured pixels are not dithered, because their colour comes straight from the texture.
- **Depth:** the pixel passes only if `z < stored`. A pass writes colour, then depth.
- **Texture:** nearest texel, with no perspective correction. `row = (tex_row + (v & mask)) & 0x7FF`, `column = u & mask`, `mask = 2^tex_size - 1`. The texel replaces the colour.

## Memory
- Bank 2 holds depth: row = y, column = x >> 1, 16 bits each, with odd x in the high half.
- Bank 3 holds textures: 2048 rows of 256 bytes, loaded with `TEX_SPAN` (0x18). Rows from 2048 up are skipped, and so are bytes past the end of a row.
- `CLEAR_DEPTH` (0x19) takes a 2-byte value.

## Hardware
The multiplier and divider work one bit per clock and use no DSP blocks, so setup takes hundreds of clocks per triangle. A pixel outside the triangle takes 1 clock, and a row ends as soon as the triangle has been left, since a triangle crosses a row in one piece.

The pixel loop handles one pixel per clock while it has what it needs. It holds one word of colour (4 pixels), one word of texture (4 texels) and a depth tile of 8 words (16 pixels). The tile is read as one burst. Writes collect until the pixel moves to another word or tile, and everything is written before the triangle reports done, so the next command sees finished memory. None of this changes the picture, which still has to match `sw/dtgc/raster.py` bit for bit.

Attributes a triangle doesn't need are skipped: colour when textured, u and v when not, and depth when the depth test is off.

Build results are in `docs/resources.md`.
