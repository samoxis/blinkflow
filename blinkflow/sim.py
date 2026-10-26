"""Run one scenario of the Microduck target: simulator up, Viser window, brain for N s, simulator down.

The brain is a pure function of its inputs, so the same scenario run twice should look the same.
The snapshot of the whole scenario is taken from the capture buffer right after the brain stops.

    python -m blinkflow.sim --brain ~/duck-target --seconds 12
"""
import argparse
import gzip
import json
import os
import pathlib
import subprocess
import time

from .capture import Sidecar

HOME = pathlib.Path.home()
SIM = HOME / "microduck"
RUNS = HOME / "blinkflow-runs"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CAM_DIR = "/mnt/c/Users/sorin/blinkflow/camera"


def sim_env(cam_script, port):
    env = dict(os.environ)
    env.update(PATH=f"{HOME}/.cargo/bin:{HOME}/.local/bin:{env['PATH']}",
               DUCK_SIM_RL=str(HOME / "microduck_rl"), DUCK_VISER="1", DUCK_VISER_PORT=str(port),
               LP_NUM_THREADS="4", DUCK_SIM_SCENE="demo", DUCK_CAM="1", DUCK_CAM_SCRIPT=cam_script)
    return env


def open_viser(port, size=(1100, 700)):
    """A Chrome --app window at a fixed place and size, in its own profile, so every run frames the same."""
    args = [f"--app=http://localhost:{port}", r"--user-data-dir=$env:LOCALAPPDATA\BlinkFlow\chrome",
            "--no-first-run", "--no-default-browser-check", "--window-position=0,0",
            f"--window-size={size[0]},{size[1]}"]
    arglist = ",".join(f'"{a}"' for a in args)   # double quotes: PowerShell expands $env:
    subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                    f"Start-Process '{CHROME}' -ArgumentList {arglist}"], check=True)


def brain_start(record):
    """Epoch (WSL clock) of the brain's first tick, from its monotonic timestamp."""
    with gzip.open(record, "rt") as f:
        next(f)
        t = json.loads(next(f))["t"]
    return t + (time.time() - time.monotonic())


def run(brain, seconds, cam_script, out_dir, port=8090, settle=10):
    env = sim_env(cam_script, port)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    record = RUNS / f"run-{stamp}.jsonl.gz"
    RUNS.mkdir(exist_ok=True)
    subprocess.run([str(SIM / "scripts" / "duck-sim")], cwd=SIM, env=env, check=True,
                   stdout=subprocess.DEVNULL)
    cap = Sidecar()
    try:
        open_viser(port)
        cap.start()
        time.sleep(settle)                      # scene loaded, duck standing
        subprocess.run(["uv", "run", "-q", "microduck-brain", "--duration", str(seconds),
                        "--record", str(record)], cwd=brain, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t_start = brain_start(record)
        meta = cap.snapshot(time.time() - t_start + 1.5, out_dir)
    finally:
        cap.stop(close_window=True)
        subprocess.run([str(SIM / "scripts" / "duck-sim"), "down"], cwd=SIM, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    meta.update(brain=str(brain), record=str(record), brain_start=t_start, seconds=seconds,
                cam_script=cam_script)
    pathlib.Path(out_dir, f"{meta['id']}.json").write_text(json.dumps(meta))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(HOME / "duck-target"))
    ap.add_argument("--seconds", type=float, default=12)
    ap.add_argument("--cam", default=f"{CAM_DIR}/shots_incident.json")
    ap.add_argument("--out", default=str(RUNS / "clips"))
    a = ap.parse_args()
    meta = run(pathlib.Path(a.brain).expanduser(), a.seconds, a.cam, a.out)
    print(json.dumps({k: meta[k] for k in ("path", "t0_epoch", "brain_start", "frames", "record")}))


if __name__ == "__main__":
    main()
