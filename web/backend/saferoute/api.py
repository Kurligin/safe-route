"""HTTP API рабочего места оператора и раздача собранного интерфейса.

Чтение открыто. Запись (запуск прогонов, сохранение сценария) — только JSON-запросом с того
же адреса: проверяются Content-Type, Host из списка и Origin; флаг readonly выключает запись.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import armcore, derive, limits
from .catalog import Catalog, TooBig
from .config import Settings
from .jobs import JobQueue, LaunchError

log = logging.getLogger("saferoute")
JSON_TYPE = "application/json; charset=utf-8"
NO_STORE = {"Cache-Control": "no-store"}
# интерфейс без внешних ресурсов: скрипты, стили и шрифты только свои; inline-стили — атрибуты React
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
}


def _json(obj: Any, status: int = 200) -> Response:
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return Response(body.encode("utf-8"), status_code=status, media_type=JSON_TYPE, headers=NO_STORE)


def _err(msg: str, status: int) -> Response:
    return _json({"error": msg}, status)


def _csv(name: str, data: bytes) -> Response:
    disp = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
        name.encode("ascii", "replace").decode(),
        quote(name),
    )
    headers = {**NO_STORE, "Content-Disposition": disp}
    return Response(data, media_type="text/csv; charset=utf-8", headers=headers)


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or Settings.from_env()
    catalog = Catalog(cfg)
    jobs = JobQueue(cfg, catalog)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(jobs.check_runner)
        jobs.start()
        state = "по %d одновременно" % cfg.parallel if jobs.can_run else jobs.reason
        log.warning(
            "SafeRoute: симулятор %s; прогоны: %s",
            cfg.sim or "не найден",
            "только просмотр" if cfg.readonly else state,
        )
        yield

    app = FastAPI(title="SafeRoute · АРМ оператора", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=5)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if request.url.path.startswith("/assets/"):  # имена с хэшем содержимого
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    def client_of(request: Request) -> str:
        """Адрес посетителя: за своим прокси — последний адрес X-Forwarded-For (его дописал прокси)."""
        if cfg.trust_xff:
            xff = [a.strip() for a in (request.headers.get("x-forwarded-for") or "").split(",") if a.strip()]
            if xff:
                return xff[-1]
        return request.client.host if request.client else ""

    app.state.cfg, app.state.catalog, app.state.jobs = cfg, catalog, jobs

    def post_refusal(request: Request) -> Response | None:
        """Защита записи: readonly, только JSON (браузер сделает preflight), свой Host и Origin."""
        if cfg.readonly:
            return _err("режим только просмотра: запуск и сохранение выключены", 403)
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return _err("нужен Content-Type: application/json", 415)
        host = request.headers.get("host") or ""
        if (urlsplit("//" + host).hostname or "").lower() not in cfg.allowed_hosts:
            return _err("запрос к серверу по чужому имени: %s" % host, 403)
        origin = request.headers.get("origin")
        if origin is not None and urlsplit(origin).netloc.lower() != host.lower():
            return _err("запрос с чужой страницы: %s" % origin, 403)
        try:
            n = int(request.headers.get("content-length") or "")
        except ValueError:
            return _err("нужен Content-Length", 411)
        if not 0 <= n <= cfg.max_body:
            return _err("слишком большой или неверный запрос", 413)
        return None

    async def read_payload(request: Request, max_body: int | None = None) -> dict | Response:
        refusal = post_refusal(request)
        if refusal is not None:
            return refusal
        body = await request.body()
        if max_body is not None and len(body) > max_body:
            return _err("сценарий больше %d КБ" % (max_body // 1000), 413)
        try:
            payload = json.loads(body or b"{}")
        except (ValueError, RecursionError):
            return _err("неверный JSON", 400)
        if not isinstance(payload, dict):
            return _err("ожидался объект JSON", 400)
        return payload

    # ------------------------------------------------------------ чтение
    @app.get("/api/health")
    def health() -> Response:
        return _json({"ok": True})

    @app.get("/api/meta")
    def meta() -> Response:
        return _json(
            {
                "canRun": jobs.can_run and not cfg.readonly,
                "readonly": cfg.readonly,
                "reason": "режим только просмотра" if cfg.readonly else jobs.reason,
                "parallel": cfg.parallel,
                "avgS": round(jobs.avg_seconds(), 1),
                "controllers": [{"key": k, "label": armcore.CTRL_LABELS[k]} for k in ("ours", "baseline")],
            }
        )

    @app.get("/api/runs")
    def runs() -> Response:
        return _json(catalog.runs())

    @app.get("/api/runs/{key}")
    def run(key: str, lite: int = 0) -> Response:
        try:
            d = catalog.run(key, full=not lite)
        except TooBig as e:
            return _err(str(e), 413)
        return _err("нет такого прогона", 404) if d is None else _json(d)

    @app.get("/api/runs/{key}/trips.csv")
    def trips_csv(key: str) -> Response:
        d = catalog.run(key, full=False)
        if d is None:
            return _err("нет такого прогона", 404)
        return _csv("%s_рейсы.csv" % key, derive.to_csv(derive.trips_rows(d)))

    @app.get("/api/runs/{key}/stops.csv")
    def stops_csv(key: str) -> Response:
        try:
            d = catalog.run(key, full=True)
        except TooBig as e:
            return _err(str(e), 413)
        if d is None:
            return _err("нет такого прогона", 404)
        return _csv("%s_остановки.csv" % key, derive.to_csv(derive.stops_rows(d)))

    @app.get("/api/scenarios")
    def scenarios() -> Response:
        items, base_map = catalog.scenarios()
        return _json({"items": items, "baseMap": base_map})

    @app.get("/api/scenarios/{sid}")
    def scenario(sid: str, raw: int = 0) -> Response:
        found = catalog.scenario(sid)
        if not found:
            return _err("нет такого сценария", 404)
        path, group = found
        if raw:  # исходный файл без пересборки — для «Скачать» в режиме просмотра
            return FileResponse(path, media_type="application/json", filename=path.name, headers=NO_STORE)
        return _json({"id": sid, "group": group, "scenario": catalog.scenario_data(path)})

    @app.get("/api/jobs")
    def jobs_list() -> Response:
        return _json(jobs.view())

    # ------------------------------------------------------------ запись
    @app.post("/api/launch")
    async def launch(request: Request) -> Response:
        payload = await read_payload(request)
        if isinstance(payload, Response):
            return payload
        args = (payload.get("scenario"), payload.get("controllers"), payload.get("seeds"), client_of(request))
        try:
            ids = await run_in_threadpool(jobs.launch, *args)
        except LaunchError as e:
            return _err(str(e), 400)
        return _json({"jobs": ids})

    @app.post("/api/scenarios")
    async def save_scenario(request: Request) -> Response:
        payload = await read_payload(request, limits.MAX_BYTES + 4096)
        if isinstance(payload, Response):
            return payload
        if not jobs.can_run:
            return _err(jobs.reason or "симулятор недоступен: проверить сценарий нечем", 400)
        try:
            sid, token = await run_in_threadpool(
                catalog.save_custom, payload.get("id"), payload.get("token"), payload.get("scenario")
            )
        except (ValueError, TypeError) as e:
            return _err(str(e), 400)
        except OSError:
            log.exception("не удалось сохранить сценарий")
            return _err("не удалось сохранить сценарий", 500)
        return _json({"id": sid, "token": token})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def api_404(rest: str) -> Response:
        return _err("нет такого адреса: /api/%s" % rest, 404)

    # ------------------------------------------------------------ интерфейс
    if cfg.static_dir and (cfg.static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=cfg.static_dir, html=True), name="ui")
    return app
