# BlinkFlow: white robot touches the purple box

**Fixed and verified in attempt 1 of 1.** Seen -> fixed and verified: **387 s** of machine time (the control in every other scene included; the person took 3.3 s to answer "Fix it?", not counted; 362 s in all with the answers).

## What was seen

Snapshot `../window/snapshot.json` (live run, wall clock). Named by glimmer: robot = *white robot*, object = *purple box*. First contact (base reading) at frame 133, t = 10.869 s after the brain starts, 2026-10-31T23:54:47.076+00:00.

![incident](../window/evidence/evidence.png)

## Cause (Muse Wonder)

`brain.toml`, `obstacle.side_memory_seconds`, lines 29-29: The time for remembering wall returns near the robot's side is set to zero, so side hazards are never retained once they leave the current central view.

In plain words: The box was beside the robot rather than squarely ahead, so as the robot drew level with it the box slipped out of the sensor's central view and the way ahead looked clear. Because remembering nearby side obstacles was switched off, the robot forgot the close obstacle it had seen at its side and kept walking straight until it touched the box.

Confidence 0.78; grounded (the file, its lines and function real; key frames and log ticks cited that exist): yes. Full diagnosis: `../window/evidence/diagnosis.md`.

## The fix

Muse Code: I set `obstacle.side_memory_seconds` in brain.toml from 0.0 back to the built-in 3.0. With zero the robot forgot the close side wall returns as soon as the box left the central view, so it kept walking forward into it.

1 file changed, 1 insertion(+), 1 deletion(-). Committed in the target as `93f3f41` (base `b2fe90a`).

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
| before (base commit) | **yes** | 11.455 | 10.650 | 1 | 3.26 |
| attempt 1 (kept) | **no** | - | - | 106 | 2.89 |

![before](before/evidence/evidence.png)

![after](attempt-1/evidence/evidence.png)

## Control: the same brain in every other scene

Replayed in the twin, each scene's shot followed by SAM 3.1 (every 3rd frame) with the names Glimmer gave it; clean = no contact and no fall, from pixels only.

| scene | named | clean | why |
|---|---|---|---|
| low_cube | white robot / brown step | yes | no contact, no fall |
| ledge | white robot / gray block | yes | no contact, no fall; closest gap 0 px |
| corner | white robot / red barrier | yes | no contact, no fall; closest gap 50 px |
| doorway | white robot / white rectangle | yes | no contact, no fall; closest gap 36 px |

## Attempts

### Attempt 1: kept

- diagnosis used: `../window/evidence/diagnosis.md` (cause `brain.toml::[obstacle] side_memory_seconds`)
- Muse Code: completed, 42 s, 1 file changed, 1 insertion(+), 1 deletion(-); files: brain.toml
- its note: I set `obstacle.side_memory_seconds` in brain.toml from 0.0 back to the built-in 3.0. With zero the robot forgot the close side wall returns as soon as the box left the central view, so it kept walking forward into it.
- control: low_cube clean; ledge clean; corner clean; doorway clean
- replay: no contact; closest gap 106 px at t = 12.93 s

## Time

Stages marked background run beside the others, so the column does not add up to the total.

| stage | from (s) | s |
|---|---|---|
| Glimmer loaded and kept warm (background) | 0 | 0 |
| Muse Wonder's prompt cache: instructions + code (background) | 0 | 3 |
| replay before any change: twin render (background) | 0 | 31 |
| understand (Glimmer key frames, Muse Wonder) | 3 | 74 |
| replay before any change: SAM 3.1 + verdict (background) | 31 | 19 |
| attempt 1: the person decides to fix | 77 | 3 |
| wait for the replay before any change | 80 | 0 |
| attempt 1: Muse Code edits the target | 80 | 42 |
| attempt 1: replay and look again | 122 | 37 |
| attempt 1: control, every other scene (pixels) | 158 | 200 |
| attempt 1: the person decides to keep | 358 | 4 |
| **total** | 0 | **362** |

The incident's evidence and first diagnosis were made before the loop (the voice or watcher step); their time is not counted above.

## Models

