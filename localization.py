"""Pose filter for the platform.

State: x, y, theta, s (odometry scale), bh (INS heading bias), gx, gy (GNSS bias).
Prediction: odometry divided by (1 + s), or the motion model of own commands
(speed law from config). Corrections: scan matching against a signed distance
field of the map (iterated EKF, robust weights, information only where the scan
sees structure), INS heading, GNSS with a chi-square gate and jump detector, GNSS
shadow edge crossings, odometry scale against the commanded motion. Stall
detector: bumper from the scan with a scan-to-scan veto. Lost state with
correlative search for recovery. Independent scale monitor for diagnostics.
Only the standard library and numpy.
"""

import math

import numpy as np

from geometry import DistanceField, inside_mask, map_bounds, wrap
from motion import speed_law

IX, IY, ITH, IS, IBH, IGX, IGY = range(7)
NSTATE = 7


class ScaleMonitor:
    """Independent odometry scale estimate: odometry travel against pose travel along
    the heading, counted only on ticks where the scan pinned the pose in both axes
    before and after. Diagnostics only, it never feeds the filter."""

    def __init__(self, min_len: float = 10.0, anchor_eig: float = 200.0):
        self.min_len = min_len
        self.anchor_eig = anchor_eig
        self.a_odom = 0.0
        self.a_pose = 0.0
        self.s = None
        self.prev_anchored = False

    def update(self, od_dx: float, dx_pose: float, anchored: bool, blocked: bool) -> None:
        if self.prev_anchored and anchored and not blocked:
            self.a_odom += od_dx
            self.a_pose += dx_pose
            if abs(self.a_pose) > self.min_len:
                self.s = min(max(self.a_odom / self.a_pose - 1.0, -0.06), 0.06)
        self.prev_anchored = anchored


