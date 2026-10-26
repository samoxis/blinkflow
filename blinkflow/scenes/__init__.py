"""Scenes for the twin, each one obstacle on the robot's real path, built on Pollen Robotics' scene.

Every scene starts from `scene_demo.xml` of Pollen Robotics' `microduck_rl` (the Microduck robot and
its apartment; `mjlab_microduck/robot/microduck/`), loaded as it is with MjSpec. Their files are never
edited: a scene removes geoms from the loaded spec in memory and attaches its own fragment, an MJCF
file in this folder. All BlinkFlow geoms are named `bf_<scene>_...`; each obstacle has a colour no
other object in its camera shot has, so SAM can be asked for it by name.

    box       Pollen's own `demo_box` (the purple box of the first incident), as the reference
    low_cube  a 7 cm cube on the floor: the low-object layer (bottom sensor rows, memory)
    ledge     the office floor ends in a 12 cm step down: the drop layer
    corner    two walls in a V just inside the office, open towards the robot: the stop threshold
              and the choice of direction
    doorway   a 0.40 m door in a wall across the hall: the swept corridor and the body's width

The robot starts at the origin facing +x (Pollen's HOME placement) and walks through the office door
(x = 0.5, y in [-0.2, 0.6]) into the office; every obstacle is where the clean brain walks. The
office's walls are 1.6 m high, so the new scenes' cameras sit inside the office or above the walls.
Run with microduck_rl's interpreter (mujoco and mjlab_microduck).
"""
import pathlib
import threading
from dataclasses import dataclass, field

import mujoco
from mjlab_microduck.sim.body_server import SCENES as POLLEN, TIMESTEP, World

HERE = pathlib.Path(__file__).resolve().parent
BASE = POLLEN / "scene_demo.xml"
GROUND = ("floor", "rug")           # what the feet stand on: touching these is walking, not an incident


@dataclass(frozen=True)
class Scene:
    name: str
    obstacle: tuple[str, ...]        # geom names (or `bf_` prefixes) that are this scene's obstacle
    camera: dict                     # the incident's fixed shot: pos, look, fov (twin.Video)
    remove: tuple[str, ...] = ()     # Pollen geoms taken out of the loaded spec
    fragment: str | None = None      # MJCF file in this folder, attached to the world
    ground: tuple[str, ...] = field(default=())   # extra geom prefixes the feet may stand on


SCENE_LIST = [
    Scene("box", ("demo_box",), {"pos": [1.2, 0.4088, 0.9657], "look": [0.9, 0.34, 0.12], "fov": 30}),
    Scene("low_cube", ("bf_low_cube",), {"pos": [1.5, 0.6, 1.0], "look": [0.8, 0.22, 0.05], "fov": 45},
          remove=("demo_box",), fragment="low_cube.xml"),
    Scene("ledge", ("bf_ledge_pit",), {"pos": [1.55, 0.75, 1.1], "look": [0.75, 0.35, 0.0], "fov": 50},
          remove=("demo_box", "floor_e", "floor_office"), fragment="ledge.xml", ground=("bf_ledge_floor",)),
    Scene("corner", ("bf_corner_wall",), {"pos": [1.5, 0.33, 1.45], "look": [0.75, 0.33, 0.0], "fov": 50},
          remove=("demo_box", "off_cabinet"), fragment="corner.xml"),
    Scene("doorway", ("bf_doorway",), {"pos": [0.65, 0.1, 2.2], "look": [0.25, 0.1, 0.0], "fov": 45},
          remove=("demo_box",), fragment="doorway.xml"),
]
SCENE_BY_NAME = {s.name: s for s in SCENE_LIST}
NAMES = [s.name for s in SCENE_LIST]


def get(name):
    if name not in SCENE_BY_NAME:
        raise SystemExit(f"unknown scene {name!r}: one of {', '.join(NAMES)}")
    return SCENE_BY_NAME[name]


def model(name):
    """Pollen's scene, loaded as it is, minus `remove`, plus this scene's fragment."""
    s = get(name)
    spec = mujoco.MjSpec.from_file(str(BASE))
    for g in s.remove:
        spec.delete(spec.geom(g))
    if s.fragment:
        spec.attach(mujoco.MjSpec.from_file(str(HERE / s.fragment)), prefix="", frame=spec.worldbody.add_frame())
    return spec.compile()


def world(name):
    """A body_server.World holding this scene's model (World itself only loads files)."""
    w = World.__new__(World)
    w.model = model(name)
    w.model.opt.timestep = TIMESTEP
    w.data = mujoco.MjData(w.model)
    w.lock = threading.Lock()
    w.bodies = []
    return w


def is_ground(scene, geom_name):
    return bool(geom_name) and geom_name.startswith(GROUND + get(scene).ground)


def is_obstacle(scene, geom_name):
    return bool(geom_name) and geom_name.startswith(get(scene).obstacle)
