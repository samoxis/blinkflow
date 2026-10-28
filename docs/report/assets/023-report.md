# BlinkFlow: white robot touches the purple box

**Fixed and verified in attempt 1 of 1.** Seen -> fixed and verified: **191 s** of machine time.

## What was seen

Snapshot `~/blinkflow-runs/quick/cache-2/snapshot.json` (live run, wall clock). Named by glimmer: robot = *white robot*, object = *purple box*. First contact (base reading) at frame 407, t = 12.022 s after the brain starts, 2026-10-26T17:36:22.518+00:00.

![incident](incident/evidence.png)

## Cause (Muse Wonder)

`brain.toml`, `configuration value`, lines 29-29: side_memory_seconds is set to 0.0, disabling the side-hazard memory.

In plain words: The robot had seen the tall box on its side while it was still ahead, but a configuration choice switched off the short memory meant for nearby side objects. Once the robot drew alongside it, the box was no longer in the forward view, so the robot believed the way was clear and kept walking until its side clipped the box.

Confidence 0.84; grounded in key frames and log ticks: yes. Full diagnosis: `incident/diagnosis.md`.

## The fix

Muse Code: Changed `brain.toml` to set `side_memory_seconds` from 0.0 to 3.0, matching the code default, so wall returns near the body are remembered while the robot passes them. Added `tests/test_side_memory.py` as a regression check that the deployed config keeps side-hazard memory enabled.