class Localizer:
    """EKF over [x, y, th, s, bh, gx, gy]."""

    def __init__(
        self,
        map_,
        config,
        initial_pose,
        use_model=True,
        scale_from_cmd=False,
        field=None,
    ):
        self.use_model = use_model
        # odometry mode: the pose is predicted from odometry, its scale is also calibrated
        # against the commanded motion (the model of own commands never moves the pose)
        self.scale_from_cmd = scale_from_cmd
        self.dt = float(config["dt"])
        self.rb = config["robot"]
        lid = config["lidar"]
        self.nb = int(lid["beams"])
        self.amin = float(lid["angle_min_deg"])
        self.ainc = float(lid["angle_increment_deg"])
        rel = np.radians(self.amin + self.ainc * np.arange(self.nb))
        self.cos_rel = np.cos(rel)
        self.sin_rel = np.sin(rel)
        od = config["odom"]
        self.o_rel = float(od["sigma_rel"])
        self.o_lat = float(od["sigma_lat_rel"])
        self.o_th = math.radians(od["heading_rw_deg_per_sqrt_min"]) / math.sqrt(60.0 / self.dt)
        self.o_snow = float(od["snow_multiplier"])
        lo, hi = od["scale_error_abs_range"]
        sig_s = math.sqrt((lo * lo + lo * hi + hi * hi) / 3.0)
        imu = config["imu"]
        self.h_sig = float(imu["heading_sigma"])
        self.h_rw = math.radians(imu["heading_rw_deg_per_sqrt_min"]) / math.sqrt(60.0 / self.dt)
        g = config["gnss"]
        self.g_a = math.exp(-self.dt / float(g["bias_tau_s"]))
        self.g_b = float(g["bias_sigma"])
        self.g_q = self.g_b * math.sqrt(1.0 - self.g_a**2)
        self.g_w = float(g["white_sigma"])

        if field is None:
            polys = [np.asarray(b["polygon"], dtype=float) for b in map_["buildings"]]
            field = DistanceField(polys, map_bounds(map_, polys), 0.1, 3.0)
        self.field = field
        self.shadows = [np.asarray(z["polygon"], dtype=float) for z in map_["zones"] if z["type"] == "gnss_shadow"]
        edges = []
        for p in self.shadows:
            for i in range(len(p)):
                edges.append([p[i][0], p[i][1], p[(i + 1) % len(p)][0], p[(i + 1) % len(p)][1]])
        self.sh_edges = np.asarray(edges, dtype=float).reshape(-1, 4)

        self.xs = np.array([float(initial_pose[0]), float(initial_pose[1]), float(initial_pose[2]), 0.0, 0.0, 0.0, 0.0])
        self.P = np.diag([0.02**2, 0.02**2, 0.003**2, sig_s**2, 0.003**2, self.g_b**2, self.g_b**2])
        self.vw = 0.0
        self.t = 0.0
        self.k = 0
        self.prev_r = None
        self.prev_valid = None
        self.prev_xy = (self.xs[0], self.xs[1])
        self.snow_est = 0.0
        self.snow = False
        # diagnostics / monitors
        self.blocked = False
        self.blocked_prev = False
        self.stall_llr = 0.0
        self.lost = False
        self.lost_ticks = 0
        self.bad_hist = []
        self.good_run = 0
        self.inl_ratio = 1.0
        self.n_map = 0
        self.out_ratio = 0.0
        self.out_hist = []
        self.last_csm = -1000
        self.mm = False
        self.prev_raw = None
        self.jump_until = -1.0
        self.last_Hxy = np.zeros((2, 2))
        self.last_dth = 0.0
        self.last_ds = 0.0
        self.lost_cooldown = 0
        self.degen_ticks = 0
        self.degen_dir = np.array([1.0, 0.0])
        self.exit_check = 0
        self.last_good_inn = None
        self.rej = []
        self.settle = 0
        self.infl_run = 0
        self.scan_rej = 0
        self.gnss_hist = []
        self.ev = ""
        self.scan_ok = False
        self.smon = ScaleMonitor()

    # ------------------------------------------------------------------ helpers
    def pose(self):
        return float(self.xs[0]), float(self.xs[1]), float(wrap(self.xs[2]))

    def sigma_pos(self):
        w = np.linalg.eigvalsh(self.P[:2, :2])
        return float(math.sqrt(max(w[-1], 0.0)))

    def _kalman(self, H, y, R):
        """Linear update: H (m, n), y (m,), R (m, m)."""
        P = self.P
        S = H @ P @ H.T + R
        K = np.linalg.solve(S, H @ P).T
        self.xs = self.xs + K @ y
        self.xs[ITH] = wrap(self.xs[ITH])
        IKH = np.eye(NSTATE) - K @ H
        self.P = IKH @ P @ IKH.T + K @ R @ K.T
        self.P = 0.5 * (self.P + self.P.T)

    def _scan_points(self, r):
        ok = np.isfinite(r) & (r > 0.2)
        near = r < 3.0
        if self.prev_r is not None:
            k = int(round(math.degrees(self.last_dth) / self.ainc))
            prev = np.roll(self.prev_r, -k) if k else self.prev_r
            with np.errstate(invalid="ignore"):
                conf = np.abs(r - prev) < 0.15 + self.last_ds
        else:
            conf = np.zeros(len(r), dtype=bool)
        ok &= (~near) | conf
        return r[ok] * self.cos_rel[ok], r[ok] * self.sin_rel[ok]

    def _snow_update(self, r):
        fin = np.isfinite(r)
        rl = np.roll(r, 1)
        rr = np.roll(r, -1)
        with np.errstate(invalid="ignore"):
            iso_l = ~np.isfinite(rl) | (np.abs(r - rl) > 0.5)
            iso_r = ~np.isfinite(rr) | (np.abs(r - rr) > 0.5)
            cnt = int(np.count_nonzero(fin & (r < 3.0) & iso_l & iso_r))
        self.snow_est = 0.97 * self.snow_est + 0.03 * cnt
        self.snow = self.snow_est > 3.0

    # ------------------------------------------------------------ stall test
    def _project(self, px, py, tx, ty, dth, cur):
        """Residual of previous-scan points moved by (tx, ty, dth) against the current scan,
        interpolated at the exact bearing (no binning: binning favours "stood still")."""
        qx = px - tx
        qy = py - ty
        c, s = math.cos(-dth), math.sin(-dth)
        rx = c * qx - s * qy
        ry = s * qx + c * qy
        f = (np.degrees(np.arctan2(ry, rx)) - self.amin) / self.ainc
        fl = np.floor(f)
        t = f - fl
        i0 = fl.astype(np.intp) % self.nb
        i1 = (i0 + 1) % self.nb
        a = cur[i0]
        b = cur[i1]
        with np.errstate(invalid="ignore"):
            ok = np.isfinite(a) & np.isfinite(b) & (np.abs(a - b) < 0.3)
        return np.where(ok, a + t * (b - a) - np.hypot(rx, ry), np.nan)

    def _stall_llr(self, prev, cur, dx, dy, dth):
        """> 0: the scan says the platform stood still, < 0: it moved as predicted."""
        if math.hypot(dx, dy) < 0.008:
            return 0.0
        with np.errstate(invalid="ignore"):
            nbd = 0.5 * np.abs(np.roll(prev, -1) - np.roll(prev, 1))
            ok = np.isfinite(prev) & (prev > 0.3) & (prev < 12.0) & np.isfinite(nbd) & (nbd < 0.045 * prev)
        if np.count_nonzero(ok) < 8:
            return 0.0
        px = prev[ok] * self.cos_rel[ok]
        py = prev[ok] * self.sin_rel[ok]
        e1 = self._project(px, py, dx, dy, dth, cur)
        e0 = self._project(px, py, 0.0, 0.0, dth, cur)
        with np.errstate(invalid="ignore"):
            m = np.isfinite(e1) & np.isfinite(e0) & (np.abs(e1 - e0) > 0.025)
        if np.count_nonzero(m) < 4:
            return 0.0
        e1 = e1[m]
        e0 = e0[m]
        c2 = 0.15**2
        return float((np.minimum(e1 * e1, c2).sum() - np.minimum(e0 * e0, c2).sum()) / (2 * 0.05**2))

    @staticmethod
    def _kmin(d, k=3):
        return float(np.partition(d, k - 1)[:k].mean()) if len(d) >= k else math.inf

    def _touch(self, r, dx, dy, hold=False):
        """Bumper from the scan, the same test the simulator applies (world.step_robot):
        blocked if the commanded step (dx, dy) would bring the body into what the previous scan
        saw (gap after the step < 0) while the gap decreases. Both (dx, dy) and prev_r are in the
        frame of the start of the step, so no rotation. Only returns confirmed by the current scan
        (|r - r_prev| < 5 cm + ds: kills snow and flicker) within 0.5 m of the body. Direct
        distances: walls, corners, pedestrians and pallets alike, any speed and angle.
        The gap estimate (mean of the 2 smallest distances) is biased low by lidar noise (sigma
        3 cm), hence the -2 cm entry threshold. A grazing contact under ~5 deg stays ambiguous at
        this noise (the gap changes by < 1 cm per tick)."""
        ds = math.hypot(dx, dy)
        prev = self.prev_r
        if ds < 1e-4 or prev is None:
            return False
        R = self.rb["radius"]
        with np.errstate(invalid="ignore"):
            ok = np.isfinite(prev) & np.isfinite(r) & (prev - R < 0.5) & (np.abs(r - prev) < 0.05 + ds)
        if np.count_nonzero(ok) < 3:
            return False
        px, py = prev[ok] * self.cos_rel[ok], prev[ok] * self.sin_rel[ok]
        g0 = self._kmin(np.hypot(px, py), 2) - R
        g1 = self._kmin(np.hypot(px - dx, py - dy), 2) - R
        # thresholds tuned on a synthetic suite (walls, 90 deg corner, pedestrian, pallet, snow,
        # fog, 0.05-1.39 m/s): enter below -2 cm, hold below +2 cm
        return g1 < g0 and g1 < (0.02 if hold else -0.02)

    # ------------------------------------------------------------- prediction
    def _predict(self, dx, dy, dth, from_odom):
        xs, P = self.xs, self.P
        th = xs[ITH]
        c, s = math.cos(th), math.sin(th)
        F = np.eye(NSTATE)
        F[IX, ITH] = -s * dx - c * dy
        F[IY, ITH] = c * dx - s * dy
        if from_odom:
            k = -1.0 / (1.0 + xs[IS])
            F[IX, IS] = k * (c * dx - s * dy)
            F[IY, IS] = k * (s * dx + c * dy)
        F[IGX, IGX] = F[IGY, IGY] = self.g_a
        xs[IX] += c * dx - s * dy
        xs[IY] += s * dx + c * dy
        xs[ITH] = wrap(th + dth)
        xs[IGX] *= self.g_a
        xs[IGY] *= self.g_a
        ds = math.hypot(dx, dy)
        mult = self.o_snow if self.snow else 1.0
        if from_odom:
            sa, sl = self.o_rel * ds * mult, self.o_lat * ds * mult
            sth = self.o_th * mult if (ds > 1e-6 or abs(dth) > 1e-6) else 0.0
        else:
            sa, sl, sth = 0.01 * ds, 0.005 * ds, 1e-4 * min(1.0, ds / 0.05 + abs(dth) / 0.01)
        sa, sl, sth = sa + 2e-4, sl + 2e-4, sth + 2e-5
        Rb = np.array([[c, -s], [s, c]])
        Q = np.zeros((NSTATE, NSTATE))
        Q[:2, :2] = Rb @ np.diag([sa * sa, sl * sl]) @ Rb.T
        Q[ITH, ITH] = sth * sth
        Q[IS, IS] = 1e-12
        Q[IBH, IBH] = self.h_rw**2
        Q[IGX, IGX] = Q[IGY, IGY] = self.g_q**2
        self.P = F @ P @ F.T + Q

    # ------------------------------------------------------------ corrections
    def _odom_scale(self, od, m_dx, m_ds):
        if abs(m_dx) < 1e-3:
            return
        mult = self.o_snow if self.snow else 1.0
        H = np.zeros((1, NSTATE))
        H[0, IS] = m_dx
        y = np.array([od["dx"] - m_dx * (1.0 + self.xs[IS])])
        R = np.array([[(self.o_rel * m_ds * mult) ** 2 + 1e-10]])
        self._kalman(H, y, R)

    def _imu(self, imu):
        H = np.zeros((1, NSTATE))
        H[0, ITH] = 1.0
        H[0, IBH] = 1.0
        y = np.array([wrap(imu["heading"] - self.xs[ITH] - self.xs[IBH])])
        self._kalman(H, y, np.array([[self.h_sig**2 + 1e-8]]))

    def _residuals(self, xs, bx, by):
        c, s = math.cos(xs[ITH]), math.sin(xs[ITH])
        wx = xs[IX] + c * bx - s * by
        wy = xs[IY] + s * bx + c * by
        val, gx, gy = self.field.lookup(wx, wy)
        return wx, wy, val, gx, gy

    def _explained_along(self, wx, wy, v):
        """Among points whose map gradient is along v (they carry information on v),
        the share that lies on a wall (|D| < 0.2). None if there are too few such points."""
        val, gx, gy = self.field.lookup(wx, wy)
        near = np.abs(val) < self.field.clamp - 0.3
        inf = near & (np.abs(gx * v[0] + gy * v[1]) > 0.7)
        n = int(np.count_nonzero(inf))
        if n < 8:
            return None
        return float(np.count_nonzero(inf & (np.abs(val) < 0.2))) / n

    def _search_1d(self, bx, by, v=None, sl=None, span=None):
        """Wide 1D correlative search along the least observed direction.
        Returns "fix", "confirm" or None (ambiguous)."""
        w, V = np.linalg.eigh(self.P[:2, :2])
        if v is None:
            v = V[:, -1]
        if sl is None:
            sl = math.sqrt(max(w[-1], 0.0))
        if span is None:
            span = min(8.0, 3.0 * sl + 0.5)
        taus = np.arange(-span, span + 1e-9, 0.1)
        c, s = math.cos(self.xs[ITH]), math.sin(self.xs[ITH])
        wx = self.xs[IX] + c * bx - s * by
        wy = self.xs[IY] + s * bx + c * by
        WX = wx[None, :] + taus[:, None] * v[0]
        WY = wy[None, :] + taus[:, None] * v[1]
        val, _, _ = self.field.lookup(WX.ravel(), WY.ravel())
        val = val.reshape(WX.shape)
        cost = np.minimum(val * val, 0.3**2).sum(axis=1) / (2 * 0.1**2) + taus * taus / (2 * sl * sl)
        ib = int(np.argmin(cost))
        i0 = int(np.argmin(np.abs(taus)))
        far = np.abs(taus - taus[ib]) > 1.0
        second = float(cost[far].min()) if far.any() else math.inf
        tb = float(taus[ib])
        thr = max(8.0, 0.03 * len(bx))
        if abs(tb) > 0.15:
            # weak-prior search: an unmapped face next to a mapped one aliases (container by K1);
            # accept only if the current pose explains almost none of the informative points
            # and the candidate explains most of them
            e0 = self._explained_along(wx, wy, v)
            e1 = self._explained_along(WX[ib], WY[ib], v)
            if e0 is None or e1 is None or e0 > 0.3 or e1 < 0.7:
                return "reject"
        if cost[i0] - cost[ib] > thr and second - cost[ib] > thr and abs(tb) > 0.15:
            H = np.zeros((1, NSTATE))
            H[0, IX], H[0, IY] = v[0], v[1]
            var = float(H @ self.P @ H.T)
            if var < sl * sl:  # weak-prior search: the filter was overconfident along v
                self.P[:2, :2] += (sl * sl - var) * np.outer(v, v)
            self._kalman(H, np.array([tb]), np.array([[0.08**2]]))
            self.ev += "S%+.1f " % tb
            self._gnss_forget()
            return "fix"
        if abs(tb) <= 0.15 and second - cost[ib] > thr:
            return "confirm"
        return None

    def _scan(self, r):
        self.scan_ok = False
        bx, by = self._scan_points(r)
        if len(bx) < 10:
            self.n_map = 0
            return
        if self.exit_check > 0:
            # longitudinal structure is back after a degenerate stretch: check the whole
            # +-4 m along the formerly blind axis with a weak prior, whatever P says
            self.exit_check -= 1
            if self.exit_check % 2 == 0:
                res = self._search_1d(
                    bx,
                    by,
                    v=self.degen_dir,
                    sl=max(1.5, self.sigma_pos()),
                    span=max(4.0, min(8.0, 3.0 * self.sigma_pos())),
                )
                if res == "reject":
                    self.ev += "Xr "
                elif res is not None:
                    self.exit_check = 0
                    self.ev += "X%s " % res[0]
        elif self.sigma_pos() > 0.35 and self.k % 2 == 0:
            self._search_1d(bx, by)
        xb = self.xs.copy()
        P = self.P
        P33 = P[:3, :3]
        P33inv = np.linalg.inv(P33)
        pb = xb[:3].copy()
        pi = pb.copy()
        sp = self.sigma_pos()
        gate = min(1.0, 0.5 + 2.0 * sp)
        if self.mm:
            # the scan disagrees with the map (unmapped fence or container along a wall): take
            # only points that lie on mapped walls, else an unmapped face inside the gate pulls
            # the pose across, a centimetre per tick (fence 0.7 m before T in fog: 0.7-0.9 m)
            gate = 0.2
        sig2 = 0.05**2 * 4.0  # per point, inflated for correlated errors
        clamp = self.field.clamp - 0.3
        Hs = None
        p_ok = None
        for _ in range(4):
            wx, wy, val, gx, gy = self._residuals(np.concatenate([pi, xb[3:]]), bx, by)
            av = np.abs(val)
            use = (av < gate) & (av < clamp)
            if np.count_nonzero(use) < 6:
                break  # keep the last good iteration
            vv = val[use]
            wt = np.where(np.abs(vv) < 0.08, 1.0, 0.08 / np.maximum(np.abs(vv), 1e-9)) / sig2
            gxu, gyu = gx[use], gy[use]
            jth = -gxu * (wy[use] - pi[1]) + gyu * (wx[use] - pi[0])
            J = np.stack([gxu, gyu, jth], axis=1)
            Jw = J * wt[:, None]
            Hi = J.T @ Jw
            gs = Jw.T @ vv
            d0 = pi - pb
            d0[2] = wrap(d0[2])
            delta = np.linalg.solve(P33inv + Hi, -P33inv @ d0 - gs)
            Hs = Hi
            pi = pi + delta
            pi[2] = wrap(pi[2])
            p_ok = pi.copy()
            if abs(delta[0]) + abs(delta[1]) < 1e-4 and abs(delta[2]) < 1e-5:
                break
        if Hs is not None:
            d = p_ok - pb
            d[2] = wrap(d[2])
            # NIS only over directions the scan observes: along a degenerate axis the solution is
            # set by the prior alone, and with a wide prior its step grows like P, so a full NIS
            # grows with every inflation (runaway seen: sigma 0.1 -> 1e7 m in 2 s)
            hw, hv = np.linalg.eigh(Hs[:2, :2])
            cols = [np.array([hv[0, i], hv[1, i], 0.0]) for i in range(2) if hw[i] > 200.0]
            obs = np.stack(cols + [np.array([0.0, 0.0, 1.0])], axis=1)
            do = obs.T @ d
            nis = float(do @ np.linalg.solve(obs.T @ P33 @ obs, do))
            if nis > 25.0:
                # the scan pulls far outside the prior: do not take it; widen the prior a few
                # times at most, never past 1 m (then only the monitors may move the pose)
                # and not at all while the scan disagrees with the map (unmapped fence or
                # container): widening the gate there only lets the fake wall in (lateral snap)
                if self.infl_run < 3 and self.sigma_pos() < 0.5 and not self.mm:
                    self.P[:3, :] *= 2.0
                    self.P[:, :3] *= 2.0
                    self.infl_run += 1
                    self.ev += "I "
                else:
                    self.ev += "R "
                self.scan_rej += 1
            else:
                self.infl_run = 0
                self.scan_rej = 0
                self.scan_ok = True
                # conditional update of the whole state; no inversion of the 7x7 P
                self.xs = xb + P[:, :3] @ (P33inv @ d)
                self.xs[ITH] = wrap(self.xs[ITH])
                M = np.linalg.solve(np.eye(3) + Hs @ P33, Hs @ P[:3, :])
                Pn = P - P[:, :3] @ M
                self.P = 0.5 * (Pn + Pn.T)
            self.last_Hxy = Hs[:2, :2].copy()
            lw, lv = np.linalg.eigh(Hs[:2, :2])
            if lw[0] < 200.0:
                self.degen_ticks += 1
                self.degen_dir = lv[:, 0]
            else:
                if self.degen_ticks >= 30:
                    self.exit_check = 20
                    self.ev += "DX "
                self.degen_ticks = 0
        _, _, val, _, _ = self._residuals(self.xs, bx, by)
        av = np.abs(val)
        nm = int(np.count_nonzero(av < clamp))
        self.n_map = nm
        self.inl_ratio = float(np.count_nonzero(av < 0.2)) / nm if nm else 1.0
        self.out_ratio = float(np.count_nonzero((av > 0.3) & (av < clamp))) / nm if nm else 0.0

    def _gnss_forget(self):
        """After any jump of the pose estimate old GNSS innovations mean nothing."""
        self.prev_raw = None
        self.last_good_inn = None
        self.rej = []

    def _gnss(self, g):
        if not g["valid"]:
            self.rej = []
            self.settle = 20
            self.prev_raw = None
            self.jump_until = -1.0
            self.gnss_hist = []
            return
        z = np.array([g["x"], g["y"]], dtype=float)
        H = np.zeros((2, NSTATE))
        H[0, IX] = H[1, IY] = 1.0
        H[0, IGX] = H[1, IGY] = 1.0
        nu = z - H @ self.xs
        R = np.eye(2) * (self.g_w**2 + 1e-6)
        S = H @ self.P @ H.T + R
        d2 = float(nu @ np.linalg.solve(S, nu))
        # a jump (3-8 m for 2-5 s) starts and ends within one tick: a step between neighbours
        if self.prev_raw is not None and float(np.hypot(*(nu - self.prev_raw))) > 2.0:
            if self.t < self.jump_until:
                self.jump_until = -1.0
            elif not (self.n_map >= 40 and self.inl_ratio < 0.4):
                # the scan still fits the map, so the step is on the GNSS side
                self.jump_until = self.t + 5.5
        self.prev_raw = nu
        hd = g["hdop"]
        jump = self.t < self.jump_until or (hd is not None and hd > 1.3)
        if not jump:
            self.gnss_hist.append(z - self.xs[IGX : IGY + 1])
            self.gnss_hist = self.gnss_hist[-20:]
        if self.settle > 0:
            self.settle -= 1
            if self.settle > 0:
                return
        if not jump and d2 < 13.8:
            self._kalman(H, nu, R)
            self.last_good_inn = nu
            self.rej = []
            return
        if not jump:
            self.rej.append(nu)
        if len(self.rej) >= 60:
            a = np.array(self.rej[-30:])
            m = a.mean(axis=0)
            u = m / max(float(np.hypot(*m)), 1e-9)
            seen = float(u @ self.last_Hxy @ u) > 200.0
            if a.std(axis=0).max() < 0.7 and not (self.n_map >= 40 and self.inl_ratio > 0.6 and seen):
                # steady disagreement, and the scan does not pin the pose in that direction
                self.xs[IX] += m[0]
                self.xs[IY] += m[1]
                self.P[:2, :] = 0.0
                self.P[:, :2] = 0.0
                self.P[IX, IX] = self.P[IY, IY] = 0.5**2
                self.infl_run = self.scan_rej = 0
                self._gnss_forget()
                self.ev += "G "
            self.rej = []

    def _edge(self, valid, dmove):
        """GNSS valid flag changed: the platform crossed a known shadow edge this tick."""
        if len(self.sh_edges) == 0:
            return
        x, y = self.xs[IX], self.xs[IY]
        E = self.sh_edges
        ex, ey = E[:, 2] - E[:, 0], E[:, 3] - E[:, 1]
        l2 = np.maximum(ex * ex + ey * ey, 1e-12)
        u = np.clip(((x - E[:, 0]) * ex + (y - E[:, 1]) * ey) / l2, 0.0, 1.0)
        qx, qy = E[:, 0] + u * ex, E[:, 1] + u * ey
        dist = np.hypot(qx - x, qy - y)
        lim = 2.0 + 3.0 * self.sigma_pos()
        mx, my = dmove
        dm = math.hypot(mx, my)
        if dm < 1e-4:
            return
        for i in np.argsort(dist):
            if dist[i] > lim:
                return
            L = math.sqrt(l2[i])
            n = np.array([-ey[i] / L, ex[i] / L])
            a = n[0] * mx + n[1] * my
            if abs(a) < 0.3 * dm:
                continue
            if a < 0:
                n, a = -n, -a
            # exactly one side of the edge must be in shadow
            ins = [
                any(
                    inside_mask(np.array([qx[i] + sg * 0.1 * n[0]]), np.array([qy[i] + sg * 0.1 * n[1]]), p)[0]
                    for p in self.shadows
                )
                for sg in (-1.0, 1.0)
            ]
            if ins[0] == ins[1]:
                continue
            if ins[1] != (not valid):  # entering must go into shadow, leaving out of it
                continue
            H = np.zeros((1, NSTATE))
            H[0, IX], H[0, IY] = n[0], n[1]
            h = n[0] * (x - E[i, 0]) + n[1] * (y - E[i, 1])
            y_ = 0.5 * a - h
            R = a * a / 12.0 + 0.03**2
            sh = math.sqrt(float(H @ self.P @ H.T))
            S = sh * sh + R
            # the crossing must fall inside this tick's own motion (an outage near an edge must not)
            if -3.0 * sh - 0.1 <= h <= a + 3.0 * sh + 0.1 and y_ * y_ / S < 9.0:
                self._kalman(H, np.array([y_]), np.array([[R]]))
                self.ev += "E%+.2f " % y_
            return

    # ----------------------------------------------------------------- lost
    def _csm_grid(self, px, py, cx, cy, offs):
        GX, GY = np.meshgrid(offs, offs)
        GX, GY = GX.ravel(), GY.ravel()
        WX = cx + GX[:, None] + px[None, :]
        WY = cy + GY[:, None] + py[None, :]
        val, _, _ = self.field.lookup(WX.ravel(), WY.ravel())
        val = val.reshape(WX.shape)
        return GX, GY, np.exp(-val * val / (2 * 0.15**2)).sum(axis=1)

    def _csm(self, r, center, win):
        """Correlative search: coarse 0.5 m grid, then 0.125 m around the best cell."""
        bx, by = self._scan_points(r)
        if len(bx) < 20:
            return None
        bx, by = bx[::3], by[::3]
        th0 = self.xs[ITH]
        best = None
        cur = 0.0
        win = 0.5 * math.ceil(win / 0.5)
        offs = np.arange(-win, win + 1e-9, 0.5)
        fine = np.arange(-0.5, 0.5 + 1e-9, 0.125)
        for dth in (-0.02, 0.0, 0.02):
            c, s = math.cos(th0 + dth), math.sin(th0 + dth)
            px = c * bx - s * by
            py = s * bx + c * by
            GX, GY, sc = self._csm_grid(px, py, center[0], center[1], offs)
            if dth == 0.0:
                cur = float(sc[int(np.argmin(np.hypot(GX, GY)))])
            i = int(np.argmax(sc))
            far = np.hypot(GX - GX[i], GY - GY[i]) > 1.0
            second = float(sc[far].max()) if far.any() else 0.0
            fx, fy = center[0] + GX[i], center[1] + GY[i]
            GX2, GY2, sc2 = self._csm_grid(px, py, fx, fy, fine)
            j = int(np.argmax(sc2))
            cand = (float(sc2[j]), second, fx + GX2[j], fy + GY2[j], wrap(th0 + dth), len(bx))
            if best is None or cand[0] > best[0]:
                best = cand
        return best + (cur,)

    def _prior_ok(self, dx, dy, floor=0.25):
        """A relocalization candidate must be plausible under the filter covariance
        (plus a floor for unmodelled effects): scan-only jumps alias on unmapped walls."""
        Pxy = self.P[:2, :2] + np.eye(2) * floor**2
        d = np.array([dx, dy])
        return float(d @ np.linalg.solve(Pxy, d)) < 16.0

    def _lost_monitor(self, r, g):
        bad = self.n_map >= 40 and self.inl_ratio < 0.4
        self.bad_hist.append(1 if bad else 0)
        self.bad_hist = self.bad_hist[-15:]
        mismatch = sum(self.bad_hist) >= 12
        if self.lost_cooldown > 0:
            self.lost_cooldown -= 1
        gnss_conflict = len(self.rej) >= 30
        if not self.lost:
            self.out_hist.append(1 if (self.n_map >= 30 and self.out_ratio > 0.3) else 0)
            self.out_hist = self.out_hist[-5:]
            if sum(self.out_hist) == 5 and self.k - self.last_csm >= 10:
                self.last_csm = self.k
                best = self._csm(r, (self.xs[IX], self.xs[IY]), max(2.0, min(6.0, 3.0 * self.sigma_pos())))
                if best is not None:
                    sc, second, bx_, by_, bth, npt, cur = best
                    dx, dy = bx_ - self.xs[IX], by_ - self.xs[IY]
                    if (
                        sc - cur > max(3.0, 0.15 * cur)
                        and sc - second > 0.1 * sc
                        and math.hypot(dx, dy) > 0.2
                        and self._prior_ok(dx, dy)
                    ):
                        H = np.zeros((2, NSTATE))
                        H[0, IX] = H[1, IY] = 1.0
                        self._kalman(H, np.array([dx, dy]), np.eye(2) * 0.1**2)
                        self._gnss_forget()
                        self.ev += "C%+.1f,%+.1f " % (dx, dy)
            if mismatch:
                # the scan disagrees with the map; that alone is a changed map, not a lost pose:
                # stop only if a second source doubts the pose too
                if (self.sigma_pos() > 0.5 or gnss_conflict or self.scan_rej >= 20) and self.lost_cooldown == 0:
                    self.lost = True
                    self.lost_ticks = 0
                    self.good_run = 0
                    self.ev += "LOST "
                elif not self.mm:
                    self.mm = True
                    self.ev += "MM "
            else:
                self.mm = False
            return
        self.lost_ticks += 1
        if self.n_map >= 40 and self.inl_ratio > 0.6:
            self.good_run += 1
            if self.good_run >= 3:
                self.lost = False
                self.bad_hist = []
                self.ev += "OK "
                return
        else:
            self.good_run = 0
        if self.lost_ticks % 5 == 1:
            win = min(6.0, max(2.0, 3.0 * self.sigma_pos()))
            best = self._csm(r, (self.xs[IX], self.xs[IY]), win)
            if best is not None:
                sc, second, bx_, by_, bth, npt, cur = best
                dx, dy = bx_ - self.xs[IX], by_ - self.xs[IY]
                if sc > 0.5 * npt and sc - second > 0.1 * sc and sc > cur and self._prior_ok(dx, dy, 0.5):
                    self.xs[IX], self.xs[IY], self.xs[ITH] = bx_, by_, bth
                    self.P[:3, :] = 0.0
                    self.P[:, :3] = 0.0
                    self.P[IX, IX] = self.P[IY, IY] = 0.15**2
                    self.infl_run = self.scan_rej = 0
                    self.P[ITH, ITH] = 0.01**2
                    self._gnss_forget()
                    self.ev += "CSM "
                    self.lost = False
                    self.bad_hist = []
                    return
        if self.lost_ticks > 50 and g["valid"] and len(self.gnss_hist) >= 10:
            m = np.mean(self.gnss_hist[-10:], axis=0)  # clean fixes, GNSS bias removed
            self.xs[IX], self.xs[IY] = m[0], m[1]
            self.P[:2, :] = 0.0
            self.P[:, :2] = 0.0
            self.P[IX, IX] = self.P[IY, IY] = 1.0
            self.infl_run = self.scan_rej = 0
            self.lost = False
            self.bad_hist = []
            self.lost_cooldown = 150
            self._gnss_forget()
            self.ev += "GREL "
        elif self.lost_ticks > 100:
            self.P[:2, :2] += np.eye(2) * 1.0
            self.infl_run = self.scan_rej = 0
            self.lost = False
            self.bad_hist = []
            self.lost_cooldown = 150  # drive on as "map mismatch" instead of a stop-go loop
            self.ev += "GIVEUP "

    # ------------------------------------------------------------------ step
    def update(self, obs, cmd):
        """cmd = (v, w, estop) sent on the previous tick."""
        self.ev = ""
        self.t = float(obs.get("t", self.t + self.dt))
        r = np.asarray(obs["lidar"]["ranges"], dtype=float)
        od = obs["odom"]
        self._snow_update(r)
        v_cmd, w_cmd, estop = cmd
        p = self.rb
        vt = min(max(float(v_cmd), p["v_min"]), p["v_max"])
        wt = min(max(float(w_cmd), -p["w_max"]), p["w_max"])
        vn = speed_law(self.vw, vt, bool(estop), self.rb, self.dt)
        va = 0.5 * (self.vw + vn)
        self.vw = vn
        half = 0.5 * wt * self.dt
        m_dx, m_dy, m_dth = va * self.dt * math.cos(half), va * self.dt * math.sin(half), wt * self.dt
        # NaN means "unknown": a broken odometry reading is replaced by the model of own commands
        # for the prediction and never taken as a scale measurement; a broken heading is skipped
        od_ok = all(math.isfinite(od[k]) for k in ("dx", "dy", "dtheta"))
        from_odom = not self.use_model and od_ok
        if not from_odom:
            dx, dy, dth = m_dx, m_dy, m_dth
        else:
            k = 1.0 / (1.0 + self.xs[IS])
            dx, dy, dth = od["dx"] * k, od["dy"] * k, od["dtheta"]
        self.blocked_prev = self.blocked
        self.blocked = False
        if self.prev_r is not None:
            self.stall_llr = self._stall_llr(self.prev_r, r, dx, dy, dth)
            # a stall needs a contact: the scan-to-scan test alone is fooled by people walking
            # along with the platform (corridor walls carry no evidence either way) and is blind
            # below 0.25 m/s (per-tick shift under its 25 mm mask); the bumper test covers both.
            # The scan test keeps a veto: a clear "moved" overrides a grazing contact.
            touch = self._touch(r, dx, dy, self.blocked_prev)
            if touch and self.stall_llr > -20.0:
                self.blocked = True
                dx = dy = 0.0
        c0, s0 = math.cos(self.xs[ITH]), math.sin(self.xs[ITH])
        pmove = (c0 * dx - s0 * dy, s0 * dx + c0 * dy)
        self.last_dth = dth
        self.last_ds = math.hypot(dx, dy)
        x_prev, y_prev = float(self.xs[IX]), float(self.xs[IY])
        self._predict(dx, dy, dth, from_odom)
        if (self.use_model or self.scale_from_cmd) and od_ok:
            # FALLBACK+cal: the pose is still predicted from odometry, only its scale is
            # calibrated against the commanded motion (unobservable otherwise when blind from the
            # start: fog + shadow from a dock, red team rt_n_fog*)
            self._odom_scale(od, m_dx, abs(va) * self.dt)
        if math.isfinite(obs["imu"]["heading"]):
            self._imu(obs["imu"])
        self._scan(r)
        g = obs["gnss"]
        self._gnss(g)
        valid = bool(g["valid"])
        if self.prev_valid is not None and valid != self.prev_valid:
            self._edge(valid, pmove)
        self.prev_valid = valid
        self._lost_monitor(r, g)
        anchored = self.scan_ok and float(np.linalg.eigvalsh(self.last_Hxy)[0]) > self.smon.anchor_eig
        th = self.xs[ITH]
        travel = math.cos(th) * (self.xs[IX] - x_prev) + math.sin(th) * (self.xs[IY] - y_prev)
        if od_ok:
            self.smon.update(float(od["dx"]), float(travel), anchored, self.blocked)
        self.prev_r = r
        self.k += 1

    def diag(self):
        sm = self.smon.s
        return "b%d k%.0f l%d s%+.4f m%s sp%.2f in%.2f n%d %s" % (
            int(self.blocked),
            self.stall_llr,
            int(self.lost),
            self.xs[IS],
            "%+.4f" % sm if sm is not None else "-",
            self.sigma_pos(),
            self.inl_ratio,
            self.n_map,
            self.ev.strip(),
        )
