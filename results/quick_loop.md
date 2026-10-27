# Quick loop: purple box, seen -> fixed and verified

Oct 27. The live purple-box incident (`clips/20261026-173622-2e3fba.json`), full loop (`blinkflow.fix`) on a
fresh copy of `~/duck-target` each time, then the scorer (twin's own contact log: box 20 s + control in all
5 scenes). `python3 tools/profile_loop.py run LABEL` / `table LABEL...`. Seconds, wall clock.

`before` is the code at 995a71d. Its twin render was measured on its own (82.9 s sequential, 658 frames);
the base-1 run itself already rendered in parallel, so its loop was 317.9 s, and with the sequential render it
is ~440 s (the Oct 26 run took 455 s). opt-1 has parallel render, chunked SAM, parallel mask decode, Glimmer
warm, Wonder cache warm-up and the before-replay in the background; opt-2 adds the faster gap measure, key
frames decoding only their masks and the workspace in Muse Code's prompt; opt-3 adds the background render at
low priority.

| step | before | opt-1 | opt-2 | opt-3 |
|---|---|---|---|---|
| Glimmer: name robot + object | 2.4 | 1.6 | 1.8 | 1.9 |
| SAM 3.1 on the incident (robot, object; slowest call) | 25.2 | 12.8 | 13.2 | 11.7 |
| see: the rest (ffmpeg, masks, measuring) | 5.1 | 9.2 | 9.9 | 7.2 |
| Glimmer: describe 4 key frames | 7.0 | 6.5 | 5.2 | 5.3 |
| Muse Wonder: prompt cache warm-up (background) | - | 2.1 | 3.2 | 2.1 |
| Muse Wonder: diagnosis | 72.3 | 81.1 | 56.8 | 54.9 |
| Muse Wonder: output tokens | 6717 | 6854 | 4670 | 4680 |
| Muse Wonder: input tokens read from cache | 8166 | 30182 | 30182 | 30310 |
| replay before: twin render | 82.9 | 31.7 (bg) | 28.6 (bg) | 29.4 (bg) |
| replay before: SAM 3.1 + verdict | 60.6 | 17.1 (bg) | 16.3 (bg) | 16.2 (bg) |
| Muse Code: edit | 29.0 | 31.5 | 17.6 | 18.9 |
| replay after: twin render | 82.9 | 21.7 | 20.3 | 20.3 |
| replay after: SAM 3.1 + verdict | 52.9 | 15.6 | 14.7 | 13.5 |
| scorer: box 20 s + control in 5 scenes | 2.8 | 2.8 | 2.8 | 2.8 |
| **seen -> fixed and verified** | **~440** | **188.0** | **142.7** | **137.1** |
| attempts / fixed / control clean | 1 / yes / yes | 1 / yes / yes | 1 / yes / yes | 1 / yes / yes |
| model cost ($) | 0.91 | 1.02 | 0.87 | 0.88 |

(bg) = in the background, off the critical path. opt-3's critical path: see 0-20.8, understand 20.8-84.4
(key frames + Wonder), Muse Code 84.4-103.3, replay after 103.3-137.1.

## What changed

- **Twin render in parallel** (`twin.py`, `ParallelVideo`): the run keeps each frame's poses; 12 forked
  processes render them with Mesa llvmpipe into the same encoder. Output byte-identical to the sequential
  render (md5). 82.9 -> ~20 s. It stops scaling at 8 processes: the CPU (24 threads) is full, one frame costs
  ~320 ms per process under load against 110 ms alone; encoding is 0.6 s.
- **SAM 3.1 in pieces** (`see.py`): the shot is cut into ~90-frame pieces (15 frames of overlap to let the
  tracker settle, dropped), all pieces of both concepts sent at once, replies renumbered and merged. Server
  time grows with the frames returned: 43.7 s for 658 frames whole, 11.6 s per 90-frame piece.
  Checked on the base-1 replays: same verdicts, same first contact (11.455 s), closest gap 106.6 vs 106.4 px,
  robot mask IoU median 0.982, box 0.998, no frame where only one method found a mask.
- **Mask decoding off the GIL** (`sam.py`): the range decoder is pure Python (26 s for 658 box frames, and it
  blocked the threads waiting on SAM); now a process pool decodes each frame line as it streams in: 4.6 s.
- **Gap measure** (`see.py`): nearest edge pixels in the pair's bounding box via a k-d tree instead of a
  distance transform: 2.4 ms vs 7 ms a frame, identical values on every saved frame of these runs.
- **Key frames** (`diagnose.py`) decode only the 5 masks they draw (3.6 s -> 0.7 s; same images, md5), and
  Glimmer describes the 4 at once.
- **Glimmer kept warm** (`keep_alive` 30 m, loaded at the start) and **Wonder's prompt cache** warmed in
  the background with the fixed head (instructions + the target's code): 30k of the input tokens come from
  the cache instead of 8k. It lowers cost, not latency: Wonder's time follows its output (~85 tokens/s).
- **The replay before any change** renders and is checked in the background while the incident is seen and
  diagnosed (at `nice 10`, so it does not slow the critical path); it is still required before Muse Code runs.
- **Muse Code's prompt** carries the workspace's file list and the file the diagnosis names, numbered: 4 tool
  calls instead of 7 (no `ls`, `git log`, `ls -R`), 31.5 -> 18 s. Same edit.

Unchanged: the same twin replay before and after, the same SAM verdict from masks only, the same scorer
(box + control in all 5 scenes), same Wonder model, effort and schema.

## What still decides the time

Muse Wonder is ~40% of the loop and varies with its output: 55-81 s here, 33-101 s in earlier purple-box
runs. Everything else on the critical path is ~82 s, so the loop stays under 3 minutes while Wonder answers
in under ~98 s. Pre-spawning Muse Code is pointless (spawn + session 0.4 s). The twin render is CPU-bound.
