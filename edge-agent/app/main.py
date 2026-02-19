import os
import time
import threading
import subprocess
from typing import Dict, List, Optional, Any
import requests
from fastapi import FastAPI, Response, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

EDGE_ID = os.getenv("EDGE_ID", "edge-001")
API_KEY = os.getenv("API_KEY", "")
CENTRAL_BASE_URL = os.getenv("CENTRAL_BASE_URL", "").rstrip("/")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "30"))
RTMP_PUBLISH_BASE = os.getenv("RTMP_PUBLISH_BASE", "rtmp://mediamtx:1935").rstrip("/")
YTDLP_FORMAT = os.getenv("YTDLP_FORMAT", "best")
EDGE_PUBLIC_HOST = os.getenv("EDGE_PUBLIC_HOST", "")  # opcional: IP/host pÃºblico do EDGE (pra playlist absoluta)
HLS_PORT = os.getenv("HLS_PORT", "8080")
PROXY_YOUTUBE = os.getenv("PROXY_YOUTUBE", "1").lower() in ("1", "true", "yes")

CENTRAL_CHANNELS_URL = f"{CENTRAL_BASE_URL}/api/edge/channels"

LOG_DIR = os.getenv("LOG_DIR", "/data/logs")
os.makedirs(LOG_DIR, exist_ok=True)

class Channel(BaseModel):
    id: str
    name: str
    source_url: str
    enabled: bool = True
    kind: str = "hls"  # hls | youtube
    playback_url: Optional[str] = None
    schedule: Optional[Any] = None
    schedule_start: Optional[str] = None  # ISO 8601
    items: Optional[Any] = None  # for youtube_linear (Central payload)

app = FastAPI(title="Edge Agent", version="10.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # depois podemos restringir
    # Com wildcard em origins, credentials deve ficar false para CORS válido.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


procs: Dict[str, subprocess.Popen] = {}
last_channels: Dict[str, Channel] = {}
last_sync_ts: float = 0.0
last_error: Optional[str] = None
resolved_cache: Dict[str, str] = {}

def normalize_channel(it: dict) -> Optional[Channel]:
    cid = (
        it.get("channel_id")
        or it.get("channel_number")
        or it.get("id")
    )
    if not cid:
        return None

    kind = str(it.get("kind", "")).lower()
    source = it.get("playback_url") or it.get("source_url")

    # Central often sends youtube_linear with empty source_url and a list of items.
    if (not source) and kind == "youtube_linear":
        items = it.get("items") or []
        if isinstance(items, list) and items:
            u = (items[0] or {}).get("url")
            if u:
                source = u
    if not source and kind != "youtube_linear":
        return None

    return Channel(
        id=str(cid).strip(),
        name=str(it.get("name", cid)).strip(),
        source_url=str(source or "").strip(),
        enabled=bool(int(it.get("is_active", 1))) if str(it.get("is_active", "1")).isdigit() else bool(it.get("is_active", True)),
        schedule=it.get("schedule"),
        schedule_start=(
            str(it.get("schedule_start") or it.get("scheduleStart") or (it.get("schedule") or {}).get("start") or "").strip()
            or None
        ),
        items=it.get("items"),
    )


YOUTUBE_HOST_SNIPPETS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
)


def is_youtube(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return any(h in u for h in YOUTUBE_HOST_SNIPPETS)

def should_proxy_youtube(ch: Channel) -> bool:
    return PROXY_YOUTUBE and (ch.kind in ("youtube", "youtube_linear") or is_youtube(ch.source_url))

def get_hls_base(request: Optional[Request] = None) -> str:
    if EDGE_PUBLIC_HOST:
        host = EDGE_PUBLIC_HOST
    elif request and request.url.hostname:
        host = request.url.hostname
    else:
        host = "127.0.0.1"
    return f"http://{host}:{HLS_PORT}".rstrip("/")

def get_hls_url(channel_id: str, request: Optional[Request] = None) -> str:
    base = get_hls_base(request)
    return f"{base}/hls/{EDGE_ID}/{channel_id}/index.m3u8"

def resolve_youtube(url: str) -> str:
    cmd = ["yt-dlp", "-f", YTDLP_FORMAT, "-g", url]
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=30)
    line = out.strip().splitlines()[0].strip()
    if not line:
        raise RuntimeError("yt-dlp returned empty URL")
    return line

