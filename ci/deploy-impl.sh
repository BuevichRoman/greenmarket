#!/bin/bash
# Реальная логика деплоя — версионируется в git, в отличие от тонкой
# обёртки /opt/greenmarket/deploy.sh на сервере (та стабильна и не
# меняется, чтобы не редактировать сама себя во время git reset --hard,
# который её вызывает).
set -euo pipefail

# Пилот на рынке Валентина: второй процесс того же кода (greenmarket-pilot-api,
# :8001, /pilot/ в nginx) со своей базой greenmarket_pilot. Заведён руками
# только на сервере — где файла нет, шаги пилота пропускаются.
PILOT_ENV=/etc/greenmarket-pilot.env

echo "=== Migrations ==="
bash /opt/greenmarket/ci/apply-migrations.sh
if [[ -f "$PILOT_ENV" ]]; then
  ENV_FILE="$PILOT_ENV" bash /opt/greenmarket/ci/apply-migrations.sh
fi

echo "=== Backend ==="
cd /opt/greenmarket/backend
/root/.local/bin/uv sync
# Отметка развёрнутой версии — её отдаёт GET /health, по ней снаружи видно,
# отстал ли прод от main (см. app/core/deployed_commit.py). Пишется до
# рестарта, чтобы поднявшийся процесс сразу знал свою версию. Файл не в git.
git -C /opt/greenmarket rev-parse HEAD > /opt/greenmarket/backend/DEPLOYED_SHA
systemctl restart greenmarket-api
sleep 2
systemctl is-active greenmarket-api
curl -sf localhost/health
echo
if [[ -f "$PILOT_ENV" ]]; then
  systemctl restart greenmarket-pilot-api
  sleep 2
  systemctl is-active greenmarket-pilot-api
  curl -sf localhost:8001/health
  echo
fi

echo "=== seller-cabinet ==="
cd /opt/greenmarket/seller-cabinet
npm ci
npx tsc -b
npx vite build --base=/seller/
rm -rf /var/www/html/seller/*
cp -r dist/* /var/www/html/seller/

echo "=== Deploy complete ==="
