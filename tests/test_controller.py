import math
import unittest

from controller import Controller
from tests.fixtures import CONFIG, MAP, mission, obs


def _finite_answer(tc, out):
    tc.assertIsInstance(out, dict)
    for k in ("v", "w"):
        tc.assertIsInstance(out[k], float)
        tc.assertTrue(math.isfinite(out[k]))
    tc.assertIn(out["status"], ("moving", "arrived", "waiting", "lost", "estop"))
    tc.assertEqual(len(out["pose_est"]), 3)
    for a in out["pose_est"]:
        tc.assertIsInstance(a, float)
        tc.assertTrue(math.isfinite(a))
    tc.assertIsInstance(out["note"], str)
    tc.assertLessEqual(len(out["note"]), 200)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.c = Controller(MAP, CONFIG, [0.5, 10.0, 0.0])

    def test_answer_is_finite(self):
        for k in range(30):
            _finite_answer(self, self.c.step(obs(0.1 * k, mission())))

    def test_no_mission(self):
        out = self.c.step(obs(0.0, None))
        _finite_answer(self, out)
        self.assertEqual(out["v"], 0.0)

    def test_malformed_observation_is_sanitized(self):
        for bad in (
            {k: v for k, v in obs(0.0, mission()).items() if k != "lidar"},
            dict(obs(0.0, mission()), gnss=None),
            {k: v for k, v in obs(0.0, mission()).items() if k != "gnss"},
            dict(obs(None, mission())),
            dict(obs(0.0, mission()), lidar={"ranges": []}),
            dict(obs(0.0, dict(mission(), reference_path=[]))),
        ):
            out = self.c.step(bad)
            _finite_answer(self, out)
            self.assertNotEqual(out["note"], "err")
            self.assertEqual(self.c.errors, 0)

    def test_exception_gives_a_safe_stop_and_recovers(self):
        c = self.c
        real = c.perception.update

        def broken(*a, **k):
            raise RuntimeError("broken")

        c.perception.update = broken
        out = c.step(obs(0.0, mission()))
        _finite_answer(self, out)
        self.assertEqual((out["v"], out["w"], out["note"], out["status"]), (0.0, 0.0, "err", "waiting"))
        c.perception.update = real
        out = c.step(obs(0.1, mission()))
        self.assertNotEqual(out["note"], "err")

    def test_exception_while_rolling_reports_moving(self):
        c = self.c
        c.loc.vw = 1.0

        def broken(*a, **k):
            raise RuntimeError("broken")

        c.perception.update = broken
        out = c.step(obs(0.0, mission()))
        self.assertEqual((out["v"], out["status"]), (0.0, "moving"))

    def test_nan_everywhere_does_not_leak(self):
        o = obs(0.0, mission())
        o["odom"] = {"dx": float("nan"), "dy": 0.0, "dtheta": float("inf")}
        o["imu"] = {"heading": float("nan")}
        _finite_answer(self, self.c.step(o))
        _finite_answer(self, self.c.step(obs(0.1, mission())))
        self.assertTrue(all(math.isfinite(float(a)) for a in self.c.loc.xs))

    def test_status_follows_the_speed_model(self):
        # a real stop reason (yielding): "moving" while the model speed is above 0.05, then "waiting"
        c = self.c
        c.loc.vw = 1.0
        c.last_cmd = (1.0, 0.0, False)
        c.safety.yield_hold = 20
        out = c.step(obs(0.0, mission()))
        self.assertEqual((out["v"], out["status"]), (0.0, "moving"))
        self.assertIn("wait:person", out["note"])
        for k in range(12):
            out = c.step(obs(0.1 * (k + 1), mission()))
        self.assertEqual(c.loc.vw, 0.0)
        self.assertEqual(out["status"], "waiting")
