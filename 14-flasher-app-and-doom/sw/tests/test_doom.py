#!/usr/bin/env python3
"""Usage: python -m unittest sw.tests.test_doom

The path a Doom frame takes: engine program, local socket, sw/dtgc/doom.py, DTGC commands, the emulator's picture.
No copy of Doom is used. A stand-in engine (sw/tests/doom_standin) is compiled with the real platform file
sw/doom/doomgeneric_dtgc.c and behaves towards it as doomgeneric does. The tests that need it skip when this PC has
no C compiler. So this shows our side of the link is right; it does not show the real engine builds or runs.
"""
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from sw.dtgc import doom, emulator
from sw.dtgc import protocol as p
from sw.dtgc.client import Dtgc

sys.path.insert(0, "scripts")
import get_doom  # noqa: E402

STANDIN = Path("sw/tests/doom_standin")
BUILD = Path("build/sim/doom_standin").resolve()
ENGINE_KEY_LEFT, ENGINE_KEY_FIRE, ENGINE_KEY_F5 = 0xAC, 0xA3, 0x80 + 0x3F  # the engine's own numbers, from its doomkeys.h


def build_standin(indexed):
    """The stand-in engine with our platform file, as get_doom.py builds the real one. None when it cannot be built."""
    program = BUILD / ("indexed" if indexed else "plain") / get_doom.program_name()
    program.parent.mkdir(parents=True, exist_ok=True)
    sources = [(STANDIN / "standin.c").resolve(), get_doom.PLATFORM_FILE]
    ok, text = get_doom.compile_engine(sources, STANDIN.resolve(), program, indexed)
    if not ok and ("was not found" in text):
        return None
    if not ok:
        raise AssertionError(text[-2000:])
    return program


class Keys(unittest.TestCase):
    def test_named_keys(self):
        self.assertEqual(doom.key_number("Left"), doom.LEFT)
        self.assertEqual(doom.key_number("Control_L"), doom.FIRE)
        self.assertEqual(doom.key_number("space"), doom.USE)
        self.assertEqual(doom.key_number("F1"), doom.F1)
        self.assertEqual(doom.key_number("F12"), doom.F1 + 11)
        self.assertEqual(doom.key_number("Return"), doom.ENTER)

    def test_letters_are_sent_in_lower_case(self):
        self.assertEqual(doom.key_number("Y"), ord("y"))
        self.assertEqual(doom.key_number("7"), ord("7"))

    def test_other_keys_are_left_out(self):
        self.assertIsNone(doom.key_number("Caps_Lock"))
        self.assertIsNone(doom.key_number("Win_L"))

    def test_our_numbers_do_not_collide_with_characters(self):
        ours = [v for v in doom.NAMED_KEYS.values() if v >= 128]
        self.assertEqual(min(ours), 128)
        self.assertEqual(max(ours), doom.F1 + 11)
        self.assertLess(max(ours), 256)


class Fit(unittest.TestCase):
    def frame(self, width, height):
        return bytes(1 + (x + y) % 200 for y in range(height) for x in range(width))

    def test_centred_when_it_fits(self):
        picture = doom.fit(self.frame(320, 200), 320, 200)
        self.assertEqual(len(picture), p.WIDTH * p.HEIGHT)
        left, top = (p.WIDTH - 320) // 2, (p.HEIGHT - 200) // 2
        self.assertEqual(picture[top * p.WIDTH + left], 1)
        self.assertEqual(picture[(top + 199) * p.WIDTH + left + 319], 1 + (319 + 199) % 200)
        self.assertEqual(picture[(top - 1) * p.WIDTH + left], 0)
        self.assertEqual(picture[top * p.WIDTH + left - 1], 0)

    def test_every_picture_size_the_builds_use(self):
        for width, height, expected in ((340, 340, (320, 200)), (384, 216, (320, 200)), (480, 270, (320, 200)),
                                        (640, 360, (320, 200)), (960, 540, (320, 200)), (320, 180, (288, 180)),
                                        (274, 154, (246, 154))):
            with mock.patch.object(p, "WIDTH", width), mock.patch.object(p, "HEIGHT", height):
                self.assertEqual(doom.shown_size(320, 200), expected, (width, height))
                self.assertEqual(len(doom.fit(self.frame(320, 200), 320, 200)), width * height)

    def test_scale_is_used_only_when_there_is_room(self):
        with mock.patch.object(p, "WIDTH", 960), mock.patch.object(p, "HEIGHT", 540):
            self.assertEqual(doom.shown_size(320, 200, 2), (640, 400))
            self.assertEqual(doom.shown_size(320, 200, 5), (640, 400))
            picture = doom.fit(self.frame(320, 200), 320, 200, 2)
            left, top = (960 - 640) // 2, (540 - 400) // 2
            self.assertEqual(picture[top * 960 + left], picture[(top + 1) * 960 + left + 1])  # each pixel is a 2x2 block
        self.assertEqual(doom.shown_size(320, 200, 2), (320, 200))  # 340x340 has no room for twice the size


