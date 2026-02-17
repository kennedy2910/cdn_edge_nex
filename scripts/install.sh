#!/usr/bin/env bash
set -euo pipefail

echo "=== EDGE CDN v11 INSTALLER (compat) ==="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ---------- helpers ----------
have_cmd() { command -v "$1" >/dev/null 2>&1; }

# docker permission detection: if docker ps fails, use sudo
DOCKER="docker"
if have_cmd docker; then
  if ! docker ps >/dev/null 2>&1; then
    DOCKER="sudo docker"
  fi
else
  echo "[ERRO] Docker não está instalado."
  echo "Ubuntu:"
  echo "  sudo apt update && sudo apt install -y docker.io"
  echo "Depois (opcional):"
  echo "  sudo usermod -aG docker $USER && newgrp docker"
  exit 1
fi

COMPOSE="$DOCKER compose"
if ! $COMPOSE version >/dev/null 2>&1; then
  # fallback para docker-compose (legacy)
  if have_cmd docker-compose; then
    if ! docker-compose version >/dev/null 2>&1; then
      echo "[ERRO] 'docker-compose' encontrado, mas falhou ao executar."
      exit 1
    fi
    echo "[WARN] 'docker compose' não disponível. Usando 'docker-compose' (legacy)."
    COMPOSE="docker-compose"
  else
    echo "[ERRO] Docker Compose não encontrado."
    echo "Opções:"
    echo "  - Compose plugin: sudo apt install -y docker-compose-plugin"
    echo "  - Legacy:        sudo apt install -y docker-compose"
    exit 1
  fi
fi

# ---------- env ----------
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "[OK] Criado .env a partir de .env.example (edite depois se quiser)."
  else
    echo "[ERRO] Não achei .env nem .env.example."
    exit 1
  fi
fi

# shellcheck disable=SC1091
source ./.env || true

mkdir -p ./data/mediamtx ./data/nginx-cache ./data/hls

# ---------- mediamtx config sanity (corrige o erro 'directory vs file') ----------
CONF="./data/mediamtx/mediamtx.yml"
if [ -d "$CONF" ]; then
  echo "[WARN] $CONF está como PASTA (errado). Vou remover e recriar como arquivo."
  rm -rf "$CONF"
fi

if [ ! -f "$CONF" ]; then
  if [ -f "./configs/mediamtx/mediamtx.yml" ]; then
    cp ./configs/mediamtx/mediamtx.yml "$CONF"
  else
    cat >"$CONF" <<'YAML'
logLevel: info

rtmp: yes
hls: yes

hlsDirectory: /tmp/hls
hlsVariant: lowLatency
hlsSegmentDuration: 2s
hlsPartDuration: 200ms

paths:
  all:
    source: publisher
YAML
  fi
  echo "[OK] Criado $CONF"
fi

# ---------- run ----------
echo "[INFO] Subindo containers (pull/build/up)..."
$COMPOSE pull || true
$COMPOSE build --no-cache edge-agent || true
$COMPOSE up -d --remove-orphans

echo
echo "✅ EDGE CDN v11 rodando."
echo
echo "RTMP ingest:"
echo "  rtmp://<EDGE_IP>:1935/<channel_id>"
echo
echo "HLS playback:"
echo "  http://<EDGE_IP>:8080/hls/<channel_id>/index.m3u8"
echo
echo "Playlist (M3U):"
echo "  http://<EDGE_IP>:8080/playlist.m3u"
echo "  http://<EDGE_IP>:8080/playlist.m3   (alias)"
echo
echo "Edge Agent health:"
echo "  http://<EDGE_IP>:9100/health"
echo
echo "Sync manual (POST):"
echo "  curl -X POST http://<EDGE_IP>:9100/sync"
echo
echo "Boa caralho. 🚀"
