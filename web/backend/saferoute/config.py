"""Настройки сервиса из переменных окружения.

Все пути задаются снаружи: в контейнере это копии сдаваемого репозитория и симулятора,
локально — папки проекта. Значения по умолчанию подходят для запуска из репозитория
в раскладке `repos/safe-route-web` + `repos/safe-route` + `inbox/amrsim-participants`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2]  # корень репозитория safe-route-web


def _env_path(name: str, default: Path | None) -> Path | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return Path(raw).expanduser().resolve() if raw.strip() else None


def _env_paths(name: str) -> list[Path]:
    raw = os.environ.get(name, "")
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except ValueError:
        return default
    return max(lo, min(hi, v))


def _env_set(name: str, default: str) -> frozenset[str]:
    return frozenset(h.strip().lower() for h in os.environ.get(name, default).split(",") if h.strip())


@dataclass(frozen=True)
class Settings:
    """Настройки сервиса. Поля — см. README, раздел «Переменные окружения»."""

    submission: Path  # сдаваемый репозиторий: controller.py, results/, scenarios/
    sim: Path | None  # папка симулятора организаторов: amrsim/, scenarios/, baseline/
    python: str  # интерпретатор с numpy, которым запускается симулятор
    runs_dir: Path  # прогоны, запущенные из сервиса
    custom_dir: Path  # свои сценарии из конструктора
    extra_runs: list[Path] = field(default_factory=list)  # ещё папки с прогонами (только чтение)
    static_dir: Path | None = None  # собранный фронтенд (vite build)
    parallel: int = 2
    timeout_s: int = 700  # предел симулятора 600 с плюс запас
    readonly: bool = False
    allowed_hosts: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
    max_jobs_per_request: int = 12
    max_queued: int = 60
    max_per_client: int = 12  # активных заданий (в очереди и идущих) с одного адреса
    max_custom: int = 200
    max_runs: int = 2000
    max_runs_mb: int = 3000  # объём папки прогонов сервиса
    max_log_mb: int = 30  # больший лог целиком не отдаётся
    full_cache_mb: int = 150  # кэш разобранных прогонов, по размеру логов
    custom_timeout_s: int = 180  # предел прогона своего сценария
    custom_ttl_min: int = 60  # свои сценарии и их прогоны живут столько минут от создания; 0 — вечно
    trust_xff: bool = False  # адрес клиента — из X-Forwarded-For (только за своим прокси)
    max_body: int = 5_000_000

    @classmethod
    def from_env(cls) -> Settings:
        # две раскладки: веб внутри сдаваемого репозитория (safe-route/web) или рядом с ним
        # (repos/safe-route-web + repos/safe-route); симулятор — рядом с репозиторием или в inbox/
        parent = WEB_ROOT.parent
        sub_default = parent if (parent / "controller.py").is_file() else parent / "safe-route"
        sims = [sub_default.parent / "amrsim-participants", parent.parent / "inbox" / "amrsim-participants"]
        sim_default = next((p for p in sims if (p / "amrsim").is_dir()), None)
        static_default = WEB_ROOT / "frontend" / "dist"
        return cls(
            submission=_env_path("SAFEROUTE_SUBMISSION", sub_default) or sub_default,
            sim=_env_path("SAFEROUTE_SIM", sim_default),
            python=os.environ.get("SAFEROUTE_PYTHON") or sys.executable,
            runs_dir=_env_path("SAFEROUTE_RUNS", WEB_ROOT / "var" / "runs") or WEB_ROOT / "var" / "runs",
            custom_dir=_env_path("SAFEROUTE_CUSTOM", WEB_ROOT / "var" / "custom") or WEB_ROOT / "var" / "custom",
            extra_runs=_env_paths("SAFEROUTE_EXTRA_RUNS"),
            static_dir=_env_path("SAFEROUTE_STATIC", static_default),
            parallel=_env_int("SAFEROUTE_PARALLEL", 2, 1, 3),
            timeout_s=_env_int("SAFEROUTE_TIMEOUT", 700, 30, 3600),
            readonly=_env_flag("SAFEROUTE_READONLY"),
            allowed_hosts=_env_set("SAFEROUTE_ALLOWED_HOSTS", "127.0.0.1,localhost,::1"),
            max_jobs_per_request=_env_int("SAFEROUTE_MAX_JOBS_PER_REQUEST", 12, 1, 200),
            max_queued=_env_int("SAFEROUTE_MAX_QUEUED", 60, 1, 1000),
            max_per_client=_env_int("SAFEROUTE_MAX_PER_CLIENT", 12, 1, 1000),
            max_custom=_env_int("SAFEROUTE_MAX_CUSTOM", 200, 1, 9999),
            max_runs=_env_int("SAFEROUTE_MAX_RUNS", 2000, 10, 100_000),
            max_runs_mb=_env_int("SAFEROUTE_MAX_RUNS_MB", 3000, 10, 1_000_000),
            max_log_mb=_env_int("SAFEROUTE_MAX_LOG_MB", 30, 1, 1000),
            full_cache_mb=_env_int("SAFEROUTE_FULL_CACHE_MB", 150, 10, 10_000),
            custom_timeout_s=_env_int("SAFEROUTE_CUSTOM_TIMEOUT", 180, 30, 3600),
            custom_ttl_min=_env_int("SAFEROUTE_CUSTOM_TTL_MIN", 60, 0, 100_000),
            trust_xff=_env_flag("SAFEROUTE_TRUST_XFF"),
        )
