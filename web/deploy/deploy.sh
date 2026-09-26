#!/usr/bin/env bash
# Выкладка АРМ «Безопасный маршрут» на сервер svo.
#
# Что делает: копирует rsync'ом три папки в /opt/saferoute (этот репозиторий, сдаваемый
# репозиторий и симулятор без .venv/out/teams), собирает образ на сервере и поднимает
# контейнер `docker compose -p saferoute up -d --build`, затем проверяет /api/health.
#
# Чего НЕ делает: не трогает /etc/caddy/Caddyfile — блок из deploy/Caddyfile.saferoute
# добавляется вручную. Прогоны и свои сценарии живут в томах docker и не затираются.
#
# Запуск из корня репозитория:  bash deploy/deploy.sh
# Пути к соседним папкам можно переопределить: SUBMISSION_SRC, AMRSIM_SRC.

set -euo pipefail

HOST="${DEPLOY_HOST:-svo}"
DEST="${DEPLOY_DIR:-/opt/saferoute}"
cd "$(dirname "$0")/.."
WEB="$(pwd)"
SUBMISSION_SRC="${SUBMISSION_SRC:-$WEB/../safe-route}"
AMRSIM_SRC="${AMRSIM_SRC:-$WEB/../../inbox/amrsim-participants}"

for d in "$SUBMISSION_SRC/controller.py" "$AMRSIM_SRC/amrsim" "$AMRSIM_SRC/baseline/controller.py"; do
  [ -e "$d" ] || { echo "не найдено: $d" >&2; exit 1; }
done

echo "==> каталог $DEST на $HOST"
ssh "$HOST" "sudo mkdir -p '$DEST' && sudo chown \"\$(id -un)\" '$DEST'"

RSYNC=(rsync -az --delete --exclude .git --exclude __pycache__ --exclude .DS_Store)
echo "==> веб-сервис"
"${RSYNC[@]}" --exclude node_modules --exclude .venv --exclude dist --exclude var \
  --exclude .pytest_cache --exclude .ruff_cache "$WEB/" "$HOST:$DEST/web/"
echo "==> сдаваемый репозиторий"
"${RSYNC[@]}" --exclude venv --exclude .venv --exclude arm/runs --exclude arm/custom \
  "$SUBMISSION_SRC/" "$HOST:$DEST/safe-route/"
echo "==> симулятор (без .venv, out/, teams/)"
"${RSYNC[@]}" --exclude '.venv*' --exclude out --exclude teams "$AMRSIM_SRC/" "$HOST:$DEST/amrsim/"

echo "==> сборка и запуск"
ssh "$HOST" "cd '$DEST/web' && docker compose -p saferoute -f deploy/compose.svo.yml up -d --build"

echo "==> проверка живости"
for _ in $(seq 1 30); do
  if ssh "$HOST" "curl -fsS -m 5 http://127.0.0.1:8098/api/meta"; then
    echo
    echo "==> готово: АРМ на 127.0.0.1:8098 сервера $HOST"
    echo "    наружу — после добавления deploy/Caddyfile.saferoute в системный Caddy"
    exit 0
  fi
  sleep 3
done
echo "сервис не ответил за 90 секунд, журнал:" >&2
ssh "$HOST" "cd '$DEST/web' && docker compose -p saferoute -f deploy/compose.svo.yml logs --tail 60" >&2
exit 1