def build_ffmpeg_cmd(channel_id: str, source_url: str):
    # Namespaced publish path so the generated HLS directory becomes:
    # /hls/{EDGE_ID}/{channel_id}/index.m3u8
    publish_url = f"{RTMP_PUBLISH_BASE}/{EDGE_ID}/{channel_id}"

    headers = (
        "User-Agent: Mozilla/5.0\r\n"
        "Referer: https://google.com\r\n"
        "Origin: https://google.com\r\n"
        "Accept: */*\r\n"
    )

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "info",

        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "10",

        "-headers", headers,

        "-i", source_url,

        "-map", "0:v:0",
        "-map", "0:a:0?",

        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-profile:v", "baseline",
        "-preset", "veryfast",
        "-g", "60",
        "-keyint_min", "60",
        "-sc_threshold", "0",
        "-bf", "0",

        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",

        "-f", "flv",
        publish_url
    ]

def stop_channel(channel_id: str):
    p = procs.get(channel_id)
    if p and p.poll() is None:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    procs.pop(channel_id, None)

def start_channel(channel: Channel):
    # Requirement: YouTube should be executed directly (bypass), not transcoded to HLS.
    if channel.kind in ("youtube", "youtube_linear") or is_youtube(channel.source_url):
        return
    if channel.id in procs and procs[channel.id].poll() is None:
        return
    source_url = channel.source_url
    if should_proxy_youtube(channel) and is_youtube(source_url):
        if source_url in resolved_cache:
            source_url = resolved_cache[source_url]
        else:
            source_url = resolve_youtube(source_url)
            resolved_cache[channel.source_url] = source_url

    cmd = build_ffmpeg_cmd(channel.id, source_url)

    print(f"[EDGE] Starting channel {channel.id}")
    print(" ".join(cmd))

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    procs[channel.id] = p

    def log_errors():
        try:
            for line in p.stderr:
                print(f"[FFMPEG:{channel.id}] {line.strip()}")
        except:
            pass

    threading.Thread(target=log_errors, daemon=True).start()

def parse_central_payload(payload: dict) -> Dict[str, Channel]:
    channels: Dict[str, Channel] = {}

    providers = payload.get("providers", []) or []
    for prov in providers:
        for it in (prov.get("channels", []) or []):
            ch = normalize_channel(it)
            if not ch:
                continue

            # define kind de forma compatível
            ch.kind = (
                str(it.get("kind")).lower()
                if it.get("kind")
                else ("youtube" if is_youtube(ch.source_url) else "hls")
            )

            # preserva playback_url se vier da Central
            ch.playback_url = it.get("playback_url") or ch.source_url
            ch.schedule = it.get("schedule")
            ch.items = it.get("items")
            ch.schedule_start = (
                str(it.get("schedule_start") or it.get("scheduleStart") or (it.get("schedule") or {}).get("start") or "").strip()
                or ch.schedule_start
            )

            channels[ch.id] = ch

    return channels


