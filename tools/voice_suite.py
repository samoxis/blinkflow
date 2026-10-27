"""Muse Voice measured: how far the moment a person names is from the true contact. Scorer side: it knows
the truth (the watcher suite's cases, the twin's and the simulator's contact logs); blinkflow.voice gets
only the clip, the moment the key goes down and the sound.

    python3 tools/voice_suite.py tts            # 5 English sentences spoken by espeak-ng, each "pressed" a
                                                # person's delay after the true contact, through blinkflow.voice clip
    python3 tools/voice_suite.py gate           # one of them through the whole loop on a terminal, answering
                                                # y to "Fix it?" and n to "Keep the fix?"; the target must end as it began
    python3 tools/voice_suite.py score DIR ...  # voice runs (tts, or blinkflow.voice_test --mic) against the truth
    python3 tools/voice_suite.py table [DIR]    # markdown, for results/voice.md

The voices are espeak-ng's (a system package, GPL-3, nothing of it in this repo); the WAVs go to
~/blinkflow-runs/voice/tts/<stamp>/.
"""
import argparse
import json
import pathlib
import shlex
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path[:0] = [str(REPO), str(HERE)]
import inject_bug  # noqa: E402
import score_contact  # noqa: E402
from blinkflow.see import load_snapshot  # noqa: E402

HOME = pathlib.Path.home()
OUT = HOME / "blinkflow-runs" / "voice" / "tts"
CASES = HOME / "blinkflow-runs" / "watch-suite" / "cases.json"
# case, sentence, the key goes down this long after the true contact (a person's guess is off by a second
# or so, both ways), espeak-ng voice
PHRASES = [
    ("live20-before-1", "Three seconds ago the duck's right leg hit the purple box.", 3.4, "en-gb"),
    ("live20-before-3", "Just now the robot bumped into the purple box.", 0.8, "en-us"),
    ("live20-before-4", "About five seconds ago it walked into the box.", 4.3, "en-gb-x-rp"),
    ("b11", "Two seconds ago its foot clipped the purple box.", 2.6, "en-us+f3"),
    ("b1", "The robot kicked the little cube, maybe four seconds ago.", 3.2, "en-gb-scotland"),
]
GATE = 3          # the phrase whose case goes through the whole loop: b11, on a clone of its target as drawn


def speak(text, voice, out):
    raw = out.with_suffix(".espeak.wav")
    subprocess.run(["espeak-ng", "-v", voice, "-s", "155", "-w", str(raw), text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ac", "1", "-ar", "24000", "-sample_fmt", "s16",
                    "-map_metadata", "-1", str(out)], check=True)
    raw.unlink()
    return out


def voice_cmd(case, press, wav, out, *extra):
    return [sys.executable, "-m", "blinkflow.voice", "clip", case["snapshot"], "--press", f"{press:.3f}",
            "--wav", str(wav), "--out", str(out), *extra]


def tts(stamp):
    cases = json.loads(CASES.read_text())
    d = OUT / stamp
    d.mkdir(parents=True)
    for i, (k, text, delay, voice) in enumerate(PHRASES, 1):
        wav = speak(text, voice, d / f"phrase-{i}.wav")
        press = cases[k]["truth_s"] + delay
        with open(d / f"phrase-{i}.log", "w") as log:
            subprocess.run(voice_cmd(cases[k], press, wav, d / f"run-{i}", "--no-loop"), cwd=REPO, check=True,
                           stdout=log, stderr=subprocess.STDOUT)
        (d / f"run-{i}" / "case.json").write_text(json.dumps({"case": k, "voice": voice, "delay_s": delay}))
        print(json.dumps(score(d / f"run-{i}")), flush=True)
    return d


