import unittest

import config_team as cfg
from tests.fixtures import CONFIG, MAP, PATH_AW, mission
from mission import DOCKING, HOLD, TO_GOAL, TO_PICKUP, Mission


class MissionTest(unittest.TestCase):
    def setUp(self):
        self.m = Mission(MAP, CONFIG)

    def test_start_at_pickup_goes_to_goal(self):
        v = self.m.update(mission(), 0.5, 10.0, 0.02)
        self.assertEqual(v.phase, TO_GOAL)
        self.assertTrue(v.new_phase)
        self.assertTrue(self.m.picked)
        v = self.m.update(mission(), 1.0, 10.0, 0.02)
        self.assertFalse(v.new_phase)

    def test_start_away_from_pickup_goes_there_first(self):
        # the previous mission ended in the middle of the road
        v = self.m.update(mission(), 30.0, 10.0, 0.05)
        self.assertEqual(v.phase, TO_PICKUP)
        self.assertEqual(v.pickup, (0.5, 10.0))
        v = self.m.update(mission(), 5.0, 10.0, 0.05)
        self.assertEqual(v.phase, TO_PICKUP)
        v = self.m.update(mission(), 1.2, 10.0, 0.05)
        self.assertEqual(v.phase, TO_GOAL)
        self.assertTrue(v.new_phase)  # the path switches to the reference path

    def test_pickup_needs_margin_for_uncertain_pose(self):
        self.m.update(mission(), 30.0, 10.0, 0.05)
        v = self.m.update(mission(), 1.9, 10.0, 0.3)  # inside 2 m, but the pose is uncertain
        self.assertEqual(v.phase, TO_PICKUP)

    def test_docking_phase_near_goal(self):
        self.m.update(mission(), 0.5, 10.0, 0.02)
        v = self.m.update(mission(), 57.5, 10.0, 0.02)
        self.assertEqual(v.phase, DOCKING)

    def test_arrival_conditions(self):
        self.m.update(mission(), 0.5, 10.0, 0.02)
        self.m.update(mission(), 59.45, 10.0, 0.02)
        self.assertFalse(self.m.check_arrival(59.45, 10.0, 0.02, at_rest=False))  # still moving
        self.assertFalse(self.m.check_arrival(59.2, 10.0, 0.02, at_rest=True))  # too far
        self.assertFalse(self.m.check_arrival(59.45, 10.0, 0.12, at_rest=True))  # pose unsure
        self.assertTrue(self.m.check_arrival(59.45, 10.0, 0.02, at_rest=True))
        self.assertEqual(self.m.update(mission(), 59.45, 10.0, 0.02).phase, HOLD)
        # held until the mission changes
        self.assertTrue(self.m.check_arrival(59.0, 10.0, 0.5, at_rest=False))

    def test_late_sigma_after_waiting(self):
        self.m.update(mission(), 0.5, 10.0, 0.02)
        self.m.update(mission(), 59.45, 10.0, 0.1)
        got = [self.m.check_arrival(59.45, 10.0, 0.1, at_rest=True) for _ in range(cfg.ARRIVE_LATE_TICKS + 1)]
        self.assertFalse(got[0])
        self.assertTrue(got[-1])

    def test_new_id_resets_arrived_on_the_same_tick(self):
        self.m.update(mission(), 0.5, 10.0, 0.02)
        self.m.update(mission(), 59.45, 10.0, 0.02)
        self.assertTrue(self.m.check_arrival(59.45, 10.0, 0.02, at_rest=True))
        m2 = mission("m2", "shop_a", "warehouse", PATH_AW)
        v = self.m.update(m2, 59.45, 10.0, 0.02)
        self.assertFalse(self.m.arrived)
        self.assertEqual(v.phase, TO_GOAL)
        self.assertTrue(v.new_phase)
        self.assertEqual(v.goal[0], 0.5)
        # standing at the old goal is not an arrival at the new one
        self.assertFalse(self.m.check_arrival(59.45, 10.0, 0.02, at_rest=True))

    def test_no_mission(self):
        v = self.m.update(None, 0.0, 0.0, 0.02)
        self.assertEqual(v.phase, "done")


class MissionPathTest(unittest.TestCase):
    def test_path_ends_at_the_goal(self):
        m = Mission(MAP, CONFIG)
        v = m.update(mission(path=[[0.5, 10.0], [30.0, 10.0], [59.0, 10.0]]), 0.5, 10.0, 0.02)
        self.assertEqual(v.reference_path[-1], (59.5, 10.0))

    def test_empty_path(self):
        m = Mission(MAP, CONFIG)
        v = m.update(dict(mission(), reference_path=[]), 0.5, 10.0, 0.02)
        self.assertEqual(v.reference_path, [(0.5, 10.0), (59.5, 10.0)])

    def test_pickup_reachable_with_a_poor_pose(self):
        m = Mission(MAP, CONFIG)
        self.assertGreaterEqual(m.pickup_reach(1.0), cfg.PICKUP_FLOOR)
        m.update(mission(), 30.0, 10.0, 1.0)
        self.assertEqual(m.update(mission(), 0.6, 10.0, 1.0).phase, TO_GOAL)
