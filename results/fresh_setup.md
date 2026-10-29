# The full loop from a fresh clone

Oct 28. The steps of README "Run the full loop (GPU)" followed as written, on this PC, in a new folder: a fresh
clone of `samoxis/blinkflow` from GitHub at `5e3fa01`, a new venv with `pip install -r requirements.txt` (numpy
2.5.4, scipy 1.18.1, requests 2.34.2, matplotlib 3.11.2, pillow 12.1.1, muse-code-sdk 1.4.14), `python3 -m
blinkflow.gate install`, and the target made by `python3 tools/make_target.py`. The folder was deleted afterwards.

## The target

`diff -r -x .git <new target> ~/duck-target`: the only differences are `.venv/` and `src/microduck_brain/__pycache__/`
in `~/duck-target`, the brain's environment made by `uv run` (both gitignored). Every file of the code is the same.
The base commit's hash differs (a new commit date), as it would on any machine.

The branch `samoxis/microduck_rl@blinkflow-demo-scene` (efb57e9), cloned fresh: `scene_demo.xml`,
`apartment_demo.xml`, the Viser hook, the camera director and `shots_incident.json` are byte for byte the files the
runs here used, and its `src/` matches this PC's `~/microduck_rl/src/`.

## One loop

On the clip [`examples/purple-box/`](https://github.com/samoxis/blinkflow/tree/49a9695/examples/purple-box) held then (it now holds a later live run).

```bash
BLINKFLOW_SAM_CACHE=0 BLINKFLOW_SAM_BUDGET=8 python3 -m blinkflow.voice clip examples/purple-box/outside/snapshot.json \
  --press 12.4 --text "just now its right leg hit the purple box" --brain <new target> --auto
```

`BLINKFLOW_SAM_CACHE=0`: a new machine has no SAM 3.1 cache, so none was read. `BLINKFLOW_SAM_BUDGET=8`: this PC
had already spent $3.95 on SAM 3.1 that day, close to the default $5 guard. Run `voice/20261028-192828`.

| What | Result |
|---|---|
| Heard | "just now its right leg hit the purple box": contact, 0 s before the key |
| Seen (SAM 3.1, pixels) | white robot touched the purple box at 10.92 s (base reading) |
| Cause (Muse Wonder) | `brain.toml` `[obstacle] side_memory_seconds`; 56.3 s, 5257 output tokens |
| Fix (Muse Code, `muse-spark-1.3-contributor`) | `side_memory_seconds` 0.0 → 3.0, nothing else; attempt 1; 45.0 s; nothing blocked |
| Proof on pixels (twin replay, SAM 3.1) | before: contact at 11.46 s; after: no contact, closest gap 106.8 px |
| Scorer (twin's own contact log, never read by BlinkFlow), box scene 20 s | base commit: 1 touch (`ankle_right` on `demo_box`, 11.47 s); fixed: 0 |
| Seen → fixed and verified (machine time, BlinkFlow's clock) | **167.3 s** |
| The whole command (clip played to the key, hearing, seeing, the loop) | 214.6 s wall clock |
| Model cost (`fix/models.json`) | **$0.83**: SAM 3.1 $0.672 (32 calls, 3360 frames, none cached), Muse Wonder $0.155, Muse Code $0.0061, Muse Glimmer 6 calls on this PC, $0 |

Within the 135.8–234.0 s of the ten purple-box loops in `results/loop_times.md`; the cost is close to the $0.93 of
the first, uncached run in [`examples/purple-box/models-first-run.json`](https://github.com/samoxis/blinkflow/tree/49a9695/examples/purple-box/models-first-run.json) as it was then.

## Not checked from scratch

- `microduck_rl`'s `uv sync`, the Pollen stack and the policy download: this PC's `~/microduck_rl`, `~/microduck` and
  `~/.cache/duck-sim/policies` were used (the twin's paths are fixed to them).
- Ollama, Glimmer and the Muse Code CLI were the ones already installed (CLI 1.4.14).
- The live path (`voice live --type`): it needs a person at the terminal and the Windows side; it has run on this PC
  throughout (`results/live_check.md`, `results/watcher.md`), not from the fresh clone.
