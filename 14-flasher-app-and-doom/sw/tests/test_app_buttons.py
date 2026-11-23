#!/usr/bin/env python3
"""Usage: python -m unittest sw.tests.test_app_buttons

The app's newer parts: loading a design, the setup check, Doom, the picture list and the notification when a board
is found. No board is used. The notification test starts the real system command once, so a small "DTGC test" note
may appear on this PC's screen while it runs; set DTGC_NO_NOTE=1 to leave that test out.
"""
import os
import sys
import unittest
from unittest import mock

from sw.dtgc import app, flash

sys.path.insert(0, "scripts")
import build_all  # noqa: E402


class Buttons(unittest.TestCase):
    def test_check_is_there_for_every_version(self):
        for version, _label in app.VERSIONS:
            self.assertEqual(app.arguments_for(version, "check"), ["check"])

    def test_doom_goes_to_a_window_without_a_board(self):
        self.assertEqual(app.arguments_for("laptop", "doom"), ["doom", "--window"])
        self.assertEqual(app.arguments_for("hdmi", "doom"), ["doom"])
        self.assertIsNone(app.arguments_for("usb", "doom"))

    def test_load_command_is_one_the_program_accepts(self):
        self.assertEqual(app.run_command([*app.flash_arguments("blink"), "--help"], lambda _line: None), 0)
        self.assertEqual(app.flash_arguments("blink", keep=True), ["flash", "blink", "--keep"])

    def test_every_button_has_a_label_and_a_different_action(self):
        actions = [action for _label, action in app.ACTIONS]
        self.assertEqual(len(set(actions)), len(actions))
        for wanted in ("doom", "check"):
            self.assertIn(wanted, actions)


class Pictures(unittest.TestCase):
    def test_every_picture_a_design_draws_can_be_chosen(self):
        offered = {name for name, _label in app.PICTURES}
        for _name, _stem, picture, _link, _text in flash.BUILDS:
            if picture:
                self.assertIn(picture, offered)

    def test_every_choice_is_a_size_some_design_draws(self):
        made = set()
        for _top, _cst, _sources, options in build_all.DESIGNS.values():
            params = dict(item.split("=") for item in options if "=" in item)
            made.add(f"{params.get('WIDTH', 340)}x{params.get('HEIGHT', 340)}")
        for name, _label in app.PICTURES:
            self.assertIn(name, made)

    def test_designs_list_matches_what_is_built(self):
        rows = [("blink", "blink.fs", None, None, "an LED blinks"), ("1080p30x5", "x.fs", "384x216", "usb", "the GPU")]
        with mock.patch.object(flash, "available", return_value=rows):
            self.assertEqual(app.designs(), [("blink", None, "an LED blinks"), ("1080p30x5", "384x216", "the GPU")])


class Notification(unittest.TestCase):
    def test_words_never_become_part_of_the_command(self):
        nasty = "'; Remove-Item x; \"$(calc)\""
        found = app.notification_command(nasty, nasty)
        if found is None:
            self.skipTest("this system has no notification command")
        command, extra = found
        if sys.platform == "win32":
            self.assertFalse(any(nasty in part for part in command))
            self.assertEqual(extra, {"DTGC_NOTE_TITLE": nasty, "DTGC_NOTE_TEXT": nasty})
        else:
            self.assertEqual(command[-3:], ["--", nasty, nasty])

    def test_missing_program_is_not_an_error(self):
        with mock.patch.object(app, "notification_command", return_value=(["no-such-program-dtgc"], {})):
            self.assertIsNone(app.notify("a", "b"))
        with mock.patch.object(app, "notification_command", return_value=None):
            self.assertIsNone(app.notify("a", "b"))

    @unittest.skipIf(os.environ.get("DTGC_NO_NOTE"), "DTGC_NO_NOTE is set")
    @unittest.skipUnless(sys.platform == "win32", "the Windows notification")
    def test_the_real_command_runs_without_an_error(self):
        process = app.notify("DTGC test", "This note comes from the DTGC tests.")
        self.assertIsNotNone(process)
        self.assertEqual(process.wait(60), 0)


if __name__ == "__main__":
    unittest.main()
