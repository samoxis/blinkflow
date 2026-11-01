"""Pre-tool and post-turn restriction to robot files, excluding the harness."""
import json
import os
import pathlib

ROOT=pathlib.Path(__file__).resolve().parent.parent
ROBOT=ROOT/"arm"
WRITABLE={"brain.py","brain.toml"}
READABLE=WRITABLE|{"scene.xml"}


def outside(tool,args,target=ROBOT):
    from blinkflow import fix
    if tool not in {"read_file","edit_file","write_file","apply_patch"}:
        return [f"tool {tool} is unavailable; use read_file/edit_file on robot files"]
    paths=fix.arg_paths(args)
    if not paths:return ["no explicit robot file"]
    allowed=READABLE if tool=="read_file" else WRITABLE
    root=pathlib.Path(target).resolve()
    bad=[]
    for name in paths:
        p=pathlib.Path(name).expanduser()
        p=(p if p.is_absolute() else root/p).resolve()
        if p.parent!=root or p.name not in allowed:bad.append(name)
    return bad


def configure():
    from blinkflow import fix
    fix.GATE_BUNDLE=ROOT/"tools/robot-gate"
    fix.GATE_HOME=ROOT/".cache/muse-host"


def install():
    configure()
    from blinkflow.gate import install as original_install
    original_install()


if __name__=="__main__":install()
