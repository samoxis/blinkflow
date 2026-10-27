"""The voice, tested with a person: the simulator runs the purple-box scenario, the person watches the
Viser window, and when the robot touches something holds F9 and says in English what they saw and when
("two seconds ago its right leg hit the purple box"). Each run is `blinkflow.voice live`, without the loop
unless --loop (then it asks "Fix it?" and "Keep the fix?" here).

    python -m blinkflow.voice_test --mic [--runs 3] [--seconds 25] [--loop] [--mic-name NAME]

Scored afterwards against the simulator's own contact log, which BlinkFlow does not read:
    python3 tools/voice_suite.py table <the folder printed at the end>
The same test without a microphone (5 sentences from a TTS, on recorded clips): tools/voice_suite.py tts.
"""
import argparse
import json
import pathlib
import sys
import time

from . import TARGET, fix, sim, voice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic", action="store_true", required=True, help="a person speaks into the microphone")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=25)
    ap.add_argument("--brain", default=str(TARGET))
    ap.add_argument("--loop", action="store_true", help="start the loop on what is seen, asking here")
    ap.add_argument("--mic-name", help="the microphone's dshow name (default: the first real one)")
    a = ap.parse_args()
    if a.loop and not sys.stdin.isatty():
        raise SystemExit("--loop asks at a terminal")
    tty = fix.terminal() if a.loop else None
    out = voice.RUNS / "mic" / time.strftime("%Y%m%d-%H%M%S")
    print(f"{a.runs} runs of {a.seconds:g} s. Watch the Viser window; when the robot touches the box, hold "
          f"{voice.KEY} and say what you saw and how long ago, in English. Let go when you are done.", flush=True)
    for k in range(1, a.runs + 1):
        print(f"\n== run {k} of {a.runs} ==", flush=True)
        doc = voice.live(pathlib.Path(a.brain).expanduser(), a.seconds, f"{sim.CAM_DIR}/shots_incident.json",
                         out / f"run-{k}", with_loop=a.loop, mic=a.mic_name, tty=tty)
        h = doc.get("heard")
        print(json.dumps({"said": h and h["said"], "seconds_ago": h and h["seconds_ago"],
                          "moment_brain_s": h and h["moment_brain_s"],
                          "seen_s": (doc.get("incident") or {}).get("incident_s")}), flush=True)
    print(f"\nDone. Score it against the simulator's contact log:\n  python3 tools/voice_suite.py table {out}")


if __name__ == "__main__":
    main()
