"""Pose filter on the synthetic road of the fixtures: the scan is ray cast from the true pose."""

import math
import unittest

import numpy as np

from geometry import raycast, wall_segments
from localization import Localizer
from motion import speed_law
from tests.fixtures import CONFIG, MAP

SEGS = wall_segments(MAP)
REL = np.radians(np.arange(360.0))


def scan(x, y, th):
    r = raycast(x, y, th + REL, SEGS)
    return np.where(r <= 20.0, r, np.nan)


def drive(loc, ticks, v=1.0, gnss=None, odom_scale=0.02, mutate=None):
    """Straight east along y = 10 from x = 5; returns the true x."""
    x, vw = 5.0, 0.0
    cmd = (0.0, 0.0, False)
    for k in range(ticks):
        # the odometry of the previous tick: the platform follows the speed law from config
        vn = speed_law(vw, cmd[0], False, CONFIG["robot"], 0.1)
        dx = 0.5 * (vw + vn) * 0.1
        vw = vn
        x += dx
        obs = {
            "t": 0.1 * k,
            "lidar": {"ranges": scan(x, 10.0, 0.0)},
            "odom": {"dx": dx * (1.0 + odom_scale), "dy": 0.0, "dtheta": 0.0},
            "imu": {"heading": 0.0},
            "gnss": gnss(k, x) if gnss else {"x": None, "y": None, "valid": False, "hdop": None},
        }
        if mutate:
            obs = mutate(k, obs)
        loc.update(obs, cmd)
        cmd = (v, 0.0, False)
    return x


class LocalizerTest(unittest.TestCase):
    def setUp(self):
        self.loc = Localizer(MAP, CONFIG, [5.0, 10.0, 0.0], use_model=False, scale_from_cmd=True)

    def test_pose_holds_on_a_straight_road(self):
        x = drive(self.loc, 200)
        px, py, pth = self.loc.pose()
        self.assertLess(abs(py - 10.0), 0.05)  # the walls pin the lateral position
        self.assertLess(abs(px - x), 0.5)  # along the road: odometry with its scale learned
        self.assertLess(abs(pth), 0.01)
        self.assertFalse(self.loc.lost)

    def test_scale_is_learned_from_the_commands(self):
        drive(self.loc, 200, odom_scale=0.03)
        self.assertAlmostEqual(float(self.loc.xs[3]), 0.03, delta=0.01)

    def test_nan_input_is_skipped(self):
        def nan(k, obs):
            if k in (50, 51, 120):
                obs["odom"] = {"dx": float("nan"), "dy": 0.0, "dtheta": 0.0}
                obs["imu"] = {"heading": float("nan")}
            return obs

        x = drive(self.loc, 200, mutate=nan)
        self.assertTrue(np.isfinite(self.loc.xs).all())
        self.assertTrue(np.isfinite(self.loc.P).all())
        self.assertLess(abs(self.loc.pose()[0] - x), 0.5)
        self.assertAlmostEqual(float(self.loc.xs[3]), 0.02, delta=0.01)

    def test_gnss_jump_is_rejected(self):
        def gnss(k, x):
            jump = 6.0 if 100 <= k < 130 else 0.0
            return {"x": x + jump, "y": 10.0, "valid": True, "hdop": 0.9}

        x = drive(self.loc, 160, gnss=gnss)
        self.assertLess(math.hypot(self.loc.pose()[0] - x, self.loc.pose()[1] - 10.0), 0.5)
