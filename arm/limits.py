"""Пределы своего сценария: близко к скрытым сценариям организаторов, с запасом.

Схема симулятора ограничивает только `duration_s` ≤ 3600, а лог и память прогона растут с числом
пешеходов и длительностью. Поэтому свой сценарий проверяется до вызова симулятора.
"""

from __future__ import annotations

import json
from typing import Any

MAX_BYTES = 512_000
MAX_DURATION_S = 900.0
MAX_PEDESTRIANS = 30
MAX_EVENTS = 20
MAX_PATCHES = 10
MAX_MISSIONS = 10
MAX_POINTS = 5000


def _points(sc: dict[str, Any]) -> int:
    """Точек во всех полигонах и путях сценария."""

    def n(seq: Any) -> int:
        return len(seq) if isinstance(seq, list) else 0

    m = sc.get("map") if isinstance(sc.get("map"), dict) else {}
    total = sum(n(p) for p in (m.get("drivable") or []) if isinstance(p, list))
    for key in ("buildings", "zones"):
        total += sum(n(b.get("polygon")) for b in (m.get(key) or []) if isinstance(b, dict))
    total += sum(n(p.get("polygon")) for p in (sc.get("map_patches") or []) if isinstance(p, dict))
    total += sum(n(p.get("waypoints")) for p in (sc.get("pedestrians") or []) if isinstance(p, dict))
    total += sum(n(m_.get("reference_path")) for m_ in (sc.get("missions") or []) if isinstance(m_, dict))
    return total


def check(sc: dict[str, Any]) -> str | None:
    """Текст отказа или None, если сценарий в пределах."""
    size = len(json.dumps(sc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_BYTES:
        return "сценарий больше %d КБ" % (MAX_BYTES // 1000)
    dur = sc.get("duration_s")
    if isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > MAX_DURATION_S:
        return "длительность больше %d с" % MAX_DURATION_S
    counts = (
        ("pedestrians", MAX_PEDESTRIANS, "пешеходов"),
        ("events", MAX_EVENTS, "событий"),
        ("map_patches", MAX_PATCHES, "расхождений карты"),
        ("missions", MAX_MISSIONS, "рейсов"),
    )
    for key, limit, what in counts:
        v = sc.get(key)
        if isinstance(v, list) and len(v) > limit:
            return "%s больше %d" % (what, limit)
    if _points(sc) > MAX_POINTS:
        return "точек в полигонах и путях больше %d" % MAX_POINTS
    return None
