"""Paths and the speed profile.

- Path: a polyline with arc length; projection of the pose onto it (the segment
  index only moves forward), lookahead points.
- Route to the pickup point when a mission starts away from it: A* on a 0.5 m
  grid over the drivable area, cells at least 1.4 m from walls, then
  line-of-sight shortcuts.
- Speed profile: zone limit + a small allowance, braking into a slower zone ahead
  of time, braking before sharp turns, a square-root profile into the dock.
- Bypass: an object next to the path axis is passed by a lateral offset of the
  path inside the road (S-shaped transitions), chosen from the static points in
  Frenet coordinates; the offset path stays in the drivable area, out of forbidden
  zones and clear of the map walls.
- The planned track ahead in the robot frame for the safety layer."""

import heapq
import math

import numpy as np

import config_team as cfg
from geometry import inside, inside_mask


class Path:
    def __init__(self, pts):
        self.pts = np.asarray(pts, dtype=float).reshape(-1, 2)
        if len(self.pts) == 1:
            self.pts = np.vstack([self.pts, self.pts])
        d = np.hypot(np.diff(self.pts[:, 0]), np.diff(self.pts[:, 1]))
        self.seg_len = d
        self.cum = np.concatenate([[0.0], np.cumsum(d)])
        self.length = float(self.cum[-1])
        self.seg = 0

    def start_at(self, x: float, y: float) -> None:
        """Segment index = the closest segment to (x, y)."""
        best, bd = 0, math.inf
        for i in range(len(self.pts) - 1):
            d, _ = self._seg_dist(i, x, y)
            if d < bd - 1e-6:
                best, bd = i, d
        self.seg = best

    def _seg_dist(self, i: int, x: float, y: float):
        bx, by = self.pts[i]
        ax, ay = self.pts[i + 1]
        ex, ey = ax - bx, ay - by
        L2 = ex * ex + ey * ey
        u = max(0.0, min(1.0, ((x - bx) * ex + (y - by) * ey) / L2)) if L2 > 0 else 0.0
        return math.hypot(bx + u * ex - x, by + u * ey - y), u

    def project(self, x: float, y: float) -> float:
        """Arc length of the projection of (x, y); advances the segment index."""
        n = len(self.pts)
        while self.seg < n - 2:
            bx, by = self.pts[self.seg]
            ax, ay = self.pts[self.seg + 1]
            ex, ey = ax - bx, ay - by
            L2 = ex * ex + ey * ey
            u = ((x - bx) * ex + (y - by) * ey) / L2 if L2 > 0 else 1.0
            if u >= 1.0:
                self.seg += 1
            else:
                break
        _, u = self._seg_dist(self.seg, x, y)
        return float(self.cum[self.seg] + u * self.seg_len[self.seg])

    def point_at(self, s: float):
        s = min(max(s, 0.0), self.length)
        i = int(np.searchsorted(self.cum, s, side="right")) - 1
        i = min(max(i, 0), len(self.pts) - 2)
        L = self.seg_len[i]
        f = (s - self.cum[i]) / L if L > 0 else 0.0
        p, q = self.pts[i], self.pts[i + 1]
        return float(p[0] + f * (q[0] - p[0])), float(p[1] + f * (q[1] - p[1]))

    def frame_at(self, s):
        """Point, unit tangent and left normal at arc lengths s (array): three (N, 2) arrays."""
        s = np.clip(np.asarray(s, dtype=float), 0.0, self.length)
        i = np.clip(np.searchsorted(self.cum, s, side="right") - 1, 0, len(self.pts) - 2)
        a, b = self.pts[i], self.pts[i + 1]
        L = np.maximum(self.cum[i + 1] - self.cum[i], 1e-9)
        f = ((s - self.cum[i]) / L)[:, None]
        t = (b - a) / L[:, None]
        n = np.stack([-t[:, 1], t[:, 0]], axis=1)
        return a + f * (b - a), t, n

    def end_direction(self):
        """Unit direction of the last non-degenerate segment."""
        for i in range(len(self.pts) - 2, -1, -1):
            if self.seg_len[i] > 1e-6:
                d = self.pts[i + 1] - self.pts[i]
                return float(d[0] / self.seg_len[i]), float(d[1] / self.seg_len[i])
        return 1.0, 0.0

    def corners(self):
        """(arc length, deflection angle) of interior vertices."""
        out = []
        for i in range(1, len(self.pts) - 1):
            if self.seg_len[i - 1] < 1e-6 or self.seg_len[i] < 1e-6:
                continue
            a = self.pts[i] - self.pts[i - 1]
            b = self.pts[i + 1] - self.pts[i]
            c = (a[0] * b[0] + a[1] * b[1]) / (self.seg_len[i - 1] * self.seg_len[i])
            out.append((float(self.cum[i]), math.acos(max(-1.0, min(1.0, c)))))
        return out


