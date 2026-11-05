# DTGC protocol, version 1

How the PC talks to the GPU. The same bytes go over every link: USB serial now, the FT2232H FIFO later, and TCP to the emulator.

## Packet format

| Byte | Field | Notes |
|---|---|---|
| 0 | Sync | always `0xD7` |
| 1 | Version | always 1 |
| 2 | Type | see below |
| 3 | Sequence | counts up by 1 per packet, wrapping at 255 |
| 4, 5 | Payload length | little-endian, 0 to 1024 |
| 6 | Header CRC | CRC-8 of bytes 1 to 5 |
| 7 onward | Payload | |
| last 2 | Body CRC | little-endian CRC-16 of everything from byte 1 through the payload |

A **CRC** is a checksum that catches damaged data.
- CRC-8: polynomial 0x07, start value 0x00.
- CRC-16: CCITT polynomial 0x1021, start value 0xFFFF.

## Commands (PC to GPU)

Multi-byte numbers are little-endian. Drawing always goes to the hidden buffer. Coordinates are in the 340x340 picture.

| Type | Name | Payload | What it does |
|---|---|---|---|
| 0x01 | HELLO | ignored | Restarts sequence numbering from this packet's number |
| 0x02 | PING | ignored | Only asks for a reply |
| 0x10 | CLEAR | color (1 byte) | Fills the hidden buffer |
| 0x11 | SPAN | x, y (2 bytes each), then pixels | Writes one row of pixels. Pixels off the picture are skipped and never wrap to the next row |
| 0x12 | RECT | x, y, w, h (2 bytes each), color (1 byte) | Fills a rectangle, cut off at the picture's edge |
| 0x13 | PALETTE | first index (1 byte), then red, green, blue triples | Sets colours. Entries past index 255 are ignored |
| 0x14 | SWAP | none | Shows the hidden buffer during vertical blanking, then replies. The new hidden buffer holds the frame before last |
| 0x15 | TILE | x, y, w, h (2 bytes each), then pixels | Fills an area left to right, row by row, from raw pixels. Stops when the area is full or the pixels run out. Pixels off the picture are skipped, and still use up their place in the area |
| 0x16 | RLE | x, y, w, h (2 bytes each), then (n, colour) pairs | The same, where each pair means n + 1 pixels of that colour. **Run-length coding** like this shrinks flat areas. An odd payload length is refused |
| 0x17 | TRIANGLE | 37 bytes, see `docs/rasterizer.md` | Draws one triangle with optional depth test and texture |
| 0x18 | TEX_SPAN | row (2 bytes), u (1 byte), then pixels | Writes texture memory. Rows from 2048 up, and bytes past the end of a row, are skipped |
| 0x19 | CLEAR_DEPTH | value (2 bytes) | Fills the depth memory |
| 0x1A | DEPTH_RECT | x, y, w, h (2 bytes each), value (2 bytes) | Fills a rectangle of the depth memory, cut off at the picture's edge |
| 0x1C | VERTICES | first slot (1 byte), count (1 byte), then count x (x, y as signed 2 bytes in sixteenths of a pixel, z as 2 bytes) | Stores corners in the GPU's 256 slots, for TRIANGLE_LIST. A length that does not match the count is BAD_LENGTH. Running past slot 255 is BAD_VALUE and stores nothing. Slots hold unknown values until written |
| 0x1D | TRIANGLE_LIST | mode (1 byte), count (1 byte), then count x (3 slots, red, green, blue: 1 byte each) | Draws flat-coloured triangles from stored corners, so a corner shared by several triangles is sent once. An invalid triangle is skipped, the others are drawn, and the reply is BAD_VALUE |
| 0x1B | READ_RECT | x, y, w, h (2 bytes each), which buffer (1 byte) | Sends a rectangle of the framebuffer back as DATA packets, then an ACK |

The default palette after reset maps a pixel to `RRRGGGBB`. Buffers are not cleared at reset, so clear both before showing them.

## Replies (GPU to PC)

Replies use the same packet format, with a sequence byte of 0 and a 2-byte payload.

| Type | Name | Byte 0 | Byte 1 |
|---|---|---|---|
| 0x80 | ACK | sequence number being answered | 0 = done, 1 = unknown type, 2 = bad length, 3 = bad value |
| 0x81 | NACK | sequence number the GPU wants next | 1 = body CRC failed, 2 = wrong sequence number |

READ_RECT also sends one DATA packet per row, before its ACK:

| Type | Name | Payload |
|---|---|---|
| 0x82 | DATA | row number y (2 bytes), then that row's pixels. The sequence byte is the READ_RECT's sequence number |

## How errors are handled

| What arrives | What the GPU does |
|---|---|
| Bytes with no sync | Skips them |
| Bad header CRC, wrong version, or length over 1024 | Drops the header silently, then looks for sync from the next byte. The PC finds out by timeout |
| Bad body CRC | Sends NACK 1 and applies nothing, because payloads are stored and checked before use |
| Next expected sequence number | Applies it and sends ACK |
| The sequence number just before that | Sends ACK without applying it again |
| Any other sequence number | Sends NACK 2 with the number it wants |
| Silence of 65536 clocks (about 2.6 ms) in the middle of a packet | Drops the partial packet, so a pulled cable cannot swallow the next one |

The PC (`sw/dtgc/client.py`) keeps up to 1024 bytes and 64 packets unacknowledged. On a NACK or after 0.25 s of silence it resends from the first missing packet. After 5 s with no progress it raises `LinkError`.

If a burst noise byte is a false sync, the 6 bytes after it are taken as a header, which can swallow the start of a real packet. That packet is then recovered by resending.

## Known limits
- **Flow control depends on the PC.** The GPU's receive buffer is 1024 bytes and has no way to stop the sender on the UART link, so the PC's limit is what prevents overflow. An overflow lights an LED and loses bytes, and resending then recovers them.
- **A reset GPU and a running PC disagree on sequence numbers.** Send HELLO after connecting; `Dtgc` does.
- **Disconnects.** After reconnecting, `Dtgc` sends HELLO, and the application should redraw the frame it was drawing. The GPU keeps its buffers.
- **The PC's memory cannot be read by the GPU.** Everything it draws has to be sent over the link. `sw/dtgc/assets.py` tracks what has already been sent. A miss holds up the frame for size / link speed: a 64 x 64 texture of 4096 bytes takes about 14 ms at an assumed 0.3 MB/s, roughly a fifth of the 66 ms frame time at 15 fps. Prefetch sends assets early to avoid that. Nothing on the GPU reads from that memory until textures arrive in Milestone 6.
- **The 1024-byte window limits speed on a slow round trip.** At most 1024 bytes can wait for a reply, so throughput cannot go over 1024 bytes per round trip. A 16 ms USB delay would mean about 64 KB/s, whatever the link speed. The real delay is unmeasured (`docs/verify.md`).

Throughput on real hardware is unmeasured.
