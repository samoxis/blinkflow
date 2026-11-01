# Replaying recorded inputs through the brain (Nov 1)

This is open-loop decision divergence on recorded inputs, not an outcome proof: after the first different
command, the recorded inputs no longer describe the fixed brain's world, because the robot that ran the fixed
brain would have been somewhere else.

What it does: the sensor inputs recorded during an incident (depth frames, poses, safety, odometry) are fed
tick by tick through the buggy brain (A) and the fixed brain (B), and every command they emit is compared
exactly. The replay mechanism is Pollen's pre-existing `microduck_brain.record.replay` (Pollen Robotics /
Hugging Face Microduck ecosystem, Apache-2.0), unchanged. The new work is the adapter (an observer around
`record.replay` that runs each brain in its own isolated process, no site packages, sockets refused), the
measurement, the classification and the tests: [`blinkflow/sil/`](../blinkflow/sil),
[`tests/test_sil_purple_box.py`](../tests/test_sil_purple_box.py),
[`tests/test_sil_suite.py`](../tests/test_sil_suite.py).

## The eight suite bugs

The rule: the result is read on the shared prefix that ends at the first exact different command. It is a
discrete decision before impact when, at that command, B stops or turns in place (or enters a protective state)
while A stays forward, before the cited impact tick, with no earlier difference. When the first difference is
continuous steering, the result is continuous-only (inconclusive), even if a later state differs. From
[`examples/suite-sil/summary.md`](../examples/suite-sil/summary.md), verbatim (links pointed at the folder):

| bug | scene | kept fix | first exact divergence | first state divergence | B's decisive command | lead before impact: exact / state / B command | class |
|---|---|---|---|---|---|---|---|
| [b3](../examples/suite-sil/b3/report.md) | low_cube | [low] range_margin 0.4 -> 0.25 (TOML) | 7.250000 s (tick 145) | 7.250000 s (tick 145); A forward / B brake | stop 0.0, +0.0 at 7.250000 s (tick 145) | 2.850000 / 2.850000 / 2.850000 s | discrete-decision-before-impact |
| [b4](../examples/suite-sil/b4/report.md) | low_cube | [low] wall_margin 2.5 -> 0.25 (TOML and default) | 3.400000 s (tick 68) | 5.900000 s (tick 118); A forward / B brake* | stop 0.0, +0.0 at 5.900000 s (tick 118)* | 6.700000 / 4.200000 / 4.200000 s | continuous-only |
| [b6](../examples/suite-sil/b6/report.md) | box | side_memory_seconds 0.05 -> 5.0 (TOML) | 1.700000 s (tick 34) | 8.800000 s (tick 176); A forward / B brake* | stop 0.0, +0.0 at 8.800000 s (tick 176)* | 10.700000 / 3.600000 / 3.600000 s | continuous-only |
| [b7](../examples/suite-sil/b7/report.md) | ledge | restore drop forward/lateral components | 1.850000 s (tick 37) | 1.850000 s (tick 37); A forward / B brake | stop 0.0, +0.0 at 1.850000 s (tick 37) | 8.200000 / 8.200000 / 8.200000 s | discrete-decision-before-impact |
| [b8](../examples/suite-sil/b8/report.md) | box | SIDE half-width = max(obstacle width, low width); configured 0.05 retained | 1.700000 s (tick 34) | 5.600000 s (tick 112); A forward / B brake* | stop 0.0, +0.0 at 5.600000 s (tick 112)* | 16.700000 / 12.800000 / 12.800000 s | continuous-only |
| [b9](../examples/suite-sil/b9/report.md) | low_cube | restore low-object forward/lateral components | 3.400000 s (tick 68) | 5.900000 s (tick 118); A forward / B brake* | stop 0.0, +0.0 at 5.900000 s (tick 118)* | 6.700000 / 4.200000 / 4.200000 s | continuous-only |
| [b10](../examples/suite-sil/b10/report.md) | ledge | [drop] range_margin 0.6 -> 0.2 (TOML and default) | 1.850000 s (tick 37) | 1.850000 s (tick 37); A forward / B brake | stop 0.0, +0.0 at 1.850000 s (tick 37) | 8.200000 / 8.200000 / 8.200000 s | discrete-decision-before-impact |
| [b11](../examples/suite-sil/b11/report.md) | ledge | [drop] max_expected 0.3 -> 0.9 (TOML) | 1.850000 s (tick 37) | 1.850000 s (tick 37); A forward / B brake | stop 0.0, +0.0 at 1.850000 s (tick 37) | 8.200000 / 8.200000 / 8.200000 s | discrete-decision-before-impact |

Discrete decision before impact: **4** (b3, b7, b10, b11: A walks on, B brakes with `stop 0.0, 0.0`, 2.85 to
8.2 s before the impact tick). Continuous-only: **4** (b4, b6, b8, b9: the first difference is steering; the
later brakes, marked `*`, come after the inputs stopped describing B's world). No divergence before impact: 0.
Unprocessed: 0.

## The purple box

Continuous-only (inconclusive): the first exact difference is at 2.104866302 s (tick 42), a steering change
of 7.4·10⁻⁵ rad/s (`move 0.24, +0.2552380952380953` → `+0.25531240141981854`, below upstream's 1e-4 command
tolerance) while both brains stay `forward`; the recorded contact is 8.8 s later. Commands differ on 236 of 289
ticks, but none of the later ones is evidence about the fixed robot.
[`examples/purple-box-sil/report.md`](../examples/purple-box-sil/report.md).

## Limits

- The recordings are deterministic-twin recordings from the simulator, not from a physical robot. The log
  format would take a physical recording; none was tested.
- Seven of the eight mutations repeat earlier suite mutations, so the eight are not an independent sample.
- Impact times are cited from the saved pixel evidence, not measured again.
- Cost: $0, no model calls.
- Built with Codex (GPT-6.1 Sol) on Nov 1, in a separate repo, from a written brief, then moved here as
  `blinkflow/sil/`, as declared in `DEVLOG.md`.

## Re-check it

Standard library only, no key, no simulator:

```bash
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -B -m blinkflow.sil.recheck examples/purple-box-sil
env -u MODEL_API_KEY -u BASETEN_API_KEY python3 -B -m blinkflow.sil.recheck examples/suite-sil
```
