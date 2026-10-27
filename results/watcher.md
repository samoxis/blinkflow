# BlinkFlow watcher: false alarms and misses

`blinkflow/watch.py` watches the capture buffer with nobody telling it anything.

**Glimmer raises a hand.** Muse Glimmer runs locally and looks at the newest frame about once a second. Every other look is a pair: the frame plus the one from 2 s earlier. It answers yes/no against a JSON schema:
- is the robot in view;
- is it touching something;
- is it close to touching it;
- has it fallen;
- (pairs only) is it stuck.

**SAM 3.1 confirms or dismisses.** The 6 s before the raised frame and the 1 s after it are cut from the buffer, and `blinkflow.see` follows the robot and the nearest object through that window. Only what the proof would also call an incident counts:
- a contact (the reading `prove.verdict` trusts);
- a fall (pixels, or the brain's own log);
- a robot whose mask stays still for 4 s after it has moved.

In every case, what SAM followed as the robot must have moved in the window.

**The first confirmed incident starts the existing loop** (`blinkflow.fix`) with `--loop`. The window is the snapshot, the moment is the raised frame's time on BlinkFlow's clock, and see's evidence is reused. The quick loop and the proof are unchanged.

**What the watcher reads:**
- the buffer: the sidecar's new `/frame`, which decodes the segment being written, and the existing `/snapshot` (or a recorded clip);
- the twin's `meta.json` (frame times, scene name, settle time);
- the brain's log, cut at the window's end.

It never reads `contacts-*.csv`, the scene XML or the twin's `truth.json`. Only the scorer below reads them.

## The set

`tools/watch_suite.py` runs 33 runs, one at a time:
- **Twin, 8 layered bugs.** Each bug is drawn in its own scene (the suite of `results/bug_suite.md`). It is rendered for 20 s with the brain as drawn.
- **Twin, 5 controls.** The clean base (the v0.3 behaviour) in each of the 5 scenes. It touches nothing and does not fall.
- **Live, 20 runs** recorded by the sidecar from the real simulator (live-check, purple box): 9 runs of `duck-target` before its fix, with a contact, and 11 without one.

**How a clip is played.** It runs on the wall clock as if it were the buffer:
- watching starts with the brain;
- a frame becomes visible 0.08 s after its time (the measured `/frame` lag);
- Glimmer's real latency decides which frames get looked at.

**How it is scored.** Truth is the twin's own log, or the simulator's contact log for live runs.
- Caught: SAM confirmed an incident, and the confirmed raise came no more than 1.5 s before the true one.
- False alarm: a confirmation without an incident, or one more than 1.5 s early.
- Miss: an incident with no confirmation.

## Results (final code)

| set | runs | caught | missed | false alarms | Glimmer raises | SAM dismissed | SAM $ |
|---|---|---|---|---|---|---|---|
| twin bugs | 8 | 7 | 1 | 0 | 34 | 4 | 1.11 |
| twin controls (v0.3 in 5 scenes) | 5 | 0 | 0 | **0** | 3 | 3 | 0.31 |
| live, contact | 9 | 7 | 2 | 0 | 21 | 4 | 0.67 |
| live, no contact | 11 | 0 | 0 | **0** | 1 | 1 | 0.07 |

- **No false alarms in 16 runs without an incident.** Glimmer raised a hand 4 times there, and SAM dismissed all 4.
- **14 of 17 incidents caught.**
- **Timing.** The raise SAM confirmed came between -1.2 s and +2.5 s of the true incident (median -0.1 s). The confirmation is ready a median 19.5 s after the incident (13-52 s), and SAM's see takes most of that time. The 44-52 s cases are the ones where the first raise was dismissed.
- **Glimmer's pace.** A look takes a median 0.97 s here, one look per 1.0 s. Live, beside the simulator, it is about 1.45 s (see below).
- **Cost.** SAM 3.1 cost $2.15 for the 33 runs.

| case | scene | truth | Glimmer raised (signs) | SAM: confirmed / dismissed | outcome | raised after | confirmed after | look s | SAM $ |
|---|---|---|---|---|---|---|---|---|---|
| control-box | box | none | 2 (stuck) | - / 2 | quiet |  |  | 0.91 | 0.22 |
| control-low_cube | low_cube | none | 0 (-) | - / 0 | quiet |  |  | 1.01 | 0.00 |
| control-ledge | ledge | none | 0 (-) | - / 0 | quiet |  |  | 0.94 | 0.00 |
| control-corner | corner | none | 0 (-) | - / 0 | quiet |  |  | 0.96 | 0.00 |
| control-doorway | doorway | none | 1 (fallen) | - / 1 | quiet |  |  | 1.0 | 0.09 |
| b1 | low_cube | contact 10.56 s | 3 (close, touching) | contact 10.12 s / 0 | caught | -0.16 | +17.6 | 0.99 | 0.09 |
| b2 | low_cube | contact 10.56 s | 6 (close, touching) | contact 10.12 s / 0 | caught | -1.24 | +13.7 | 0.88 | 0.09 |
| b5 | ledge | contact 9.34 s | 5 (close, fallen, stuck) | fall 10.05 s / 0 | caught | +0.68 | +17.3 | 0.93 | 0.09 |
| b6 | ledge | contact 9.34 s | 5 (close, fallen, stuck) | fall 10.05 s / 0 | caught | +1.56 | +18.8 | 0.85 | 0.09 |
| b7 | ledge | contact 9.34 s | 3 (fallen, stuck) | fall 10.05 s / 0 | caught | +2.47 | +19.5 | 0.81 | 0.09 |
| b9 | low_cube | contact 10.56 s | 6 (close, touching) | contact 10.12 s / 0 | caught | -1.24 | +12.9 | 0.89 | 0.09 |
| b10 | box | contact 18.43 s | 4 (close, stuck, touching) | contact 18.49 s / 2 | caught | -0.12 | +44.4 | 0.88 | 0.31 |
| b11 | box | contact 12.38 s | 2 (stuck) | - / 2 | miss |  |  | 1.02 | 0.27 |
| live12-before-1 | box | contact 11.58 s | 1 (close) | - / 1 | miss |  |  | 0.96 | 0.06 |
| live12-after-1 | box | none | 1 (close) | - / 1 | quiet |  |  | 0.96 | 0.07 |
| live12-before-2 | box | contact 10.60 s | 2 (close) | contact 10.66 s / 0 | caught | +0.59 | +21.4 | 1.11 | 0.06 |
| live12-after-2 | box | none | 0 (-) | - / 0 | quiet |  |  | 1.04 | 0.00 |
| live12-before-3 | box | contact 11.29 s | 2 (close) | contact 10.89 s / 0 | caught | -0.70 | +20.0 | 0.97 | 0.05 |
| live12-after-3 | box | none | 0 (-) | - / 0 | quiet |  |  | 1.08 | 0.00 |
| live12-before-4 | box | none | 0 (-) | - / 0 | quiet |  |  | 0.96 | 0.00 |
| live12-after-4 | box | none | 0 (-) | - / 0 | quiet |  |  | 0.94 | 0.00 |
| live12-before-5 | box | contact 11.19 s | 1 (close) | contact 10.90 s / 0 | caught | -0.09 | +23.4 | 1.0 | 0.05 |
| live12-after-5 | box | none | 0 (-) | - / 0 | quiet |  |  | 1.03 | 0.00 |
| live20-before-1 | box | contact 12.27 s | 4 (close, stuck) | contact 12.80 s / 1 | caught | +0.92 | +44.1 | 0.98 | 0.13 |
| live20-after-1 | box | none | 0 (-) | - / 0 | quiet |  |  | 0.96 | 0.00 |
| live20-before-2 | box | contact 16.87 s | 2 (close) | contact 16.96 s / 1 | caught | +0.63 | +51.7 | 1.0 | 0.18 |
| live20-after-2 | box | none | 0 (-) | - / 0 | quiet |  |  | 0.98 | 0.00 |
| live20-before-3 | box | contact 11.48 s | 4 (close, stuck) | contact 11.12 s / 0 | caught | -0.79 | +19.1 | 0.99 | 0.05 |
| live20-after-3 | box | none | 0 (-) | - / 0 | quiet |  |  | 0.98 | 0.00 |
| live20-before-4 | box | contact 11.71 s | 2 (close) | - / 1 | miss |  |  | 0.99 | 0.05 |
| live20-after-4 | box | none | 0 (-) | - / 0 | quiet |  |  | 1.06 | 0.00 |
| live20-before-5 | box | contact 11.62 s | 3 (close, touching) | contact 11.38 s / 0 | caught | -0.81 | +19.5 | 0.94 | 0.05 |
| live20-after-5 | box | none | 0 (-) | - / 0 | quiet |  |  | 0.96 | 0.00 |

live12-before-4 is a "before" run whose walk happened to miss the box: live, the brain's path varies a little from run to run. It counts as a negative.

## Why the three misses

- **b11:** Glimmer raised only "stuck", at 6.2 s and 19.0 s, never "close" near the 12.4 s contact. The first window named the purple box as the robot, and the robot check turned it down. That check is what keeps the controls quiet, so it stays. Asking Muse Spark to name the window again was tried in round 2 and gave "purple robot" too, so it was not kept.
- **live12-before-1 and live20-before-4:** Glimmer raised "close" on time (+0.03 s and -0.7 s). SAM followed the robot and the box correctly, but read no contact in the window. In live12-before-1 the closest gap was 2.8 px, against the 2 px rule. These are the same rules the proof uses, so they were not loosened for the watcher.

## How it got here

| round | looks | twin caught | controls false | live caught | live false |
|---|---|---|---|---|---|
| 1 | pair; touching, fallen, stuck | 8/8 | 0/5 | 5/9, of which 3 bogus | 0/11 |
| 2 | pair; + close; SAM: the robot must have moved | 7/8 | 0/5 | 6/9 | 0/11 |
| 3 (final) | one frame and pair alternating | 7/8 | 0/5 | 7/9 | 0/11 |

**Round 1.**
- The 3 bogus live catches were confirmed as falls of the purple box, which Glimmer had named as the robot, 8-9 s after the real contact. Honestly that is 2/9.
- Before it, a still box named as the robot was confirmed as "stuck" on a control. Since then stuck needs the robot to have moved first and then stay still for 4 s, after a 2 s grace.

**Round 2.**
- Added the "close" sign: any part of the robot within a foot's width of an object. From above, a foot brushing a box is a few pixels, and Glimmer rarely says "touching".
- Added the moved-robot check, which removed the bogus falls.

**Round 3.**
- A bench on the frames around each incident (from 1 s before to 1.5 s after, every 0.25 s) showed that the two kinds of look see different things:
  - the pair sees the low cube better: 9/11 frames vs 3/11;
  - a single frame sees the box better: b11 6/11 vs 0/11, live 61/77 vs 29/77.
- On 9 negative runs (17 frames each) the two flagged about as many frames.
- A single frame takes 0.9 s against 1.25 s. Alternating the two kinds gains a live catch (live20-before-1 and -2 now caught, live20-before-4 lost to the gap rule).

## Live: Glimmer beside the simulator

**Command:**
```
python3 -m blinkflow.watch live --brain <copy of duck-target> --seconds 20 --loop
```
Each run starts the sim, Viser and the sidecar, launches the brain, and watches. The target is a fresh copy of `duck-target`, with the known bug.

| run | code | lag of /frame (median / max) | look s | true contact | watcher | loop |
|---|---|---|---|---|---|---|
| live-1 | round 2, before the flush fix | 0.61 / 1.06 s | 1.85 | 12.09 s | missed (no raise) | - |
| live-2 | round 2 | 0.078 / 0.14 s | 1.79 | 12.02 s | missed (no raise) | - |
| live-3 | final | 0.073 / 0.10 s | 1.46 | none | quiet | - |
| live-4 | final | 0.083 / 0.10 s | 1.44 | none | quiet | - |
| live-5 | final | 0.083 / 0.11 s | 1.54 | 11.87 s | raised at 11.68 s (close); SAM: contact at 11.58 s; confirmed 20.3 s after the contact | **fixed in attempt 1, 172 s** |

**Requirement 2 holds in all 5 runs:**
- **Capture is not blocked.** The sidecar recorded every frame it should have (690/690, or 660/660 for live-3) while Glimmer was looking. Glimmer gets the newest frame when it is free; frames that arrive meanwhile are skipped, not queued.
- **VRAM.** The peak was 20,514 MiB of 24,564 with the simulator, Viser, NVENC and Glimmer all on the GPU. Glimmer reuses the warm copy at the same `num_ctx`.

**`/frame` was too late at first.** The ffmpeg segment muxer held each open segment in its buffer until the segment closed, so `/frame` could only serve the last closed second (0.6 s late on average). With `-segment_format_options flush_packets=1` it decodes the segment being written: 0.08 s.

**live-5 end to end, without anyone saying anything:**
- At 11.68 s of brain time Glimmer said "close" on a single frame.
- SAM 3.1 confirmed a contact at 11.58 s (the true one was 11.87 s), and the brain was stopped.
- The loop started from the confirmation window:
  - Muse Wonder named `brain.toml [obstacle] side_memory_seconds` (106 s, slower than the 55-81 s of `results/quick_loop.md`).
  - Muse Code changed it from 0.0 to 3.0.
  - The replay showed no contact, closest gap 106 px.
- From the contact to the proven fix: about 192 s.
- Cost: SAM for the confirmation $0.06; the loop $1.06.

## What this does not show

- **The suite runs Glimmer faster than live.** Offline, a look takes 0.97 s; beside the simulator it takes 1.45 s, so live sees about two thirds as many frames. Live looks happen every 1.5 s. A contact as brief as the box's (one tick in the contact log) can fall between two looks, as in live-1 and live-2.
- **Stuck has no positive in the set.** No layered bug leaves the robot stuck without touching or falling first, so the stuck path is only tested for not firing. It was raised 3 times on runs without an incident, and SAM dismissed them all. The loop is **not** started for a stuck robot, because the proof has no verdict for "stuck"; the watcher only reports it.
- **Four distinct twin behaviours, not eight.** b1/b2/b9 give the same trajectory in the twin, and so do b5/b6/b7.
- **All live runs are the purple box.**
- **Confirmation takes about 20 s.** The watcher says what happened and when, 20 s after the event; a raise comes within 1-2 s.
