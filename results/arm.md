# The same loop on a 3-joint arm (Nov 1)

BlinkFlow's loop (see → diagnose → fix → prove) on a second robot: a hand-written MuJoCo arm. The world is
[`blinkflow/arm/world/`](../blinkflow/arm/world): the scene (`scene.xml`, 43 lines, no assets: a three-joint
planar arm, a red block, a green target) and the names SAM 3.1 is given. The robot's controller is
[`blinkflow/arm/robot/`](../blinkflow/arm/robot): `brain.py` (45 lines: waypoints, inverse kinematics, joint PD
at 200 Hz) and `brain.toml`. The planted bug is `clearance = 0.0`, so the end effector sweeps through the block.
Like `~/duck-target` for the duck, `robot/` is the only folder Muse Code may touch: the gate refuses any path
outside it, the world and the harness included ([`blinkflow/arm/`](../blinkflow/arm): the twin and the adapters
to SAM 3.1, the proof, Muse Wonder, the loop and the re-check). A test runs the gate's hook and expects a denial
for `world/scene.xml` and `run.py` and an allow for `brain.py` and `brain.toml`
([`tests/test_arm_guards.py`](../tests/test_arm_guards.py)).

The fix is accepted as the duck's is, by what the camera sees and nothing else: the incident replayed shows no
contact, the end effector reaches the target within 20 mm, and both control scenes are clean, all measured from
SAM 3.1's masks; otherwise the change is rolled back and Muse Code tries again (at most three attempts). No rule
reads what the change says. The only other checks are about where and how: every changed file is inside
`robot/`, the SDK ran with shell disabled, and its tool calls pass the gate's audit.

The run is in [`examples/arm/`](../examples/arm) ([before and after, side by side](../examples/arm/preview.html)).
It is the third run of the loop, from the same inputs (the planted `brain.toml`, the same scene, the same box
seed), after the world was moved out of the target and the content rule was removed. The earlier runs are kept:
the first (whole arm as target, with the calibration probes) at
[`2a09938`](https://github.com/samoxis/blinkflow/tree/2a09938/examples/arm), the second (`robot/` with the scene in
it, and a rule that accepted only a positive clearance) at
[`e57473c`](https://github.com/samoxis/blinkflow/tree/e57473c/examples/arm).

## Measured

| Check | Result | Source |
|---|---|---|
| Determinism, planted brain | two replays, one record: `291bd97e…f732f08a` (the same as in the first run) | [`offline-report.json`](../examples/arm/offline-report.json), [`determinism.json`](../examples/arm/determinism.json) |
| Determinism, fixed brain, both rendered | two replays, one record `ea5f8535…ee8`, one video `ced05136…b5e3`; the record equals the one measured after the fix | [`determinism.json`](../examples/arm/determinism.json) |
| First contact, SAM 3.1 pixels / MuJoCo's own contact log | **2.035 s / 2.010 s**, 0.025 s apart (one episode in the log, never shown to the models) | [`alignment.json`](../examples/arm/alignment.json) |
| Muse Wonder's cause | `brain.toml:1–2`, `planner.clearance = 0.0`; `diagnose.check`: `grounded=true`, `bad_refs=[]` (K4, tick 2.000 s) | [`diagnosis.json`](../examples/arm/before/evidence/diagnosis.json) |
| Muse Code | first attempt, one line in `robot/brain.toml`: `clearance = 0.0` → `0.15`; five tool calls (read `brain.toml`, read `brain.py`, list the workspace, edit, read back), gate and audit clean, 74.6 s | [`change.diff`](../examples/arm/attempt-1/change.diff), [`muse-code.json`](../examples/arm/attempt-1/muse-code.json) |
| Contacts, before → after | **1 → 0**, from pixels; the 200 Hz contact log agrees | [`result.json`](../examples/arm/result.json) |
| Closest gap after the fix | **3.6 px** (contact is ≤ 2 px) | [`attempt-1/verdict.json`](../examples/arm/attempt-1/verdict.json) |
| Controls: block moved / target moved | **2/2 clean**, closest **21.0 / 51.3 px**, both reach the target | [`control/`](../examples/arm/attempt-1/control) |
| Target reached | error below 0.001 mm (an ideal simulation), tolerance 20 mm | [`result.json`](../examples/arm/result.json) |
| Tracking coverage | 180/180 frames for both objects, before and after; 57/57 in each control | the four `evidence.json` |
| Offline re-check | passed: the four pixel measurements re-derived from SAM 3.1's saved replies, the citation check, the diff, and the physics replayed (same record hashes), with no key and the network blocked | `python3 -m blinkflow.arm.recheck examples/arm` |
| Cost of this loop | **$0.27414**: SAM 3.1 $0.1896 (8 replies, none cached), Muse Wonder $0.07976, Muse Code $0.00478 | [`models.json`](../examples/arm/models.json) |
| Spent on the arm, in total | **$1.30199**: the three clearance runs ($0.38726 for the first with its calibration, $0.3007, $0.27414) and the two below ($0.185188, $0.1547084), of a $3 cap | the three examples' `models.json` |

### Against the earlier runs

Same inputs and same method, but not the same answers from the models. Nothing was tuned between the runs.

| | First (2a09938) | Second (e57473c) | This run |
|---|---|---|---|
| What Muse Code may edit | the whole arm, harness included | `robot/` with the scene | `robot/`: `brain.py`, `brain.toml` |
| What the loop accepts | pixels + only a positive clearance | pixels + only a positive clearance | pixels only |
| Muse Code's change | `clearance = 0.08` | `clearance = 0.12` | `clearance = 0.15` |
| Muse Code's tool calls, time | 13, 107.8 s | 2, 35.2 s | 5 (also read `brain.py` and listed the files), 74.6 s |
| Muse Wonder's citations | K3, K4; ticks 1.350, 2.000 s | K1, K4; ticks 0.000, 1.350, 2.000 s | K4; tick 2.000 s |
| Closest gap, block moved | 20.0 px | 21.0 px | 21.0 px |
| Loop cost | $0.29366 | $0.3007 | $0.27414 |

Unchanged in all three: the incident replay (record `291bd97e…`), the first contact (2.035 s and 2.010 s), the
cause (`brain.toml:1–2`), 1 → 0, 3.6 px after the fix, 51.3 px with the target moved, 2/2 controls, a fix on the
first attempt. The closest gap after the fix stays 3.6 px with any of the three values: it is reached at the end
of the move, as the arm comes down to the target beside the block, not in the lift. With the content rule gone,
Muse Code still chose to change only the clearance; nothing made it.

## Three runs on the arm

Two more runs, made in the arm's own repo (at its commit `c335000`, before it was integrated
again), copied here unchanged: [`examples/arm-bug2/`](../examples/arm-bug2) and
[`examples/arm-voice/`](../examples/arm-voice). The same scene, camera, box seed, gains and timing in all three.

