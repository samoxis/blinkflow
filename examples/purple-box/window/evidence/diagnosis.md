# Diagnosis: white robot touches the purple box

**Cause:** `brain.toml`, `[obstacle] side_memory_seconds`, lines 29-29. side_memory_seconds is set to 0.0, disabling the hazard map's SIDE kind (hazards.py HazardMap._enabled requires side_memory_seconds > 0). Near-body wall returns in the peripheral sensor column are therefore never remembered or merged into the view ahead, so Forward never starts an avoidance episode for an object alongside the body.

**In plain words:** The purple box approached along the robot's flank rather than head-on, so it showed up only at the edge of the robot's depth view while the way straight ahead stayed clear. The robot therefore kept walking its straight line and clipped the box with its side. The safeguard meant to remember things seen close alongside the body was turned off in the settings, so those edge sightings were thrown away instead of making the robot steer away or stop.

**What happened:** Robot walked straight forward into contact with a purple box that was visible only in the leftmost (peripheral) depth column at ~0.7m, while central columns stayed >1m clear.

**Confidence:** 0.72  ·  **Fix direction (no patch):** Restore a positive side-memory duration in the configuration (the built-in default is 3 seconds) so near-body side returns are retained and fed into avoidance.

## Evidence cited

- *frame* `K1 t=9.903s`: frame 102, gap 26.0 px. Purple box already close on the robot's side, 1s before contact, gap 26px, yet approaching.
- *frame* `K2 t=10.403s`: frame 117. Box at the robot's left side 0.5s before contact, gap 2px on screen.
- *frame* `K3 t=10.803s / K4 t=10.903s`: frames 129/132. Box remains very close at the side through first contact (gap 2px, feet -13.3px past base edge at K4).
- *log* `log t=9.923s full frame`: col0 row2=77cm, col1 row2=129cm. Sensor did see the object in its leftmost column: column 0 reads 77cm in the wall rows while column 1 reads ~129cm  the object is peripheral, not in the central front columns.
- *log* `log t=10.424s full frame`: col0 72-73cm. Object still only in column 0: rows 3-4 read 73/72cm there against 119/120cm in column 1.
- *log* `log t=7.918s..11.126s`: state=forward throughout. Brain stayed in forward at vx=0.24 the whole approach, vyaw only small heading corrections, never brake/turn  it never treated the side object as an obstacle.
- *code* `brain.toml line 29 vs config.py line 46`: 0.0 vs default 3.0. Configured side_memory_seconds=0.0 overrides the built-in default of 3.0s, switching off the only mechanism (hazards.py SIDE detection, SIDE_LOOKAHEAD 0.8m / SIDE_BAND 0.30m) that keeps near-body wall returns like this ~0.72m, column-0 return in play.

## Ruled out

- Head-on wall detection failure / blind sensor: Central front columns read over a metre at t=9.923s and t=10.925s while only column 0 was near; the view ahead was genuinely clear, so the stop-and-turn path correctly never fired.
- Fall, unsafe state, or missing depth frames: Log shows safe=yes on every tick and the state never left forward for hold; valid depth arrived throughout.
- Low-object (cube/ball) floor-geometry detection missed it: The object returns 72-77cm readings in the middle/upper rows (rows 3-4) of column 0, i.e. a tall body-height object, not a floor-level return in the bottom rows.
- Sensor blindness / failed measurements: Depth frames are full of valid returns (nearest per row continuous in the log), so the frame was not blind; the near return was present but in the peripheral column only.

## Check against what was sent

- file exists: True; lines in range: True; function found: True; lines inside it: True
- key frames cited: K1, K2, K3, K4; log ticks cited: 7.918, 9.903, 9.923, 10.403, 10.424, 10.803, 10.903, 11.126
- references that match nothing sent: none
- **grounded (file, lines and function real, the lines inside it; key frames and log ticks cited that exist; every citation real): yes**

## Key frames

**K1** 1 s before contact, t = 9.90 s. Glimmer: *The robot is walking forward with its legs apart and orange feet on the ground, and the purple box is to the left of the robot in the picture, slightly below and in front of it, close to the left edge.*

![K1](keyframes/K1.jpg)

**K2** 0.5 s before contact, t = 10.40 s. Glimmer: *The robot is walking forward with its legs positioned under its body, and the purple box is to the left of the robot in the picture, slightly in front of it and close to its left side.*

![K2](keyframes/K2.jpg)

**K3** just before contact, t = 10.80 s. Glimmer: *The robot is walking forward with its legs lifted off the ground, and the purple box is to the left of the robot in the picture, slightly in front of it and very close to its left side.*

![K3](keyframes/K3.jpg)

**K4** first contact, t = 10.90 s. Glimmer: *The robot is standing facing the camera with its orange feet planted on the ground and its legs slightly apart, and the purple box is to the left of the robot, partially in front of it and very close to its left side.*

![K4](keyframes/K4.jpg)

## Model

muse-wonder-1.0 (Meta Model API), effort medium, 41217 input tokens (30182 cached), 6954 output (5850 reasoning), $0.189, 61 s. Every call of this incident is in `models.json`.