def gate(stamp, answers=("y", "n")):
    """The loop through a terminal (script(1) gives it a tty), with these answers typed in."""
    cases = json.loads(CASES.read_text())
    k, text, delay, voice = PHRASES[GATE]
    d = OUT / stamp
    d.mkdir(parents=True, exist_ok=True)
    wav = speak(text, voice, d / "gate.wav")
    brain = d / "gate-brain"
    src = inject_bug.SUITE_LAYERS / k / "target"
    first = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=src, capture_output=True,
                           text=True, check=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", str(src), str(brain)], check=True)
    subprocess.run(["git", "reset", "-q", "--hard", first], cwd=brain, check=True)
    head = lambda: subprocess.run(["git", "rev-parse", "HEAD"], cwd=brain, capture_output=True, text=True).stdout.strip()
    status = lambda: subprocess.run(["git", "status", "--porcelain"], cwd=brain, capture_output=True, text=True).stdout
    before, dirty = head(), status()
    cmd = shlex.join(voice_cmd(cases[k], cases[k]["truth_s"] + delay, wav, d / "gate", "--brain", str(brain)))
    with open(d / "gate.log", "w") as log:
        subprocess.run(["script", "-qec", cmd, "/dev/null"], cwd=REPO, input="".join(a + "\n" for a in answers),
                       text=True, stdout=log, stderr=subprocess.STDOUT)
    doc = json.loads((d / "gate" / "voice.json").read_text())
    # the loop's checkpoint commit (a dirty tree as it was) is the only commit a "no" may leave behind
    r = {"case": k, "answers": list(answers), "loop": doc.get("loop"), "head_before": before, "head_after": head(),
         "clean_after": not status().strip(), "dirty_before": bool(dirty.strip())}
    r["target_unchanged"] = r["head_after"] == before and r["clean_after"]
    (d / "gate.json").write_text(json.dumps(r, indent=1))
    print(json.dumps(r, indent=1))
    return r


def score(run):
    run = pathlib.Path(run)
    doc = json.loads((run / "voice.json").read_text())
    h, c = doc.get("heard"), doc.get("incident")
    meta = run / "case.json"
    s = {"run": str(run), **(json.loads(meta.read_text()) if meta.exists() else {"case": doc["feed"]})}
    snap = run / "window" / "snapshot.json"
    if not (h and snap.exists()):
        return {**s, "heard": None}
    src = json.loads(snap.read_text()).get("watched_from") or str(snap)
    gt = score_contact.truth(src, load_snapshot(src))
    t = gt and gt[0]
    press = h.get("press_brain_s", h["press"])
    w = c and c.get("window_brain_s")
    s.update(said=h["said"], read_by=h["read_by"], seconds_ago=h["seconds_ago"], event=h["event"],
             truth_s=t and round(t, 3), truth_body=gt and gt[1],
             press_after_truth_s=t and round(press - t, 2), moment_error_s=t and round(h["moment_brain_s"] - t, 2),
             window=w, in_window=bool(t and w and w[0] <= t <= w[1]),
             seen=c and c["kind"], names=c and c["names"], names_agree=c and c["names_agree"],
             seen_error_s=round(c["incident_s"] - t, 3) if t is not None and c and c["incident_s"] is not None else None,
             transcribe_s=h["transcribe_s"], read_s=h["read_s"], see_s=c and c["seconds"],
             cost_usd=c and c["see_cost_usd"])
    return s


def table(d):
    runs = sorted(pathlib.Path(d).glob("run-*"))
    rows = [score(r) for r in runs]
    print("| # | said (Muse Voice Transcribe) | true contact (s) | key after it (s) | said ago (s) | moment said - true (s) "
          "| window (s) | SAM 3.1 saw | seen - true (s) | names | hear + read (s) | see (s) | $ |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(rows, 1):
        if not s.get("said"):
            print(f"| {i} | (nothing heard) | | | | | | | | | | | |")
            continue
        fmt = lambda x, f="+.2f": "-" if x is None else format(x, f)
        w = s["window"] and f"{s['window'][0]:.1f}-{s['window'][1]:.1f}"
        print(f"| {i} | {s['said']} | {fmt(s['truth_s'], '.2f')} | {fmt(s['press_after_truth_s'])} | {s['seconds_ago']:g} | "
              f"**{fmt(s['moment_error_s'])}** | {w}{'' if s['in_window'] else ' (missed)'} | {s['seen'] or 'nothing'} | "
              f"{fmt(s['seen_error_s'], '+.3f')} | {' / '.join(s['names'] or [])} | "
              f"{s['transcribe_s']:.1f} + {s['read_s']:.1f} | {fmt(s['see_s'], '.0f')} | {fmt(s['cost_usd'], '.3f')} |")
    (pathlib.Path(d) / "scored.json").write_text(json.dumps(rows, indent=1))
    return rows


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tts")
    g = sub.add_parser("gate")
    g.add_argument("--stamp", help="put it beside this tts run")
    g.add_argument("--answers", default="y n")
    s = sub.add_parser("score")
    s.add_argument("runs", nargs="+")
    t = sub.add_parser("table")
    t.add_argument("dir", nargs="?")
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if a.cmd == "tts":
        table(tts(stamp))
    elif a.cmd == "gate":
        gate(a.stamp or stamp, tuple(a.answers.split()))
    elif a.cmd == "score":
        print(json.dumps([score(r) for r in a.runs], indent=1))
    else:
        table(a.dir or sorted(OUT.iterdir())[-1])


if __name__ == "__main__":
    main()
