#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/test_channel.sh Teste "https://.../index.m3u8"
#   ./scripts/test_channel.sh canal1 rtmp://....

CHANNEL_ID="${1:-canal1}"
SOURCE_URL="${2:-testsrc}"

if [ "$SOURCE_URL" = "testsrc" ]; then
  echo "[INFO] Publicando testsrc para $CHANNEL_ID via RTMP..."
  ffmpeg -re \
    -f lavfi -i testsrc=size=1280x720:rate=30 \
    -f lavfi -i sine=frequency=1000 \
    -c:v libx264 -pix_fmt yuv420p -profile:v baseline -preset veryfast \
    -g 60 -keyint_min 60 -sc_threshold 0 -bf 0 \
    -c:a aac -ar 44100 -ac 2 \
    -f flv "rtmp://localhost:1935/${CHANNEL_ID}"
else
  echo "[INFO] Relaying $SOURCE_URL -> $CHANNEL_ID via RTMP..."
  ffmpeg -re -i "$SOURCE_URL" \
    -c:v libx264 -pix_fmt yuv420p -profile:v baseline -preset veryfast \
    -g 60 -keyint_min 60 -sc_threshold 0 -bf 0 \
    -c:a aac -ar 44100 -ac 2 \
    -f flv "rtmp://localhost:1935/${CHANNEL_ID}"
fi
