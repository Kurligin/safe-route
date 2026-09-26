"""Тесты ядра рабочего места оператора: разбор прогонов и сценариев на синтетических файлах."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import armcore  # noqa: E402

POINTS = {
    "warehouse": {"x": 51.5, "y": 150.0, "heading": 3.141593, "tol": 0.2},
    "shop_a": {"x": 220.0, "y": 158.5, "heading": 1.570796, "tol": 0.2},
    "charger": {"x": 190.0, "y": 85.5, "heading": -1.570796, "tol": 0.2},
}
MAP = {"bounds": [0, 0, 250, 200], "drivable": [], "buildings": [], "points": POINTS, "zones": []}


def write_log(path: Path, n: int = 30, note: str = "") -> None:
    header = {
        "type": "header",
        "scenario": "04_busy_yard",
        "seed": 3,
        "points": POINTS,
        "missions": [{"id": "m1", "from": "warehouse", "to": "shop_a", "deadline_s": 200.7}],
        "map": MAP,
        "map_patches": [],
        "events": [{"type": "fog_bank", "t1": 1.0, "t2": 2.0}],
    }
    lines = [header]
    for i in range(n):
        pe = None if i == 5 else [51.5 + 0.1 * i + 0.3, 150.0 + 0.4, 0.0]
        tick = {
            "type": "tick",
            "t": round(0.1 * i, 1),
            "x": 51.5 + 0.1 * i,
            "y": 150.0,
            "th": 0.0,
            "v": 1.0,
            "w": 0.0,
            "cv": 1.0,
            "st": "moving",
            "pe": pe,
            "m": "m1",
            "drv": 1,
            "hum": None,
            "obj": 3.0,
            "vmax": None,
            "coll": 0,
            "cont": 0,
            "peds": [[60.0, 151.0]],
        }
        if note:
            tick["nt"] = note
        lines.append(tick)
    lines.append(
        {
            "type": "mission",
            "id": "m1",
            "from": "warehouse",
            "to": "shop_a",
            "t_start": 0.0,
            "t_end": 2.9,
            "t_arrival": 2.8,
            "deadline_s": 200.7,
            "delivered": True,
            "reason": "delivered",
        }
    )
    lines.append({"type": "end", "t": 3.0, "reason": "missions_done", "error": None})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(d) for d in lines) + "\n", encoding="utf-8")


def write_report(path: Path, total: float = 97.5, ctrl_path: str = "controller.py") -> None:
    rep = {
        "controller": {"path": ctrl_path},
        "counted": True,
        "end_reason": "missions_done",
        "score": {
            "total": total,
            "blocks": {"delivery": 40.0},
            "max": {"delivery": 40.0},
            "deliveries": 1,
            "fatal": False,
            "missions": [],
            "episodes": [{"type": "near_person", "t_start": 1.0, "t_end": 1.5, "cost": 0.4, "x": 52, "y": 150}],
        },
        "step_time_ms": {"mean": 0.5, "max": 2.0},
        "wall_time_s": 1.2,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep), encoding="utf-8")


class FindRunsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_flat_pair(self) -> None:
        write_log(self.root / "runs" / "ours__04_busy_yard__s3.jsonl")
        write_report(self.root / "runs" / "ours__04_busy_yard__s3.json")
        runs = armcore.find_runs(self.root / "runs")
        log, rep = runs["ours__04_busy_yard__s3"]
        self.assertEqual(log.suffix, ".jsonl")
        self.assertEqual(rep.name, "ours__04_busy_yard__s3.json")

    def test_results_layout_logs_and_reports_apart(self) -> None:
        write_log(self.root / "results" / "logs" / "04_busy_yard__s1.jsonl")
        write_report(self.root / "results" / "reports" / "04_busy_yard__s1.json")
        write_report(self.root / "results" / "reports" / "04_busy_yard__s2.json")  # отчёт без лога
        runs = armcore.find_runs(self.root / "results")
        self.assertEqual(list(runs), ["04_busy_yard__s1"])
        self.assertEqual(runs["04_busy_yard__s1"][1].parent.name, "reports")

    def test_log_without_report(self) -> None:
        write_log(self.root / "a" / "x__01_clear__s1.jsonl")
        self.assertIsNone(armcore.find_runs(self.root / "a")["x__01_clear__s1"][1])

    def test_same_name_in_two_folders_gets_unique_key(self) -> None:
        write_log(self.root / "a" / "x.jsonl")
        write_log(self.root / "b" / "x.jsonl")
        self.assertEqual(sorted(armcore.find_runs(self.root / "a", self.root / "b")), ["b_x", "x"])

    def test_missing_dir_is_skipped(self) -> None:
        self.assertEqual(armcore.find_runs(self.root / "nope"), {})


class LoadRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "baseline__04_busy_yard__s3.jsonl"
        self.rep = self.root / "baseline__04_busy_yard__s3.json"
        write_log(self.log, note="wait:person")
        write_report(self.rep, ctrl_path="/sim/baseline/controller.py")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_run(self) -> None:
        r = armcore.load_run(self.log, self.rep)
        self.assertEqual(r["scenario"], "04_busy_yard")
        self.assertEqual(r["seed"], 3)
        self.assertEqual(r["ctrl"], "baseline")
        self.assertEqual(r["label"], "Baseline")
        self.assertEqual(set(r["ticks"]), set(armcore.TICK_KEYS))
        self.assertEqual(len(r["ticks"]["t"]), 30)
        self.assertAlmostEqual(r["ticks"]["err"][0], 0.5, places=3)  # |(0.3, 0.4)|
        self.assertIsNone(r["ticks"]["px"][5])
        self.assertIsNone(r["ticks"]["err"][5])
        self.assertEqual(r["ticks"]["nt"][0], "wait:person")
        self.assertEqual(r["score"]["total"], 97.5)
        self.assertEqual(len(r["score"]["episodes"]), 1)
        self.assertEqual(r["map"]["bounds"], [0, 0, 250, 200])
        self.assertEqual(r["end"]["reason"], "missions_done")

    def test_lite_run_has_no_ticks_and_map(self) -> None:
        r = armcore.load_run(self.log, self.rep, full=False)
        self.assertNotIn("ticks", r)
        self.assertNotIn("map", r)
        self.assertEqual(len(r["missions"]), 1)
        self.assertEqual(r["n_ticks"], 30)
        self.assertEqual(r["score"]["total"], 97.5)

    def test_without_report_score_comes_from_missions(self) -> None:
        r = armcore.load_run(self.log, None)
        self.assertEqual(r["score"]["deliveries"], 1)
        self.assertEqual(r["score"]["total"], 0.0)
        self.assertEqual(r["ctrl"], "baseline")

    def test_our_run_from_results_has_no_prefix(self) -> None:
        log = self.root / "01_clear__s1.jsonl"
        write_log(log)
        self.assertEqual(armcore.load_run(log, None)["ctrl"], "ours")

    def test_broken_log_raises(self) -> None:
        bad = self.root / "bad.jsonl"
        bad.write_text('{"type":"tick","t":0}\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            armcore.load_run(bad)


class ControllerKeyTest(unittest.TestCase):
    def test_keys(self) -> None:
        self.assertEqual(armcore.controller_key("baseline__01_clear__s1", None), "baseline")
        self.assertEqual(armcore.controller_key("ours__01_clear__s1", None), "ours")
        self.assertEqual(armcore.controller_key("01_clear__s1", {"controller": {"path": "controller.py"}}), "ours")
        self.assertEqual(armcore.controller_key("x", {"controller": {"path": "/a/baseline/controller.py"}}), "baseline")


class ScenarioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "02_gnss_shadow.json"
        sc = {
            "schema": "amr-1.0",
            "name": "02_gnss_shadow",
            "description": "GNSS shadow",
            "duration_s": 300.0,
            "weather": {"snow": False},
            "map": MAP,
            "map_patches": [],
            "start": {"x": 51.5, "y": 150.0, "theta": 0.0},
            "missions": [
                {
                    "id": "m1",
                    "from": "warehouse",
                    "to": "shop_a",
                    "deadline_s": 252.0,
                    "reference_path": [[51.5, 150.0], [55.04, 150.0], [220.0, 158.5]],
                    "reference_length_m": 218.918,
                }
            ],
            "pedestrians": [],
            "events": [],
        }
        self.path.write_text(json.dumps(sc), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_scenario(self) -> None:
        d = armcore.load_scenario(self.path)
        self.assertEqual(d["name"], "02_gnss_shadow")
        self.assertEqual(d["duration_s"], 300.0)
        m = d["missions"][0]
        self.assertEqual(m["deadline_s"], 252.0)
        self.assertEqual(m["ref"][1], [55.04, 150.0])  # путь без огрубления
        self.assertEqual(d["map"]["points"]["warehouse"]["x"], 51.5)
        self.assertFalse(d["provide_detections"])
        self.assertIsNone(d["generator"])


class CustomIdTest(unittest.TestCase):
    def test_next_custom_id(self) -> None:
        self.assertEqual(armcore.next_custom_id([]), "custom_01")
        self.assertEqual(armcore.next_custom_id(["custom_01", "custom_07", "other"]), "custom_08")

    def test_valid_custom_id(self) -> None:
        self.assertTrue(armcore.is_custom_id("custom_03"))
        self.assertFalse(armcore.is_custom_id("01_clear"))
        self.assertFalse(armcore.is_custom_id("custom_../x"))


if __name__ == "__main__":
    unittest.main()
