# Running BlinkFlow

Moved here unchanged from the README's [Run the full loop](../README.md#run-the-full-loop-3060-min-gpu) and [The console](../README.md#the-console), which keep a summary. The quickstart without a GPU stays in the [README](../README.md#try-it-in-2-min-no-gpu).

## Run the full loop (~30–60 min, GPU)

The quickstart replays a recorded run. This runs the loop itself on a new machine: BlinkFlow sees the incident, Muse Wonder finds the cause, Muse Code fixes the target, the twin replays the scene and SAM 3.1 checks it again.

Checked on Oct 28 from a fresh clone, a new venv and a target made by `tools/make_target.py` (same files as the one every run used): the purple-box loop below (on the clip the example held then), without the SAM cache, fixed it in attempt 1, contacts 1 → 0, in 167.3 s for **$0.83** ([`results/fresh_setup.md`](../results/fresh_setup.md), which also says what was not redone from scratch).

**1. What you need**

- Linux or WSL2 (tested on WSL2 Ubuntu 24.04), Python 3.12, git, `ffmpeg`, [uv](https://docs.astral.sh/uv/).
- An NVIDIA GPU that holds Muse Glimmer. The runs here used an RTX 4090 (24 GB); with the live simulator beside it the peak was 20.5 of 24.6 GB ([`results/watcher.md`](../results/watcher.md)). Glimmer is required: Muse Spark Open on Baseten (`BASETEN_API_KEY`) stands in only when Glimmer's answer for naming the objects or reading the sentence cannot be used. No setting replaces Glimmer, and the key-frame descriptions have no fallback, so without such a GPU use the [quickstart](../README.md#try-it-in-2-min-no-gpu).
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

The gate is Muse Code's PreToolUse hook (see [Safety](../README.md#safety)); BlinkFlow will not start Muse Code without it.

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

Without the sidecar (any Linux, no simulator window): the recorded live clip in [`examples/purple-box/window/`](../examples/purple-box/window) plays on the clock as if it were the 60 s buffer, the key goes down at 13.00 s of the brain's time (the leg touches the box at 11.20 s), and the sentence is typed. From there on it is the same loop as live; only the proof needs the twin.

```bash
python3 -m blinkflow.voice clip examples/purple-box/window/snapshot.json --press 13.00 \
  --text "two seconds ago, the right leg hit the purple box" --brain ~/duck-target --auto
```

Live (Windows 11 + WSL2). On the Windows side: Python 3 on the PATH as `python` (the sidecar, [`sidecar/capture.py`](../sidecar/capture.py), uses only the standard library), an `ffmpeg` with `ddagrab` and NVENC on the PATH, and Google Chrome. The browser view and the camera of the simulator go into `microduck_rl`'s environment once:

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
| `said.wav`, `answers.jsonl` | the push-to-talk audio (spoken runs), the answers given in the console |
| `events.jsonl` | every step, for the console: `python3 -m blinkflow.console report <run>/events.jsonl --out report` |
| `window/` | the snapshot cut from the buffer, and `evidence/`: SAM 3.1's masks, the distance per frame, first contact, the key frames, Muse Wonder's diagnosis (`diagnosis.md`) |
| `fix/fix.json` | the base commit, each attempt, fixed or not, kept or not |
| `fix/attempt-N/` | Muse Code's prompt and turn (`muse-code.json`), `change.diff`, the replay in the twin and its `verdict.json` |
| `fix/before/` | the same scene replayed before the fix, measured the same way |
| `fix/models.json` | every model call: model, where it ran, tokens or frames, seconds, cost |
| `fix/report.md` | the run in plain words |

The fix itself is a commit in `~/duck-target`, on top of the base commit. With `--auto` it is kept; `git -C ~/duck-target reset --hard <base commit>` undoes it (the base is in `fix/fix.json`).

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

## Cost

The SAM 3.1 replies are cached by the exact hash of the video bytes, the concept and the parameters: the twin is deterministic, so an unchanged scene gives the same video and is not paid twice. Muse Spark runs on Baseten (`meta-models/muse-spark-open-1026`); Muse Wonder stays on the Meta Model API. Muse Code now runs on `muse-spark-1.3-contributor` ($0.10 / $0.20 per 1M tokens in / out, against $1.25 / $4.25; its conversations may be used for training, and the target and this repo are public): one purple-box loop gave the same fix, 1 → 0, control 5/5, and $0.0053 for Muse Code instead of $0.070 (`BLINKFLOW_MUSE_MODEL=muse-spark-1.3` goes back). The loop costs in Results were all measured on `muse-spark-1.3`, Muse Code included. `python3 tools/spend.py --day YYYY-MM-DD` sums the `models.json` of every run that day, per model and per provider.
