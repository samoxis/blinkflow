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
| BlinkFlow, the film's run (Oct 31) | 1 | yes | 0.0 → 3.0 | contacts 1 → 0, closest 106 px | 4/4 clean | 41.6 | 386.6 | $0.005 | (in the $0.38) |
| BlinkFlow, the example (Nov 1) | 1 | yes | 0.0 → 3.0 | contacts 1 → 0, closest 107 px | 4/4 clean, each scene's own obstacle | 37.8 | 368.0 | $0.005 | (in the $0.95) |

**The control in this table, and the rule since.** Here the control followed objects Glimmer named in each
scene, as it did until Nov 1: run 1 followed a "brown edge" for the low cube, all three a "white rectangle" in
the doorway, and in run 3 the ledge's "yellow pit" was found in no frame, which then counted as clean. Since
Nov 1 each scene's own obstacle is followed, as the scene defines it (`blinkflow/scenes/obstacles.json`), and
an obstacle seen in no frame is no verdict. All three runs kept the same blob (`a2deec7`) as BlinkFlow; with
that rule, the Nov 1 example's control of that blob is 4/4 clean (closest 139, 157, 50 and 14 px).

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
ablation shows that **the demo bug is findable from the code alone**. A code bug (b7, below) turned out to be
findable from the code alone as well.

**What BlinkFlow's evidence changed here:** speed and the first attempt. With the cause cited to frames, the
brain's log and the line, Muse Code made the change in one attempt, 41.6 s and 6 tool calls; alone it took
2–3 attempts and 5–10 minutes of Muse Code (17–27 tool calls per working turn). The whole loop took 386.6 s
with seeing and diagnosing included; alone, 509–820 s without them (counted from Muse Code's first turn; the
replay before any change was taken from the example). In money the ablation was cheaper: no Muse Wonder
($0.21 in the example), and most SAM 3.1 replies came from the cache, since the same change gives the same
twin video. The proof itself is BlinkFlow's in both cases: without the replay and the control, nothing would
have said which of these attempts worked.

## A code bug: b7, the swapped drop position (Nov 1)

The same test on a bug in Python code rather than a setting: b7 of the bug suite (`results/bug_suite.md`),
where `depth.drop_zones` gives each drop's forward distance as its sideways offset and back
(`DropZone(r, c, nominal * by, nominal * bx, ...)`, `depth.py:320`), so the robot walks into the yellow pit of
the ledge scene. Muse Code got only "a couple of seconds ago the robot fell into the yellow pit" and the
buggy brain (`653458d`, in a copy holding that one commit, so no fix sits in its history). The same method as
above: at most 3 attempts, each judged by the frozen pass's own scene replayed in the twin (the fall at
10.06 s, 1.48 m walked), then the control in the four other scenes (box, low cube, corner, doorway), each
following its own obstacle. Between attempts, only "the robot still fell into the yellow pit".

`tools/ablation.py --scene ledge`; the runs are in `~/blinkflow-runs/ablation/b7-20261101-102347/run-{1,2,3}`.

| run | attempts | found the swap | the change kept | twin proof | control | Muse Code time (s) | whole run (s) | Muse Code cost | proof + control cost |
|---|---|---|---|---|---|---|---|---|---|
| b7 · 1 | 2 | yes, in both | `by, bx` → `bx, by` | fall at 10.06 s → none, walked 2.26 m, pit no closer than 157 px | 4/4 clean | 144.0 | 398.7 | $0.014 | $0.235 |
| b7 · 2 | 1 | yes | `by, bx` → `bx, by` | the same | 4/4 clean | 38.6 | 269.9 | $0.006 | $0 (cached) |
| b7 · 3 | 1 | yes | `by, bx` → `bx, by` | the same | 4/4 clean | 61.6 | 282.8 | $0.006 | $0 (cached) |
| b7 · BlinkFlow, frozen-code pass (Oct 28) | 1 | yes | `by, bx` → `bx, by` | fall → none | 5/5 clean (the rule of then) | 23.6 | 152 | (in the $0.98) | (in the $0.98) |

All four kept the same blob (`7ea627d`), BlinkFlow's included. The control closest gaps: box 107, low cube
139, corner 50, doorway 14 px. Run 1's first attempt made the same change and was rejected by the audit
before any replay, because it wrote a probe script to `/tmp/drop_probe.py`; attempt 2 passed. Runs 2 and 3
passed on the first attempt (9 tool calls each; BlinkFlow's attempt took 3).

**Both bugs, in short.** On both, the purple box (a setting) and b7 (a line of code), the cause was findable
from the code alone: Muse Code, given only the sentence, made BlinkFlow's own change in 3 of 3 runs each.
What BlinkFlow brought each time was the right fix on the first attempt (1 of 1, against 0 of 3 runs alone on
the purple box and 2 of 3 on b7) and the proof. Alone, Muse Code's attempts were not judged by Muse Code: the
ones that failed were stopped by BlinkFlow's gate and audit before any replay (a write to `/tmp`, an empty
turn), and the ones kept were kept because BlinkFlow's replay in the twin and its control in the other scenes,
from pixels, said they worked. On b7 the evidence saved less time than on the purple box (24 s against
39–144 s of agent time, above). Two bugs are still a small sample.

