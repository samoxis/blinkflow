"""Talks to the Windows capture sidecar: start it, ask for the last N seconds, stop it."""
import json
import pathlib
import subprocess
import time
import urllib.request

PORT = 8771
SIDECAR = pathlib.Path(__file__).resolve().parent.parent / "sidecar" / "capture.py"


def windows_host():
    """The Windows side of the WSL NAT link (default gateway)."""
    out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True).stdout
    return out.split()[2]


def unc(path):
    out = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True)
    return out.stdout.strip()


class Sidecar:
    def __init__(self, host=None, port=PORT):
        self.host = host or windows_host()
        self.base = f"http://{self.host}:{port}"
        self.port = port

    def _get(self, path, timeout=10):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return r.read()

    def start(self, title="Viser", crop_top=45, crop_right=356, wait=30):
        args = ["-u", unc(SIDECAR), "--host", self.host, "--port", str(self.port),
                "--title", title, "--crop-top", str(crop_top), "--crop-right", str(crop_right)]
        arglist = ",".join(f"'{a}'" for a in args)
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        f"Start-Process -WindowStyle Hidden python -ArgumentList {arglist}"],
                       check=True)
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                h = self.health()
                if h["recording"] and h["segments"] >= 2:
                    return h
            except OSError:
                pass
            time.sleep(0.5)
        raise RuntimeError("capture sidecar did not come up")

    def health(self):
        return json.loads(self._get("/health", timeout=2))

    def skew(self, n=15):
        """Windows clock minus WSL clock, in seconds, from the lowest-latency /health round trip."""
        best = None
        for _ in range(n):
            a = time.time()
            now = self.health()["now"]
            b = time.time()
            if best is None or b - a < best[0]:
                best = (b - a, now - (a + b) / 2)
        return best[1]

    def snapshot(self, seconds, out_dir, end=None):
        """Save the last `seconds` (up to `end`, WSL epoch) as out_dir/<id>.mp4 + .json.

        Times in the returned metadata are on the WSL clock (t0 = first frame)."""
        skew = self.skew()
        q = f"/snapshot?seconds={seconds}" + (f"&end={end + skew}" if end else "")
        meta = json.loads(self._get(q, timeout=30))
        if "error" in meta:
            raise RuntimeError(meta["error"])
        meta["skew"] = skew
        for k in ("t0_epoch", "t1_epoch"):
            meta[k] -= skew
        meta["requested"] = [t - skew for t in meta["requested"]]
        meta["cursor"] = [(t - skew, x, y) for t, x, y in meta["cursor"]]
        out = pathlib.Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        clip = out / f"{meta['id']}.mp4"
        clip.write_bytes(self._get(f"/clip/{meta['id']}", timeout=60))
        meta["path"] = str(clip)
        (out / f"{meta['id']}.json").write_text(json.dumps(meta))
        return meta

    def stop(self, close_window=False):
        req = urllib.request.Request(self.base + "/quit" + ("?close=1" if close_window else ""),
                                     method="POST")
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except OSError:
            pass
