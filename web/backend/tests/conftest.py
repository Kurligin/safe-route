"""Общие заготовки: маленький прогон, сдаваемый репозиторий и поддельный симулятор во временной папке."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from saferoute.config import Settings

MAP = {
    "bounds": [0, 0, 250, 200],
    "drivable": [[[0, 0], [100, 0], [100, 10], [0, 10]]],
    "buildings": [{"id": "W", "polygon": [[0, 20], [10, 20], [10, 30], [0, 30]]}],
    "points": {"warehouse": {"x": 1.0, "y": 5.0, "heading": 3.141593}, "shop_a": {"x": 90.0, "y": 5.0, "heading": 0}},
    "zones": [{"type": "gnss_shadow", "polygon": [[20, 0], [40, 0], [40, 10], [20, 10]]}],
}


def tick(t: float, x: float, v: float, st: str = "moving", nt: str = "", w: float = 0.0) -> dict:
    return {"type": "tick", "t": t, "x": x, "y": 5.0, "th": 0.0, "v": v, "w": w, "cv": v, "st": st, "nt": nt,
            "pe": [x + 0.1, 5.0, 0.0], "m": "m1", "hum": 9.0, "obj": 5.0, "vmax": None, "peds": [[50.0, 6.0]],
            "coll": 0, "cont": 0, "drv": 1}  # fmt: skip


def write_run(folder: Path, stem: str, total: float = 97.5) -> None:
    """Прогон: 2 с движения, 3 с ожидания человека, 1 с движения, прибытие."""
    folder.mkdir(parents=True, exist_ok=True)
    header = {"type": "header", "scenario": "01_clear", "seed": 1, "points": MAP["points"], "events": [],
              "map_patches": [], "missions": [{"id": "m1", "from": "warehouse", "to": "shop_a", "deadline_s": 60}],
              "map": MAP}  # fmt: skip
    rows = [header]
    t, x = 0.0, 1.0
    for _ in range(20):
        rows.append(tick(t, x, 1.0))
        t, x = round(t + 0.1, 1), x + 0.1
    for _ in range(30):
        rows.append(tick(t, x, 0.0, "waiting", "wait:person"))
        t = round(t + 0.1, 1)
    for _ in range(10):
        rows.append(tick(t, x, 1.0, nt="zone:1.04"))
        t, x = round(t + 0.1, 1), x + 0.1
    rows.append(tick(t, x, 0.0, "arrived"))
    rows.append({"type": "mission", "id": "m1", "from": "warehouse", "to": "shop_a", "t_start": 0.0, "t_end": t,
                 "t_arrival": t, "deadline_s": 60, "delivered": True, "reason": "delivered"})  # fmt: skip
    rows.append({"type": "end", "t": t, "reason": "missions_done"})
    (folder / (stem + ".jsonl")).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    score = {"total": total, "blocks": {"delivery": 40.0}, "deliveries": 1,
             "episodes": [{"type": "person_near_fast", "t_start": 2.5, "t_end": 3.0, "cost": 1.5,
                           "x": 3.0, "y": 5.0}]}  # fmt: skip
    rep = {"score": score, "controller": {"path": "controller.py"}, "step_time_ms": {"mean": 0.5, "max": 1.0}}
    (folder / (stem + ".json")).write_text(json.dumps(rep), encoding="utf-8")


def scenario_doc(name: str = "01_clear") -> dict:
    return {"schema": "amr-1.0", "name": name, "description": "тест", "duration_s": 100, "map": MAP,
            "start": {"x": 1, "y": 5, "theta": 0},
            "missions": [{"id": "m1", "from": "warehouse", "to": "shop_a", "deadline_s": 60,
                          "reference_path": [[1, 5], [90, 5]], "reference_length_m": 89}],
            "pedestrians": [], "events": [], "map_patches": []}  # fmt: skip


FAKE_MAIN = """
import argparse, json, sys, time
ap = argparse.ArgumentParser()
ap.add_argument("cmd"); ap.add_argument("scenario"); ap.add_argument("--controller")
ap.add_argument("--seed", type=int)
ap.add_argument("--report"); ap.add_argument("--log")
a = ap.parse_args()
sc = json.load(open(a.scenario, encoding="utf-8"))
if sc.get("name") == "broken":
    print("RuntimeError: controller crashed", file=sys.stderr); sys.exit(2)
hdr = {"type": "header", "scenario": sc["name"], "seed": a.seed, "points": {}, "events": [], "map_patches": [],
       "missions": [], "map": sc.get("map")}
tk = {"type": "tick", "t": 0.0, "x": 1, "y": 5, "th": 0, "v": 0, "w": 0, "st": "moving", "pe": [1, 5, 0], "peds": []}
open(a.log, "w").write(json.dumps(hdr) + "\\n" + json.dumps(tk) + "\\n")
open(a.report, "w").write(json.dumps({"score": {"total": 42.0 + a.seed}, "controller": {"path": a.controller}}))
"""
FAKE_SCHEMA = """
import json
def load_scenario(path):
    d = json.load(open(path, encoding="utf-8"))
    if not d.get("missions"):
        raise ValueError("missions: at least one mission is required")
    return d
"""


@pytest.fixture()
def layout(tmp_path: Path) -> dict[str, Path]:
    sub, sim = tmp_path / "safe-route", tmp_path / "amrsim"
    write_run(sub / "results" / "logs", "01_clear__s1")
    (sub / "results" / "reports").mkdir(parents=True)
    (sub / "results" / "logs" / "01_clear__s1.json").rename(sub / "results" / "reports" / "01_clear__s1.json")
    (sub / "scenarios").mkdir()
    (sub / "scenarios" / "gen_001_AWA.json").write_text(json.dumps(scenario_doc("gen_001_AWA")), encoding="utf-8")
    (sub / "scenarios" / "broken.json").write_text(json.dumps(scenario_doc("broken")), encoding="utf-8")
    (sub / "scenarios" / "showcase" / "works").mkdir(parents=True)
    show = sub / "scenarios" / "showcase" / "works" / "w1_demo.json"
    show.write_text(json.dumps(scenario_doc("w1_demo")), encoding="utf-8")
    (sub / "controller.py").write_text("# наш\n", encoding="utf-8")
    (sim / "amrsim").mkdir(parents=True)
    (sim / "amrsim" / "__init__.py").write_text("", encoding="utf-8")
    (sim / "amrsim" / "__main__.py").write_text(FAKE_MAIN, encoding="utf-8")
    (sim / "amrsim" / "schema.py").write_text(FAKE_SCHEMA, encoding="utf-8")
    (sim / "numpy.py").write_text("", encoding="utf-8")  # проверка готовности импортирует numpy
    (sim / "baseline").mkdir()
    (sim / "baseline" / "controller.py").write_text("# baseline\n", encoding="utf-8")
    (sim / "scenarios").mkdir()
    for sid in ("01_clear", "01e_clear_easy"):
        (sim / "scenarios" / (sid + ".json")).write_text(json.dumps(scenario_doc(sid)), encoding="utf-8")
    return {"sub": sub, "sim": sim, "runs": tmp_path / "runs", "custom": tmp_path / "custom"}


@pytest.fixture()
def settings(layout: dict[str, Path]) -> Settings:
    return Settings(
        submission=layout["sub"],
        sim=layout["sim"],
        python=sys.executable,
        runs_dir=layout["runs"],
        custom_dir=layout["custom"],
        static_dir=None,
        parallel=2,
        allowed_hosts=frozenset({"testserver", "127.0.0.1", "localhost"}),
        max_jobs_per_request=4,
        max_queued=6,
    )
