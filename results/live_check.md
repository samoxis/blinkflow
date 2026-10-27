# Live check: does the fix hold in the real simulator?

Oct 26. `tools/live_check.py` (scorer side, not part of the agent) runs the live scenario: simulator, Viser
window, capture, brain. It alternates the target without the fix (`5f280fd`, `side_memory_seconds = 0.0`) and with
BlinkFlow's fix (`ef8b69d`, set to 3.0 by Muse Code), 5 runs each. Contacts come from the simulator's own
contact log, which BlinkFlow never reads. The live stack runs on four wall clocks, so the same brain does not
walk the same path twice (DEVLOG, Oct 26 17:41): hence 5 runs per side rather than one.

## 12 s of brain per run (`live_check/20261026-195624.json`)

| target | runs | runs with contact | first contact (s after the brain starts) | body |
|---|---|---|---|---|
| before `5f280fd` | 5 | **4/5** | 11.58, 10.60, 11.29, 11.19 | ankle_right, jaw_soft, upper_leg_right |
| after `ef8b69d` | 5 | **0/5** | - | - |

## 20 s of brain per run (`live_check/20261026-200235.json`)

| target | runs | runs with contact | first contact (s after the brain starts) | body |
|---|---|---|---|---|
| before `5f280fd` | 5 | **5/5** | 12.27, 16.87, 11.48, 11.71, 11.62 | upper_leg_right |
| after `ef8b69d` | 5 | **0/5** | - | - |

The 12 s runs are too short to judge: one run without the fix had not reached the box by 12 s (the first
contacts in the 20 s set range up to 16.87 s). With 20 s: **5/5 before, 0/5 after.** The snapshots and brain logs
of each run are named in the JSON files (they stay on the author's PC; the JSON is the record).
