import math
import unittest

import config_team as cfg
from tests.fixtures import CONFIG, MAP, PATH_WA
from follow import Follower
from motion import speed_law
from geometry import DistanceField, map_bounds
from planner import Planner

import numpy as np

RB = CONFIG["robot"]
DT = CONFIG["dt"]


class SpeedLawTest(unittest.TestCase):
    def test_accelerate(self):
        self.assertAlmostEqual(speed_law(0.0, 1.39, False, RB, DT), 0.05)
        self.assertAlmostEqual(speed_law(1.36, 1.39, False, RB, DT), 1.39)

    def test_brake(self):
        self.assertAlmostEqual(speed_law(1.0, 0.0, False, RB, DT), 0.88)
        self.assertEqual(speed_law(0.1, 0.0, False, RB, DT), 0.0)  # exact zero

    def test_estop(self):
        self.assertAlmostEqual(speed_law(1.0, 1.0, True, RB, DT), 0.75)

    def test_reversal_passes_zero_first(self):
        self.assertAlmostEqual(speed_law(0.5, -0.3, False, RB, DT), 0.38)
        self.assertEqual(speed_law(0.05, -0.3, False, RB, DT), 0.0)
        self.assertAlmostEqual(speed_law(0.0, -0.3, False, RB, DT), -0.05)

    def test_stop_from_top_speed_takes_twelve_ticks(self):
        v, n = 1.39, 0
        while v > 0:
            v = speed_law(v, 0.0, False, RB, DT)
            n += 1
        self.assertEqual(n, 12)


class ProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        polys = [np.asarray(b["polygon"], dtype=float) for b in MAP["buildings"]]
        cls.field = DistanceField(polys, map_bounds(MAP, polys))

    def setUp(self):
        self.pl = Planner(MAP, CONFIG, self.field)
        self.path = self.pl.set_path(PATH_WA, 0.5, 10.0, True)

    def test_zone_allowance(self):
        v, zone = self.pl.speed_limit(35.0 - 0.5, 35.0, 10.0, 0.0)
        self.assertAlmostEqual(v, 0.8 + cfg.ZONE_ALLOWANCE)
        self.assertAlmostEqual(zone, 0.8 + cfg.ZONE_ALLOWANCE)
        self.assertLess(v, 0.8 + 0.05)

    def test_brakes_before_the_zone(self):
        vz = 0.8 + cfg.ZONE_ALLOWANCE
        far, _ = self.pl.speed_limit(10.0, 10.5, 10.0, 0.0)
        self.assertEqual(far, CONFIG["robot"]["v_max"])
        near, zone = self.pl.speed_limit(28.5, 29.0, 10.0, 0.0)  # 1 m before the border
        self.assertLess(near, CONFIG["robot"]["v_max"])
        self.assertGreater(near, vz)
        # never above what braking at ZONE_DECEL allows with the margin
        d = 30.0 - 29.0 - cfg.ZONE_MARGIN
        self.assertLessEqual(near, math.sqrt(vz * vz + 2 * cfg.ZONE_DECEL * max(0.0, d)) + 0.05)

    def test_speed_after_braking_is_legal_at_the_border(self):
        # drive the braking profile tick by tick: the speed at the zone border is within the rule
        x, v = 20.0, 1.39
        while x < 30.0:
            lim, _ = self.pl.speed_limit(x - 0.5, x, 10.0, 0.0)
            v = speed_law(v, lim, False, RB, DT)
            x += v * DT
        self.assertLessEqual(v, 0.8 + 0.05)

    def test_dock_profile(self):
        v, _ = self.pl.speed_limit(self.path.length - 1.0, 58.5, 10.0, 0.0)
        self.assertAlmostEqual(v, math.sqrt(2 * cfg.DOCK_DECEL * (1.0 - cfg.DOCK_STOP_OFFSET)) + cfg.DOCK_CREEP)

    def test_dock_approach_stops_inside_tolerance(self):
        f = Follower(CONFIG)
        path = self.pl.set_path(PATH_WA, 50.0, 10.0, True)
        x, v, stopped = 50.0, 1.39, False
        for _ in range(400):
            s = path.project(x, 10.0)
            lim, _ = self.pl.speed_limit(s, x, 10.0, 0.0)
            c = f.command(path, s, x, 10.0, 0.0, v, lim, True)
            vn = speed_law(v, c.v, False, RB, DT)
            x += 0.5 * (v + vn) * DT
            v = vn
            if c.mode == "stop" and v == 0.0:
                stopped = True
                break
        self.assertTrue(stopped)
        self.assertLess(abs(x - 59.5), cfg.ARRIVE_DIST)

    def test_reverse_after_overshoot(self):
        f = Follower(CONFIG)
        path = self.pl.set_path(PATH_WA, 58.0, 10.0, True)
        c = f.command(path, path.project(59.9, 10.0), 59.9, 10.0, 0.0, 0.0, 1.39, True)
        self.assertEqual(c.mode, "reverse")
        self.assertLess(c.v, 0.0)
        self.assertGreaterEqual(c.v, -cfg.REVERSE_V)

    def test_rotate_in_place_when_facing_away(self):
        f = Follower(CONFIG)
        path = self.pl.set_path(PATH_WA, 10.0, 10.0, True)
        c = f.command(path, path.project(10.0, 10.0), 10.0, 10.0, math.pi, 0.0, 1.39, True)
        self.assertEqual(c.mode, "rotate")
        self.assertEqual(c.v, 0.0)
        self.assertLessEqual(abs(c.w), CONFIG["robot"]["w_max"])