| stage | model | where | purpose | input tokens (cached) | output tokens | cost $ | s |
|---|---|---|---|---|---|---|---|
| incident | muse-voice-transcribe-1.0 | Meta Model API | what the person said (push-to-talk) | - | - | 0.0002 | 2 |
| incident | muse-glimmer | local | when it happened and what it touched, from the person's words | 240 | 28 | 0.0000 | 1 |
| incident | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1529 | 42 | 0.0000 | 2 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 0-74, sent from 0) | - | - | 0.0150 | 7 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 0-74, sent from 0) | - | - | 0.0150 | 8 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 151-225, sent from 136) | - | - | 0.0180 | 9 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 151-225, sent from 136) | - | - | 0.0180 | 11 |
| incident | sam-3.1 | Meta Model API | track 'white robot' (frames 75-150, sent from 60) | - | - | 0.0182 | 12 |
| incident | sam-3.1 | Meta Model API | track 'purple box' (frames 75-150, sent from 60) | - | - | 0.0182 | 13 |
| incident | muse-glimmer | local | describe key frame K2 | 591 | 43 | 0.0000 | 2 |
| incident | muse-glimmer | local | describe key frame K1 | 589 | 53 | 0.0000 | 4 |
| incident | muse-glimmer | local | describe key frame K4 | 586 | 40 | 0.0000 | 6 |
| incident | muse-glimmer | local | describe key frame K3 | 587 | 49 | 0.0000 | 8 |
| incident | muse-wonder-1.0 | Meta Model API | diagnose (evidence, run 1) | 41158 (30310) | 7708 | 0.2036 | 63 |
| before | sam-3.1 | cached | track 'white robot' (frames 662-755, sent from 647) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 94-188, sent from 79) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 189-283, sent from 174) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 567-661, sent from 552) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 0-93, sent from 0) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 284-377, sent from 269) | - | - | 0.0000 | 8 |
| before | sam-3.1 | cached | track 'white robot' (frames 472-566, sent from 457) | - | - | 0.0000 | 12 |
| before | sam-3.1 | cached | track 'purple box' (frames 0-93, sent from 0) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 284-377, sent from 269) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 94-188, sent from 79) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 472-566, sent from 457) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 189-283, sent from 174) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 662-755, sent from 647) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'white robot' (frames 378-471, sent from 363) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 378-471, sent from 363) | - | - | 0.0000 | 13 |
| before | sam-3.1 | cached | track 'purple box' (frames 567-661, sent from 552) | - | - | 0.0000 | 13 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 0-93, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 189-283, sent from 174) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 94-188, sent from 79) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 662-755, sent from 647) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 284-377, sent from 269) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 567-661, sent from 552) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 378-471, sent from 363) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 472-566, sent from 457) | - | - | 0.0000 | 1 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 189-283, sent from 174) | - | - | 0.0000 | 3 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 0-93, sent from 0) | - | - | 0.0000 | 3 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 567-661, sent from 552) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 378-471, sent from 363) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 284-377, sent from 269) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 472-566, sent from 457) | - | - | 0.0000 | 6 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 94-188, sent from 79) | - | - | 0.0000 | 6 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 662-755, sent from 647) | - | - | 0.0000 | 6 |
| attempt-1 control corner | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 53 | 0.0000 | 3 |
| attempt-1 control corner | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control corner | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 1 |
| attempt-1 control corner | sam-3.1 | cached | track 'red barrier' (frames 110-219, sent from 95) | - | - | 0.0000 | 3 |
| attempt-1 control corner | sam-3.1 | cached | track 'red barrier' (frames 0-109, sent from 0) | - | - | 0.0000 | 4 |
| attempt-1 control doorway | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 58 | 0.0000 | 3 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white rectangle' (frames 110-219, sent from 95) | - | - | 0.0000 | 2 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 2 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white rectangle' (frames 0-109, sent from 0) | - | - | 0.0000 | 2 |
| attempt-1 control doorway | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 2 |
| attempt-1 control ledge | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 42 | 0.0000 | 4 |
| attempt-1 control ledge | sam-3.1 | cached | track 'yellow pit' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'yellow pit' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control ledge | muse-spark-open-1026 | Baseten | name the robot and the object or hazard nearest to it | 1500 | 715 | 0.0049 | 6 |
| attempt-1 control ledge | sam-3.1 | cached | track 'gray block' (frames 110-219, sent from 95) | - | - | 0.0000 | 6 |
| attempt-1 control ledge | sam-3.1 | cached | track 'gray block' (frames 0-109, sent from 0) | - | - | 0.0000 | 10 |
| attempt-1 control low_cube | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1411 | 56 | 0.0000 | 2 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'floor edge' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'floor edge' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'white robot' (frames 0-109, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | sam-3.1 | cached | track 'white robot' (frames 110-219, sent from 95) | - | - | 0.0000 | 0 |
| attempt-1 control low_cube | muse-spark-open-1026 | Baseten | name the robot and the object or hazard nearest to it | 1500 | 1239 | 0.0071 | 8 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'brown step' (frames 0-109, sent from 0) | - | - | 0.0220 | 5 |
| attempt-1 control low_cube | sam-3.1 | Meta Model API | track 'brown step' (frames 110-219, sent from 95) | - | - | 0.0250 | 5 |
| incident | muse-wonder-1.0 | Meta Model API | warm the prompt cache (instructions + code) | 30279 (30182) | 16 | 0.0067 | 3 |
| attempt-1 | muse-spark-1.3-contributor | Muse Code (muse serve, default profile) -> Meta Model API | fix attempt 1 | 174896 (127187) | 1444 | 0.0053 | 42 |

Total $0.377. Every call is in `models.json`; Muse Code's cost is the host's own estimate, or, when the host reports none, priced from its token counts.

## Guardrails

- the person decided: Fix it? yes (attempt 1, 3 s); Keep the fix? yes (attempt 1, 4 s)
- control: every other twin scene replayed with the change and judged from pixels before anything was called fixed; a scene not clean undoes the change.
- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`; it does not stop a read or a write outside the target), approval mode `promptUnmatched`; edits are approved only when every path is inside the target.
- BlinkFlow's gate (muse-gate/, a PreToolUse hook: a filter on the paths each call names, not an isolation) checked every tool call before it ran: 6 calls, blocked: 0.
- approval requests that reached BlinkFlow: 0 (in-workspace reads and edits are allowed by the host's own rules and never ask).
- every tool call was audited after each turn (file paths, paths named in shell commands); an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.
- the simulator's contact log and the twin's record of falls are not read by BlinkFlow; the scorers (tools/live_check.py, tools/bug_suite.py) do that.
