"""Losing the pose and getting it back (synthetic room with posts, the scan ray cast from the truth).

The platform is carried 12 m away while standing (a kidnap: odometry sees nothing). The scan stops
fitting the map, GNSS keeps disagreeing: the filter declares "lost", the controller stops at zero with
status "lost", then the pose is re-anchored to GNSS and confirmed by the scan."""

import math
import unittest

import numpy as np

from controller import Controller
from geometry import raycast, wall_segments
from localization import Localizer
from tests.fixtures import CONFIG


def _box(x0, y0, x1, y1, i):
    return {"id": "b%d" % i, "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


POSTS = [(6, 7), (11, 22), (17, 12), (23, 25), (9, 16), (25, 8), (19, 19), (14, 5)]
ROOM = {
    "bounds": [-3.0, -3.0, 33.0, 33.0],
    "buildings": [_box(-2, -2, 32, 0, 0), _box(-2, 30, 32, 32, 1), _box(-2, 0, 0, 30, 2), _box(30, 0, 32, 30, 3)]
    + [_box(x - 0.4, y - 0.4, x + 0.4, y + 0.4, 10 + i) for i, (x, y) in enumerate(POSTS)],
    "zones": [],
    "drivable": [[[0.0, 0.0], [30.0, 0.0], [30.0, 30.0], [0.0, 30.0]]],
    "points": {},
}
SEGS = wall_segments(ROOM)
REL = np.radians(np.arange(360.0))
KIDNAP_TICK = 100


def observe(k, x, y, th):
    r = raycast(x, y, th + REL, SEGS)
    return {
        "t": 0.1 * k,
        "lidar": {"ranges": np.where(r <= 20.0, r, np.nan)},
        "odom": {"dx": 0.0, "dy": 0.0, "dtheta": 0.0},
        "imu": {"heading": th},
        "gnss": {"x": x, "y": y, "valid": True, "hdop": 0.9},
        "mission": None,
    }


def truth(k):
    return (4.0, 3.0, 0.3) if k < KIDNAP_TICK else (16.0, 6.0, 0.3)


class LostTest(unittest.TestCase):
    def test_filter_declares_lost_and_recovers(self):
        loc = Localizer(ROOM, CONFIG, [4.0, 3.0, 0.3], use_model=False, scale_from_cmd=True)
        lost_at = back_at = None
        for k in range(400):
            loc.update(observe(k, *truth(k)), (0.0, 0.0, False))
            if loc.lost and lost_at is None:
                lost_at = k
            if lost_at is not None and not loc.lost and back_at is None:
                back_at = k
        self.assertIsNotNone(lost_at)
        self.assertLess(lost_at - KIDNAP_TICK, 50)  # lost within 5 s
        self.assertIsNotNone(back_at)
        self.assertLess(back_at - lost_at, 60)  # back within 6 s
        x, y, _ = truth(399)
        px, py, _ = loc.pose()
        self.assertLess(math.hypot(px - x, py - y), 0.2)
        self.assertFalse(loc.lost)

    def test_controller_stops_with_status_lost(self):
        c = Controller(ROOM, CONFIG, [4.0, 3.0, 0.3])
        seen = []
        for k in range(400):
            out = c.step(observe(k, *truth(k)))
            seen.append((out["status"], out["v"], out["w"], out["note"]))
        lost = [s for s in seen if s[0] == "lost"]
        self.assertTrue(lost)
        self.assertTrue(all(v == 0.0 and w == 0.0 and note == "lost" for _, v, w, note in lost))
        self.assertNotEqual(seen[-1][0], "lost")
        x, y, _ = truth(399)  # после восстановления оценка позы снова точная
        px, py, _ = c.loc.pose()
        self.assertLess(math.hypot(px - x, py - y), 0.2)
