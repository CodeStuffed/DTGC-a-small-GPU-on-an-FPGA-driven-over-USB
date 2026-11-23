"""Looks at this PC and says what is ready and what is missing. It reads; it changes nothing.

Usage: python -m sw.dtgc check

It answers "do I need drivers?" on the PC that has the board plugged in:
  - which Python packages are there
  - whether openFPGALoader (the tool that loads a design onto the board) is found
  - which FPGA designs are built
  - what Windows sees on USB, and which driver each part of the board is using
  - whether the loader can reach the FPGA

A **driver** is the piece of Windows that speaks to a USB device. Two programs want the board: the loader, which uses the
programming port, and this app, which uses the serial port. On Windows they can need different drivers for those two
ports, and that is the usual reason a loader cannot find a board that Windows shows. docs/flash.md has the steps.

The USB ids below come from documents, not from a real board, so they stay marked VERIFY in docs/verify.md.
"""
import subprocess
import sys

from . import flash

FTDI_VENDOR = "0403"  # FTDI's USB vendor id. openFPGALoader's entry for this board looks for an FTDI-style device

PACKAGES = (
    ("serial", "pyserial", "the serial link to the board", True),
    ("numpy", "numpy", "the PC-drawn version and the pictures", True),
    ("PIL", "pillow", "screen mirroring", False),
    ("ftd2xx", "ftd2xx", "the xDTGC backpack's fast link only, with FTDI's D2XX driver", False),
)

# Windows driver names (the "service" of a device), and what each means for us.
DRIVERS = {
    "ftdibus": "FTDI's driver. The serial port and the backpack link work through it. The loader may not be able to open this port (VERIFY)",
    "ftser2k": "FTDI's serial port driver. This is the port the app talks to",
    "winusb": "the plain Windows USB driver. The loader can open this port; it is not a serial port any more",
    "libusbk": "a plain USB driver. The loader can open this port; it is not a serial port any more",
    "libusb0": "a plain USB driver. The loader can open this port; it is not a serial port any more",
    "usbccgp": "Windows' driver for a device with several ports. The ports are listed on their own lines",
    "usbser": "Windows' own serial port driver",
    "": "no driver. Windows shows it with a warning mark",
}

_QUERY = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'USB\\VID_*' -or $_.PNPDeviceID -like 'FTDIBUS\\*' } | "
          "ForEach-Object { \"$($_.PNPDeviceID)|$($_.Service)|$($_.Name)\" }")


def parse_devices(text):
    """Turns the query's lines into (device id, driver, name), keeping FTDI-style devices only."""
    devices = []
    for line in text.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and (f"VID_{FTDI_VENDOR}" in parts[0].upper() or parts[0].upper().startswith("FTDIBUS")):
            devices.append(tuple(parts))
    return devices


def usb_devices():
    """What Windows lists on USB with an FTDI-style id. None when it could not be asked (not Windows, or no PowerShell)."""
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _QUERY], capture_output=True, text=True,
                                timeout=60, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_devices(result.stdout)


def serial_ports():
    """(port, usb id or None, description) for each serial port. None when pyserial is missing."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    return [(port.device, f"{port.vid:04X}:{port.pid:04X}" if port.vid is not None else None, port.description)
            for port in list_ports.comports()]


def packages():
    found = []
    for module, name, use, needed in PACKAGES:
        try:
            __import__(module)
            present = True
        except Exception:  # a broken install counts as missing
            present = False
        found.append((name, present, use, needed))
    return found


def port_number(device_id):
    """Which port of a several-port device this line is: 0, 1, or None for the device as a whole."""
    upper = device_id.upper()
    if "&MI_" in upper:
        return int(upper.split("&MI_")[1][:2], 16)
    return None


def driver_advice(devices):
    """Plain lines about the drivers found. This is the answer to "do I need drivers?" for this PC."""
    if devices is None:
        return ["Could not ask this system for its USB devices. On Linux run lsusb and look for an id starting 0403."]
    if not devices:
        return ["No board is plugged in, or Windows does not see it. Use a USB-C cable that carries data, straight into the PC.",
                "With no board there is nothing to check a driver against. Run this again with the board plugged in."]
    lines = []
    programming = [d for d in devices if port_number(d[0]) == 0]
    for device_id, driver, name in devices:
        meaning = DRIVERS.get(driver.lower(), "a driver this check does not know")
        lines.append(f"  {name}: driver {driver or 'none'} ({meaning})")
        lines.append(f"      {device_id}")
    if any(d[1].lower() in ("winusb", "libusbk", "libusb0") for d in programming):
        lines.append("The programming port has a plain USB driver, which is what the loader wants.")
    elif programming:
        lines.append("The programming port (port 0) does not have a plain USB driver. If the loader below cannot open the board,")
        lines.append("that is the likely reason. docs/flash.md, section \"Drivers\", has the steps. Leave port 1 alone: it is the serial port.")
    return lines


def report(say=print, detect=True):
    """Prints the whole check. Returns True when nothing needed for the serial version is missing."""
    ready = True
    say(f"Python {sys.version.split()[0]} on {sys.platform}")
    say("")
    say("Python packages")
    for name, present, use, needed in packages():
        mark = "ok     " if present else ("MISSING" if needed else "absent ")
        say(f"  {mark} {name:9} {use}")
        if needed and not present:
            ready = False
            say(f"          install it with: python -m pip install {name}")
    say("")
    say("Loader")
    loader = flash.find_loader()
    if loader:
        code, output = flash.run([loader, "-V"], lambda _line: None)
        say(f"  ok      {output.strip() or 'openFPGALoader'} at {loader}")
    else:
        ready = False
        say("  MISSING openFPGALoader. It comes with the OSS CAD Suite (docs/setup.md)")
    built = flash.available()
    say("")
    say(f"Designs built: {len(built)} of {len(flash.BUILDS)}" + ("" if built else ". Run: python scripts/build_all.py"))
    say("")
    say("Serial ports")
    ports = serial_ports()
    for port, usb_id, text in ports or []:
        say(f"  {port:8} {usb_id or 'not USB':10} {text}")
    if ports is not None and not any(usb_id for _port, usb_id, _text in ports):
        say("  no USB serial port. The board's serial port should appear here when it is plugged in.")
    say("")
    say("USB devices with an FTDI-style id, and their drivers")
    devices = usb_devices()
    for line in driver_advice(devices):
        say(line)
    if loader and detect:
        say("")
        say("Asking the FPGA to say what it is")
        code, _output = flash.run(flash.command(loader), say)
        if code == 0:
            say("The loader reached the board. No driver change is needed for loading designs.")
        elif devices:
            say("Windows lists the board but the loader cannot open it. docs/flash.md, section \"Drivers\", has the steps.")
        else:
            say("The loader found no board either, which fits: nothing is plugged in.")
    return ready
