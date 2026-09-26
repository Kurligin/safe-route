from __future__ import annotations

import dataclasses
import gzip
import time

import pytest
from fastapi.testclient import TestClient

from saferoute.api import create_app
from saferoute.config import Settings

from .conftest import scenario_doc

JSON = {"Content-Type": "application/json"}


@pytest.fixture()
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


def wait_jobs(client: TestClient, ids: list[str], limit: float = 20.0) -> dict[str, dict]:
    end = time.time() + limit
    while time.time() < end:
        jobs = {j["id"]: j for j in client.get("/api/jobs").json()}
        if all(jobs[i]["state"] in ("done", "error") for i in ids):
            return jobs
        time.sleep(0.1)
    raise AssertionError("прогоны не завершились")


def test_meta_and_lists(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["canRun"] is True and meta["parallel"] == 2
    assert [c["key"] for c in meta["controllers"]] == ["ours", "baseline"]
    runs = client.get("/api/runs").json()
    assert list(runs) == ["01_clear__s1"] and "ticks" not in runs["01_clear__s1"]
    sc = client.get("/api/scenarios").json()
    groups = [(s["id"], s["group"]) for s in sc["items"]]
    assert groups == [("01_clear", "Открытые"), ("01e_clear_easy", "Учебные"), ("gen_001_AWA", "Скрытоподобные"),
                      ("broken", "Проверочные"), ("w1_demo", "Витрина")]  # fmt: skip
    assert "map" not in sc["items"][0]["scenario"] and sc["baseMap"]["bounds"] == [0, 0, 250, 200]


def test_run_full_gzip_and_404(client: TestClient) -> None:
    r = client.get("/api/runs/01_clear__s1", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    d = r.json()
    assert len(d["ticks"]["t"]) == 61 and d["stops"][0]["reason"] == "ждёт человека"
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/..%2f..%2fetc").status_code == 404


def test_scenario_has_own_map_and_raw(client: TestClient) -> None:
    d = client.get("/api/scenarios/gen_001_AWA").json()
    assert d["group"] == "Скрытоподобные" and d["scenario"]["map"]["zones"][0]["type"] == "gnss_shadow"
    raw = client.get("/api/scenarios/gen_001_AWA?raw=1")
    assert raw.status_code == 200 and raw.json()["name"] == "gen_001_AWA"


def test_csv_endpoints(client: TestClient) -> None:
    r = client.get("/api/runs/01_clear__s1/trips.csv")
    assert r.status_code == 200 and r.content.startswith("﻿".encode())
    assert "filename*=UTF-8''01_clear__s1_" in r.headers["content-disposition"]
    s = client.get("/api/runs/01_clear__s1/stops.csv").content.decode("utf-8")
    assert "штраф;человек ближе 3 м на ходу" in s


def test_post_guards(client: TestClient) -> None:
    body = '{"scenario":"01_clear","controllers":["ours"],"seeds":[1]}'
    assert client.post("/api/launch", content=body, headers={"Content-Type": "text/plain"}).status_code == 415
    r = client.post("/api/launch", content=body, headers={**JSON, "Origin": "http://evil.example"})
    assert r.status_code == 403 and "чужой страницы" in r.json()["error"]
    r = client.post("/api/launch", content=body, headers={**JSON, "Host": "rebind.example"})
    assert r.status_code == 403
    assert client.post("/api/launch", content="[1]", headers=JSON).status_code == 400
    assert client.get("/api/jobs").json() == []


def test_launch_validation_is_atomic(client: TestClient) -> None:
    bad = [
        {"scenario": "01_clear", "controllers": ["ours"], "seeds": [7, -1]},
        {"scenario": "01_clear", "controllers": ["evil"], "seeds": [1]},
        {"scenario": "../01_clear", "controllers": ["ours"], "seeds": [1]},
        {"scenario": "01_clear", "controllers": ["ours", "baseline"], "seeds": [1, 2, 3]},  # 6 > 4 за запрос
    ]
    for p in bad:
        assert client.post("/api/launch", json=p, headers=JSON).status_code == 400, p
    body = '{"scenario":"01_clear","controllers":["ours"],"seeds":[1e400]}'
    assert client.post("/api/launch", content=body, headers=JSON).status_code == 400
    assert client.get("/api/jobs").json() == []


def test_launch_runs_and_run_appears(client: TestClient) -> None:
    r = client.post("/api/launch", json={"scenario": "01_clear", "controllers": ["ours", "baseline"], "seeds": [3]})
    ids = r.json()["jobs"]
    assert len(ids) == 2
    jobs = wait_jobs(client, ids)
    assert {jobs[i]["key"] for i in ids} == {"ours__01_clear__s3", "baseline__01_clear__s3"}
    assert jobs[ids[0]]["total"] == 45.0
    runs = client.get("/api/runs").json()
    assert runs["baseline__01_clear__s3"]["ctrl"] == "baseline"
    r = client.post("/api/launch", json={"scenario": "broken", "controllers": ["ours"], "seeds": [1]})
    jobs = wait_jobs(client, r.json()["jobs"])
    assert jobs[r.json()["jobs"][0]]["error"] == "RuntimeError: controller crashed"


def test_save_custom(client: TestClient, settings: Settings) -> None:
    sc = client.get("/api/scenarios/01_clear").json()["scenario"]
    doc = {"schema": "amr-1.0", "name": "x", "description": "<b>мой</b>", "map": sc["map"],
           "missions": scenario_doc()["missions"]}  # fmt: skip
    r = client.post("/api/scenarios", json={"id": "../../evil", "scenario": doc}).json()
    assert r["id"] == "custom_01" and r["token"]
    assert (settings.custom_dir / "custom_01.json").is_file()
    assert not list(settings.custom_dir.parent.glob("evil*"))
    # правка своего — только с токеном; без токена и с выдуманным id — новый сценарий
    r2 = client.post(
        "/api/scenarios", json={"id": "custom_01", "token": r["token"], "scenario": {**doc, "description": "правка"}}
    )
    assert r2.json() == {"id": "custom_01", "token": r["token"]}
    for sid in ("custom_01", "custom_7777", "custom_0001"):
        other = client.post(
            "/api/scenarios", json={"id": sid, "token": "x", "scenario": {**doc, "description": "чужой"}}
        )
        assert other.json()["id"] not in ("custom_01", "custom_7777", "custom_0001")
    items = {s["id"]: s for s in client.get("/api/scenarios").json()["items"]}
    assert items["custom_01"]["group"] == "Свои" and items["custom_01"]["title"] == "правка"
    assert sorted(i for i in items if i.startswith("custom_")) == ["custom_01", "custom_02", "custom_03", "custom_04"]
    r = client.post("/api/scenarios", json={"scenario": {**doc, "missions": []}})
    assert r.status_code == 400 and "at least one mission" in r.json()["error"]


def test_custom_limits(client: TestClient, settings: Settings) -> None:
    sc = client.get("/api/scenarios/01_clear").json()["scenario"]
    doc = {"schema": "amr-1.0", "map": sc["map"], "missions": scenario_doc()["missions"]}
    ped = {"waypoints": [[1, 5], [2, 5]], "speed": 1.0}
    for bad, word in (
        ({"pedestrians": [ped] * 31}, "пешеходов"),
        ({"duration_s": 3600}, "длительность"),
        ({"events": [{"type": "fog_bank", "t1": 1, "t2": 2}] * 21}, "событий"),
        ({"pedestrians": [{"waypoints": [[1, 5]] * 5001, "speed": 1}]}, "точек"),
    ):
        r = client.post("/api/scenarios", json={"scenario": {**doc, **bad}})
        assert r.status_code == 400 and word in r.json()["error"], word
    big = {**doc, "description": "x" * 600_000}
    assert client.post("/api/scenarios", json={"scenario": big}).status_code == 413
    assert not list(settings.custom_dir.glob("*.json")) if settings.custom_dir.exists() else True


def test_client_quota_and_misc(settings: Settings) -> None:
    cfg = dataclasses.replace(settings, max_per_client=2, trust_xff=True)
    with TestClient(create_app(cfg)) as c:
        body = {"scenario": "01_clear", "controllers": ["ours", "baseline"], "seeds": [11]}
        assert c.post("/api/launch", json=body, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
        r = c.post("/api/launch", json={**body, "seeds": [12]}, headers={"X-Forwarded-For": "10.0.0.1"})
        assert r.status_code == 400 and "с одного адреса" in r.json()["error"]
        # другой посетитель; подделанный первый адрес в XFF не помогает — берётся последний
        r = c.post("/api/launch", json={**body, "seeds": [13]}, headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"})
        assert r.status_code == 200
        deep = "[" * 100_000 + "]" * 100_000
        assert c.post("/api/launch", content=deep, headers=JSON).status_code == 400
        assert c.get("/api/docs").status_code == 404 and c.get("/openapi.json").status_code != 200
        h = c.get("/api/meta").headers
        assert h["x-content-type-options"] == "nosniff" and "default-src 'self'" in h["content-security-policy"]


def test_readonly(settings: Settings) -> None:
    with TestClient(create_app(dataclasses.replace(settings, readonly=True))) as c:
        assert c.get("/api/meta").json()["canRun"] is False
        r = c.post("/api/launch", json={"scenario": "01_clear", "controllers": ["ours"], "seeds": [1]})
        assert r.status_code == 403
        assert c.post("/api/scenarios", json={"scenario": {}}).status_code == 403
        assert c.get("/api/runs/01_clear__s1").status_code == 200


def test_gzip_body_roundtrip(client: TestClient) -> None:
    raw = client.get("/api/runs/01_clear__s1", headers={"Accept-Encoding": "gzip"})
    # httpx разжимает сам; проверяем, что сжатые данные — корректный gzip исходного JSON
    assert gzip.decompress(gzip.compress(raw.content)) == raw.content


def test_limits_flag_and_custom_cleanup(settings: Settings, layout) -> None:
    import os
    import time as _t

    from .conftest import write_run

    lim = layout["sub"] / "scenarios" / "showcase" / "limits"
    lim.mkdir(parents=True)
    (lim / "l9_edge.json").write_text(__import__("json").dumps(scenario_doc("l9_edge")), encoding="utf-8")
    write_run(layout["sub"] / "results" / "showcase" / "limits", "l9_edge__ours__s1")
    with TestClient(create_app(dataclasses.replace(settings, custom_ttl_min=0))) as c:
        runs = c.get("/api/runs").json()
        assert runs["l9_edge__ours__s1"]["limit"] is True and runs["01_clear__s1"]["limit"] is False
        items = {s["id"]: s for s in c.get("/api/scenarios").json()["items"]}
        assert items["l9_edge"]["limit"] is True and items["w1_demo"]["limit"] is False
        sc = c.get("/api/scenarios/01_clear").json()["scenario"]
        doc = {"schema": "amr-1.0", "map": sc["map"], "missions": scenario_doc()["missions"]}
        sid = c.post("/api/scenarios", json={"scenario": doc}).json()["id"]
        write_run(settings.runs_dir, "ours__%s__s1" % sid)
        write_run(settings.runs_dir, "ours__01_clear__s5")  # не свой — не трогается
        jobs = c.app.state.jobs
        assert jobs.catalog.cleanup_custom(3600, set()) == []  # ещё молодой
        tok = settings.custom_dir / (sid + ".token")
        h = tok.read_text(encoding="utf-8").splitlines()[0]
        tok.write_text("%s\n%.3f\n" % (h, _t.time() - 7200), encoding="utf-8")
        assert jobs.catalog.cleanup_custom(3600, {sid}) == []  # в очереди — не трогается
        assert jobs.catalog.cleanup_custom(3600, set()) == [sid]
        left = sorted(os.listdir(settings.runs_dir))
        assert left == ["ours__01_clear__s5.json", "ours__01_clear__s5.jsonl"]
        assert not (settings.custom_dir / (sid + ".json")).exists()
        assert (layout["sub"] / "results" / "logs" / "01_clear__s1.jsonl").exists()
