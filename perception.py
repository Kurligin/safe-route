"""Perception: lidar returns the map does not explain, clustered and tracked.

- Map subtraction: a return well in front of the expected map range (ray cast from
  the estimated pose) and not right next to a mapped wall is "unexplained".
- Clusters: neighbouring unexplained beams (fog gaps and stray snow returns are
  bridged).
- Tracks live in the pure odometry frame, so pose corrections do not move them.
  A track that walks at least 0.6 m in 1 s is a person (and stays "seen walking");
  one that stays put is static (a person never seen walking who stands still for
  0.9 s counts as an object). Each track keeps a centre estimate (the nearest point
  pushed 0.3 m away: a person is a circle of 0.3 m) and a least-squares velocity.
- Straight clusters longer than 1 m are unmapped walls, as are short pieces that
  continue them.
- Output: confirmed clusters, all clusters, person-like tracks in the robot frame
  (including ones that flickered out for up to 1.5 s) and static points."""

import math
from dataclasses import dataclass, field

import numpy as np

import config_team as cfg
from geometry import raycast, seg_dist, wall_segments, wrap


class Track:
    __slots__ = (
        "x",
        "y",
        "hist",
        "seen",
        "dyn",
        "still",
        "k_seen",
        "chist",
        "cx",
        "cy",
        "vx",
        "vy",
        "width",
        "ever",
        "wall",
        "conf",
        "yield_ticks",
    )

    def __init__(self, x: float, y: float):
        self.x, self.y = x, y  # centroid, odometry frame
        self.hist = [(x, y)]
        self.seen = [1]
        self.dyn = None  # None unknown, True moving, False static
        self.still = 0  # ticks without motion
        self.k_seen = 0
        self.chist = []  # (k, cx, cy): centre estimates, odometry frame
        self.cx = self.cy = 0.0
        self.vx = self.vy = 0.0
        self.width = 0.0
        self.ever = False  # was seen walking
        self.wall = False
        self.conf = 0  # ticks as a confirmed cluster
        self.yield_ticks = 0  # ticks the platform yielded to him


@dataclass
class Person:
    """A person-like track in the robot frame (x forward, y left)."""

    c: tuple  # centre
    v: tuple  # velocity over ground, (0, 0) if below 0.3 m/s
    sp: float  # speed
    gap: float  # body-to-person clearance now (from the nearest point, or the centre)
    tr: Track
    young: bool  # too few centre estimates for a velocity


@dataclass
class Percept:
    """What planning and safety get each tick."""

    ranges: np.ndarray
    v_odom: float
    found: list = field(default_factory=list)  # confirmed [(robot-frame points (N, 2), Track)]
    clusters: list = field(default_factory=list)  # all [(points, Track)], confirmed or not
    people: list = field(default_factory=list)  # [Person]
    static: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))  # robot-frame points


def is_wall(pts: np.ndarray) -> bool:
    """Longer than a person and straight: an unmapped wall or fence, not people."""
    if len(pts) < 3:
        return False
    c = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    along = c @ vt[0]
    across = c @ vt[1]
    # robust: the end face of a fence or a stray return must not make it "not straight"
    return float(along.max() - along.min()) > 1.0 and float(np.percentile(np.abs(across), 80)) < 0.1


def on_wall(pts: np.ndarray, walls: list) -> bool:
    """A short cluster that continues the line of an unmapped wall next to it."""
    for w in walls:
        if float(np.min(np.hypot(pts[:, None, 0] - w[None, :, 0], pts[:, None, 1] - w[None, :, 1]))) > 0.6:
            continue
        c = w.mean(axis=0)
        _, _, vt = np.linalg.svd(w - c, full_matrices=False)
        if float(np.percentile(np.abs((pts - c) @ vt[1]), 80)) < 0.15:
            return True
    return False


