#!/usr/bin/env python3
"""Usage: python -m unittest sw.tests.test_board_watcher

The part of the app that notices a board. Fake port lists stand in for USB, as this runs with no board.
"""
import unittest

from sw.dtgc.app import BoardWatcher


class Watcher(unittest.TestCase):
    def setUp(self):
        self.ports = []
        self.boards = set()
        self.hellos = []

    def says_hello(self, port):
        self.hellos.append(port)
        return port in self.boards

    def watcher(self):
        return BoardWatcher(lambda: self.ports, self.says_hello)

    def test_nothing_plugged_in(self):
        self.assertIsNone(self.watcher().poll())
        self.assertEqual(self.hellos, [])

    def test_board_is_found_once(self):
        watcher = self.watcher()
        self.ports, self.boards = ["COM5"], {"COM5"}
        self.assertEqual(watcher.poll(), "COM5")
        self.assertIsNone(watcher.poll())
        self.assertEqual(self.hellos, ["COM5"])

    def test_other_device_is_left_alone_after_one_try(self):
        watcher = self.watcher()
        self.ports = ["COM3"]
        self.assertIsNone(watcher.poll())
        self.assertIsNone(watcher.poll())
        self.assertEqual(self.hellos, ["COM3"])

    def test_board_is_found_again_after_replugging(self):
        watcher = self.watcher()
        self.ports, self.boards = ["COM5"], {"COM5"}
        self.assertEqual(watcher.poll(), "COM5")
        self.ports = []
        self.assertIsNone(watcher.poll())
        self.ports = ["COM5"]
        self.assertEqual(watcher.poll(), "COM5")

    def test_board_behind_another_device_is_found(self):
        watcher = self.watcher()
        self.ports, self.boards = ["COM3", "COM5"], {"COM5"}
        self.assertEqual(watcher.poll(), "COM5")
        self.assertEqual(self.hellos, ["COM3", "COM5"])


if __name__ == "__main__":
    unittest.main()
