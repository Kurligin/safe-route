"""Rules for people and objects on synthetic clusters (robot frame: x forward, y left)."""

import unittest

import numpy as np

import config_team as cfg
from perception import Percept, Person, Track
from safety import PEOPLE_STOPS, STOP_AHEAD, STOP_GUARD, STOP_OBJECT, STOP_YIELD, Safety
from tests.fixtures import CONFIG

NAN = np.full(360, np.nan)


def straight_track(length=6.0):
    ss = np.arange(0.0, length + 1e-6, 0.1)
    return np.stack([ss, np.zeros_like(ss)], axis=1), ss


def person(cx, cy, vx=0.0, vy=0.0, ever=True, young=False, width=0.5):
    tr = Track(0.0, 0.0)
    tr.ever = ever
    tr.dyn = True if ever else None
    tr.width = width
    sp = float(np.hypot(vx, vy))
    gap = float(np.hypot(cx, cy)) - 0.9 - 0.3
    return Person((cx, cy), (vx, vy) if sp > 0.3 else (0.0, 0.0), sp, gap, tr, young)


def cluster(cx, cy, n=5, dyn=None, r=0.25):
    a = np.linspace(-1.0, 1.0, n)
    pts = np.stack([cx - r * np.cos(a), cy + r * np.sin(a)], axis=1)
    tr = Track(cx, cy)
    tr.dyn = dyn
    return pts, tr


class ForecastTest(unittest.TestCase):
    def setUp(self):
        self.s = Safety(CONFIG)
        self.track, self.ss = straight_track()

    def lim(self, ppl, v0=1.39):
        return self.s.forecast_limit(ppl, self.track, self.ss, v0)

    def test_nobody_full_speed(self):
        self.assertEqual(self.lim([]), CONFIG["robot"]["v_max"])

    def test_person_far_ahead_does_not_limit(self):
        self.assertEqual(self.lim([person(25.0, 0.0)]), CONFIG["robot"]["v_max"])

    def test_person_walking_at_us_stops_or_crawls(self):
        # 2.8 m gap and closing: faster than the crawl breaks the 3 m rule at once
        v = self.lim([person(4.0, 0.0, vx=-1.2)], v0=1.0)
        self.assertLessEqual(v, cfg.CRAWL)

    def test_far_walker_at_us_allows_going_on_with_a_stop_later(self):
        # the forecast is redone every tick: going on now is fine while stopping later stays possible
        v = self.lim([person(9.0, 0.0, vx=-1.2)], v0=0.3)
        self.assertGreater(v, cfg.CRAWL)

    def test_person_crossing_close_ahead_limits(self):
        v = self.lim([person(4.0, 3.0, vy=-1.0)])
        self.assertLess(v, CONFIG["robot"]["v_max"])

    def test_person_behind_walking_away_does_not_limit(self):
        self.assertEqual(self.lim([person(-5.0, 0.0, vx=-1.2)]), CONFIG["robot"]["v_max"])

    def test_close_person_means_zero_or_crawl(self):
        # 0.6 m gap ahead: moving at all breaks the 0.5 m + margin rule
        self.assertEqual(self.lim([person(1.8, 0.0)], v0=0.0), 0.0)

    def test_young_track_assumed_to_approach(self):
        still = self.lim([person(7.0, 0.0, ever=False)], v0=1.39)
        young = self.lim([person(7.0, 0.0, ever=False, young=True)], v0=1.39)
        self.assertLessEqual(young, still)

    def test_candidate_never_below_zero(self):
        for p in ([person(3.0, 0.5)], [person(10.0, -3.0, vy=1.4)]):
            self.assertGreaterEqual(self.lim(p), 0.0)


