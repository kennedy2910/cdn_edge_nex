#!/usr/bin/env bash
set -euo pipefail

echo "=== EDGE CDN v11 RESET (zera tudo) ==="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DOCKER="docker"
if command -v docker >/dev/null 2>&1; then
  if ! docker ps >/dev/null 2>&1; then
    DOCKER="sudo docker"
  fi
else
  echo "[ERRO] docker não encontrado."
  exit 1
fi

COMPOSE="$DOCKER compose"
if $COMPOSE version >/dev/null 2>&1; then
  $COMPOSE down -v --remove-orphans || true
else
  echo "[WARN] 'docker compose' não disponível. Tentando 'docker-compose'..."
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose down -v --remove-orphans || true
  fi
fi

echo "[INFO] Removendo ./data (cache, hls, configs gerados)..."
rm -rf ./data

echo "✅ Reset concluído. Agora rode:"
echo "  ./scripts/install.sh"
