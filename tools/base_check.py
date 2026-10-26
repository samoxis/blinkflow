"""Is the base BlinkFlow found from pixels where the box really stands? Scorer-side only, twin runs only
(the twin's camera is known exactly; the live Viser camera is not).

    ~/microduck_rl/.venv/bin/python tools/base_check.py <twin evidence.json>

Projects the four floor corners of `demo_box` from the scene through the twin's fixed camera, rebuilds
the base the same way `blinkflow.see.base_of` did, and reports the overlap of the two.
"""
import json
import math
import pathlib
import sys

import mujoco
import numpy as np
from matplotlib.path import Path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from blinkflow import sam, see  # noqa: E402

CAM = {"pos": [1.2, 0.4088, 0.9657], "look": [0.9, 0.34, 0.12], "fov": 30}   # twin.Video, incident shot


def true_base(scene, size):
    m = mujoco.MjModel.from_xml_path(scene)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "demo_box")
    pos, look = np.array(CAM["pos"]), np.array(CAM["look"])
    f = (look - pos) / np.linalg.norm(look - pos)
    r = np.cross(f, [0, 0, 1])
    r /= np.linalg.norm(r)
    up = np.cross(r, f)
    w, h = size
    focal = h / 2 / math.tan(math.radians(CAM["fov"] / 2))
    R, half = d.geom_xmat[g].reshape(3, 3), m.geom_size[g]
    corners = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        v = d.geom_xpos[g] + R @ (np.array([sx, sy, -1]) * half) - pos
        z = v @ f
        corners.append((w / 2 + focal * (v @ r) / z, h / 2 - focal * (v @ up) / z))
    yy, xx = np.mgrid[:h, :w]
    inside = Path(corners).contains_points(np.stack([xx.ravel(), yy.ravel()], 1)).reshape(h, w)
    return inside


def main():
    ev = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out = pathlib.Path(sys.argv[1]).parent
    snap = json.loads(pathlib.Path(ev["snapshot"]).read_text())
    size = tuple(ev["shot"]["size"])
    f = ev["base"]["from_frame"] - ev["shot"]["first_frame"]
    obj = see.union(sam.load_raw(out / "sam-object.txt")[f], size)
    found = see.base_of(obj, see.rgb(str(out / "shot.mp4"), f))["mask"]
    truth = true_base(snap["scene"], size)
    ys_f, ys_t = np.nonzero(found)[0], np.nonzero(truth)[0]
    print(json.dumps({"iou": round(float((found & truth).sum() / (found | truth).sum()), 3),
                      "found_rows": [int(ys_f.min()), int(ys_f.max())],
                      "true_rows": [int(ys_t.min()), int(ys_t.max())]}))


if __name__ == "__main__":
    main()
