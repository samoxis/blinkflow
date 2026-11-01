# The same loop on a 3-joint arm (Nov 1)

BlinkFlow's loop (see → diagnose → fix → prove) on a second robot: a hand-written MuJoCo arm. The robot is
[`blinkflow/arm/robot/`](../blinkflow/arm/robot). The scene (`scene.xml`, 43 lines, no assets) holds a
three-joint planar arm, a red block and a green target. The controller is `brain.py` (45 lines: waypoints,
inverse kinematics, joint PD at 200 Hz) plus `brain.toml`. The planted bug is `clearance = 0.0`, so the end
effector sweeps through the block. Like `~/duck-target` for the duck, `robot/` is the only folder Muse Code may
touch: the gate refuses any path outside it, including the harness beside it
([`blinkflow/arm/`](../blinkflow/arm): the twin and the adapters to SAM 3.1, the proof, Muse Wonder, the loop
and the re-check). A test runs the gate's hook on a write to `blinkflow/arm/run.py` and expects a denial
([`tests/test_arm_guards.py`](../tests/test_arm_guards.py)).

The run is in [`examples/arm/`](../examples/arm) ([before and after, side by side](../examples/arm/preview.html)).
It is a re-run of the first loop from the same inputs after the target was narrowed: the same planted
`brain.toml`, the same scene, the same box seed. The first run (in the arm's own repo, whole arm as target)
is kept at [`2a09938`](https://github.com/samoxis/blinkflow/tree/2a09938/examples/arm), with its calibration
probes.

## Measured

| Check | Result | Source |
|---|---|---|
| Determinism, planted brain | two replays, one record: `291bd97e…f732f08a` (the same as in the first run) | [`offline-report.json`](../examples/arm/offline-report.json), [`determinism.json`](../examples/arm/determinism.json) |
| Determinism, fixed brain, both rendered | two replays, one record `21c0f2ae…a928b011`, one video `6ccce3dd…64c2b2dd3f`; the record equals the one measured after the fix | [`determinism.json`](../examples/arm/determinism.json) |
| First contact, SAM 3.1 pixels / MuJoCo's own contact log | **2.035 s / 2.010 s**, 0.025 s apart (one episode in the log, never shown to the models) | [`alignment.json`](../examples/arm/alignment.json) |
| Muse Wonder's cause | `brain.toml:1–2`, `planner.clearance = 0.0`; `diagnose.check`: `grounded=true`, `bad_refs=[]` (K1, K4, ticks 0.000, 1.350 and 2.000 s) | [`diagnosis.json`](../examples/arm/before/evidence/diagnosis.json) |
| Muse Code | first attempt, one line in `robot/brain.toml`: `clearance = 0.0` → `0.12`; two tool calls (read, edit), gate and audit clean, 35.2 s | [`change.diff`](../examples/arm/attempt-1/change.diff), [`muse-code.json`](../examples/arm/attempt-1/muse-code.json) |
| Contacts, before → after | **1 → 0**, from pixels; the 200 Hz contact log agrees | [`result.json`](../examples/arm/result.json) |
| Closest gap after the fix | **3.6 px** (contact is ≤ 2 px) | [`attempt-1/verdict.json`](../examples/arm/attempt-1/verdict.json) |
| Controls: block moved / target moved | **2/2 clean**, closest **21.0 / 51.3 px**, both reach the target | [`control/`](../examples/arm/attempt-1/control) |
| Target reached | error below 0.001 mm (an ideal simulation), tolerance 20 mm | [`result.json`](../examples/arm/result.json) |
| Tracking coverage | 180/180 frames for both objects, before and after; 57/57 in each control | the four `evidence.json` |
| Offline re-check | passed: the four pixel measurements re-derived from SAM 3.1's saved replies, the citation check, the diff, and the physics replayed (same record hashes), with no key and the network blocked | `python3 -m blinkflow.arm.recheck examples/arm` |
| Cost of this loop | **$0.3007**: SAM 3.1 $0.1896 (8 replies, none cached), Muse Wonder $0.10756, Muse Code $0.00354 | [`models.json`](../examples/arm/models.json) |
| Spent on the arm, in total | **$0.68795**: the first run with its calibration ($0.38726) plus this re-run, of a $3 cap | [`models.json`](../examples/arm/models.json) (`repo_spend_usd`) |

### Against the first run

Same inputs and same method, but not the same answers from the models. Nothing was tuned between the runs.

| | First run (2a09938) | Re-run (this example) |
|---|---|---|
| Muse Code's value | `clearance = 0.08` | `clearance = 0.12` |
| Muse Wonder's citations | K3, K4; ticks 1.350, 2.000 s | K1, K4; ticks 0.000, 1.350, 2.000 s |
| Closest gap, block moved | 20.0 px | 21.0 px |
| Loop cost | $0.29366 | $0.3007 |

Unchanged: the incident replay (record `291bd97e…`), the first contact (2.035 s and 2.010 s), the cause
(`brain.toml:1–2`), 1 → 0, 3.6 px after the fix, 51.3 px with the target moved, 2/2 controls, a fix on the
first attempt. The closest gap after the fix stays 3.6 px with either value: it is reached at the end of the
move, as the arm comes down to the target beside the block, not in the lift.

## Limits

- **SAM 3.1 did not find the arm from text.** "robot arm" gave masks in 0 of 180 frames, and so did every other
  phrase tried ("robotic arm", "orange robot"…; the probes are in [the first run's `calibration/`](https://github.com/samoxis/blinkflow/tree/2a09938/examples/arm/calibration)). The arm is
  tracked from a box marked once on the first frame, with Meta's documented box prompt (`<0f>1<|box;…|>`,
  [`blinkflow/arm/see.py`](../blinkflow/arm/see.py)). The box is identical before, after and in both controls,
  and is never taken from a contact frame or from the simulator. The obstacle is text-prompted ("red block").
  This shows visually seeded tracking, not text-only detection of the arm.
- An ideal planar simulation: gravity off, no actuator latency or sensor noise, one fixed side camera, one
  scene family (the incident and two small variations), one planted parameter bug. 3.6 px is a modest
  margin; the 9.5 fps control videos alone cannot rule out a touch between frames (the 200 Hz log is clean).
- `scene.xml` is inside the target, so the gate would let Muse Code edit the world. The loop accepts only a
  change to `brain.toml` that leaves everything but a positive clearance as it was; anything else is rolled
  back.
- The sentence is fixed text; no voice, no live window, no physical robot.
- Built with Codex (GPT-6.1 Sol) on Nov 1, in a separate repo, from a written brief (`AGENTS.md` there),
  then moved here as `blinkflow/arm/`, as declared in `DEVLOG.md`. The re-run was made here.

## Re-check it

```bash
pip install -r requirements.txt
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -m blinkflow.arm.recheck examples/arm
```

How to run it, and the interpreter it was made with: [`docs/RUNNING.md`](../docs/RUNNING.md#the-arm).
