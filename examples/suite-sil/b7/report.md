# b7 — ledge SIL

**Open-loop decision divergence, not an outcome proof.** Recorded inputs belong to the buggy brain. After its first different command, the fixed robot would be elsewhere and later inputs no longer describe its world. Outcome proof stays with BlinkFlow's deterministic twin; no physical robot was tested.

Uses unchanged, pre-existing `microduck_brain.record.replay` (Pollen Robotics / Hugging Face Microduck ecosystem, Apache-2.0) with the Phase 1 observer. New work is the adapter, measurements, classification, report and tests.

Class: **discrete-decision-before-impact**. B changes a discrete decision on the shared prefix before the saved event; this remains decision evidence, not evidence of avoiding the outcome.

Kept fix (attempt 1): restore drop forward/lateral components. The exact saved patch is [change.diff](change.diff). Source revisions and hashes are in [case.json](case.json).

Saved pixel **fall**, reading `pixels`, frame 373: elapsed 10.055000 s. Nearest impact tick 201: elapsed 10.050000 s, original timestamp 13.05. Saved pixel fall has no cited brain_tick; derived the nearest original input tick using BlinkFlow's first-tick time origin. Tick minus pixel-event time: -0.005000 s.

The selected saved event excerpt is in [event.json](event.json); its original evidence-file path and SHA-256 are recorded. `pixel_contact_elapsed_s` is the legacy Phase 1 compatibility key and denotes the selected pixel **fall** when event_kind is fall. No fall is relabelled as a contact.

| measurement | elapsed time / tick | A state → B state | commands A / B (vx m/s, vyaw rad/s) | lead to cited impact tick / saved pixel event | shared prefix |
|---|---|---|---|---|---|
| First exact divergence | 1.850000 s (tick 37) | forward → brake | `move 0.24, +0.24165328872397987` / `stop 0.0, +0.0` | 8.200000 / 8.205000 s | yes |
| First state divergence | 1.850000 s (tick 37) | forward → brake | `move 0.24, +0.24165328872397987` / `stop 0.0, +0.0` | 8.200000 / 8.205000 s | yes |
| B first stop/turn, including startup | 0.000000 s (tick 0) | hold → hold | `stop 0.0, +0.0` / `stop 0.0, +0.0` | 10.050000 / 10.055000 s | yes |
| B first stop/turn after entering forward | 1.850000 s (tick 37) | forward → brake | `move 0.24, +0.24165328872397987` / `stop 0.0, +0.0` | 8.200000 / 8.205000 s | yes |
| B first differential stop/turn while A forward | 1.850000 s (tick 37) | forward → brake | `move 0.24, +0.24165328872397987` / `stop 0.0, +0.0` | 8.200000 / 8.205000 s | yes |

Classify on the prefix ending at the first exact different command. discrete-decision-before-impact requires a pre-impact first different command and B's differential stop/in-place turn or protective state while A stays forward, with no earlier different command. Earlier continuous steering makes the result continuous-only (inconclusive), even if a later state differs before impact. Without a command difference strictly before the cited impact tick, classify no-divergence-before-impact. No numerical threshold replaces exact equality.

The initial shared startup stop is not a differential decision. A turn means `move` with vx=0 and nonzero vyaw; steering with vx>0 stays continuous. All comparisons use exact unrounded command values, without tuning a threshold.

Ticks: 370; exact command differences: 168; state differences: 168. A matches the saved commands at upstream's 1e-4 recording tolerance and all saved states. `why_B` is only the upstream safety/hold reason; no avoidance explanation is invented.

![Emitted commands and decision markers](commands.png)

Traces show emitted commands, not observed motion. Gaps represent `none`. Shading starts at exact divergence; later state/command markers are retained without claiming their later inputs are counterfactual reality.

Offline recheck: `python3 -B -m blinkflow.sil.recheck examples/suite-sil`. No API, simulator, installation, key file or network is needed; cost $0.
