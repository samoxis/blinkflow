"""A QNX 8.0 target reached over SSH: the brain is deployed to it, runs on it at a real-time priority,
and drives the simulator on the host through the bridge (blinkflow.qnx.bridge).

    t = Target()                        # BLINKFLOW_QNX_HOST / _PORT / _GATEWAY / _BIND, default the QEMU VM
    t.deploy(~/duck-target)             # src/ + brain.toml + bridge.py, nothing else
    run = t.launch(20, record)          # Popen-like: poll / wait / interrupt; record fetched on wait
    t.replay(record)                    # the target's brain replays a recording made anywhere (probe.py)

Times: the brain records its own monotonic clock, which on the target is not the host's. Before a
launch the offset between the host's epoch and the target's monotonic clock is measured over one
SSH session (lowest round trip of several pings, error under half of it), so the host can place the
brain's first tick on its own clock, as it does for a brain running on the host.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import shlex
import subprocess
import tarfile
import time

from . import bridge

HOME = pathlib.Path.home()
REMOTE = "/data/home/root/duck"
SIM_SOCKETS = {7701: HOME / ".cache" / "duck-sim" / "duck-a.sock",
               7702: HOME / ".cache" / "duck-sim" / "duck-a-tof.sock"}
TARGET_SOCKETS = {7701: "/tmp/robotd.sock", 7702: "/tmp/tof.sock"}
BRIDGE = pathlib.Path(bridge.__file__)
PROBE = BRIDGE.with_name("probe.py")
PRIORITY = 30                      # `on -p 30`: round robin above every default-priority process
LAUNCH = 'import sys; from microduck_brain.cli import main; sys.argv[0] = "microduck-brain"; sys.exit(main())'


class Target:
    def __init__(self, host=None, port=None, user="root", gateway=None, bind=None, priority=PRIORITY):
        self.host = host or os.environ.get("BLINKFLOW_QNX_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("BLINKFLOW_QNX_PORT", 2222))
        self.gateway = gateway or os.environ.get("BLINKFLOW_QNX_GATEWAY", "10.0.2.2")   # the host, from the target
        # where the host's half of the bridge listens: loopback is enough for QEMU user networking
        # (10.0.2.2 lands on the host's 127.0.0.1); a board needs a host address it can reach
        self.bind = bind or os.environ.get("BLINKFLOW_QNX_BIND", "127.0.0.1")
        self.user, self.priority = user, priority

    def _ssh(self):
        return ["ssh", "-p", str(self.port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                f"{self.user}@{self.host}"]

    def sh(self, script, check=True, **kw):
        """Run a POSIX sh script on the target (fed on stdin, so nothing is quoted twice)."""
        return subprocess.run(self._ssh() + ["sh", "-s"], input=script, text=True, capture_output=True,
                              check=check, **kw)

    def reachable(self):
        try:
            return self.sh("echo ok", check=False, timeout=10).stdout.strip() == "ok"
        except subprocess.TimeoutExpired:
            return False

    def info(self):
        r = self.sh("uname -a; python3 -c 'import sys; print(sys.version.split()[0])'; pidin info | grep -m1 Processor1")
        lines = r.stdout.splitlines()
        return {"uname": lines[0], "python": lines[1], "cpu": " ".join(lines[2:]).strip(), "priority": self.priority}

    def deploy(self, brain):
        """The brain's package and config, the bridge and the probe, into REMOTE (old src/ removed first)."""
        brain = pathlib.Path(brain).expanduser().resolve()

        def clean(m):
            if "__pycache__" in m.name:
                return None
            m.uid = m.gid = 0
            m.uname = m.gname = "root"
            m.mtime = 0                           # same tree, same bytes, same digest
            return m

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in sorted(p.relative_to(brain).as_posix() for p in (brain / "src").rglob("*.py")):
                tar.add(brain / name, name, filter=clean)
            if (brain / "brain.toml").exists():
                tar.add(brain / "brain.toml", "brain.toml", filter=clean)
            for f in (BRIDGE, PROBE):
                tar.add(f, f.name, filter=clean)
        data = buf.getvalue()
        subprocess.run(self._ssh() + [f"rm -rf {REMOTE}/src {REMOTE}/brain.toml; mkdir -p {REMOTE}; tar xf - -C {REMOTE}"],
                       input=data, check=True, capture_output=True)
        rev = None
        if (brain / ".git").exists():
            r = subprocess.run(["git", "-C", str(brain), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
            d = subprocess.run(["git", "-C", str(brain), "status", "--porcelain"], capture_output=True, text=True)
            rev = r.stdout.strip() + ("+dirty" if d.stdout.strip() else "")
        return {"brain": str(brain), "git": rev, "sha256": hashlib.sha256(data).hexdigest()[:16], "bytes": len(data),
                "to": f"{self.user}@{self.host}:{REMOTE}"}

    def clock(self, pings=15):
        """(host epoch - target monotonic, round trip) from the fastest of `pings` echoes."""
        echo = "import sys,time\nfor _ in sys.stdin: print(repr(time.monotonic()), flush=True)"
        p = subprocess.Popen(self._ssh() + [shlex.join(["python3", "-u", "-c", echo])],   # ssh joins argv for a shell
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        best = None
        try:
            for _ in range(pings):
                t0 = time.time()
                try:
                    p.stdin.write("\n")
                    p.stdin.flush()
                    line = p.stdout.readline()
                except BrokenPipeError:
                    line = ""
                if not line:
                    raise RuntimeError(f"the target {self.user}@{self.host}:{self.port} did not answer the clock "
                                       "echo (SSH down, or no python3 on it)")
                mono = float(line)
                t1 = time.time()
                if best is None or t1 - t0 < best[1]:
                    best = ((t0 + t1) / 2 - mono, t1 - t0)
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait(10)
            p.stdout.close()
        return best

    def launch(self, seconds, record):
        r = self.sh(f"test -f {REMOTE}/src/microduck_brain/cli.py", check=False)
        if r.returncode:
            raise RuntimeError("the deployed brain has no microduck_brain/cli.py: it can be replayed, not run")
        return QnxBrain(self, seconds, pathlib.Path(record))

    def replay(self, record, dump=False):
        """The deployed brain replays `record` on the target (blinkflow.qnx.probe): its answers against
        the recorded ones, and a fingerprint of every answer."""
        subprocess.run(self._ssh() + [f"cat > {REMOTE}/replay.jsonl.gz"], stdin=open(record, "rb"), check=True)
        r = self.sh(f"cd {REMOTE} && PYTHONPATH=src python3 probe.py replay.jsonl.gz{' --dump' if dump else ''}; rc=$?; rm -f replay.jsonl.gz; exit $rc",
                    check=False)
        if r.returncode:
            raise RuntimeError(f"probe on the target failed: {r.stderr.strip()[-600:]}")
        return json.loads(r.stdout)

    def fetch(self, remote, local):
        with open(local, "wb") as f:
            subprocess.run(self._ssh() + [f"cat {remote}"], stdout=f, check=True)


class QnxBrain:
    """The brain running on the target for `seconds`, as a host subprocess would: poll, wait, interrupt."""

    def __init__(self, target, seconds, record):
        self.target, self.record = target, record
        self.epoch_offset, self.rtt = target.clock()
        self.listeners = bridge.expose([f"{port}={path}" for port, path in SIM_SOCKETS.items()], target.bind)
        maps = " ".join(f"--map {TARGET_SOCKETS[port]}={target.gateway}:{port}" for port in SIM_SOCKETS)
        script = f"""cd {REMOTE} || exit 2
rm -f run.jsonl.gz brain.pid
python3 bridge.py offer {maps} > bridge.log 2>&1 &
B=$!
sleep 1
PYTHONPATH=src on -p {target.priority} python3 -c '{LAUNCH}' --robot-socket {TARGET_SOCKETS[7701]} \\
  --tof-socket {TARGET_SOCKETS[7702]} --duration {seconds} --record run.jsonl.gz > brain.log 2>&1 &
P=$!
echo $P > brain.pid
wait $P
rc=$?
kill $B 2>/dev/null
rm -f brain.pid
exit $rc
"""
        self.proc = subprocess.Popen(target._ssh() + ["sh", "-s"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, text=True)
        self.proc.stdin.write(script)
        self.proc.stdin.close()
        self.returncode = None

    def poll(self):
        return self.proc.poll()

    def interrupt(self):
        """SIGINT to the brain on the target: it stops and closes its record, as with Ctrl+C."""
        self.target.sh(f"[ -f {REMOTE}/brain.pid ] && kill -s INT $(cat {REMOTE}/brain.pid)", check=False)

    terminate = interrupt

    def wait(self, timeout=None):
        try:
            self.returncode = self.proc.wait(timeout)
        finally:
            for ls in self.listeners:
                bridge.stop(ls)
        if self.returncode:
            log = self.target.sh(f"tail -5 {REMOTE}/brain.log", check=False).stdout.strip()
            raise RuntimeError(f"the brain on the target exited with {self.returncode}: {log}")
        self.target.fetch(f"{REMOTE}/run.jsonl.gz", self.record)
        return self.returncode
