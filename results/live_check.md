# Live check: does the fix hold in the real simulator?

Oct 28. `tools/live_check.py` (scorer side, not part of the agent) runs the live scenario: simulator, Viser
window, capture, brain. It alternates the target without the fix and with BlinkFlow's fix, 5 runs each, 20 s of
brain per run. Contacts come from the simulator's own contact log, which BlinkFlow never reads. The live stack
runs on four wall clocks, so the same brain does not walk the same path twice (DEVLOG, Oct 26 17:41): hence
5 runs per side rather than one.

The two revisions, in `~/duck-target` (the target's own repo on the author's PC):

- before: `b2fe90a`, the target as built (`brain.toml:29  side_memory_seconds = 0.0`)
- after: `215f024` on branch `fix-demo`, the fix alone:

```diff
-side_memory_seconds = 0.0 # remember wall returns near the body for this long (s)
+side_memory_seconds = 3.0 # remember wall returns near the body for this long (s)
```

That `brain.toml` is byte-identical to the one Muse Code wrote in the packed example (blob `a2deec7` in both
diffs, `examples/purple-box/fix/fix.json`); Muse Code's added regression test is left out.

## The check (`live_check/20261028-075435.json`)

| target | runs | runs with contact | first contact (s after the brain starts) | body |
|---|---|---|---|---|
| before `b2fe90a` | 5 | **5/5** | 11.10, 11.63, 10.41, 11.61, 11.52 | jaw_soft, upper_leg_right, ankle_right |
| after `215f024` | 5 | **0/5** | - | - |

**5/5 before, 0/5 after.**

## An earlier pass, not counted (`live_check/20261028-074251.json`)

| target | runs | runs with contact | first contact (s after the brain starts) | body |
|---|---|---|---|---|
| before `b2fe90a` | 5 | 3/5 | 10.74, 11.57, 10.83 | jaw_soft, upper_leg_right |
| after `215f024` | 5 | 0/5 | - | - |

From 07:46 to 07:53 an offline re-measurement (SAM mask decoding on all 24 cores) ran on the same PC, over
runs 3 to 5 of this pass. The two "before" runs without contact are runs 3 and 5. The live simulator keeps wall
time, so this pass was repeated with nothing else running; it is kept here because it was run.

The snapshots and brain logs of each run are named in the JSON files (they stay on the author's PC; the JSON is
the record). The Oct 26 check (5/5 → 0/5) named revisions of an earlier build of the target that no longer
exist; it is in this file's git history.
