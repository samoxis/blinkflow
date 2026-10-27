<p align="center"><img src="docs/icon.png" width="160" alt="BlinkFlow icon"></p>

# BlinkFlow

**The robot did something wrong? Just say what you saw.**

BlinkFlow watches a robot simulator the way you do: through the screen. When the robot does something wrong, you say what you saw. BlinkFlow rewinds to that moment, works out which part of the robot's program caused it, writes the fix, and plays the exact same scene again to prove the problem is gone. If the fix doesn't work, it undoes it and tries again.

It runs Meta's **open-weight Muse Glimmer on this PC**, so the robot's camera never leaves the machine until there is something worth fixing.

> Built during the [Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon), Oct 26 – Nov 4, 2026. Indie Developer track, theme: Push the Frontier.
> **Work in progress.** This README grows as each piece starts working. The build log is in [`DEVLOG.md`](DEVLOG.md).

## How it works

| Step | What happens | Meta model |
|---|---|---|
| Remember | The last 60 seconds of the simulator window are kept locally | — |
| Watch | Or nobody says anything: about once a second the newest frame is checked locally for a robot touching, nearly touching, fallen or stuck; a raised hand is confirmed on pixels before the loop starts, and the moment comes from BlinkFlow's own clock (`results/watcher.md`) | Muse Glimmer (local), SAM 3.1 |
| Listen | Hold F9 and say what you saw ("three seconds ago its right leg hit the purple box"), or type it; the moment is the key press on BlinkFlow's own clock minus the time you said; the sentence is read locally (`results/voice.md`) | Muse Voice Transcribe, Muse Glimmer (local) |
| See | Objects in those seconds are named locally and then followed pixel by pixel; the masks become measurements (distance between objects per frame, first contact) | Muse Glimmer (local), SAM 3.1 |
| Understand | Key frames + measurements + time-aligned logs + the robot's code → the cause, plus a plain-language explanation | Muse Wonder |
| Fix | A coding agent patches the code inside its sandbox; a git commit is taken first | Muse Code (Python SDK) |
| Prove | The identical scenario is replayed and checked again on pixels; failed fixes are rolled back and retried | SAM 3.1, Muse Code |

## The console

A local page that shows the loop live, one step at a time, with the model behind each step: the last 60 seconds rewinding to the moment, the sentence, SAM 3.1's masks and the distance to first contact, Muse Wonder's cause as it streams with the key frame, the log row and the code line, the change and the safety commit, the replay before | after, the control scenes, the clock and the bill. "Fix it?" and "Keep the fix?" can be answered there or in the terminal, whichever comes first.

```bash
python3 -m blinkflow.console serve                # http://localhost:8777, follows the newest run
python3 -m blinkflow.console report <run>/events.jsonl   # the same page as static files, for the report
```

The console only reads the loop's event log (`events.jsonl`); the loop runs the same without it. It serves only files the log names, and never the scorer's files. Keep it off the simulator window while recording: the buffer films that window.

## Pre-existing vs built during the hackathon

The rules ask entrants to separate earlier work from new work. **Everything in this repository was written after the kickoff session on Oct 26, 2026.**

Existed before, used only as the test target, not part of this repo:

- [microduck-brain](https://github.com/samoxis/microduck-brain), an autonomy layer for the open-source Microduck biped (Apache-2.0), by the same author. BlinkFlow works on a clean copy of it (no README, no tests, no history, hint comments rewritten), so it cannot read the answer.
- The Microduck MuJoCo simulation and walking policies by [Pollen Robotics / Hugging Face](https://github.com/pollen-robotics/microduck) (Apache-2.0), and a recoloured demo scene.
- A screen-recording and camera-direction script used to film the simulator (Oct 22).
- Preparation tests made before the kickoff on Oct 26: a first API call, SAM 3.1 tracking on an old clip, a headless Muse Code session, a Muse Glimmer test and a prototype screen buffer. None of that code is included; the buffer was rewritten from scratch here.

## Honesty notes

- The simulator's own contact log is never given to BlinkFlow. It is used only as ground truth to score whether a fix worked.
- Results are measured during the hackathon, on BlinkFlow's own fixes, including bugs injected blind into the robot's code.
- Every incident report lists each model call: model, where it ran, tokens.
- Speed-ups in the demo video are labelled on screen.

## Safety

Muse Code runs inside its sandbox. BlinkFlow approves only edits to the chosen target folder and refuses everything else. Every fix starts from a git commit and can be undone with one command. Before Muse Code writes, BlinkFlow shows the cause in two plain sentences and asks "Fix it?"; after the proof it asks "Keep the fix?", and a no rolls the change back. `--auto` runs without a person (the bug suites, the watcher).

## Credits and licence

The icon was generated with Meta's Muse Image.

The deterministic twin (`blinkflow/twin.py`) is new code, but the physics, the scenes, the depth sensor and the walking policies it runs are imported from [Pollen Robotics' Microduck](https://github.com/pollen-robotics/microduck) (`microduck_rl`), not copied.


Apache-2.0 (see `LICENSE`). Microduck and its simulation are by Pollen Robotics and Hugging Face, Apache-2.0. Code in this repository is written with AI coding assistants under the author's direction.
