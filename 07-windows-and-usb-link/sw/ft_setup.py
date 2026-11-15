#!/usr/bin/env python3
"""Usage: python sw/ft_setup.py [--index N]           show the FT2232H's EEPROM settings
       python sw/ft_setup.py [--index N] --write   set both channels to 245 FIFO and the name to DTGC, then check

Once per chip, before the first FIFO use. Unplug and replug the USB cable after --write.
Needs the `ftd2xx` package and FTDI's D2XX driver. Never yet run on a real chip (docs/verify.md).
The chip must have an EEPROM fitted, which not every breakout module does.
"""
import argparse
import sys

# Names from the ftd2xx package's ft_program_data, field by field as the FT2232H uses them.
WANTED = {
    "IFAIsFifo7": 1, "IFAIsFifoTar7": 0, "IFAIsFastSer7": 0, "AIsVCP7": 0,
    "IFBIsFifo7": 1, "IFBIsFifoTar7": 0, "IFBIsFastSer7": 0, "BIsVCP7": 0,
    # The name the chip gives Windows. FTDI's own driver may still show its usual name in Device Manager, with this
    # one under "Bus reported device description" (docs/windows-device.md).
    "Manufacturer": b"DTGC", "ManufacturerId": b"DT", "Description": b"DTGC USB Graphics",
}


def differences(data):
    """The settings that are not yet what FIFO mode needs, as {name: (now, wanted)}."""
    return {name: (getattr(data, name), want) for name, want in WANTED.items() if getattr(data, name) != want}


def setup(device, write, show=print):
    """Returns True when the EEPROM ends up right."""
    data = device.eeRead()
    for name in WANTED:
        show(f"{name:15} {getattr(data, name)}")
    wrong = differences(data)
    if not wrong:
        show("Already set for FIFO mode. Nothing to do.")
        return True
    show(f"{len(wrong)} settings differ: {', '.join(wrong)}")
    if not write:
        show("Nothing changed. Add --write to change them.")
        return False

    for name, want in WANTED.items():
        setattr(data, name, want)
    device.eeProgram(data)
    still_wrong = differences(device.eeRead())
    if still_wrong:
        show(f"FAILED: still different after writing: {', '.join(still_wrong)}")
        return False
    show("Written and read back correctly. Unplug and replug the USB cable now.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=int, default=0, help="which FT2232H, 0 for the first")
    parser.add_argument("--write", action="store_true", help="change the EEPROM")
    args = parser.parse_args()

    import ftd2xx

    device = ftd2xx.open(args.index)
    try:
        ok = setup(device, args.write)
    finally:
        device.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
