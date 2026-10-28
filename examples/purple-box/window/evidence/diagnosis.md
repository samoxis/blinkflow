# Diagnosis: white robot touches the purple box

**Cause:** `brain.toml`, `[obstacle] configuration`, lines 29-29. side_memory_seconds is set to 0.0

**In plain words:** The robot walked forward past a box that sat beside it, outside the patch directly ahead that it uses to decide to stop. A separate safeguard was meant to remember close objects at its sides while it passed them, but that safeguard was turned off in its settings, so it kept walking straight until its side touched the box.

**What happened:** The robot walked forward alongside the purple box and touched its side at t=12.503 s (K4, gap 2.0 px) without ever braking or turning away.

**Confidence:** 0.82  ·  **Fix direction (no patch):** Turn the side-hazard memory back on in the configuration (a few seconds, as in the built-in default) so close side returns are remembered and can stop or steer the robot while it is passing an object, then confirm with a replay or simulator run of this approach.

## Evidence cited

- *frame* `K1`: K1. At t=11.503 s, 1 s before contact, the purple box is beside and just in front of the robot's leg, very close; the gap is 36.1 px and the feet are already 101.3 px past the base's far edge, so this was a side approach, not a head-on approach.
- *frame* `K2/K3`: K2, K3. At t=12.003 s (K2) and t=12.403 s (K3) the box remains very close to the robot's left side while the robot continues past it.
- *frame* `K4`: K4. At t=12.503 s the mask gap is 2.0 px, the first-contact reading, with the feet 249.3 px past the base's far edge: the robot touched the box while passing alongside it.
- *log* `log`: t=9.527..12.490. From t=9.527 to t=12.490 (just before contact) every tick is state=forward with cmd move vx=0.24 and only small vyaw; the robot never brakes or turns in place, so nothing ever made the passing box count as blocking.
- *log* `log`: t=9.527. At t=9.527 the leftmost wall-row depth readings are about 67-74 cm with valid frames arriving (marked *), and safe=yes throughout; the sensor was delivering close returns on that side.
- *code* `hazards.py`: hazards.py:62-66,96-107. Side ('wall returns near the body') memory is enabled only when obstacle.side_memory_seconds > 0 (lines 62-66); side hazards are detected from all wall-row columns within 0.8 m ahead and 0.30 m of the axis (lines 96-107), remembered (lines 171-205) and merged into the view so a close one blocks (lines 209-226).
- *code* `brain.toml`: brain.toml:29. brain.toml sets side_memory_seconds = 0.0, switching that side memory off; the built-in default in config.py:46 is 3.0 s.
- *code* `brain.py`: brain.py:143-170. Forward only stops when the ahead view is blocked (lines 143-148) and otherwise keeps moving forward (line 170), so with side memory off the alongside box could never trigger a stop.

## Ruled out

- A missed obstacle dead ahead in the front wall rows: At t=12.390 and t=12.490 the wall-row readings ahead are around 1.0-3.0 m in the full depth frames, well beyond the stop distance; the box was beside, not in the front columns (depth.py:93-112 only judges blocked from the front columns). The failure is the disabled side path, not a missed reading of something dead ahead.
- A low object on the floor missed by the bottom-row detector: In the bottom rows of the full frames (e.g. t=11.989, t=12.490) the readings are smooth floor-like values around 50-100 cm, and contact was with the tall box's side (K1-K4) at leg/body height, not with a small floor-level object in front.
- A fall, unhealthy robot, or blind/missing depth causing a hold: safe=yes on every tick from t=9.527 to t=12.741, new depth frames keep arriving (marked *), and the state never leaves forward for hold; the guard in brain.py:360-371 was never triggered.
- Heading control steering the wrong way: Small vyaw corrections (within about +/-0.2 rad/s) are present throughout the log and the heading stays in a narrow band (yaw about +0.13 to +0.42 rad); the robot held roughly its course. It hit the box because the alongside hazard was never made blocking, not because it steered the wrong way.

## Check against what was sent

- file exists: True; lines in range: True; function found: True
- key frames cited: K1, K2, K3, K4; log ticks cited: none
- references that match nothing sent: ['log', 'log']
- **grounded in pixels and log: NO**

## Key frames

**K1** 1 s before contact, t = 11.50 s. Glimmer: *The robot is walking forward with its legs apart and slightly splayed, and the purple box is to the left of the robot in the picture, just in front of its left leg and very close to it.*

![K1](keyframes/K1.jpg)

**K2** 0.5 s before contact, t = 12.00 s. Glimmer: *The robot is walking forward with its legs positioned under its body, and the purple box is to the left of the robot, slightly above it in the picture and very close to its left side.*

![K2](keyframes/K2.jpg)

**K3** just before contact, t = 12.40 s. Glimmer: *The robot is standing with its legs together and slightly forward, and the purple box is to the left of the robot, just in front of it and very close.*

![K3](keyframes/K3.jpg)

**K4** first contact, t = 12.50 s. Glimmer: *The white robot is standing still with its orange legs positioned under its body, and the purple box is to the left of the robot, slightly above it in the picture and close to its left side.*

![K4](keyframes/K4.jpg)

## Model

muse-wonder-1.0 (Meta Model API), effort medium, 41239 input tokens (30182 cached), 6701 output (5526 reasoning), $0.184, 67 s. Every call of this incident is in `models.json`.
