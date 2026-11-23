#!/usr/bin/env python3
"""Usage: python -m unittest sw.tests.test_flash

The flasher and the setup check, with no board. A small script stands in for openFPGALoader: it prints what the real
one printed on this PC with nothing plugged in, or a plain success, and writes down the arguments it was given.
"""
import argparse
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sw.dtgc import check, flash

sys.path.insert(0, "scripts")
import build_all  # noqa: E402

NO_BOARD = "unable to open ftdi device: -3 (device not found)\nJTAG init failed with: unable to open ftdi device"
STAND_IN = """import os, sys
open(os.environ["FAKE_LOADER_LOG"], "w").write("\\n".join(sys.argv[1:]))
if os.environ.get("FAKE_LOADER_MODE") == "noboard":
    print({no_board!r})
    sys.exit(1)
print("write to ram")
print("Load SRAM: [==================================================] 100.00%")
print("Done")
"""


def arguments(name=None, keep=False, detect=False, dry_run=False):
    return argparse.Namespace(name=name, keep=keep, detect=detect, dry_run=dry_run)


class Table(unittest.TestCase):
    def test_names_are_unique(self):
        self.assertEqual(len({row[0] for row in flash.BUILDS}), len(flash.BUILDS))
        self.assertEqual(len({row[1] for row in flash.BUILDS}), len(flash.BUILDS))

    def test_every_entry_is_a_design_the_build_script_makes_with_the_right_picture(self):
        made = {}
        for top, _cst, _sources, options in build_all.DESIGNS.values():
            name = options[options.index("--name") + 1] if "--name" in options else top
            params = dict(item.split("=") for item in options if "=" in item)
            made[name] = f"{params.get('WIDTH', 340)}x{params.get('HEIGHT', 340)}"
        for name, stem, picture, _link, _text in flash.BUILDS:
            self.assertIn(stem, made, name)
            if picture:
                self.assertEqual(picture, made[stem], name)

    def test_backpack_designs_are_marked(self):
        for _name, stem, _picture, link, _text in flash.BUILDS:
            self.assertEqual(link == "ft", stem.endswith("_ft"), stem)


