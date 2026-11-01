# The same loop on a 3-joint arm (Nov 1)

BlinkFlow's loop (see → diagnose → fix → prove) on a second robot: a hand-written MuJoCo arm. The scene
([`blinkflow/arm/scene.xml`](../blinkflow/arm/scene.xml), 43 lines, no assets) holds a three-joint planar arm,
a red block and a green target. The controller is [`brain.py`](../blinkflow/arm/brain.py) (45 lines: waypoints,
inverse kinematics, joint PD at 200 Hz) plus [`brain.toml`](../blinkflow/arm/brain.toml). The planted bug is
`clearance = 0.0`, so the end effector sweeps through the block. The same SAM 3.1 measurement, Muse Wonder
diagnosis, citation check, Muse Code fix with BlinkFlow's gate and pixel proof are reused through thin adapters
in [`blinkflow/arm/`](../blinkflow/arm).

The run is in [`examples/arm/`](../examples/arm) ([before and after, side by side](../examples/arm/preview.html)).

## Measured

| Check | Result | Source |
|---|---|---|
| Determinism, planted brain | two replays, one record: `291bd97e…f732f08a` | [`determinism.json`](../examples/arm/determinism.json), [`offline-report.json`](../examples/arm/offline-report.json) |
| Determinism, fixed brain, both rendered | two replays, one record `2a4c4acc…0aabae5`, one video `7e6010ff…5aff51fe` | [`determinism.json`](../examples/arm/determinism.json) |
| First contact, SAM 3.1 pixels / MuJoCo's own contact log | **2.035 s / 2.010 s**, 0.025 s apart (one episode in the log, never shown to the models) | [`alignment.json`](../examples/arm/alignment.json) |
| Muse Wonder's cause | `brain.toml:1–2`, `planner.clearance = 0.0`; `diagnose.check`: `grounded=true`, `bad_refs=[]` (K3, K4, ticks 1.350 and 2.000 s) | [`diagnosis.json`](../examples/arm/before/evidence/diagnosis.json) |
| Muse Code | first attempt, one line: `clearance = 0.0` → `0.08`, only `brain.toml`; gate and audit clean | [`change.diff`](../examples/arm/attempt-1/change.diff), [`muse-code.json`](../examples/arm/attempt-1/muse-code.json) |
| Contacts, before → after | **1 → 0**, from pixels; the 200 Hz contact log agrees | [`result.json`](../examples/arm/result.json) |
| Closest gap after the fix | **3.6 px** (contact is ≤ 2 px) | [`attempt-1/verdict.json`](../examples/arm/attempt-1/verdict.json) |
| Controls: block moved / target moved | **2/2 clean**, closest **20.0 / 51.3 px**, both reach the target | [`control/`](../examples/arm/attempt-1/control) |
| Target reached | error below 0.001 mm (an ideal simulation), tolerance 20 mm | [`result.json`](../examples/arm/result.json) |
| Tracking coverage | 180/180 frames for both objects, before and after; 57/57 in each control | the four `evidence.json` |
| Offline re-check | passed: the four pixel measurements re-derived from SAM 3.1's saved replies, the citation check, the diff, and the physics replayed (same record hashes), with no key and the network blocked | `python3 -m blinkflow.arm.recheck examples/arm` |
| Cost | **$0.29366** the finished loop (SAM 3.1 $0.1896, Muse Wonder $0.09736, Muse Code $0.0067); **$0.38726** in total, with calibration ($0.0936) and one reply lost to a local decoder error, still charged | [`models.json`](../examples/arm/models.json) |

`alignment.json` and `truth.json` say 2.010 s for the physical contact. The arm repo's README says 2.020 s and
0.015 s, figures from an earlier scene. The table above follows the files.

## Limits

- **SAM 3.1 did not find the arm from text.** "robot arm" gave masks in 0 of 180 frames, and so did every other
  phrase tried ("robotic arm", "orange robot"…). The arm is tracked from a box marked once on the first frame,
  with Meta's documented box prompt (`<0f>1<|box;…|>`, [`blinkflow/arm/see.py`](../blinkflow/arm/see.py)). The
  box is identical before, after and in both controls, and is never taken from a contact frame or from the
  simulator. The obstacle is text-prompted ("red block"). This shows visually seeded tracking, not text-only
  detection of the arm.
- An ideal planar simulation: gravity off, no actuator latency or sensor noise, one fixed side camera, one
  scene family (the incident and two small variations), one planted parameter bug. 3.6 px is a modest
  margin; the 9.5 fps control videos alone cannot rule out a touch between frames (the 200 Hz log is clean).
- The sentence is fixed text; no voice, no live window, no physical robot.
- Built with Codex (GPT-6.1 Sol) on Nov 1, in a separate repo, from a written brief (`AGENTS.md` there),
  then moved here as `blinkflow/arm/`, as declared in `DEVLOG.md`.

## Re-check it

```bash
pip install -r requirements.txt mujoco==3.10.0
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -m blinkflow.arm.recheck examples/arm
```

How to run it, and the interpreter it was made with: [`docs/RUNNING.md`](../docs/RUNNING.md#the-arm).
