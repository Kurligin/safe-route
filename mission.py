"""Mission state machine.

Phases of one mission:
    to_pickup -> to_goal -> docking -> hold
- to_pickup: the platform has not yet been near the `from` point during this
  mission (the previous one ended away from it): drive there first, the load is
  counted only within the pickup radius;
- to_goal: along the reference path;
- docking: the last metres into the dock bay;
- hold: arrived (estimate at the goal, pose certain, platform at rest); the
  status stays "arrived" until the mission id changes.
A new mission id resets everything on the same tick, so "arrived" is never
carried over into the next mission."""

import math
from dataclasses import dataclass

import config_team as cfg

TO_PICKUP = "to_pickup"
TO_GOAL = "to_goal"
DOCKING = "docking"
HOLD = "hold"
DONE = "done"


@dataclass
class MissionView:
    """What the rest of the pipeline needs from the mission."""

    phase: str
    new_phase: bool  # the phase (and so the path) changed on this tick
    goal: tuple  # (x, y, heading) of the current target
    pickup: tuple  # (x, y) of the `from` point
    reference_path: list


class Mission:
    def __init__(self, map_, config):
        self.points = {k: (float(p["x"]), float(p["y"])) for k, p in map_["points"].items()}
        mc = config.get("mission", {})
        self.pickup_radius = float(mc.get("pickup_radius", 2.0))
        self.id = None
        self.phase = DONE
        self.picked = False
        self.arrived = False
        self.at_goal_ticks = 0
        self.goal = (0.0, 0.0, 0.0)
        self.pickup = (0.0, 0.0)
        self.path = []

    def pickup_reach(self, sigma: float) -> float:
        """Estimated distance to `from` that surely means the true one is inside the radius. With a very
        uncertain pose it never drops below PICKUP_FLOOR: standing at `from` must count."""
        return max(cfg.PICKUP_FLOOR, self.pickup_radius - cfg.PICKUP_MARGIN - 3.0 * sigma)

    def update(self, m, x: float, y: float, sigma: float) -> MissionView:
        """m: mission from the observation (or None). Pose estimate x, y with sigma."""
        prev = self.phase
        if m is None:
            self.id = None
            self.phase = DONE
            return MissionView(DONE, prev != DONE, self.goal, self.pickup, self.path)
        new = m["id"] != self.id
        if new:
            self.id = m["id"]
            self.arrived = False
            self.at_goal_ticks = 0
            self.picked = False
            path = [(float(p[0]), float(p[1])) for p in (m.get("reference_path") or [])]
            path = [p for p in path if math.isfinite(p[0]) and math.isfinite(p[1])]
            g = [float(a) for a in (m.get("goal") or [])] + [0.0, 0.0, 0.0]
            if not (math.isfinite(g[0]) and math.isfinite(g[1])):
                g[:2] = path[-1] if path else (x, y)  # no usable goal: the end of the path
            self.goal = (g[0], g[1], g[2] if math.isfinite(g[2]) else 0.0)
            f = self.points.get(m.get("from"))
            if f is None:
                f = path[0] if path else (x, y)
            self.pickup = f
            # the path ends at the goal the arrival is checked against
            if not path:
                path = [(x, y)]
            if math.hypot(path[-1][0] - self.goal[0], path[-1][1] - self.goal[1]) > 0.01:
                path.append(self.goal[:2])
            self.path = path
        if not self.picked and math.hypot(x - self.pickup[0], y - self.pickup[1]) <= self.pickup_reach(sigma):
            self.picked = True
        if self.arrived:
            self.phase = HOLD
        elif not self.picked:
            self.phase = TO_PICKUP
        elif math.hypot(x - self.goal[0], y - self.goal[1]) <= cfg.DOCK_DIST:
            self.phase = DOCKING
        else:
            self.phase = TO_GOAL
        # a phase change within the route (to_goal <-> docking) keeps the same path
        path_change = new or (prev == TO_PICKUP) != (self.phase == TO_PICKUP)
        return MissionView(self.phase, path_change, self.goal, self.pickup, self.path)

    def check_arrival(self, x: float, y: float, sigma: float, at_rest: bool) -> bool:
        """Arrived: estimate within ARRIVE_DIST of the goal, pose certain, platform at rest.
        If the pose stays a bit less certain at the goal, accept a looser sigma after a while
        rather than time out standing in the dock."""
        if self.arrived:
            return True
        if self.phase not in (TO_GOAL, DOCKING) or not self.picked:
            return False
        d = math.hypot(x - self.goal[0], y - self.goal[1])
        if d > cfg.ARRIVE_DIST or not at_rest:
            self.at_goal_ticks = 0
            return False
        self.at_goal_ticks += 1
        lim = cfg.ARRIVE_SIGMA if self.at_goal_ticks < cfg.ARRIVE_LATE_TICKS else cfg.ARRIVE_SIGMA_LATE
        if sigma <= lim:
            self.arrived = True
            self.phase = HOLD
        return self.arrived
