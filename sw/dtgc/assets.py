"""Host-side cache of what is stored in the GPU's spare memory.

Usage:
    cache = AssetCache(capacity_bytes, upload=lambda address, data: ...)
    cache.begin_frame()
    address = cache.use("brick", load=lambda: open("brick.raw", "rb").read())
    cache.prefetch(["next_room"], load_for, budget_bytes=20000)

The GPU cannot read the PC's memory, so anything it draws from has to be sent first. This keeps track
of what is already there, sends what is missing, and when memory runs out removes whatever was used
longest ago. **Eviction** means forgetting an asset to free its space. **Prefetch** means sending an
asset before it is needed, up to a byte budget, so a frame does not have to wait for it.

Assets used in the current frame are never evicted. The link speed sets the cost of a miss: see
upload_seconds and docs/protocol.md.
"""
from collections import OrderedDict


class CacheFull(Exception):
    """The asset does not fit, even after evicting everything not in use this frame."""


def upload_seconds(size, bytes_per_second):
    """How long a miss holds things up on a link of this speed, ignoring packet overhead."""
    return size / bytes_per_second


class AssetCache:
    def __init__(self, capacity, upload):
        self.capacity = capacity
        self.upload = upload
        self.entries = OrderedDict()  # name: (address, size, frame last used), oldest first
        self.free = [(0, capacity)]   # (address, size), sorted by address, never touching
        self.frame = 0
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "bytes_uploaded": 0, "prefetched": 0}

    def begin_frame(self):
        self.frame += 1

    def use(self, name, load):
        """Returns the asset's address, sending it first if it is not there."""
        if name in self.entries:
            address, size, _ = self.entries.pop(name)
            self.entries[name] = (address, size, self.frame)
            self.stats["hits"] += 1
            return address
        self.stats["misses"] += 1
        return self._add(name, load(), self.frame)

    def prefetch(self, names, load, budget_bytes):
        """Sends missing assets until the budget is spent. Never evicts: a guess must not cost a hit."""
        for name in names:
            if name in self.entries:
                continue
            data = load(name)
            if len(data) > budget_bytes:
                return
            address = self._take_free(len(data))
            if address is None:
                return
            budget_bytes -= len(data)
            self._store(name, address, data, self.frame - 1)
            self.stats["prefetched"] += 1

    def _add(self, name, data, frame):
        if len(data) > self.capacity:
            raise CacheFull(f"{name} is {len(data)} bytes, and the cache holds {self.capacity}")
        address = self._take_free(len(data))
        while address is None:
            self._evict_oldest(name)
            address = self._take_free(len(data))
        self._store(name, address, data, frame)
        return address

    def _store(self, name, address, data, frame):
        self.upload(address, data)
        self.entries[name] = (address, len(data), frame)
        self.stats["bytes_uploaded"] += len(data)

    def _evict_oldest(self, wanted):
        for name, (address, size, used) in self.entries.items():
            if used < self.frame:
                del self.entries[name]
                self._release(address, size)
                self.stats["evictions"] += 1
                return
        raise CacheFull(f"{wanted} does not fit: everything else is in use this frame")

    def _take_free(self, size):
        for i, (address, free_size) in enumerate(self.free):
            if free_size >= size:
                if free_size == size:
                    del self.free[i]
                else:
                    self.free[i] = (address + size, free_size - size)
                return address
        return None

    def _release(self, address, size):
        self.free.append((address, size))
        self.free.sort()
        merged = []
        for start, length in self.free:
            if merged and merged[-1][0] + merged[-1][1] == start:
                merged[-1] = (merged[-1][0], merged[-1][1] + length)
            else:
                merged.append((start, length))
        self.free = merged


class TextureCache:
    """Keeps square textures in the GPU's texture memory, a store of 2048 rows of 256 bytes.

    Usage:
        textures = TextureCache(gpu)
        textures.begin_frame()
        row, size = textures.use("brick", load=lambda: pixels)    # pixels is side x side bytes
        gpu.triangle(Triangle(MODE_TEXTURE, row, size, ...))

    A texture takes whole rows, so every address is a multiple of 256 and the row is address / 256.
    size is log2 of the side, as the TRIANGLE command wants it.
    """
    ROWS = 2048
    ROW_BYTES = 256

    def __init__(self, gpu):
        self.gpu = gpu
        self.cache = AssetCache(self.ROWS * self.ROW_BYTES, self._upload)
        self.sides = {}

    def begin_frame(self):
        self.cache.begin_frame()

    def use(self, name, load):
        """Returns (first row, log2 of the side), sending the texture first if it is not there."""
        address = self.cache.use(name, lambda: self._prepare(name, load()))
        side = self.sides[name]
        return address // self.ROW_BYTES, side.bit_length() - 1

    def _prepare(self, name, pixels):
        """Pads each row to the full 256 bytes, since that is the space it takes up."""
        side = int(len(pixels) ** 0.5)
        if side * side != len(pixels) or side & (side - 1) or not 1 <= side <= self.ROW_BYTES:
            raise ValueError(f"{name} must be square with a power-of-two side of at most 256")
        self.sides[name] = side
        padding = bytes(self.ROW_BYTES - side)
        return b"".join(pixels[i:i + side] + padding for i in range(0, len(pixels), side))

    def _upload(self, address, data):
        # Only the real pixels are sent. The padding is space, and is never read.
        rows = len(data) // self.ROW_BYTES
        side = rows
        pixels = b"".join(data[r * self.ROW_BYTES:r * self.ROW_BYTES + side] for r in range(rows))
        self.gpu.texture_rows(address // self.ROW_BYTES, side, pixels)