class Planner:
    def __init__(self, map_, config, field):
        rb = config["robot"]
        self.v_top = float(rb["v_max"])
        self.R = float(rb["radius"])
        self.w_max = float(rb["w_max"])
        self.decel = float(rb["decel"])
        self.field = field
        self.zones = [
            (np.asarray(z["polygon"], dtype=float), float(z["v_max"]))
            for z in map_["zones"]
            if z["type"] == "speed_limit" and z.get("v_max") is not None
        ]
        self.drivable = [np.asarray(p, dtype=float) for p in map_.get("drivable", [])]
        self.forbidden = [np.asarray(z["polygon"], dtype=float) for z in map_["zones"] if z["type"] == "forbidden"]
        self._grid = None
        self.path = None
        self.final = True
        self.samples_s = np.zeros(0)
        self.samples_v = np.zeros(0)
        self.corner_list = []
        self.bypass = Bypass(self, config)

    # ------------------------------------------------------------------ paths
    def set_path(self, pts, x: float, y: float, final: bool) -> Path:
        """final: the path ends at a stop point (the goal dock)."""
        self.path = Path(pts)
        self.path.start_at(x, y)
        self.final = final
        step = cfg.PROFILE_STEP
        s = np.arange(0.0, self.path.length + step, step)
        xy = np.array([self.path.point_at(float(si)) for si in s]).reshape(-1, 2)
        lim = np.full(len(s), self.v_top)
        for poly, vm in self.zones:
            m = inside_mask(xy[:, 0], xy[:, 1], poly)
            lim[m] = np.minimum(lim[m], vm + cfg.ZONE_ALLOWANCE)
        self.samples_s = s
        self.samples_v = lim
        self.corner_list = self.path.corners()
        self.bypass.reset()
        return self.path

    def target(self, s: float):
        """The point of the planned (possibly offset) path at arc length s."""
        p, _, n = self.path.frame_at(np.array([s]))
        d = self.bypass.offset_at(np.array([s]))[0]
        return float(p[0, 0] + d * n[0, 0]), float(p[0, 1] + d * n[0, 1])

    def track_ahead(self, x: float, y: float, th: float, s0: float, length: float, step: float = 0.1):
        """Planned track ahead in the robot frame: (points (M, 2), arc length (M,)). Starts exactly at
        the platform and blends onto the path over the first 1.5 m."""
        ss = np.arange(0.0, length + 1e-6, step)
        pt, _, nm = self.path.frame_at(s0 + ss)
        pt = pt + self.bypass.offset_at(s0 + ss)[:, None] * nm
        c, sn = math.cos(th), math.sin(th)
        dx, dy = pt[:, 0] - x, pt[:, 1] - y
        xy = np.stack([c * dx + sn * dy, -sn * dx + c * dy], axis=1)
        blend = np.clip(ss / cfg.TRACK_BLEND, 0.0, 1.0)[:, None]
        straight = np.stack([ss, np.zeros_like(ss)], axis=1)
        return blend * xy + (1.0 - blend) * straight, ss

    def _zone_samples(self, s) -> np.ndarray:
        pt, _, nm = self.path.frame_at(s)
        pt = pt + self.bypass.offset_at(s)[:, None] * nm
        lim = np.full(len(s), self.v_top)
        for poly, vm in self.zones:
            m = inside_mask(pt[:, 0], pt[:, 1], poly)
            lim[m] = np.minimum(lim[m], vm + cfg.ZONE_ALLOWANCE)
        return lim

    def offset_ok(self, q: np.ndarray) -> bool:
        """Centre points q (N, 2): inside the drivable area, out of forbidden zones, clear of walls."""
        inn = np.zeros(len(q), dtype=bool)
        for p in self.drivable:
            inn |= inside_mask(q[:, 0], q[:, 1], p)
        if not inn.all():
            return False
        for p in self.forbidden:
            if inside_mask(q[:, 0], q[:, 1], p).any():
                return False
        val, _, _ = self.field.lookup(q[:, 0], q[:, 1])
        return bool(val.min() > self.R + cfg.BYPASS_WALL)

    def zone_limit(self, x: float, y: float) -> float:
        lim = self.v_top
        for poly, vm in self.zones:
            if inside(x, y, poly):
                lim = min(lim, vm + cfg.ZONE_ALLOWANCE)
        return lim

    # ------------------------------------------------------------ speed profile
    def speed_limit(self, s: float, x: float, y: float, sigma: float):
        """Speed limit at arc length s for the pose (x, y): (v, zone limit or None)."""
        a = cfg.ZONE_DECEL
        # the border lies up to one sample before the first sample inside the zone
        m = cfg.ZONE_MARGIN + 3.0 * sigma + cfg.PROFILE_STEP
        v = self.v_top
        zone = self.zone_limit(x, y)
        v = min(v, zone)
        zone_v = zone if zone < self.v_top else None
        if len(self.samples_s):
            ss, vs = self.samples_s, self.samples_v
            win = (ss >= s - m) & (ss <= s + m + (self.v_top**2) / (2 * a) + 0.5)
            if win.any():
                vw = vs[win]
                if self.bypass.active():
                    vw = self._zone_samples(ss[win])  # the zones along the offset path
                d = np.maximum(0.0, ss[win] - s - m)
                lim = np.sqrt(vw**2 + 2.0 * a * d)
                k = int(np.argmin(lim))
                if lim[k] < v:
                    v = float(lim[k])
                    zone_v = float(vw[k])
        # sharp turns ahead: the corner speed that pure pursuit can hold, braked into
        for sc, phi in self.corner_list:
            d = sc - s
            if d < -cfg.LOOKAHEAD or d > cfg.CORNER_WINDOW:
                continue
            if phi < cfg.CORNER_MIN:
                continue
            r = cfg.LOOKAHEAD / math.tan(0.5 * min(phi, 3.1))
            vc = min(self.w_max * r, math.sqrt(cfg.LAT_ACCEL * r))
            v = min(v, math.sqrt(vc * vc + 2.0 * cfg.TURN_DECEL * max(0.0, d)))
        if self.final:
            rem = self.path.length - s
            v = min(v, math.sqrt(2.0 * cfg.DOCK_DECEL * max(0.0, rem - cfg.DOCK_STOP_OFFSET)) + cfg.DOCK_CREEP)
        return v, zone_v

    # ------------------------------------------------------------ A* to pickup
    def _build_grid(self):
        res = cfg.GRID_RES
        allp = np.vstack(self.drivable) if self.drivable else np.zeros((1, 2))
        x0, y0 = allp[:, 0].min(), allp[:, 1].min()
        x1, y1 = allp[:, 0].max(), allp[:, 1].max()
        nx = int(math.ceil((x1 - x0) / res)) + 1
        ny = int(math.ceil((y1 - y0) / res)) + 1
        gx = x0 + np.arange(nx) * res
        gy = y0 + np.arange(ny) * res
        X, Y = np.meshgrid(gx, gy)
        free = np.zeros(X.shape, dtype=bool)
        for p in self.drivable:
            free |= inside_mask(X, Y, p)
        # keep the centre away from the drivable edge: pure pursuit cuts corners
        for _ in range(int(round(cfg.GRID_EDGE_MARGIN / res))):
            e = free.copy()
            e[1:, :] &= free[:-1, :]
            e[:-1, :] &= free[1:, :]
            e[:, 1:] &= free[:, :-1]
            e[:, :-1] &= free[:, 1:]
            e[0, :] = e[-1, :] = False
            e[:, 0] = e[:, -1] = False
            free = e
        for p in self.forbidden:
            free &= ~inside_mask(X, Y, p)
        val, _, _ = self.field.lookup(X.ravel(), Y.ravel())
        free &= val.reshape(X.shape) >= cfg.GRID_CLEARANCE
        self._grid = (x0, y0, res, nx, ny, free)

    def route_to(self, x: float, y: float, gx: float, gy: float, reach: float):
        """Grid A* from (x, y) to any free cell within `reach` of (gx, gy); a polyline
        (world points) or None."""
        if self._grid is None:
            self._build_grid()
        x0, y0, res, nx, ny, free = self._grid

        def cell(px, py):
            return int(round((px - x0) / res)), int(round((py - y0) / res))

        def nearest_free(px, py, rad=cfg.GRID_SNAP):
            ci, cj = cell(px, py)
            best, bd = None, math.inf
            for dj in range(-rad, rad + 1):
                for di in range(-rad, rad + 1):
                    i, j = ci + di, cj + dj
                    if 0 <= i < nx and 0 <= j < ny and free[j, i]:
                        d = di * di + dj * dj
                        if d < bd:
                            best, bd = (i, j), d
            return best

        start = nearest_free(x, y)
        goal = nearest_free(gx, gy)
        if start is None or goal is None:
            return None
        reach_c = reach / res
        diag = math.sqrt(2.0)
        moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0)]
        moves += [(1, 1, diag), (1, -1, diag), (-1, 1, diag), (-1, -1, diag)]
        gi, gj = goal
        openq = [(0.0, 0.0, start)]
        came = {start: None}
        cost = {start: 0.0}
        end = None
        while openq:
            _, c, cur = heapq.heappop(openq)
            if c > cost.get(cur, math.inf):
                continue
            i, j = cur
            if math.hypot(i - gi, j - gj) <= reach_c:
                end = cur
                break
            for di, dj, mc in moves:
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or not free[nj, ni]:
                    continue
                nc = c + mc
                if nc < cost.get((ni, nj), math.inf):
                    cost[(ni, nj)] = nc
                    came[(ni, nj)] = cur
                    heapq.heappush(openq, (nc + math.hypot(ni - gi, nj - gj), nc, (ni, nj)))
        if end is None:
            return None
        cells = []
        c = end
        while c is not None:
            cells.append(c)
            c = came[c]
        cells.reverse()
        cells = self._shortcut(cells, free)
        pts = [(x, y)] + [(float(x0 + i * res), float(y0 + j * res)) for i, j in cells[1:]]
        pts.append((gx, gy))
        return pts

    @staticmethod
    def _line_free(a, b, free) -> bool:
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) * 2 + 1
        for k in range(n + 1):
            t = k / n
            i = int(round(a[0] + t * (b[0] - a[0])))
            j = int(round(a[1] + t * (b[1] - a[1])))
            if not free[j, i]:
                return False
        return True

    def _shortcut(self, cells, free):
        out = [cells[0]]
        k = 0
        while k < len(cells) - 1:
            nxt = k + 1
            for m in range(len(cells) - 1, k + 1, -1):
                if self._line_free(cells[k], cells[m], free):
                    nxt = m
                    break
            out.append(cells[nxt])
            k = nxt
        return out