class YieldTest(unittest.TestCase):
    def setUp(self):
        self.s = Safety(CONFIG)

    def test_standing_person_seen_walking_in_front(self):
        self.assertTrue(self.s.yield_rule([person(3.5, 0.5)]))

    def test_standing_blob_never_seen_walking_is_ignored(self):
        self.assertFalse(self.s.yield_rule([person(3.5, 0.5, ever=False)]))

    def test_standing_person_behind_is_ignored(self):
        self.assertFalse(self.s.yield_rule([person(-2.0, 0.0)]))

    def test_walking_towards_us(self):
        self.assertTrue(self.s.yield_rule([person(3.0, 1.0, vx=-1.0, vy=-0.2)]))

    def test_walking_away(self):
        self.assertFalse(self.s.yield_rule([person(3.0, 1.0, vx=1.0)]))

    def test_yield_is_bounded(self):
        p = person(3.5, 0.0)
        got = [self.s.yield_rule([p]) for _ in range(cfg.YIELD_MAX_TICKS + 5)]
        self.assertTrue(got[0])
        self.assertFalse(got[-1])

    def test_limit_stops_at_exact_zero(self):
        per = Percept(NAN, 0.0, people=[person(3.5, 0.0)])
        track, ss = straight_track()
        vd = self.s.limit(per, 1.0, 0.3, 50.0, track, ss, 0.0)
        self.assertEqual(vd.v, 0.0)
        self.assertEqual(vd.stop, STOP_YIELD)
        self.assertEqual(vd.w, 0.3)  # standing: the turn on the spot goes on


class ObjectsTest(unittest.TestCase):
    def setUp(self):
        self.s = Safety(CONFIG)
        self.track, self.ss = straight_track()

    def test_object_on_track_stops(self):
        pts, tr = cluster(1.8, 0.2, dyn=False)
        per = Percept(NAN, 0.5, found=[(pts, tr)], clusters=[(pts, tr)], static=pts)
        vd = self.s.limit(per, 1.0, 0.0, 50.0, self.track, self.ss, 0.5)
        self.assertEqual((vd.v, vd.stop), (0.0, STOP_AHEAD))

    def test_object_beside_track_passes_with_clearance_cap(self):
        pts, tr = cluster(1.5, 1.35, dyn=False)  # gap to the body ~0.2 m sideways
        per = Percept(NAN, 0.5, found=[(pts, tr)], clusters=[(pts, tr)], static=pts)
        vd = self.s.limit(per, 1.0, 0.0, 50.0, self.track, self.ss, 0.5)
        self.assertEqual(vd.stop, "")
        self.assertTrue(vd.clearance)
        self.assertLessEqual(vd.v, cfg.CLEARANCE_V)

    def test_start_guard(self):
        pts, tr = cluster(1.4, 0.9, dyn=None)  # unknown cluster 0.5 m from the body
        per = Percept(NAN, 0.0, clusters=[(pts, tr)])
        vd = self.s.limit(per, 0.5, 0.0, 50.0, self.track, self.ss, 0.0)
        self.assertEqual((vd.v, vd.stop), (0.0, STOP_GUARD))
        tr.dyn = False  # a known object does not hold the start
        self.s = Safety(CONFIG)
        vd = self.s.limit(per, 0.5, 0.0, 50.0, self.track, self.ss, 0.0)
        self.assertNotEqual(vd.stop, STOP_GUARD)

    def test_people_stop_holds_up_to_the_goal(self):
        per = Percept(NAN, 0.0, people=[person(1.8, 0.0)])
        vd = self.s.limit(per, 0.2, 0.0, 0.1, self.track, self.ss, 0.0)
        self.assertEqual(vd.v, 0.0)
        self.assertIn(vd.stop, PEOPLE_STOPS)

    def test_person_in_the_corridor_near_the_goal_still_stops(self):
        # review C1: the person is also a confirmed cluster in the corridor; in the last 0.3 m
        # the corridor stop is lifted, the people stop must not be
        pts, tr = cluster(1.35, 0.0, dyn=True)
        p = person(1.35 + 0.3, 0.0)
        per = Percept(NAN, 0.0, found=[(pts, tr)], clusters=[(pts, tr)], people=[p])
        vd = self.s.limit(per, 0.7, 0.0, 0.25, self.track, self.ss, 0.0)
        self.assertEqual(vd.v, 0.0)
        self.assertIn(vd.stop, PEOPLE_STOPS)

    def test_corridor_stop_is_lifted_in_the_dock_only_for_objects(self):
        pts, tr = cluster(1.8, 0.0, dyn=False)
        per = Percept(NAN, 0.3, found=[(pts, tr)], clusters=[(pts, tr)], static=pts)
        self.assertEqual(self.s.limit(per, 0.3, 0.0, 0.25, self.track, self.ss, 0.3).v, 0.3)
        self.assertEqual(self.s.limit(per, 0.3, 0.0, 1.0, self.track, self.ss, 0.3).v, 0.0)

    def test_new_object_stop_is_not_a_person(self):
        per = Percept(NAN, 0.0, people=[person(1.8, 0.0, ever=False, young=True)])
        vd = self.s.limit(per, 0.5, 0.0, 50.0, self.track, self.ss, 0.0)
        self.assertEqual((vd.v, vd.stop), (0.0, STOP_OBJECT))

    def test_no_backing_up_with_a_person_behind(self):
        per = Percept(NAN, 0.0, people=[person(-2.5, 0.0, ever=False)])
        vd = self.s.limit(per, -0.3, 0.0, 0.5, self.track, self.ss, 0.0)
        self.assertEqual(vd.v, 0.0)


