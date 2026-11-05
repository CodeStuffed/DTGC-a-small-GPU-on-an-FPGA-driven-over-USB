"""Bit-for-bit comparison of the Verilog GPU and the Python emulator on the same random byte streams.

Usage: python -m unittest sw.tests.test_rtl_match    (set DTGC_RTL_SEEDS=N for more streams)

Compares both framebuffers, the palette, every reply byte, the sequence state and the video output.
Needs Icarus Verilog on the PATH, and skips with a message if it is missing.
"""
import os
import shutil
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sw.dtgc import emulator
from sw.dtgc import protocol as p
from sw.tests.streams import IDLE, TEXTURE_COLUMNS, TEXTURE_ROWS, make_stream

BUILD = Path("build/sim/match")
SIM_TIMEOUT = 1500  # seconds
BUILD_FT = Path("build/sim/match_ft")
SOURCES = ["sim/gpu_core_tb.v", "sim/sdram_model.v", "rtl/gpu_core.v", "rtl/raster.v", "rtl/vertex_store.v", "rtl/depth_flags.v", "rtl/video_timing.v",
           "rtl/sdram_ctrl.v", "rtl/fb_scanout.v", "rtl/byte_fifo.v", "rtl/pkt_parser.v",
           "rtl/cmd_exec.v", "rtl/reply_tx.v", "rtl/frame_reader.v"]
FT_SOURCES = ["sim/ft2232h_model.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v"]


def run_python(stream):
    device = emulator.Device()
    replies = bytearray()
    for word in stream:
        if word == IDLE:
            device.idle()
        else:
            replies += device.feed(bytes([word]))
    return device, bytes(replies)


def run_verilog(seed, stream, vvp, folder, options=()):
    prefix = folder / f"seed{seed}"
    stream_file = folder / f"seed{seed}.hex"
    stream_file.write_text("\n".join(f"{w:03x}" for w in stream) + "\n")
    result = subprocess.run(
        ["vvp", str(vvp), f"+stream={stream_file}", f"+words={len(stream)}", f"+out={prefix}", *options],
        capture_output=True, text=True, timeout=SIM_TIMEOUT)
    return prefix, result.stdout + result.stderr


