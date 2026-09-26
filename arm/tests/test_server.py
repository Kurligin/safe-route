"""Тесты сервера рабочего места: группы сценариев, очередь, защита POST, HTTP на живом порту."""

import http.client
import json
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

SCEN = "gen_000_AWA"  # сценарий из scenarios/ репозитория: есть и без папки симулятора


class GroupTest(unittest.TestCase):
    def test_groups(self) -> None:
        self.assertEqual(server.scenario_group("01_clear", "sim"), "Открытые")
        self.assertEqual(server.scenario_group("02e_gnss_shadow_easy", "sim"), "Учебные")
        self.assertEqual(server.scenario_group("gen_012_WCB", "repo"), "Скрытоподобные")
        self.assertEqual(server.scenario_group("stress_swarm_007_WCB", "repo"), "Стресс")
        self.assertEqual(server.scenario_group("own_pallet_drop", "repo"), "Проверочные")
        self.assertEqual(server.scenario_group("custom_01", "custom"), "Свои")


class CfgCase(unittest.TestCase):
    """Меняет CFG на время теста и чистит очередь (воркеры в тестах не запущены)."""

    cfg: dict = {}

    def setUp(self) -> None:
        self.saved = dict(server.CFG)
        server.CFG.update(self.cfg)
        self.jobs = dict(server.JOBS)

    def tearDown(self) -> None:
        server.CFG.clear()
        server.CFG.update(self.saved)
        server.JOBS.clear()
        server.JOBS.update(self.jobs)
        while not server._queue.empty():
            server._queue.get_nowait()


class WithoutSimulatorTest(CfgCase):
    cfg = {"sim": None, "can_run": False, "reason": "нет симулятора"}

    def test_launch_refused(self) -> None:
        with self.assertRaises(ValueError):
            server.launch_many("01_clear", ["ours"], [1])

    def test_validation_needs_simulator(self) -> None:
        self.assertIn("симулятор", server.validate_scenario(Path("x.json")))


class LaunchTest(CfgCase):
    cfg = {"can_run": True, "readonly": False}

    def test_whole_request_or_nothing(self) -> None:
        before = len(server.JOBS)
        with self.assertRaises(ValueError):
            server.launch_many(SCEN, ["ours"], [7, -1])
        for bad in ([1.0], [True], ["1"], [10**12]):
            with self.assertRaises(ValueError):
                server.launch_many(SCEN, ["ours"], bad)
        with self.assertRaises(ValueError):
            server.launch_many(SCEN, ["ours", "evil"], [1])
        self.assertEqual(len(server.JOBS), before)

    def test_queue_and_duplicates(self) -> None:
        ids = server.launch_many(SCEN, ["ours", "baseline"], [1, 2])
        self.assertEqual(len(ids), 4)
        self.assertEqual(server.launch_many(SCEN, ["ours"], [1]), ids[:1])  # тот же прогон ещё в очереди
        self.assertEqual(server._queue.qsize(), 4)

    def test_limits(self) -> None:
        with self.assertRaises(ValueError):
            server.launch_many(SCEN, ["ours"], list(range(server.MAX_JOBS_PER_REQUEST + 1)))
        for start in range(0, server.MAX_QUEUED, server.MAX_JOBS_PER_REQUEST):
            server.launch_many(SCEN, ["ours"], list(range(start, min(start + 40, server.MAX_QUEUED))))
        with self.assertRaises(ValueError):
            server.launch_many(SCEN, ["baseline"], [1])

    def test_readonly(self) -> None:
        server.CFG["readonly"] = True
        with self.assertRaises(ValueError):
            server.launch_many(SCEN, ["ours"], [1])


class HttpTest(CfgCase):
    cfg = {"can_run": True, "readonly": False, "hosts": {"127.0.0.1", "localhost"}}

    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(self.base + path) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def post(self, body: bytes, headers: dict) -> int:
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/api/launch", skip_host=True)
        for k, v in {"Host": "127.0.0.1:%d" % self.port, **headers}.items():
            if v is not None:
                c.putheader(k, v)
        c.endheaders(body)
        code = c.getresponse().status
        c.close()
        return code

    def test_index_and_static(self) -> None:
        code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"/data.js", body)
        self.assertEqual(self.get("/static/app.js")[0], 200)
        self.assertEqual(self.get("/static/../server.py")[0], 404)

    def test_data_js(self) -> None:
        code, body = self.get("/data.js")
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        for name in ("RUNS", "SCENS", "SCEN_LIST", "CTRLS", "BASEMAP", "ARM"):
            self.assertIn("window.%s = " % name, text)

    def test_scenario_with_map_and_raw(self) -> None:
        code, body = self.get("/api/scenario/" + SCEN)
        d = json.loads(body)["scenario"]
        self.assertEqual(code, 200)
        self.assertIn("zones", d["map"])
        self.assertIsNotNone(d["generator"])
        code, raw = self.get("/api/scenario/%s?raw=1" % SCEN)
        self.assertEqual(raw, (server.REPO / "scenarios" / (SCEN + ".json")).read_bytes())

    def test_unknown_run_and_scenario(self) -> None:
        self.assertEqual(self.get("/api/run/nope")[0], 404)
        self.assertEqual(self.get("/api/scenario/nope")[0], 404)

    def test_jobs_list(self) -> None:
        code, body = self.get("/api/jobs")
        self.assertEqual(code, 200)
        self.assertIsInstance(json.loads(body), list)

    def test_post_guards(self) -> None:
        body = json.dumps({"scenario": SCEN, "controllers": ["ours"], "seeds": [3]}).encode()
        n = str(len(body))
        js = {"Content-Type": "application/json", "Content-Length": n}
        self.assertEqual(self.post(body, {"Content-Type": "text/plain", "Content-Length": n}), 415)
        self.assertEqual(self.post(body, {**js, "Origin": "http://evil.example"}), 403)
        self.assertEqual(self.post(body, {**js, "Host": "evil.example"}), 403)
        self.assertEqual(self.post(body, {**js, "Content-Length": "abc"}), 411)
        self.assertEqual(self.post(body, {**js, "Content-Length": "-1"}), 413)
        bad = json.dumps({"scenario": SCEN, "controllers": ["ours"], "seeds": [1e308 * 10]}).encode()
        self.assertEqual(self.post(bad, {"Content-Type": "application/json", "Content-Length": str(len(bad))}), 400)
        self.assertEqual(self.post(body, {**js, "Origin": "http://127.0.0.1:%d" % self.port}), 200)
        server.CFG["readonly"] = True
        self.assertEqual(self.post(body, js), 403)


if __name__ == "__main__":
    unittest.main()
