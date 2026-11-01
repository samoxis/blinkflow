With clearance = 0.0 at brain.toml:2, brain.py:33 computes lift = max(z0,z1) + 0.0. Log t=0.000 gives z0=0.22 m and the target is at the same height in K1-K4, so the 1.3-3.4 s transit (brain.py:34-35) is a flat line at z approx 0.22 m. Log t=1.950 (waypoint=2) confirms the EE is still at z=0.22017 m while x advances toward the block, and K4 at t=2.035 s shows gap=1.0 px (mask contact). In K4 the block top sits roughly 50 px above the EE centre; at the arm's scale (L1=0.36 m, brain.py:9, spanning roughly 330 px in K1) that is about 0.05-0.06 m, putting the block top near z=0.27-0.28 m, well above the EE bottom at the commanded height.

{
 "cause": {
  "file": "brain.toml",
  "function": "planner.clearance config key",
  "lines": {
   "end": 2,
   "start": 1
  },
  "what": "Clearance is exactly zero, so the transit height equals the higher endpoint and the arm travels horizontally into the block. Evidence: K4 shows mask contact at t=2.035 s, frame 61, gap=1.0 px (<=2 px), and log t=1.950 shows waypoint=2 with ee_xyz=[-0.0311, 0.0, 0.22017] moving right at essentially constant z."
 },
 "confidence": 0.88,
 "evidence": [
  {
   "ref": "K1-K4",
   "shows": "Gap closes monotonically: K1 t=1.035 frame 31 gap=77.4 px, K2 t=1.535 frame 46 gap=70.7 px, K3 t=1.935 frame 58 gap=17.0 px, K4 t=2.035 frame 61 gap=1.0 px, i.e. mask contact by the <=2 px rule.",
   "source": "frame",
   "value": "77.4 -> 70.7 -> 17.0 -> 1.0 px"
  },
  {
   "ref": "log t=0.000",
   "shows": "Start EE is [-0.10, 0.0, 0.22] with clearance(m)=0.0, so START height is z=0.22 m.",
   "source": "log",
   "value": "ee z=0.220 m, clearance=0.0"
  },
  {
   "ref": "log t=1.350 to t=2.000",
   "shows": "During waypoint=2 the EE moves horizontally: x goes -0.0999 -> -0.0202 while z stays 0.22000 -> 0.22018, i.e. no lift is being commanded before contact at 2.035 s.",
   "source": "log",
   "value": "waypoint=2, z approx 0.220 m constant"
  },
  {
   "ref": "brain.py:26",
   "shows": "Brain reads self.clearance = cfg[\"planner\"][\"clearance\"].",
   "source": "code",
   "value": "self.clearance = cfg[\"planner\"][\"clearance\"]"
  },
  {
   "ref": "brain.py:33-35",
   "shows": "lift = max(z0, z1) + self.clearance and waypoints go (x0,lift) at 1.3 s to (x1,lift) at 3.4 s; with clearance 0 this is a flat transit at endpoint height.",
   "source": "code",
   "value": "lift = max(z0, z1) + self.clearance"
  },
  {
   "ref": "brain.toml:2",
   "shows": "The causal setting itself.",
   "source": "code",
   "value": "clearance = 0.0"
  }
 ],
 "explanation": "With clearance = 0.0 at brain.toml:2, brain.py:33 computes lift = max(z0,z1) + 0.0. Log t=0.000 gives z0=0.22 m and the target is at the same height in K1-K4, so the 1.3-3.4 s transit (brain.py:34-35) is a flat line at z approx 0.22 m. Log t=1.950 (waypoint=2) confirms the EE is still at z=0.22017 m while x advances toward the block, and K4 at t=2.035 s shows gap=1.0 px (mask contact). In K4 the block top sits roughly 50 px above the EE centre; at the arm's scale (L1=0.36 m, brain.py:9, spanning roughly 330 px in K1) that is about 0.05-0.06 m, putting the block top near z=0.27-0.28 m, well above the EE bottom at the commanded height.",
 "fix_direction": "Increase planner.clearance in brain.toml (direction only, no patch). The EE centre must pass with its underside above the block top: block top is about 0.055 m above the 0.22 m EE centre (K4, log t=0.000) plus roughly 0.04 m EE half-height plus margin, so a clearance of at least ~0.12 m is physically sufficient; 0.15 m gives a safe margin. Reachability is preserved: lift becomes about 0.37 m, and from BASE=(-0.38,0.16) at brain.py:8 the required reach stays under L1+L2=0.70 m (brain.py:9), so the arm can still descend to the green target in the 3.4-4.3 s segment (brain.py:35).",
 "observed": "Blue end-effector translates right at fixed height and strikes the side of the tall block between the start and the green target: K3 t=1.935 gap=17.0 px closing to K4 t=2.035 gap=1.0 px, while log t=1.950 shows waypoint=2 and ee z=0.22017 m.",
 "plain": {
  "camera": "The camera shows the blue arm gliding sideways toward a tall block.",
  "robot": "The robot arm bumps into the block about two seconds in.",
  "why": "It flies too low because its extra lift is set to zero."
 },
 "ruled_out": [
  {
   "because": "K1-K4 show a smooth elbow-up posture progressing rightward and log t=1.350-2.000 shows joint targets changing continuously without the ValueError path at brain.py:16-17 triggering; motion proceeds, so IK is solving.",
   "cause": "Inverse kinematics failure / unreachable waypoint"
  },
  {
   "because": "Log t=1.350 to t=2.000 shows EE z held at 0.2200-0.2202 m exactly as the flat plan commands, with smooth x progression; a PD sag or oscillation would show z droop or jitter, which is absent. kp=100.0, kd=8.0 at brain.toml:5-6 are not implicated.",
   "cause": "PD gains (kp/kd) causing droop or oscillation"
  },
  {
   "because": "Contact occurs at K4 t=2.035 s during waypoint=2 per log t=1.950-2.000, which is the horizontal transit segment (1.3-3.4 s, brain.py:35), long before the descent segment at 3.4-4.3 s.",
   "cause": "Descending too early onto the target/block"
  },
  {
   "because": "Gap shrinks steadily from 77.4 px at K1 t=1.035 to 1.0 px at K4 t=2.035 in step with the logged x motion from log t=1.350 onward; this is planned-path geometry, not a frame artefact. No simulator contact truth is used; only the <=2 px mask rule.",
   "cause": "Camera/mask artefact"
  }
 ]
}