class Bypass:
    """Lateral offset of the path around static objects next to its axis."""

    def __init__(self, planner: Planner, config):
        self.pl = planner
        self.R = float(config["robot"]["radius"])
        self.off = None  # dict(d, s1, s2, lin)
        self.mem = []  # [(tick, world points (N, 2))]
        self.k = 0

    def reset(self) -> None:
        self.off = None

    def active(self) -> bool:
        return self.off is not None

    def offset_at(self, s) -> np.ndarray:
        o = self.off
        s = np.asarray(s, dtype=float)
        if o is None:
            return np.zeros_like(s)
        a0, a1 = o["s1"] - cfg.BYPASS_LEAD - o["lin"], o["s1"] - cfg.BYPASS_LEAD
        b0, b1 = o["s2"] + cfg.BYPASS_TRAIL, o["s2"] + cfg.BYPASS_TRAIL + cfg.BYPASS_EXIT
        r_in = np.clip((s - a0) / max(a1 - a0, 1e-6), 0.0, 1.0)
        r_out = np.clip((b1 - s) / max(b1 - b0, 1e-6), 0.0, 1.0)
        r = np.minimum(r_in, r_out)
        return o["d"] * r * r * (3.0 - 2.0 * r)

    def update(self, pts_robot: np.ndarray, x: float, y: float, th: float, s0: float) -> None:
        """pts_robot: static points of this tick (robot frame); remembered for BYPASS_MEMORY ticks,
        so an object that drops out of view for a moment keeps its offset."""
        self.k += 1
        c, sn = math.cos(th), math.sin(th)
        if len(pts_robot):
            w = np.stack(
                [x + c * pts_robot[:, 0] - sn * pts_robot[:, 1], y + sn * pts_robot[:, 0] + c * pts_robot[:, 1]], axis=1
            )
        else:
            w = np.empty((0, 2))
        self.mem.append((self.k, w))
        self.mem = [e for e in self.mem if self.k - e[0] <= cfg.BYPASS_MEMORY]
        allp = [e[1] for e in self.mem if len(e[1])]
        self._plan(np.vstack(allp) if allp else np.empty((0, 2)), s0)

    def _plan(self, spts: np.ndarray, s0: float) -> None:
        path = self.pl.path
        if self.off is not None and s0 > self.off["s2"] + cfg.BYPASS_KEEP:
            self.off = None
        if len(spts) == 0:
            return
        horizon = cfg.BYPASS_HORIZON
        ss = np.arange(max(0.0, s0 - 3.0), min(path.length, s0 + horizon) + 1e-6, 0.25)
        if len(ss) < 2:
            return
        pt, tg, nm = path.frame_at(ss)
        # Frenet coordinates of the points
        dx = spts[:, None, 0] - pt[None, :, 0]
        dy = spts[:, None, 1] - pt[None, :, 1]
        j = np.argmin(dx * dx + dy * dy, axis=1)
        qx, qy = dx[np.arange(len(spts)), j], dy[np.arange(len(spts)), j]
        sp = ss[j] + qx * tg[j, 0] + qy * tg[j, 1]
        lp = qx * nm[j, 0] + qy * nm[j, 1]
        near = (np.abs(lp) < cfg.BYPASS_LATERAL) & (sp > s0 - 1.0) & (sp < s0 + horizon - 1.0)
        blocking = near & (np.abs(lp) < self.R + cfg.BYPASS_TRIGGER)
        if not blocking.any():
            return
        bs = sp[blocking]
        s1, s2 = float(bs.min()), float(bs.max())
        ls = lp[near & (sp > s1 - 1.5) & (sp < s2 + 1.5)]
        clear = self.R + cfg.BYPASS_CLEAR
        prev_d = 0.0
        if self.off is not None and self.off["s1"] - 2.0 < s2 and s1 < self.off["s2"] + 2.0:
            prev_d = self.off["d"]
        cands = []
        for d in np.arange(-cfg.BYPASS_MAX, cfg.BYPASS_MAX + 0.01, 0.1):
            d = round(float(d), 2)
            if abs(d) < 0.05:
                continue
            if len(ls) and float(np.min(np.abs(ls - d))) < clear:
                continue
            cands.append((abs(d) + (0.3 if prev_d * d < 0 else 0.0), d))
        cands.sort()
        chosen = None
        # the whole offset stretch, S-transitions included, must be drivable and clear of walls
        s_chk = np.arange(s1 - cfg.BYPASS_KEEP, s2 + cfg.BYPASS_TRAIL + cfg.BYPASS_EXIT + 0.1, 0.5)
        p2, _, n2 = path.frame_at(s_chk)
        for _, d in cands:
            if self.pl.offset_ok(p2 + d * n2):
                chosen = d
                break
        if chosen is None:
            return
        lin = cfg.BYPASS_EXIT if s1 - s0 > cfg.BYPASS_KEEP else max(1.5, s1 - s0 - cfg.BYPASS_LEAD)
        if self.off is not None and abs(self.off["d"] - chosen) < 1e-6:
            lin = self.off["lin"]
            s1 = min(s1, self.off["s1"])
            s2 = max(s2, self.off["s2"])
        self.off = {"d": chosen, "s1": s1, "s2": s2, "lin": lin}
