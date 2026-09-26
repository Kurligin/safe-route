"""Controller of the delivery platform. The per-tick pipeline:

    Localizer.update(obs, previous command) -> pose, sigma, flags
    Perception.update(pose)                 -> unexplained clusters, tracks
    Mission.update(mission, pose)           -> phase, target
    Planner (path, speed profile)           -> path, speed limit
    Follower.command(...)                   -> desired v, w
    Safety.limit(...)                       -> final v, w, reason
    answer {v, w, status, pose_est, note}

The status comes from the own speed model (speed law from config): "moving" while
the speed at the start or at the end of the tick is above 0.05 m/s; "waiting" and
"lost" only at rest. Any exception inside the pipeline gives a safe stop for the tick."""

import math
import sys
import traceback

import numpy as np

import config_team as cfg
from follow import Follower
from motion import speed_law
from geometry import DistanceField, map_bounds
from localization import Localizer
from mission import DONE, TO_PICKUP, Mission
from perception import Perception
from planner import Planner
from safety import PEOPLE_STOPS, Safety

STATUSES = ("moving", "arrived", "waiting", "lost", "estop")


def _num(x, lo: float, hi: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return min(hi, max(lo, x)) if math.isfinite(x) else 0.0


class Controller:
    def __init__(self, map_, config, initial_pose):
        polys = [np.asarray(b["polygon"], dtype=float) for b in map_["buildings"]]
        self.field = DistanceField(polys, map_bounds(map_, polys), 0.1, 3.0)
        self.loc = Localizer(
            map_,
            config,
            initial_pose,
            use_model=cfg.LOC_MODE == "model",
            scale_from_cmd=cfg.SCALE_FROM_CMD,
            field=self.field,
        )
        self.perception = Perception(map_, config)
        self.mission = Mission(map_, config)
        self.planner = Planner(map_, config, self.field)
        self.follower = Follower(config)
        self.safety = Safety(config, self.field)
        self.rb = config["robot"]
        self.dt = float(config["dt"])
        self.v_lo, self.v_hi, self.w_hi = float(self.rb["v_min"]), float(self.rb["v_max"]), float(self.rb["w_max"])
        self.pose = [float(a) for a in initial_pose]
        self.path = None
        self.last_cmd = (0.0, 0.0, False)
        self.beams = int(config["lidar"]["beams"])
        self.errors = 0

    def step(self, obs):
        try:
            v, w, status, note = self._step(obs)
        except Exception:
            self.errors += 1
            if self.errors <= cfg.MAX_TRACES:
                traceback.print_exc(file=sys.stderr)
            elif self.errors % 1000 == 0:
                print("step errors: %d" % self.errors, file=sys.stderr)
            # forget the scan of the broken tick, so the next one starts clean
            self.loc.prev_r = None
            # a platform still rolling reports "moving" (the status rule looks at the true speed)
            vw = float(self.loc.vw) if math.isfinite(self.loc.vw) else 0.0
            v, w, note = 0.0, 0.0, "err"
            status = "moving" if abs(vw) > cfg.STATUS_MOVING_V else "waiting"
        v = _num(v, self.v_lo, self.v_hi)
        w = _num(w, -self.w_hi, self.w_hi)
        if status not in STATUSES:
            status = "waiting"
        self.last_cmd = (v, w, status == "estop")
        pose = [_num(a, -1e6, 1e6) for a in self.pose]
        return {"v": v, "w": w, "status": status, "pose_est": pose, "note": str(note)[:200]}

    # ------------------------------------------------------------------ pipeline
    @staticmethod
    def _finite(x) -> bool:
        return isinstance(x, (int, float)) and math.isfinite(x)

    def _sanitize(self, obs):
        """Bring the observation to the expected shape. Values the filter must treat as unknown (NaN
        in odometry or heading, a GNSS fix without coordinates) are left to the Localizer, which skips
        them instead of taking them as measurements."""
        obs = dict(obs)
        r = obs.get("lidar") or {}
        ranges = r.get("ranges") if isinstance(r, dict) else None
        try:
            ranges = np.asarray(ranges, dtype=float)
        except (TypeError, ValueError):
            ranges = None
        if ranges is None or ranges.shape != (self.beams,):
            ranges = np.full(self.beams, np.nan)
        obs["lidar"] = {"ranges": ranges}
        od = obs.get("odom") or {}
        obs["odom"] = {k: float(od[k]) if self._number(od.get(k)) else math.nan for k in ("dx", "dy", "dtheta")}
        imu = obs.get("imu") or {}
        obs["imu"] = {"heading": float(imu["heading"]) if self._number(imu.get("heading")) else math.nan}
        g = obs.get("gnss") or {}
        if g.get("valid") and self._finite(g.get("x")) and self._finite(g.get("y")):
            hd = g.get("hdop")
            obs["gnss"] = {
                "x": float(g["x"]),
                "y": float(g["y"]),
                "valid": True,
                "hdop": hd if self._finite(hd) else None,
            }
        else:
            obs["gnss"] = {"x": None, "y": None, "valid": False, "hdop": None}
        if not self._finite(obs.get("t")):
            obs["t"] = self.loc.t + self.dt
        return obs

    @staticmethod
    def _number(x) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def _step(self, obs):
        obs = self._sanitize(obs)
        self.perception.odometry(obs)
        self.loc.update(obs, self.last_cmd)
        x, y, th = self.loc.pose()
        self.pose = [x, y, th]
        sigma = self.loc.sigma_pos()
        per = self.perception.update((x, y, th), min(10.0, 3.0 * sigma))
        v, w, stop, codes = self._drive(obs.get("mission"), per, x, y, th, sigma)
        v_model = float(self.loc.vw)
        if codes == "arrived":
            return 0.0, 0.0, "arrived", self._note(["dock"])
        if self.loc.lost:
            v, w, stop = 0.0, 0.0, "lost"
            codes = ["lost"]
        if self.safety.estop and abs(v_model) > cfg.STATUS_MOVING_V:
            return 0.0, 0.0, "estop", self._note(codes)
        # the rule looks at the speed at the start of the tick, the platform moves with the next
        # one: "moving" while either is above the threshold
        v_next = speed_law(v_model, _num(v, self.v_lo, self.v_hi), False, self.rb, self.dt)
        if max(abs(v_model), abs(v_next)) > cfg.STATUS_MOVING_V:
            status = "moving"
        elif stop == "lost":
            status = "lost"
        elif stop:
            status = "waiting"
        else:
            status = "moving"
        return v, w, status, self._note(codes)

    def _drive(self, m, per, x, y, th, sigma):
        """Returns (v, w, stop reason, note codes) or codes == "arrived"."""
        mv = self.mission.update(m, x, y, sigma)
        if mv.phase == DONE:
            return 0.0, 0.0, "", []
        if mv.new_phase or self.path is None:
            self._set_path(mv, x, y)
        if self.mission.check_arrival(x, y, sigma, float(self.loc.vw) == 0.0):
            return 0.0, 0.0, "", "arrived"
        s = self.path.project(x, y)
        pl = self.planner
        pl.bypass.update(per.static, x, y, th, s)
        v_lim, zone_v = pl.speed_limit(s, x, y, sigma)
        vm = float(self.loc.vw)
        cmd = self.follower.command(self.path, s, x, y, th, vm, v_lim, True, pl.target)
        track, ss = pl.track_ahead(x, y, th, s, cfg.TRACK_AHEAD)
        vd = self.safety.limit(per, cmd.v, cmd.w, cmd.remaining, track, ss, vm, (x, y, th))
        codes = []
        if vd.estop:
            codes.append("estop:object")
        elif vd.stop:
            codes.append("wait:person" if vd.stop in PEOPLE_STOPS else "wait:object")
        elif vd.slow:
            codes.append("slow:person")
        elif vd.clearance:
            codes.append("slow:object")
        if pl.bypass.active() and abs(float(pl.bypass.offset_at(np.array([s]))[0])) > 0.05:
            codes.append("bypass:object")
        if mv.phase == TO_PICKUP:
            codes.append("pickup")
        elif cmd.mode in ("dock", "reverse", "backoff", "stop"):
            codes.append("dock")
        if zone_v is not None and not vd.stop and abs(vd.v - v_lim) < 1e-9:
            codes.append("zone:%.2f" % zone_v)
        if self.loc.mm:
            codes.append("mismatch:map")
        return vd.v, vd.w, vd.stop, codes

    def _set_path(self, mv, x, y):
        if mv.phase == TO_PICKUP:
            fx, fy = mv.pickup
            pts = self.planner.route_to(x, y, fx, fy, max(0.5, self.mission.pickup_reach(0.0) - 0.5))
            if pts is None:
                pts = [(x, y), (fx, fy)]
        else:
            pts = mv.reference_path
        self.path = self.planner.set_path(pts, x, y, True)
        self.follower.reset()

    def _note(self, codes) -> str:
        note = " ".join(codes)
        if cfg.NOTE_DEBUG:
            note = "%s|%s" % (note, self.loc.diag())
        return note
