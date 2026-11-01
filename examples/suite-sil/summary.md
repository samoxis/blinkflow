# Frozen-code suite SIL results

Open-loop decision divergence only; no contact/fall prevention or physical-robot outcome is proved. All inputs are saved deterministic-twin recordings. Replay is the pre-existing microduck_brain.record.replay mechanism (Pollen Robotics / Hugging Face Microduck ecosystem, Apache-2.0).

Cases remain in the frozen-code table's order; each uses the stored buggy base and the actual kept fix, without tuning or replacing a fix. Seven of these eight mutations repeated an earlier suite mutation; this is not an independent sample.

Classify on the prefix ending at the first exact different command. discrete-decision-before-impact requires a pre-impact first different command and B's differential stop/in-place turn or protective state while A stays forward, with no earlier different command. Earlier continuous steering makes the result continuous-only (inconclusive), even if a later state differs before impact. Without a command difference strictly before the cited impact tick, classify no-divergence-before-impact. No numerical threshold replaces exact equality.

`continuous-only` names the inconclusive evidence at first command divergence, not an assertion that no later state ever differs. Later state/stop observations are retained and explicitly marked outside the shared prefix.

All times below are seconds since the first recorded input, ticks zero based. Lead column: exact / state / differential B stop-or-turn, relative to the cited nearest impact tick. Pixel-event leads and the signed rounding/alignment offsets are retained in each report and JSON. `*` means after an earlier command divergence.

| bug | scene | kept fix | first exact divergence | first state divergence | B's decisive command | lead before impact: exact / state / B command | class |
|---|---|---|---|---|---|---|---|
| [b3](b3/report.md) | low_cube | [low] range_margin 0.4 -> 0.25 (TOML) | 7.250000 s (tick 145) | 7.250000 s (tick 145); A forward / B brake | stop 0.0, +0.0 at 7.250000 s (tick 145) | 2.850000 / 2.850000 / 2.850000 s | discrete-decision-before-impact |
| [b4](b4/report.md) | low_cube | [low] wall_margin 2.5 -> 0.25 (TOML and default) | 3.400000 s (tick 68) | 5.900000 s (tick 118); A forward / B brake* | stop 0.0, +0.0 at 5.900000 s (tick 118)* | 6.700000 / 4.200000 / 4.200000 s | continuous-only |
| [b6](b6/report.md) | box | side_memory_seconds 0.05 -> 5.0 (TOML) | 1.700000 s (tick 34) | 8.800000 s (tick 176); A forward / B brake* | stop 0.0, +0.0 at 8.800000 s (tick 176)* | 10.700000 / 3.600000 / 3.600000 s | continuous-only |
| [b7](b7/report.md) | ledge | restore drop forward/lateral components | 1.850000 s (tick 37) | 1.850000 s (tick 37); A forward / B brake | stop 0.0, +0.0 at 1.850000 s (tick 37) | 8.200000 / 8.200000 / 8.200000 s | discrete-decision-before-impact |
| [b8](b8/report.md) | box | SIDE half-width = max(obstacle width, low width); configured 0.05 retained | 1.700000 s (tick 34) | 5.600000 s (tick 112); A forward / B brake* | stop 0.0, +0.0 at 5.600000 s (tick 112)* | 16.700000 / 12.800000 / 12.800000 s | continuous-only |
| [b9](b9/report.md) | low_cube | restore low-object forward/lateral components | 3.400000 s (tick 68) | 5.900000 s (tick 118); A forward / B brake* | stop 0.0, +0.0 at 5.900000 s (tick 118)* | 6.700000 / 4.200000 / 4.200000 s | continuous-only |
| [b10](b10/report.md) | ledge | [drop] range_margin 0.6 -> 0.2 (TOML and default) | 1.850000 s (tick 37) | 1.850000 s (tick 37); A forward / B brake | stop 0.0, +0.0 at 1.850000 s (tick 37) | 8.200000 / 8.200000 / 8.200000 s | discrete-decision-before-impact |
| [b11](b11/report.md) | ledge | [drop] max_expected 0.3 -> 0.9 (TOML) | 1.850000 s (tick 37) | 1.850000 s (tick 37); A forward / B brake | stop 0.0, +0.0 at 1.850000 s (tick 37) | 8.200000 / 8.200000 / 8.200000 s | discrete-decision-before-impact |

discrete-decision-before-impact: **4**; continuous-only: **4**; no-divergence-before-impact: **0**; unprocessed: **0**.

Every run begins with a common startup stop. It is recorded as B's absolute first stop/turn, but never counted as a changed protective decision. The table uses B's first differential stop/in-place turn while A remains forward.

The impact/fall comes from each before-run's saved pixel evidence, not the scorer times in the historical suite table. Contact citations already name a nearest log tick; pixel falls do not, so the same nearest-tick rule is applied and that derivation is recorded. No new pixel measurement was made.

Phase 1 purple-box remains **continuous-only (inconclusive)**: the first exact change is steering at 2.104866302 s. Its later state differences cannot undo that earlier divergence. The Phase 1 bundle is unchanged.

Offline: `python -B -S -m sil.recheck examples/suite-sil`. Integrity and original source citations are in `sha256.json` and `suite.json`. New work is the adapter, divergence measurement, classification, report and tests. No model API calls or tuning; replay cost $0.
