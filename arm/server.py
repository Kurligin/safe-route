"""Рабочее место оператора «Безопасный маршрут»: локальный веб-сервер на стандартной библиотеке.

Запуск из корня репозитория:
    python arm/server.py --sim /путь/к/amrsim-participants
и открыть http://127.0.0.1:8765 в браузере.

Сервер показывает прогоны (пары лог .jsonl + отчёт .json) из results/ и arm/runs/,
сценарии — из папки симулятора, scenarios/ репозитория и arm/custom/, и запускает
новые прогоны командой симулятора `run` (очередь, по два одновременно).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import armcore  # noqa: E402
import limits  # noqa: E402

ARM = Path(__file__).resolve().parent
REPO = ARM.parent
STATIC = ARM / "static"
RUNS_DIR = ARM / "runs"
CUSTOM_DIR = ARM / "custom"
MAX_JOBS_PER_REQUEST = 40  # прогонов за один запрос /api/launch
MAX_QUEUED = 120  # заданий, ожидающих очереди
MAX_BODY = 5_000_000  # байт в теле POST

CFG: dict[str, Any] = {
    "sim": None,  # папка симулятора
    "python": sys.executable,  # интерпретатор с numpy для прогонов
    "parallel": 2,
    "timeout": 700,  # с на прогон: предел симулятора 600 с плюс запас
    "can_run": False,
    "reason": "",
    "extra_runs": [],  # дополнительные папки с прогонами (--runs)
    "readonly": False,  # только просмотр: POST выключены
    "hosts": {"127.0.0.1", "localhost", "::1"},  # допустимые Host у POST (защита от DNS rebinding)
}
GROUP_ORDER = ("Открытые", "Учебные", "Скрытоподобные", "Стресс", "Проверочные", "Витрина", "Свои")
MAX_CUSTOM = 200  # своих сценариев
MAX_CUSTOM_NUM = 9999


def ctrl_path(key: str) -> Path:
    if key == "baseline":
        return CFG["sim"] / "baseline" / "controller.py"
    return REPO / "controller.py"


# ---------------------------------------------------------------- сценарии
def scenario_group(stem: str, where: str, rel: Path | None = None) -> str:
    if where == "sim":
        return "Учебные" if stem[2:3] == "e" else "Открытые"
    if where == "custom":
        return "Свои"
    if rel is not None and "showcase" in rel.parts[:-1]:
        return "Витрина"
    if stem.startswith("stress"):
        return "Стресс"
    if stem.startswith("gen_"):
        return "Скрытоподобные"
    return "Проверочные"


def scenario_files() -> dict[str, tuple[Path, str]]:
    """id сценария -> (путь, группа)."""
    out: dict[str, tuple[Path, str]] = {}
    srcs = [(REPO / "scenarios", "repo"), (CUSTOM_DIR, "custom")]
    if CFG["sim"]:
        srcs.insert(0, (CFG["sim"] / "scenarios", "sim"))
    for folder, where in srcs:
        # scenarios/ репозитория — рекурсивно: витрина лежит в scenarios/showcase/**
        for p in sorted(folder.rglob("*.json") if where == "repo" else folder.glob("*.json")):
            out.setdefault(p.stem, (p, scenario_group(p.stem, where, p.relative_to(folder))))
    return out


_scen_cache: dict[str, tuple[float, dict]] = {}  # одна запись на путь: перезапись файла не плодит записи


def scenario_data(p: Path) -> dict:
    mt = p.stat().st_mtime
    hit = _scen_cache.get(str(p))
    if hit is None or hit[0] != mt:
        hit = _scen_cache[str(p)] = (mt, armcore.load_scenario(p))
    return hit[1]


def validate_scenario(path: Path) -> str | None:
    """Проверка сценария схемой самого симулятора. None — сценарий годен."""
    if not CFG["sim"]:
        return "папка симулятора не найдена: проверить сценарий нечем"
    code = "import sys\nfrom amrsim.schema import load_scenario\nload_scenario(sys.argv[1])\n"
    try:
        r = subprocess.run(
            [CFG["python"], "-c", code, str(path)], cwd=str(CFG["sim"]), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return "не удалось проверить сценарий: %s" % e
    if r.returncode:
        lines = [ln for ln in (r.stderr or r.stdout).strip().splitlines() if ln.strip()]
        msg = lines[-1] if lines else "ошибка проверки"
        return re.sub(r"^[\w.]+Error: ", "", msg).replace(str(path), "сценарий").replace(str(CFG["sim"]), "amrsim")
    return None


_save_lock = threading.Lock()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _may_overwrite(sid: Any, token: Any) -> bool:
    """Перезаписать можно только свой сценарий: id выдан сервером и совпал токен правки."""
    if not (isinstance(sid, str) and isinstance(token, str) and token and armcore.is_custom_id(sid)):
        return False
    if sid != "custom_%02d" % int(sid[7:]):  # только нормальная форма: custom_01, не custom_0001
        return False
    tf = CUSTOM_DIR / (sid + ".token")
    if not (CUSTOM_DIR / (sid + ".json")).is_file() or not tf.is_file():
        return False
    return hmac.compare_digest(tf.read_text(encoding="utf-8").strip(), _token_hash(token))


def save_custom(payload: dict) -> tuple[str, str]:
    """Сохранить сценарий из конструктора в arm/custom/. Возвращает (id, токен правки).

    id выдаёт только сервер; существующий перезаписывается, только если предъявлен токен правки.
    """
    sc = payload["scenario"]
    if not isinstance(sc, dict):
        raise ValueError("scenario должен быть объектом")
    refusal = limits.check(sc)
    if refusal:
        raise ValueError("сценарий вне пределов: " + refusal)
    CUSTOM_DIR.mkdir(exist_ok=True)
    with _save_lock:  # выбор нового id и запись — одним шагом, иначе два сохранения получат один id
        sid, token = payload.get("id"), payload.get("token")
        if not _may_overwrite(sid, token):
            existing = [p.stem for p in CUSTOM_DIR.glob("custom_*.json")]
            if len(existing) >= MAX_CUSTOM:
                raise ValueError("своих сценариев уже %d — это предел" % len(existing))
            sid = armcore.next_custom_id(existing)
            if int(sid[7:]) > MAX_CUSTOM_NUM:
                raise ValueError("номера своих сценариев закончились")
            token = secrets.token_urlsafe(18)
        sc["name"] = sid
        tmp = CUSTOM_DIR / (sid + ".check.tmp")
        tmp.write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
        err = validate_scenario(tmp)
        if err:
            tmp.unlink()
            raise ValueError("симулятор не принял сценарий: " + err)
        os.replace(tmp, CUSTOM_DIR / (sid + ".json"))
        (CUSTOM_DIR / (sid + ".token")).write_text(_token_hash(token), encoding="utf-8")
    return sid, token


# ---------------------------------------------------------------- прогоны
def run_dirs() -> list[Path]:
    return [REPO / "results", RUNS_DIR] + [Path(d) for d in CFG["extra_runs"]]


def all_runs() -> dict[str, tuple[Path, Path | None]]:
    return armcore.find_runs(*run_dirs())


_lite_cache: dict[str, tuple[tuple, dict]] = {}  # одна запись на лог
_full_cache: OrderedDict[str, tuple[tuple, dict]] = OrderedDict()
_cache_lock = threading.Lock()


def _stamp(log: Path, rep: Path | None) -> tuple:
    return (log.stat().st_mtime, rep.stat().st_mtime if rep else 0.0)


def run_lite(log: Path, rep: Path | None) -> dict:
    key = _stamp(log, rep)
    with _cache_lock:
        hit = _lite_cache.get(str(log))
    if hit is None or hit[0] != key:
        hit = (key, armcore.load_run(log, rep, full=False))
        with _cache_lock:
            _lite_cache[str(log)] = hit
    return hit[1]


def run_full(log: Path, rep: Path | None) -> dict:
    key = _stamp(log, rep)
    with _cache_lock:
        hit = _full_cache.get(str(log))
        if hit and hit[0] == key:
            _full_cache.move_to_end(str(log))
            return hit[1]
    d = armcore.load_run(log, rep, full=True)
    with _cache_lock:
        _full_cache[str(log)] = (key, d)
        _full_cache.move_to_end(str(log))
        while len(_full_cache) > 8:
            _full_cache.popitem(last=False)
    return d


def data_js() -> bytes:
    runs = {}
    lim_dir = REPO / "scenarios" / "showcase" / "limits"  # витрина «граница возможностей»
    limit = {p.stem for p in lim_dir.glob("*.json")} if lim_dir.is_dir() else set()
    for k, (log, rep) in all_runs().items():
        try:
            lite = run_lite(log, rep)
            runs[k] = {**lite, "limit": lite["scenario"] in limit or "limits" in log.parent.parts}
        except (OSError, ValueError, KeyError) as e:
            print("пропущен прогон %s: %s" % (k, e), file=sys.stderr)
    scens, lst, base_map, base_open = {}, [], None, False
    for sid, (p, grp) in scenario_files().items():
        try:
            d = dict(scenario_data(p))
        except (OSError, ValueError, KeyError) as e:
            print("пропущен сценарий %s: %s" % (sid, e), file=sys.stderr)
            continue
        m = d.pop("map", None)
        d.pop("generator", None)  # конструктор берёт сценарий целиком через /api/scenario/<id>
        if m and (base_map is None or (grp == "Открытые" and not base_open)):
            base_map, base_open = m, grp == "Открытые"
        scens[sid] = d
        lst.append({"id": sid, "group": grp, "title": d["description"] if grp == "Свои" else "", "limit": sid in limit})
    lst.sort(key=lambda s: (GROUP_ORDER.index(s["group"]), s["id"]))
    info = {
        "canRun": CFG["can_run"] and not CFG["readonly"],
        "readonly": CFG["readonly"],
        "reason": "режим только просмотра (--readonly)" if CFG["readonly"] else CFG["reason"],
        "parallel": CFG["parallel"],
        "avgS": round(avg_job_seconds(), 1),
    }
    ctrls = [{"key": k, "label": armcore.CTRL_LABELS[k]} for k in ("ours", "baseline")]
    parts = [("RUNS", runs), ("SCENS", scens), ("SCEN_LIST", lst), ("CTRLS", ctrls), ("BASEMAP", base_map),
             ("ARM", info)]  # fmt: skip
    return "".join(
        "window.%s = %s;\n" % (n, json.dumps(v, ensure_ascii=False, separators=(",", ":"))) for n, v in parts
    ).encode("utf-8")


# ---------------------------------------------------------------- очередь прогонов
JOBS: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_queue: queue.Queue[str] = queue.Queue()
_durations: list[float] = []


def avg_job_seconds() -> float:
    last = _durations[-10:]
    return sum(last) / len(last) if last else 6.0


def start_workers(n: int) -> None:
    """Пул из n воркеров над общей очередью: прогонов одновременно не больше n."""
    for _ in range(n):
        threading.Thread(target=_worker, daemon=True).start()


def _worker() -> None:
    while True:
        _run_job(_queue.get())


def _run_job(jid: str) -> None:
    j = JOBS[jid]
    j.update(state="run", started=time.time())
    try:
        _execute(j)
    except Exception as e:  # задание не должно зависнуть в состоянии «идёт»
        print("сбой задания %s: %r" % (jid, e), file=sys.stderr, flush=True)
        j.update(state="error", error="сбой запуска прогона (подробности — в выводе сервера)")
    j["finished"] = time.time()


def _execute(j: dict) -> None:
    """Один прогон симулятора. Пишет во временные файлы и переименовывает только готовую пару."""
    p, _ = scenario_files()[j["scenario"]]
    stem = "%s__%s__s%d" % (j["controller"], j["scenario"], j["seed"])
    RUNS_DIR.mkdir(exist_ok=True)
    log, rep = RUNS_DIR / (stem + ".jsonl"), RUNS_DIR / (stem + ".json")
    log_tmp, rep_tmp = RUNS_DIR / (stem + ".jsonl.part"), RUNS_DIR / (stem + ".json.part")
    ctrl = ctrl_path(j["controller"])
    cmd = [CFG["python"], "-m", "amrsim", "run", str(p), "--controller", str(ctrl), "--seed", str(j["seed"]),
           "--report", str(rep_tmp), "--log", str(log_tmp)]  # fmt: skip
    shown_ctrl = "baseline/controller.py" if j["controller"] == "baseline" else "controller.py"
    j["cmd"] = "python -m amrsim run %s --controller %s --seed %d --report arm/runs/%s.json --log arm/runs/%s.jsonl" % (
        p.name, shown_ctrl, j["seed"], stem, stem)  # fmt: skip
    try:
        r = subprocess.run(cmd, cwd=str(CFG["sim"]), capture_output=True, text=True, timeout=CFG["timeout"])
        j["out"] = _scrub((r.stdout + r.stderr)[-1500:], p)
        if rep_tmp.exists() and log_tmp.exists():
            os.replace(log_tmp, log)
            os.replace(rep_tmp, rep)
            d = json.loads(rep.read_text(encoding="utf-8"))
            j.update(state="done", key=stem, total=(d.get("score") or {}).get("total", 0.0))
            _durations.append(time.time() - j["started"])
        else:
            lines = [ln for ln in j["out"].strip().splitlines() if ln.strip()]
            j.update(state="error", error=lines[-1] if lines else "симулятор не записал отчёт")
    except subprocess.TimeoutExpired:
        j.update(state="error", error="превышен предел времени %d с" % CFG["timeout"])
    except OSError as e:
        print("не удалось запустить симулятор: %r" % e, file=sys.stderr, flush=True)
        j.update(state="error", error="не удалось запустить симулятор")
    finally:
        for t in (log_tmp, rep_tmp):
            if t.exists():
                t.unlink()


def _scrub(text: str, scen: Path) -> str:
    """Вывод симулятора без абсолютных путей."""
    text = text.replace(str(scen), scen.name).replace(str(REPO), ".")
    return text.replace(str(CFG["sim"]), "amrsim") if CFG["sim"] else text


def _seed(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 10**9:
        raise ValueError("seed должен быть целым числом от 0 до 10^9: %r" % (v,))
    return v


def launch_many(scenario: Any, controllers: Any, seeds: Any) -> list[str]:
    """Поставить в очередь все пары (контроллер, seed). Сначала проверяется весь запрос, потом ставится:
    либо все задания, либо ни одного."""
    if CFG["readonly"]:
        raise ValueError("режим только просмотра: запуск выключен")
    if not CFG["can_run"]:
        raise ValueError(CFG["reason"] or "запуск прогонов недоступен")
    if not isinstance(scenario, str) or scenario not in scenario_files():
        raise ValueError("неизвестный сценарий: %s" % (scenario,))
    if not isinstance(controllers, list) or not isinstance(seeds, list) or not controllers or not seeds:
        raise ValueError("controllers и seeds — непустые списки")
    for c in controllers:
        if c not in armcore.CTRL_LABELS:
            raise ValueError("неизвестный контроллер: %s" % (c,))
    pairs = list(dict.fromkeys((c, _seed(s)) for c in controllers for s in seeds))
    if len(pairs) > MAX_JOBS_PER_REQUEST:
        raise ValueError("за один запрос не больше %d прогонов" % MAX_JOBS_PER_REQUEST)
    ids, fresh = [], []
    with _jobs_lock:
        active = {(j["scenario"], j["controller"], j["seed"]): j["id"] for j in JOBS.values()
                  if j["state"] in ("queued", "run")}  # fmt: skip
        queued = sum(1 for j in JOBS.values() if j["state"] == "queued")
        new = [p for p in pairs if (scenario,) + p not in active]
        if queued + len(new) > MAX_QUEUED:
            raise ValueError("очередь заполнена: ждут %d прогонов, предел %d" % (queued, MAX_QUEUED))
        for c, s in pairs:
            jid = active.get((scenario, c, s))  # тот же прогон уже в работе: второй не нужен, файлы общие
            if jid is None:
                jid = uuid.uuid4().hex[:10]
                JOBS[jid] = {"id": jid, "scenario": scenario, "controller": c, "seed": s,
                             "label": armcore.CTRL_LABELS[c], "state": "queued", "created": time.time()}  # fmt: skip
                fresh.append(jid)
            ids.append(jid)
        while len(JOBS) > 300:  # старые завершённые не храним
            old = next((k for k, v in JOBS.items() if v["state"] in ("done", "error")), None)
            if old is None:
                break
            del JOBS[old]
    for jid in fresh:
        _queue.put(jid)
    return ids


def jobs_view() -> list[dict]:
    now, eta = time.time(), avg_job_seconds()
    out = []
    with _jobs_lock:
        items = sorted(JOBS.values(), key=lambda j: j["created"])
    for j in items:
        v = {k: j.get(k) for k in ("id", "scenario", "controller", "label", "seed", "state", "key", "total", "error",
                                   "cmd")}  # fmt: skip
        if j["state"] == "run":
            v["p"] = min(95.0, 100.0 * (now - j["started"]) / max(eta, 0.5))
            v["left"] = max(0.0, eta - (now - j["started"]))
        else:
            v["p"] = 100.0 if j["state"] in ("done", "error") else 0.0
            v["left"] = eta if j["state"] == "queued" else 0.0
        out.append(v)
    return out


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "SafeRouteARM/1.0"

    def log_message(self, *a: Any) -> None:
        pass

    def _send(self, code: int, body: bytes | str, ctype: str = "application/json; charset=utf-8") -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 2048
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")
        try:
            self._get(path, query)
        except (OSError, ValueError, KeyError) as e:
            print("ошибка GET %s: %r" % (path, e), file=sys.stderr, flush=True)
            self._json({"error": "внутренняя ошибка сервера"}, 500)

    def _get(self, path: str, query: str) -> None:
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/data.js":
            return self._send(200, data_js(), "application/javascript; charset=utf-8")
        if path.startswith("/static/"):
            f = (STATIC / path[len("/static/") :]).resolve()
            if STATIC in f.parents and f.is_file():
                ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype)
            return self._send(404, "not found", "text/plain; charset=utf-8")
        if path == "/api/jobs":
            return self._json(jobs_view())
        m = re.match(r"^/api/run/([A-Za-z0-9_.\-]+)$", path)
        if m:
            runs = all_runs()
            if m.group(1) not in runs:
                return self._json({"error": "нет такого прогона"}, 404)
            log, rep = runs[m.group(1)]
            return self._json(run_lite(log, rep) if "lite=1" in query else run_full(log, rep))
        m = re.match(r"^/api/scenario/([A-Za-z0-9_.\-]+)$", path)
        if m:
            sc = scenario_files().get(m.group(1))
            if not sc:
                return self._json({"error": "нет такого сценария"}, 404)
            if "raw=1" in query:  # исходный файл без пересборки — для «Скачать» в режиме просмотра
                return self._send(200, sc[0].read_bytes())
            return self._json({"id": m.group(1), "group": sc[1], "scenario": scenario_data(sc[0])})
        return self._send(404, "not found", "text/plain; charset=utf-8")

    def _post_refusal(self) -> tuple[int, str] | None:
        """Защита POST: только JSON, Host из списка и Origin той же страницы.

        Content-Type application/json заставляет браузер сделать preflight (OPTIONS), на который
        сервер не отвечает, так что чужая страница не может запустить прогон.
        """
        if CFG["readonly"]:
            return 403, "режим только просмотра: запуск и сохранение выключены"
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return 415, "нужен Content-Type: application/json"
        host = self.headers.get("Host") or ""
        if (urlsplit("//" + host).hostname or "").lower() not in CFG["hosts"]:
            return 403, "запрос к серверу по чужому имени: %s" % host
        origin = self.headers.get("Origin")
        if origin is not None and urlsplit(origin).netloc.lower() != host.lower():
            return 403, "запрос с чужой страницы: %s" % origin
        return None

    def do_POST(self) -> None:  # noqa: N802
        refusal = self._post_refusal()
        if refusal:
            return self._json({"error": refusal[1]}, refusal[0])
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self._json({"error": "нужен Content-Length"}, 411)
        if not 0 <= n <= (limits.MAX_BYTES + 4096 if self.path == "/api/scenario" else MAX_BODY):
            return self._json({"error": "слишком большой или неверный запрос"}, 413)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, RecursionError):
            return self._json({"error": "неверный JSON"}, 400)
        if not isinstance(payload, dict):
            return self._json({"error": "ожидался объект JSON"}, 400)
        try:
            if self.path == "/api/launch":
                ids = launch_many(payload.get("scenario"), payload.get("controllers"), payload.get("seeds"))
                return self._json({"jobs": ids})
            if self.path == "/api/scenario":
                sid, token = save_custom(payload)
                return self._json({"id": sid, "token": token})
        except (KeyError, ValueError, TypeError, OverflowError) as e:
            return self._json({"error": str(e)}, 400)
        except OSError as e:
            print("ошибка POST %s: %r" % (self.path, e), file=sys.stderr, flush=True)
            return self._json({"error": "внутренняя ошибка сервера"}, 500)
        return self._send(404, "not found", "text/plain; charset=utf-8")


def check_runner() -> None:
    """Можно ли запускать прогоны: есть папка симулятора и интерпретатор видит numpy и пакет симулятора."""
    if not CFG["sim"]:
        CFG.update(can_run=False, reason="папка симулятора не найдена (флаг --sim)")
        return
    try:
        r = subprocess.run([CFG["python"], "-c", "import numpy, amrsim"], cwd=str(CFG["sim"]), capture_output=True,
                           text=True, timeout=60)  # fmt: skip
        ok, why = r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1]
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, why = False, str(e)
    CFG.update(can_run=ok, reason="" if ok else "интерпретатор %s не готов: %s (флаг --python)" % (CFG["python"], why))


def find_sim(arg: str | None) -> Path | None:
    cands = [arg] if arg else [os.environ.get("AMRSIM_DIR"), str(REPO.parent / "amrsim-participants")]
    for c in cands:
        if c and (Path(c) / "scenarios").is_dir() and (Path(c) / "baseline" / "controller.py").is_file():
            return Path(c).resolve()
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Рабочее место оператора «Безопасный маршрут»")
    ap.add_argument("--sim", help="папка симулятора организаторов (в ней scenarios/ и baseline/); "
                                  "по умолчанию $AMRSIM_DIR или ../amrsim-participants")  # fmt: skip
    ap.add_argument("--python", default=sys.executable, help="интерпретатор с numpy для прогонов (по умолчанию этот)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--parallel", type=int, default=2, choices=(1, 2, 3, 4), help="прогонов одновременно")
    ap.add_argument("--runs", action="append", default=[], help="ещё папка с прогонами (можно несколько раз)")
    ap.add_argument("--readonly", action="store_true", help="только просмотр: без запуска прогонов и сохранения")
    ap.add_argument(
        "--allow-host", action="append", default=[], help="имя сервера для POST за reverse-proxy (можно несколько раз)"
    )
    a = ap.parse_args()
    CFG.update(sim=find_sim(a.sim), python=a.python, parallel=a.parallel, extra_runs=a.runs, readonly=a.readonly)
    CFG["hosts"] = {h.lower() for h in CFG["hosts"] | {a.host} | set(a.allow_host)}
    check_runner()
    start_workers(a.parallel)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("Рабочее место оператора: http://%s:%d" % (a.host, srv.server_address[1]), flush=True)
    print("симулятор: %s" % (CFG["sim"] or "не найден"), flush=True)
    state = "запускаются, по %d одновременно" % a.parallel if CFG["can_run"] else CFG["reason"]
    print("прогоны: %s" % ("только просмотр (--readonly)" if a.readonly else state), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
