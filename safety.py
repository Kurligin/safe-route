"""Safety layer: the last word on the command. It only lowers the speed (down to a
stop at exactly zero) and never speeds up.

Rules, in order:
- objects: anything (confirmed cluster) within R + 0.12 of the planned track
  ahead within the stopping distance: stop, turning on the spot stays allowed;
- people, yielding (H2): a person seen walking who stands in front of us within
  4.6 m, or walks at us within 4.4 m: stop at zero and let him pass;
- people, forecast (H1): each person moves on at constant velocity for 3 s (with
  a spread); the speed is the highest candidate that, followed by an escape
  (crawl or stop), keeps him 3 m + margin away while faster than the crawl speed
  and 0.5 m + margin away while moving at all; people behind and walking away do
  not limit; the allowed speed is held as the minimum over 0.8 s;
- start guard: do not start while any cluster that is not a known object is
  within 0.8 m of the body;
- independent of the map: any return inside the swept footprint within the
  braking distance stops the platform; backing up, the same behind it, and no
  backing up with a person close behind;
- emergency brake (estop): an object ahead closer than 1.4 m that normal braking
  at decel can no longer stop for; held only while the platform still moves;
- body clearance: an object or a map wall within R + 0.3 of the planned track
  ahead caps the speed.
People come first: their stops (and "too close") hold up to the goal, only the
object corridor is lifted in the last 0.3 m before the dock point (the dock walls).
A platform standing still keeps turning on the spot while it waits."""

import math
from dataclasses import dataclass

import numpy as np

import config_team as cfg
from motion import speed_law
from perception import Percept

STOP_AHEAD = "obstacle ahead"
STOP_CLOSE = "too close"
STOP_YIELD = "yield"
STOP_PEOPLE = "people"
STOP_GUARD = "person close"
STOP_OBJECT = "object"  # the forecast stops for a young track never seen walking (a new object)
PEOPLE_STOPS = (STOP_YIELD, STOP_PEOPLE, STOP_GUARD)


@dataclass
class Verdict:
    v: float
    w: float
    stop: str  # "" if none
    slow: bool  # the speed was capped for people nearby
    clearance: bool = False  # the speed was capped: the body passes an object or a wall too close
    estop: bool = False  # emergency brake


def _min_dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """For each point of a (N, 2) the distance to the nearest point of b (M, 2)."""
    return np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1]).min(axis=1)


