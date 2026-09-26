"""Очередь прогонов симулятора: пул из `parallel` воркеров над общей очередью.

Каждый прогон — `python -m amrsim run <сценарий> --controller ... --seed ...` в папке
симулятора. Симулятор пишет во временные файлы `.part`, в папку прогонов попадает только
готовая пара «лог + отчёт».
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import armcore
from .catalog import Catalog
from .config import Settings

log = logging.getLogger("saferoute")
MAX_KEPT = 300  # завершённых заданий в памяти
STATE_ACTIVE = ("queued", "run")


class LaunchError(ValueError):
    """Запрос на запуск отклонён целиком: ни одно задание не поставлено."""


class JobQueue:
    def __init__(self, cfg: Settings, catalog: Catalog) -> None:
        self.cfg = cfg
        self.catalog = catalog
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._durations: list[float] = []
        self._started = False
        self.can_run, self.reason = False, ""

    # ------------------------------------------------------------ готовность
    def check_runner(self) -> None:
        """Можно ли запускать прогоны: есть симулятор, интерпретатор видит numpy и amrsim."""
        if not self.cfg.sim:
            self.can_run, self.reason = False, "папка симулятора не найдена (SAFEROUTE_SIM)"
            return
        try:
            r = subprocess.run(
                [self.cfg.python, "-c", "import numpy, amrsim"],
                cwd=str(self.cfg.sim),
                capture_output=True,
                text=True,
                timeout=60,
            )
            ok, why = r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1]
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, why = False, str(e)
        self.can_run = ok
        self.reason = "" if ok else "интерпретатор %s не готов: %s (SAFEROUTE_PYTHON)" % (self.cfg.python, why)

    def ctrl_path(self, key: str) -> Path:
        if key == "baseline":
            assert self.cfg.sim is not None
            return self.cfg.sim / "baseline" / "controller.py"
        return self.cfg.submission / "controller.py"

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for _ in range(self.cfg.parallel):
            threading.Thread(target=self._worker, name="saferoute-run", daemon=True).start()
        if self.cfg.custom_ttl_min > 0:
            threading.Thread(target=self._janitor, name="saferoute-cleanup", daemon=True).start()

    CLEANUP_EVERY_S = 300

    def cleanup_once(self) -> list[str]:
        """Удалить устаревшие свои сценарии и их прогоны (кроме тех, что сейчас в очереди)."""
        with self._lock:
            busy = {j["scenario"] for j in self.jobs.values() if j["state"] in STATE_ACTIVE}
        removed = self.catalog.cleanup_custom(self.cfg.custom_ttl_min * 60, busy)
        if removed:
            log.warning("удалены свои сценарии старше %d мин: %s", self.cfg.custom_ttl_min, ", ".join(removed))
        return removed

    def _janitor(self) -> None:
        while True:
            try:
                self.cleanup_once()
            except Exception:  # noqa: BLE001 — фоновая уборка не должна умирать
                log.exception("сбой уборки своих сценариев")
            time.sleep(self.CLEANUP_EVERY_S)

    def avg_seconds(self) -> float:
        last = self._durations[-10:]
        return sum(last) / len(last) if last else 6.0

    # ------------------------------------------------------------ выполнение
    def _worker(self) -> None:
        while True:
            self._run_job(self._queue.get())

    def _run_job(self, jid: str) -> None:
        j = self.jobs[jid]
        j.update(state="run", started=time.time())
        try:
            self._execute(j)
        except Exception:  # noqa: BLE001 — задание не должно зависнуть в состоянии «идёт»
            log.exception("сбой задания %s", jid)
            j.update(state="error", error="сбой запуска прогона (подробности — в журнале сервиса)")
        j["finished"] = time.time()

    def _execute(self, j: dict[str, Any]) -> None:
        found = self.catalog.scenario(j["scenario"])
        if not found:
            j.update(state="error", error="сценарий пропал: %s" % j["scenario"])
            return
        p = found[0]
        stem = "%s__%s__s%d" % (j["controller"], j["scenario"], j["seed"])
        runs = self.cfg.runs_dir
        runs.mkdir(parents=True, exist_ok=True)
        logf, rep = runs / (stem + ".jsonl"), runs / (stem + ".json")
        log_tmp, rep_tmp = runs / (stem + ".jsonl.part"), runs / (stem + ".json.part")
        ctrl = self.ctrl_path(j["controller"])
        cmd = [
            self.cfg.python, "-m", "amrsim", "run", str(p), "--controller", str(ctrl),
            "--seed", str(j["seed"]), "--report", str(rep_tmp), "--log", str(log_tmp),
        ]  # fmt: skip
        shown = "baseline/controller.py" if j["controller"] == "baseline" else "controller.py"
        j["cmd"] = "python -m amrsim run %s --controller %s --seed %d --report runs/%s.json --log runs/%s.jsonl" % (
            p.name, shown, j["seed"], stem, stem,
        )  # fmt: skip
        limit = self.cfg.custom_timeout_s if found[1] == "Свои" else self.cfg.timeout_s
        try:
            out, _code = self._spawn(cmd, limit)
            j["out"] = self._scrub(out[-1500:], p)
            if rep_tmp.exists() and log_tmp.exists():
                os.replace(log_tmp, logf)
                os.replace(rep_tmp, rep)
                d = json.loads(rep.read_text(encoding="utf-8"))
                j.update(state="done", key=stem, total=(d.get("score") or {}).get("total", 0.0))
                self._durations.append(time.time() - j["started"])
            else:
                lines = [ln for ln in j["out"].strip().splitlines() if ln.strip()]
                j.update(state="error", error=lines[-1] if lines else "симулятор не записал отчёт")
        except subprocess.TimeoutExpired:
            j.update(state="error", error="превышен предел времени %d с" % limit)
        except OSError:
            log.exception("не удалось запустить симулятор")
            j.update(state="error", error="не удалось запустить симулятор")
        finally:
            for t in (log_tmp, rep_tmp):
                if t.exists():
                    t.unlink()

    def _spawn(self, cmd: list[str], limit: int) -> tuple[str, int]:
        """Запуск в своей группе процессов: по пределу времени убивается вся группа (с контроллером)."""
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.cfg.sim),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            out, _ = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise
        return out or "", proc.returncode

    def _scrub(self, text: str, scen: Path) -> str:
        """Вывод симулятора без внутренних путей сервиса."""
        text = text.replace(str(scen), scen.name)
        for base, short in (
            (self.cfg.runs_dir, "runs"),
            (self.cfg.custom_dir, "custom"),
            (self.cfg.submission, "safe-route"),
            (self.cfg.sim, "amrsim"),
        ):
            if base:
                text = text.replace(str(base), short)
        return text

    def _runs_usage(self) -> tuple[int, int]:
        """Число прогонов и объём папки прогонов сервиса, байт."""
        if not self.cfg.runs_dir.is_dir():
            return 0, 0
        n = size = 0
        for f in self.cfg.runs_dir.iterdir():
            if f.suffix == ".jsonl":
                n += 1
            if f.is_file():
                size += f.stat().st_size
        return n, size

    # ------------------------------------------------------------ постановка
    @staticmethod
    def _seed(v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 10**9:
            raise LaunchError("seed должен быть целым числом от 0 до 10^9: %r" % (v,))
        return v

    def launch(self, scenario: Any, controllers: Any, seeds: Any, client: str = "") -> list[str]:
        """Поставить в очередь все пары (контроллер, seed): либо все задания, либо ни одного.

        `client` — адрес посетителя: активных заданий с одного адреса не больше `max_per_client`.
        """
        if self.cfg.readonly:
            raise LaunchError("режим только просмотра: запуск выключен")
        if not self.can_run:
            raise LaunchError(self.reason or "запуск прогонов недоступен")
        if not isinstance(scenario, str) or not self.catalog.scenario(scenario):
            raise LaunchError("неизвестный сценарий: %s" % (scenario,))
        if not isinstance(controllers, list) or not isinstance(seeds, list) or not controllers or not seeds:
            raise LaunchError("controllers и seeds — непустые списки")
        for c in controllers:
            if not isinstance(c, str) or c not in armcore.CTRL_LABELS:
                raise LaunchError("неизвестный контроллер: %s" % (c,))
        pairs = list(dict.fromkeys((c, self._seed(s)) for c in controllers for s in seeds))
        if len(pairs) > self.cfg.max_jobs_per_request:
            raise LaunchError("за один запрос не больше %d прогонов" % self.cfg.max_jobs_per_request)
        n_runs, size = self._runs_usage()
        if n_runs + len(pairs) > self.cfg.max_runs:
            raise LaunchError("в папке прогонов уже %d прогонов — это предел сервиса" % n_runs)
        if size > self.cfg.max_runs_mb * 1_000_000:
            raise LaunchError("папка прогонов заняла больше %d МБ — это предел сервиса" % self.cfg.max_runs_mb)
        ids: list[str] = []
        fresh: list[str] = []
        with self._lock:
            active = {
                (j["scenario"], j["controller"], j["seed"]): j["id"]
                for j in self.jobs.values()
                if j["state"] in STATE_ACTIVE
            }
            queued = sum(1 for j in self.jobs.values() if j["state"] == "queued")
            new = [p for p in pairs if (scenario, *p) not in active]
            if queued + len(new) > self.cfg.max_queued:
                raise LaunchError("очередь заполнена: ждут %d прогонов, предел %d" % (queued, self.cfg.max_queued))
            mine = sum(1 for j in self.jobs.values() if j["state"] in STATE_ACTIVE and j.get("client") == client)
            if mine + len(new) > self.cfg.max_per_client:
                raise LaunchError(
                    "с одного адреса не больше %d прогонов в очереди, у вас уже %d — дождитесь завершения"
                    % (self.cfg.max_per_client, mine)
                )
            for c, s in pairs:
                jid = active.get((scenario, c, s))  # тот же прогон уже в работе: файлы общие
                if jid is None:
                    jid = uuid.uuid4().hex[:10]
                    self.jobs[jid] = {
                        "id": jid, "scenario": scenario, "controller": c, "seed": s,
                        "label": armcore.CTRL_LABELS[c], "state": "queued", "created": time.time(), "client": client,
                    }  # fmt: skip
                    fresh.append(jid)
                ids.append(jid)
            while len(self.jobs) > MAX_KEPT:  # старые завершённые не храним
                old = next((k for k, v in self.jobs.items() if v["state"] in ("done", "error")), None)
                if old is None:
                    break
                del self.jobs[old]
        for jid in fresh:
            self._queue.put(jid)
        return ids

    def view(self) -> list[dict[str, Any]]:
        now, eta = time.time(), self.avg_seconds()
        with self._lock:
            items = sorted(self.jobs.values(), key=lambda j: j["created"])
        out = []
        keys = ("id", "scenario", "controller", "label", "seed", "state", "key", "total", "error", "cmd")
        for j in items:
            v = {k: j.get(k) for k in keys}
            if j["state"] == "run":
                v["p"] = min(95.0, 100.0 * (now - j["started"]) / max(eta, 0.5))
                v["left"] = max(0.0, eta - (now - j["started"]))
            else:
                v["p"] = 100.0 if j["state"] in ("done", "error") else 0.0
                v["left"] = eta if j["state"] == "queued" else 0.0
            out.append(v)
        return out
