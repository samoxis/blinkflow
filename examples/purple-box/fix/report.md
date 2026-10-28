# BlinkFlow: white robot touches the purple box

**Fixed and verified in attempt 1 of 1.** Seen -> fixed and verified: **197 s** of machine time (the person took 2.0 s to answer "Fix it?", not counted; 442 s in all with the control and the answers).

## What was seen

Snapshot `~/blinkflow-runs/voice/20261028-212723/window/snapshot.json` (live run, wall clock). Named by glimmer: robot = *white robot*, object = *purple box*. First contact (base reading) at frame 202, t = 12.503 s after the brain starts, 2026-10-28T21:27:56.489+00:00.

![incident](~/blinkflow-runs/voice/20261028-212723/window/evidence/evidence.png)

## Cause (Muse Wonder)

`brain.toml`, `[obstacle] configuration`, lines 29-29: side_memory_seconds is set to 0.0

In plain words: The robot walked forward past a box that sat beside it, outside the patch directly ahead that it uses to decide to stop. A separate safeguard was meant to remember close objects at its sides while it passed them, but that safeguard was turned off in its settings, so it kept walking straight until its side touched the box.

Confidence 0.82; grounded in key frames and log ticks: NO. Full diagnosis: `~/blinkflow-runs/voice/20261028-212723/window/evidence/diagnosis.md`.

## The fix

Muse Code: Changed `side_memory_seconds` in brain.toml from 0.0 to 3.0, restoring the built-in default. This re-enables the side-hazard memory so close wall returns beside the robot are remembered while passing and can block forward motion.

1 file changed, 1 insertion(+), 1 deletion(-). Committed in the target as `d1e47a7` (base `b2fe90a`).

```diff
diff --git a/brain.toml b/brain.toml
index 86c6b1c..a2deec7 100644
--- a/brain.toml
+++ b/brain.toml
@@ -26,7 +26,7 @@ first_row = 0             # frame rows used for walls (0 = top). Rows below last
 last_row = 4              # they are handled separately, as low objects and drops.
 corridor_half_width = 0.14 # half-width of the robot's swept corridor (m): body width + margin
 sensor_lateral = 0.0224   # the sensor sits this far left of the robot's axis (m; MJCF `tof` site)
-side_memory_seconds = 0.0 # remember wall returns near the body for this long (s)
+side_memory_seconds = 3.0 # remember wall returns near the body for this long (s)
 front_first_col = 1       # central columns used to decide whether the sensor is blind (0 = the sensor's left)
 front_last_col = 6
 min_zones = 2             # how many zones must be close for it to count (rejects single-zone noise)
```

## Proof: the same scenario replayed in the twin, before and after

The verdict comes from SAM 3.1 masks on the rendered incident shot, following the incident's robot and purple box. Contact = masks touching with the robot's feet at the object's base (the base reading), or, when the feet never get there, with the robot within reach of the base (body reading: another part of it, such as its head).

| replay | contact | first contact (s) | masks touch on screen (s) | closest gap (px) | walked (m) |
|---|---|---|---|---|---|
| before (base commit) | **yes** | 11.455 | 10.650 | 1 | 3.15 |
| attempt 1 (kept) | **no** | - | - | 106 | 2.78 |

![before](before/evidence/evidence.png)

![after](attempt-1/evidence/evidence.png)

## Control: the same brain in every other scene

Replayed in the twin, each scene's shot followed by SAM 3.1 (every 3rd frame) with the names Glimmer gave it; clean = no contact and no fall, from pixels only.

| scene | named | clean | why |
|---|---|---|---|
| low_cube | white robot / cyan box | yes | no contact, no fall; closest gap 30 px |
| ledge | white robot / gray block | yes | no contact, no fall; closest gap 0 px |
| corner | white robot / red barrier | yes | no contact, no fall; closest gap 50 px |
| doorway | white robot / white rectangle | yes | no contact, no fall; closest gap 36 px |

## Attempts

### Attempt 1: kept

