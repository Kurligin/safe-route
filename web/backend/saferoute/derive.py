"""Производные данные прогона: остановки и замедления, подписи по-русски, CSV.

Логика остановок перенесена из интерфейса АРМ (`derive` в arm/static/app.js), чтобы таблица
«Остановки и штрафы» и выгрузка CSV считались в одном месте.
"""

from __future__ import annotations

import re
from typing import Any

CODE_RU = {
    "wait:person": "ждёт человека",
    "slow:person": "человек рядом",
    "wait:object": "препятствие впереди",
    "slow:object": "узкий проход",
    "bypass:object": "объезд препятствия",
    "estop:object": "аварийный стоп",
    "mismatch:map": "карта расходится с миром",
    "lost": "потеря позиции",
    "dock": "заход в док",
    "pickup": "едет к точке забора",
    "err": "ошибка шага",
    "person near": "человек рядом",
    "too close": "слишком близко",
    "obstacle ahead": "препятствие впереди",
    "waiting": "ожидание",
}
EP_RU = {
    "person_near_fast": "человек ближе 3 м на ходу",
    "person_close_pass": "проезд ближе 0,5 м к человеку",
    "person_contact_moving": "наезд на человека",
    "person_contact_standing": "контакт со стоящей платформой",
    "out_of_drivable": "выезд за проезд",
    "forbidden_zone": "въезд в запретную зону",
    "overspeed": "превышение скорости зоны",
    "pose_error": "ошибка позы больше 1 м",
    "status_mismatch": "статус не совпадает с движением",
    "estop_no_object": "аварийный стоп без причины",
    "collision": "столкновение",
}
ST_RU = {
    "moving": "едет",
    "arrived": "прибыл",
    "waiting": "ждёт",
    "lost": "потерял позицию",
    "estop": "аварийный стоп",
}
REASON_RU = {
    "delivered": "доставлен",
    "timeout": "не успел",
    "off_target": "не в точке",
    "not_picked_up": "без забора",
    "not_finished": "не завершён",
    "not_started": "не начат",
}
PT_RU = {"warehouse": "Склад", "shop_a": "Цех A", "shop_b": "Цех B", "charger": "Зарядка"}
SOFT = re.compile(r"^(zone:|dock$|pickup$)")  # поясняют движение, но сами не причина остановки

STILL_V = 0.05  # м/с и рад/с: быстрее — уже движение
MIN_STOP_S = 1.0  # короче — не остановка


def note_codes(note: str | None) -> list[str]:
    """Коды из поля `nt` контроллера: до «|», целиком из словаря или через пробел."""
    if not note:
        return []
    note = note.split("|")[0].strip()
    if not note:
        return []
    return [note] if note in CODE_RU else note.split()


def code_ru(code: str) -> str:
    if code in CODE_RU:
        return CODE_RU[code]
    if code.startswith("zone:"):
        return "зона скорости %s м/с" % code[5:]
    return code


def note_ru(note: str | None) -> str:
    return ", ".join(code_ru(c) for c in note_codes(note))


def cause_ru(note: str | None) -> str:
    return ", ".join(code_ru(c) for c in note_codes(note) if not SOFT.match(c))


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def stops(ticks: dict[str, list]) -> list[dict[str, Any]]:
    """Остановки и замедления: |v| < 0.05 (не разворот на месте) или причина в `nt` дольше 1 с.

    Причина интервала — самая частая подпись за время остановки.
    """
    t, v, w, st, nt = ticks["t"], ticks["v"], ticks["w"], ticks["st"], ticks["nt"]
    x, y = ticks["x"], ticks["y"]
    n = len(t)
    out: list[dict[str, Any]] = []
    s: int | None = None
    why: dict[str, int] = {}
    for i in range(n + 1):
        cause = cause_ru(nt[i]) if i < n else ""
        still = i < n and abs(_num(v[i])) < STILL_V and abs(_num(w[i])) < STILL_V
        slow = i < n and (still or bool(cause)) and st[i] != "arrived"
        if slow:
            if s is None:
                s, why = i, {}
            label = (
                cause
                or (ST_RU[st[i]] if st[i] in ("lost", "estop") else "")
                or (note_ru(nt[i]) if still else "")
                or ("стоп" if still else "")
            )
            if label:
                why[label] = why.get(label, 0) + 1
        elif s is not None:
            t0, t1 = _num(t[s]), _num(t[i - 1])
            if t1 - t0 >= MIN_STOP_S:
                top = max(why, key=lambda k: why[k]) if why else "стоп"  # при равенстве — первая
                minv = min(abs(_num(v[k])) for k in range(s, i))
                out.append({"t0": t0, "t1": t1, "reason": top, "full": minv < STILL_V, "x": x[s], "y": y[s]})
            s = None
    return out


# ---------------------------------------------------------------- CSV
def _js_num(v: float) -> str:
    """Число как в интерфейсе: три знака после запятой без хвостовых нулей, десятичная запятая."""
    r = round(float(v), 3)
    if r == 0:
        r = 0.0
    text = str(int(r)) if r == int(r) else repr(r)
    return text.replace(".", ",")


def _cell(c: Any) -> str:
    if c is None:
        return ""
    if isinstance(c, bool):
        return "да" if c else "нет"
    if isinstance(c, (int, float)):
        return _js_num(c)
    text = re.sub(r"[;\n\r]", ",", str(c))
    # текст, похожий на формулу, Excel выполнит: экранируем апострофом
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t") else text


def to_csv(rows: list[list[Any]]) -> bytes:
    """CSV для Excel: UTF-8 с BOM, разделитель «;», десятичная запятая, строки через CRLF."""
    return ("﻿" + "\r\n".join(";".join(_cell(c) for c in r) for r in rows)).encode("utf-8")


def _cost(v: Any) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == int(v):
        return str(int(v))
    return str(v)


def trips_rows(run: dict[str, Any]) -> list[list[Any]]:
    head = ["рейс", "откуда", "куда", "начало, с", "прибытие, с", "дедлайн, с", "доставлен", "причина"]
    rows: list[list[Any]] = [head]
    for m in run["missions"]:
        rows.append(
            [
                m.get("id"),
                PT_RU.get(m.get("from"), m.get("from")),
                PT_RU.get(m.get("to"), m.get("to")),
                m.get("t_start"),
                m.get("t_arrival"),
                m.get("deadline_s"),
                "да" if m.get("delivered") else "нет",
                REASON_RU.get(m.get("reason"), m.get("reason")),
            ]
        )
    return rows


def stops_rows(run: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = [["начало, с", "конец, с", "тип", "причина", "x", "y"]]
    for s in run.get("stops") or stops(run["ticks"]):
        rows.append([s["t0"], s["t1"], "стоп" if s["full"] else "медленно", s["reason"], s["x"], s["y"]])
    for e in run["score"].get("episodes") or []:
        what = "%s (%s б.)" % (EP_RU.get(e.get("type"), e.get("type")), _cost(e.get("cost")))
        rows.append([e.get("t_start"), e.get("t_end"), "штраф", what, e.get("x"), e.get("y")])
    return rows
