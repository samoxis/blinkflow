<p align="center"><img src="docs/icon.png" width="160" alt="BlinkFlow icon"></p>

# BlinkFlow

**The robot did something wrong? Just say what you saw.**

**[See a real run, no install](https://samoxis.github.io/blinkflow/report/)**: the purple-box incident from the snapshot to the proof, the static report built from `examples/purple-box/`.

<p align="center"><img src="docs/blinkflow.gif" width="640" alt="The robot's right leg brushes the purple box; after BlinkFlow's fix, contacts go from 1 to 0"></p>

For people who write robot software and test it in a simulator: you say what went wrong on screen, BlinkFlow finds the cause in the robot's code, fixes it, and proves the fix on the same scene.

BlinkFlow watches a robot simulator the way you do: through the screen. When the robot does something wrong, you say what you saw. BlinkFlow rewinds to that moment, works out which part of the robot's program caused it, writes the fix, and plays the same scene again to prove the problem is gone. If the fix doesn't work, it undoes it and tries again.

What it films is the simulator's window on your screen, not a camera on the robot. It runs Meta's **open-weight Muse Glimmer on this PC**, so that window never leaves the machine until there is something worth fixing.

> Built during the [Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon), Oct 26 – Nov 4, 2026. Indie Developer track, theme: Push the Frontier.
> **Work in progress.** This README grows as each piece starts working. The build log is in [`DEVLOG.md`](DEVLOG.md).

**New vs pre-existing:** everything in this repo was written after the kickoff on Oct 26, 2026; the robot, its simulator and its brain existed before — see [Pre-existing vs built during the hackathon](#pre-existing-vs-built-during-the-hackathon).

## How it works

| Step | What happens | Meta model |
|---|---|---|
| Remember | The last 60 seconds of the simulator window are kept locally | — |
| Watch | Or nobody says anything: about once a second the newest frame is checked locally for a robot touching, nearly touching, fallen or stuck; a raised hand is confirmed on pixels before the loop starts, and the moment comes from BlinkFlow's own clock (`results/watcher.md`) | Muse Glimmer (local), SAM 3.1 |
| Listen | Hold F9 and say what you saw ("three seconds ago its right leg hit the purple box"), or type it; the moment is the key press on BlinkFlow's own clock minus the time you said; the sentence is read locally (`results/voice.md`) | Muse Voice Transcribe, Muse Glimmer (local) |
| See | Objects in those seconds are named locally and then followed pixel by pixel; the masks become measurements (distance between objects per frame, first contact) | Muse Glimmer (local), SAM 3.1 |
| Understand | Key frames + measurements + time-aligned logs + the robot's code → the cause, plus a plain-language explanation. Every claim cites its source: a key frame, a measurement, a log tick or a code line, and the answer is checked against what was sent (the file, function and lines exist; the cited frames and ticks exist) | Muse Wonder |
| Fix | A coding agent patches the code inside its sandbox; a git commit is taken first | Muse Code (Python SDK) |
| Prove | The same scene, replayed exactly in a deterministic twin, and checked again on pixels; failed fixes are rolled back and retried. For the demo incident, then confirmed on the live simulator (`results/live_check.md`) | SAM 3.1, Muse Code |

## Results

Measured during the hackathon; each number links to the file it comes from.

| What | Result | Source |
|---|---|---|
| Bug suite, stratified by layer (11 mutations drawn with a sealed seed, 8 gave an incident); blind to the mutation; perception rules were revised between passes | **5/8 on the first pass, 8/8 on the third**: incidents gone, control clean in all five scenes. Changes on the mutated line: **5/8 on the first pass, 6/8 on the third** | [`results/bug_suite.md`](results/bug_suite.md) |
| Same suite, held-out pass: a new seed, the code frozen, one pass, no reruns. 7 of the 8 kept bugs are a first-pass mutation with the same value; 1 is new | **8/8**: incidents gone, control clean in all five scenes. Changes on the mutated line: **7/8** | [`results/bug_suite.md`](results/bug_suite.md#held-out-pass-oct-28) |
| First suite (6 bugs), blind to the mutation, one pass | 6/6 fixed; Muse Wonder's cause on the mutated line in 5/6 | [`results/bug_suite.md`](results/bug_suite.md) |
| Live simulator, the demo incident, 20 s per run | contact in **5/5** runs without the fix, **0/5** with it (an earlier pass, with a CPU-heavy job beside it: 3/5, 0/5) | [`results/live_check.md`](results/live_check.md) |
| Seen → fixed and verified (machine time) | **135.8–191.0 s** over 8 purple-box loops, median 166.6 s; the spread is mostly Muse Wonder (55–97 s) | [`results/loop_times.md`](results/loop_times.md), [`results/quick_loop.md`](results/quick_loop.md) |
| Control after the fix, on pixels | **5/5 scenes clean, all 5 measured** (the 166.4 s run); the twin's log agrees | [`results/loop_times.md`](results/loop_times.md), [`results/console/`](results/console) |
| Watcher (nobody speaks) | **0 false alarms** in 16 runs without an incident; **14/17** incidents caught. Optimistic: the suite gave Glimmer a look every 0.97 s, live beside the simulator it is ~1.45 s | [`results/watcher.md`](results/watcher.md) |
| Voice | **5/5** sentences from a TTS heard, read and seen; the real microphone not yet tested | [`results/voice.md`](results/voice.md) |
| Pixel rule against ground truth | 92 saved looks re-measured: 60/64 incidents caught, false alarms 1 → 0 after one correction | [`results/control.md`](results/control.md) |
| Cost of one loop (model calls) | **$0.88** for the profiled loop; $0.34–$1.71 over the 8 runs (measuring the four control scenes adds SAM 3.1; replies from the cache cost $0) | [`results/quick_loop.md`](results/quick_loop.md), [`results/loop_times.md`](results/loop_times.md) |

Every run writes a `models.json`: each model call with the model, where it ran (this PC, Meta, Baseten, the cache), tokens or frames, seconds and cost.

## Where this could go (not built or tested yet)

BlinkFlow needs three things: a screen, a log and a folder of code. Only the deterministic twin and the target are specific to the duck; the rest of the loop is not, so it could serve:

- **Warehouse and delivery robots**, tested every day in simulation before they touch a real shelf.
- **Home robots**, like a vacuum that keeps getting stuck under the same sofa.
- **Open-source robots for hobbyists and schools** (Microduck, LeRobot arms, Reachy), whose owners are not robotics experts.
- **Game characters** that walk through walls or get stuck in doorways: also pixels, logs and code.

On a real robot the proof changes: the real world never repeats exactly, but the robot's recorded sensor log can be replayed through the fixed brain ("with exactly what it saw, would it turn now?"), then checked in simulation, then on the robot, and only with a person's "Keep the fix?".

## Try it without a GPU

A recorded run of the demo incident is in [`examples/purple-box/`](examples/purple-box): the 60 s snapshot, the evidence, Muse Wonder's diagnosis, Muse Code's change, the replays before and after, and the model calls. No GPU, no simulator, no key.

**1. The report.** Python 3 (tested on 3.12), standard library only:

```bash
git clone https://github.com/samoxis/blinkflow && cd blinkflow
python3 -m venv .venv && . .venv/bin/activate
python3 -m blinkflow.console report examples/purple-box/events.jsonl --out report
```

Open `report/index.html` over a local server (`python3 -m http.server -d report 8000`, then http://localhost:8000): the whole loop step by step, the masks, the distance to first contact, the cause with its key frame, log row and code line, the replay before | after, the clock and the bill.

**2. Measure it again.** The contact is re-derived from SAM 3.1's saved replies, offline (needs `ffmpeg`):

```bash
pip install -r requirements-judge.txt
cp -r examples/purple-box /tmp/pb
python3 -m blinkflow.see /tmp/pb/outside/snapshot.json --out /tmp/pb/incident --reuse
```

`/tmp/pb/incident/evidence.json` comes out identical to `examples/purple-box/incident/evidence.json` (first contact, closest gap, the gap in every frame) except for the two paths it names. It writes into the evidence folder, hence the copy.

**What needs a key.** Nothing above. Asking the models again does: SAM 3.1 and Muse Wonder need `MODEL_API_KEY` (Meta Model API), a diagnosis with Muse Spark needs `BASETEN_API_KEY` (Baseten), and both also need the robot's code. Keys are read from the environment or `~/.config/blinkflow/env`, never from the repo.

## Run the full loop (GPU)

The quickstart replays a recorded run. This runs the loop itself on a new machine: BlinkFlow sees the incident, Muse Wonder finds the cause, Muse Code fixes the target, the twin replays the scene and SAM 3.1 checks it again.

**1. What you need**

- Linux or WSL2 (tested on WSL2 Ubuntu 24.04), Python 3.12, git, `ffmpeg`, [uv](https://docs.astral.sh/uv/).
- An NVIDIA GPU that holds Muse Glimmer. The runs here used an RTX 4090 (24 GB); with the live simulator beside it the peak was 20.5 of 24.6 GB ([`results/watcher.md`](results/watcher.md)). Glimmer is required: Muse Spark Open on Baseten (`BASETEN_API_KEY`) stands in only when Glimmer's answer for naming the objects or reading the sentence cannot be used. No setting replaces Glimmer, and the key-frame descriptions have no fallback, so without such a GPU use the quickstart above.
- [Ollama](https://ollama.com) serving on `127.0.0.1:11434` (on WSL2, Ollama for Windows works), with Glimmer:

  ```bash
  ollama pull muse-glimmer
  ```

- The Muse Code CLI and its Python SDK, both 1.4.14 (the SDK must match `muse --version`). The launcher installs `muse` in `~/.local/bin` and signs you in with your Meta account:

  ```bash
  curl -fsSL https://api.meta.ai/muse-launcher.sh | bash
  ```

- Keys in `~/.config/blinkflow/env` (or the environment), never in the repo:

  ```
  MODEL_API_KEY=...       # Meta Model API: SAM 3.1, Muse Wonder, Muse Voice Transcribe
  BASETEN_API_KEY=...     # optional: Muse Spark Open, the fallback
  ```

**2. BlinkFlow and its gate**

```bash
git clone https://github.com/samoxis/blinkflow && cd blinkflow
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 -m blinkflow.gate install
```

The gate is Muse Code's PreToolUse hook (see [Safety](#safety)); BlinkFlow will not start Muse Code without it.

**3. The target and the simulator** (pre-existing, outside this repo; the paths below are the ones BlinkFlow expects)

```bash
python3 tools/make_target.py ~/duck-target
git clone -b blinkflow-demo-scene https://github.com/samoxis/microduck_rl ~/microduck_rl
(cd ~/microduck_rl && uv sync)
git clone https://github.com/pollen-robotics/microduck ~/microduck
git -C ~/microduck checkout ded2f7c980217049817580562b2bbc7393b16de4
sh ~/microduck/scripts/seed-policies.sh ~/.cache/duck-sim/policies
```

- `tools/make_target.py` clones [microduck-brain](https://github.com/samoxis/microduck-brain) at `e1e157d`, keeps only the code (no README, docs, tests, tools, CI or history), puts in the demo bug (the robot judges "ahead" from the front columns only and forgets what it passed: its right leg brushes the purple box) and rewrites the comments that would name it, then makes one base commit. The result is the same, file for file, as the target every run in `results/` used.
- `microduck_rl` is Pollen Robotics' simulation (MuJoCo, the walking policies' runtime) on the branch [`blinkflow-demo-scene`](https://github.com/samoxis/microduck_rl/tree/blinkflow-demo-scene): upstream `8d0db74` plus the recoloured demo scene with the purple box. The twin loads that scene.
- `microduck` is Pollen Robotics' robot stack; `seed-policies.sh` downloads the walking policies from the Hugging Face Hub. The live simulator also builds its daemons from it with `cargo` the first time it starts.

**4. One loop on the purple box**

Without the sidecar (any Linux, no simulator window): the recorded live clip in [`examples/purple-box/outside/`](examples/purple-box/outside) plays on the clock as if it were the 60 s buffer, the key goes down at 12.4 s of the brain's time (the leg touches the box at ~12.0 s), and the sentence is typed. From there on it is the same loop as live; only the proof needs the twin.

```bash
python3 -m blinkflow.voice clip examples/purple-box/outside/snapshot.json --press 12.4 \
  --text "just now its right leg hit the purple box" --brain ~/duck-target --auto
```

Live (Windows 11 + WSL2). On the Windows side: Python 3 on the PATH as `python` (the sidecar, [`sidecar/capture.py`](sidecar/capture.py), uses only the standard library), an `ffmpeg` with `ddagrab` and NVENC on the PATH, and Google Chrome. The browser view and the camera of the simulator go into `microduck_rl`'s environment once:

```bash
cp ~/microduck_rl/blinkflow-demo/duck_viser_hook.* ~/microduck_rl/blinkflow-demo/duck_cam_director.py \
  ~/microduck_rl/.venv/lib/python3.12/site-packages/
uv pip install --python ~/microduck_rl/.venv/bin/python viser==1.0.30 mjviser==0.0.14
python3 -m blinkflow.voice live --type --auto
```

BlinkFlow starts the simulator in the demo scene, the Viser window in Chrome and the sidecar itself, and the robot walks for 30 s: press Enter when you see it go wrong, then type what you saw. Without `--type`, hold F9 and say it. Without `--auto`, BlinkFlow asks "Fix it?" before Muse Code writes and "Keep the fix?" after the proof.

**5. What comes out**

One folder per run, `~/blinkflow-runs/voice/<stamp>/` (or `--out DIR`):

| File | What it holds |
|---|---|
| `voice.json` | what was heard, the moment, the incident as seen, the loop's outcome |
| `events.jsonl` | every step, for the console: `python3 -m blinkflow.console report <run>/events.jsonl --out report` |
| `window/` | the snapshot cut from the buffer, and `evidence/`: SAM 3.1's masks, the distance per frame, first contact, the key frames, Muse Wonder's diagnosis (`diagnosis.md`) |
| `fix/fix.json` | the base commit, each attempt, fixed or not, kept or not |
| `fix/attempt-N/` | Muse Code's prompt and turn (`muse-code.json`), `change.diff`, the replay in the twin and its `verdict.json` |
| `fix/before/` | the same scene replayed before the fix, measured the same way |
| `fix/models.json` | every model call: model, where it ran, tokens or frames, seconds, cost |
| `fix/report.md` | the run in plain words |

The fix itself is a commit in `~/duck-target`, on top of the base commit. With `--auto` it is kept; `git -C ~/duck-target reset --hard <base commit>` undoes it (the base is in `fix/fix.json`).

## Muse Glimmer, on this PC — provenance

Glimmer is the open-weight model that names objects, describes key frames and reads the person's sentence, on an RTX 4090 through Ollama. To check that without this PC, [`examples/purple-box/`](examples/purple-box) carries:

- [`models.json`](examples/purple-box/models.json): every model call of the run. Glimmer's five are `muse-glimmer`, `local`, with tokens in and out and seconds; the 32 SAM 3.1 calls are `cached, $0`, each with the hash of the video bytes, concept and parameters it answers.
- [`models-first-run.json`](examples/purple-box/models-first-run.json): the same loop on the same clip three minutes earlier, when SAM 3.1 was still paid for ($0.93 against $0.34).
- [`provenance.txt`](examples/purple-box/provenance.txt): `ollama ps` and `nvidia-smi` sampled every ~3 s while the run ran, with timestamps that line up with Glimmer's calls: `muse-glimmer`, 16 GB, 100% GPU, context 8192.
- [`glimmer.jsonl`](examples/purple-box/glimmer.jsonl): Glimmer's raw replies from the run, each with what it was asked and the image it saw.

`python3 tools/pack_example.py <run>/events.jsonl examples/<name>` packs any run the same way: paths made relative to the example, the home folder written as `~`, no keys, and never the scorer's ground truth.

## Limits

- **The twin is not the live simulator.** It starts the robot standing (no sit-to-stand boot) and re-states robotd's controller in Python, so robotd itself is bypassed.
- **The live simulator is not deterministic.** Four wall clocks run it, so the same brain does not walk the same path twice. That is why the proof is double: exact in the twin, then 5 runs on each side live.
- **Muse Wonder varies.** The same evidence gives different lengths of answer (4.7k–8.4k output tokens), and that alone moves the loop time by about 40 s; its cause is not always on the mutated line ([`results/bug_suite.md`](results/bug_suite.md)).
- **The watcher confirms after the fact,** a median 19.5 s after the incident (13–52 s): it is a safety net, not a brake.
- **"Stuck" has no real case.** The watcher checks for it, but no run has had a robot stuck.
- **The real microphone is untested.** This PC has only a virtual one; voice was measured with TTS sentences.

## Cost

The SAM 3.1 replies are cached by the exact hash of the video bytes, the concept and the parameters: the twin is deterministic, so an unchanged scene gives the same video and is not paid twice. Muse Spark runs on Baseten (`meta-models/muse-spark-open-1026`); Muse Wonder stays on the Meta Model API. Muse Code now runs on `muse-spark-1.3-contributor` ($0.10 / $0.20 per 1M tokens in / out, against $1.25 / $4.25; its conversations may be used for training, and the target and this repo are public): one purple-box loop gave the same fix, 1 → 0, control 5/5, and $0.0053 for Muse Code instead of $0.070 (`BLINKFLOW_MUSE_MODEL=muse-spark-1.3` goes back). The loop costs in Results were all measured on `muse-spark-1.3`, Muse Code included. `python3 tools/spend.py --day YYYY-MM-DD` sums the `models.json` of every run that day, per model and per provider.

## The console

A local page that shows the loop live, one step at a time, with the model behind each step: the last 60 seconds rewinding to the moment, the sentence, SAM 3.1's masks and the distance to first contact, Muse Wonder's cause as it streams with the key frame, the log row and the code line, the change and the safety commit, the replay before | after, the control scenes, the clock and the bill. "Fix it?" and "Keep the fix?" can be answered there or in the terminal, whichever comes first.

```bash
python3 -m blinkflow.console serve                # http://localhost:8777, follows the newest run
python3 -m blinkflow.console report <run>/events.jsonl   # the same page as static files, for the report
python3 -m blinkflow.console serve --film --speed 4 --events <run>/events.jsonl   # full screen at 1920x1080 on Windows, replayed at 4x
python3 tools/teaser.py <run>/events.jsonl        # the 20 s phone teaser, 16:9 and 1:1, filmed headless, subtitles from the run
python3 tools/side_shot.py                        # the first touch, low from behind-right, slowed 4x, held 0.5 s; one clip per angle and a sheet (scorer side: twin truth)
```

The clock counts machine time only: the seconds a person takes to answer "Fix it?" are shown apart and not counted.

The console only reads the loop's event log (`events.jsonl`); the loop runs the same without it. It serves only files the log names, and never the scorer's files. Keep it off the simulator window while recording: the buffer films that window.

## Pre-existing vs built during the hackathon

The rules ask entrants to separate earlier work from new work. **Everything in this repository was written after the kickoff session on Oct 26, 2026.**

Existed before, used only as the test target, not part of this repo:

- [microduck-brain](https://github.com/samoxis/microduck-brain), an autonomy layer for the open-source Microduck biped (Apache-2.0), by the same author. BlinkFlow works on a clean copy of it (no README, no tests, no history, hint comments rewritten), so it cannot read the answer.
- The Microduck MuJoCo simulation and walking policies by [Pollen Robotics / Hugging Face](https://github.com/pollen-robotics/microduck) (Apache-2.0), and a recoloured demo scene.
- The recoloured demo scene with the purple box, the hook that shows the simulator in the browser (Viser) and the camera-direction script that films it (all Oct 22). Published unchanged, after the kickoff and labelled as pre-existing, on the branch [`blinkflow-demo-scene`](https://github.com/samoxis/microduck_rl/tree/blinkflow-demo-scene) of the author's `microduck_rl` fork: `scene_demo.xml`, `apartment_demo.xml`, `duck_viser_hook.py` + `.pth`, `duck_cam_director.py` and the incident's camera script `shots_incident.json`.
- The demo bug in the brain: the author's commit "demo: reintroduce finding 6" (Oct 22), never pushed. `tools/make_target.py` re-states it as text edits.
- The script that first made the target (strip the README, tests and hint comments). Not in this repo. It was started before the kickoff (Oct 26, 14:42) and its list of hint comments was last edited at 19:32 that day. **`tools/make_target.py` replaces it: rewritten from scratch on Oct 28, no code copied**, and it makes the same target file for file.
- Preparation tests made before the kickoff on Oct 26: a first API call, SAM 3.1 tracking on an old clip, a headless Muse Code session, a Muse Glimmer test and a prototype screen buffer. None of that code is included; the buffer was rewritten from scratch here.

## Honesty notes

- The simulator's own contact log is never given to BlinkFlow. It is used only as ground truth to score whether a fix worked.
- The twin loads the scene to simulate it; perception, diagnosis and the fix receive only pixels, the brain's own log and the code — never the contact log, truth.json or the scene geometry.
- Results are measured during the hackathon, on BlinkFlow's own fixes, including bugs injected blind into the robot's code.
- Every incident report lists each model call: model, where it ran, tokens.
- Speed-ups in the demo video are labelled on screen.

## Safety

Muse Code runs under `muse serve`'s default sandboxed profile (not `:unrestricted`). That sandbox does not stop a read or a write outside the target: on Oct 28 one Muse Code turn ($0.05) in a throwaway workspace ran `cat ../canary.txt` without an approval prompt and returned the file's random token, and BlinkFlow's approval handler was never called in the 53 saved turns, edits included. So a tool call that names a path outside the target is **blocked before it runs, by a Muse Code PreToolUse hook** (`muse-gate/`, installed with `python3 -m blinkflow.gate install`). It lives in the data home of the `muse serve` BlinkFlow starts (`~/.local/share/blinkflow/muse-host`) and is trusted for that host only, so your own muse sessions never load it and `~/.config/muse` is not written; BlinkFlow refuses to start Muse Code if it is missing or older than the repo copy. The hook denies with a reason Muse Code reads ("outside the target: /tmp/x. The target is …; work only inside it.") and adds a `musecode.blocked` event that the console shows as "blocked before it ran". File tools may name only paths inside the target; a shell command may also read `/usr`, `/etc`, `/bin`, `/lib`, `/dev`, `/proc` and `/opt`, and may not name `/tmp`, `/var/tmp` or `/dev/shm` at all. If the hook itself fails, the call is denied. How it was measured, Oct 28: (a) offline, $0: all 497 saved tool calls (153 shell commands) from the 53 saved turns through the hook. 9 are refused: the 4 scratch scripts written to `/tmp` and the 5 shell commands that ran them; no call inside the target is refused. (b) Three Muse Code turns (~$0.15) through BlinkFlow's own host, each asked for one thing: `cat ../canary.txt`, `write_file` to `/tmp`, `echo x > /tmp/x`. All three were refused before they ran; neither file exists, and the canary's new token appears in no reply, event or host file. (c) One loop on the purple-box incident with `--auto` (`tools/profile_loop.py run gate-1`, $0.34: its `models.json` says $0.27 because it left Muse Code out, the host having reported no cost, and Muse Code's $0.070 comes from its tokens at the catalog's prices): 1 → 0 contacts, control clean in all 5 scenes, the same fix as before (`side_memory_seconds` 0.0 → 3.0) in attempt 1, nothing blocked, 136.9 s, inside the 135.8–191.0 s of the 8 earlier loops. The hook costs ~0.33 s per tool call (a fresh Python), ~1.7 s of that loop's 23.5 s of Muse Code. The after-turn audit still runs and rejects an attempt for the same reasons; the suites in `results/` ran before the gate existed. Every fix starts from a git commit and can be undone with one command. Before Muse Code writes, BlinkFlow shows the cause in two plain sentences and asks "Fix it?"; after the proof it asks "Keep the fix?", and a no rolls the change back. To undo a fix you kept: `git -C <target> reset --hard <base commit>` (the base commit is the console's "safety save"). `--auto` runs without a person (the bug suites, the watcher).

## Credits and licence

The icon was generated with Meta's Muse Image.

The deterministic twin (`blinkflow/twin.py`) is new code, but the physics, the scenes, the depth sensor and the walking policies it runs are imported from [Pollen Robotics' Microduck](https://github.com/pollen-robotics/microduck) (`microduck_rl`), not copied.


Apache-2.0 (see `LICENSE`). Microduck and its simulation are by Pollen Robotics and Hugging Face, Apache-2.0. Code in this repository is written with AI coding assistants under the author's direction.
