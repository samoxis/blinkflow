"""A deterministic twin of the Microduck scenario: same physics, same walking policies, same brain,
one process, one clock — simulated time on a 5 ms grid.

The live stack (MuJoCo server, robotd, tofd, the brain) runs on four wall clocks, so two identical
runs drift apart within two seconds. Here every event happens at a fixed simulated instant and in a
fixed order, so the same brain gives the same run, bit for bit, and a fix can be proven by replay.

What is imported, not copied: the world, body, depth sensor and scenes from Pollen Robotics'
`microduck_rl` (`mjlab_microduck.sim`), and the brain itself from the target directory. The scene is
one of blinkflow.scenes (Pollen's apartment plus one obstacle; default `box`, their demo box).
What is re-stated here, from robotd's `control.rs` and `main.rs`: the per-tick controller — stand
below a twist of 0.05, walk above; targets = home + scale x action (0.9 walk, 1.0 stand); gain 200
walking, 160 standing; low-pass 0.7 legs, 0.5 head; command EMA 0.2; 500 ms deadman.
Simplifications, on purpose: the duck starts standing at the home placement (no sit-to-stand
boot); odometry is the true trunk pose; "fallen" is gravity z above -0.5.

Run with microduck_rl's interpreter (it has mujoco and onnxruntime):

    ~/microduck_rl/.venv/bin/python -m blinkflow.twin --brain ~/duck-target --seconds 12
"""
import argparse
import csv
import json
import math
import os
import pathlib
import sys
import time

import mujoco
import numpy as np
import onnxruntime as ort
from mjlab_microduck.sim.body_server import (HOME_POSE, JOINT_NAMES, MOUTH_INDEX, Body, gravity_in_trunk,
                                             pose_table)

from . import scenes

HOME = pathlib.Path.home()
POLICIES = HOME / ".cache" / "duck-sim" / "policies" / "current"

STEP_MS = 5                       # MuJoCo timestep (body_server.TIMESTEP)
CONTROL_STEPS = 4                 # robotd, 50 Hz
BRAIN_STEPS = 10                  # brain, 20 Hz
STATE_STEPS = 8                   # robot.state stream to the brain, 25 Hz
TOF_HZ = 15                       # tofd

STAND_THRESHOLD = 0.05
ACTION_SCALE, STAND_SCALE = 0.9, 1.0
GAIN, STAND_GAIN = 200, 160
LEGS_ALPHA, HEAD_ALPHA = 0.7, 0.5
CMD_ALPHA = 0.2
DEADMAN_S = 0.5
HEAD_JOINTS = range(5, 9)
HOME_ARR = np.array(HOME_POSE)
OBS_JOINTS = [i for i in range(len(JOINT_NAMES)) if i != MOUTH_INDEX]


class Controller:
    """robotd's walk/stand path of `Controller::step`, nothing else."""

    def __init__(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = 1   # deterministic, like robotd
        load = lambda n: ort.InferenceSession(str(POLICIES / n), opts, providers=["CPUExecutionProvider"])
        self.walk, self.stand = load("alpha_walking.onnx"), load("alpha_stand.onnx")
        self.last_action = np.zeros(14, np.float32)
        self.previous = None

    def step(self, s, twist):
        standing = math.sqrt(sum(v * v for v in twist)) <= STAND_THRESHOLD
        pos, vel = np.array(s["positions"]), np.array(s["velocities"])
        obs = np.concatenate([s["imu"]["gyro"], s["imu"]["gravity"],
                              (pos - HOME_ARR)[OBS_JOINTS], vel[OBS_JOINTS], self.last_action,
                              list(twist), [0.0] * 10]).astype(np.float32)[None]
        net = self.stand if standing else self.walk
        action = net.run(None, {"obs": obs})[0][0]
        self.last_action = action.astype(np.float32)
        offsets = np.zeros(len(JOINT_NAMES))
        offsets[OBS_JOINTS] = action
        targets = HOME_ARR + (STAND_SCALE if standing else ACTION_SCALE) * offsets
        if self.previous is not None:
            for j in range(len(targets)):
                if j == MOUTH_INDEX:
                    continue
                a = HEAD_ALPHA if j in HEAD_JOINTS else LEGS_ALPHA
                targets[j] = a * targets[j] + (1 - a) * self.previous[j]
        self.previous = targets
        return targets, (STAND_GAIN if standing else GAIN)


def quat_of(mat):
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(mat).reshape(9))
    return q