## A vague sentence: "something went wrong" (Nov 1)

The question: when does BlinkFlow's seeing become indispensable rather than faster? The same two bugs, with a
sentence that names no obstacle, no fall and no colour: **"a couple of seconds ago something went wrong with
the robot"**. Alone, as above (at most 3 attempts, the twin proof, the control in the four other scenes), and
between attempts only "something still went wrong with the robot" (`tools/ablation.py --said`). Then the
same sentence through the whole of BlinkFlow (see → diagnose → fix → prove, `blinkflow.voice clip --text ...
--auto`), once per bug, from saved inputs: the purple box from the example's 60 s clip with its key press
(13.483 s); b7 from its incident in the twin, rendered again to 14 s with the same buggy brain (contact
9.335 s, fall 10.25 s, as in the suite) so the key could go down 2.58 s after the fall, as on the purple box.

Each bug ran on its own copy of the buggy brain (purple box: the tree of `b2fe90a`; b7: `653458d`), with no
fix in its history. The runs are in `~/blinkflow-runs/ablation/vague-20261101-114005/` (not in the repo).

| bug | sentence | alone: fixed? | alone: attempts | alone: Muse Code time (s) | alone: whole run (s) | alone: what it changed | with BlinkFlow: fixed? | with BlinkFlow: attempts | with BlinkFlow: Muse Code (s) | with BlinkFlow: seen → verified (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| purple box · 1 | vague | yes, control 4/4 clean | 1 | 375.5 | 618.6 | `brain.toml` `side_memory_seconds` 0.0 → 3.0 | yes, control 4/4 clean | 1 | 42.5 | 358.1 |
| purple box · 2 | vague | yes, control 4/4 clean | 1 | 160.9 | 366.5 | the same | | | | |
| purple box · 3 | vague | yes, control 4/4 clean | 2 | 771.8 | 973.9 | attempt 1: `src/microduck_brain/brain.py` (rejected by the audit, `/tmp` named; never replayed); attempt 2: the same as run 1 | | | | |
| b7 · 1 | vague | yes, control 4/4 clean | 1 | 216.5 | 425.0 | `depth.py` `drop_zones`: `by, bx` → `bx, by` | yes, control clean | 1 | 43.8 | 327.9 |
| b7 · 2 | vague | yes, control 4/4 clean | 1 | 104.8 | 310.7 | the same | | | | |
| b7 · 3 | vague | yes, control 4/4 clean | 1 | 180.6 | 383.2 | the same | | | | |

Every kept change is BlinkFlow's own blob (`a2deec7` for the purple box, `7ea627d` for b7), in the six runs
alone and in both loops. Alone, Muse Code used 14–47 tool calls per run; its cost was $0.009–0.039 a run, and
the proof and control came from SAM 3.1's cache ($0). The two loops cost $0.38 (purple box, mostly cached)
and $0.76 (b7).

**What BlinkFlow said it saw**, from the vague sentence: "the white robot touched the purple box at t = 10.90 s"
and "the white robot fell off the yellow pit at t = 10.05 s". Glimmer read the sentence as "other, 2 s before
the key"; SAM 3.1 then found the incident in the window from pixels, and Muse Wonder's cause was
`brain.toml [obstacle] side_memory_seconds` and `depth.py::drop_zones`.

**What this says.** For these two bugs the eyes were not indispensable: Muse Code alone, told only that
something went wrong, found the same fix in 6 of 6 runs, on the first attempt in 5. The vague sentence did
not make it worse than the specific one on the purple box (161–772 s against 296–597 s, 1–2 attempts against
2–3) and made it slower on b7 (105–217 s against 39–144 s). Both bugs leave a single suspicious line in a
small brain; a vague complaint about a robot with one odd setting or one swapped pair still leads there. With
BlinkFlow the change came in 43–44 s of Muse Code, first attempt, and the person learned what had gone
wrong, at which second, which the agent alone never said. Bugs whose cause is not the only odd line in
the code are where the eyes would have to earn more than speed; none was tried here.

**One thing the b7 loop shows about the control.** BlinkFlow's loop runs its control on the four scenes other
than the demo's box (`prove.CONTROL_SCENES`): for an incident in the ledge scene that list holds the ledge
itself and leaves the box out. The b7 loop's control was low cube, ledge, corner and doorway, all clean; the
box scene was not replayed with that change. The ablation script leaves out the incident's own scene instead
(`--scene`).