class Perception:
    def __init__(self, map_, config):
        self.dt = float(config["dt"])
        self.R = float(config["robot"]["radius"])
        lid = config["lidar"]
        self.rel = np.radians(lid["angle_min_deg"] + lid["angle_increment_deg"] * np.arange(lid["beams"]))
        self.cos_rel, self.sin_rel = np.cos(self.rel), np.sin(self.rel)
        self.segs = wall_segments(map_)
        self.seg_lo = np.minimum(self.segs[:, :2], self.segs[:, 2:])
        self.seg_hi = np.maximum(self.segs[:, :2], self.segs[:, 2:])
        self.ox = self.oy = self.oth = 0.0  # pure odometry frame for tracking (no corrections)
        self.v_odom = 0.0
        self.tracks = []
        self.r = None
        self.k = 0

    def odometry(self, obs) -> None:
        """Integrate raw odometry into the tracking frame (every tick)."""
        od = obs["odom"]
        dx, dy, dth = (float(od[k]) if math.isfinite(od[k]) else 0.0 for k in ("dx", "dy", "dtheta"))
        oc, os_ = math.cos(self.oth), math.sin(self.oth)
        self.ox += oc * dx - os_ * dy
        self.oy += os_ * dx + oc * dy
        self.oth = wrap(self.oth + dth)
        self.v_odom = dx / self.dt
        self.r = np.asarray(obs["lidar"]["ranges"], dtype=float)
        self.k += 1

    def near_segs(self, x: float, y: float, reach: float = 20.5) -> np.ndarray:
        m = (
            (self.seg_lo[:, 0] <= x + reach)
            & (self.seg_hi[:, 0] >= x - reach)
            & (self.seg_lo[:, 1] <= y + reach)
            & (self.seg_hi[:, 1] >= y - reach)
        )
        return self.segs[m]

    def update(self, pose, unc: float) -> Percept:
        """Clusters and people for the pose estimate (x, y, th) with position uncertainty
        unc (3 sigma, m)."""
        found, clusters = self._perceive(pose, unc)
        people = self._people(found)
        return Percept(self.r, self.v_odom, found, clusters, people, self._static(found))

    # ------------------------------------------------------------------ frames
    def odo_to_robot(self, ox, oy):
        c, s = math.cos(self.oth), math.sin(self.oth)
        dx, dy = np.asarray(ox) - self.ox, np.asarray(oy) - self.oy
        return c * dx + s * dy, -s * dx + c * dy

    def odo_vec_to_robot(self, vx, vy):
        c, s = math.cos(self.oth), math.sin(self.oth)
        return c * vx + s * vy, -s * vx + c * vy

    # ---------------------------------------------------------------- clusters
    def _perceive(self, pose, unc: float):
        x, y, th = pose
        r = self.r
        segs = self.near_segs(x, y)
        exp = raycast(x, y, th + self.rel, segs)
        margin = 0.35 + min(1.5, 1.5 * unc)
        bad = np.isfinite(r) & (r < exp - margin)
        if bad.any():
            # a return close to a mapped wall is most likely that wall seen from a wrong pose
            idx = np.flatnonzero(bad)
            ang = th + self.rel[idx]
            wx = x + r[idx] * np.cos(ang)
            wy = y + r[idx] * np.sin(ang)
            near_wall = seg_dist(wx, wy, segs) < 0.4 + min(1.5, 1.5 * unc)
            bad[idx[near_wall]] = False
        n = len(r)
        clusters = []
        finite = np.isfinite(r)
        breaks = finite & ~bad  # a real return the map explains ends an object; NaN does not
        if bad.any():
            # start after a beam that ends objects (explained return, else a missing one):
            # in fog in the open yard every return can be unexplained
            start = int(np.argmax(breaks)) if breaks.any() else int(np.argmax(~finite)) if (~finite).any() else 0
            run = []
            skipped = 0
            for j in range(1, n + 1):
                k = (start + j) % n
                if bad[k] and (not run or self._gap(r, k, run[-1]) < 0.6):
                    # neighbours closer than 0.6 m in the plane belong to one object (a fence seen
                    # at a shallow angle has large range steps between beams, small gaps in the plane)
                    run.append(k)
                    skipped = 0
                    continue
                if run and skipped < 2:
                    nxt = [(start + j + d) % n for d in (1, 2)]
                    if not finite[k] or any(bad[q] and self._gap(r, q, run[-1]) < 0.6 for q in nxt):
                        skipped += 1  # a dropped beam (fog) or a stray return (snow) inside an object
                        continue
                if len(run) >= 2:
                    clusters.append(run)
                run = [k] if bad[k] else []
                skipped = 0
            if len(run) >= 2:
                clusters.append(run)
        # tracks live in the odometry frame: GNSS corrections of the pose do not move them
        c, s = math.cos(self.oth), math.sin(self.oth)
        out = []
        cur = []
        for run in clusters:
            idx = np.array(run)
            px = r[idx] * self.cos_rel[idx]
            py = r[idx] * self.sin_rel[idx]
            wx = self.ox + c * px.mean() - s * py.mean()
            wy = self.oy + s * px.mean() + c * py.mean()
            cur.append((np.stack([px, py], axis=1), wx, wy))
        # associate with tracks (nearest within 1 m)
        used = set()
        for pts, wx, wy in cur:
            best, bd = None, 1.0
            for i, tr in enumerate(self.tracks):
                if i in used:
                    continue
                d = math.hypot(tr.x - wx, tr.y - wy)
                if d < bd:
                    best, bd = i, d
            if best is None:
                tr = Track(wx, wy)
                # a fragment of a person already known to move (fog drops beams) keeps the class
                if any(o.dyn is True and math.hypot(o.x - wx, o.y - wy) < 1.0 for o in self.tracks):
                    tr.dyn = True
                    tr.ever = True
                self.tracks.append(tr)
                used.add(len(self.tracks) - 1)
            else:
                tr = self.tracks[best]
                used.add(best)
                tr.x, tr.y = wx, wy
                tr.hist.append((wx, wy))
                tr.seen.append(1)
            self._centre(tr, pts, c, s)
            out.append((pts, tr))
        robot_still = abs(self.v_odom) < 0.02
        for i, tr in enumerate(self.tracks):
            if i not in used:
                tr.seen.append(0)
                tr.hist.append(tr.hist[-1])
            tr.hist = tr.hist[-11:]
            tr.seen = tr.seen[-11:]
            self._velocity(tr)
            if len(tr.hist) >= 11:
                # a person walks >= 0.8 m in 1 s; the visible arc of a static object shifts less
                moved = math.hypot(tr.hist[-1][0] - tr.hist[0][0], tr.hist[-1][1] - tr.hist[0][1])
                if moved >= cfg.WALK_MOVED:
                    tr.dyn = True
                    tr.ever = True
                    tr.still = 0
                elif moved < cfg.STILL_MOVED:
                    tr.still = tr.still + 1 if robot_still else 0
                    if tr.dyn is None and sum(tr.seen) >= 9:
                        tr.dyn = False
                    elif tr.still > cfg.STILL_TICKS:
                        tr.dyn = False  # nobody walks away from a standing platform: an object
        keep = cfg.TRACK_PERSIST
        self.tracks = [tr for tr in self.tracks if sum(tr.seen[-keep:]) > 0]
        found = [(pts, tr) for pts, tr in out if sum(tr.seen[-4:]) >= 3]
        for _, tr in found:
            tr.conf += 1
        return found, out

    def _centre(self, tr: Track, pts: np.ndarray, c: float, s: float) -> None:
        """Centre: the nearest point pushed 0.3 m away from the lidar; width along the cluster."""
        dd = np.hypot(pts[:, 0], pts[:, 1])
        j = int(np.argmin(dd))
        f = 1.0 + 0.3 / max(dd[j], 0.3)
        qx, qy = pts[j, 0] * f, pts[j, 1] * f
        tr.cx, tr.cy = self.ox + c * qx - s * qy, self.oy + s * qx + c * qy
        tr.chist.append((self.k, tr.cx, tr.cy))
        tr.chist = tr.chist[-12:]
        tr.k_seen = self.k
        if len(pts) >= 2:
            cc = pts - pts.mean(axis=0)
            _, _, vt = np.linalg.svd(cc, full_matrices=False)
            al = cc @ vt[0]
            tr.width = float(al.max() - al.min())

    def _velocity(self, tr: Track) -> None:
        """Least-squares velocity of the centre over the last second."""
        h = [e for e in tr.chist if self.k - e[0] <= cfg.VEL_WINDOW]
        if len(h) >= 4 and h[-1][0] - h[0][0] >= 4:
            t = np.array([e[0] for e in h], dtype=float) * self.dt
            t -= t.mean()
            den = float((t * t).sum())
            vx = float((t * np.array([e[1] for e in h])).sum() / den)
            vy = float((t * np.array([e[2] for e in h])).sum() / den)
        else:
            vx = vy = 0.0
        if math.hypot(vx, vy) > 2.5:  # association jump, not a walk
            vx = vy = 0.0
        tr.vx, tr.vy = vx, vy

    def _gap(self, r, a: int, b: int) -> float:
        return math.hypot(
            r[a] * self.cos_rel[a] - r[b] * self.cos_rel[b], r[a] * self.sin_rel[a] - r[b] * self.sin_rel[b]
        )

    # ------------------------------------------------------------------ people
    def _people(self, found) -> list:
        """Person-like tracks (moving or not yet classified), robot frame. A track that flickered
        out (fog, occlusion) keeps counting for up to TRACK_PERSIST ticks, moved on by its velocity."""
        straight = [is_wall(pts) for pts, _ in found]
        walls = [pts for (pts, _), st in zip(found, straight, strict=True) if st]
        ppl = []
        seen_ids = set()
        for (pts, tr), st in zip(found, straight, strict=True):
            seen_ids.add(id(tr))
            if st or on_wall(pts, walls):
                tr.wall = True
                continue
            tr.wall = False
            if tr.dyn is False:
                continue
            ppl.append(self._person(tr, float(np.hypot(pts[:, 0], pts[:, 1]).min()) - self.R))
        for tr in self.tracks:
            if (
                id(tr) in seen_ids
                or tr.dyn is False
                or tr.wall
                or tr.conf < 3
                or self.k - tr.k_seen > cfg.TRACK_PERSIST
            ):
                continue
            ppl.append(self._person(tr, None))
        return ppl

    def _person(self, tr: Track, gap_now) -> Person:
        age = (self.k - tr.k_seen) * self.dt
        cx, cy = self.odo_to_robot(tr.cx + tr.vx * age, tr.cy + tr.vy * age)
        vx, vy = self.odo_vec_to_robot(tr.vx, tr.vy)
        sp = math.hypot(vx, vy)
        if gap_now is None:
            gap_now = math.hypot(cx, cy) - self.R - 0.3
        young = sum(1 for e in tr.chist if self.k - e[0] <= 10) < 4 and tr.dyn is not False
        if not tr.ever and sp < 0.6:  # centroid drift of a static blob seen from a moving platform
            vx = vy = sp = 0.0
        v = (float(vx), float(vy)) if sp > 0.3 else (0.0, 0.0)
        return Person((float(cx), float(cy)), v, float(sp), float(gap_now), tr, young)

    @staticmethod
    def _static(found) -> np.ndarray:
        """Points of confirmed clusters that are not people: objects, unmapped walls, unknown blobs
        that do not move."""
        pts = [p for p, tr in found if tr.dyn is not True and not (tr.dyn is None and math.hypot(tr.vx, tr.vy) > 0.3)]
        return np.vstack(pts) if pts else np.empty((0, 2))
