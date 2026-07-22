#!/bin/bash
# Реальная логика деплоя — версионируется в git, в отличие от тонкой
# обёртки /opt/greenmarket/deploy.sh на сервере (та стабильна и не
# меняется, чтобы не редактировать сама себя во время git reset --hard,
# который её вызывает).
set -euo pipefail

echo "=== Backend ==="
cd /opt/greenmarket/backend
/root/.local/bin/uv sync
systemctl restart greenmarket-api
sleep 2
systemctl is-active greenmarket-api
curl -sf localhost/health
echo

echo "=== buyer-web ==="
cd /opt/greenmarket/buyer-web
npm ci
npx tsc -b
npx vite build --base=/buyer/
rm -rf /var/www/html/buyer/*
cp -r dist/* /var/www/html/buyer/

echo "=== seller-cabinet ==="
cd /opt/greenmarket/seller-cabinet
npm ci
npx tsc -b
npx vite build --base=/seller/
rm -rf /var/www/html/seller/*
cp -r dist/* /var/www/html/seller/

echo "=== Deploy complete ==="
