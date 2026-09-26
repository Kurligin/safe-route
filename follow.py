"""Path following: regulated pure pursuit.

- Lookahead point on the path; near the end of a path that stops at the goal the
  target is the goal itself.
- Heading error above ROTATE_ANGLE: rotate on the spot (v = 0).
- Regulation: v <= v_top * cos^2(alpha), and the arc must be feasible with w_max.
- Angular speed from the speed the platform will actually have on this tick
  (speed law), not from the command: no over-steering while accelerating.
- Dock: square-root braking profile to the goal along the final segment; if the
  platform overshot the goal (up to REVERSE_MAX), it backs up. In the last 0.3 m
  there is no steering; if the goal lies off the heading line by more than
  DOCK_CROSS there (the estimate jumped, or the platform turned while waiting),
  driving straight can never reach it: back off to DOCK_BACKOFF and come in again."""

import math
from dataclasses import dataclass

import config_team as cfg
from geometry import wrap
from motion import speed_law
from planner import Path


@dataclass
class Command:
    v: float
    w: float
    remaining: float  # along the path to its end, m
    mode: str  # "follow", "rotate", "dock", "reverse", "stop"


class Follower:
    def __init__(self, config):
        self.rb = config["robot"]
        self.dt = float(config["dt"])
        self.v_top = float(self.rb["v_max"])
        self.w_top = float(self.rb["w_max"])
        self.backoff = False

    def reset(self) -> None:
        """A new path: forget the dock manoeuvre."""
        self.backoff = False

    def command(
        self,
        path: Path,
        s: float,
        x: float,
        y: float,
        th: float,
        v_now: float,
        v_lim: float,
        final: bool,
        target=None,
    ) -> Command:
        """path: the current path (s = arc length of the pose projection), v_now: model speed,
        v_lim: speed profile limit, final: the path ends at the goal where the platform stops,
        target: arc length -> point of the planned (possibly offset) path; default the path itself."""
        remaining = max(0.0, path.length - s)
        gx, gy = (float(path.pts[-1][0]), float(path.pts[-1][1]))
        dgoal = math.hypot(gx - x, gy - y)
        if final and self.backoff:
            if dgoal < cfg.DOCK_BACKOFF:
                vb = min(cfg.REVERSE_V, math.sqrt(2.0 * cfg.DOCK_DECEL * (cfg.DOCK_BACKOFF - dgoal)) + cfg.DOCK_CREEP)
                return Command(-vb, 0.0, dgoal, "backoff")
            self.backoff = False
        if final and dgoal < cfg.REVERSE_MAX + 0.5:
            ex, ey = path.end_direction()
            along = (gx - x) * ex + (gy - y) * ey  # > 0: goal still ahead
            if abs(along) <= cfg.DOCK_STOP_DIST and dgoal <= cfg.ARRIVE_DIST:
                return Command(0.0, 0.0, 0.0, "stop")
            cross = -math.sin(th) * (gx - x) + math.cos(th) * (gy - y)  # goal off the heading line
            if dgoal < cfg.DOCK_NEAR and abs(cross) > cfg.DOCK_CROSS:
                self.backoff = True
                return Command(-cfg.DOCK_CREEP, 0.0, dgoal, "backoff")
            if along < -cfg.DOCK_STOP_DIST and -along <= cfg.REVERSE_MAX and dgoal <= cfg.REVERSE_MAX:
                # overshot the dock point: straight back along the heading
                vb = min(cfg.REVERSE_V, math.sqrt(2.0 * cfg.DOCK_DECEL * max(0.0, -along - cfg.DOCK_STOP_OFFSET)))
                vb = max(vb, cfg.DOCK_CREEP)
                return Command(-vb, 0.0, dgoal, "reverse")
        if final and remaining < cfg.LOOKAHEAD:
            tx, ty = gx, gy
        else:
            tx, ty = (target or path.point_at)(s + cfg.LOOKAHEAD)
        lx = math.hypot(tx - x, ty - y)
        alpha = wrap(math.atan2(ty - y, tx - x) - th) if lx > 1e-6 else 0.0
        if final and dgoal < cfg.DOCK_NEAR:
            # the last centimetres: no turning towards a point under the platform
            alpha = 0.0
        if abs(alpha) > cfg.ROTATE_ANGLE:
            # brake to a stop and turn; while still rolling, the swing is capped by the lateral limit
            w_cap = self.w_top if abs(v_now) < 0.05 else min(self.w_top, cfg.LAT_ACCEL / abs(v_now))
            return Command(0.0, max(-w_cap, min(w_cap, cfg.ROTATE_GAIN * alpha)), remaining, "rotate")
        v = min(v_lim, self.v_top * math.cos(alpha) ** 2)
        lx = max(0.5, lx)
        sa = abs(math.sin(alpha))
        if sa > 1e-3:
            # pure pursuit curvature 2 sin(a) / L must be feasible with w_max and the lateral limit
            kappa = 2.0 * sa / lx
            v = min(v, max(cfg.CURVE_V_MIN, min(self.w_top / kappa, math.sqrt(cfg.LAT_ACCEL / kappa))))
        v = max(0.0, v)
        v_next = speed_law(v_now, v, False, self.rb, self.dt)
        v_avg = 0.5 * (v_now + v_next)
        if v_avg > 0.05:
            w = 2.0 * v_avg * math.sin(alpha) / lx
        else:
            w = cfg.ROTATE_GAIN * alpha
        w = max(-self.w_top, min(self.w_top, w))
        return Command(v, w, remaining, "dock" if final and remaining < cfg.DOCK_DIST else "follow")