class Twin:
    def __init__(self, scene, brain_dir):
        self.scene = scene
        sys.path.insert(0, str(pathlib.Path(brain_dir) / "src"))
        from microduck_brain import config as brain_config
        from microduck_brain.brain import Brain, Inputs
        from microduck_brain.depth import DepthFrame, Pose
        self.Inputs, self.DepthFrame, self.Pose = Inputs, DepthFrame, Pose
        toml = pathlib.Path(brain_dir) / "brain.toml"
        self.cfg = brain_config.load(toml if toml.exists() else None)
        self.brain = Brain(self.cfg)

        self.world = scenes.world(scene)
        self.body = Body(self.world, 0)
        _, trunk_z = pose_table(scenes.BASE, "HOME")
        self.body.place(None, trunk_z, offset_y=0.0)
        self.world.bodies.append(self.body)
        mujoco.mj_forward(self.world.model, self.world.data)
        self.body.set_torque(True)
        self.ctl = Controller()

        m = self.world.model
        self.trunk_body = m.jnt_bodyid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "trunk_base_freejoint")]
        self.duck_geoms = {g for g in range(m.ngeom) if m.body_rootid[m.geom_bodyid[g]] == self.trunk_body}
        names = {g: mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or f"geom{g}" for g in range(m.ngeom)}
        self.obstacle = {g for g, n in names.items() if scenes.is_obstacle(scene, n)}
        # Anything the duck may not touch: every other geom except what it walks on.
        self.things = {g: n for g, n in names.items() if g not in self.duck_geoms and not scenes.is_ground(scene, n)}

        self.step_n = 0
        self.twist_target, self.twist_at = (0.0, 0.0, 0.0), -1e9
        self.twist = [0.0, 0.0, 0.0]
        self.frame, self.frame_at, self.frame_t = None, -1e9, 0.0
        self.states = []               # (t, state dict), last 64
        self.contacts = []             # (t, duck body) with the scene's obstacle
        self.touches = []              # (t, duck body, geom) with anything but the ground, first per geom
        self.track = []                # (t, x, y, fallen), every brain tick
        self.tof_n = 0

    @property
    def t(self):
        return self.step_n * STEP_MS / 1000.0

    # ── what robotd and tofd would publish ────────────────────────────────
    def robot_state(self):
        d, m = self.world.data, self.world.model
        b = self.trunk_body
        r_trunk = d.xmat[b].reshape(3, 3)
        site = self.body.tof.site
        sensor_pos = r_trunk.T @ (d.site_xpos[site] - d.xpos[b])
        sensor_quat = quat_of(r_trunk.T @ d.site_xmat[site].reshape(3, 3))
        trunk_q = d.qpos[self.body.trunk + 3:self.body.trunk + 7]
        w, x, y, z = trunk_q
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        grav = gravity_in_trunk(trunk_q.copy())
        return {"odom": {"yaw": yaw, "position": [float(v) for v in d.qpos[self.body.trunk:self.body.trunk + 3]]},
                "safety": {"gravity": [float(v) for v in grav], "fallen": bool(grav[2] > -0.5)},
                "frames": {"tof": {"pos": [float(v) for v in sensor_pos],
                                   "quat": [float(v) for v in sensor_quat]}}}

    # ── the brain's Runner.inputs, on simulated time ──────────────────────
    def inputs(self):
        now, s = self.t, self.cfg.safety
        frame = self.frame if now - self.frame_at <= s.tof_timeout else None
        if not self.states:
            return self.Inputs(now=now, frame=frame, safe=False, safe_reason="no robot.state")
        t_state, st = self.states[-1]
        fresh = now - t_state <= s.state_timeout
        pose = None
        if fresh:
            t_p, p = min(self.states, key=lambda e: abs(e[0] - self.frame_t))
            if abs(t_p - self.frame_t) <= 0.1:
                pose = self.Pose.from_state(p)
        reason = "" if fresh else "no robot.state"
        if not reason and st["safety"]["fallen"]:
            reason = "the robot has fallen"
        return self.Inputs(now=now, frame=frame, safe=not reason, safe_reason=reason,
                           yaw=st["odom"]["yaw"] if fresh else None, pose=pose,
                           pos=tuple(st["odom"]["position"][:2]) if fresh else None)

    def _contacts(self):
        d, m = self.world.data, self.world.model
        for i in range(d.ncon):
            c = d.contact[i]
            g1, g2 = int(c.geom1), int(c.geom2)
            for duck, other in ((g1, g2), (g2, g1)):
                if duck in self.duck_geoms and other in self.things:
                    name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[duck])
                    if other in self.obstacle:
                        self.contacts.append((round(self.t, 3), name))
                    if all(g != self.things[other] for _, _, g in self.touches):
                        self.touches.append((round(self.t, 3), name, self.things[other]))

    def run(self, settle, seconds, recorder=None, on_frame=None):
        """`settle` s standing still, then `seconds` s of brain. Brain time 0 = end of settle."""
        brain_from = round(settle * 1000 / STEP_MS)
        total = brain_from + round(seconds * 1000 / STEP_MS)
        while self.step_n < total:
            n = self.step_n
            if n * TOF_HZ * STEP_MS >= self.tof_n * 1000:       # tofd: frame due
                self.tof_n += 1
                self.frame = self.DepthFrame.from_params(self.body.depth())
                self.frame_at = self.frame_t = self.t
            if n % STATE_STEPS == 0:
                self.states = (self.states + [(self.t, self.robot_state())])[-64:]
            if n >= brain_from and (n - brain_from) % BRAIN_STEPS == 0:
                inp = self.inputs()
                cmd = self.brain.tick(inp)
                if cmd.kind == "move":
                    self.twist_target, self.twist_at = (cmd.vx, 0.0, cmd.vyaw), self.t
                elif cmd.kind == "stop":
                    self.twist_target, self.twist_at = (0.0, 0.0, 0.0), self.t
                if recorder is not None:
                    recorder.write(inp, cmd, self.brain.state_name)
                st = self.states[-1][1]
                self.track.append((round(self.t, 3), *st["odom"]["position"][:2], st["safety"]["fallen"]))
            if n % CONTROL_STEPS == 0:
                target = self.twist_target if self.t - self.twist_at <= DEADMAN_S else (0.0, 0.0, 0.0)
                self.twist = [e + CMD_ALPHA * (g - e) for e, g in zip(self.twist, target)]
                targets, gain = self.ctl.step(self.body.sensors(), self.twist)
                self.body.set_gain(gain)
                self.body.set_targets(list(targets))
            if on_frame is not None:
                on_frame(self)
            self.world.step(1)
            self.step_n += 1
            self._contacts()
        return brain_from * STEP_MS / 1000.0


