# BlinkFlow: white robot touches the purple box

**Fixed and verified in attempt 1 of 1.** Seen -> fixed and verified: **234 s** of machine time (the person took 7.5 s to answer "Fix it?", not counted; 454 s in all with the control and the answers).

## What was seen

Snapshot `~/blinkflow-runs/voice/20261029-170922/window/snapshot.json` (live run, wall clock). Named by glimmer: robot = *white robot*, object = *purple box*. First contact (base reading) at frame 163, t = 11.202 s after the brain starts, 2026-10-29T17:09:55.286+00:00.

![incident](~/blinkflow-runs/voice/20261029-170922/window/evidence/evidence.png)

## Cause (Muse Wonder)

`brain.toml`, `[obstacle] side_memory_seconds`, lines 29-29: side_memory_seconds is set to 0.0, disabling the hazard memory for wall returns near the body

In plain words: The box approached at the very edge of the depth sensor's view, beside the robot rather than in the centre of its path, so the ordinary check of what lies directly ahead stayed clear and the robot kept walking. A separate safeguard exists that remembers nearby surfaces seen at the sides, but that memory was switched off in the settings, so those edge sightings left no trace and were never acted on.

Confidence 0.62; grounded in key frames and log ticks: yes. Full diagnosis: `~/blinkflow-runs/voice/20261029-170922/window/evidence/diagnosis.md`.

## The fix

Muse Code: Changed `side_memory_seconds` in brain.toml from 0.0 to 3.0, restoring the built-in default. This re-enables the side-hazard memory so wall returns seen in the outer depth columns are retained and merged into the view ahead, letting the robot steer or stop before a side object like the purple box.

1 file changed, 1 insertion(+), 1 deletion(-). Committed in the target as `77db417` (base `b2fe90a`).

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
| low_cube | white robot / gray pillar | yes | no contact, no fall; closest gap 2 px |
| ledge | white robot / gray block | yes | no contact, no fall; closest gap 0 px |
| corner | white robot / red barrier | yes | no contact, no fall; closest gap 50 px |
| doorway | white robot / white rectangle | yes | no contact, no fall; closest gap 36 px |

## Attempts

### Attempt 1: kept

- diagnosis used: `~/blinkflow-runs/voice/20261029-170922/window/evidence/diagnosis.md` (cause `brain.toml::[obstacle] side_memory_seconds`)
- Muse Code: completed, 37 s, 1 file changed, 1 insertion(+), 1 deletion(-); files: brain.toml
- its note: Changed `side_memory_seconds` in brain.toml from 0.0 to 3.0, restoring the built-in default. This re-enables the side-hazard memory so wall returns seen in the outer depth columns are retained and merged into the view ahead, letting the robot steer or stop before a side object like the purple box.
- replay: no contact; closest gap 106 px at t = 12.89 s

## Time

Stages marked background run beside the others, so the column does not add up to the total.

| stage | from (s) | s |
|---|---|---|
| Glimmer loaded and kept warm (background) | 0 | 0 |
| Muse Wonder's prompt cache: instructions + code (background) | 0 | 2 |
| replay before any change: twin render (background) | 0 | 25 |
| understand (Glimmer key frames, Muse Wonder) | 2 | 130 |
| replay before any change: SAM 3.1 + verdict (background) | 25 | 14 |
| attempt 1: the person decides to fix | 132 | 8 |
| wait for the replay before any change | 140 | 0 |
| attempt 1: Muse Code edits the target | 140 | 37 |
| attempt 1: replay and look again | 176 | 33 |
| attempt 1: control, every other scene (pixels) | 210 | 232 |
| attempt 1: the person decides to keep | 442 | 13 |
| **total** | 0 | **454** |

The incident's evidence and first diagnosis were reused from an earlier run; their time is not counted above.

## Models

