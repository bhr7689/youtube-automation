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
            "likes": int(st.get("likeCount", 0) or 0),
            "comments": int(st.get("commentCount", 0) or 0),
            "published_at": sn["publishedAt"],
            "channel_age_months": ch.get("age_months", 999),
            "channel_avg_views": avg,
            "subscribers": int(ch.get("subs", 0) or 0),
            "multiplier": round(views / avg, 1) if avg else None,
            "vph": _vph(views, sn["publishedAt"]),
            # 실제 업로더가 검색 노출용으로 넣은 태그(키워드) — 공식 API snippet.tags
            "keywords": sn.get("tags", []) or [],
        })
    return cards


# ── 🔥 트렌드 피드 (등록 레퍼런스 채널의 급등 영상) ──────

def trending_from_channels(
    channel_ids: list[str],
    period_days: int = 7,
    video_type: str = "all",       # shorts | long | all
    max_per_channel: int = 20,
    max_results: int = 200,
) -> list[dict]:
    """등록된 레퍼런스 채널들의 최근 업로드를 모아 '평균 대비 배수'로 급등 영상을 뽑는다.

    배수 = 영상 조회수 / 채널 평균 조회수(총조회수/영상수) — search 와 동일 정의(정확).
    키가 없거나 등록 채널이 없으면 데모 폴백.
    """
    channel_ids = [c for c in dict.fromkeys(channel_ids) if c and not c.startswith("demo_")]
    if not has_key() or not channel_ids:
        return _demo_trend(video_type, max_results)

    yt = _yt()
    # 1) 채널 정보(업로드 재생목록 + 평균 조회수 + 나이)
    info: dict[str, dict] = {}
    for i in range(0, len(channel_ids), 50):
        resp = yt.channels().list(
            part="snippet,statistics,contentDetails",
            id=",".join(channel_ids[i : i + 50]), maxResults=50,
        ).execute()
        for it in resp.get("items", []):
            st = it.get("statistics", {})
            vc = int(st.get("viewCount", 0))
            n = max(1, int(st.get("videoCount", 1)))
            info[it["id"]] = {
                "uploads": it.get("contentDetails", {})
                    .get("relatedPlaylists", {}).get("uploads"),
                "avg_views": vc / n,
                "subs": int(st.get("subscriberCount", 0) or 0),
                "title": it["snippet"]["title"],
                "age_months": _months_since(it["snippet"]["publishedAt"]),
            }

    # 2) 채널별 최근 업로드 videoId 수집
    vid_owner: dict[str, str] = {}
    for cid, meta in info.items():
        pl = meta.get("uploads")
        if not pl:
            continue
        try:
            resp = yt.playlistItems().list(
                part="contentDetails", playlistId=pl,
                maxResults=min(50, max_per_channel),
            ).execute()
        except Exception:
            continue
        for it in resp.get("items", []):
            vid_owner[it["contentDetails"]["videoId"]] = cid

    if not vid_owner:
        return []

    # 3) 영상 상세 → 카드 (기간·형식 필터 + 배수)
    cutoff = None
    if period_days:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=period_days)
    ids = list(vid_owner.keys())
    cards: list[dict] = []
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(ids[i : i + 50]),
        ).execute()
        for v in resp.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            pub = sn["publishedAt"]
            if cutoff is not None:
                try:
                    if dt.datetime.fromisoformat(pub.replace("Z", "+00:00")) < cutoff:
                        continue
                except ValueError:
                    pass
            try:
                dur = int(isodate.parse_duration(v["contentDetails"]["duration"]).total_seconds())
            except Exception:
                dur = 0
            is_short = dur <= SHORT_MAX_SEC
            if video_type == "shorts" and not is_short:
                continue
            if video_type == "long" and is_short:
                continue
            cid = vid_owner.get(v["id"], sn["channelId"])
            ci = info.get(cid, {})
            avg = ci.get("avg_views") or 0
            views = int(st.get("viewCount", 0))
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
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
                "published_at": pub,
                "channel_age_months": ci.get("age_months", 999),
                "channel_avg_views": avg,
                "subscribers": int(ci.get("subs", 0) or 0),
                "multiplier": round(views / avg, 1) if avg else None,
                "vph": _vph(views, pub),
                "keywords": sn.get("tags", []) or [],
            })
    cards.sort(key=lambda c: -(c.get("multiplier") or 0))
    return cards[:max_results]


