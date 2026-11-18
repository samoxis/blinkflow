"""The QNX 8.0 target as a QEMU/KVM virtual machine on the host, built with the SDP's mkqnximage.

Nothing from the SDP is in this repository: the image is built on your machine from your own SDP
install (a free non-commercial licence from myQNX works), into BLINKFLOW_QNX_VM (default ~/qnx-vm).

    build   mkqnximage: x86_64, Python, SSH with your public key, 4 CPUs, 2 GB
    up      QEMU user networking, no root needed: the guest sees the host as 10.0.2.2,
            the host reaches the guest's SSH on 127.0.0.1:2222
    down    stop it

mkqnximage's own runimage wants a bridge (and root); user networking is all the bridge needs.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import time

HOME = pathlib.Path.home()
VM = pathlib.Path(os.environ.get("BLINKFLOW_QNX_VM", HOME / "qnx-vm"))
SDP = pathlib.Path(os.environ.get("QNX_SDP", HOME / "qnx800"))
SSH_PORT = int(os.environ.get("BLINKFLOW_QNX_PORT", 2222))


def build(key=HOME / ".ssh" / "id_ed25519.pub", cpus=4, ram="2G"):
    VM.mkdir(parents=True, exist_ok=True)
    cmd = (f"source {SDP}/qnxsdp-env.sh >/dev/null && mkqnximage --type=qemu --arch=x86_64 --python=yes "
           f"--ssh-ident={key} --cpu={cpus} --ram={ram} --hostname=duckqnx --ip=dhcp --noprompt")
    subprocess.run(["bash", "-c", cmd], cwd=VM, check=True)


def pid():
    f = VM / "output" / "qemu.pid"
    try:
        p = int(f.read_text())
        os.kill(p, 0)
        return p
    except (OSError, ValueError):
        return None


def up(cpus=4, ram="2G", wait=60):
    if pid():
        return pid()
    out = VM / "output"
    subprocess.run(["qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-smp", str(cpus), "-m", ram,
                    "-kernel", str(out / "ifs.bin"), "-drive", f"file={out / 'disk-qemu.vmdk'},if=ide,id=drv0",
                    "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22",
                    "-device", "virtio-net-pci,netdev=net0",
                    "-object", "rng-random,filename=/dev/urandom,id=rng0", "-device", "virtio-rng-pci,rng=rng0",
                    "-pidfile", str(out / "qemu.pid"), "-display", "none",
                    "-serial", f"file:{out / 'console.log'}", "-daemonize"], check=True)
    from .target import Target
    t, end = Target(), time.time() + wait
    while time.time() < end:
        if t.reachable():
            return pid()
        time.sleep(2)
    raise TimeoutError(f"QNX VM started but SSH on 127.0.0.1:{SSH_PORT} did not answer in {wait} s")


def down():
    p = pid()
    if p:
        os.kill(p, 15)
    return p