- diagnosis used: `~/blinkflow-runs/voice/20261028-212723/window/evidence/diagnosis.md` (cause `brain.toml::[obstacle] side_memory_seconds`)
- Muse Code: completed, 42 s, 1 file changed, 1 insertion(+), 1 deletion(-); files: brain.toml
- its note: Changed `side_memory_seconds` in brain.toml from 0.0 to 3.0, restoring the built-in default. This re-enables the side-hazard memory so close wall returns beside the robot are remembered while passing and can block forward motion.
- replay: no contact; closest gap 106 px at t = 12.89 s

## Time

Stages marked background run beside the others, so the column does not add up to the total.

| stage | from (s) | s |
|---|---|---|
| Glimmer loaded and kept warm (background) | 0 | 0 |
| Muse Wonder's prompt cache: instructions + code (background) | 0 | 4 |
| replay before any change: twin render (background) | 0 | 27 |
| understand (Glimmer key frames, Muse Wonder) | 4 | 78 |
| replay before any change: SAM 3.1 + verdict (background) | 27 | 14 |
| attempt 1: the person decides to fix | 82 | 2 |
| wait for the replay before any change | 84 | 0 |
| attempt 1: Muse Code edits the target | 84 | 42 |
| attempt 1: replay and look again | 126 | 40 |
| attempt 1: control, every other scene (pixels) | 166 | 274 |
| attempt 1: the person decides to keep | 440 | 2 |
| **total** | 0 | **442** |

The incident's evidence and first diagnosis were reused from an earlier run; their time is not counted above.

## Models

