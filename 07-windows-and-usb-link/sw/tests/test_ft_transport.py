"""The FT2232H driver code against a stand-in for FTDI's library. It proves our calls and their order,
not that a real chip behaves this way.

Usage: python -m unittest sw.tests.test_ft_transport
"""
import types
import unittest

from sw import ft_setup
from sw.dtgc import emulator
from sw.dtgc.client import Dtgc
from sw.dtgc.transport import Ft2232hTransport


class FakeChip:
    """Answers like ftd2xx's device object, with an emulated GPU behind it."""

    def __init__(self, largest_write=None, fail_on=None):
        self.link = emulator.LocalTransport(emulator.Device())
        self.calls = []
        self.waiting = b""
        self.largest_write = largest_write
        self.fail_on = fail_on
        self.closed = False

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))
            if name == self.fail_on:
                raise OSError("stand-in failure")
        return record

    def write(self, data):
        if self.fail_on == "write":
            raise OSError("stand-in failure")
        count = len(data) if self.largest_write is None else min(self.largest_write, len(data))
        self.link.send(data[:count])
        return count

    def getQueueStatus(self):
        self.waiting += self.link.receive(0)
        return len(self.waiting)

    def read(self, count):
        data, self.waiting = self.waiting[:count], self.waiting[count:]
        return data

    def close(self):
        self.closed = True


def library_with(chip):
    return types.SimpleNamespace(open=lambda index: chip)


class Transport(unittest.TestCase):
    def test_starts_fifo_mode_in_order(self):
        chip = FakeChip()
        Ft2232hTransport(library=library_with(chip), settle=0)
        modes = [call for call in chip.calls if call[0] == "setBitMode"]
        self.assertEqual(modes, [("setBitMode", 0xFF, 0x00), ("setBitMode", 0xFF, 0x40)])
        self.assertEqual(chip.calls[-1][0], "purge")

    def test_gpu_answers_through_it(self):
        gpu = Dtgc(Ft2232hTransport(library=library_with(FakeChip()), settle=0))
        gpu.hello()
        gpu.ping()
        gpu.close()

    def test_short_writes_send_everything(self):
        gpu = Dtgc(Ft2232hTransport(library=library_with(FakeChip(largest_write=3)), settle=0))
        gpu.hello()
        gpu.close()

    def test_write_that_takes_nothing_is_an_error(self):
        link = Ft2232hTransport(library=library_with(FakeChip(largest_write=0)), settle=0)
        with self.assertRaises(ConnectionError):
            link.send(b"abc")

    def test_receive_with_nothing_is_empty(self):
        link = Ft2232hTransport(library=library_with(FakeChip()), settle=0)
        self.assertEqual(link.receive(0.001), b"")

    def test_failed_start_closes_the_chip(self):
        chip = FakeChip(fail_on="setUSBParameters")
        with self.assertRaises(ConnectionError):
            Ft2232hTransport(library=library_with(chip), settle=0)
        self.assertTrue(chip.closed)


class FakeEeprom:
    def __init__(self, stuck=False, **settings):
        self.data = types.SimpleNamespace(**{name: 0 for name in ft_setup.WANTED})
        self.data.AIsVCP7 = self.data.BIsVCP7 = 1
        vars(self.data).update(settings)
        self.programmed = 0
        self.stuck = stuck

    def eeRead(self):
        return types.SimpleNamespace(**vars(self.data))

    def eeProgram(self, data):
        self.programmed += 1
        if not self.stuck:
            self.data = data


class Setup(unittest.TestCase):
    def quiet(self, _line):
        pass

    def test_looking_changes_nothing(self):
        chip = FakeEeprom()
        self.assertFalse(ft_setup.setup(chip, write=False, show=self.quiet))
        self.assertEqual(chip.programmed, 0)

    def test_write_sets_fifo_on_both_channels(self):
        chip = FakeEeprom()
        self.assertTrue(ft_setup.setup(chip, write=True, show=self.quiet))
        self.assertEqual(chip.programmed, 1)
        self.assertEqual(ft_setup.differences(chip.data), {})

    def test_right_already_writes_nothing(self):
        chip = FakeEeprom(**ft_setup.WANTED)
        self.assertTrue(ft_setup.setup(chip, write=True, show=self.quiet))
        self.assertEqual(chip.programmed, 0)

    def test_failed_write_is_reported(self):
        self.assertFalse(ft_setup.setup(FakeEeprom(stuck=True), write=True, show=self.quiet))


if __name__ == "__main__":
    unittest.main()