def compare(seed, stream, vvp, folder=BUILD, options=None, video=True):
    """Returns a list of differences; empty means an exact match. Odd seeds have a link that often makes replies wait."""
    if options is None:
        options = ("+txstall=70",) if seed % 2 else ()
    prefix, output = run_verilog(seed, stream, vvp, folder, options)
    if "PASS" not in output:
        return [f"simulation did not finish: {output[-400:]}"]
    device, replies = run_python(stream)
    problems = []

    state = dict(line.split() for line in Path(f"{prefix}.state").read_text().splitlines())
    if state["rule_errors"] != "0":
        problems.append(f"SDRAM rule errors: {state['rule_errors']}")
    if state["out_of_range"] != "0":
        problems.append(f"{state['out_of_range']} writes landed outside the picture")
    if state["stray_words"] != "0":
        problems.append(f"{state['stray_words']} read words arrived with nothing waiting for them")
    if state["overflow"] != "0":
        problems.append("receive buffer overflowed")
    if state["underrun"] != "0":
        problems.append("scan-out ran out of pixels")
    if int(state["front"]) != device.front:
        problems.append(f"front buffer {state['front']} vs {device.front}")
    if int(state["expected"]) != device.expected:
        problems.append(f"expected sequence {state['expected']} vs {device.expected}")

    reply_words = Path(f"{prefix}.replies").read_text().split()
    if any("x" in v or "z" in v for v in reply_words):
        return [*problems, "a reply byte was unknown"]
    rtl_replies = bytes(int(v, 16) for v in reply_words)
    if rtl_replies != replies:
        at = next((i for i, (a, b) in enumerate(zip(rtl_replies, replies)) if a != b),
                  min(len(rtl_replies), len(replies)))
        problems.append(f"replies differ at byte {at}: lengths {len(rtl_replies)} and {len(replies)}")

    words = Path(f"{prefix}.memory").read_text().split()
    line_words = (p.WIDTH + 3) // 4
    if len(words) != 2 * p.HEIGHT * line_words:
        problems.append(f"memory dump has {len(words)} words")
    else:
        wrong = 0
        for buffer in range(2):
            for y in range(p.HEIGHT):
                for col in range(line_words):
                    word = words[(buffer * p.HEIGHT + y) * line_words + col]
                    want = device.buffers[buffer][y * p.WIDTH + col * 4:y * p.WIDTH + col * 4 + 4]
                    got = bytes.fromhex(word)[::-1] if "x" not in word and "z" not in word else None
                    if got != bytes(want):
                        if not wrong:
                            problems.append(f"first memory difference: buffer {buffer} row {y} "
                                            f"word {col}: {word} vs {bytes(want).hex()}")
                        wrong += 1
        if wrong:
            problems.append(f"{wrong} memory words differ")

    depth_words = Path(f"{prefix}.depth").read_text().split()
    wrong = 0
    for y in range(p.HEIGHT):
        for col in range(p.WIDTH // 2):
            want = device.depth[y * p.WIDTH + col * 2] | (device.depth[y * p.WIDTH + col * 2 + 1] << 16)
            word = depth_words[y * (p.WIDTH // 2) + col]
            if word != f"{want:08x}":
                if not wrong:
                    problems.append(f"first depth difference: row {y} word {col}: {word} vs {want:08x}")
                wrong += 1
    if wrong:
        problems.append(f"{wrong} depth words differ")

    texture_words = Path(f"{prefix}.texture").read_text().split()
    wrong = 0
    for row in range(TEXTURE_ROWS):
        for col in range(TEXTURE_COLUMNS // 4):
            at = row * 256 + col * 4
            if texture_words[row * 4 + col] != bytes(device.texture[at:at + 4])[::-1].hex():
                wrong += 1
    if wrong:
        problems.append(f"{wrong} texture words differ")

    palette = Path(f"{prefix}.palette").read_text().split()
    want_palette = [bytes(c).hex() for c in device.palette]
    if palette != want_palette:
        problems.append("palette differs")

    if not video:
        return problems
    screen = Path(f"{prefix}.screen").read_text().split()
    want_screen = device.screen_rgb()
    if len(screen) != 640 * 480:
        problems.append(f"screen dump has {len(screen)} pixels")
    else:
        wrong = sum(1 for i, v in enumerate(screen) if v != want_screen[i * 3:i * 3 + 3].hex())
        if wrong:
            problems.append(f"{wrong} screen pixels differ")
    return problems


@unittest.skipUnless(shutil.which("iverilog"), "Icarus Verilog is not on the PATH")
@unittest.skipUnless(p.WIDTH == 340, "the 340x340 picture only")
class VerilogMatchesEmulator(unittest.TestCase):
    def test_random_streams(self):
        seeds = range(1, int(os.environ.get("DTGC_RTL_SEEDS", "4")) + 1)
        BUILD.mkdir(parents=True, exist_ok=True)
        vvp = BUILD / "gpu_core_tb.vvp"
        subprocess.run(["iverilog", "-g2005", "-o", str(vvp), *SOURCES], check=True)
        streams = {seed: make_stream(seed) for seed in seeds}
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = dict(zip(seeds, pool.map(lambda s: compare(s, streams[s], vvp), seeds)))
        for seed, problems in results.items():
            print(f"seed {seed}: {'exact match' if not problems else problems}")
        self.assertEqual({s: r for s, r in results.items() if r}, {})

    def test_without_hard_multipliers(self):
        """The fallback build's maths must give the same answers as the multipliers."""
        folder = BUILD / "serial_math"
        folder.mkdir(parents=True, exist_ok=True)
        vvp = folder / "gpu_core_tb.vvp"
        subprocess.run(["iverilog", "-g2005", "-DRASTER_SERIAL_MATH", "-o", str(vvp), *SOURCES], check=True)
        problems = compare(1, make_stream(1), vvp, folder)
        print(f"no hard multipliers: {'exact match' if not problems else problems}")
        self.assertEqual(problems, [])

    def test_usb_output_version(self):
        """With no lines read for a screen, everything the PC can see must be just the same."""
        seeds = range(1, int(os.environ.get("DTGC_RTL_SEEDS", "4")) + 1)
        folder = Path("build/sim/match_usb")
        folder.mkdir(parents=True, exist_ok=True)
        vvp = folder / "gpu_core_tb.vvp"
        subprocess.run(["iverilog", "-g2005", "-Pgpu_core_tb.SCANOUT=0", "-o", str(vvp), *SOURCES], check=True)
        streams = {seed: make_stream(seed) for seed in seeds}
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = dict(zip(seeds, pool.map(lambda s: compare(s, streams[s], vvp, folder, video=False), seeds)))
        for seed, problems in results.items():
            print(f"USB output seed {seed}: {'exact match' if not problems else problems}")
        self.assertEqual({s: r for s, r in results.items() if r}, {})

    def test_through_the_ft2232h_link(self):
        """The same streams, arriving through the FT2232H model with the chip hesitating on odd seeds."""
        seeds = range(1, int(os.environ.get("DTGC_RTL_SEEDS", "4")) + 1)
        BUILD_FT.mkdir(parents=True, exist_ok=True)
        vvp = BUILD_FT / "gpu_core_tb.vvp"
        subprocess.run(["iverilog", "-g2005", "-DUSE_FT_LINK", "-o", str(vvp), *SOURCES, *FT_SOURCES], check=True)
        streams = {seed: make_stream(seed) for seed in seeds}

        def one(seed):
            options = ("+rxstall=30", "+txstall=30") if seed % 2 else ()
            return compare(seed, streams[seed], vvp, BUILD_FT, options)

        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = dict(zip(seeds, pool.map(one, seeds)))
        for seed, problems in results.items():
            print(f"FT link seed {seed}: {'exact match' if not problems else problems}")
        self.assertEqual({s: r for s, r in results.items() if r}, {})


@unittest.skipUnless(shutil.which("iverilog"), "Icarus Verilog is not on the PATH")
@unittest.skipUnless(p.WIDTH != 340, "run with DTGC_PICTURE=960x540 in the environment")
class LargePictureMatchesEmulator(unittest.TestCase):
    def test_random_streams(self):
        """The core with no video, as test_upscale_rtl checks the screen. The picture does not fit the plain 640x480 output."""
        seeds = range(1, int(os.environ.get("DTGC_RTL_SEEDS", "4")) + 1)
        folder = Path("build/sim/match_large")
        folder.mkdir(parents=True, exist_ok=True)
        vvp = folder / "gpu_core_tb.vvp"
        subprocess.run(["iverilog", "-g2005", "-Pgpu_core_tb.SCANOUT=0", f"-Pgpu_core_tb.WIDTH={p.WIDTH}", f"-Pgpu_core_tb.HEIGHT={p.HEIGHT}",
                        "-o", str(vvp), *SOURCES], check=True)
        streams = {seed: make_stream(seed) for seed in seeds}
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = dict(zip(seeds, pool.map(lambda s: compare(s, streams[s], vvp, folder, video=False), seeds)))
        for seed, problems in results.items():
            print(f"{p.WIDTH}x{p.HEIGHT} seed {seed}: {'exact match' if not problems else problems}")
        self.assertEqual({s: r for s, r in results.items() if r}, {})


if __name__ == "__main__":
    unittest.main()
