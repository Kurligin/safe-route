from __future__ import annotations

from saferoute import armcore, derive

from .conftest import write_run


def test_note_codes_and_cause() -> None:
    assert derive.note_codes("wait:person | debug") == ["wait:person"]
    assert derive.note_codes("zone:1.04 dock") == ["zone:1.04", "dock"]
    assert derive.note_ru("zone:1.04") == "зона скорости 1.04 м/с"
    assert derive.cause_ru("zone:1.04 dock") == ""  # мягкие коды — не причина остановки
    assert derive.cause_ru("slow:person") == "человек рядом"
    assert derive.note_codes(None) == []


def test_load_run_lite_and_full(tmp_path) -> None:
    write_run(tmp_path, "ours__01_clear__s1")
    runs = armcore.find_runs(tmp_path)
    log, rep = runs["ours__01_clear__s1"]
    lite = armcore.load_run(log, rep, full=False)
    assert lite["ctrl"] == "ours" and lite["n_ticks"] == 61 and "ticks" not in lite
    assert lite["score"]["total"] == 97.5 and lite["score"]["deliveries"] == 1
    full = armcore.load_run(log, rep)
    assert len(full["ticks"]["t"]) == 61 and full["map"]["bounds"] == [0, 0, 250, 200]
    assert abs(full["ticks"]["err"][0] - 0.1) < 1e-9


def test_stops_from_ticks(tmp_path) -> None:
    write_run(tmp_path, "r")
    full = armcore.load_run(tmp_path / "r.jsonl", tmp_path / "r.json")
    stops = derive.stops(full["ticks"])
    # одна остановка: ожидание человека 2,0–4,9 с; зона скорости на ходу и прибытие — не остановки
    assert len(stops) == 1
    s = stops[0]
    assert (s["t0"], s["t1"], s["reason"], s["full"]) == (2.0, 4.9, "ждёт человека", True)


def test_stops_ignore_short_and_spin() -> None:
    n = 30
    ticks = {"t": [i / 10 for i in range(n)], "v": [0.0] * n, "w": [0.5] * 20 + [0.0] * 5 + [0.0] * 5,
             "st": ["moving"] * n, "nt": [""] * n, "x": [0.0] * n, "y": [0.0] * n}  # fmt: skip
    # 20 тиков разворота на месте — не стоп; 10 тиков стоя (0,9 с) — короче секунды
    assert derive.stops(ticks) == []


def test_csv_format(tmp_path) -> None:
    write_run(tmp_path, "r")
    full = armcore.load_run(tmp_path / "r.jsonl", tmp_path / "r.json")
    full["stops"] = derive.stops(full["ticks"])
    text = derive.to_csv(derive.trips_rows(full)).decode("utf-8")
    assert text.startswith("﻿рейс;откуда;куда;")
    assert text.split("\r\n")[1] == "m1;Склад;Цех A;0;6;60;да;доставлен"
    stops = derive.to_csv(derive.stops_rows(full)).decode("utf-8").split("\r\n")
    assert stops[1] == "2;4,9;стоп;ждёт человека;3;5"
    assert stops[2] == "2,5;3;штраф;человек ближе 3 м на ходу (1.5 б.);3;5"


def test_csv_formula_escaped() -> None:
    text = derive.to_csv([["=cmd|'/c calc'!A1", "+1", "@x", "-2", "обычный", -2.5]]).decode("utf-8")
    assert text == "\ufeff'=cmd|'/c calc'!A1;'+1;'@x;'-2;обычный;-2,5"
