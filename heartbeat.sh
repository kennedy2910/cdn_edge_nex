#!/bin/bash

SMART_DNS="http://192.168.11.250:9300/api/edges/heartbeat"
TOKEN="change-me"

EDGE_ID=$(hostname)

# Detecta IP local automaticamente
IP=$(ip route get 1 | awk '{print $7; exit}')

LOAD=$(uptime | awk -F'load average:' '{ print $2 }' | cut -d',' -f1 | xargs)

BASE_URL="http://$IP:8080"
PLAYLIST_URL="http://$IP:8080/playlist.m3u"
API_URL="http://$IP:9100"

COUNTRY="PT"
REGION="Lisboa"
CITY="Lisboa"

LAT="38.7223"
LON="-9.1393"

curl -s -X POST "$SMART_DNS" \
  -H "Content-Type: application/json" \
  -H "X-ADMIN-TOKEN: $TOKEN" \
  -d "{
    \"edge_id\": \"$EDGE_ID\",
    \"name\": \"$EDGE_ID\",
    \"country\": \"$COUNTRY\",
    \"region\": \"$REGION\",
    \"city\": \"$CITY\",
    \"lat\": $LAT,
    \"lon\": $LON,
    \"base_url\": \"$BASE_URL\",
    \"playlist_url\": \"$PLAYLIST_URL\",
    \"api_url\": \"$API_URL\",
    \"load\": $LOAD,
    \"is_online\": true
  }"
