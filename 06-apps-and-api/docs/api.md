# The DTGC graphics API

This is what a game or program uses to draw. It lives in [sw/dtgc/api.py](../sw/dtgc/api.py).
Everything here has only run on the emulator so far, not on a real board.

## A whole program

```python
from sw.dtgc.api import Canvas, Mesh, rgb
from sw.dtgc.client import connect_auto

gpu = connect_auto()          # a board on a serial port, or else a running emulator
canvas = Canvas(gpu)
for frame in range(100):
    canvas.clear(rgb(0, 0, 85))
    canvas.clear_depth()
    canvas.draw_mesh(Mesh.cube(), angle_y=frame * 0.05, distance=4)
    canvas.text(8, 8, f"FRAME {frame}", rgb(255, 255, 255))
    canvas.show()
canvas.finish()
gpu.close()
```

Start an emulator first with `python -m sw.dtgc emulator --window` if no board is plugged in.

## The picture

- The picture is 340 x 340 pixels. (0, 0) is the top left corner, and y goes down.
- There are 256 colours at once. `rgb(r, g, b)` turns 0-255 parts into a colour number using 3 bits of red, 3 of green and 2 of blue.
- **Parts round down.** Red or green under 32 and blue under 64 come out as none, so `rgb(0, 0, 40)` is black. Our own games had this bug.
- You draw into a hidden picture, and `show()` puts it on screen. After `show()` the hidden picture is the frame before last, so clear it or redraw all of it.

## Canvas

| Call | What it does |
|---|---|
| `clear(color)` | Fills the hidden picture |
| `clear_depth()` | Resets the depth memory. Call this once per frame before drawing depth-tested triangles |
| `clear_scene(color)` | Does both, sending only the areas earlier frames drew on. Much faster when the scene covers part of the screen. All drawing must go through this Canvas, or some of it won't be cleared |
| `draw(triangle)` | Sends a triangle already in the GPU's own form (`sw/dtgc/raster.py`) |
| `rect(x, y, w, h, color)` | Fills a rectangle. Parts off the picture are dropped |
| `text(x, y, text, color, size=2)` | Draws capital letters, digits and `- . :` from the built-in font. Returns the width in pixels |
| `triangle(corners, colors, depth=False, dither=True)` | One triangle. `corners` are 3 `(x, y, z)`, in pixels with z from 0 to 1. `colors` are 3 `(r, g, b)`, blended across the triangle |
| `textured_triangle(corners, uvs, texture, depth=False)` | One triangle with a picture on it. `texture` comes from `TextureCache.use` in [sw/dtgc/assets.py](../sw/dtgc/assets.py) |
| `draw_mesh(mesh, position, angle_x, angle_y, distance, light)` | Turns, lights and projects a 3D object, then sends the triangles |
| `show()` | Shows the frame |
| `finish()` | Waits until the GPU has confirmed everything sent so far. Raises an error if it refused anything |

Depth means how far away a pixel is. With it on, a nearer pixel hides a further one, whichever was drawn first.

## Meshes

A `Mesh` is a list of `vertices`, each `(x, y, z)`, and a list of `triangles`, each `(a, b, c, (r, g, b))`.
`a`, `b` and `c` are places in the vertex list. `Mesh.cube(size, colors)` makes a cube.

`draw_mesh` has limits you should know about:

- It sends faces pointing towards the viewer only, which needs the corners of each triangle in the right order.
- A triangle that reaches behind the viewer is dropped whole, because the GPU has no clipping. Objects vanish a little early when very close.

## Writing a game

A game is a class with two methods. Look at [sw/dtgc/games.py](../sw/dtgc/games.py) for three examples.

```python
class MyGame:
    def step(self, keys):      # keys is a set holding any of "up", "down", "left", "right"
        ...
    def draw(self, canvas):
        ...
```

Keep the rules in `step` and the drawing in `draw`, with no clock in either. A test can then replay the same keys and get the same game.
Add the class to `GAMES` at the bottom of that file, and `python -m sw.dtgc play mygame` will run it.

## How much you can draw

Every call sends bytes over the USB link, so the link sets a limit before the GPU does. Measured bytes per frame are in [benchmarks.md](benchmarks.md).

- A `rect` is 18 bytes and a `triangle` 46, counting the packet wrapping. Each letter of `text` is one `rect` for every lit block in it, so text is expensive.
- A full-picture `clear` costs few bytes but takes the GPU a long time to carry out, about 32,000 clocks in simulation.
- There is no reading back from the GPU. The program has to remember what it drew.

## What it cannot do

No shaders, no blending or transparency, no lines or points as their own commands, and no 3D clipping.
Textures use the nearest texel with no filtering. DirectX and Vulkan programs cannot use it, and modern games are out of scope for this chip and link.
