"""Deterministic Cartesian waypoints, elbow-up inverse kinematics and 200 Hz PD."""
import math
import pathlib
import tomllib

import numpy as np

BASE = (-0.38, 0.16)
L1, L2, TOOL = 0.36, 0.34, 0.06
START = (-0.10, 0.22)


def ik(x, z):
    x, z = x - BASE[0] - TOOL, z - BASE[1]
    c = (x*x + z*z - L1*L1 - L2*L2) / (2*L1*L2)
    if not -1 <= c <= 1:
        raise ValueError(f"unreachable waypoint: {x}, {z}")
    elbow = -math.acos(c)
    shoulder = math.atan2(z, x) - math.atan2(L2*math.sin(elbow), L1+L2*math.cos(elbow))
    return np.array([shoulder, elbow, -shoulder-elbow])


class Brain:
    def __init__(self, folder, target):
        cfg = tomllib.loads((pathlib.Path(folder)/"brain.toml").read_text())
        self.clearance = cfg["planner"]["clearance"]
        self.kp, self.kd = cfg["pd"]["kp"], cfg["pd"]["kd"]
        self.target = (float(target[0]), float(target[2]))

    def waypoint(self, t):
        x0, z0 = START
        x1, z1 = self.target
        lift = max(z0, z1) + self.clearance
        points = [(0., (x0,z0)), (0.5, (x0,z0)), (1.3, (x0,lift)),
                  (3.4, (x1,lift)), (4.3, (x1,z1)), (6., (x1,z1))]
        for i, ((ta,a),(tb,b)) in enumerate(zip(points,points[1:])):
            if t <= tb:
                u = max(0., min(1., (t-ta)/(tb-ta)))
                s = u*u*(3-2*u)
                return ik(*(a[j]+s*(b[j]-a[j]) for j in range(2))), i
        return ik(x1,z1), len(points)-2

    def tick(self, t, q, dq):
        targets, waypoint = self.waypoint(t)
        return self.kp*(targets-q)-self.kd*dq, targets, waypoint
