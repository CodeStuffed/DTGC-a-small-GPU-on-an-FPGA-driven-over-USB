"""DTGC command line.

Usage: python -m sw.dtgc emulator [options]    start the emulator (--help for its options)
       python -m sw.dtgc selftest              check the link, prints PASS or FAIL
       python -m sw.dtgc bars                  draw colour bars
       python -m sw.dtgc spin [--frames N] [--scene cube|field]     draw a spinning 3D cube, or the field of cubes
       python -m sw.dtgc record FILE           draw colour bars, saving what was sent to FILE
       python -m sw.dtgc replay FILE           send a saved recording again
       python -m sw.dtgc benchmark [--frames N]  measure bytes per frame (built-in emulator unless --serial)
       python -m sw.dtgc play pong|maze|dodge  play a game (on the GPU if found, else in a window)
       python -m sw.dtgc laptop [--demo NAME]  no board: this PC's graphics card draws, and the picture fits any screen
       python -m sw.dtgc view [--demo NAME]    USB-output version: the board draws and this PC shows the picture
       python -m sw.dtgc screenshot FILE.png   read the picture back from the board and save it, no monitor needed
       python -m sw.dtgc bridge                let the Direct3D 9 layer (sw/d3d9) reach a real board, on --port
       python -m sw.dtgc app [--watch]         a window with a button for each of these. --watch starts it minimised,
                                               and it comes to the front when a board is plugged in
Set DTGC_PICTURE=960x540 in the environment for a board built for 1080p30. The app's window has a choice for this.
Common options: --serial PORT, --ft2232h INDEX, --baud N, --port N (emulator TCP port)
"""
import argparse
import sys
import time

from . import app, benchmark, demo, emulator, games
from . import protocol as p
from .client import CommandError, Dtgc, LinkError, connect_auto
from .transport import Ft2232hTransport, RecordingTransport, SerialTransport, TcpTransport


def draw_bars(gpu):
    """Eight vertical bars across the RRRGGGBB default palette."""
    colors = [0xFF, 0xFC, 0x1F, 0x1C, 0xE3, 0xE0, 0x03, 0x00]
    width = p.WIDTH // len(colors)
    for i, color in enumerate(colors):
        gpu.rect(i * width, 0, width if i < 7 else p.WIDTH - i * width, p.HEIGHT, color)
    gpu.swap()
    gpu.flush()


def read_back_check(gpu):
    """Puts a known pattern in the memory and reads it from there. A mismatch points at the SDRAM or the link."""
    pattern = bytes((i * 37 + 11) & 0xFF for i in range(3 * p.WIDTH))
    for row in range(3):
        gpu.span(0, 200 + row, pattern[row * p.WIDTH:(row + 1) * p.WIDTH])
    gpu.swap()
    if gpu.read_rect(0, 200, p.WIDTH, 3) != pattern:
        raise LinkError("the picture read back is not what was drawn")


def selftest(gpu):
    """Link checks. Passing proves the GPU answers and accepts commands, not what is on screen."""
    checks = []

    def check(name, action):
        try:
            action()
            checks.append((name, True, ""))
        except (LinkError, CommandError, OSError) as error:
            checks.append((name, False, str(error)))

    check("hello", gpu.hello)
    check("ping x100", lambda: [gpu.ping() for _ in range(100)])
    check("clear", lambda: gpu.clear(0))
    check("largest span", lambda: (gpu.span(0, 0, bytes(1020)), gpu.flush()))
    check("rect off the edge", lambda: (gpu.rect(330, 330, 100, 100, 7), gpu.flush()))
    check("palette", lambda: (gpu.palette(0, [(0, 0, 0)]), gpu.flush()))
    check("swap", lambda: (gpu.swap(), gpu.flush()))
    check("read the picture back", lambda: read_back_check(gpu))

    def must_refuse():
        gpu._send(0x7F)
        try:
            gpu.flush()
        except CommandError:
            return
        raise LinkError("an unknown command was accepted")

    check("unknown command refused", must_refuse)
    for name, ok, why in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{': ' + why if why else ''}")
    return all(ok for _, ok, _ in checks)


