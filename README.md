# EDGE CDN — BOA CARALHO EDITION v11

Este kit sobe um **Edge CDN** com:
- **MediaMTX** (RTMP ingest + HLS output)
- **Edge Agent** (puxa lista de canais do Central-Nex e faz relay com FFmpeg -> RTMP)
- **Nginx** (expondo HLS + playlist + cache)

## 1) Instalação (do zero)

```bash
chmod +x scripts/*.sh
./scripts/install.sh
```

Se você não tiver permissão no Docker (`permission denied`), o instalador automaticamente tenta usar `sudo docker`.

## 2) Configuração (.env)

O instalador cria `.env` a partir de `.env.example`.

Campos importantes:
- `EDGE_ID` (ex: `edge-001`)
- `API_KEY` (gerada no Central-Nex pro Edge)
- `CENTRAL_BASE_URL` (ex: `http://192.168.11.110:9000`)
- `EDGE_PUBLIC_HOST` (recomendado, ex: `192.168.11.109:8080`) -> playlist com URLs absolutas

> `PROVIDER_ID` é **opcional**. Só use se quiser filtrar um único provider.

## 3) Teste rápido

### Ver se o agent está sincronizando
```bash
curl http://localhost:9100/health
curl http://localhost:9100/channels
curl -X POST http://localhost:9100/sync
```

### Playlist pelo Nginx
```bash
curl http://localhost:8080/playlist.m3u
```

### Publicar um canal de teste (testsrc)
No host (precisa de ffmpeg instalado):
```bash
./scripts/test_channel.sh canal1 testsrc
```

Depois:
- HLS: `http://<EDGE_IP>:8080/hls/canal1/index.m3u8`
- Playlist: `http://<EDGE_IP>:8080/playlist.m3u`

## 4) Reset / Desinstalar (zerar tudo)

```bash
./scripts/reset.sh
```

Isso derruba containers, volumes e apaga a pasta `./data`.