class Video:
    """Offscreen render of one fixed camera at `fps` (30) of simulated time, piped to ffmpeg."""

    def __init__(self, twin, path, pos, look, fov, size=(960, 720), renderer=True, fps=30):
        import subprocess
        m = twin.world.model
        m.vis.global_.offwidth, m.vis.global_.offheight = max(size[0], 640), max(size[1], 480)
        self.size = size
        self.renderer = mujoco.Renderer(m, size[1], size[0]) if renderer else None
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        d = np.array(look) - np.array(pos)
        self.cam.lookat[:] = look
        self.cam.distance = float(np.linalg.norm(d))
        self.cam.azimuth = math.degrees(math.atan2(d[1], d[0]))
        self.cam.elevation = math.degrees(math.asin(d[2] / np.linalg.norm(d)))
        m.vis.global_.fovy = fov
        self.every = round(1000 / fps / STEP_MS)   # at 30: 7 steps = 35 ms; frame times are kept exactly
        self.times = []
        self.proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                      "-s", f"{size[0]}x{size[1]}", "-r", str(1000 / (self.every * STEP_MS)),
                                      "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                                      "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)

    def __call__(self, twin):
        if twin.step_n % self.every:
            return
        self.renderer.update_scene(twin.world.data, self.cam)
        self.proc.stdin.write(self.renderer.render().tobytes())
        self.times.append(round(twin.t, 3))

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()


# What mjv_updateScene reads from MjData for this world (no flex, skin, tendons or mocap; contact,
# frame and inertia drawing off). At a frame these are copied as they are at that instant, not
# recomputed from qpos: after mj_step the poses still belong to the step's start.
RENDER_FIELDS = ("qpos", "xpos", "xmat", "xquat", "xipos", "ximat", "geom_xpos", "geom_xmat", "site_xpos",
                 "site_xmat", "light_xpos", "light_xdir", "cam_xpos", "cam_xmat", "subtree_com")
_worker = {}


def _render_init(model, size, cam, threads):
    os.environ["LP_NUM_THREADS"] = str(threads)       # read by Mesa when this process makes its context
    _worker.update(renderer=mujoco.Renderer(model, size[1], size[0]), data=mujoco.MjData(model), cam=cam)
    mujoco.mj_forward(model, _worker["data"])


def _render(states):
    r, d = _worker["renderer"], _worker["data"]
    out = []
    for s in states:
        for k, v in s.items():
            getattr(d, k)[:] = v
        r.update_scene(d, _worker["cam"])
        out.append(r.render().tobytes())
    return b"".join(out)