def replay(transport, data, timeout=2.0):
    """Sends a recording one packet at a time, waiting for each reply, so no buffer can fill."""
    finder, replies = p.Parser(), p.Parser()
    answered = 0
    for byte in data:
        packet = finder.feed(byte)
        if not packet:
            continue
        transport.send(p.encode(packet.kind, packet.seq, packet.payload))
        deadline = time.monotonic() + timeout
        got = None
        while not got:
            if time.monotonic() > deadline:
                raise LinkError(f"no reply to packet {packet.seq}")
            for reply_byte in transport.receive(0.01):
                got = replies.feed(reply_byte) or got
        answered += 1
    return answered


def run_emulator(args):
    faults = emulator.LinkFaults(args.rate, args.drop, args.corrupt, args.disconnect_after, args.seed)
    server = emulator.Server(args.port, faults, args.png_dir)
    print(f"DTGC emulator listening on port {server.port}. Ctrl+C stops it.", flush=True)
    if args.window:
        server.start()
        emulator.show_window(server)
    else:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def open_gpu(args):
    if args.ft2232h is not None:
        return Dtgc(Ft2232hTransport(args.ft2232h))
    if args.serial:
        return Dtgc(SerialTransport(args.serial, args.baud))
    return connect_auto(args.port, args.baud)


def open_raw_link(args):
    """The link itself, with no packet handling: the program at the other end of the bridge does that."""
    if args.ft2232h is not None:
        return Ft2232hTransport(args.ft2232h)
    if args.serial:
        return SerialTransport(args.serial, args.baud)
    sys.exit("Name the board with --serial PORT or --ft2232h INDEX.")


def run_game(args):
    """With no GPU or emulator to talk to, the game runs on a private emulator and shows in its own window."""
    device = None
    try:
        gpu = open_gpu(args)
    except LinkError:
        device = emulator.Device()
        gpu = Dtgc(emulator.LocalTransport(device))
    games.play(args.game, gpu, device, frames=args.frames)
    gpu.close()


