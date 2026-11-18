"""Carry the robot's UNIX sockets over TCP, so the brain can run on a QNX target (VM or board)
while the simulator stays on the host.

    host:    python3 bridge.py expose --map 7701=~/.cache/duck-sim/duck-a.sock --map 7702=~/.cache/duck-sim/duck-a-tof.sock
    target:  python3 bridge.py offer  --map /tmp/robotd.sock=10.0.2.2:7701 --map /tmp/tof.sock=10.0.2.2:7702
    target:  microduck-brain --robot-socket /tmp/robotd.sock --tof-socket /tmp/tof.sock

10.0.2.2 is the host as QEMU's user network shows it to the guest. `expose` binds 127.0.0.1 by default.
Bytes pass through untouched (the brain speaks NDJSON JSON-RPC); the bridge never parses them.
One file, standard library only, Python 3.11+: it is copied to the target on its own.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading

CHUNK = 65536


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while data := src.recv(CHUNK):
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s, how in ((dst, socket.SHUT_WR), (src, socket.SHUT_RD)):
            try:
                s.shutdown(how)
            except OSError:
                pass


def _join(a: socket.socket, b: socket.socket) -> None:
    """Copy both ways until both sides are done, then close both."""
    back = threading.Thread(target=_pump, args=(b, a), daemon=True)
    back.start()
    _pump(a, b)
    back.join()
    a.close()
    b.close()


def _tcp(host: str, port: int) -> socket.socket:
    s = socket.create_connection((host, port), timeout=3.0)
    s.settimeout(None)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def _unix(path: str) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    return s


def _serve(listener: socket.socket, dial, name: str) -> None:
    while True:
        try:
            client, _ = listener.accept()
        except OSError:                      # the listener was closed (stop)
            return
        if client.family != socket.AF_UNIX:
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            far = dial()
        except OSError as e:
            print(f"bridge {name}: cannot reach the far side: {e}", file=sys.stderr, flush=True)
            client.close()
            continue
        threading.Thread(target=_join, args=(client, far), daemon=True).start()


def stop(listener: socket.socket) -> None:
    """Stop accepting (connections already joined run on until their ends close)."""
    try:
        listener.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    listener.close()


def expose(maps: list[str], bind: str) -> list[socket.socket]:
    """Host side: TCP port -> existing UNIX socket. Returns the listeners (see stop)."""
    listeners = []
    for m in maps:
        port, path = m.split("=", 1)
        path = os.path.expanduser(path)
        ls = socket.create_server((bind, int(port)), reuse_port=False)
        print(f"bridge: tcp {bind}:{port} -> unix {path}", flush=True)
        threading.Thread(target=_serve, args=(ls, lambda p=path: _unix(p), port), daemon=True).start()
        listeners.append(ls)
    return listeners


def offer(maps: list[str]) -> list[socket.socket]:
    """Target side: new local UNIX socket -> TCP port on the host. Returns the listeners (see stop)."""
    listeners = []
    for m in maps:
        path, addr = m.split("=", 1)
        host, port = addr.rsplit(":", 1)
        if os.path.exists(path):
            os.unlink(path)
        ls = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ls.bind(path)
        ls.listen(8)
        print(f"bridge: unix {path} -> tcp {host}:{port}", flush=True)
        threading.Thread(target=_serve, args=(ls, lambda h=host, p=int(port): _tcp(h, p), path), daemon=True).start()
        listeners.append(ls)
    return listeners


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    e = sub.add_parser("expose", help="host: TCP port -> existing UNIX socket")
    e.add_argument("--map", action="append", required=True, metavar="PORT=UNIX_PATH")
    e.add_argument("--bind", default="127.0.0.1")
    o = sub.add_parser("offer", help="target: new UNIX socket -> host TCP port")
    o.add_argument("--map", action="append", required=True, metavar="UNIX_PATH=HOST:PORT")
    a = ap.parse_args(argv)
    listeners = expose(a.map, a.bind) if a.mode == "expose" else offer(a.map)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    for ls in listeners:
        stop(ls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
