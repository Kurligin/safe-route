import math
import unittest

import numpy as np

from geometry import DistanceField, inside, inside_mask, raycast, seg_dist, wall_segments, wrap

SQUARE = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])


class WrapTest(unittest.TestCase):
    def test_range(self):
        for a in (-7.0, -math.pi, 0.0, 3.0, math.pi, 9.5):
            w = wrap(a)
            self.assertGreaterEqual(w, -math.pi)
            self.assertLess(w, math.pi)
            self.assertAlmostEqual(math.cos(w), math.cos(a))
            self.assertAlmostEqual(math.sin(w), math.sin(a))


class PolygonTest(unittest.TestCase):
    def test_inside(self):
        self.assertTrue(inside(5.0, 5.0, SQUARE))
        self.assertFalse(inside(11.0, 5.0, SQUARE))
        m = inside_mask(np.array([5.0, -1.0]), np.array([5.0, 5.0]), SQUARE)
        self.assertEqual(m.tolist(), [True, False])


class DistanceFieldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = DistanceField([SQUARE], [-5.0, -5.0, 15.0, 15.0], 0.1, 3.0)

    def test_outside_distance(self):
        # 1 m east of the east wall
        self.assertAlmostEqual(self.f.value(11.0, 5.0), 1.0, delta=0.02)

    def test_inside_negative(self):
        self.assertLess(self.f.value(9.0, 5.0), 0.0)
        self.assertAlmostEqual(self.f.value(9.0, 5.0), -1.0, delta=0.02)

    def test_clamped_far(self):
        self.assertAlmostEqual(self.f.value(14.5, 5.0), 3.0, delta=1e-6)
        self.assertAlmostEqual(self.f.value(1000.0, 5.0), 3.0, delta=1e-6)

    def test_gradient_points_away_from_wall(self):
        val, gx, gy = self.f.lookup(np.array([11.05]), np.array([5.05]))
        self.assertAlmostEqual(float(gx[0]), 1.0, delta=0.05)
        self.assertAlmostEqual(float(gy[0]), 0.0, delta=0.05)


class RayTest(unittest.TestCase):
    def test_raycast_and_seg_dist(self):
        segs = wall_segments({"buildings": [{"polygon": SQUARE.tolist()}]})
        d = raycast(-2.0, 5.0, np.array([0.0, math.pi]), segs)
        self.assertAlmostEqual(float(d[0]), 2.0)
        self.assertTrue(math.isinf(float(d[1])))
        self.assertAlmostEqual(float(seg_dist(np.array([12.0]), np.array([5.0]), segs)[0]), 2.0)
