"""blinkflow.qnx.target without a target: where the host's half of the bridge listens, and what a
dead target looks like to the clock. No VM, no simulator.

    python3 -m unittest tests.test_qnx_target -v
"""
import socket
import unittest
from unittest import mock

from blinkflow.qnx import bridge, target


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Fake(target.Target):
    """A target whose SSH is a local command."""
    def __init__(self, cmd, **kw):
        super().__init__(**kw)
        self.cmd = cmd

    def _ssh(self):
        return self.cmd


class Bind(unittest.TestCase):
    def test_default_is_loopback(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(target.Target().bind, "127.0.0.1")

    def test_env_moves_it(self):
        with mock.patch.dict("os.environ", {"BLINKFLOW_QNX_BIND": "192.168.1.20"}):
            self.assertEqual(target.Target().bind, "192.168.1.20")

    def test_brain_bridge_listens_on_the_bind_address(self):
        p1, p2 = _free_port(), _free_port()
        t = Fake(["sh", "-c", "cat > /dev/null", "ssh"], bind="127.0.0.2")
        t.clock = lambda: (0.0, 0.001)
        with mock.patch.object(target, "SIM_SOCKETS", {p1: "/nonexistent/a.sock", p2: "/nonexistent/b.sock"}), \
             mock.patch.object(target, "TARGET_SOCKETS", {**target.TARGET_SOCKETS, p1: "/tmp/a", p2: "/tmp/b"}):
            b = target.QnxBrain(t, 1, "/nonexistent/run.jsonl.gz")
        try:
            self.assertEqual({ls.getsockname()[0] for ls in b.listeners}, {"127.0.0.2"})
        finally:
            b.proc.wait(5)
            for ls in b.listeners:
                bridge.stop(ls)


class Clock(unittest.TestCase):
    def test_dead_target_says_so(self):
        with self.assertRaisesRegex(RuntimeError, "did not answer the clock echo"):
            Fake(["false"]).clock(pings=3)


if __name__ == "__main__":
    unittest.main()