class WithStandInLoader(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        folder = Path(self.folder.name)
        script = folder / "loader.py"
        script.write_text(STAND_IN.format(no_board=NO_BOARD))
        if sys.platform == "win32":
            self.loader = folder / "loader.cmd"
            self.loader.write_text(f'@"{sys.executable}" "{script}" %*\n')
        else:
            self.loader = folder / "loader"
            self.loader.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
            self.loader.chmod(self.loader.stat().st_mode | stat.S_IEXEC)
        self.log = folder / "arguments.txt"
        (folder / "top_gpu_1080p30x5.fs").write_text("not a real bitstream")
        (folder / "blink.fs").write_text("not a real bitstream")
        self.environment = mock.patch.dict(os.environ, {"DTGC_LOADER": str(self.loader), "FAKE_LOADER_LOG": str(self.log),
                                                        "DTGC_FIRMWARE": str(folder), "FAKE_LOADER_MODE": "ok"})
        self.environment.start()
        self.lines = []

    def tearDown(self):
        self.environment.stop()
        self.folder.cleanup()

    def said(self):
        return "\n".join(self.lines)

    def test_loads_into_memory_by_default(self):
        self.assertEqual(flash.main(arguments("1080p30x5"), self.lines.append), 0)
        given = self.log.read_text().splitlines()
        self.assertEqual(given[:2], ["-b", "tangnano20k"])
        self.assertNotIn("-f", given)
        self.assertTrue(given[-1].endswith("top_gpu_1080p30x5.fs"))
        self.assertIn("selftest", self.said())
        self.assertIn("384x216", self.said())

    def test_file_name_and_path_both_work(self):
        self.assertEqual(flash.main(arguments("top_gpu_1080p30x5"), self.lines.append), 0)
        self.assertEqual(flash.main(arguments(str(Path(self.folder.name) / "blink.fs")), self.lines.append), 0)
        self.assertTrue(self.log.read_text().splitlines()[-1].endswith("blink.fs"))

    def test_keep_writes_to_flash_and_warns(self):
        self.assertEqual(flash.main(arguments("blink", keep=True), self.lines.append), 0)
        self.assertIn("-f", self.log.read_text().splitlines())
        self.assertIn("has not been tried", self.said())

    def test_detect_only_asks(self):
        self.assertEqual(flash.main(arguments(detect=True), self.lines.append), 0)
        self.assertEqual(self.log.read_text().splitlines(), ["-b", "tangnano20k", "--detect"])

    def test_dry_run_runs_nothing(self):
        self.assertEqual(flash.main(arguments("blink", dry_run=True), self.lines.append), 0)
        self.assertFalse(self.log.exists())
        self.assertIn("blink.fs", self.said())

    def test_no_board_gets_plain_advice(self):
        with mock.patch.dict(os.environ, {"FAKE_LOADER_MODE": "noboard"}):
            self.assertEqual(flash.main(arguments("blink"), self.lines.append), 1)
        self.assertIn("unable to open ftdi device", self.said())
        self.assertIn("did not find the board", self.said())
        self.assertNotIn("finished without an error", self.said())

    def test_unknown_name(self):
        self.assertEqual(flash.main(arguments("nosuch"), self.lines.append), 2)
        self.assertFalse(self.log.exists())

    def test_design_not_built(self):
        with mock.patch.object(flash, "find_file", return_value=None):
            self.assertEqual(flash.main(arguments("colorbars"), self.lines.append), 2)
        self.assertIn("has not been built", self.said())

    def test_list_shows_what_is_built(self):
        self.assertEqual(flash.main(arguments(), self.lines.append), 0)
        self.assertIn("1080p30x5", self.said())

    def test_missing_loader_is_explained(self):
        with mock.patch.object(flash, "find_loader", return_value=None):
            self.assertEqual(flash.main(arguments("blink"), self.lines.append), 2)
        self.assertIn("OSS CAD Suite", self.said())

    def test_check_runs_and_reports(self):
        with mock.patch.object(check, "usb_devices", return_value=[]):
            check.report(self.lines.append)
        self.assertIn("pyserial", self.said())
        self.assertIn("No board is plugged in", self.said())
        self.assertEqual(self.log.read_text().splitlines(), ["-b", "tangnano20k", "--detect"])


class Drivers(unittest.TestCase):
    FTDI = ("USB\\VID_0403&PID_6010\\2023030621|usbccgp|USB Composite Device\n"
            "USB\\VID_0403&PID_6010&MI_00\\6&1A2B&0&0000|FTDIBUS|USB Serial Converter A\n"
            "USB\\VID_0403&PID_6010&MI_01\\6&1A2B&0&0001|FTDIBUS|USB Serial Converter B\n"
            "USB\\VID_1532&PID_024E&MI_00\\7&2DDC&0&0000|HidUsb|USB Input Device\n")

    def test_only_ftdi_style_devices_are_kept(self):
        devices = check.parse_devices(self.FTDI)
        self.assertEqual(len(devices), 3)
        self.assertEqual([check.port_number(d[0]) for d in devices], [None, 0, 1])

    def test_ftdi_driver_on_the_programming_port_is_pointed_out(self):
        text = "\n".join(check.driver_advice(check.parse_devices(self.FTDI)))
        self.assertIn("does not have a plain USB driver", text)
        self.assertIn("Leave port 1 alone", text)

    def test_plain_driver_on_the_programming_port_is_fine(self):
        text = "\n".join(check.driver_advice(check.parse_devices(self.FTDI.replace("0000|FTDIBUS", "0000|WinUSB"))))
        self.assertIn("what the loader wants", text)
        self.assertNotIn("does not have a plain USB driver", text)

    def test_nothing_plugged_in(self):
        self.assertIn("No board is plugged in", check.driver_advice([])[0])

    def test_real_no_board_text_is_recognised(self):
        self.assertIn("did not find the board", flash.explain(NO_BOARD))
        self.assertEqual(flash.explain("something new"), "")



class PortableLoader(unittest.TestCase):
    """The USB-stick folder carries openFPGALoader in loader\ beside dtgc.exe, and the app must use that copy."""

    def test_packaged_loader_is_found_first(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "dtgc.exe"
            (Path(folder) / "loader").mkdir()
            loader = Path(folder) / "loader" / "openFPGALoader.exe"
            loader.write_bytes(b"")
            with mock.patch.dict(os.environ, {"DTGC_EXE": str(exe)}):
                os.environ.pop("DTGC_LOADER", None)
                self.assertEqual(flash.find_loader(), str(loader))

    def test_keep_adds_the_flash_option(self):
        self.assertEqual(flash.command("L", Path("x.fs"), keep=True), ["L", "-b", flash.BOARD, "-f", "x.fs"])

if __name__ == "__main__":
    unittest.main()