| stage | model | where | purpose | input tokens (cached) | output tokens | cost $ | s |
|---|---|---|---|---|---|---|---|
| incident | muse-voice-transcribe-1.0 | Meta Model API | what the person said (push-to-talk) | - | - | 0.0003 | 4 |
| incident | muse-glimmer | local | when it happened and what it touched, from the person's words | 241 | 29 | 0.0000 | 1 |
| incident | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1530 | 42 | 0.0000 | 2 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 0-101, sent from 0) | - | - | 0.0204 | 8 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 0-101, sent from 0) | - | - | 0.0204 | 10 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 102-202, sent from 87) | - | - | 0.0232 | 12 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 102-202, sent from 87) | - | - | 0.0232 | 13 |
| incident | muse-glimmer | local | describe key frame K1 | 589 | 48 | 0.0000 | 2 |
| incident | muse-glimmer | local | describe key frame K2 | 591 | 46 | 0.0000 | 3 |
| incident | muse-glimmer | local | describe key frame K4 | 586 | 53 | 0.0000 | 5 |
| incident | muse-glimmer | local | describe key frame K3 | 587 | 61 | 0.0000 | 7 |
| incident | muse-wonder-1.0 | Meta Model API | diagnose (evidence, run 1) | 41259 (30182) | 9102 | 0.2324 | 120 |
| before | sam-3.1 | cached | track 'white robot' (frames 184-275, sent from 169) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 553-644, sent from 538) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 0-91, sent from 0) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 92-183, sent from 77) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 645-736, sent from 630) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 276-367, sent from 261) | - | - | 0.0000 | 3 |
| before | sam-3.1 | cached | track 'white robot' (frames 461-552, sent from 446) | - | - | 0.0000 | 5 |
| before | sam-3.1 | cached | track 'purple box' (frames 184-275, sent from 169) | - | - | 0.0000 | 5 |
| before | sam-3.1 | cached | track 'purple box' (frames 92-183, sent from 77) | - | - | 0.0000 | 6 |
| before | sam-3.1 | cached | track 'purple box' (frames 645-736, sent from 630) | - | - | 0.0000 | 6 |
| before | sam-3.1 | cached | track 'purple box' (frames 553-644, sent from 538) | - | - | 0.0000 | 6 |
| before | sam-3.1 | cached | track 'white robot' (frames 368-460, sent from 353) | - | - | 0.0000 | 7 |
| before | sam-3.1 | cached | track 'purple box' (frames 276-367, sent from 261) | - | - | 0.0000 | 7 |
| before | sam-3.1 | cached | track 'purple box' (frames 461-552, sent from 446) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'purple box' (frames 368-460, sent from 353) | - | - | 0.0000 | 9 |
| before | sam-3.1 | cached | track 'purple box' (frames 0-91, sent from 0) | - | - | 0.0000 | 10 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 92-183, sent from 77) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 0-91, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 184-275, sent from 169) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 553-644, sent from 538) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 276-367, sent from 261) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 645-736, sent from 630) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 368-460, sent from 353) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 461-552, sent from 446) | - | - | 0.0000 | 1 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 0-91, sent from 0) | - | - | 0.0000 | 1 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 184-275, sent from 169) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 553-644, sent from 538) | - | - | 0.0000 | 3 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 368-460, sent from 353) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 645-736, sent from 630) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 92-183, sent from 77) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 461-552, sent from 446) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 276-367, sent from 261) | - | - | 0.0000 | 6 |
| attempt-1 control corner | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 53 | 0.0000 | 2 |
| attempt-1 control corner | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control corner | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control corner | sam-3.1 | cached | track 'red barrier' (frames 110-219, sent from 95) | - | - | 0.0000 | 2 |
| attempt-1 control corner | sam-3.1 | cached | track 'red barrier' (frames 0-109, sent from 0) | - | - | 0.0000 | 4 |
| attempt-1 control doorway | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 58 | 0.0000 | 3 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 2 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white rectangle' (frames 0-109, sent from 0) | - | - | 0.0000 | 3 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 4 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white rectangle' (frames 110-219, sent from 95) | - | - | 0.0000 | 4 |
| attempt-1 control ledge | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 42 | 0.0000 | 5 |
| attempt-1 control ledge | sam-3.1 | cached | track 'yellow pit' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'yellow pit' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | muse-spark-open-1026 | Baseten | name the robot and the object or hazard nearest to it | 1500 (128) | 446 | 0.0036 | 23 |
| attempt-1 control ledge | sam-3.1 | cached | track 'gray block' (frames 110-219, sent from 95) | - | - | 0.0000 | 8 |
| attempt-1 control ledge | sam-3.1 | cached | track 'gray block' (frames 0-109, sent from 0) | - | - | 0.0000 | 13 |
| attempt-1 control low_cube | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 60 | 0.0000 | 3 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'floor edge' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'floor edge' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 1 |
| attempt-1 control low_cube | muse-spark-open-1026 | Baseten | name the robot and the object or hazard nearest to it | 1500 | 808 | 0.0053 | 6 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'gray pillar' (frames 0-109, sent from 0) | - | - | 0.0220 | 25 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'gray pillar' (frames 110-219, sent from 95) | - | - | 0.0250 | 34 |
| incident | muse-wonder-1.0 | Meta Model API | warm the prompt cache (instructions + code) | 30279 | 16 | 0.1214 | 2 |
| attempt-1 | muse-spark-1.3-contributor | Muse Code (muse serve, sandboxed) -> Meta Model API | fix attempt 1 | 174504 (127059) | 1150 | 0.0052 | 37 |

Total $0.502. Every call is in `models.json`; Muse Code's cost is the host's own estimate.

## Guardrails

- the person decided: Fix it? yes (attempt 1, 8 s); Keep the fix? yes (attempt 1, 13 s)
- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`), approval mode `promptUnmatched`; edits are approved only when every path is inside the target.
- approval requests that reached BlinkFlow: 0 (in-workspace reads and edits are allowed by the host's own rules and never ask).
- every tool call was audited after each turn (file paths, paths named in shell commands); an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.
- the simulator's contact log and the twin's record of falls are not read by BlinkFlow; the scorers (tools/live_check.py, tools/bug_suite.py) do that.
