"""Installs BlinkFlow's gate (muse-gate/: a Muse Code plugin with one PreToolUse hook that denies a tool
call naming a path outside the target, before it runs).

It goes into the data home of the muse host BlinkFlow starts (fix.GATE_HOME, ~/.local/share/blinkflow/
muse-host), not into ~/.local/share/muse, so your own muse sessions never load it. Muse trusts the hook
only on that host, through `-c runtime_capabilities` (fix.gate()); ~/.config/muse is not written.
blinkflow.fix refuses to start Muse Code while the gate is missing or older than muse-gate/.

    python3 -m blinkflow.gate install      # again after any change to muse-gate/
"""
import os
import subprocess

from . import fix


def install():
    env = {**os.environ, "XDG_DATA_HOME": str(fix.GATE_HOME)}
    have = subprocess.run(["muse", "plugins", "inspect", fix.GATE_PLUGIN, "--json"], env=env,
                          capture_output=True).returncode == 0
    cmd = ["update", fix.GATE_PLUGIN] if have else ["install", str(fix.GATE_BUNDLE), "--scope", "user"]
    subprocess.run(["muse", "plugins", *cmd], env=env, check=True)
    fix.gate()
    print(f"gate installed in {fix.GATE_HOME}")


if __name__ == "__main__":
    install()
