"""Sends whole frames while only transmitting the tiles that changed.

Usage:
    from sw.dtgc.stream import FrameStreamer
    stream = FrameStreamer(gpu)
    stream.send_frame(pixels)      # pixels: 340 x 340 bytes

A **dirty tile** is a square of the picture that differs from what is already there. There are two
buffers, so a new frame is compared with the frame before last, which is what the hidden buffer
holds. Each tile goes as raw pixels or run-length coded, whichever is shorter.
"""
from . import protocol as p

MAX_TILE = 31  # 31 x 31 raw pixels still fit one packet


def tiles_for(width, height, size):
    for y in range(0, height, size):
        for x in range(0, width, size):
            yield x, y, min(size, width - x), min(size, height - y)


def tile_changed(new, old, x, y, w, h):
    if old is None:
        return True
    for row in range(y, y + h):
        start = row * p.WIDTH + x
        if new[start:start + w] != old[start:start + w]:
            return True
    return False


def tile_pixels(frame, x, y, w, h):
    return b"".join(frame[row * p.WIDTH + x:row * p.WIDTH + x + w] for row in range(y, y + h))


class FrameStreamer:
    def __init__(self, gpu, tile_size=20, compress=True):
        if not 1 <= tile_size <= MAX_TILE:
            raise ValueError(f"tile_size must be 1 to {MAX_TILE}")
        self.gpu = gpu
        self.tile_size = tile_size
        self.compress = compress
        self.invalidate()

    def invalidate(self):
        """Forget what the GPU holds, for example after reconnecting. The next two frames go in full."""
        self.hidden = [None, None]
        self.which = 0

    def send_frame(self, pixels):
        """Sends the changed tiles, swaps, and waits for the GPU. Returns the tiles sent."""
        if len(pixels) != p.WIDTH * p.HEIGHT:
            raise ValueError("a frame is 340 x 340 bytes")
        old = self.hidden[self.which]
        sent = 0
        for x, y, w, h in tiles_for(p.WIDTH, p.HEIGHT, self.tile_size):
            if tile_changed(pixels, old, x, y, w, h):
                self._send_tile(x, y, w, h, tile_pixels(pixels, x, y, w, h))
                sent += 1
        self.gpu.swap()
        self.gpu.flush()
        self.hidden[self.which] = bytes(pixels)
        self.which = 1 - self.which
        return sent

    def _send_tile(self, x, y, w, h, tile):
        pairs = p.rle_pairs(tile) if self.compress else None
        if pairs is not None and len(pairs) < len(tile):
            self.gpu.rle(x, y, w, h, pairs)
        else:
            self.gpu.tile(x, y, w, h, tile)
