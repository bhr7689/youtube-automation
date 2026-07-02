"""YouTube Data API 클라이언트 + 키 없을 때 데모 폴백.

카드 공통 스키마(dict):
  video_id, title, channel_id, channel_title, thumb, duration_sec, is_short,
  views, published_at(ISO), channel_age_months, channel_avg_views, multiplier
multiplier = 영상 조회수 / 채널 평균 조회수(총조회수/영상수) — 설계 확정값.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import random

import isodate

import store

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

SHORT_MAX_SEC = 62  # 쇼츠 판정 경계 (60s + 여유)

LANG_REGION = {
    "ko": "KR", "en": "US", "ja": "JP", "zh": "TW", "es": "MX",
    "de": "DE", "fr": "FR", "pt": "BR", "hi": "IN",
}


def has_key() -> bool:
    return bool(YOUTUBE_API_KEY)


def _yt():
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)


def _months_since(iso: str) -> int:
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 999
    now = dt.datetime.now(dt.timezone.utc)
    return max(0, int((now - t).days / 30.44))


def _fetch_channels(ids: list[str]) -> dict[str, dict]:
    """채널 통계 (캐시 우선). {id: {title, published_at, subs, avg_views, age_months}}"""
    ids = list(dict.fromkeys(ids))
    cached = store.cache_get_channels(ids)
    missing = [i for i in ids if i not in cached]
    fresh: dict[str, dict] = {}
    if missing and has_key():
        yt = _yt()
        for i in range(0, len(missing), 50):
            resp = yt.channels().list(
                part="snippet,statistics", id=",".join(missing[i : i + 50]), maxResults=50
            ).execute()
            for it in resp.get("items", []):
                st = it.get("statistics", {})
                vc = int(st.get("viewCount", 0))
                n = max(1, int(st.get("videoCount", 1)))
                fresh[it["id"]] = {
                    "title": it["snippet"]["title"],
                    "published_at": it["snippet"]["publishedAt"],
                    "subs": int(st.get("subscriberCount", 0)),
                    "avg_views": vc / n,
                    "age_months": _months_since(it["snippet"]["publishedAt"]),
                }
        if fresh:
            store.cache_put_channels(fresh)
    cached.update(fresh)
    return cached


def search_videos(
    query: str,
    video_type: str = "all",      # shorts | long | all
    order: str = "viewCount",     # viewCount | date
    max_results: int = 50,
    period_days: int = 0,          # 0 = 전체
    lang: str = "",
) -> list[dict]:
    if not has_key():
        return _demo_cards(query, video_type, max_results)

    yt = _yt()
    params = dict(
        part="id", q=query, type="video", order=order,
        maxResults=min(50, max_results), safeSearch="none",
    )
    if period_days:
        after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=period_days)
        params["publishedAfter"] = after.strftime("%Y-%m-%dT%H:%M:%SZ")
    if video_type == "shorts":
        params["videoDuration"] = "short"   # <4min — 이후 duration으로 재판정
    elif video_type == "long":
        params["videoDuration"] = "medium"
    if lang and lang in LANG_REGION:
        params["relevanceLanguage"] = lang
        params["regionCode"] = LANG_REGION[lang]

    video_ids: list[str] = []
    page_token = None
    while len(video_ids) < max_results:
        if page_token:
            params["pageToken"] = page_token
        resp = yt.search().list(**params).execute()
        video_ids += [it["id"]["videoId"] for it in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    video_ids = video_ids[:max_results]
    if not video_ids:
        return []

    videos: list[dict] = []
    for i in range(0, len(video_ids), 50):
        resp = yt.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids[i : i + 50]),
        ).execute()
        videos += resp.get("items", [])

    chans = _fetch_channels([v["snippet"]["channelId"] for v in videos])

    cards = []
    for v in videos:
        sn, st = v["snippet"], v.get("statistics", {})
        try:
            dur = int(isodate.parse_duration(v["contentDetails"]["duration"]).total_seconds())
        except Exception:
            dur = 0
        is_short = dur <= SHORT_MAX_SEC
        if video_type == "shorts" and not is_short:
            continue
        if video_type == "long" and is_short:
            continue
        ch = chans.get(sn["channelId"], {})
        views = int(st.get("viewCount", 0))
        avg = ch.get("avg_views") or 0
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
        cards.append({
            "video_id": v["id"],
            "title": sn["title"],
            "channel_id": sn["channelId"],
            "channel_title": sn["channelTitle"],
            "thumb": thumb,
            "duration_sec": dur,
            "is_short": is_short,
            "views": views,
            "published_at": sn["publishedAt"],
            "channel_age_months": ch.get("age_months", 999),
            "channel_avg_views": avg,
            "multiplier": round(views / avg, 1) if avg else None,
        })
    return cards


# ── 데모 폴백 (YOUTUBE_API_KEY 없을 때) ────────────────

_DEMO_CH = [
    ("밤편지플리", 2), ("추억의소리함", 4), ("꿈결라디오", 5), ("세월의노래", 14),
    ("소리꾼TV", 1), ("효도라디오", 3), ("昭和のこころ", 5), ("고속도로디제이", 18),
    ("새벽감성상점", 1), ("토닥토닥뮤직", 6),
]
_DEMO_T = [
    "듣다가 결국 울어버린 {q} 💔", "가슴 시린 옛날 {q} 모음", "잠 안 올 때 듣는 {q}",
    "사무치게 그리운 {q} BEST 30", "한(恨)이 서린 {q} — 눈물 주의", "{q} 플레이리스트 광고없이 1시간",
    "새벽에 몰래 듣는 {q}", "마음이 먹먹한 날, {q}", "중장년층 취향 저격 {q} 메들리",
    "위로가 되는 {q} 연속듣기",
]


def _demo_cards(query: str, video_type: str, n: int) -> list[dict]:
    rnd = random.Random(int(hashlib.md5(query.encode()).hexdigest()[:8], 16))
    now = dt.datetime.now(dt.timezone.utc)
    cards = []
    for i in range(min(n, 24)):
        ch_name, age = _DEMO_CH[i % len(_DEMO_CH)]
        short = (i % 3 == 0) if video_type == "all" else (video_type == "shorts")
        dur = rnd.randint(18, 59) if short else rnd.randint(600, 9000)
        views = rnd.randint(50_000, 90_000_000)
        avg = max(1000, int(views / rnd.uniform(1.2, 45)))
        pub = now - dt.timedelta(days=rnd.randint(1, 400))
        cards.append({
            "video_id": f"demo_{hashlib.md5(f'{query}{i}'.encode()).hexdigest()[:9]}",
            "title": _DEMO_T[i % len(_DEMO_T)].format(q=query),
            "channel_id": f"demo_ch_{ch_name}",
            "channel_title": ch_name,
            "thumb": "",
            "duration_sec": dur,
            "is_short": short,
            "views": views,
            "published_at": pub.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "channel_age_months": age,
            "channel_avg_views": avg,
            "multiplier": round(views / avg, 1),
            "demo": True,
        })
    return cards
