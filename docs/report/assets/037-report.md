# BlinkFlow: white robot touches the purple box

**Fixed and verified in attempt 1 of 1.** Seen -> fixed and verified: **368 s** of machine time (the control in every other scene included).

## What was seen

Snapshot `../window/snapshot.json` (live run, wall clock). Named by glimmer: robot = *white robot*, object = *purple box*. First contact (base reading) at frame 132, t = 10.903 s after the brain starts, 2026-10-31T23:54:47.109+00:00.

![incident](../window/evidence/evidence.png)

## Cause (Muse Wonder)

`brain.toml`, `[obstacle] side_memory_seconds`, lines 29-29: side_memory_seconds is set to 0.0, disabling the hazard map's SIDE kind (hazards.py HazardMap._enabled requires side_memory_seconds > 0). Near-body wall returns in the peripheral sensor column are therefore never remembered or merged into the view ahead, so Forward never starts an avoidance episode for an object alongside the body.

In plain words: The purple box approached along the robot's flank rather than head-on, so it showed up only at the edge of the robot's depth view while the way straight ahead stayed clear. The robot therefore kept walking its straight line and clipped the box with its side. The safeguard meant to remember things seen close alongside the body was turned off in the settings, so those edge sightings were thrown away instead of making the robot steer away or stop.

Confidence 0.72; grounded (the file, its lines and function real; key frames and log ticks cited that exist): yes. Full diagnosis: `../window/evidence/diagnosis.md`.

## The fix

Muse Code: Changed `side_memory_seconds` in [brain.toml](~/duck-target/brain.toml) from 0.0 to 3.0, restoring the built-in default. This re-enables SIDE hazard memory so near-body wall returns seen only in the peripheral column are retained and fed into avoidance.

1 file changed, 1 insertion(+), 1 deletion(-). Committed in the target as `64e8f71` (base `b2fe90a`).

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
| before (base commit) | **yes** | 11.455 | 10.650 | 1 | 3.11 |
| attempt 1 (kept) | **no** | - | - | 107 | 2.73 |

![before](before/evidence/evidence.png)

![after](attempt-1/evidence/evidence.png)

## Control: the same brain in every other scene

Replayed in the twin, each scene's shot followed by SAM 3.1 (every 3rd frame): the robot and the scene's own obstacle as the scene defines it (named by Glimmer only if that is found in no frame); clean = the obstacle seen, no contact and no fall, from pixels only.

| scene | named | clean | why |
|---|---|---|---|
| low_cube | white robot / orange cube | yes | no contact, no fall; closest gap 139 px |
| ledge | white robot / yellow floor | yes | no contact, no fall; closest gap 157 px |
| corner | white robot / red barrier | yes | no contact, no fall; closest gap 50 px |
| doorway | white robot / blue block | yes | no contact, no fall; closest gap 14 px |

## Attempts

### Attempt 1: kept

- diagnosis used: `../window/evidence/diagnosis.md` (cause `brain.toml::[obstacle] side_memory_seconds`)
- Muse Code: completed, 38 s, 1 file changed, 1 insertion(+), 1 deletion(-); files: brain.toml
- its note: Changed `side_memory_seconds` in [brain.toml](~/duck-target/brain.toml) from 0.0 to 3.0, restoring the built-in default. This re-enables SIDE hazard memory so near-body wall returns seen only in the peripheral column are retained and fed into avoidance.
- control: low_cube clean; ledge clean; corner clean; doorway clean
- replay: no contact; closest gap 107 px at t = 12.89 s

## Time

Stages marked background run beside the others, so the column does not add up to the total.

| stage | from (s) | s |
|---|---|---|
| Glimmer loaded and kept warm (background) | 0 | 0 |
| Muse Wonder's prompt cache: instructions + code (background) | 0 | 3 |
| replay before any change: twin render (background) | 0 | 31 |
| understand (Glimmer key frames, Muse Wonder) | 3 | 71 |
| replay before any change: SAM 3.1 + verdict (background) | 31 | 25 |
| wait for the replay before any change | 74 | 0 |
| attempt 1: Muse Code edits the target | 74 | 38 |
| attempt 1: replay and look again | 112 | 36 |
| attempt 1: control, every other scene (pixels) | 148 | 192 |
| **total** | 0 | **340** |

The incident's evidence and first diagnosis were made before the loop (the voice or watcher step); their time is not counted above.

## Models

