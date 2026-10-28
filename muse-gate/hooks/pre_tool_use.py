"""BlinkFlow's gate, a Muse Code PreToolUse hook: before a tool call runs, blinkflow.fix.outside reads the
paths it names; if one is outside the target, the call is denied with the reason (Muse Code sees it and can
change its plan) and a musecode.blocked event goes to the run's stream.

Muse gives hooks a filtered environment, so the target and the stream come from blinkflow-gate.json, which
blinkflow.fix writes into the host's data home before each turn (found among this file's parents, or
given as argv[1]). Anything that goes wrong denies the call.
"""
import json
import os
import pathlib
import sys

CONF = "blinkflow-gate.json"


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def main():
    call = json.loads(sys.stdin.read())
    found = [pathlib.Path(sys.argv[1])] if len(sys.argv) > 1 else [
        p / CONF for p in pathlib.Path(__file__).resolve().parents if (p / CONF).exists()]
    if not found:
        return deny(f"BlinkFlow gate: no {CONF}, so no target to check against")
    conf = json.loads(found[0].read_text())
    os.environ["BLINKFLOW_TARGET"] = conf["target"]
    if conf.get("events"):
        os.environ["BLINKFLOW_EVENTS"] = conf["events"]
    sys.path.insert(0, conf["repo"])
    from blinkflow import events, fix
    tool = call.get("tool_name", "")
    refs = fix.outside(tool, call.get("tool_input") or {})
    if refs:
        reason = f"outside the target: {', '.join(refs)}. The target is {fix.TARGET}; work only inside it."
        events.emit("musecode.blocked", tag=conf.get("tag", ""), id=call.get("tool_use_id"), tool=tool,
                    args=json.dumps(call.get("tool_input"))[:400], reason=reason)
        deny(reason)


try:
    main()
except Exception as e:                      # a gate that cannot decide does not let the call through
    deny(f"BlinkFlow gate failed, so the call is denied: {type(e).__name__}: {e}")
