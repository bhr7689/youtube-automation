import logging
import re
from datetime import datetime

from googleapiclient.discovery import build

from core.config import YOUTUBE_API_KEY
from core.store import init_db, upsert_channel
from core.utils import new_id

logger = logging.getLogger(__name__)


def _build_yt():
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY 가 .env에 없습니다.")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def parse_channel_input(raw):
    raw = raw.strip()
    if re.match(r"^UC[\w-]{22}$", raw):
        return {"type": "id", "value": raw}
    if raw.startswith("@"):
        return {"type": "handle", "value": raw}
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", raw)
    if m:
        return {"type": "id", "value": m.group(1)}
    m = re.search(r"youtube\.com/@([\w.-]+)", raw)
    if m:
        return {"type": "handle", "value": "@" + m.group(1)}
    m = re.search(r"youtube\.com/c/([\w.-]+)", raw)
    if m:
        return {"type": "custom", "value": m.group(1)}
    m = re.search(r"youtube\.com/user/([\w.-]+)", raw)
    if m:
        return {"type": "user", "value": m.group(1)}
    return {"type": "unknown", "value": raw}


def _lookup_by_id(yt, channel_id):
    resp = yt.channels().list(id=channel_id, part="snippet,statistics").execute()
    items = resp.get("items", [])
    return items[0] if items else None


def _lookup_by_handle(yt, handle):
    handle_clean = handle.lstrip("@")
    resp = yt.channels().list(forHandle=handle_clean, part="snippet,statistics").execute()
    items = resp.get("items", [])
    return items[0] if items else None


def _lookup_by_username(yt, username):
    resp = yt.channels().list(forUsername=username, part="snippet,statistics").execute()
    items = resp.get("items", [])
    return items[0] if items else None


def _item_to_channel(item, note="직접등록"):
    snip = item["snippet"]
    stats = item.get("statistics", {})
    return {"channel_id": item["id"], "name": snip.get("title", ""),
        "description": snip.get("description", ""), "category": note,
        "subscriber_cnt": int(stats.get("subscriberCount", 0)),
        "avg_view_cnt": int(stats.get("viewCount", 0)), "avg_ctr_est": 0.0,
        "country": snip.get("country", ""),
        "thumbnail_url": snip.get("thumbnails", {}).get("default", {}).get("url", ""),
        "collected_at": datetime.utcnow().isoformat()}


def register_channel(raw_input, note="직접등록"):
    yt = _build_yt()
    parsed = parse_channel_input(raw_input)
    item = None
    if parsed["type"] == "id":
        item = _lookup_by_id(yt, parsed["value"])
    elif parsed["type"] == "handle":
        item = _lookup_by_handle(yt, parsed["value"])
    elif parsed["type"] in ("custom", "user"):
        item = _lookup_by_username(yt, parsed["value"])
    if not item:
        return None
    ch = _item_to_channel(item, note)
    upsert_channel(ch)
    return ch


def register_channels_bulk(raw_inputs, note="직접등록"):
    results = []
    for raw in raw_inputs:
        ch = register_channel(raw.strip(), note)
        if ch:
            results.append(ch)
    return results
