# Making Windows see DTGC as a device

There are three levels. Each one takes more work than the one before, and only the first has a clear path on real hardware.

| Level | What you get | Status |
|---|---|---|
| 1. Name on the USB chip | The FT2232H board reports "DTGC USB Graphics" | Written in `sw/ft_setup.py`. Needs the real chip: VERIFY |
| 2. Software device | A "DTGC" entry in Device Manager while the tool runs | Built. Windows refused it without admin rights, so it is untested |
| 3. Indirect display driver | Windows gets an extra monitor that draws on DTGC | Not built. Needs the Windows Driver Kit and a test machine |

## Level 1: name on the USB chip (xDTGC only)

`python sw/ft_setup.py` writes our name to the FT2232H's settings memory. FTDI's driver may still show its usual name, "USB Serial Converter A/B", with ours under *Details → Bus reported device description*. The Tang Nano's own USB chip (BL616) cannot be renamed by us.

## Level 2: software device

`build/device/dtgc_device.exe` asks Windows to create a device with `SwDeviceCreate`. The entry lasts while the tool runs. Without admin rights Windows answers `FAIL SwDeviceCreate: 0x80070005` (access denied), so this needs your admin terminal.

**Before you start:** this adds a temporary Device Manager entry and changes nothing else.

1. Open the Start menu, type `terminal`, right-click **Terminal**, and choose **Run as administrator**.
   Expected: the title bar says Administrator.
2. Run these two commands:
   ```
   cd C:\Users\User\Documents\tinygpu
   build\device\dtgc_device.exe
   ```
   Expected: a line starting with `PASS`.
3. Open Device Manager, then choose **View → Show hidden devices**.
   Expected: a DTGC entry, probably under **Software devices**. It may carry a warning mark because it has no driver. This has not been tested yet, so note exactly what you see.
4. Press Ctrl+C in the terminal.
   Expected: the tool exits and the entry goes away.

If step 2 prints anything else, send me the exact line.

This entry shows that Windows knows about DTGC. It does not make Windows draw on it, and it does not put DTGC in Task Manager's GPU tab.

## Level 3: indirect display driver

An *indirect display driver* (built on Microsoft's IddCx framework) makes Windows treat a device as a real monitor and hand it finished desktop pictures. It is the right way to get an extended desktop over USB.

| What it needs | Why |
|---|---|
| Windows Driver Kit, about 3 GB or more (VERIFY the size on Microsoft's page) | The driver headers and build tools are not on this PC |
| A virtual machine, plus a Windows install image | A driver bug can crash Windows, so it should not be tested on your main system first |
| Test-signing turned on in that machine | Windows refuses unsigned drivers. Turning this on is a security setting, so you would have to do it yourself |
| A real signature, to give it to other people | Requires a paid certificate and Microsoft's signing process |

This PC runs Windows 11 Home, so Hyper-V Manager is not available. VirtualBox or QEMU would be needed. None of these have been downloaded, because each download needs your approval.

## What Windows detects today (2026-11-12)

With none of the three levels above, Windows still notices the board in the ordinary way, and the app builds on that:

1. Plugging in the Tang Nano 20K should make a new COM port appear (VERIFY: seen on no real board yet).
2. The app tries each new USB serial port and says hello. A device that answers like a DTGC is a board.
3. The app's window comes to the front, its status line shows the port, and Windows shows a notification, "DTGC board found".
4. `python -m sw.dtgc check` lists the board's USB ports with the driver Windows gave each one.

That is detection by our app through Windows' serial port list. Windows itself still calls the board a serial device, not a graphics card. Only level 3 would change that.

What to expect even if it works: USB speed and the 340 × 340 8-bit picture limit it to a small, slow desktop. The HD builds scale that picture up on the monitor, but they add no detail. Whether Task Manager's GPU tab would list it is unconfirmed (see `docs/verify.md`). The tab normally lists full WDDM graphics adapters, and DTGC does not have the shaders those need.
