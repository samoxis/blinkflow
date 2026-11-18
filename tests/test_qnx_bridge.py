"""The QNX bridge (blinkflow.qnx.bridge): NDJSON round trip through both halves, UNIX -> TCP -> UNIX.
Standard library only.

    python3 -m pytest tests/test_qnx_bridge.py
"""
import json
import os
import socket
import tempfile
import threading
import unittest

from blinkflow.qnx import bridge


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RoundTrip(unittest.TestCase):
    def test_ndjson_passes_both_ways_untouched(self):
        d = tempfile.mkdtemp()
        robotd, local = os.path.join(d, "robotd.sock"), os.path.join(d, "brain-side.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(robotd)
        srv.listen(1)

        def fake_robotd():            # answers the call, then streams three notifications
            c, _ = srv.accept()
            f = c.makefile("rb")
            req = json.loads(f.readline())
            out = [{"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}}]
            out += [{"jsonrpc": "2.0", "method": "robot.state", "params": {"n": i}} for i in range(3)]
            c.sendall(b"".join(json.dumps(m).encode() + b"\n" for m in out))
            c.close()

        threading.Thread(target=fake_robotd, daemon=True).start()
        port = _free_port()
        bridge.expose([f"{port}={robotd}"], "127.0.0.1")
        bridge.offer([f"{local}=127.0.0.1:{port}"])

        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(5)
        c.connect(local)
        c.sendall(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{"hz":25}}\n')
        lines = [json.loads(x) for x in c.makefile("rb")]
        c.close()
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
        self.assertEqual([m["params"]["n"] for m in lines[1:]], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
