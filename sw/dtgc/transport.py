"""Links between the PC and the GPU, all behind one small interface.

Usage: from sw.dtgc.transport import TcpTransport, SerialTransport, Ft2232hTransport. Each has send(bytes),
receive(timeout) returning bytes (empty when nothing arrived) and close().
"""
import socket
import time


class Transport:
    def send(self, data):
        raise NotImplementedError

    def receive(self, timeout):
        raise NotImplementedError

    def close(self):
        pass


class TcpTransport(Transport):
    """Talks to the emulator."""

    def __init__(self, host="127.0.0.1", port=7654, connect_timeout=1.0):
        self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send(self, data):
        self.sock.sendall(data)

    def receive(self, timeout):
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return b""
        if not data:
            raise ConnectionError("the link closed")
        return data

    def close(self):
        self.sock.close()


class SerialTransport(Transport):
    """Talks to the Tang Nano 20K over its USB serial port. Needs pyserial.

    The default baud rate is what rtl/uart_rx.v is built for. The bridge chip's real maximum is
    still unmeasured (docs/verify.md).
    """

    def __init__(self, port, baud=3000000):
        import serial

        self.serial = serial.Serial(port, baudrate=baud, timeout=0, write_timeout=1.0)

    def send(self, data):
        try:
            self.serial.write(data)
        except Exception as error:
            raise ConnectionError(f"serial write failed: {error}") from error

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            data = self.serial.read(4096)
            if data or time.monotonic() >= deadline:
                return data
            time.sleep(0.0005)

    def close(self):
        self.serial.close()


class Ft2232hTransport(Transport):
    """FT2232H synchronous FIFO link, for the breakout module and the xDTGC backpack.

    Needs the `ftd2xx` package and FTDI's D2XX driver, and the chip's EEPROM set up once with
    sw/ft_setup.py. Tested only against a stand-in, never a real chip (docs/verify.md). `library`
    exists so the tests can pass that stand-in.
    """

    # From FTDI AN_130 and the D2XX guide. VERIFY on the real chip.
    MODE_RESET = 0x00
    MODE_SYNC_FIFO = 0x40
    ALL_PINS = 0xFF
    FLOW_RTS_CTS = 0x0100
    PURGE_BOTH = 3
    LATENCY_MS = 2
    USB_TRANSFER = 0x10000
    WRITE_TIMEOUT_MS = 1000

    def __init__(self, index=0, library=None, settle=0.05):
        if library is None:
            import ftd2xx as library

        try:
            self.device = library.open(index)
        except Exception as error:
            raise ConnectionError(f"could not open FT2232H {index}: {error}") from error
        try:
            # The chip's 60 MHz clock starts here, and the FPGA can only move a byte after that.
            self.device.setBitMode(self.ALL_PINS, self.MODE_RESET)
            time.sleep(settle)
            self.device.setBitMode(self.ALL_PINS, self.MODE_SYNC_FIFO)
            self.device.setLatencyTimer(self.LATENCY_MS)
            self.device.setUSBParameters(self.USB_TRANSFER, self.USB_TRANSFER)
            self.device.setFlowControl(self.FLOW_RTS_CTS, 0, 0)
            self.device.setTimeouts(self.WRITE_TIMEOUT_MS, self.WRITE_TIMEOUT_MS)
            self.device.purge(self.PURGE_BOTH)
        except Exception as error:
            self.device.close()
            raise ConnectionError(f"could not start FIFO mode: {error}") from error

    def send(self, data):
        data = bytes(data)
        while data:
            try:
                written = self.device.write(data)
            except Exception as error:
                raise ConnectionError(f"FT2232H write failed: {error}") from error
            if not written:
                raise ConnectionError("FT2232H took no bytes: is the FPGA loaded and reading?")
            data = data[written:]

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            try:
                waiting = self.device.getQueueStatus()
                if waiting:
                    return self.device.read(waiting)
            except Exception as error:
                raise ConnectionError(f"FT2232H read failed: {error}") from error
            if time.monotonic() >= deadline:
                return b""
            time.sleep(0.0005)

    def close(self):
        self.device.close()


class RecordingTransport(Transport):
    """Wraps another link and saves everything sent, for `python -m sw.dtgc replay`."""

    def __init__(self, inner, path):
        self.inner = inner
        self.file = open(path, "wb")

    def send(self, data):
        self.file.write(data)
        self.inner.send(data)

    def receive(self, timeout):
        return self.inner.receive(timeout)

    def close(self):
        self.file.close()
        self.inner.close()