class Safety:
    def __init__(self, config, field=None):
        self.field = field  # signed distance to the map walls (None: no wall clearance)
        self.rb = config["robot"]
        self.R = float(self.rb["radius"])
        self.v_top = float(self.rb["v_max"])
        self.dt = float(config["dt"])
        lid = config["lidar"]
        rel = np.radians(lid["angle_min_deg"] + lid["angle_increment_deg"] * np.arange(lid["beams"]))
        self.cos_rel, self.sin_rel = np.cos(rel), np.sin(rel)
        self.yield_hold = 0
        self.vp_hist = []
        self.estop = False
        self.tt = (np.arange(cfg.PRED_HORIZON) + 1) * self.dt

    # ------------------------------------------------------------------ objects
    def path_blocked(self, found: list, track: np.ndarray, ss: np.ndarray, d_stop: float) -> bool:
        """Points of confirmed clusters within R + PATH_CORRIDOR of the track over the stopping distance."""
        xy = track[ss <= d_stop]
        if not len(xy):
            return False
        for pts, _ in found:
            ahead = pts[pts[:, 0] > cfg.AHEAD_X]
            if len(ahead) and (_min_dist(ahead, xy) < self.R + cfg.PATH_CORRIDOR).any():
                return True
        return False

    def reach(self, v_now: float) -> float:
        """Centre to the far end of the swept footprint: braking distance + one tick + a margin."""
        return self.R + v_now * v_now / 2.4 + v_now * self.dt + cfg.CLOSE_MARGIN

    def close_points(self, r: np.ndarray, v_now: float) -> np.ndarray:
        """Returns (three adjacent beams: a real obstacle, not a snowflake) inside the swept footprint
        within the braking distance, robot frame (N, 2)."""
        reach = self.reach(v_now)
        with np.errstate(invalid="ignore"):
            px, py = r * self.cos_rel, r * self.sin_rel
            close = np.isfinite(r) & (px > 0) & (px < reach) & (np.abs(py) < self.R + cfg.CLOSE_SIDE)
        close &= np.roll(close, 1) & np.roll(close, -1)
        return np.stack([px[close], py[close]], axis=1)

    def too_close(self, r: np.ndarray, v_now: float) -> bool:
        """Anything inside the swept footprint within the braking distance, map or not: a wrong pose
        estimate must not hide a real wall."""
        return len(self.close_points(r, v_now)) > 0

    def estop_needed(self, per: Percept, v_now: float, track: np.ndarray, ss: np.ndarray) -> bool:
        """An object ahead closer than ESTOP_GAP that normal braking can no longer stop for:
        - points of a confirmed static cluster (seen ESTOP_CONF ticks) in the track corridor;
        - raw returns in the swept footprint away from any person: three adjacent beams at about
          the same range (snow returns are independent across beams, a surface is not).
        Returns closer to the lidar than the radius are snow: nothing real can be inside the body."""
        if v_now <= 0.05:
            return False
        pts = []
        xy = track[ss <= self.reach(v_now)]
        for p, tr in per.found:
            if tr.dyn is True or tr.conf < cfg.ESTOP_CONF or not len(xy):
                continue
            p = p[p[:, 0] > 0.0]
            if len(p):
                pts.append(p[_min_dist(p, xy) < self.R + cfg.PATH_CORRIDOR])
        pts.append(self._surface_points(per))
        allp = np.vstack(pts)
        allp = allp[np.hypot(allp[:, 0], allp[:, 1]) > self.R + cfg.ESTOP_MIN_GAP]
        if not len(allp):
            return False
        gap = float(np.hypot(allp[:, 0], allp[:, 1]).min()) - self.R
        need = v_now * v_now / (2.0 * float(self.rb["decel"])) + v_now * self.dt + cfg.ESTOP_MARGIN
        return gap < min(cfg.ESTOP_GAP, need)

    def _surface_points(self, per: Percept) -> np.ndarray:
        """Raw returns in the swept footprint: three adjacent beams within ESTOP_SPREAD in range, not
        next to a person."""
        r = per.ranges
        reach = self.reach(abs(per.v_odom))
        with np.errstate(invalid="ignore"):
            px, py = r * self.cos_rel, r * self.sin_rel
            inb = np.isfinite(r) & (px > 0) & (px < reach) & (np.abs(py) < self.R + cfg.CLOSE_SIDE)
            rl, rr = np.roll(r, 1), np.roll(r, -1)
            flat = (np.abs(r - rl) < cfg.ESTOP_SPREAD) & (np.abs(r - rr) < cfg.ESTOP_SPREAD)
        m = inb & np.roll(inb, 1) & np.roll(inb, -1) & flat
        cp = np.stack([px[m], py[m]], axis=1)
        if len(cp) and per.people:
            pc = np.array([p.c for p in per.people])
            cp = cp[_min_dist(cp, pc) > cfg.ESTOP_PERSON_DIST]
        return cp

    def rear_blocked(self, r: np.ndarray) -> bool:
        """Any return (three adjacent beams) in the band behind the platform within REAR_REACH."""
        with np.errstate(invalid="ignore"):
            px, py = r * self.cos_rel, r * self.sin_rel
            close = np.isfinite(r) & (px < 0) & (px > -(self.R + cfg.REAR_REACH)) & (np.abs(py) < self.R + 0.1)
        return bool((close & np.roll(close, 1) & np.roll(close, -1)).any())

    def clearance(self, static: np.ndarray, track: np.ndarray, ss: np.ndarray, reach: float, pose) -> bool:
        """An object or a map wall within R + CLEARANCE of the planned track ahead (the body would pass
        it too close or graze it; a grazing contact is invisible to the stall detector)."""
        xy = track[ss <= reach]
        if not len(xy):
            return False
        lim = self.R + cfg.CLEARANCE
        if len(static):
            pts = static[static[:, 0] > cfg.AHEAD_X]
            if len(pts) and (_min_dist(pts, xy) < lim).any():
                return True
        if self.field is not None and pose is not None:
            x, y, th = pose
            c, s = math.cos(th), math.sin(th)
            val, _, _ = self.field.lookup(x + c * xy[:, 0] - s * xy[:, 1], y + s * xy[:, 0] + c * xy[:, 1])
            return bool((val < lim).any())
        return False

    def people_behind(self, people: list) -> bool:
        """A person behind the platform closer than REAR_PEOPLE (clearance): no backing up."""
        return any(p.c[0] < 0.0 and p.gap < cfg.REAR_PEOPLE for p in people)

    # ------------------------------------------------------------------- people
    def yield_rule(self, people: list) -> bool:
        """H2: a person seen walking who stands in front of us, or walks at us."""
        for p in people:
            cx, cy = p.c
            dc = math.hypot(cx, cy)
            tr = p.tr
            if not tr.ever or tr.yield_ticks >= cfg.YIELD_MAX_TICKS:
                continue  # a blob never seen walking never walks away
            if p.sp <= cfg.WALK_SPEED:
                if dc < cfg.YIELD_STANDING and cx > cfg.YIELD_BEHIND and tr.width < cfg.YIELD_WIDTH:
                    tr.yield_ticks += 1
                    return True
            elif dc < cfg.YIELD_WALKING:
                ux, uy = p.v[0] / p.sp, p.v[1] / p.sp
                if ux * (-cx) + uy * (-cy) > 0.3 * dc:
                    tr.yield_ticks += 1
                    return True
        return False

    def profile(self, v0: float, vc: float, esc: float):
        """Speeds and distances over the horizon: vc for PRED_HOLD, then the escape speed."""
        v, d = v0, 0.0
        n = cfg.PRED_HORIZON
        vs, ds = np.empty(n), np.empty(n)
        for i in range(n):
            cmd = vc if (i + 1) * self.dt <= cfg.PRED_HOLD + 1e-9 else min(vc, esc)
            vn = speed_law(v, cmd, False, self.rb, self.dt)
            d += 0.5 * (v + vn) * self.dt
            v = vn
            vs[i] = v
            ds[i] = d
        return vs, ds

    def forecast_limit(self, people: list, track: np.ndarray, ss: np.ndarray, v0: float):
        """H1: the highest candidate speed with a safe escape (0: stand)."""
        v_cap = self.v_top
        if not people:
            return v_cap
        crawl = cfg.CRAWL
        C = np.array([p.c for p in people])
        V = np.array([p.v for p in people])
        for i, p in enumerate(people):
            if p.young:  # a track without a velocity yet: assume it walks at us
                d = max(1e-6, math.hypot(*p.c))
                V[i] = (-cfg.YOUNG_SPEED * p.c[0] / d, -cfg.YOUNG_SPEED * p.c[1] / d)
        tt = self.tt
        PX = C[None, :, 0] + V[None, :, 0] * tt[:, None]
        PY = C[None, :, 1] + V[None, :, 1] * tt[:, None]
        spread = cfg.SPREAD * np.hypot(V[:, 0], V[:, 1])[None, :] * tt[:, None]
        gnow = np.array([p.gap for p in people])
        near = cfg.NEAR_GAP + cfg.NEAR_MARGIN
        pas = cfg.PASS_GAP + cfg.PASS_MARGIN
        cands = sorted({round(min(v_cap, c), 3) for c in (v_cap,) + cfg.PRED_CANDIDATES + (crawl,)} - {0.0})
        worst = ""
        for vc in reversed(cands):
            for esc in (crawl, 0.0) if vc > crawl else (0.0,):
                vs, ds = self.profile(v0, vc, esc)
                gap = self._gaps(ds, track, ss, PX, PY) - spread
                fast = vs > crawl + 0.005
                viol_a = bool((fast[:, None] & (gap < near)).any()) or bool(fast[0] and (gnow < near).any())
                viol_b = bool(((vs > 1e-6)[:, None] & (gap < pas)).any())
                if not (viol_a or viol_b):
                    return vc
                worst = "a" if viol_a else "b"
        # nothing safe but standing: if only the 3 m rule is broken anyway (a person appeared close),
        # brake to the crawl speed rather than to zero, unless a close pass threatens
        vs, ds = self.profile(v0, crawl, 0.0)
        gap = self._gaps(ds, track, ss, PX, PY) - spread
        if not ((vs > 1e-6)[:, None] & (gap < pas)).any() and worst == "a" and v0 > crawl + 0.01:
            return crawl
        return 0.0

    def _gaps(self, ds, track, ss, PX, PY) -> np.ndarray:
        rx = np.interp(ds, ss, track[:, 0])
        ry = np.interp(ds, ss, track[:, 1])
        return np.hypot(rx[:, None] - PX, ry[:, None] - PY) - self.R - cfg.PERSON_RADIUS

    def start_guard(self, clusters: list) -> bool:
        """Anything that may be a person (confirmed or not, not a known object or an unmapped wall)
        within START_GUARD of the body."""
        for pts, tr in clusters:
            if tr.dyn is False or (tr.wall and not tr.ever):
                continue
            if float(np.hypot(pts[:, 0], pts[:, 1]).min()) - self.R < cfg.START_GUARD:
                return True
        return False

    # -------------------------------------------------------------------- limit
    def limit(
        self, per: Percept, v: float, w: float, remaining: float, track, ss, v_model: float, pose=None
    ) -> Verdict:
        """Final command from the desired (v, w). track, ss: planned track ahead in the robot frame
        with arc lengths; v_model: speed of the platform by the speed law; pose: (x, y, th) for the
        wall clearance."""
        v_now = abs(per.v_odom)
        r = per.ranges
        ahead = ""
        d_stop = v_now * v_now / 2.0 + cfg.STOP_MARGIN  # body stopping distance + margin
        if self.path_blocked(per.found, track, ss, d_stop):
            ahead = STOP_AHEAD
        people = ""
        slow = False
        if self.yield_rule(per.people):
            self.yield_hold = cfg.YIELD_HOLD
            people = STOP_YIELD
        elif self.yield_hold > 0:
            self.yield_hold -= 1
            people = STOP_YIELD
        if not people:
            vp = self.forecast_limit(per.people, track, ss, v_model)
            self.vp_hist.append(vp)
            self.vp_hist = self.vp_hist[-cfg.PRED_MEMORY :]
            vp = min(self.vp_hist) if vp > 0.0 else 0.0
            if vp <= 0.0:
                # only young tracks never seen walking: most likely a new object, not a person
                real = any(p.tr.ever or p.tr.dyn is True for p in per.people)
                people = STOP_PEOPLE if real or not per.people else STOP_OBJECT
            elif vp < self.v_top - 1e-6:
                slow = vp < v
                v = min(v, vp)
        if not people and v_now < 0.05 and v > 0.0 and self.start_guard(per.clusters):
            people = STOP_GUARD
        if v < 0.0:
            # backing up in a dock: the forward rules do not apply, look behind instead
            if people or self.people_behind(per.people) or self.rear_blocked(r):
                return Verdict(0.0, 0.0, people or STOP_CLOSE, slow)
            return Verdict(v, w, "", slow)
        stop = people or ahead  # people first: their stops hold up to the goal
        if stop in ("", STOP_AHEAD) and self.too_close(r, v_now):
            stop = STOP_CLOSE
        # emergency brake: set when normal braking is too late, held while the platform still moves
        if self.estop and (v_model <= 0.05 or not stop):
            self.estop = False
        if not self.estop and stop and self.estop_needed(per, v_now, track, ss):
            self.estop = True
        reach = self.reach(v_now)
        # the track blends from straight ahead: never look past the end of the path (the dock wall)
        clear = not stop and self.clearance(per.static, track, ss, min(reach, remaining), pose)
        if clear:
            v = min(v, cfg.CLEARANCE_V)
        if stop and (remaining > cfg.DOCK_EXEMPT or stop != STOP_AHEAD):
            v = 0.0
            if stop != STOP_AHEAD and v_now >= 0.05:
                # a round platform standing still may keep turning on the spot while it waits
                # (and turning may clear the corridor); a moving one brakes straight
                w = 0.0
        if self.estop:
            v, w = 0.0, 0.0
        return Verdict(v, w, stop, slow, clear, self.estop)
