# BlinkFlow — context for Claude Code

Sorin's entry for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026, Indie track, Push the Frontier). Solo. Deadline: submit by **Wed Nov 4, ~20:00 UK** (official 21:00 ET).

## Non-negotiable rules
- **Only code written after the kickoff (Oct 26, 16:30 UK) goes in this repo.** Never copy from `~/blinkflow-prep` (pre-kickoff prototype, archived) or from `~/microduck-brain*`. Learn from them, rewrite from scratch. Never alter commit timestamps.
- **No secrets.** API keys live in `~/.config/blinkflow/env` (`MODEL_API_KEY`, `BASETEN_API_KEY`). Grep for keys before every push.
- **BlinkFlow never reads `~/blinkflow-runs/contacts-*.csv`.** That file is only the scorer's ground truth.
- The target is **`~/duck-target`** (clean copy of the buggy brain). Never point BlinkFlow at `~/microduck-brain-bug`.
- Commit small and often, with plain messages. Append a line to `DEVLOG.md` whenever something starts working.
- Leave no junk: delete temp files and scripts when done.

## Architecture (decided)
- One Python package `blinkflow/` in WSL = the agent. Windows has only a small sidecar: screen capture + microphone, exposing localhost HTTP (`/snapshot`, later `/listen`).
- Capture: ffmpeg `ddagrab` on the window's client area → NVENC → 1 s segments in a 60 s ring; snapshot = copy + `concat -c copy`; cursor sampled at 60 Hz. Keep the window `--topmost` while recording.
- Objects named by **Muse Glimmer** locally (Ollama `muse-glimmer`, `think: false`, `format: json`, strip trailing `<|eot|>`). ~20.5 GB VRAM at 8k ctx; if it clashes with the sim, lower `num_ctx`, then use a 3-bit quant.
- Tracking: **SAM 3.1** via Meta Model API (`POST https://api.meta.ai/v1/responses`, model `sam-3.1`, one noun phrase per request, `input_video` as base64 data URL or `file_id`, stream SSE, per-frame lines `<Nf>` with `<|box;…|>` + mask, `metadata.include_confidence`). $0.20 / 1000 frames. Decode masks (`@meta-sam/parser` format) → distance per frame, first contact.
- Diagnosis: **Muse Wonder** (`muse-wonder-1.0`) gets key frames chosen from SAM evidence (not the whole clip), the measurements, time-aligned brain logs and the target's code → cause + plain-language explanation. Muse Spark 1.3 for cheap steps.
- Fix: **Muse Code** via `muse-code-sdk` (`muse serve`, default sandboxed profile, NOT `:unrestricted`; `session.on_approval(handler)` after `start_session`; approve only edits inside the target; `client_info.name` must match `[a-z0-9_]+`). git commit before, `git reset --hard` on failure, max 3 attempts.
- Proof: replay the identical scenario (the brain is a pure function of its inputs), run SAM again, compare.
- Judge package: `blinkflow analyze examples/<incident>` runs with only an API key (no GPU, no simulator), using Muse Spark Open on Baseten (`https://inference.baseten.co/v1`, `reasoning_effort: low`) instead of local Glimmer. Static HTML report per run. Every report includes a model manifest (model, provider, tokens).
- Voice (later): Muse Voice Transcribe, push-to-talk; text input is the fallback.

## Target facts
- Sim: `~/microduck_walk_demo.sh N` with `DUCK_BRAIN_DIR=~/duck-target`; viser at `localhost:8090`; the window title is `Viser` (Chrome `--app` window; crop 45 px top, 356 px right panel).
- Known bug (for the main demo): the right leg brushes the purple `demo_box` ~8 s into the scenario. Other bugs are injected blind by a script in `tools/`.
- Runs are recorded as `~/blinkflow-runs/run-*.jsonl.gz` (per-tick brain log) — BlinkFlow may read these.

## Plan
Full plan, judging criteria and video script live in the Claude project "BlinkFlow" (`plan.md`, `plan-filmare.md`, `hackathon-reguli.md`). Order: buffer → SAM evidence → Wonder diagnosis → Muse Code fix + replay proof (loop closed by Thu Oct 29) → blind bug set → voice + Glimmer watcher → judge package → video. Features freeze Mon Nov 2 evening.
