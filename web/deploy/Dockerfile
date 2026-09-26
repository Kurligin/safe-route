# syntax=docker/dockerfile:1.6
# Образ АРМ «Безопасный маршрут»: FastAPI + собранный интерфейс + копии сдаваемого репозитория и симулятора.
#
# Основной контекст — этот репозиторий. Дополнительные (compose: build.additional_contexts):
#   submission — сдаваемый репозиторий safe-route (controller.py и модули, scenarios/, results/);
#   amrsim     — папка симулятора организаторов (amrsim/, baseline/, scenarios/), без .venv, out/, teams/.

FROM mirror.gcr.io/library/node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM mirror.gcr.io/library/python:3.10-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# numpy — для самого симулятора и контроллеров (та же версия, что в venv разработки)
RUN pip install "numpy==2.2.6"
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/saferoute backend/saferoute
RUN pip install ./backend

COPY --from=amrsim amrsim /opt/amrsim/amrsim
COPY --from=amrsim baseline /opt/amrsim/baseline
COPY --from=amrsim scenarios /opt/amrsim/scenarios
COPY --from=submission *.py /opt/safe-route/
COPY --from=submission scenarios /opt/safe-route/scenarios
COPY --from=submission results /opt/safe-route/results
COPY --from=ui /ui/dist /app/static

ENV SAFEROUTE_SUBMISSION=/opt/safe-route \
    SAFEROUTE_SIM=/opt/amrsim \
    SAFEROUTE_PYTHON=/usr/local/bin/python \
    SAFEROUTE_RUNS=/data/runs \
    SAFEROUTE_CUSTOM=/data/custom \
    SAFEROUTE_STATIC=/app/static

RUN useradd --system --uid 10001 saferoute \
    && mkdir -p /data/runs /data/custom \
    && chown -R saferoute /data
USER saferoute

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
# один процесс: очередь прогонов живёт в памяти
CMD ["uvicorn", "saferoute.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