class FakeEngine:
    """Plays the engine's part of the socket link from inside the test."""

    def __init__(self, port):
        self.link = socket.create_connection(("127.0.0.1", port))

    def send(self, data):
        self.link.sendall(data)

    def frame(self, width, height, pixels):
        self.send(b"F" + bytes((width & 255, width >> 8, height & 255, height >> 8)) + pixels)


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


class Link(unittest.TestCase):
    def setUp(self):
        self.engine = doom.Engine()
        threading.Thread(target=self.engine._read, daemon=True).start()
        self.fake = FakeEngine(self.engine.port)
        self.device = emulator.Device()
        self.gpu = Dtgc(emulator.LocalTransport(self.device))
        self.player = doom.Player(self.engine, self.gpu)

    def tearDown(self):
        self.fake.link.close()
        self.engine.close()

    def test_colours_and_a_frame_reach_the_picture(self):
        colours = bytes((i * 7) & 255 for i in range(768))
        pixels = bytes((x * 3 + y) & 255 for y in range(200) for x in range(320))
        self.fake.send(b"P" + colours)
        self.fake.frame(320, 200, pixels)
        self.assertTrue(wait_for(lambda: self.engine.frames_drawn == 1))
        self.assertTrue(self.player.step())
        self.assertEqual(self.device.palette[5], tuple(colours[15:18]))
        self.assertEqual(self.device.palette[255], tuple(colours[765:768]))
        self.assertEqual(bytes(self.device.buffers[self.device.front]), doom.fit(pixels, 320, 200))
        self.assertFalse(self.player.step())  # nothing new: nothing is sent

    def test_only_the_newest_frame_is_shown(self):
        for value in (1, 2, 3):
            self.fake.frame(320, 200, bytes([value]) * 64000)
        self.assertTrue(wait_for(lambda: self.engine.frames_drawn == 3))
        self.assertTrue(self.player.step())
        self.assertFalse(self.player.step())
        self.assertEqual(self.device.buffers[self.device.front][(p.HEIGHT // 2) * p.WIDTH + p.WIDTH // 2], 3)
        self.assertEqual(self.player.frames_shown, 1)

    def test_a_still_frame_costs_almost_nothing_the_second_time(self):
        pixels = bytes((x ^ y) & 255 for y in range(200) for x in range(320))
        for _ in range(3):  # two buffers, so the third frame is the first that finds nothing changed
            self.fake.frame(320, 200, pixels)
            self.assertTrue(wait_for(lambda: self.engine.frame is not None))
            before = self.gpu.stats["bytes"]
            self.player.step()
        self.assertLess(self.gpu.stats["bytes"] - before, 32)

    def test_keys_go_back_to_the_engine(self):
        self.assertTrue(wait_for(lambda: self.engine.connection is not None))
        self.engine.key(True, doom.LEFT)
        self.engine.key(False, doom.LEFT)
        self.fake.link.settimeout(5)
        got = b""
        while len(got) < 6:
            got += self.fake.link.recv(6 - len(got))
        self.assertEqual(got, bytes((ord("K"), 1, doom.LEFT, ord("K"), 0, doom.LEFT)))

    def test_title_and_built_in_colours(self):
        self.fake.send(b"T" + bytes((5, 0)) + b"hello" + b"D")
        self.assertTrue(wait_for(lambda: self.engine.palette is not None))
        self.assertEqual(self.engine.title, "hello")
        self.assertEqual(self.engine.take()[0], emulator.default_palette())

    def test_engine_going_away_is_noticed(self):
        self.assertTrue(wait_for(lambda: self.engine.connection is not None))
        self.fake.link.close()
        self.assertTrue(self.engine.closed.wait(5))


class Setup(unittest.TestCase):
    def test_missing_parts_are_explained(self):
        self.assertIn("get_doom.py", doom.missing_message(None, None))
        self.assertIn("WAD", doom.missing_message(Path("engine"), None))
        self.assertIsNone(doom.missing_message(Path("engine"), Path("game.wad")))

    def test_game_file_is_named_in_full(self):
        command = doom.command_for(Path("build/doom/dtgc_doom.exe"), Path("some.wad"), ["-warp", "1", "3"])
        self.assertEqual(command[1], "-iwad")
        self.assertTrue(Path(command[2]).is_absolute())
        self.assertEqual(command[-3:], ["-warp", "1", "3"])

    def test_engine_file_list_has_no_other_platform(self):
        for name in get_doom.ENGINE_FILES:
            self.assertFalse(name.startswith("doomgeneric_"), name)
            self.assertNotIn("sdl", name)
            self.assertNotIn("allegro", name)
        self.assertEqual(len(set(get_doom.ENGINE_FILES)), len(get_doom.ENGINE_FILES))


class StandInEngine(unittest.TestCase):
    """The compiled platform file, driven by the stand-in engine, all the way to the emulator's picture."""

    def play(self, indexed):
        program = build_standin(indexed)
        if program is None:
            self.skipTest("no C compiler on this PC")
        engine = doom.Engine()
        device = emulator.Device()
        gpu = Dtgc(emulator.LocalTransport(device))
        player = doom.Player(engine, gpu)
        engine.start([str(program)])
        self.addCleanup(engine.close)
        return engine, device, player

    def corner(self, device):
        """The colour number in the block where the stand-in shows the last key."""
        left, top = (p.WIDTH - 320) // 2, (p.HEIGHT - 200) // 2
        return device.buffers[device.front][top * p.WIDTH + left]

    def show_until(self, player, condition, seconds=10.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            player.step()
            if condition():
                return True
            time.sleep(0.002)
        return False

    def test_frames_colours_and_keys_with_one_byte_per_pixel(self):
        engine, device, player = self.play(indexed=True)
        self.assertTrue(self.show_until(player, lambda: player.frames_shown >= 6), "no frames arrived")
        self.assertEqual(engine.title, "stand-in engine")
        # The stand-in changes its colours on its fourth frame: red of entry i becomes (i + 100) & 255.
        self.assertTrue(self.show_until(player, lambda: device.palette[1] == (101, 254, 0)), device.palette[:3])
        self.assertEqual(device.palette[200], ((200 + 100) & 255, 55, 100))
        # The pattern is made of 16x16 squares with values that are multiples of 17.
        left, top = (p.WIDTH - 320) // 2, (p.HEIGHT - 200) // 2
        row = bytes(device.buffers[device.front][(top + 100) * p.WIDTH + left:(top + 100) * p.WIDTH + left + 320])
        self.assertTrue(all(value % 17 == 0 for value in row), row[:40])
        self.assertEqual(len(set(row[16 * k] for k in range(16))), 16)
        for ours, theirs in ((doom.LEFT, ENGINE_KEY_LEFT), (doom.FIRE, ENGINE_KEY_FIRE), (doom.F1 + 4, ENGINE_KEY_F5), (ord("y"), ord("y"))):
            engine.key(True, ours)
            self.assertTrue(self.show_until(player, lambda: self.corner(device) == theirs), (ours, self.corner(device)))
            engine.key(False, ours)
            self.assertTrue(self.show_until(player, lambda: self.corner(device) == 0), ours)
        self.assertGreaterEqual(engine.frames_drawn, player.frames_shown)

    def test_full_colour_build_falls_back_to_the_built_in_colours(self):
        engine, device, player = self.play(indexed=False)
        self.assertTrue(self.show_until(player, lambda: player.frames_shown >= 3), "no frames arrived")
        self.assertEqual(device.palette, emulator.default_palette())
        left, top = (p.WIDTH - 320) // 2, (p.HEIGHT - 200) // 2
        row = bytes(device.buffers[device.front][(top + 100) * p.WIDTH + left:(top + 100) * p.WIDTH + left + 320])
        greys = {(v & 0xE0) | ((v >> 3) & 0x1C) | (v >> 6) for v in range(0, 256, 17)}  # 3 bits red, 3 green, 2 blue
        self.assertTrue(set(row) <= greys, sorted(set(row)))
        self.assertGreater(len(set(row)), 4)

    def test_engine_stops_when_the_window_goes(self):
        engine, _device, player = self.play(indexed=True)
        self.assertTrue(self.show_until(player, lambda: player.frames_shown >= 2))
        engine.connection.close()
        self.assertEqual(engine.process.wait(10), 0)


if __name__ == "__main__":
    unittest.main()