def sync_once():
    global last_sync_ts, last_error, last_channels
    headers = {
        "X-API-KEY": API_KEY,
        "X-EDGE-ID": EDGE_ID,
    }

    try:
        r = requests.get(CENTRAL_CHANNELS_URL, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        channels = parse_central_payload(data)

        # stop removed
        for cid in list(last_channels.keys()):
            if cid not in channels or not channels[cid].enabled:
                stop_channel(cid)

        # start/update
        for cid, ch in channels.items():
            if not ch.enabled:
                stop_channel(cid)
                continue
            prev = last_channels.get(cid)
            if prev and (prev.source_url != ch.source_url or prev.kind != ch.kind):
                stop_channel(cid)
            if ch.kind == "youtube_linear" and not should_proxy_youtube(ch):
                continue
            start_channel(ch)

        last_channels = channels
        last_error = None
        last_sync_ts = time.time()

    except Exception as e:
        last_error = str(e)

def _first_item_url(items: Any) -> Optional[str]:
    if not isinstance(items, list) or not items:
        return None
    u = (items[0] or {}).get("url")
    return str(u).strip() if u else None

def youtube_bypass_url(ch: Channel) -> Optional[str]:
    u = (ch.source_url or "").strip() or (ch.playback_url or "").strip()
    if u:
        return u
    return _first_item_url(ch.items)

def to_app_item(ch: Channel, request: Request) -> Optional[dict]:
    """Return an item in the exact shape expected by lineartv-pro App.tsx."""
    # For HLS/live: keep offset at 0 by using a far-future schedule_start.
    schedule_start = ch.schedule_start or ("2099-01-01T00:00:00Z" if ch.kind == "hls" else "2024-01-01T00:00:00Z")

    if ch.kind == "youtube_linear":
        items = ch.items if isinstance(ch.items, list) else []
        # Ensure items list is in the expected schema
        norm_items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            u = it.get("url")
            d = it.get("duration")
            if not u or not d:
                continue
            norm_items.append({"type": "video", "url": str(u).strip(), "duration": int(d)})
        if not norm_items:
            u = youtube_bypass_url(ch)
            if not u:
                return None
            norm_items = [{"type": "video", "url": u, "duration": 3600}]
        return {
            "channel_id": ch.id,
            "name": ch.name,
            "kind": "youtube_linear",
            "schedule_start": schedule_start,
            "items": norm_items,
            "loop": True,
        }

    if ch.kind == "youtube" or is_youtube(ch.source_url) or is_youtube(ch.playback_url or ""):
        u = youtube_bypass_url(ch)
        if not u:
            return None
        return {
            "channel_id": ch.id,
            "name": ch.name,
            "kind": "youtube",
            "schedule_start": schedule_start,
            "items": [{"type": "video", "url": u, "duration": 3600}],
            "loop": True,
        }

    # Default: HLS served by this edge
    hls_url = get_hls_url(ch.id, request)
    return {
        "channel_id": ch.id,
        "name": ch.name,
        "kind": "hls",
        "schedule_start": schedule_start,
        "items": [{"type": "video", "url": hls_url, "duration": 86400}],
        "loop": True,
    }


def worker_loop():
    while True:
        sync_once()

        # reiniciar processos que morreram
        for cid, ch in list(last_channels.items()):
            if not ch.enabled:
                continue
            if ch.kind == "youtube_linear":
                continue
            p = procs.get(cid)
            if p is None or p.poll() is not None:
                stop_channel(cid)
                try:
                    start_channel(ch)
                except Exception:
                    pass

        time.sleep(max(5, SYNC_INTERVAL))

@app.on_event("startup")
def on_startup():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

@app.get("/health")
def health():
    ok = bool(CENTRAL_BASE_URL and API_KEY)
    return {
        "status": "ok" if ok else "misconfigured",
        "edge_id": EDGE_ID,
        "central": CENTRAL_BASE_URL,
        "last_sync_ts": last_sync_ts,
        "last_error": last_error,
        "running_channels": [cid for cid, p in procs.items() if p.poll() is None],
    }

@app.get("/sync")
def sync():
    sync_once()
    return {
        "ok": last_error is None,
        "last_error": last_error,
        "running_channels": [cid for cid, p in procs.items() if p.poll() is None],
        "channels": [c.model_dump() for c in last_channels.values()],
    }

@app.get("/channels")
def channels(request: Request):
    out = []
    for ch in last_channels.values():
        if not ch.enabled:
            continue
        item = to_app_item(ch, request)
        if item:
            out.append(item)
    return out

@app.get("/playlist.m3u")
def playlist(request: Request):
    lines = ["#EXTM3U"]
    for ch in last_channels.values():
        if not ch.enabled:
            continue
        name = ch.name.replace("\n", " ").strip()
        lines.append(f"#EXTINF:-1,{name}")
        # Mixed playlist:
        # - HLS channels: served by this edge at /hls/{EDGE_ID}/{channel_id}/index.m3u8
        # - YouTube channels: pass-through URL (no caching/proxying)
        if ch.kind == "youtube_linear":
            u = youtube_bypass_url(ch)
            if u:
                lines.append(u)
            else:
                lines.pop()  # remove EXTINF
        elif ch.kind == "youtube" and (ch.playback_url or ch.source_url):
            lines.append(ch.playback_url or ch.source_url)
        elif ch.kind == "youtube" or is_youtube(ch.source_url) or is_youtube(ch.playback_url or ""):
            u = youtube_bypass_url(ch)
            if u:
                lines.append(u)
            else:
                lines.pop()
        else:
            lines.append(get_hls_url(ch.id, request))
    body = "\n".join(lines) + "\n"
    return Response(content=body, media_type="application/x-mpegURL")


@app.get("/playlist.json")
def playlist_json(request: Request):
    """Playlist consumida pelo app.

    Retorna apenas metadata do Central com o campo `kind` e `schedule`.
    """
    out = []
    for ch in last_channels.values():
        if not ch.enabled:
            continue
        item = to_app_item(ch, request)
        if item:
            out.append(item)
    return {"edge_id": EDGE_ID, "items": out}