class RouteTest(unittest.TestCase):
    def test_route_to_pickup(self):
        polys = [np.asarray(b["polygon"], dtype=float) for b in MAP["buildings"]]
        pl = Planner(MAP, CONFIG, DistanceField(polys, map_bounds(MAP, polys)))
        pts = pl.route_to(40.0, 10.0, 0.5, 10.0, 1.0)
        self.assertIsNotNone(pts)
        self.assertEqual(pts[0], (40.0, 10.0))
        self.assertEqual(pts[-1], (0.5, 10.0))
        for x, y in pts[1:-1]:
            self.assertGreaterEqual(pl.field.value(x, y), cfg.GRID_CLEARANCE - 0.1)


class DockLoopTest(unittest.TestCase):
    """Review M1: an estimate off the heading line in the last 0.3 m must not loop forever."""

    @classmethod
    def setUpClass(cls):
        polys = [np.asarray(b["polygon"], dtype=float) for b in MAP["buildings"]]
        cls.field = DistanceField(polys, map_bounds(MAP, polys))

    def drive(self, x, lat, th, v):
        pl, fo = Planner(MAP, CONFIG, self.field), Follower(CONFIG)
        y = 10.0 + lat
        path = pl.set_path(PATH_WA, x, y, True)
        for k in range(600):
            s = path.project(x, y)
            lim, _ = pl.speed_limit(s, x, y, 0.03)
            c = fo.command(path, s, x, y, th, v, lim, True, pl.target)
            if c.mode == "stop" and v == 0.0:
                return k, math.hypot(x - 59.5, y - 10.0)
            vn = speed_law(v, c.v, False, RB, DT)
            va = 0.5 * (v + vn)
            v = vn
            w = max(-1.0, min(1.0, c.w))
            x += va * DT * math.cos(th + 0.5 * w * DT)
            y += va * DT * math.sin(th + 0.5 * w * DT)
            th += w * DT
        return None, math.hypot(x - 59.5, y - 10.0)

    def test_every_start_near_the_dock_ends_stopped_inside_tolerance(self):
        for x in (58.5, 59.2, 59.3, 59.6):
            for lat in (-0.25, -0.16, 0.0, 0.13, 0.2):
                for th in (-0.3, -0.1, 0.0, 0.1, 0.3):
                    k, d = self.drive(x, lat, th, 0.0)
                    self.assertIsNotNone(k, (x, lat, th))
                    self.assertLess(d, cfg.ARRIVE_DIST, (x, lat, th))