| stage | model | where | purpose | input tokens (cached) | output tokens | cost $ | s |
|---|---|---|---|---|---|---|---|
| incident | muse-voice-transcribe-1.0 | Meta Model API | what the person said (push-to-talk) | - | - | 0.0002 | 3 |
| incident | muse-glimmer | local | when it happened and what it touched, from the person's words | 240 | 28 | 0.0000 | 1 |
| incident | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1529 | 42 | 0.0000 | 2 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 0-98, sent from 0) | - | - | 0.0198 | 9 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 0-98, sent from 0) | - | - | 0.0198 | 11 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 99-197, sent from 84) | - | - | 0.0228 | 12 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 99-197, sent from 84) | - | - | 0.0228 | 13 |
| incident | muse-glimmer | local | describe key frame K1 | 589 | 51 | 0.0000 | 2 |
| incident | muse-glimmer | local | describe key frame K2 | 591 | 46 | 0.0000 | 4 |
| incident | muse-glimmer | local | describe key frame K3 | 587 | 47 | 0.0000 | 5 |
| incident | muse-glimmer | local | describe key frame K4 | 586 | 52 | 0.0000 | 7 |
| incident | muse-wonder-1.0 | Meta Model API | diagnose (evidence, run 1) | 41217 (30182) | 6954 | 0.1893 | 61 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 182-272, sent from 167) | - | - | 0.0212 | 4 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 0-90, sent from 0) | - | - | 0.0182 | 5 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 637-727, sent from 622) | - | - | 0.0212 | 5 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 546-636, sent from 531) | - | - | 0.0212 | 5 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 91-181, sent from 76) | - | - | 0.0212 | 5 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 91-181, sent from 76) | - | - | 0.0212 | 13 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 0-90, sent from 0) | - | - | 0.0182 | 14 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 273-363, sent from 258) | - | - | 0.0212 | 15 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 182-272, sent from 167) | - | - | 0.0212 | 15 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 455-545, sent from 440) | - | - | 0.0212 | 15 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 273-363, sent from 258) | - | - | 0.0212 | 16 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 637-727, sent from 622) | - | - | 0.0212 | 16 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 364-454, sent from 349) | - | - | 0.0212 | 16 |
| before | sam-3.1 | Meta Model API | track 'white robot' (frames 364-454, sent from 349) | - | - | 0.0212 | 16 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 455-545, sent from 440) | - | - | 0.0212 | 16 |
| before | sam-3.1 | Meta Model API | track 'purple box' (frames 546-636, sent from 531) | - | - | 0.0212 | 16 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 0-90, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 91-181, sent from 76) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 182-272, sent from 167) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 0-90, sent from 0) | - | - | 0.0000 | 1 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 182-272, sent from 167) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 91-181, sent from 76) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 546-636, sent from 531) | - | - | 0.0212 | 4 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 273-363, sent from 258) | - | - | 0.0212 | 5 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 637-727, sent from 622) | - | - | 0.0212 | 5 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 364-454, sent from 349) | - | - | 0.0212 | 6 |
| attempt-1 | sam-3.1 | Meta Model API | track 'white robot' (frames 455-545, sent from 440) | - | - | 0.0212 | 7 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 273-363, sent from 258) | - | - | 0.0212 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 637-727, sent from 622) | - | - | 0.0212 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 546-636, sent from 531) | - | - | 0.0212 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 455-545, sent from 440) | - | - | 0.0212 | 8 |
| attempt-1 | sam-3.1 | Meta Model API | track 'purple box' (frames 364-454, sent from 349) | - | - | 0.0212 | 9 |
| attempt-1 control corner | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control corner | sam-3.1 | cached | track 'red barrier' (frames 0-109, sent from 0) | - | - | 0.0000 | 2 |
| attempt-1 control corner | sam-3.1 | cached | track 'red barrier' (frames 110-219, sent from 95) | - | - | 0.0000 | 3 |
| attempt-1 control corner | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 3 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 1 |
| attempt-1 control doorway | sam-3.1 | cached | track 'blue block' (frames 0-109, sent from 0) | - | - | 0.0000 | 2 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 3 |
| attempt-1 control doorway | sam-3.1 | cached | track 'blue block' (frames 110-219, sent from 95) | - | - | 0.0000 | 4 |
| attempt-1 control ledge | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'yellow floor' (frames 110-219, sent from 95) | - | - | 0.0000 | 4 |
| attempt-1 control ledge | sam-3.1 | cached | track 'yellow floor' (frames 0-109, sent from 0) | - | - | 0.0000 | 8 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'orange cube' (frames 0-109, sent from 0) | - | - | 0.0000 | 1 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 4 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 7 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'orange cube' (frames 110-219, sent from 95) | - | - | 0.0000 | 7 |
| incident | muse-wonder-1.0 | Meta Model API | warm the prompt cache (instructions + code) | 30279 | 16 | 0.1214 | 3 |
| attempt-1 | muse-spark-1.3-contributor | Muse Code (muse serve, default profile) -> Meta Model API | fix attempt 1 | 161362 (118483) | 1135 | 0.0047 | 38 |

Total $0.946. Every call is in `models.json`; Muse Code's cost is the host's own estimate, or, when the host reports none, priced from its token counts.

## Guardrails

- run with --auto: no one was asked before Muse Code wrote or before the fix was kept.
- control: every other twin scene replayed with the change and judged from pixels before anything was called fixed; a scene not clean undoes the change.
- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`; it does not stop a read or a write outside the target), approval mode `promptUnmatched`; edits are approved only when every path is inside the target.
- BlinkFlow's gate (muse-gate/, a PreToolUse hook: a filter on the paths each call names, not an isolation) checked every tool call before it ran: 5 calls, blocked: 0.
- approval requests that reached BlinkFlow: 0 (in-workspace reads and edits are allowed by the host's own rules and never ask).
- every tool call was audited after each turn (file paths, paths named in shell commands); an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.
- the simulator's contact log and the twin's record of falls are not read by BlinkFlow; the scorers (tools/live_check.py, tools/bug_suite.py) do that.