class ParallelVideo(Video):
    """The same shot as Video, rendered after the physics by `workers` processes.

    The renderer here is Mesa's llvmpipe (software): ~110 ms a frame, and it does not get faster
    with more threads in one context, only with more processes. Physics is ~1 ms a frame, so the run
    keeps each frame's poses (RENDER_FIELDS, ~40 kB) and renders them afterwards, in order, into the
    same ffmpeg encoder: the same frames, byte for byte (checked against Video, Oct 27)."""

    CHUNK = 6

    def __init__(self, twin, path, pos, look, fov, size=(960, 720), workers=12, fps=30):
        super().__init__(twin, path, pos, look, fov, size, renderer=False, fps=fps)
        self.model, self.workers, self.states = twin.world.model, workers, []

    def __call__(self, twin):
        if twin.step_n % self.every:
            return
        d = twin.world.data
        self.states.append({k: getattr(d, k).copy() for k in RENDER_FIELDS})
        self.times.append(round(twin.t, 3))

    def close(self):
        import multiprocessing
        chunks = [self.states[i:i + self.CHUNK] for i in range(0, len(self.states), self.CHUNK)]
        threads = max(1, (os.cpu_count() or 2) // self.workers)
        # fork: the workers inherit the model exactly as the run built it (scene, offscreen size, fov).
        with multiprocessing.get_context("fork").Pool(self.workers, _render_init,
                                                      (self.model, self.size, self.cam, threads)) as pool:
            for frames in pool.imap(_render, chunks):
                self.proc.stdin.write(frames)
        super().close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(HOME / "duck-target"))
    ap.add_argument("--scene", default="box", help=f"one of {', '.join(scenes.NAMES)}")
    ap.add_argument("--settle", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--video", action="store_true", help="render the incident's fixed shot")
    ap.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 1),
                    help="processes rendering the shot (1: render during the run)")
    ap.add_argument("--camera", help='another shot instead of the scene\'s: {"pos": [..], "look": [..], "fov": deg}')
    ap.add_argument("--size", default="960x720", help="the shot's width x height")
    ap.add_argument("--fps", type=float, default=30, help="frames per simulated second (up to 200)")
    ap.add_argument("--out", default=str(HOME / "blinkflow-runs" / "twin"))
    a = ap.parse_args()

    brain = pathlib.Path(a.brain).expanduser()
    out = pathlib.Path(a.out) / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    if a.scene.endswith("scene_demo.xml"):        # replays of incidents recorded before named scenes
        a.scene = "box"
    twin = Twin(a.scene, brain)
    from microduck_brain.record import Recorder
    rec = Recorder(out / "run.jsonl.gz", {"config": str(brain / "brain.toml"), "twin": True})
    video = None
    if a.video:
        # The scene's fixed shot (for `box`, the live incident's camera/shots_incident.json).
        shot = json.loads(a.camera) if a.camera else scenes.get(a.scene).camera
        size = tuple(int(x) for x in a.size.split("x"))
        video = (ParallelVideo(twin, out / "twin.mp4", **shot, size=size, workers=a.workers, fps=a.fps)
                 if a.workers > 1 else Video(twin, out / "twin.mp4", **shot, size=size, fps=a.fps))
    wall = time.time()
    brain_start = twin.run(a.settle, a.seconds, rec, video)
    rec.close()
    if video:
        video.close()
    # Ground truth for the scorer only, like the live simulator's contacts-*.csv: contacts with the
    # scene's obstacle; and in truth.json, the first touch of every other thing and the trunk's track.
    with open(out / "contacts.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_brain", "body"])
        for t, body in twin.contacts:
            w.writerow([f"{t - brain_start:.3f}", body])
    fell = next((t for t, _, _, fallen in twin.track if fallen), None)
    truth = {"scene": a.scene,
             "touches": [{"t": round(t - brain_start, 3), "body": b, "geom": g} for t, b, g in twin.touches],
             "fell_s": None if fell is None else round(fell - brain_start, 3),
             "track": [[round(t - brain_start, 2), round(x, 3), round(y, 3), f] for t, x, y, f in twin.track]}
    (out / "truth.json").write_text(json.dumps(truth))
    meta = {"brain": str(brain), "scene": a.scene, "settle": a.settle, "seconds": a.seconds,
            "record": str(out / "run.jsonl.gz"), "video": str(out / "twin.mp4") if video else None,
            "video_times": video.times if video else None, "brain_start_sim": brain_start,
            "wall_s": round(time.time() - wall, 2)}
    (out / "meta.json").write_text(json.dumps(meta))
    first = twin.contacts[0] if twin.contacts else None
    print(json.dumps({"out": str(out), "scene": a.scene, "wall_s": meta["wall_s"],
                      "first_contact_s": None if not first else round(first[0] - brain_start, 3),
                      "body": None if not first else first[1], "touches": truth["touches"],
                      "fell_s": truth["fell_s"]}))


if __name__ == "__main__":
    main()
