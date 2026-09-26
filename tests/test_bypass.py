"""Bypass of an object next to the path axis (planner, synthetic static points)."""

import unittest

import numpy as np

import config_team as cfg
from geometry import DistanceField, map_bounds
from planner import Planner
from tests.fixtures import CONFIG, MAP, PATH_WA


class BypassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        polys = [np.asarray(b["polygon"], dtype=float) for b in MAP["buildings"]]
        cls.field = DistanceField(polys, map_bounds(MAP, polys))

    def setUp(self):
        self.pl = Planner(MAP, CONFIG, self.field)
        self.pl.set_path(PATH_WA, 10.0, 10.0, True)

    @staticmethod
    def pallet(x, y, r=0.45):
        a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
        return np.stack([x + r * np.cos(a), y + r * np.sin(a)], axis=1)

    def feed(self, world, x=10.0, y=10.0):
        # robot at (x, y) heading east: robot frame = world shifted
        self.pl.bypass.update(world - np.array([x, y]), x, y, 0.0, self.pl.path.project(x, y))

    def test_no_object_no_offset(self):
        self.feed(np.empty((0, 2)))
        self.assertFalse(self.pl.bypass.active())

    def test_far_from_axis_no_offset(self):
        self.feed(self.pallet(18.0, 12.2))  # 2.2 m off the axis
        self.assertFalse(self.pl.bypass.active())

    def test_pallet_on_axis_offset_clears_it(self):
        pal = self.pallet(18.0, 10.6)
        self.feed(pal)
        self.assertTrue(self.pl.bypass.active())
        s = np.arange(15.0, 21.0, 0.1)
        d = self.pl.bypass.offset_at(s)
        centre = np.stack([s + 0.5, 10.0 + d], axis=1)  # path x = s + 0.5
        gap = np.hypot(centre[:, None, 0] - pal[None, :, 0], centre[:, None, 1] - pal[None, :, 1]).min()
        self.assertGreaterEqual(gap, CONFIG["robot"]["radius"] + cfg.BYPASS_CLEAR - 0.06)
        # the offset stays inside the road (y 7.5..12.5) and clear of the walls
        self.assertLess(float(np.max(np.abs(d))), 2.5)
        self.assertTrue(self.pl.offset_ok(centre))

    def test_offset_shape_is_s_shaped(self):
        self.feed(self.pallet(18.0, 10.6))
        o = self.pl.bypass.off
        self.assertEqual(float(self.pl.bypass.offset_at(np.array([o["s1"] - 1.2 - o["lin"] - 0.5]))[0]), 0.0)
        self.assertAlmostEqual(float(self.pl.bypass.offset_at(np.array([0.5 * (o["s1"] + o["s2"])]))[0]), o["d"])

    def test_target_follows_the_offset(self):
        self.feed(self.pallet(18.0, 10.6))
        o = self.pl.bypass.off
        tx, ty = self.pl.target(0.5 * (o["s1"] + o["s2"]))
        self.assertAlmostEqual(ty, 10.0 + o["d"])

    def test_no_room_no_offset(self):
        # a wide object across the whole road: nothing fits, no offset (the safety layer stops)
        wall = np.stack([np.full(40, 18.0), np.linspace(7.6, 12.4, 40)], axis=1)
        self.feed(wall)
        self.assertFalse(self.pl.bypass.active())

    def test_track_ahead_starts_at_the_platform(self):
        xy, ss = self.pl.track_ahead(10.0, 10.3, 0.0, self.pl.path.project(10.0, 10.3), 6.0)
        self.assertAlmostEqual(float(xy[0, 0]), 0.0)
        self.assertAlmostEqual(float(xy[0, 1]), 0.0)
        self.assertAlmostEqual(float(xy[-1, 1]), -0.3, places=2)  # back on the axis 0.3 m to the right
