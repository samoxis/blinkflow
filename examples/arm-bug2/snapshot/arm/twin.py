"""Fixed-step arm replay. Truth is separate from the brain log and pixel pipeline."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import time

import mujoco
import numpy as np

from . import ROBOT, STATE, WORLD

STEP = 0.005
SCENES = ("incident", "obstacle_moved", "target_moved")


def replay(out, brain=ROBOT, scene="incident", seconds=6., fps=30., video=True):
    out, brain = pathlib.Path(out).resolve(), pathlib.Path(brain).resolve()
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("arm_controller", brain/"brain.py")
    ctl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctl)
    model = mujoco.MjModel.from_xml_path(str(WORLD/"scene.xml"))
    gid = lambda name: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
    if scene not in SCENES:
        raise ValueError(scene)
    if scene == "obstacle_moved":
        model.geom_pos[gid("obstacle"),0] = -0.02
    if scene == "target_moved":
        model.geom_pos[gid("target")] = (0.25,0,0.30)
    data = mujoco.MjData(model)
    controller = ctl.Brain(brain, model.geom_pos[gid("target")])
    data.qpos[:] = ctl.ik(*ctl.START)
    mujoco.mj_forward(model,data)
    renderer = mujoco.Renderer(model,720,960) if video else None
    encoder = subprocess.Popen(["ffmpeg","-v","error","-y","-f","rawvideo","-pix_fmt","rgb24",
                                "-s","960x720","-r",str(fps),"-i","-","-c:v","libx264",
                                "-preset","fast","-crf","18","-pix_fmt","yuv420p",str(out/"shot.mp4")],
                               stdin=subprocess.PIPE) if video else None
    rows, contacts, times, episodes, active = [], [], [], [], False
    arm_geoms = {gid(n) for n in ("upper_link","forearm_link","tool_link","end_effector")}
    ee = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_SITE,"ee")
    target = model.geom_pos[gid("target")].copy()
    start = time.monotonic()
    try:
        for n in range(round(seconds/STEP)):
            t = round(n*STEP,6)
            # Bring geometry and contacts to exactly the state being logged/rendered.
            mujoco.mj_forward(model,data)
            torque, targets, waypoint = controller.tick(t,data.qpos.copy(),data.qvel.copy())
            point = data.site_xpos[ee].copy()
            rows.append({"t":t,"joint_targets":targets.tolist(),"q":data.qpos.tolist(),
                         "end_effector":point.tolist(),"target":target.tolist(),"waypoint":waypoint,
                         "clearance":getattr(controller,"clearance",None),"pos":point[:2].tolist(),
                         "state":str(waypoint),"safe":True,"yaw":0.,"cmd":["move",0.,0.]})
            touching = []
            for c in data.contact[:data.ncon]:
                pair = {int(c.geom1),int(c.geom2)}
                if gid("obstacle") in pair and pair & arm_geoms and c.dist <= 0:
                    touching.append({"t":t,"geoms":[mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,int(g))
                                                    for g in (c.geom1,c.geom2)],"distance":float(c.dist)})
            if touching and not active:
                episodes.append(t)
            active = bool(touching)
            contacts.extend(touching)
            if video and n >= round(len(times)*200/fps-1e-8):
                renderer.update_scene(data,camera="incident")
                encoder.stdin.write(renderer.render().tobytes())
                times.append(t)
            data.ctrl[:] = torque
            mujoco.mj_step(model,data)
    finally:
        if encoder:
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError("ffmpeg failed")
            renderer.close()
    mujoco.mj_forward(model,data)
    error = float(np.linalg.norm(data.site_xpos[ee]-target))
    payload = "\n".join(json.dumps(r,separators=(",",":"),sort_keys=True) for r in [{"arm":True,"step":STEP}]+rows)+"\n"
    (out/"record.jsonl.gz").write_bytes(gzip.compress(payload.encode(),mtime=0))
    truth = {"first_contact_s":contacts[0]["t"] if contacts else None,"contact_episodes":episodes,
             "contact_ticks":len({c["t"] for c in contacts}),"contacts":contacts,"target_error_m":error}
    (out/"truth.json").write_text(json.dumps(truth,indent=1))
    meta = {"brain":str(brain),"scene":scene,"seconds":seconds,"settle":0.,
            "record":str(out/"record.jsonl.gz"),"video":str(out/"shot.mp4") if video else None,
            "video_times":times,"brain_start_sim":0.,"fps":fps,"step":STEP,
            "record_sha256":hashlib.sha256((out/"record.jsonl.gz").read_bytes()).hexdigest(),
            "wall_s":round(time.monotonic()-start,2)}
    (out/"meta.json").write_text(json.dumps(meta,indent=1))
    return meta


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--brain",default=str(ROBOT))
    ap.add_argument("--seconds",type=float,default=6.)
    ap.add_argument("--scene",choices=SCENES,default="incident")
    ap.add_argument("--fps",type=float,default=30.)
    ap.add_argument("--out",default=str(STATE/("twin-"+time.strftime("%Y%m%d-%H%M%S"))))
    ap.add_argument("--no-video",action="store_true")
    a=ap.parse_args()
    print(json.dumps(replay(a.out,a.brain,a.scene,a.seconds,a.fps,not a.no_video)))


if __name__=="__main__":
    main()