class EstopTest(unittest.TestCase):
    def setUp(self):
        self.s = Safety(CONFIG)
        self.track, self.ss = straight_track()

    def per(self, x, v):
        pts, tr = cluster(x, 0.0, dyn=None)
        tr.conf = 5  # confirmed for a while
        r = NAN.copy()
        k = np.round(np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))).astype(int) % 360
        r[k] = np.hypot(pts[:, 0], pts[:, 1])
        return Percept(r, v, found=[(pts, tr)], clusters=[(pts, tr)], static=pts)

    def limit(self, per, v, remaining=50.0, v_model=None):
        """Two ticks with the same scan (the estop needs a confirmation on the previous scan)."""
        vm = per.v_odom if v_model is None else v_model
        self.s.limit(per, v, 0.0, remaining, self.track, self.ss, vm)
        return self.s.limit(per, v, 0.0, remaining, self.track, self.ss, vm)

    def test_sudden_object_at_speed(self):
        # 0.8 m gap at 1.39 m/s: normal braking needs ~0.9 m
        vd = self.limit(self.per(0.9 + 0.8 + 0.25, 1.39), 1.39)
        self.assertTrue(vd.estop)
        self.assertEqual((vd.v, vd.w), (0.0, 0.0))

    def test_normal_braking_is_enough(self):
        # 1.0 m gap at 0.6 m/s: the corridor stop brakes normally (~0.2 m), no estop
        vd = self.limit(self.per(0.9 + 1.0 + 0.25, 0.6), 0.6)
        self.assertEqual((vd.v, vd.stop), (0.0, STOP_AHEAD))
        self.assertFalse(vd.estop)

    def test_estop_released_at_rest(self):
        p = self.per(0.9 + 0.8 + 0.25, 1.39)
        self.assertTrue(self.limit(p, 1.39).estop)
        p.v_odom = 0.0
        self.assertFalse(self.s.limit(p, 1.0, 0.0, 50.0, self.track, self.ss, 0.0).estop)

    def test_no_estop_for_a_person(self):
        # raw returns of a person in the footprint are not an object
        r = NAN.copy()
        r[358:360] = 1.5
        r[0:3] = 1.5
        per = Percept(r, 1.39, people=[person(1.8, 0.0)])
        vd = self.limit(per, 1.39)
        self.assertFalse(vd.estop)
        self.assertEqual(vd.v, 0.0)

    def test_returns_inside_the_body_are_no_estop(self):
        # closer to the lidar than the radius: snow, nothing real
        self.assertFalse(self.limit(self.per(0.6, 1.39), 1.39).estop)


class SurfaceTest(unittest.TestCase):
    def test_raw_surface_triggers_estop_scattered_returns_do_not(self):
        s = Safety(CONFIG)
        track, ss = straight_track()
        r = NAN.copy()
        r[358:360] = 1.75
        r[0:3] = 1.75  # a flat face 0.85 m ahead of the body
        self.assertTrue(s.limit(Percept(r, 1.39), 1.39, 0.0, 50.0, track, ss, 1.39).estop)
        s = Safety(CONFIG)
        r2 = NAN.copy()
        r2[0:3] = (1.2, 1.75, 2.4)  # snow: independent ranges on adjacent beams
        vd = s.limit(Percept(r2, 1.39), 1.39, 0.0, 50.0, track, ss, 1.39)
        self.assertFalse(vd.estop)