| Run | Bug | Input | Attempts | Result | Cost |
|---|---|---|---|---|---|
| [Clearance](../examples/arm) | `clearance = 0.0` | fixed text | 1 | fixed (`0.0` → `0.15` here; 0.08 in the first run), target reached, controls 2/2 | $0.27 (this run) |
| [Bug 2](../examples/arm-bug2/preview.html) | `lift = max(z0, z1) - clearance` in `brain.py`: a sign error, `clearance` stays 0.08 | fixed text | 1 | one-line logic fix in `brain.py` (`-` → `+`), target reached, controls 2/2 | $0.19 |
| [Voice](../examples/arm-voice/preview.html) | the first run's controller (`clearance = 0.0`) | Sorin's recorded sentence through Muse Voice Transcribe: a 13.6 s WAV, the sentence said twice; transcript saved | 1 | the same fix (`0.0` → `0.08`) and the same after-proof as the first run (2a09938): records, masks and verdicts identical | $0.15 |

Bug 2 is a different incident from the same scene: first contact 2.035 s on pixels, 2.015 s in MuJoCo's log
(two contact episodes). Muse Wonder named `Brain.waypoint`, `brain.py:30–35` (grounded, `bad_refs=[]`, K1–K4
cited); Muse Code read `brain.py` and edited one line in 28.7 s; closest gap after 3.6 px, controls 20.0 / 51.3 px.
In the voice run Muse Voice Transcribe returned both sentences ("a couple of seconds ago the arm hit the red
block", twice; $0.00068), Muse Glimmer read "2 seconds ago, contact, red block", and the clip was cut from the
recording around that moment (151 frames, 0–5 s); SAM 3.1 found the contact at 2.035 s in it, and Muse Wonder
named `brain.toml:1–2` with the transcript in its input.

`python3 -m blinkflow.arm.recheck` re-checks both offline, with their bytes as published: each was made in the
arm repo's flat layout (the robot was `arm/brain.py`, `arm/brain.toml`), so their diffs and file lists name
`arm/`, and the re-check reads that as the robot. For the voice run it also checks the transcript against the
saved Muse Voice reply, the delay Glimmer read, the press-minus-delay moment, the window, the cut log (a prefix
of the full one) and the WAV's length.

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
- The prompts still name the robot and the incident ("hit a red block on its way to a green target"), as the
  duck's do; the controller's log, sent to Muse Wonder, has a clearance column because the controller logs it.
- The sentence is fixed text in the clearance runs and bug 2. The voice run used a supplied key-press time (4 s)
  and derived the incident moment at 2 s from it and the spoken delay: a replayed press on a recorded sentence,
  not live capture. The box seed is still needed for the arm in all three. No physical robot.
- Bug 2 and the voice run were made with the arm repo's loop, before acceptance here became pixels only: its
  prompt named the one file to edit, and it accepted only that file (a logic fix of at most two lines with the
  config unchanged, or only a positive clearance), with a diagnosis naming the planted file. Both passed those
  and the pixel proof; the re-check here applies only the pixel proof and the path and audit checks.
- Built with Codex (GPT-6.1 Sol) on Nov 1, in a separate repo, from a written brief (`AGENTS.md` there),
  then moved here as `blinkflow/arm/`, as declared in `DEVLOG.md`. The two clearance re-runs were made here; bug 2 and the
  voice run were made there on Nov 1, also with Codex.

## Re-check it

```bash
pip install -r requirements.txt
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -m blinkflow.arm.recheck examples/arm
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -m blinkflow.arm.recheck examples/arm-bug2
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -m blinkflow.arm.recheck examples/arm-voice
```

How to run it, and the interpreter it was made with: [`docs/RUNNING.md`](../docs/RUNNING.md#the-arm).