| stage | model | where | purpose | input tokens (cached) | output tokens | cost $ | s |
|---|---|---|---|---|---|---|---|
| incident | muse-glimmer | local | when it happened and what it touched, from the person's words | 239 | 28 | 0.0000 | 2 |
| incident | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1528 | 42 | 0.0000 | 2 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 0-103, sent from 0) | - | - | 0.0208 | 8 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 104-208, sent from 89) | - | - | 0.0240 | 12 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 0-103, sent from 0) | - | - | 0.0208 | 16 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 104-208, sent from 89) | - | - | 0.0240 | 19 |
| incident | muse-glimmer | local | describe key frame K1 | 589 | 48 | 0.0000 | 2 |
| incident | muse-glimmer | local | describe key frame K3 | 587 | 39 | 0.0000 | 4 |
| incident | muse-glimmer | local | describe key frame K4 | 586 | 46 | 0.0000 | 6 |
| incident | muse-glimmer | local | describe key frame K2 | 591 | 45 | 0.0000 | 7 |
| incident | muse-wonder-1.0 | Meta Model API | diagnose (evidence, run 1) | 41239 (30182) | 6701 | 0.1843 | 67 |
| before | sam-3.1 | cached | track 'white robot' (frames 92-183, sent from 77) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 645-736, sent from 630) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 553-644, sent from 538) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 0-91, sent from 0) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 184-275, sent from 169) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 276-367, sent from 261) | - | - | 0.0000 | 5 |
| before | sam-3.1 | cached | track 'white robot' (frames 461-552, sent from 446) | - | - | 0.0000 | 7 |
| before | sam-3.1 | cached | track 'purple box' (frames 0-91, sent from 0) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 368-460, sent from 353) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 553-644, sent from 538) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 184-275, sent from 169) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 461-552, sent from 446) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'white robot' (frames 368-460, sent from 353) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 92-183, sent from 77) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 645-736, sent from 630) | - | - | 0.0000 | 9 |
| before | sam-3.1 | cached | track 'purple box' (frames 276-367, sent from 261) | - | - | 0.0000 | 9 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 92-183, sent from 77) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 0-91, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 184-275, sent from 169) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 0-91, sent from 0) | - | - | 0.0000 | 1 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 92-183, sent from 77) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 184-275, sent from 169) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 645-736, sent from 630) | - | - | 0.0214 | 4 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 553-644, sent from 538) | - | - | 0.0214 | 5 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 276-367, sent from 261) | - | - | 0.0214 | 5 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 368-460, sent from 353) | - | - | 0.0216 | 6 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 461-552, sent from 446) | - | - | 0.0214 | 7 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 276-367, sent from 261) | - | - | 0.0214 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 461-552, sent from 446) | - | - | 0.0214 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 368-460, sent from 353) | - | - | 0.0216 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 553-644, sent from 538) | - | - | 0.0214 | 9 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 645-736, sent from 630) | - | - | 0.0214 | 11 |
| attempt-1 control corner | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 55 | 0.0000 | 21 |
| attempt-1 control corner | sam-3.1 | Meta Model API | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0220 | 7 |
| attempt-1 control corner | sam-3.1 | Meta Model API | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0250 | 8 |
| attempt-1 control corner | sam-3.1 | Meta Model API | track 'red barrier' (frames 110-219, sent from 95) | - | - | 0.0250 | 12 |
| attempt-1 control corner | sam-3.1 | Meta Model API | track 'red barrier' (frames 0-109, sent from 0) | - | - | 0.0220 | 13 |
| attempt-1 control doorway | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 58 | 0.0000 | 16 |
| attempt-1 control doorway | sam-3.1 | Meta Model API | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0250 | 6 |
| attempt-1 control doorway | sam-3.1 | Meta Model API | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0220 | 7 |
| attempt-1 control doorway | sam-3.1 | Meta Model API | track 'white rectangle' (frames 0-109, sent from 0) | - | - | 0.0220 | 9 |
| attempt-1 control doorway | sam-3.1 | Meta Model API | track 'white rectangle' (frames 110-219, sent from 95) | - | - | 0.0250 | 10 |
| attempt-1 control ledge | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 42 | 0.0000 | 19 |
| attempt-1 control ledge | sam-3.1 | Meta Model API | track 'yellow pit' (frames 0-109, sent from 0) | - | - | 0.0220 | 5 |
| attempt-1 control ledge | sam-3.1 | Meta Model API | track 'yellow pit' (frames 110-219, sent from 95) | - | - | 0.0250 | 5 |
| attempt-1 control ledge | sam-3.1 | Meta Model API | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0220 | 7 |
| attempt-1 control ledge | sam-3.1 | Meta Model API | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0250 | 8 |
| attempt-1 control ledge | muse-spark-open-1026 | Baseten | name the robot and the object or hazard nearest to it | 1500 (128) | 806 | 0.0052 | 6 |
| attempt-1 control ledge | sam-3.1 | Meta Model API | track 'gray block' (frames 0-109, sent from 0) | - | - | 0.0220 | 21 |
| attempt-1 control ledge | sam-3.1 | Meta Model API | track 'gray block' (frames 110-219, sent from 95) | - | - | 0.0250 | 22 |
| attempt-1 control low_cube | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 60 | 0.0000 | 22 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'floor edge' (frames 0-109, sent from 0) | - | - | 0.0220 | 5 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'floor edge' (frames 110-219, sent from 95) | - | - | 0.0250 | 5 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0220 | 7 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0250 | 9 |
| attempt-1 control low_cube | muse-spark-open-1026 | Baseten | name the robot and the object or hazard nearest to it | 1500 (128) | 1975 | 0.0101 | 10 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'cyan box' (frames 0-109, sent from 0) | - | - | 0.0220 | 8 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'cyan box' (frames 110-219, sent from 95) | - | - | 0.0250 | 8 |
| incident | muse-wonder-1.0 | Meta Model API | warm the prompt cache (instructions + code) | 30279 (30182) | 16 | 0.0067 | 4 |
| attempt-1 | muse-spark-1.3-contributor | Muse Code (muse serve, sandboxed) -> Meta Model API | fix attempt 1 | 196387 (153796) | 651 | 0.0047 | 42 |

Total $0.985. Every call is in `models.json`; Muse Code's cost is the host's own estimate.

## Guardrails

- the person decided: Fix it? yes (attempt 1, 2 s); Keep the fix? yes (attempt 1, 2 s)
- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`), approval mode `promptUnmatched`; edits are approved only when every path is inside the target.
- approval requests that reached BlinkFlow: 0 (in-workspace reads and edits are allowed by the host's own rules and never ask).
- every tool call was audited after each turn (file paths, paths named in shell commands); an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.
- the simulator's contact log and the twin's record of falls are not read by BlinkFlow; the scorers (tools/live_check.py, tools/bug_suite.py) do that.
