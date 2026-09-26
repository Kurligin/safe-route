"""Каталог данных: сценарии (симулятор, scenarios/ сдаваемого репозитория, свои) и прогоны.

Разбор файлов кэшируется по времени изменения, так что повторные запросы дешёвые, а
перезапуск прогона с тем же именем сразу виден.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from . import armcore, derive, limits
from .config import Settings

log = logging.getLogger("saferoute")

GROUP_ORDER = ("Открытые", "Учебные", "Скрытоподобные", "Стресс", "Проверочные", "Витрина", "Свои")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")
MAX_CUSTOM_NUM = 9999


class TooBig(ValueError):
    """Прогон слишком велик, чтобы отдавать его целиком."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


class Catalog:
    """Сценарии и прогоны из папок, заданных настройками."""

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        # одна запись на путь: (метка времени, данные) — перезапись файла не плодит записи
        self._scen_cache: dict[str, tuple[float, dict]] = {}
        self._lite: dict[str, tuple[tuple, dict]] = {}
        self._full: OrderedDict[str, tuple[tuple, dict, int]] = OrderedDict()  # LRU по байтам логов
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()

    # ------------------------------------------------------------ сценарии
    def scenario_files(self) -> dict[str, tuple[Path, str]]:
        """id сценария -> (путь, группа). Первым находится сценарий симулятора."""
        out: dict[str, tuple[Path, str]] = {}
        srcs = [(self.cfg.submission / "scenarios", "repo"), (self.cfg.custom_dir, "custom")]
        if self.cfg.sim:
            srcs.insert(0, (self.cfg.sim / "scenarios", "sim"))
        for folder, where in srcs:
            if not folder.is_dir():
                continue
            # scenarios/ сдаваемого репозитория — рекурсивно (витрина лежит в scenarios/showcase/**)
            files = folder.rglob("*.json") if where == "repo" else folder.glob("*.json")
            for p in sorted(files):
                if SAFE_ID.match(p.stem):
                    out.setdefault(p.stem, (p, scenario_group(p.stem, where, p.relative_to(folder))))
        return out

    def scenario_data(self, p: Path) -> dict:
        mt = p.stat().st_mtime
        with self._lock:
            hit = self._scen_cache.get(str(p))
        if hit is None or hit[0] != mt:
            hit = (mt, armcore.load_scenario(p))
            with self._lock:
                self._scen_cache[str(p)] = hit
        return hit[1]

    def limit_ids(self) -> set[str]:
        """Сценарии витрины «граница возможностей» (scenarios/showcase/limits): в списках скрыты по умолчанию."""
        folder = self.cfg.submission / "scenarios" / "showcase" / "limits"
        return {p.stem for p in folder.glob("*.json")} if folder.is_dir() else set()

    def scenarios(self) -> tuple[list[dict], dict | None]:
        """Список сценариев со сводкой (без карты) и базовая карта для конструктора.

        Базовая карта — карта первого открытого сценария (у скрытоподобных своя тень ГНСС,
        поэтому конструктор при открытии сценария берёт карту из него самого).
        """
        items: list[dict] = []
        limit = self.limit_ids()
        base_map, base_open = None, False
        for sid, (p, grp) in self.scenario_files().items():
            try:
                d = dict(self.scenario_data(p))
            except (OSError, ValueError, KeyError, TypeError) as e:
                log.warning("пропущен сценарий %s: %s", sid, e)
                continue
            m = d.pop("map", None)
            d.pop("generator", None)
            if m and (base_map is None or (grp == "Открытые" and not base_open)):
                base_map, base_open = m, grp == "Открытые"
            title = d["description"] if grp == "Свои" else ""
            items.append({"id": sid, "group": grp, "title": title, "limit": sid in limit, "scenario": d})
        items.sort(key=lambda s: (GROUP_ORDER.index(s["group"]), s["id"]))
        return items, base_map

    def scenario(self, sid: str) -> tuple[Path, str] | None:
        if not SAFE_ID.match(sid or ""):
            return None
        return self.scenario_files().get(sid)

    def validate_scenario(self, path: Path) -> str | None:
        """Проверка сценария схемой самого симулятора. None — сценарий годен."""
        if not self.cfg.sim:
            return "папка симулятора не найдена: проверить сценарий нечем"
        code = "import sys\nfrom amrsim.schema import load_scenario\nload_scenario(sys.argv[1])\n"
        try:
            r = subprocess.run(
                [self.cfg.python, "-c", code, str(path)],
                cwd=str(self.cfg.sim),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return "не удалось проверить сценарий: %s" % e
        if r.returncode:
            lines = [ln for ln in (r.stderr or r.stdout).strip().splitlines() if ln.strip()]
            msg = lines[-1] if lines else "ошибка проверки"
            msg = re.sub(r"^[\w.]+Error: ", "", msg).replace(str(path), "сценарий")
            return msg.replace(str(self.cfg.sim), "amrsim")
        return None

    def _next_id(self, existing: list[str]) -> str:
        nums = [int(m.group(1)) for m in (armcore.CUSTOM_ID.match(x) for x in existing) if m]
        n = max(nums, default=0) + 1
        if n > MAX_CUSTOM_NUM:
            raise ValueError("номера своих сценариев закончились")
        return "custom_%02d" % n

    def _may_overwrite(self, sid: Any, token: Any) -> bool:
        """Перезаписать можно только свой сценарий: id выдан сервером и токен правки совпал."""
        if not (isinstance(sid, str) and isinstance(token, str) and armcore.is_custom_id(sid) and token):
            return False
        if sid != "custom_%02d" % int(sid[7:]):  # только нормальная форма: custom_01, не custom_0001
            return False
        folder = self.cfg.custom_dir
        tf = folder / (sid + ".token")
        if not (folder / (sid + ".json")).is_file() or not tf.is_file():
            return False
        stored = (tf.read_text(encoding="utf-8").splitlines() or [""])[0].strip()
        return hmac.compare_digest(stored, _hash(token))

    def _created(self, sid: str) -> float | None:
        """Когда сценарий создан: вторая строка файла токена (первое сохранение), иначе mtime."""
        tf = self.cfg.custom_dir / (sid + ".token")
        try:
            lines = tf.read_text(encoding="utf-8").splitlines()
            return float(lines[1])
        except (OSError, IndexError, ValueError):
            f = self.cfg.custom_dir / (sid + ".json")
            return f.stat().st_mtime if f.is_file() else None

    def save_custom(self, sid: Any, token: Any, sc: Any) -> tuple[str, str]:
        """Сохранить сценарий конструктора. Возвращает (id, токен правки).

        id выдаёт только сервер. Существующий сценарий перезаписывается, только если клиент
        предъявил токен правки, полученный при первом сохранении; иначе сохраняется новый.
        """
        if not isinstance(sc, dict):
            raise ValueError("scenario должен быть объектом")
        refusal = limits.check(sc)
        if refusal:
            raise ValueError("сценарий вне пределов сервиса: " + refusal)
        folder = self.cfg.custom_dir
        folder.mkdir(parents=True, exist_ok=True)
        with self._save_lock:  # выбор нового id и запись — одним шагом
            created = time.time()
            if self._may_overwrite(sid, token):
                assert isinstance(sid, str) and isinstance(token, str)
                new_token = token
                created = self._created(sid) or created  # срок жизни считается от создания
            else:
                existing = [p.stem for p in folder.glob("custom_*.json")]
                if len(existing) >= self.cfg.max_custom:
                    raise ValueError("своих сценариев уже %d — это предел" % len(existing))
                sid = self._next_id(existing)
                new_token = secrets.token_urlsafe(18)
            sc["name"] = sid
            tmp = folder / (sid + ".check.tmp")
            tmp.write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
            err = self.validate_scenario(tmp)
            if err:
                tmp.unlink()
                raise ValueError("симулятор не принял сценарий: " + err)
            os.replace(tmp, folder / (sid + ".json"))
            (folder / (sid + ".token")).write_text("%s\n%.3f\n" % (_hash(new_token), created), encoding="utf-8")
        return sid, new_token

    def cleanup_custom(self, ttl_s: float, busy: set[str]) -> list[str]:
        """Удалить свои сценарии старше `ttl_s` от создания и их прогоны в папке прогонов сервиса.

        Прогоны из results/ и доп. папок не трогаются; сценарии с идущими заданиями (`busy`) — тоже.
        Возвращает удалённые id.
        """
        folder, now, removed = self.cfg.custom_dir, time.time(), []
        if not folder.is_dir():
            return removed
        with self._save_lock:
            for f in sorted(folder.glob("custom_*.json")):
                sid = f.stem
                created = self._created(sid)
                if not armcore.is_custom_id(sid) or sid in busy or created is None or now - created < ttl_s:
                    continue
                for extra in (f, folder / (sid + ".token"), folder / (sid + ".check.tmp")):
                    extra.unlink(missing_ok=True)
                removed.append(sid)
        runs = self.cfg.runs_dir
        if runs.is_dir():  # прогоны удалённых и давно пропавших своих сценариев
            alive = {p.stem for p in folder.glob("custom_*.json")} if folder.is_dir() else set()
            for f in runs.iterdir():
                parts = f.name.split("__")
                if len(parts) != 3 or not armcore.is_custom_id(parts[1]) or parts[1] in alive or parts[1] in busy:
                    continue
                if parts[1] in removed or now - f.stat().st_mtime >= ttl_s:
                    f.unlink(missing_ok=True)
        with self._lock:  # записи кэшей удалённых файлов больше не нужны
            for cache in (self._scen_cache, self._lite, self._full):
                for key in [k for k in cache if not Path(k).exists()]:
                    del cache[key]
        return removed

    # ------------------------------------------------------------ прогоны
    def run_dirs(self) -> list[Path]:
        return [self.cfg.submission / "results", self.cfg.runs_dir, *self.cfg.extra_runs]

    def run_files(self) -> dict[str, tuple[Path, Path | None]]:
        return armcore.find_runs(*self.run_dirs())

    @staticmethod
    def _stamp(logf: Path, rep: Path | None) -> tuple:
        return (logf.stat().st_mtime, rep.stat().st_mtime if rep else 0.0)

    def run_lite(self, logf: Path, rep: Path | None) -> dict:
        key = self._stamp(logf, rep)
        with self._lock:
            hit = self._lite.get(str(logf))
        if hit is None or hit[0] != key:
            hit = (key, armcore.load_run(logf, rep, full=False))
            with self._lock:
                self._lite[str(logf)] = hit
        return hit[1]

    def run_full(self, logf: Path, rep: Path | None) -> dict:
        key = self._stamp(logf, rep)
        size = logf.stat().st_size
        with self._lock:
            hit = self._full.get(str(logf))
            if hit and hit[0] == key:
                self._full.move_to_end(str(logf))
                return hit[1]
        if size > self.cfg.max_log_mb * 1_000_000:
            raise TooBig("лог прогона больше %d МБ — целиком не показывается" % self.cfg.max_log_mb)
        d = armcore.load_run(logf, rep, full=True)
        d["stops"] = derive.stops(d["ticks"])
        with self._lock:
            self._full[str(logf)] = (key, d, size)
            self._full.move_to_end(str(logf))
            budget = self.cfg.full_cache_mb * 1_000_000
            while len(self._full) > 1 and sum(v[2] for v in self._full.values()) > budget:
                self._full.popitem(last=False)
        return d

    def runs(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        limit = self.limit_ids()
        for k, (logf, rep) in self.run_files().items():
            try:
                lite = self.run_lite(logf, rep)
                out[k] = {**lite, "limit": lite["scenario"] in limit or "limits" in logf.parent.parts}
            except (OSError, ValueError, KeyError, TypeError) as e:
                log.warning("пропущен прогон %s: %s", k, e)
        return out

    def run(self, key: str, full: bool = True) -> dict | None:
        if not SAFE_ID.match(key or ""):
            return None
        found = self.run_files().get(key)
        if not found:
            return None
        return self.run_full(*found) if full else self.run_lite(*found)