def main():
    parser = argparse.ArgumentParser(prog="python -m sw.dtgc", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--serial", help="serial port (default: search, then emulator)")
    parser.add_argument("--ft2232h", type=int, metavar="INDEX", help="use the FT2232H link, 0 for the first chip")
    parser.add_argument("--baud", type=int, default=3000000)
    parser.add_argument("--port", type=int, default=7654, help="emulator TCP port")
    commands = parser.add_subparsers(dest="command", required=True)

    emu = commands.add_parser("emulator")
    emu.add_argument("--window", action="store_true", help="show the picture live")
    emu.add_argument("--png-dir", help="save a PNG of each frame to this folder")
    emu.add_argument("--rate", type=float, help="limit the link to this many bytes per second")
    emu.add_argument("--drop", type=float, default=0.0, help="chance each byte is lost")
    emu.add_argument("--corrupt", type=float, default=0.0, help="chance each byte is damaged")
    emu.add_argument("--disconnect-after", type=int, help="pull the plug every N bytes")
    emu.add_argument("--seed", type=int, default=1)

    commands.add_parser("selftest")
    commands.add_parser("bars")
    spin = commands.add_parser("spin")
    spin.add_argument("--frames", type=int, default=150)
    spin.add_argument("--scene", choices=("cube", "field"), default="cube")
    commands.add_parser("record").add_argument("file")
    commands.add_parser("replay").add_argument("file")
    commands.add_parser("benchmark").add_argument("--frames", type=int, default=6)
    play = commands.add_parser("play")
    play.add_argument("game", choices=sorted(games.GAMES))
    play.add_argument("--frames", type=int, help="stop after this many frames")
    commands.add_parser("app").add_argument("--watch", action="store_true")
    commands.add_parser("bridge", help="pass bytes between a TCP port and the board")
    demos = ("cube", "field", "bars", "pong", "maze", "dodge")
    laptop_cmd = commands.add_parser("laptop", help="draw with this PC's graphics card, no board")
    laptop_cmd.add_argument("--demo", choices=demos, help="with none, wait for other commands to draw here")
    laptop_cmd.add_argument("--exact", action="store_true", help="what the real hardware would draw, scaled up")
    laptop_cmd.add_argument("--no-vsync", action="store_true", help="do not wait for the screen, to measure speed")
    view_cmd = commands.add_parser("view", help="USB output: the board draws and this PC shows the picture")
    view_cmd.add_argument("--demo", choices=demos, default="cube")
    for command in (laptop_cmd, view_cmd):
        command.add_argument("--fullscreen", action="store_true")
        command.add_argument("--tk", action="store_true", help="the plain window, which needs no OpenGL. Always used outside Windows")
        command.add_argument("--frames", type=int, help="stop after this many frames")
    commands.add_parser("screenshot").add_argument("file")
    show = commands.add_parser("mirror", help="show the PC's screen on the GPU's HDMI output")
    show.add_argument("--frames", type=int, help="stop after this many frames")
    show.add_argument("--fps", type=float, default=15)
    show.add_argument("--no-dither", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "emulator":
            run_emulator(args)
        elif args.command == "selftest":
            gpu = open_gpu(args)
            passed = selftest(gpu)
            gpu.close()
            print("PASS" if passed else "FAIL")
            sys.exit(0 if passed else 1)
        elif args.command == "bars":
            gpu = open_gpu(args)
            draw_bars(gpu)
            gpu.close()
        elif args.command == "spin":
            gpu = open_gpu(args)
            demo.run(gpu, args.frames, scene=args.scene)
            gpu.close()
        elif args.command == "record":
            gpu = open_gpu(args)
            gpu.transport = RecordingTransport(gpu.transport, args.file)
            gpu.hello()
            draw_bars(gpu)
            gpu.close()
            print(f"Saved to {args.file}")
        elif args.command == "benchmark":
            server = None
            if args.serial:
                gpu = Dtgc(SerialTransport(args.serial, args.baud))
            else:
                server = emulator.Server(0).start()
                gpu = Dtgc(TcpTransport(port=server.port))
                print("Built-in emulator: bytes are real, times only describe this PC.\n")
            benchmark.report(gpu, args.frames)
            gpu.close()
            if server:
                server.stop()
        elif args.command == "play":
            run_game(args)
        elif args.command == "app":
            app.main(watch=args.watch)
        elif args.command == "bridge":
            from . import bridge
            bridge.run(open_raw_link(args), args.port)
        elif args.command == "mirror":
            from . import mirror
            gpu = open_gpu(args)
            mirror.run(gpu, args.frames, args.fps, not args.no_dither)
            gpu.close()
        elif args.command == "laptop":
            from . import laptop, tkwindow
            if laptop.glwindow is None or args.tk:
                tkwindow.run(args.demo or "cube", None, args.fullscreen, args.frames)
            elif args.demo:
                laptop.run_demo(args.demo, args.exact, args.fullscreen, args.frames, not args.no_vsync)
            else:
                laptop.serve(args.port, args.exact, args.fullscreen, args.frames, not args.no_vsync)
        elif args.command == "view":
            from . import laptop, tkwindow
            gpu = open_gpu(args)
            if laptop.glwindow is None or args.tk:
                tkwindow.run(args.demo, gpu, args.fullscreen, args.frames)
            else:
                laptop.view(gpu, args.demo, args.fullscreen, args.frames)
            gpu.close()
        elif args.command == "screenshot":
            gpu = open_gpu(args)
            pixels = gpu.read_frame()
            rgb = b"".join(bytes(color) for color in map(emulator.default_palette().__getitem__, pixels))
            emulator.write_png(args.file, p.WIDTH, p.HEIGHT, rgb)
            gpu.close()
            print(f"Saved {args.file}, using the default colours")
        elif args.command == "replay":
            transport = SerialTransport(args.serial, args.baud) if args.serial else TcpTransport(port=args.port)
            with open(args.file, "rb") as f:
                data = f.read()
            answered = replay(transport, data)
            transport.close()
            print(f"Replayed {len(data)} bytes, {answered} packets answered")
    except (LinkError, CommandError) as error:
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