2 files changed, 18 insertions(+), 1 deletion(-). Committed in the target as `c919c4d` (base `b2fe90a`).

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
diff --git a/tests/test_side_memory.py b/tests/test_side_memory.py
new file mode 100644
index 0000000..793ba0b
--- /dev/null
+++ b/tests/test_side_memory.py
@@ -0,0 +1,17 @@
+"""Regression check: the deployed config must not silently disable side-hazard memory."""
+
+from pathlib import Path
+
+from microduck_brain.config import load
+from microduck_brain.hazards import SIDE, HazardMap
+from microduck_brain.brain import Stats
+
+
+def test_deployed_config_keeps_side_memory_enabled():
+    brain_toml = Path(__file__).resolve().parents[1] / "brain.toml"
+    cfg = load(brain_toml)
+    assert cfg.obstacle.side_memory_seconds > 0, (
+        f"brain.toml disables side-hazard memory "
+        f"(side_memory_seconds={cfg.obstacle.side_memory_seconds!r})"
+    )
+    assert HazardMap(cfg, Stats())._enabled(SIDE)
```

## Proof: the same scenario replayed in the twin, before and after

The verdict comes from SAM 3.1 masks on the rendered incident shot, following the incident's robot and purple box. Contact = masks touching with the robot's feet at the object's base (the base reading), or, when the feet never get there, with the robot within reach of the base (body reading: another part of it, such as its head).

| replay | contact | first contact (s) | masks touch on screen (s) | closest gap (px) | walked (m) |
|---|---|---|---|---|---|
| before (base commit) | **yes** | 11.455 | 10.650 | 0 | 2.72 |
| attempt 1 (kept) | **no** | - | - | 106 | 2.34 |

![before](before/evidence/evidence.png)

![after](attempt-1/evidence/evidence.png)

## Attempts

### Attempt 1: kept

- diagnosis used: `incident/diagnosis.md` (cause `brain.toml::[obstacle] side_memory_seconds`)
- Muse Code: completed, 72 s, 2 files changed, 18 insertions(+), 1 deletion(-); files: brain.toml, tests/test_side_memory.py
- its note: Changed `brain.toml` to set `side_memory_seconds` from 0.0 to 3.0, matching the code default, so wall returns near the body are remembered while the robot passes them. Added `tests/test_side_memory.py` as a regression check that the deployed config keeps side-hazard memory enabled.
- replay: no contact; closest gap 106 px at t = 12.89 s

## Time

Stages marked background run beside the others, so the column does not add up to the total.

| stage | from (s) | s |
|---|---|---|
| Glimmer loaded and kept warm (background) | 0 | 0 |
| Muse Wonder's prompt cache: instructions + code (background) | 0 | 5 |
| see the incident (Glimmer names, SAM 3.1 masks) | 0 | 16 |
| replay before any change: twin render (background) | 0 | 33 |
| understand (Glimmer key frames, Muse Wonder) | 16 | 73 |
| replay before any change: SAM 3.1 + verdict (background) | 33 | 11 |
| wait for the replay before any change | 89 | 0 |
| attempt 1: Muse Code edits the target | 89 | 72 |
| attempt 1: replay and look again | 160 | 31 |
| **total** | 0 | **191** |

## Models

| stage | model | where | purpose | input tokens (cached) | output tokens | cost $ | s |
|---|---|---|---|---|---|---|---|
| incident | muse-glimmer | local | name the robot and the object or hazard nearest to it | 1480 | 47 | 0.0000 | 2 |
| incident | sam-3.1 | cached | track 'white robot' (frames 0-71, sent from 0) | - | - | 0.0000 | 4 |
| incident | sam-3.1 | cached | track 'purple box' (frames 0-71, sent from 0) | - | - | 0.0000 | 5 |
| incident | sam-3.1 | cached | track 'purple box' (frames 72-144, sent from 57) | - | - | 0.0000 | 6 |
| incident | sam-3.1 | cached | track 'white robot' (frames 72-144, sent from 57) | - | - | 0.0000 | 6 |
| incident | muse-glimmer | local | describe key frame K1 | 589 | 44 | 0.0000 | 2 |
| incident | muse-glimmer | local | describe key frame K2 | 591 | 44 | 0.0000 | 3 |
| incident | muse-glimmer | local | describe key frame K3 | 587 | 45 | 0.0000 | 4 |
| incident | muse-glimmer | local | describe key frame K4 | 586 | 44 | 0.0000 | 6 |
| incident | muse-wonder-1.0 | Meta Model API | diagnose (evidence, run 1) | 40826 (30182) | 6063 | 0.1699 | 64 |
| before | sam-3.1 | cached | track 'white robot' (frames 94-187, sent from 79) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 188-281, sent from 173) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 0-93, sent from 0) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 564-657, sent from 549) | - | - | 0.0000 | 0 |
| before | sam-3.1 | cached | track 'white robot' (frames 470-563, sent from 455) | - | - | 0.0000 | 1 |
| before | sam-3.1 | cached | track 'white robot' (frames 282-375, sent from 267) | - | - | 0.0000 | 1 |
| before | sam-3.1 | cached | track 'purple box' (frames 0-93, sent from 0) | - | - | 0.0000 | 2 |
| before | sam-3.1 | cached | track 'purple box' (frames 94-187, sent from 79) | - | - | 0.0000 | 3 |
| before | sam-3.1 | cached | track 'white robot' (frames 376-469, sent from 361) | - | - | 0.0000 | 4 |
| before | sam-3.1 | cached | track 'purple box' (frames 282-375, sent from 267) | - | - | 0.0000 | 4 |
| before | sam-3.1 | cached | track 'purple box' (frames 188-281, sent from 173) | - | - | 0.0000 | 5 |
| before | sam-3.1 | cached | track 'purple box' (frames 470-563, sent from 455) | - | - | 0.0000 | 5 |
| before | sam-3.1 | cached | track 'purple box' (frames 376-469, sent from 361) | - | - | 0.0000 | 6 |
| before | sam-3.1 | cached | track 'purple box' (frames 564-657, sent from 549) | - | - | 0.0000 | 6 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 0-93, sent from 0) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 282-375, sent from 267) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 188-281, sent from 173) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 94-187, sent from 79) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 564-657, sent from 549) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 470-563, sent from 455) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'white robot' (frames 376-469, sent from 361) | - | - | 0.0000 | 0 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 0-93, sent from 0) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 94-187, sent from 79) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 282-375, sent from 267) | - | - | 0.0000 | 2 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 470-563, sent from 455) | - | - | 0.0000 | 3 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 188-281, sent from 173) | - | - | 0.0000 | 4 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 376-469, sent from 361) | - | - | 0.0000 | 5 |
| attempt-1 | sam-3.1 | cached | track 'purple box' (frames 564-657, sent from 549) | - | - | 0.0000 | 5 |
| incident | muse-wonder-1.0 | Meta Model API | warm the prompt cache (instructions + code) | 30279 (30182) | 16 | 0.0067 | 5 |
| attempt-1 | muse-spark-1.3 | Muse Code (muse serve, sandboxed) -> Meta Model API | fix attempt 1 | 632461 (581949) | 3166 | 0.1639 | 71 |

Total $0.341. Every call is in `models.json`; Muse Code's cost is the host's own estimate.

## Guardrails

- run with --auto: no one was asked before Muse Code wrote or before the fix was kept.
- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`), approval mode `promptUnmatched`; edits are approved only when every path is inside the target.
- approval requests that reached BlinkFlow: 0 (in-workspace reads and edits are allowed by the host's own rules and never ask).
- every tool call was audited after each turn (file paths, paths named in shell commands); an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.
- the simulator's contact log and the twin's record of falls are not read by BlinkFlow; the scorers (tools/live_check.py, tools/bug_suite.py) do that.