def _vph(views: int, published_at: str) -> float:
    """시간당 조회수(정확) — (조회수 / 업로드 후 경과시간h)."""
    try:
        t = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        hours = max((dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600.0, 1.0)
        return round(views / hours, 1)
    except Exception:
        return 0.0


# 데모용 키워드(태그) 풀 — 실제 API 는 snippet.tags 를 그대로 씀
_DEMO_KW = [
    "emotional", "heartwarming", "wholesome", "reunion", "family", "shark tank",
    "got talent", "golden buzzer", "감동", "휴먼스토리", "인생역전", "reaction",
    "shorts", "viral", "touching moment", "kindness", "life lesson", "senior",
    "tearjerker", "documentary", "inspiring", "surprise", "second chance",
]


def _demo_keywords(rnd, k=None) -> list[str]:
    k = k if k is not None else rnd.randint(6, 14)
    return rnd.sample(_DEMO_KW, min(k, len(_DEMO_KW)))


# 해외 예능/리얼리티 시드 채널 (이 프로젝트 테마 — idea 문서 30선 기반)
_DEMO_TREND_CH = [
    ("The Dodo", 8), ("Long Lost Family", 22), ("Got Talent Global", 40),
    ("Humans of New York", 30), ("Shark Tank Global", 15), ("The Ellen Show", 60),
    ("CBS Sunday Morning", 55), ("Little Big Shots", 18), ("Undercover Boss", 25),
    ("Steve Harvey", 33),
]
_DEMO_TREND_T = [
    "40년 만에 어머니를 다시 만난 아들 😢", "심사위원 전원을 울린 할아버지의 노래",
    "역에서 매일 주인을 기다린 강아지", "레모네이드 소녀가 상어들의 마음을 녹이다",
    "밑바닥에서 배운 CEO의 눈물", "낯선 이의 친절이 바꾼 하루",
    "포기하지 않은 도전자의 무대", "가족이 재회하는 순간, 모두가 울었다",
    "작은 소년의 한 마디에 스튜디오가 조용해졌다", "인생 2막을 연 70세 할머니",
]


def _demo_trend(video_type: str, n: int) -> list[dict]:
    rnd = random.Random(20260705)
    now = dt.datetime.now(dt.timezone.utc)
    cards = []
    for i in range(min(n, 24)):
        ch_name, age = _DEMO_TREND_CH[i % len(_DEMO_TREND_CH)]
        short = (i % 4 != 0) if video_type == "all" else (video_type == "shorts")
        dur = rnd.randint(20, 59) if short else rnd.randint(300, 1800)
        avg = rnd.randint(300_000, 4_000_000)
        mult = round(rnd.uniform(1.2, 45), 1)
        views = int(avg * mult)
        pub = now - dt.timedelta(days=rnd.randint(1, 21))
        cards.append({
            "video_id": f"demo_{hashlib.md5(f'trend{i}'.encode()).hexdigest()[:9]}",
            "title": _DEMO_TREND_T[i % len(_DEMO_TREND_T)],
            "channel_id": f"demo_ch_{ch_name}",
            "channel_title": ch_name,
            "thumb": "",
            "duration_sec": dur,
            "is_short": short,
            "views": views,
            "likes": int(views * rnd.uniform(0.02, 0.06)),
            "comments": int(views * rnd.uniform(0.001, 0.004)),
            "published_at": pub.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "channel_age_months": age,
            "channel_avg_views": avg,
            "subscribers": rnd.randint(200_000, 12_000_000),
            "multiplier": mult,
            "vph": _vph(views, pub.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "keywords": _demo_keywords(rnd),
            "registered": True,   # 트렌드는 등록 채널 기준 → 배수 배지 표시
            "demo": True,
        })
    cards.sort(key=lambda c: -(c["multiplier"] or 0))
    return cards


# ── 데모 폴백 (검색용) ─────────────────────────────────

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
            "subscribers": rnd.randint(100_000, 8_000_000),
            "multiplier": round(views / avg, 1),
            "vph": _vph(views, pub.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "keywords": _demo_keywords(rnd),
            "demo": True,
        })
    return cards
