"""bookmark_tool.py — 북마크한 채널들을 한곳에 모아 상세 조회.

각 채널: 이름·로고·구독자수·생성일 + 인기 영상(썸네일·제목·조회수).
조회수순 정렬. 일↔한 번안은 앱에서 옵션 호출.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _pick(th: dict) -> str:
    for q in ("high", "medium", "default"):
        if th.get(q, {}).get("url"):
            return th[q]["url"]
    return ""


def _demo() -> dict:
    return {"demo": True, "channels": [{
        "channel_id": "demo", "channel": "새벽카페 재즈 (데모)", "logo": "",
        "subscribers": 87000, "created": "2026-03-01", "url": "",
        "videos": [{"title": "비 오는 새벽, 창가에서 듣는 재즈 ☔", "views": 1240000,
                    "published": "2026-06-28", "thumb": "", "video_id": ""}]}]}


def collect(benchmarks: list[dict]) -> dict:
    """북마크된 벤치마크 → 채널별 상세(구독자·생성일·인기영상). 키 없으면 데모."""
    try:
        import youtube_client as yc
        import channel_watcher as W
    except Exception:                   # noqa: BLE001
        return _demo()
    if not yc.has_key():
        return _demo()
    bookmarked = [b for b in benchmarks if b.get("bookmark")]
    if not bookmarked:
        return {"demo": False, "channels": []}

    cids = {}
    for b in bookmarked:
        cid = b.get("channel_id") or W.resolve_channel_id(b["url"])
        if cid:
            cids[cid] = b["url"]
    if not cids:
        return {"demo": False, "channels": []}

    yt = yc._yt()
    channels = []
    idlist = list(cids)
    for k in range(0, len(idlist), 50):
        try:
            r = yt.channels().list(part="snippet,statistics,contentDetails",
                                   id=",".join(idlist[k:k + 50])).execute()
        except Exception:               # noqa: BLE001
            continue
        for it in r.get("items", []):
            sn, stt = it["snippet"], it.get("statistics", {})
            uploads = it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            channels.append({
                "channel_id": it["id"], "channel": sn["title"],
                "logo": _pick(sn.get("thumbnails", {})),
                "subscribers": int(stt.get("subscriberCount", 0) or 0),
                "created": sn.get("publishedAt", "")[:10],
                "url": cids.get(it["id"], ""), "uploads": uploads, "videos": []})

    for ch in channels:
        if not ch["uploads"]:
            continue
        try:
            pl = yt.playlistItems().list(part="contentDetails", playlistId=ch["uploads"],
                                         maxResults=12).execute()
            vids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
            if vids:
                vr = yt.videos().list(part="snippet,statistics", id=",".join(vids)).execute()
                for v in vr.get("items", []):
                    sn, stt = v["snippet"], v.get("statistics", {})
                    ch["videos"].append({
                        "title": sn["title"], "views": int(stt.get("viewCount", 0) or 0),
                        "published": sn["publishedAt"][:10], "video_id": v["id"],
                        "thumb": _pick(sn.get("thumbnails", {}))})
                ch["videos"].sort(key=lambda x: x["views"], reverse=True)
        except Exception:               # noqa: BLE001
            pass

    channels.sort(key=lambda c: (c["videos"][0]["views"] if c["videos"] else 0), reverse=True)
    return {"demo": False, "channels": channels}


def channel_age(created: str) -> str:
    try:
        d = _dt.date.fromisoformat(created)
        days = (_dt.date.today() - d).days
        if days < 60:
            return f"{days}일"
        if days < 730:
            return f"{days // 30}개월"
        return f"{days // 365}년"
    except (ValueError, TypeError):
        return "?"
