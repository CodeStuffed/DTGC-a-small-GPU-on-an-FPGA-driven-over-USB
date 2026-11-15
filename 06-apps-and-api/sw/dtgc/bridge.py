"""Passes bytes between a TCP port and the board, so programs that only speak TCP can reach real hardware.

Usage: python -m sw.dtgc --serial COM5 --port 7654 bridge    (or --ft2232h 0 in place of --serial)

The bytes are not looked at. Checking and resending stay with the program at the far end (sw/d3d9 or Dtgc).
"""
import socket
import threading


def _to_link(connection, link, stop):
    try:
        while not stop.is_set():
            data = connection.recv(65536)
            if not data:
                break
            link.send(data)
    except OSError:
        pass
    stop.set()


def serve_one(connection, link):
    """Runs until the program at the far end closes its connection."""
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    stop = threading.Event()
    threading.Thread(target=_to_link, args=(connection, link, stop), daemon=True).start()
    try:
        while not stop.is_set():
            data = link.receive(0.01)
            if data:
                connection.sendall(data)
    except OSError:
        stop.set()
    connection.close()


def run(link, port=7654, out=print):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen()
    out(f"Bridge listening on port {port}. Ctrl+C stops it.")
    try:
        while True:
            connection, _ = listener.accept()
            serve_one(connection, link)
    finally:
        listener.close()
        link.close()
