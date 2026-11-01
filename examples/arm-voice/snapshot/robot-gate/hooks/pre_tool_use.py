"""Use BlinkFlow's scope check plus the arm's robot-file allowlist. Fail closed."""
import json
import os
import pathlib
import sys


def deny(reason):
    print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":reason}}))


try:
    conf=next(p/"blinkflow-gate.json" for p in pathlib.Path(__file__).resolve().parents
              if (p/"blinkflow-gate.json").exists())
    c=json.loads(conf.read_text())
    os.environ["PYTHONDONTWRITEBYTECODE"]="1"
    sys.dont_write_bytecode=True
    os.environ["BLINKFLOW_TARGET"]=c["target"]
    if c.get("events"):os.environ["BLINKFLOW_EVENTS"]=c["events"]
    sys.path[:0]=[str(pathlib.Path(c["target"]).parent),c["repo"]]
    from arm.gate import outside
    from blinkflow import fix,events
    call=json.loads(sys.stdin.read());tool=call.get("tool_name","");args=call.get("tool_input") or {}
    bad=fix.outside(tool,args)+outside(tool,args,c["target"])
    if bad:
        reason="Robot files only: "+", ".join(bad)
        events.emit("musecode.blocked",tag=c.get("tag"),tool=tool,reason=reason)
        deny(reason)
except Exception as exc:
    deny(f"Robot gate could not verify the call: {type(exc).__name__}: {exc}")
