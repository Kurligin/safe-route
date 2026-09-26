# SafeRoute · АРМ оператора (веб-сервис)

Рабочее место оператора межцеховой логистики для симулятора amr-sim: проигрывание прогонов на
карте с плеером, шкалой и графиками, сравнение двух прогонов, запуск пачек прогонов из
интерфейса, конструктор сценариев, выгрузка CSV. Внешний вид и поведение — как у лёгкой версии
`arm/` сдаваемого репозитория; здесь это FastAPI + React.

## Структура

| Папка | Что внутри |
| --- | --- |
| `backend/saferoute/` | `api.py` — HTTP API и раздача интерфейса; `catalog.py` — сценарии и прогоны из папок; `jobs.py` — очередь прогонов `python -m amrsim run`; `derive.py` — остановки, подписи, CSV; `armcore.py` — разбор лога и отчёта (перенесён из `arm/armcore.py`); `config.py` — переменные окружения |
| `backend/tests/` | pytest: разбор, остановки, CSV, API (защита POST, очередь, сохранение сценария) на поддельном симуляторе |
| `frontend/src/` | React 18 + TypeScript (strict) + Vite: `store/` — состояние, `components/` — экраны и панели, `lib/` — подписи и производные данные, `styles/arm.css` — стили АРМ |
| `deploy/` | `Dockerfile`, `compose.svo.yml`, `Caddyfile.saferoute`, `deploy.sh` |

## Запуск для разработки

```bash
# бэкенд (Python 3.10)
cd backend
python3.10 -m venv .venv && .venv/bin/pip install -e ".[dev]"
SAFEROUTE_PYTHON=<python с numpy, например amrsim-participants/.venv310/bin/python> \
  .venv/bin/uvicorn saferoute.api:create_app --factory --host 127.0.0.1 --port 8098

# интерфейс
cd frontend
npm ci
npm run build        # dist/ отдаёт бэкенд: http://127.0.0.1:8098
npm run dev          # или сервер разработки с прокси /api -> 127.0.0.1:8098
```

Проверки: `backend/.venv/bin/pytest -q`, `black --check`, `ruff check`; `npm run typecheck`,
`npm run format:check`.

## Переменные окружения

| Переменная | По умолчанию | Смысл |
| --- | --- | --- |
| `SAFEROUTE_SUBMISSION` | `../safe-route` | сдаваемый репозиторий: `controller.py`, `results/`, `scenarios/` |
| `SAFEROUTE_SIM` | `../../inbox/amrsim-participants` | симулятор: `amrsim/`, `baseline/`, `scenarios/` |
| `SAFEROUTE_PYTHON` | текущий интерпретатор | python с numpy для прогонов и проверки сценариев |
| `SAFEROUTE_RUNS` | `var/runs` | прогоны, запущенные из сервиса |
| `SAFEROUTE_CUSTOM` | `var/custom` | свои сценарии конструктора |
| `SAFEROUTE_EXTRA_RUNS` | — | ещё папки с прогонами через `:` (только чтение) |
| `SAFEROUTE_STATIC` | `frontend/dist` | собранный интерфейс |
| `SAFEROUTE_PARALLEL` | 2 | прогонов одновременно (1–3) |
| `SAFEROUTE_READONLY` | 0 | 1 — только просмотр: запуск и сохранение выключены |
| `SAFEROUTE_ALLOWED_HOSTS` | `127.0.0.1,localhost,::1` | допустимые Host у POST (за прокси — имя сайта) |
| `SAFEROUTE_MAX_JOBS_PER_REQUEST` / `_MAX_QUEUED` / `_MAX_PER_CLIENT` | 12 / 60 / 12 | прогонов за запрос, в очереди всего, активных с одного адреса |
| `SAFEROUTE_MAX_CUSTOM` / `_MAX_RUNS` / `_MAX_RUNS_MB` | 200 / 2000 / 3000 | своих сценариев, прогонов и МБ в папке прогонов |
| `SAFEROUTE_MAX_LOG_MB` / `_FULL_CACHE_MB` / `_CUSTOM_TIMEOUT` | 30 / 150 / 180 | больший лог целиком не отдаётся; кэш разобранных прогонов; предел прогона своего сценария, с |
| `SAFEROUTE_CUSTOM_TTL_MIN` | 60 | свои сценарии (`custom_*`) и их прогоны в папке прогонов сервиса удаляются через столько минут после создания (проверка раз в 5 минут); 0 — не удалять |
| `SAFEROUTE_TRUST_XFF` | 0 | 1 — адрес посетителя из X-Forwarded-For (только когда порт доступен лишь своему прокси) |

Свой сценарий принимается в пределах: до 512 КБ, `duration_s` ≤ 900, пешеходов ≤ 30, событий ≤ 20,
расхождений карты ≤ 10, рейсов ≤ 10, точек в полигонах и путях ≤ 5000. id выдаёт сервер
(`custom_NN`); перезаписать сценарий можно только с токеном правки из ответа на первое сохранение
(браузер хранит его в localStorage), иначе сохраняется новый.

## API

| Метод | Адрес | Что |
| --- | --- | --- |
| GET | `/api/meta` | можно ли запускать, причина, параллелизм, контроллеры |
| GET | `/api/runs` | сводки всех прогонов (без тиков) |
| GET | `/api/runs/{key}` | прогон целиком: тики, карта, остановки (`?lite=1` — сводка); сжатие gzip |
| GET | `/api/runs/{key}/trips.csv`, `/stops.csv` | CSV рейсов и остановок со штрафами (UTF-8 с BOM, «;», десятичная запятая) |
| GET | `/api/scenarios` | сценарии по группам со сводкой и базовая карта |
| GET | `/api/scenarios/{id}` | сценарий с собственной картой и патчами (`?raw=1` — исходный файл) |
| POST | `/api/scenarios` | сохранить свой сценарий `{id?, token?, scenario}` → `{id, token}` (пределы, проверка схемой симулятора) |
| POST | `/api/launch` | поставить пачку `{scenario, controllers, seeds}`: либо все задания, либо ни одного |
| GET | `/api/jobs` | задания очереди и их ход |

POST принимается только с `Content-Type: application/json`, Host из списка и Origin той же страницы.
Документация API (`/docs`, `openapi.json`) на стенде выключена. Ответы несут CSP `default-src 'self'`,
`nosniff`, `Referrer-Policy`; файлы `/assets/*` кэшируются как неизменяемые.

Ссылки на состояние: `#run=<id>&t=62&mode=cmp&cmp=<id>`, `#tab=launch`, `#tab=build&scen=<id>`.

## Локальный запуск в Docker

В составе сдаваемого репозитория сервис лежит в папке `web/`. Нужен архив симулятора организаторов
`amrsim-participants` (по умолчанию — рядом с репозиторием):

```bash
cd web
AMRSIM_DIR=/абсолютный/путь/amrsim-participants docker compose up --build -d
# http://127.0.0.1:8098
docker compose down
```

## Развёртывание на svo

`bash deploy/deploy.sh` — rsync этого репозитория, сдаваемого репозитория и симулятора (без
`.venv`, `out/`, `teams/`) в `/opt/saferoute`, затем `docker compose -p saferoute -f
deploy/compose.svo.yml up -d --build`. Сервис слушает `127.0.0.1:8098`; наружу — блок
`deploy/Caddyfile.saferoute` (`saferoute.kurligin.ru` и `msk-hac.rapira-cloud.ru`), который добавляется в системный Caddy
вручную. Прогоны и свои сценарии хранятся в томах `saferoute_runs` и `saferoute_custom`.
