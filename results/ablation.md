# Muse Code alone, from the sentence only (Nov 1)

The question: how much of the purple-box fix comes from BlinkFlow's seeing and diagnosis, and how much would
Muse Code find by itself? Muse Code got **only the person's sentence**, "a couple of seconds ago the robot hit
the purple box", and the target at `b2fe90a` (the buggy brain). No frames, no SAM 3.1, no Muse Wonder, no log,
no file named. Everything else as in the real loop: the same model (`muse-spark-1.3-contributor`), the same
gate and after-turn audit (`fix.muse_code`), the same rules in the prompt, at most 3 attempts. Each change was
judged as BlinkFlow judges its own: the example's scene replayed in the twin, then the control in the four
other scenes, from pixels. Between attempts Muse Code heard only what a person watching would say ("the robot
still hit the purple box", or "no longer, but other scenes failed"), plus its own earlier diff, as in the
real loop's history.

`tools/ablation.py`; the runs are in `~/blinkflow-runs/ablation/20261101-013935/run-{1,2,3}` (not in the repo).

| run | attempts | found `side_memory_seconds` | the change kept | twin proof | control | Muse Code time (s) | whole run (s) | Muse Code cost | proof + control cost |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | yes, in both | 0.0 → 3.0 | contacts 1 → 0, closest 106 px | 4/4 clean | 577.7 | 802.6 | $0.041 | $0.060 |
| 2 | 2 | yes, in attempt 2 | 0.0 → 3.0 | contacts 1 → 0, closest 106 px | 4/4 clean | 596.5 | 820.1 | $0.034 | $0.013 |
| 3 | 3 | yes, in attempt 3 | 0.0 → 3.0 | contacts 1 → 0, closest 106 px | 4/4 clean | 295.5 | 508.9 | $0.014 | $0.009 |
| BlinkFlow, the example | 1 | yes | 0.0 → 3.0 | contacts 1 → 0, closest 106 px | 4/4 clean | 41.6 | 386.6 | $0.005 | (in the $0.38) |

**Muse Code alone found the cause and the same fix in 3 of 3 runs**, byte for byte the change BlinkFlow kept
(blob `a2deec7`), and that change passed the twin proof and the control every time. It did not get there on
the first attempt in any run:

- Run 1, attempt 1: the right change, rejected by the audit before any replay, because one shell command named
  `/tmp/` (`ls -la /tmp/`, "look for recordings"); the gate had blocked it before it ran. Attempt 2 made the
  same change and passed.
- Run 2, attempt 1: a different idea, 47 lines in `src/microduck_brain/hazards.py` (keep remembered low
  objects after passing them), and a scratch script in `/tmp`; rejected by the audit, never replayed, so
  untested. Attempt 2: `side_memory_seconds`, passed.
- Run 3, attempts 1 and 2: the host answered "completed" after ~22 s with no tool call, no text and no token
  count, twice; with no change there was nothing to replay. Attempt 3: `side_memory_seconds`, passed.
- A first run 2 stopped on a network fault (Baseten's name did not resolve while the control named its
  objects), not on Muse Code; it was run again. Its attempt 1 had made the same change, in 309.8 s.

**How it found it**, in its own notes: `side_memory_seconds = 0.0` is the only value in `brain.toml` that
differs from the default in the code (3.0). For this bug that is a strong clue that needs no picture. So this
ablation shows that **the demo bug is findable from the code alone**; it does not show the same for bugs
where the code itself is wrong rather than a setting, and it covered this one bug only.

**What BlinkFlow's evidence changed here:** speed and the first attempt. With the cause cited to frames, the
brain's log and the line, Muse Code made the change in one attempt, 41.6 s and 6 tool calls; alone it took
2–3 attempts and 5–10 minutes of Muse Code (17–27 tool calls per working turn). The whole loop took 386.6 s
with seeing and diagnosing included; alone, 509–820 s without them (counted from Muse Code's first turn; the
replay before any change was taken from the example). In money the ablation was cheaper: no Muse Wonder
($0.21 in the example), and most SAM 3.1 replies came from the cache, since the same change gives the same
twin video. The proof itself is BlinkFlow's in both cases: without the replay and the control, nothing would
have said which of these attempts worked.
