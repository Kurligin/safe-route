"""Разбор прогонов и сценариев для рабочего места оператора.

Только стандартная библиотека. Прогон — пара «лог JSONL + отчёт JSON» симулятора
(формат — docs/DATA.md §7). Выход — словарь, который интерфейс получает целиком:
карта, события, миссии, счёт и массивы значений по тикам.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

TICK_KEYS = (
    "t", "x", "y", "th", "px", "py", "pth", "v", "cv", "w", "st", "nt", "m", "hum", "obj",
    "vmax", "err", "peds", "coll", "cont", "drv",
)  # fmt: skip
CTRL_LABELS = {"ours": "Наш контроллер", "baseline": "Baseline"}
DEFAULT_MAX = {"delivery": 40.0, "efficiency": 15.0, "safety": 25.0, "rules": 10.0, "pose": 10.0, "collisions": 0.0}
CUSTOM_ID = re.compile(r"^custom_(\d{1,4})$")
TICK_PREFIX = '{"type":"tick"'

Run = dict[str, Any]


def _r(v: Any, n: int = 2) -> Any:
    return None if v is None else round(v, n)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def controller_key(stem: str, report: dict | None) -> str:
    """Какой контроллер ехал: по префиксу имени `<контроллер>__<сценарий>__s<seed>` и пути из отчёта."""
    tag = stem.split("__")[0].lower() if "__" in stem else ""
    path = str(((report or {}).get("controller") or {}).get("path") or "").lower()
    if "baseline" in tag or "baseline" in path:
        return "baseline"
    return "ours"


def find_runs(*dirs: Path | str) -> dict[str, tuple[Path, Path | None]]:
    """Все прогоны в папках (рекурсивно). Ключ — имя лога без расширения.

    Отчёт ищется рядом с логом (`x.jsonl` + `x.json`) или в соседней папке `reports/`
    (раскладка `results/logs` + `results/reports`). Отчёт без лога не показывается:
    проигрывать нечего.
    """
    out: dict[str, tuple[Path, Path | None]] = {}
    for base in dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        for log in sorted(base.rglob("*.jsonl")):
            cands = [log.with_suffix(".json"), log.parent.parent / "reports" / (log.stem + ".json")]
            rep = next((c for c in cands if c.is_file()), None)
            key = log.stem if log.stem not in out else "%s_%s" % (log.parent.name, log.stem)
            out[key] = (log, rep)
    return out


def _tick_row(T: dict[str, list], d: dict) -> None:
    pe = d.get("pe")
    ok = isinstance(pe, list) and len(pe) >= 3 and all(_is_num(q) for q in pe[:3])
    x, y = d.get("x"), d.get("y")
    T["t"].append(_r(d.get("t"), 1))
    T["x"].append(_r(x, 3))
    T["y"].append(_r(y, 3))
    T["th"].append(_r(d.get("th"), 3))
    T["px"].append(_r(pe[0], 3) if ok else None)
    T["py"].append(_r(pe[1], 3) if ok else None)
    T["pth"].append(_r(pe[2], 3) if ok else None)
    T["v"].append(_r(d.get("v")))
    T["cv"].append(_r(d.get("cv")))
    T["w"].append(_r(d.get("w")))
    T["st"].append(d.get("st", ""))
    T["nt"].append(d.get("nt", ""))
    T["m"].append(d.get("m"))
    T["hum"].append(_r(d.get("hum")))
    T["obj"].append(_r(d.get("obj")))
    T["vmax"].append(d.get("vmax"))
    T["err"].append(_r(math.hypot(pe[0] - x, pe[1] - y), 3) if ok and _is_num(x) and _is_num(y) else None)
    T["peds"].append([[_r(p[0], 1), _r(p[1], 1)] for p in d.get("peds", [])])
    T["coll"].append(d.get("coll", 0))
    T["cont"].append(d.get("cont", 0))
    T["drv"].append(d.get("drv", 1))


def load_run(log_path: Path | str, report_path: Path | str | None = None, full: bool = True) -> Run:
    """Прочитать прогон. `full=False` — сводка без тиков и карты (для списков).

    Отчёт необязателен: без него счёт нулевой, число доставок — по записям миссий.
    """
    log_path = Path(log_path)
    header: dict | None = None
    missions: list[dict] = []
    end: dict | None = None
    T: dict[str, list] = {k: [] for k in TICK_KEYS}
    n_ticks = 0
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith(TICK_PREFIX):
                n_ticks += 1
                if full:
                    _tick_row(T, json.loads(line))
                continue
            if not line.strip():
                continue
            d = json.loads(line)
            kind = d.get("type")
            if kind == "header":
                header = d
            elif kind == "mission":
                missions.append(d)
            elif kind == "end":
                end = d
            elif kind == "tick":  # запись в другом порядке полей
                n_ticks += 1
                if full:
                    _tick_row(T, d)
    if header is None:
        raise ValueError("в логе нет записи header: %s" % log_path)
    rep: dict | None = None
    if report_path and Path(report_path).is_file():
        rep = json.loads(Path(report_path).read_text(encoding="utf-8"))
    sc = (rep or {}).get("score") or {}
    ctrl = controller_key(log_path.stem, rep)
    out: Run = {
        "ctrl": ctrl,
        "label": CTRL_LABELS[ctrl],
        "scenario": header.get("scenario", ""),
        "seed": header.get("seed", 0),
        "points": header.get("points", {}),
        "events": header.get("events", []),
        "patches": header.get("map_patches", []),
        "missions_hdr": header.get("missions", []),
        "missions": missions,
        "end": end,
        "n_ticks": n_ticks,
        "counted": (rep or {}).get("counted"),
        "score": {
            "total": sc.get("total", 0.0),
            "blocks": sc.get("blocks", {}),
            "max": sc.get("max", DEFAULT_MAX),
            "deliveries": sc.get("deliveries", sum(1 for m in missions if m.get("delivered"))),
            "fatal": sc.get("fatal", False),
            "missions": sc.get("missions", []),
            "episodes": sc.get("episodes", []),
        },
        "step_ms": (rep or {}).get("step_time_ms") or {"mean": 0.0, "max": 0.0},
        "wall_s": (rep or {}).get("wall_time_s", 0.0),
        "mtime": log_path.stat().st_mtime,
    }
    if full:
        out["map"] = header.get("map")
        out["ticks"] = T
    return out


def load_scenario(path: Path | str) -> dict[str, Any]:
    """Сценарий для интерфейса: маршрут с эталонными путями, пешеходы, события, расхождения карты."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "name": d.get("name", Path(path).stem),
        "description": d.get("description", ""),
        "duration_s": d.get("duration_s"),
        "provide_detections": d.get("provide_detections", False),
        "generator": d.get("generator"),
        "weather": d.get("weather", {}),
        "start": d.get("start"),
        "missions": [
            {
                "id": m["id"],
                "from": m["from"],
                "to": m["to"],
                "deadline_s": m.get("deadline_s"),
                "reference_length_m": m.get("reference_length_m"),
                "ref": [[x, y] for x, y in m["reference_path"]],
            }
            for m in d.get("missions", [])
        ],
        "pedestrians": d.get("pedestrians", []),
        "events": d.get("events", []),
        "map_patches": d.get("map_patches", []),
        "map": d.get("map"),
    }


def is_custom_id(sid: str) -> bool:
    return bool(CUSTOM_ID.match(sid or ""))


def next_custom_id(existing: list[str]) -> str:
    nums = [int(m.group(1)) for m in (CUSTOM_ID.match(s) for s in existing) if m]
    return "custom_%02d" % (max(nums, default=0) + 1)
