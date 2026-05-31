"""
급상승 레퍼런스 채널 발굴 대시보드 (Trending Reference Channel Discovery Dashboard)

YouTube Data API v3 를 사용해 특정 키워드(상황/감정 기반)로 최근 N일 내 업로드된
영상을 검색하고, '구독자 수 대비 조회수' 비율이 폭발적인 신규/소형 채널만 필터링해
리스트업하는 Streamlit 대시보드입니다.
"""

from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import isodate
import numpy as np
import pandas as pd
import requests
import streamlit as st
from PIL import Image
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 자동화 모듈 (Suno 스튜디오 · 곡 역설계 · 검수 큐 탭에서 사용)
import suno_studio
import recipes
import analyzer
import store
import score as scorer

load_dotenv()

# ---------------------------------------------------------------------------
# Persistent local key store — .streamlit/keys.json (gitignored).
# UI 에서 한 번 저장하면 해지 버튼을 누르기 전까지 모든 세션에서 자동으로 불러온다.
# ---------------------------------------------------------------------------

KEY_STORE_PATH = os.path.join(".streamlit", "keys.json")


def load_saved_keys() -> dict:
    try:
        with open(KEY_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_key(name: str, value: str) -> None:
    os.makedirs(os.path.dirname(KEY_STORE_PATH) or ".", exist_ok=True)
    data = load_saved_keys()
    data[name] = value
    with open(KEY_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_key(name: str) -> None:
    data = load_saved_keys()
    if name in data:
        data.pop(name)
        with open(KEY_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


SAVED_KEYS = load_saved_keys()
# .env 의 YOUTUBE_API_KEY 가 있으면 우선, 없으면 저장된 키, 둘 다 없으면 빈 값.
DEFAULT_API_KEY = os.getenv("YOUTUBE_API_KEY") or SAVED_KEYS.get("youtube", "")

# OpenCV 는 얼굴 검출 전용. 미설치 시 얼굴 분석만 비활성화하고 나머지는 계속 동작.
try:
    import cv2  # type: ignore

    _FACE_CASCADE = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    _HAS_CV2 = not _FACE_CASCADE.empty()
except Exception:
    cv2 = None  # type: ignore
    _FACE_CASCADE = None
    _HAS_CV2 = False

# YouTube Data API v3 의 일부 엔드포인트는 한 요청당 최대 50개의 ID 만 허용한다.
MAX_IDS_PER_REQUEST = 50


@dataclass(frozen=True)
class SearchConfig:
    api_key: str
    keywords: tuple[str, ...]
    days: int
    max_results_per_keyword: int
    region_code: str
    language: str
    max_subscribers: int
    min_views: int
    min_view_sub_ratio: float
    order: str  # "date" | "viewCount" | "relevance"


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------


def build_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def search_video_ids(youtube, cfg: SearchConfig) -> list[str]:
    """주어진 키워드들로 최근 cfg.days 일 이내 업로드된 영상 ID를 수집한다."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=cfg.days)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    video_ids: list[str] = []
    seen: set[str] = set()

    for keyword in cfg.keywords:
        page_token: str | None = None
        collected = 0
        while collected < cfg.max_results_per_keyword:
            page_size = min(50, cfg.max_results_per_keyword - collected)
            request = youtube.search().list(
                part="id",
                q=keyword,
                type="video",
                order=cfg.order,
                publishedAfter=published_after,
                maxResults=page_size,
                regionCode=cfg.region_code or None,
                relevanceLanguage=cfg.language or None,
                pageToken=page_token,
            )
            response = request.execute()
            for item in response.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    video_ids.append(vid)
            collected += len(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    return video_ids


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_video_details(youtube, video_ids: list[str]) -> list[dict]:
    results: list[dict] = []
    for chunk in _chunks(video_ids, MAX_IDS_PER_REQUEST):
        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(chunk),
            maxResults=MAX_IDS_PER_REQUEST,
        ).execute()
        results.extend(response.get("items", []))
    return results


def fetch_channel_details(youtube, channel_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    unique_ids = list(dict.fromkeys(channel_ids))
    for chunk in _chunks(unique_ids, MAX_IDS_PER_REQUEST):
        response = youtube.channels().list(
            part="snippet,statistics",
            id=",".join(chunk),
            maxResults=MAX_IDS_PER_REQUEST,
        ).execute()
        for item in response.get("items", []):
            out[item["id"]] = item
    return out


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------


def parse_duration_seconds(iso_duration: str | None) -> int:
    if not iso_duration:
        return 0
    try:
        return int(isodate.parse_duration(iso_duration).total_seconds())
    except Exception:
        return 0


def build_dataframe(videos: list[dict], channels: dict[str, dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for v in videos:
        snippet = v.get("snippet", {})
        stats = v.get("statistics", {})
        content = v.get("contentDetails", {})
        channel_id = snippet.get("channelId")
        channel = channels.get(channel_id, {})
        c_stats = channel.get("statistics", {})
        c_snippet = channel.get("snippet", {})

        view_count = int(stats.get("viewCount", 0) or 0)
        like_count = int(stats.get("likeCount", 0) or 0)
        comment_count = int(stats.get("commentCount", 0) or 0)
        subscriber_count = int(c_stats.get("subscriberCount", 0) or 0)
        channel_video_count = int(c_stats.get("videoCount", 0) or 0)

        ratio = view_count / subscriber_count if subscriber_count > 0 else float(view_count)

        thumbs = snippet.get("thumbnails", {}) or {}
        # YouTube API 가 반환하는 사이즈 중 가장 큰 것을 우선 선택.
        thumb_url = ""
        for size in ("maxres", "standard", "high", "medium", "default"):
            entry = thumbs.get(size)
            if entry and entry.get("url"):
                thumb_url = entry["url"]
                break

        rows.append(
            {
                "video_title": snippet.get("title", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "duration_sec": parse_duration_seconds(content.get("duration")),
                "view_count": view_count,
                "like_count": like_count,
                "comment_count": comment_count,
                "subscriber_count": subscriber_count,
                "view_sub_ratio": round(ratio, 2),
                "channel_video_count": channel_video_count,
                "channel_country": c_snippet.get("country", ""),
                "video_url": f"https://www.youtube.com/watch?v={v.get('id')}",
                "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                "thumbnail_url": thumb_url,
                "channel_id": channel_id,
                "video_id": v.get("id"),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df["published_at"] = pd.to_datetime(
            df["published_at"], errors="coerce", utc=True
        )
        # 시간당 조회수 = 조회수 / 업로드 후 경과 시간(시간). 최소 1시간으로 클립.
        now = pd.Timestamp.now(tz="UTC")
        age_h = (now - df["published_at"]).dt.total_seconds() / 3600.0
        df["views_per_hour"] = (
            df["view_count"] / age_h.clip(lower=1)
        ).round(0).astype("Int64")
        # 좋아요(비) = 좋아요/조회수 (%).
        df["like_view_ratio"] = (
            df["like_count"] / df["view_count"].clip(lower=1) * 100
        ).round(1)
        df = df.sort_values("view_sub_ratio", ascending=False).reset_index(drop=True)
    return df


def filter_breakout_channels(df: pd.DataFrame, cfg: SearchConfig) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (
        (df["subscriber_count"] <= cfg.max_subscribers)
        & (df["view_count"] >= cfg.min_views)
        & (df["view_sub_ratio"] >= cfg.min_view_sub_ratio)
    )
    return df[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Title pattern analysis
# ---------------------------------------------------------------------------

# 한/영 공통 불용어. 음악 채널 제목에 흔히 보이지만 패턴 가치는 낮은 단어들.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at",
        "with", "by", "from", "is", "are", "be", "your", "you", "my", "i",
        "그리고", "그", "이", "저", "것", "수", "들", "및", "더",
        "music", "songs", "song", "playlist", "mix", "vibes", "vibe",
    }
)

# 의미 단위로 쪼개기 위한 토크나이저. 한글/영문/숫자만 남기고 공백 분리.
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")
# 흔한 이모지/기호 패턴. 정확한 유니코드 범위 대신 시각적 영향을 주는 핵심 블록만.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # symbols & pictographs, emoticons
    "\U0001FA70-\U0001FAFF"  # extended-A
    "☀-➿"          # misc symbols & dingbats
    "]"
)
_BRACKET_RE = re.compile(r"[\[\]\(\)\{\}【】「」『』<>《》|｜·•・★☆♥♡♪♫]")


def tokenize_title(title: str) -> list[str]:
    if not title:
        return []
    tokens = _TOKEN_RE.findall(title.lower())
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


def ngrams(tokens: list[str], n: int) -> list[str]:
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def analyze_title_patterns(df: pd.DataFrame, top_k: int = 20) -> dict:
    if df.empty:
        return {}

    titles = df["video_title"].fillna("").astype(str).tolist()
    token_lists = [tokenize_title(t) for t in titles]

    uni = Counter(t for toks in token_lists for t in toks)
    bi = Counter(g for toks in token_lists for g in ngrams(toks, 2))
    tri = Counter(g for toks in token_lists for g in ngrams(toks, 3))

    char_lengths = pd.Series([len(t) for t in titles])
    word_counts = pd.Series([len(toks) for toks in token_lists])
    emoji_share = sum(1 for t in titles if _EMOJI_RE.search(t)) / max(len(titles), 1)
    bracket_share = sum(1 for t in titles if _BRACKET_RE.search(t)) / max(len(titles), 1)

    # 고성과 vs 저성과 단어 차이 — 상위 25% 비율 그룹에 더 많이 등장하는 토큰.
    differential: list[tuple[str, float, int, int]] = []
    if "view_sub_ratio" in df.columns and len(df) >= 8:
        q = df["view_sub_ratio"].quantile(0.75)
        is_top = df["view_sub_ratio"] >= q
        top_titles = [token_lists[i] for i in range(len(df)) if is_top.iloc[i]]
        bot_titles = [token_lists[i] for i in range(len(df)) if not is_top.iloc[i]]
        top_n = max(len(top_titles), 1)
        bot_n = max(len(bot_titles), 1)
        top_c = Counter(t for toks in top_titles for t in toks)
        bot_c = Counter(t for toks in bot_titles for t in toks)
        for word, tc in top_c.items():
            if tc < 2:
                continue
            top_rate = tc / top_n
            bot_rate = bot_c.get(word, 0) / bot_n
            lift = top_rate / (bot_rate + 1e-6)
            if lift >= 1.5:
                differential.append((word, round(lift, 2), tc, bot_c.get(word, 0)))
        differential.sort(key=lambda r: r[1], reverse=True)

    return {
        "unigrams": uni.most_common(top_k),
        "bigrams": bi.most_common(top_k),
        "trigrams": tri.most_common(top_k),
        "char_length": {
            "mean": round(char_lengths.mean(), 1) if len(char_lengths) else 0,
            "median": int(char_lengths.median()) if len(char_lengths) else 0,
            "min": int(char_lengths.min()) if len(char_lengths) else 0,
            "max": int(char_lengths.max()) if len(char_lengths) else 0,
        },
        "word_count": {
            "mean": round(word_counts.mean(), 1) if len(word_counts) else 0,
            "median": int(word_counts.median()) if len(word_counts) else 0,
        },
        "emoji_share": round(emoji_share, 3),
        "bracket_share": round(bracket_share, 3),
        "differential": differential[:top_k],
        "n_titles": len(titles),
    }


# ---------------------------------------------------------------------------
# Narrative analysis — 장면 · 감정 · 페르소나 · 서사 골격
# ---------------------------------------------------------------------------

# 카테고리별 사전. 키워드는 lower-case 비교가 가능하도록 모두 소문자/원형으로.
# 음악 채널 제목 도메인 지식에 맞춰 축소 — 정확도보다 재현율 우선.
NARRATIVE_LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "시간": {
        "새벽": ("새벽", "dawn"),
        "아침": ("아침", "morning"),
        "낮/오후": ("낮", "오후", "afternoon", "daytime"),
        "저녁": ("저녁", "evening", "sunset", "dusk"),
        "밤/심야": ("밤", "야간", "한밤", "night", "midnight", "late night"),
    },
    "날씨": {
        "비": ("비", "비오는", "빗", "rain", "rainy"),
        "눈": ("눈", "snow", "snowy"),
        "맑음": ("햇살", "sunny", "sunshine"),
        "흐림": ("흐린", "구름", "cloudy", "foggy", "안개"),
    },
    "장소": {
        "카페": ("카페", "cafe", "coffee shop"),
        "방/침대": ("방", "침대", "room", "bedroom", "bed"),
        "자연": ("숲", "바다", "강", "산", "forest", "ocean", "beach", "river", "nature"),
        "도시/거리": ("거리", "도시", "street", "city", "tokyo", "seoul", "paris"),
        "차/길": ("차", "운전", "drive", "driving", "road", "highway"),
    },
    "활동/상황": {
        "공부/작업": ("공부", "작업", "집중", "study", "studying", "work", "working", "focus"),
        "수면": ("잠", "수면", "취침", "sleep", "sleeping", "잠들"),
        "휴식": ("휴식", "쉴", "relax", "chill", "unwind"),
        "운전": ("운전", "drive", "driving"),
        "운동": ("운동", "workout", "running"),
        "독서": ("독서", "reading", "책"),
    },
    "감정": {
        "위로/힐링": ("위로", "힐링", "healing", "comfort", "soothing"),
        "슬픔/우울": ("슬픈", "우울", "외로운", "쓸쓸", "sad", "lonely", "melancholy", "blue"),
        "따뜻/포근": ("따뜻", "포근", "warm", "cozy"),
        "잔잔/평온": ("잔잔", "조용", "고요", "calm", "peaceful", "quiet", "gentle"),
        "감성/노스탤지어": ("감성", "추억", "그리운", "emotional", "nostalgic", "nostalgia", "sentimental"),
        "행복/밝음": ("행복", "기쁜", "happy", "joyful", "bright", "uplifting"),
        "몽환/꿈": ("몽환", "꿈", "dreamy", "dream", "ethereal"),
    },
    "장르/형식": {
        "lofi": ("lofi", "lo-fi", "로파이"),
        "재즈": ("재즈", "jazz"),
        "피아노": ("피아노", "piano"),
        "어쿠스틱": ("어쿠스틱", "acoustic", "guitar"),
        "앰비언트": ("앰비언트", "ambient"),
        "클래식": ("클래식", "classical"),
        "playlist": ("playlist", "플레이리스트", "모음", "mix"),
    },
}

# 청자 페르소나(누구를 위한 BGM 인가)를 시사하는 표현 패턴.
PERSONA_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"([가-힣A-Za-z]{1,8})\s*할\s*때", "{0}할 때"),       # "잠 안 올 때", "공부할 때"
    (r"([가-힣A-Za-z]{1,8})\s*못\s*할\s*때", "{0} 못할 때"),
    (r"([가-힣A-Za-z]{1,10})\s*위한", "{0} 위한"),           # 조사(을/를/이/가)는 토큰에 포함된 채로 둠
    (r"([가-힣A-Za-z]{1,10})\s*에게", "{0}에게"),
    (r"for\s+([a-z]+ing)", "for {0}"),                       # "for studying", "for sleeping"
    (r"to\s+([a-z]+)\s+to", "to {0} to"),                     # "beats to study to"
    (r"when\s+you\s+([a-z]+)", "when you {0}"),
)

# 한국어 조사 꼬리. 페르소나 토큰 끝에 붙으면 떼고 보여준다.
_KO_PARTICLES = ("을", "를", "이", "가", "은", "는", "에게")


def _strip_particle(token: str) -> str:
    for p in _KO_PARTICLES:
        if token.endswith(p) and len(token) > len(p):
            return token[: -len(p)]
    return token


def _scan_lexicon(text_lower: str) -> dict[str, list[str]]:
    """제목 1개에서 카테고리별로 매칭된 태그들을 뽑는다."""
    hits: dict[str, list[str]] = {}
    for category, tags in NARRATIVE_LEXICON.items():
        found: list[str] = []
        for tag, keywords in tags.items():
            if any(kw in text_lower for kw in keywords):
                found.append(tag)
        if found:
            hits[category] = found
    return hits


def _scan_personas(text: str) -> list[str]:
    out: list[str] = []
    low = text.lower()
    for pattern, template in PERSONA_PATTERNS:
        for m in re.finditer(pattern, low):
            try:
                token = _strip_particle(m.group(1))
                out.append(template.format(token))
            except (IndexError, KeyError):
                out.append(template)
    return out


def _narrative_skeleton(hits: dict[str, list[str]]) -> str | None:
    """매칭된 카테고리 태그들을 정해진 순서로 이어 '서사 골격' 한 줄을 만든다."""
    order = ("시간", "날씨", "장소", "활동/상황", "감정", "장르/형식")
    parts = [hits[cat][0] for cat in order if cat in hits]
    if len(parts) < 2:
        return None
    return " · ".join(parts)


def analyze_narrative(df: pd.DataFrame, top_k: int = 12) -> dict:
    if df.empty:
        return {}

    titles = df["video_title"].fillna("").astype(str).tolist()

    category_counts: dict[str, Counter] = {cat: Counter() for cat in NARRATIVE_LEXICON}
    skeletons: Counter = Counter()
    personas: Counter = Counter()
    coverage = 0  # 최소 1개 이상 태그가 잡힌 제목 수

    per_title_hits: list[dict[str, list[str]]] = []
    for title in titles:
        low = title.lower()
        hits = _scan_lexicon(low)
        per_title_hits.append(hits)
        if hits:
            coverage += 1
        for cat, tags in hits.items():
            for tag in tags:
                category_counts[cat][tag] += 1
        skel = _narrative_skeleton(hits)
        if skel:
            skeletons[skel] += 1
        for p in _scan_personas(title):
            personas[p] += 1

    # 카테고리 간 동시 출현(co-occurrence) — 어떤 시간·감정 조합이 자주 함께 나오는가.
    pair_counts: Counter = Counter()
    for hits in per_title_hits:
        cats = sorted(hits.keys())
        for i in range(len(cats)):
            for j in range(i + 1, len(cats)):
                a, b = cats[i], cats[j]
                pair_counts[
                    f"{a}={hits[a][0]}  ×  {b}={hits[b][0]}"
                ] += 1

    # 고성과 그룹에서 유난히 자주 보이는 서사 골격 — 어떤 스토리가 통했는가.
    skeleton_lift: list[tuple[str, float, int, int]] = []
    if "view_sub_ratio" in df.columns and len(df) >= 8:
        q = df["view_sub_ratio"].quantile(0.75)
        top_idx = [i for i, v in enumerate(df["view_sub_ratio"].tolist()) if v >= q]
        bot_idx = [i for i, v in enumerate(df["view_sub_ratio"].tolist()) if v < q]
        top_skel = Counter(
            s for i in top_idx if (s := _narrative_skeleton(per_title_hits[i]))
        )
        bot_skel = Counter(
            s for i in bot_idx if (s := _narrative_skeleton(per_title_hits[i]))
        )
        tn = max(len(top_idx), 1)
        bn = max(len(bot_idx), 1)
        for skel, tc in top_skel.items():
            if tc < 2:
                continue
            lift = (tc / tn) / ((bot_skel.get(skel, 0) / bn) + 1e-6)
            if lift >= 1.5:
                skeleton_lift.append((skel, round(lift, 2), tc, bot_skel.get(skel, 0)))
        skeleton_lift.sort(key=lambda r: r[1], reverse=True)

    return {
        "n_titles": len(titles),
        "coverage_rate": round(coverage / max(len(titles), 1), 3),
        "categories": {
            cat: counter.most_common(top_k) for cat, counter in category_counts.items()
        },
        "skeletons": skeletons.most_common(top_k),
        "personas": personas.most_common(top_k),
        "cooccurrence": pair_counts.most_common(top_k),
        "skeleton_lift": skeleton_lift[:top_k],
    }


def summarize_story(narrative: dict) -> str:
    """카테고리별 1위 태그를 이어 '지배 서사' 한 줄 요약."""
    cats = narrative.get("categories", {})
    pick = {c: (lst[0][0] if lst else None) for c, lst in cats.items()}
    fragments: list[str] = []
    if pick.get("시간"):
        fragments.append(f"**{pick['시간']}**")
    if pick.get("날씨"):
        fragments.append(f"**{pick['날씨']}** 날")
    if pick.get("장소"):
        fragments.append(f"**{pick['장소']}**에서")
    if pick.get("활동/상황"):
        fragments.append(f"**{pick['활동/상황']}** 상황의")
    if pick.get("감정"):
        fragments.append(f"**{pick['감정']}** 정서를 담은")
    if pick.get("장르/형식"):
        fragments.append(f"**{pick['장르/형식']}**")
    if not fragments:
        return "지배적 서사를 추출할 만큼 단서가 부족합니다."
    return " ".join(fragments) + " — 이 카테고리의 지배 서사입니다."


# ---------------------------------------------------------------------------
# Title & tag recommendation — 알고리즘 친화적 제목/태그 합성
# ---------------------------------------------------------------------------

# 카테고리 태그의 '제목 문장에 자연스럽게 박히는 표면형'. 템플릿에 그대로 끼워넣어도
# 어색하지 않도록 어미·조사를 미리 붙여둔다.
SURFACE_FORMS_KO: dict[str, dict[str, str]] = {
    "시간": {
        "새벽": "새벽",
        "아침": "아침",
        "낮/오후": "오후",
        "저녁": "저녁 노을",
        "밤/심야": "한밤",
    },
    "날씨": {
        "비": "비 오는 날",
        "눈": "눈 내리는 날",
        "맑음": "햇살 좋은 날",
        "흐림": "흐린 날",
    },
    "장소": {
        "카페": "카페에서",
        "방/침대": "침대에서",
        "자연": "숲속에서",
        "도시/거리": "도시 밤거리에서",
        "차/길": "드라이브할 때",
    },
    "활동/상황": {
        "공부/작업": "공부할 때",
        "수면": "잠 안 올 때",
        "휴식": "쉬어가고 싶을 때",
        "운전": "운전할 때",
        "운동": "운동할 때",
        "독서": "책 읽을 때",
    },
    "감정": {
        "위로/힐링": "위로가 필요한",
        "슬픔/우울": "혼자인",
        "따뜻/포근": "포근한",
        "잔잔/평온": "잔잔한",
        "감성/노스탤지어": "감성",
        "행복/밝음": "기분 좋은",
        "몽환/꿈": "몽환적인",
    },
    "장르/형식": {
        "lofi": "lofi",
        "재즈": "재즈",
        "피아노": "피아노",
        "어쿠스틱": "어쿠스틱 기타",
        "앰비언트": "앰비언트",
        "클래식": "클래식",
        "playlist": "플레이리스트",
    },
}

SURFACE_FORMS_EN: dict[str, dict[str, str]] = {
    "시간": {
        "새벽": "dawn",
        "아침": "morning",
        "낮/오후": "afternoon",
        "저녁": "sunset",
        "밤/심야": "late night",
    },
    "날씨": {
        "비": "rainy",
        "눈": "snowy",
        "맑음": "sunny",
        "흐림": "foggy",
    },
    "장소": {
        "카페": "cafe",
        "방/침대": "bedroom",
        "자연": "forest",
        "도시/거리": "city",
        "차/길": "drive",
    },
    "활동/상황": {
        "공부/작업": "studying",
        "수면": "sleeping",
        "휴식": "relaxing",
        "운전": "driving",
        "운동": "workout",
        "독서": "reading",
    },
    "감정": {
        "위로/힐링": "soothing",
        "슬픔/우울": "melancholy",
        "따뜻/포근": "cozy",
        "잔잔/평온": "calm",
        "감성/노스탤지어": "nostalgic",
        "행복/밝음": "uplifting",
        "몽환/꿈": "dreamy",
    },
    "장르/형식": {
        "lofi": "lofi",
        "재즈": "jazz",
        "피아노": "piano",
        "어쿠스틱": "acoustic",
        "앰비언트": "ambient",
        "클래식": "classical",
        "playlist": "playlist",
    },
}

# 한국어 제목 템플릿. {카테고리} 자리에는 SURFACE_FORMS_KO 의 표면형이 들어간다.
# 자리가 비면(=해당 카테고리 태그가 데이터에 없으면) 해당 템플릿은 스킵.
TITLE_TEMPLATES_KO: tuple[str, ...] = (
    "{시간} {감정} {장르/형식} 모음 🎧",
    "{날씨} {장소} 듣는 {장르/형식}",
    "{활동/상황} 듣는 {감정} {장르/형식}",
    "{감정} {장르/형식} | {시간} BGM",
    "{시간} {장소} {장르/형식} 플레이리스트",
    "{날씨} {시간}에 어울리는 {장르/형식}",
    "{감정} {장르/형식} ({활동/상황})",
    "{시간} 듣기 좋은 {감정} {장르/형식} 1시간",
    "혼자 듣는 {감정} {장르/형식} · {시간}",
    "{날씨} {시간} {장소} 잔잔한 {장르/형식}",
)

TITLE_TEMPLATES_EN: tuple[str, ...] = (
    "{장르/형식} for {활동/상황}",
    "{날씨} {시간} {장소} {장르/형식}",
    "{장르/형식} to {활동/상황} to",
    "{감정} {장르/형식} playlist",
    "{날씨} {시간} {장르/형식} mix",
    "{감정} {장르/형식} for a {날씨} {시간}",
    "{시간} {장르/형식} | {활동/상황}",
)


def detect_dominant_language(titles: list[str]) -> str:
    ko = sum(1 for t in titles for c in t if "가" <= c <= "힣")
    en = sum(1 for t in titles for c in t if "a" <= c.lower() <= "z")
    return "ko" if ko >= en else "en"


def _pick_surface(
    narrative: dict, category: str, lang: str, rng: random.Random
) -> str | None:
    """카테고리에서 빈도 가중으로 태그를 뽑아 표면형으로 변환."""
    items = narrative.get("categories", {}).get(category, [])
    if not items:
        return None
    pool = items[:3]  # 노이즈를 줄이기 위해 카테고리 상위 3개로 한정
    tags = [t for t, _ in pool]
    weights = [max(c, 1) for _, c in pool]
    tag = rng.choices(tags, weights=weights, k=1)[0]
    forms = SURFACE_FORMS_KO if lang == "ko" else SURFACE_FORMS_EN
    return forms.get(category, {}).get(tag, tag)


_SLOT_RE = re.compile(r"\{([^}]+)\}")


def generate_titles(
    narrative: dict,
    *,
    n: int = 5,
    seed_theme: str | None = None,
    random_state: int | None = None,
    lang: str = "ko",
    existing_titles: Iterable[str] = (),
) -> list[dict]:
    """추천 제목 n개를 합성한다. 반환은 {title, template, used} 리스트."""
    if not narrative:
        return []
    rng = random.Random(random_state)
    templates = TITLE_TEMPLATES_KO if lang == "ko" else TITLE_TEMPLATES_EN

    # 강한 시그널이 있는 카테고리만 후보 템플릿으로 추림.
    cat_available = {
        cat for cat, lst in narrative.get("categories", {}).items() if lst
    }
    usable_templates = [
        t for t in templates
        if all(slot in cat_available for slot in _SLOT_RE.findall(t))
    ]
    if not usable_templates:
        return []

    seen_norm: set[str] = {t.strip().lower() for t in existing_titles}
    out: list[dict] = []
    attempts = 0
    max_attempts = n * 20
    while len(out) < n and attempts < max_attempts:
        attempts += 1
        tpl = rng.choice(usable_templates)
        slots = _SLOT_RE.findall(tpl)
        values: dict[str, str] = {}
        ok = True
        for slot in slots:
            v = _pick_surface(narrative, slot, lang, rng)
            if not v:
                ok = False
                break
            values[slot] = v
        if not ok:
            continue
        title = tpl.format(**values).strip()

        if seed_theme:
            theme = seed_theme.strip()
            if theme and theme.lower() not in title.lower():
                # 50% 확률로 테마를 앞 또는 뒤에 자연스럽게 결합
                title = (
                    f"{theme} · {title}" if rng.random() < 0.5
                    else f"{title} - {theme}"
                )

        norm = title.lower()
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        out.append({"title": title, "template": tpl, "values": values})
    return out


def generate_tags(
    narrative: dict,
    search_keywords: Iterable[str],
    *,
    df: pd.DataFrame | None = None,
    top_k: int = 25,
) -> list[str]:
    """YouTube 태그 후보. 검색 키워드 → 카테고리 표면형(KR+EN) → 고성과 단어 → 콤보 순."""
    tags: list[str] = []
    seen: set[str] = set()

    def add(token: str | None) -> None:
        if not token:
            return
        t = token.strip().lower()
        if not t or t in seen or len(t) < 2:
            return
        seen.add(t)
        tags.append(t)

    for kw in search_keywords:
        add(kw)

    cats = narrative.get("categories", {})
    for cat, items in cats.items():
        for tag, _ in items[:3]:
            add(SURFACE_FORMS_KO.get(cat, {}).get(tag))
            add(SURFACE_FORMS_EN.get(cat, {}).get(tag))

    # 데이터에서 검증된 고성과 단어가 있다면 함께 노출.
    if df is not None and not df.empty:
        patterns = analyze_title_patterns(df, top_k=15)
        for word, _ in patterns.get("unigrams", [])[:10]:
            add(word)
        for word, _, _, _ in patterns.get("differential", [])[:5]:
            add(word)

    # 자주 검색되는 콤보 태그도 추가 (장르 × 활동, 날씨 × 장르).
    def first(cat: str) -> str | None:
        lst = cats.get(cat, [])
        return lst[0][0] if lst else None

    genre = first("장르/형식")
    activity = first("활동/상황")
    weather = first("날씨")
    time_tag = first("시간")
    if genre and activity:
        en_g = SURFACE_FORMS_EN["장르/형식"].get(genre, genre)
        en_a = SURFACE_FORMS_EN["활동/상황"].get(activity, activity)
        add(f"{en_g} for {en_a}")
    if weather and genre:
        en_w = SURFACE_FORMS_EN["날씨"].get(weather, weather)
        en_g = SURFACE_FORMS_EN["장르/형식"].get(genre, genre)
        add(f"{en_w} {en_g}")
    if time_tag and genre:
        ko_t = SURFACE_FORMS_KO["시간"].get(time_tag, time_tag)
        ko_g = SURFACE_FORMS_KO["장르/형식"].get(genre, genre)
        add(f"{ko_t} {ko_g}")

    return tags[:top_k]


# ---------------------------------------------------------------------------
# Thumbnail analysis — 색감 · 구도 · 인물 · 배경
# ---------------------------------------------------------------------------

# 색을 무드 단어로 매핑하기 위한 기준선. HSV 공간에서 거리 비교용.
COLOR_MOODS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("warm orange",  (255, 140,  60)),
    ("warm red",     (210,  60,  60)),
    ("golden",       (230, 190,  90)),
    ("pastel pink",  (240, 180, 200)),
    ("cool blue",    ( 70, 120, 200)),
    ("deep navy",    ( 30,  40,  90)),
    ("cool teal",    ( 60, 160, 170)),
    ("forest green", ( 60, 120,  80)),
    ("muted purple", (130, 100, 160)),
    ("neutral gray", (140, 140, 140)),
    ("near black",   ( 25,  25,  30)),
    ("near white",   (235, 235, 235)),
)


def _closest_mood(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    best, best_d = "neutral", 10**9
    for name, (mr, mg, mb) in COLOR_MOODS:
        d = (r - mr) ** 2 + (g - mg) ** 2 + (b - mb) ** 2
        if d < best_d:
            best, best_d = name, d
    return best


@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def _download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.content:
            return None
        return resp.content
    except Exception:
        return None


def _dominant_palette(img: Image.Image, n: int = 5) -> list[tuple[int, tuple[int, int, int]]]:
    """이미지 → (픽셀수, RGB) 리스트. 빈도순 정렬."""
    small = img.convert("RGB").resize((128, 72))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    counts = q.getcolors() or []  # [(count, palette_index), ...]
    out: list[tuple[int, tuple[int, int, int]]] = []
    for count, idx in counts:
        base = idx * 3
        rgb = tuple(palette[base : base + 3])
        if len(rgb) == 3:
            out.append((count, rgb))  # type: ignore[arg-type]
    out.sort(reverse=True)
    return out[:n]


def _brightness_saturation(img: Image.Image) -> tuple[float, float, float]:
    """전체 평균 (brightness 0-1, saturation 0-1, warmth -1..1)."""
    arr = np.asarray(img.convert("RGB").resize((128, 72)), dtype=np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    brightness = float(((r + g + b) / 3.0).mean())
    max_c = arr.max(axis=-1)
    min_c = arr.min(axis=-1)
    saturation = float(np.where(max_c > 0, (max_c - min_c) / np.clip(max_c, 1e-6, 1), 0).mean())
    warmth = float((r.mean() - b.mean()))  # +면 따뜻함, -면 차가움
    return brightness, saturation, warmth


def _composition_zone(img: Image.Image) -> str:
    """9분할 격자에서 휘도 무게중심이 어디인지 (예: 좌하단, 정중앙)."""
    gray = np.asarray(img.convert("L").resize((120, 90)), dtype=np.float32)
    h, w = gray.shape
    cells = []
    rows = ["상단", "중단", "하단"]
    cols = ["좌측", "중앙", "우측"]
    for ri in range(3):
        for ci in range(3):
            block = gray[
                ri * h // 3 : (ri + 1) * h // 3,
                ci * w // 3 : (ci + 1) * w // 3,
            ]
            cells.append((block.mean(), rows[ri], cols[ci]))
    cells.sort(reverse=True)
    _, row, col = cells[0]
    if row == "중단" and col == "중앙":
        return "정중앙"
    return f"{row} {col}"


def _detect_faces(img: Image.Image) -> tuple[int, float]:
    """(얼굴 개수, 화면 점유율). cv2 없으면 (0, 0.0)."""
    if not _HAS_CV2 or cv2 is None:
        return 0, 0.0
    arr = np.asarray(img.convert("RGB").resize((480, 270)))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(
        gray, scaleFactor=1.2, minNeighbors=4, minSize=(24, 24)
    )
    if len(faces) == 0:
        return 0, 0.0
    area = sum(int(w * h) for (_, _, w, h) in faces)
    total = 480 * 270
    return int(len(faces)), round(area / total, 3)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def analyze_thumbnail(url: str) -> dict | None:
    raw = _download_image(url)
    if not raw:
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return None

    palette = _dominant_palette(img, n=5)
    total = sum(c for c, _ in palette) or 1
    palette_pct = [
        {"rgb": rgb, "share": round(count / total, 3), "mood": _closest_mood(rgb)}
        for count, rgb in palette
    ]
    brightness, saturation, warmth = _brightness_saturation(img)
    zone = _composition_zone(img)
    face_count, face_area = _detect_faces(img)

    return {
        "palette": palette_pct,
        "brightness": round(brightness, 3),
        "saturation": round(saturation, 3),
        "warmth": round(warmth, 3),
        "composition_zone": zone,
        "face_count": face_count,
        "face_area_ratio": face_area,
        "width": img.width,
        "height": img.height,
    }


def aggregate_thumbnail_signals(per_video: list[dict]) -> dict:
    """여러 썸네일 분석 결과를 합쳐 '이 카테고리의 대표 비주얼' 요약."""
    if not per_video:
        return {}

    mood_counter: Counter = Counter()
    palette_weighted: list[tuple[float, tuple[int, int, int]]] = []
    zone_counter: Counter = Counter()
    brightnesses: list[float] = []
    saturations: list[float] = []
    warmths: list[float] = []
    face_counts: list[int] = []
    face_areas: list[float] = []
    with_face = 0

    for v in per_video:
        for entry in v.get("palette", []):
            mood_counter[entry["mood"]] += entry["share"]
            palette_weighted.append((entry["share"], tuple(entry["rgb"])))
        zone_counter[v["composition_zone"]] += 1
        brightnesses.append(v["brightness"])
        saturations.append(v["saturation"])
        warmths.append(v["warmth"])
        face_counts.append(v["face_count"])
        face_areas.append(v["face_area_ratio"])
        if v["face_count"] > 0:
            with_face += 1

    n = len(per_video)
    avg_b = sum(brightnesses) / n
    avg_s = sum(saturations) / n
    avg_w = sum(warmths) / n

    def label_brightness(b: float) -> str:
        if b < 0.35:
            return "어두운 (저조도)"
        if b < 0.55:
            return "은은한 미드톤"
        return "밝은 (하이키)"

    def label_saturation(s: float) -> str:
        if s < 0.2:
            return "탈채도/모노톤"
        if s < 0.45:
            return "차분한 채도"
        return "비비드 채도"

    def label_warmth(w: float) -> str:
        if w > 0.05:
            return "따뜻한 톤 우세"
        if w < -0.05:
            return "차가운 톤 우세"
        return "중성 톤"

    return {
        "n_thumbnails": n,
        "top_moods": mood_counter.most_common(5),
        "top_zones": zone_counter.most_common(3),
        "brightness_avg": round(avg_b, 3),
        "saturation_avg": round(avg_s, 3),
        "warmth_avg": round(avg_w, 3),
        "brightness_label": label_brightness(avg_b),
        "saturation_label": label_saturation(avg_s),
        "warmth_label": label_warmth(avg_w),
        "face_present_share": round(with_face / n, 3),
        "avg_face_count": round(sum(face_counts) / n, 2),
        "avg_face_area_ratio": round(sum(face_areas) / n, 3),
        "cv_available": _HAS_CV2,
    }


# ---------------------------------------------------------------------------
# Thumbnail prompt generator — 텍스트-투-이미지 추천 프롬프트
# ---------------------------------------------------------------------------

PROMPT_STYLES: tuple[tuple[str, str], ...] = (
    ("anime / lo-fi illustration",
     "anime illustration, soft cel shading, lofi vibe, by studio ghibli inspired"),
    ("cinematic photograph",
     "cinematic photo, 35mm film grain, shallow depth of field, dramatic lighting"),
    ("3d render / cozy diorama",
     "isometric 3d render, cozy diorama, soft global illumination, octane render"),
    ("minimal vector",
     "minimal vector illustration, flat shapes, limited palette, clean lines"),
    ("painterly / oil",
     "painterly oil illustration, visible brushstrokes, soft edges, warm chiaroscuro"),
)


def _scene_clause(narrative: dict, lang: str = "en") -> str:
    cats = narrative.get("categories", {})
    forms = SURFACE_FORMS_EN if lang == "en" else SURFACE_FORMS_KO

    def top(cat: str) -> str | None:
        lst = cats.get(cat, [])
        return forms.get(cat, {}).get(lst[0][0], lst[0][0]) if lst else None

    parts: list[str] = []
    time_t = top("시간")
    weather = top("날씨")
    place = top("장소")
    emotion = top("감정")
    activity = top("활동/상황")
    genre = top("장르/형식")

    if weather and time_t:
        parts.append(f"a {weather} {time_t}")
    elif time_t:
        parts.append(f"a {time_t} scene")
    if place:
        parts.append(f"in a {place}")
    if activity:
        parts.append(f"someone {activity}" if lang == "en" else activity)
    if emotion:
        parts.append(f"{emotion} mood")
    if genre:
        parts.append(f"evoking {genre} music")
    return ", ".join(parts) if parts else "a cozy ambient scene"


def generate_thumbnail_prompts(
    narrative: dict,
    thumb_summary: dict,
    *,
    n: int = 5,
    seed_theme: str | None = None,
    random_state: int | None = None,
) -> list[dict]:
    if not narrative:
        return []
    rng = random.Random(random_state)

    palette_words = ", ".join(m for m, _ in thumb_summary.get("top_moods", [])[:3]) or "warm and cool harmony"
    brightness = thumb_summary.get("brightness_label", "은은한 미드톤")
    saturation = thumb_summary.get("saturation_label", "차분한 채도")
    warmth = thumb_summary.get("warmth_label", "중성 톤")
    face_share = thumb_summary.get("face_present_share", 0)
    avg_face_area = thumb_summary.get("avg_face_area_ratio", 0)
    zones = [z for z, _ in thumb_summary.get("top_zones", [])]
    zone_hint = zones[0] if zones else "정중앙"

    # 분석 결과로부터 인물/배경 구성을 추정.
    if face_share >= 0.5 and avg_face_area >= 0.05:
        subject_hint = (
            "single character close-up, eyes visible, looking off-camera"
            if avg_face_area >= 0.12
            else "character mid-shot integrated with the environment"
        )
    elif face_share >= 0.2:
        subject_hint = "background figure silhouette, environment-led composition"
    else:
        subject_hint = "no people, atmospheric still-life, environment hero"

    scene_clause_en = _scene_clause(narrative, lang="en")
    if seed_theme:
        scene_clause_en = f"{seed_theme}, {scene_clause_en}"

    # 영문 프롬프트 (이미지 모델용) + 한글 요약문 동시 생성.
    out: list[dict] = []
    styles_pool = list(PROMPT_STYLES)
    rng.shuffle(styles_pool)
    while len(out) < n:
        style_name, style_clause = styles_pool[len(out) % len(styles_pool)]
        composition = (
            f"rule-of-thirds composition with focal point at {zone_hint}, "
            "16:9 aspect ratio, room for bold title text on the negative-space side"
        )
        lighting = f"{brightness}, {saturation}, {warmth}"
        text_prompt = (
            f"{style_clause}. {scene_clause_en}. {subject_hint}. "
            f"Color palette: {palette_words}. Lighting: {lighting}. {composition}. "
            "Highly polished YouTube thumbnail, clear visual hierarchy."
        )
        negative_prompt = (
            "blurry, low contrast, cluttered composition, watermark, deformed faces, "
            "extra fingers, oversaturated, text artifacts"
        )
        out.append(
            {
                "style": style_name,
                "prompt": text_prompt,
                "negative_prompt": negative_prompt,
                "summary_ko": (
                    f"**{style_name}** · 색감: {palette_words} · "
                    f"무드: {brightness}, {warmth} · 포컬: {zone_hint} · "
                    f"인물: {'중심 인물' if face_share >= 0.5 else '환경 중심'}"
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# AI storytelling — Gemini / OpenAI 추상화 + 프롬프트 체인
# ---------------------------------------------------------------------------

# 사용자 입력 톤을 모든 프롬프트에 공통 주입하기 위한 시스템 메시지.
TONE_GUIDE = """
[글쓰기 톤 가이드 — 반드시 준수]
- 공감 · 위로 · 평안함을 전하는 언어
- "당신은 사랑받고 있다"는 느낌이 자연스럽게 스며들도록
- 강요·자극·단정형 지양, 청유형·서술형·물음형 위주
- 청취자의 마음(감정)과 육신(몸의 건강·컨디션)을 묻는 따뜻한 질문을
  반드시 한 곳에 자연스럽게 포함시킬 것
- 부드럽고 시적이지만, 누구나 한 번에 이해되는 어휘를 사용
"""


def _prompt_seo(theme: str) -> str:
    return f"""당신은 한국어 유튜브 음악 채널의 SEO 카피라이터입니다.

[채널의 주제 및 감정]
{theme}

{TONE_GUIDE}

위 톤을 유지하면서, 다음 항목을 한국어로 작성해 **JSON 객체 하나로만** 응답하세요.
JSON 외의 설명·코드펜스(```)는 출력하지 마세요.

스키마:
{{
  "thumbnail_headlines": ["12자 이내 헤드라인", "...", "..."],
  "titles": ["50자 이내 제목", "...", "...", "...", "..."],
  "description": "180~280자 영상 설명. 자연스럽게 검색 키워드를 포함하고, 청취자의 마음과 몸 컨디션을 묻는 따뜻한 한 줄을 마지막 근처에 넣을 것.",
  "hashtags": ["#한글태그", "#english_tag", "..."]
}}

지침:
- thumbnail_headlines 는 3개
- titles 5개는 각각 다른 진입각(감정형 / 시간대형 / 상황형 / 활동형 / 의문형)
- hashtags 는 12~15개, 한·영 혼합
"""


def _prompt_opening(theme: str) -> str:
    return f"""당신은 한국어로 글을 쓰는 작가이며, 청취자를 깊이 위로하는 사람입니다.

[채널의 주제 및 감정]
{theme}

{TONE_GUIDE}

위 톤을 그대로 살려, 영상 초반 **15~30초 분량 (약 70~110자, 6~8개 짧은 문장)** 의
오프닝 내레이션 대본을 한국어로 써주세요. AI 음성 더빙용입니다.

형식:
- 한 줄에 한 문장씩, 호흡 단위로 줄바꿈
- 마지막은 부드럽게 음악으로 넘어가는 연결 한 줄
- 별도 설명/제목/마크다운 없이 **대본 본문만** 출력
"""


def _prompt_lyrics(theme: str) -> str:
    return f"""당신은 따뜻한 위로를 전하는 한국어 노래 작사가입니다.

[채널의 주제 및 감정]
{theme}

{TONE_GUIDE}

다음 구조로 **완벽하게 구조화된** 한국어 가사를 써주세요. 각 섹션 헤더([Verse 1] 등)는
대괄호 그대로 출력하고, 헤더와 가사 사이는 한 줄 띄움.

[Verse 1]
…

[Pre-Chorus]
…

[Chorus]
…

[Verse 2]
…

[Bridge]
…

[Outro]
…

조건:
- 청취자의 마음(감정)과 육신(몸의 건강·컨디션)을 묻는 한 줄을 가사 어딘가에 자연스럽게 포함
- 한 섹션은 3~6줄로 간결하게
- 어휘는 시적이지만 누구나 이해 가능하게

마지막 줄에 다음 정확한 형식으로 음악 스타일 태그를 영문 8~12개 제시 (Suno/Udio 호환):
Style Prompts: tag1, tag2, tag3, ...

예) Style Prompts: lo-fi, soft piano, warm pad, 70 BPM, breathy female vocal, healing, intimate, gentle reverb

가사 본문과 'Style Prompts: …' 한 줄 외에 다른 설명/마크다운은 포함하지 마세요.
"""


def _call_gemini(
    api_key: str, prompt: str, *, model: str, response_json: bool
) -> str:
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-generativeai 패키지가 설치되어 있지 않습니다. "
            "`pip install google-generativeai` 후 다시 시도하세요."
        ) from e
    genai.configure(api_key=api_key)
    gen_cfg: dict = {"temperature": 0.9}
    if response_json:
        gen_cfg["response_mime_type"] = "application/json"
    m = genai.GenerativeModel(model_name=model, generation_config=gen_cfg)
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def _call_openai(
    api_key: str, prompt: str, *, model: str, response_json: bool
) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai 패키지가 설치되어 있지 않습니다. "
            "`pip install openai` 후 다시 시도하세요."
        ) from e
    client = OpenAI(api_key=api_key)
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
    }
    if response_json:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def call_llm(
    provider: str,
    api_key: str,
    prompt: str,
    *,
    model: str,
    response_json: bool = False,
) -> str:
    if provider == "gemini":
        return _call_gemini(api_key, prompt, model=model, response_json=response_json)
    if provider == "openai":
        return _call_openai(api_key, prompt, model=model, response_json=response_json)
    raise ValueError(f"Unknown provider: {provider}")


def _ai_generate(prompt: str, gemini_key: str, openai_key: str,
                 temperature: float = 0.9) -> tuple[str, str]:
    """Gemini 우선 호출, 실패 시 OpenAI 자동 폴백.
    Returns (raw_text, used_provider).
    API_KEY_SERVICE_BLOCKED 등 Gemini 오류 시 OpenAI로 전환.
    """
    _GEMINI_BLOCKED_HINTS = ("API_KEY_SERVICE_BLOCKED", "blocked", "403", "PERMISSION_DENIED")

    if gemini_key:
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(
                "gemini-1.5-flash",
                generation_config={"temperature": temperature},
            )
            resp = model.generate_content(prompt)
            return (resp.text or "").strip(), "gemini"
        except Exception as e:
            err_str = str(e)
            if any(h in err_str for h in _GEMINI_BLOCKED_HINTS):
                # API 키 서비스 차단 → OpenAI 폴백
                if openai_key:
                    pass  # fall through to OpenAI below
                else:
                    raise RuntimeError(
                        "🚫 Gemini API 키가 차단되었습니다 (API_KEY_SERVICE_BLOCKED).\n\n"
                        "**해결 방법:**\n"
                        "1. [Google Cloud Console](https://console.cloud.google.com) → API 및 서비스 → 사용 설정된 API\n"
                        "2. **'Generative Language API'** 검색 후 **사용 설정**\n"
                        "3. API 키 제한이 있다면 해당 API 허용 목록에 추가\n\n"
                        "또는 OpenAI API 키를 등록하면 자동으로 사용됩니다."
                    ) from e
            else:
                raise

    if openai_key:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip(), "openai"

    raise RuntimeError("Gemini 또는 OpenAI API 키를 먼저 등록해주세요.")


def _parse_seo_payload(raw: str) -> dict:
    """LLM 이 JSON 외 텍스트(코드펜스 등)를 섞어 보내도 견디게 파싱."""
    import json

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 텍스트 안에 떠 있는 첫 JSON 블록을 추출 시도.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {"_raw": raw}


def generate_story_package(
    provider: str,
    api_key: str,
    theme: str,
    *,
    model: str,
) -> dict:
    """SEO · 오프닝 · 가사 3개를 순차 호출해 한 묶음으로 돌려준다."""
    seo_raw = call_llm(
        provider, api_key, _prompt_seo(theme), model=model, response_json=True
    )
    seo = _parse_seo_payload(seo_raw)

    opening = call_llm(
        provider, api_key, _prompt_opening(theme), model=model, response_json=False
    )
    lyrics = call_llm(
        provider, api_key, _prompt_lyrics(theme), model=model, response_json=False
    )
    return {"seo": seo, "opening": opening, "lyrics": lyrics}


# ---------------------------------------------------------------------------
# Pipeline (cached)
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False, ttl=60 * 30)
def run_pipeline(cfg: SearchConfig) -> pd.DataFrame:
    youtube = build_client(cfg.api_key)
    video_ids = search_video_ids(youtube, cfg)
    if not video_ids:
        return pd.DataFrame()
    videos = fetch_video_details(youtube, video_ids)
    channel_ids = [v.get("snippet", {}).get("channelId") for v in videos if v.get("snippet")]
    channels = fetch_channel_details(youtube, [c for c in channel_ids if c])
    return build_dataframe(videos, channels)


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------


LANG_NAMES: dict[str, str] = {
    "ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese",
    "es": "Spanish", "hi": "Hindi", "fr": "French", "de": "German",
    "pt": "Portuguese", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai",
    "ar": "Arabic", "ru": "Russian", "it": "Italian",
}

# (라벨, 지역코드, 언어코드). 마지막 항목은 직접 입력용.
COUNTRY_PRESETS: list[tuple[str, str, str]] = [
    ("🇰🇷 한국 (한국어)", "KR", "ko"),
    ("🇺🇸 미국 (English)", "US", "en"),
    ("🇬🇧 영국 (English)", "GB", "en"),
    ("🇯🇵 일본 (日本語)", "JP", "ja"),
    ("🇹🇼 대만 (中文)", "TW", "zh"),
    ("🇪🇸 스페인 (Español)", "ES", "es"),
    ("🇲🇽 멕시코 (Español)", "MX", "es"),
    ("🇮🇳 인도 (हिन्दी)", "IN", "hi"),
    ("🇫🇷 프랑스 (Français)", "FR", "fr"),
    ("🇩🇪 독일 (Deutsch)", "DE", "de"),
    ("🇧🇷 브라질 (Português)", "BR", "pt"),
    ("🇮🇩 인도네시아", "ID", "id"),
    ("🇻🇳 베트남", "VN", "vi"),
    ("🇹🇭 태국", "TH", "th"),
    ("🇸🇦 사우디 (العربية)", "SA", "ar"),
    ("🌐 직접 입력", "", ""),
]


def translate_keywords(
    keywords: tuple[str, ...], target_lang_name: str
) -> tuple[list[str] | None, str]:
    """키워드를 대상 언어로 번역. (translated_list|None, info). 키 없으면 'no_key'."""
    gem = os.getenv("GEMINI_API_KEY") or SAVED_KEYS.get("gemini", "")
    oai = os.getenv("OPENAI_API_KEY") or SAVED_KEYS.get("openai", "")
    if gem:
        provider, key, model = "gemini", gem, DEFAULT_MODELS["gemini"]
    elif oai:
        provider, key, model = "openai", oai, DEFAULT_MODELS["openai"]
    else:
        return None, "no_key"
    prompt = (
        "You are a YouTube SEO translator. Translate each search keyword into natural "
        f"{target_lang_name} phrases that native creators and viewers would actually type "
        "to find that kind of music/mood. Preserve the mood/situation nuance. "
        'Return ONLY JSON in this shape: {"translated": ["...", "..."]} — same count and order.\n\n'
        + json.dumps(list(keywords), ensure_ascii=False)
    )
    try:
        raw = call_llm(provider, key, prompt, model=model, response_json=True)
    except Exception as e:
        return None, f"error: {e}"
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            arr = data.get("translated") or data.get("keywords") or []
        elif isinstance(data, list):
            arr = data
        else:
            arr = []
        out = [str(x).strip() for x in arr if str(x).strip()]
        return (out or None), provider
    except Exception as e:
        return None, f"parse_error: {e}"


def render_sidebar() -> SearchConfig | None:
    st.sidebar.header("🔍 검색 설정")

    api_key = st.sidebar.text_input(
        "YouTube Data API v3 키",
        value=DEFAULT_API_KEY,
        type="password",
        key="yt_api_key_input",
        help=(
            "https://console.cloud.google.com/ 에서 발급. "
            "아래 💾 저장 버튼을 누르면 .streamlit/keys.json 에 보관되어 "
            "해지 전까지 모든 세션에서 자동으로 불러옵니다."
        ),
    )

    saved_yt = SAVED_KEYS.get("youtube", "")
    if saved_yt:
        st.sidebar.caption("🔒 저장된 키가 자동으로 불러와졌습니다.")
    save_col, clear_col = st.sidebar.columns(2)
    if save_col.button("💾 저장", use_container_width=True, key="yt_key_save"):
        if api_key.strip():
            save_key("youtube", api_key.strip())
            SAVED_KEYS["youtube"] = api_key.strip()
            st.sidebar.success("저장됨. 다음부터 자동으로 불러옵니다.")
        else:
            st.sidebar.warning("키 값이 비어 있어 저장하지 않았습니다.")
    if clear_col.button(
        "🗑️ 해지", use_container_width=True, key="yt_key_clear", disabled=not saved_yt
    ):
        clear_key("youtube")
        SAVED_KEYS.pop("youtube", None)
        st.session_state.pop("yt_api_key_input", None)
        st.sidebar.info("저장된 키를 삭제했습니다.")
        st.rerun()

    keywords_raw = st.sidebar.text_area(
        "키워드 (상황/감정 기반, 줄바꿈 또는 쉼표로 구분)",
        value="비 오는 날 카페\n잠 안 올 때 듣는 lofi\n새벽 감성 피아노\nrainy night jazz",
        height=140,
    )

    days = st.sidebar.slider("최근 N일 이내 업로드", 1, 90, 30)
    max_results = st.sidebar.slider("키워드당 검색 결과 수", 10, 200, 50, step=10)

    st.sidebar.markdown("---")
    st.sidebar.subheader("📈 급상승 필터")
    max_subscribers = st.sidebar.number_input(
        "최대 구독자 수 (이하)", min_value=0, value=10_000, step=500
    )
    min_views = st.sidebar.number_input(
        "최소 조회수 (이상)", min_value=0, value=5_000, step=500
    )
    min_ratio = st.sidebar.number_input(
        "최소 조회수/구독자 비율", min_value=0.0, value=2.0, step=0.5
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🌍 검색 대상 국가·언어")
    preset_labels = [p[0] for p in COUNTRY_PRESETS]
    pick = st.sidebar.selectbox(
        "국가 / 언어 선택",
        options=preset_labels,
        index=0,
        key="country_preset",
        help="선택한 국가·언어권의 채널을 검색합니다. (지역코드 + 언어 우선순위 적용)",
    )
    sel = COUNTRY_PRESETS[preset_labels.index(pick)]
    if sel[1] == "":  # 직접 입력
        region = st.sidebar.text_input("지역 코드 (ISO 3166-1)", value="KR")
        language = st.sidebar.text_input("언어 코드 (예: ko, en, ja)", value="ko")
    else:
        region, language = sel[1], sel[2]
        st.sidebar.caption(f"→ 지역 `{region}` · 언어 `{language}` 로 검색")
    target_lang_name = LANG_NAMES.get(language, language)

    translate_kw = st.sidebar.checkbox(
        "🌐 키워드를 대상 언어로 자동 번역",
        value=(language != "ko"),
        key="translate_kw",
        help=(
            "켜면 한국어로 키워드를 써도 대상 국가 언어로 자동 번역해 그 언어권 채널을 "
            "찾아줍니다. (예: '비 오는 날 카페' → 미국 선택 시 'rainy day cafe' 로 검색) "
            "Gemini 또는 OpenAI 키가 필요합니다 (AI 스토리텔링 탭에서 저장)."
        ),
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ 고급")
    order = st.sidebar.selectbox(
        "정렬 기준",
        options=["date", "viewCount", "relevance"],
        index=1,
    )

    run = st.sidebar.button("🚀 발굴 시작", type="primary", use_container_width=True)

    if not run:
        return None
    if not api_key:
        st.sidebar.error("API 키를 입력하세요.")
        return None

    keywords = tuple(
        k.strip()
        for k in keywords_raw.replace(",", "\n").splitlines()
        if k.strip()
    )
    if not keywords:
        st.sidebar.error("키워드를 1개 이상 입력하세요.")
        return None

    # 대상 언어로 키워드 자동 번역 (한국어 외 대상 + 토글 ON).
    if translate_kw and language and language != "ko":
        with st.spinner(f"키워드를 {target_lang_name} 로 번역 중..."):
            translated, info = translate_keywords(keywords, target_lang_name)
        if translated:
            keywords = tuple(translated)
            st.sidebar.success(
                "번역된 키워드로 검색합니다:\n\n"
                + "\n".join(f"• {k}" for k in translated)
            )
        elif info == "no_key":
            st.sidebar.warning(
                "번역하려면 'AI 스토리텔링 & 가사 생성' 탭에서 Gemini 또는 OpenAI 키를 "
                "저장하세요. 이번에는 원본 키워드로 검색합니다."
            )
        else:
            st.sidebar.warning(
                f"키워드 번역에 실패해 원본으로 검색합니다. ({info})"
            )

    return SearchConfig(
        api_key=api_key,
        keywords=keywords,
        days=days,
        max_results_per_keyword=max_results,
        region_code=region.strip().upper(),
        language=language.strip().lower(),
        max_subscribers=int(max_subscribers),
        min_views=int(min_views),
        min_view_sub_ratio=float(min_ratio),
        order=order,
    )


def render_results(df: pd.DataFrame, filtered: pd.DataFrame, cfg: SearchConfig) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("검색 영상 수", f"{len(df):,}")
    col2.metric("필터 통과", f"{len(filtered):,}")
    col3.metric("유니크 채널", f"{filtered['channel_id'].nunique() if not filtered.empty else 0:,}")
    avg_ratio = filtered["view_sub_ratio"].mean() if not filtered.empty else 0
    col4.metric("평균 조회/구독 비율", f"{avg_ratio:,.2f}")

    st.markdown("### 🚀 급상승 레퍼런스 채널")
    if filtered.empty:
        st.info(
            "조건에 맞는 채널이 없습니다. 사이드바의 필터를 완화해보세요 "
            "(예: 최대 구독자 수↑, 최소 조회수↓, 최소 비율↓)."
        )
    else:
        sort_opts = {
            "조회수 ÷ 구독자 (급상승)": "view_sub_ratio",
            "시간당 조회수": "views_per_hour",
            "조회수": "view_count",
            "구독자수": "subscriber_count",
            "좋아요(비)": "like_view_ratio",
            "최신 업로드": "published_at",
        }
        sc1, sc2 = st.columns([3, 2])
        sort_label = sc1.selectbox(
            "정렬 기준", list(sort_opts.keys()), index=0, key="disc_sort"
        )
        order_desc = sc2.radio(
            "순서", ["높은 순", "낮은 순"], index=0, key="disc_sort_order",
            horizontal=True,
        ) == "높은 순"
        filtered = filtered.sort_values(
            sort_opts[sort_label], ascending=not order_desc, na_position="last"
        ).reset_index(drop=True)

        st.caption(
            f"총 {len(filtered):,}개 결과 · {sort_label} {'높은' if order_desc else '낮은'} 순  ·  "
            "마음에 드는 영상의 **‘✓ 제목 담기’** 를 체크하면 아래에서 한꺼번에 복사·다운로드할 수 있어요."
        )
        MAX_CARDS = 60
        selected_titles: list[str] = []
        for idx, (_, r) in enumerate(filtered.head(MAX_CARDS).iterrows()):
            vid = f"{idx}_{r.get('video_id') or ''}"
            with st.container(border=True):
                ci, ct = st.columns([1, 3])
                with ci:
                    thumb = r.get("thumbnail_url")
                    if isinstance(thumb, str) and thumb:
                        st.image(thumb, width="stretch")
                with ct:
                    st.markdown(f"**{r['video_title']}**")
                    vph = int(r["views_per_hour"]) if pd.notna(r.get("views_per_hour")) else 0
                    st.markdown(
                        f"조회수 **{int(r['view_count']):,}** · 시간당 **{vph:,}** · "
                        f"구독자 **{int(r['subscriber_count']):,}**"
                    )
                    st.markdown(
                        f"댓글 {int(r['comment_count']):,} · 좋아요(비) {r['like_view_ratio']}% · "
                        f"조회/구독 {r['view_sub_ratio']:.1f}배"
                    )
                    pub = r["published_at"]
                    pub_s = pub.strftime("%Y-%m-%d") if pd.notna(pub) else ""
                    st.caption(f"채널: {r['channel_title']}  ·  업로드: {pub_s}")
                    lc, rc = st.columns([1, 2])
                    if lc.checkbox("✓ 제목 담기", key=f"pick_{vid}"):
                        selected_titles.append(str(r["video_title"]))
                    rc.markdown(f"[▶ 영상 열기]({r['video_url']})")
        if len(filtered) > MAX_CARDS:
            st.caption(f"… 외 {len(filtered) - MAX_CARDS:,}개는 아래 CSV로 확인하세요.")

        # 담은 제목 모음 — 복사 / 다운로드 / 제목 공식 Lab 으로 보내기
        if selected_titles:
            st.markdown(f"#### 📋 담은 제목 {len(selected_titles)}개")
            joined = "\n".join(selected_titles)
            st.text_area(
                "복사용 (칸 안 클릭 → Ctrl+A → Ctrl+C)",
                value=joined, height=160, key="picked_titles_area",
            )
            bc1, bc2 = st.columns(2)
            bc1.download_button(
                "📥 담은 제목 다운로드 (.txt)",
                data=joined.encode("utf-8-sig"),
                file_name=f"picked_titles_{datetime.now():%Y%m%d_%H%M%S}.txt",
                mime="text/plain",
                use_container_width=True,
            )
            if bc2.button(
                "➡️ '제목 공식 Lab' 입력칸에 넣기", use_container_width=True
            ):
                st.session_state["title_lab_input"] = joined
                st.success("✅ '제목 공식 Lab' 탭의 입력칸에 넣었습니다. 그 탭으로 이동해 분석하세요.")

        st.download_button(
            "📥 CSV 다운로드 (전체)",
            data=filtered.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"breakout_channels_{datetime.now():%Y%m%d_%H%M%S}.csv",
            mime="text/csv",
        )

    render_recommendations(filtered, df, cfg)

    with st.expander("🔬 전체 검색 결과 보기 (필터 적용 전)"):
        full_cols = [
            c for c in [
                "thumbnail_url", "video_title", "channel_title",
                "subscriber_count", "view_count", "views_per_hour",
                "comment_count", "like_view_ratio", "view_sub_ratio",
                "published_at", "video_url",
            ] if c in df.columns
        ]
        st.dataframe(
            df[full_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "thumbnail_url": st.column_config.ImageColumn("썸네일"),
                "video_title": st.column_config.TextColumn("제목", width="large"),
                "channel_title": st.column_config.TextColumn("채널명"),
                "subscriber_count": st.column_config.NumberColumn("구독자수", format="%d"),
                "view_count": st.column_config.NumberColumn("조회수", format="%d"),
                "views_per_hour": st.column_config.NumberColumn("시간당조회수", format="%d"),
                "comment_count": st.column_config.NumberColumn("댓글수", format="%d"),
                "like_view_ratio": st.column_config.NumberColumn("좋아요(비)", format="%.1f%%"),
                "view_sub_ratio": st.column_config.NumberColumn("조회/구독", format="%.1f"),
                "published_at": st.column_config.DatetimeColumn("업로드일", format="YYYY-MM-DD HH:mm"),
                "video_url": st.column_config.LinkColumn("유튜브", display_text="▶ 열기"),
            },
        )


def render_narrative(filtered: pd.DataFrame, full: pd.DataFrame) -> None:
    st.markdown("### 🎬 제목 서사 분석 (Scene · Emotion · Persona)")
    source = filtered if not filtered.empty else full
    if source.empty:
        st.info("분석할 제목이 없습니다.")
        return

    narrative = analyze_narrative(source)
    coverage = narrative.get("coverage_rate", 0)
    st.caption(
        f"분석 대상 제목 {narrative['n_titles']:,}개 · "
        f"서사 단서 태깅된 비율 {coverage*100:.0f}%"
    )

    st.success("📖 " + summarize_story(narrative))

    cat_tabs = st.tabs(
        ["시간", "날씨", "장소", "활동/상황", "감정", "장르/형식"]
    )
    cat_order = ["시간", "날씨", "장소", "활동/상황", "감정", "장르/형식"]
    for tab, cat in zip(cat_tabs, cat_order):
        with tab:
            data = narrative["categories"].get(cat, [])
            if not data:
                st.info(f"'{cat}' 단서가 잡힌 제목이 없습니다.")
                continue
            df_cat = pd.DataFrame(data, columns=[cat, "빈도"])
            st.bar_chart(df_cat.set_index(cat), height=280)
            st.dataframe(df_cat, hide_index=True, use_container_width=True)

    st.markdown("#### 🧱 서사 골격 (Scene → Emotion → Genre)")
    skeletons = narrative.get("skeletons", [])
    if skeletons:
        df_sk = pd.DataFrame(skeletons, columns=["서사 골격", "빈도"])
        st.dataframe(df_sk, hide_index=True, use_container_width=True)
        st.caption(
            "여러 카테고리 단서를 잡아낸 제목들을 정해진 순서(시간→날씨→장소→상황→감정→장르)로 "
            "이어 만든 골격입니다. 같은 골격이 반복될수록 그 채널군의 정형화된 스토리텔링."
        )
    else:
        st.info("2개 이상 카테고리가 동시에 잡힌 제목이 부족합니다.")

    lift = narrative.get("skeleton_lift", [])
    if lift:
        st.markdown("#### 🚀 고성과 그룹에서 두드러진 서사")
        df_lift = pd.DataFrame(
            lift, columns=["서사 골격", "Lift", "상위그룹 등장", "그 외 등장"]
        )
        st.dataframe(df_lift, hide_index=True, use_container_width=True)
        st.caption(
            "조회/구독 비율 상위 25% 영상에서 그 외 그룹보다 자주 반복된 골격. "
            "벤치마킹 우선순위가 높습니다."
        )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 👤 청자 페르소나 표현")
        personas = narrative.get("personas", [])
        if personas:
            st.dataframe(
                pd.DataFrame(personas, columns=["표현", "빈도"]),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("페르소나 표현이 감지되지 않았습니다.")
    with col_b:
        st.markdown("#### 🔗 카테고리 동시 출현")
        pairs = narrative.get("cooccurrence", [])
        if pairs:
            st.dataframe(
                pd.DataFrame(pairs, columns=["조합", "빈도"]),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("2개 카테고리가 동시에 잡힌 제목이 부족합니다.")


def render_recommendations(
    filtered: pd.DataFrame, full: pd.DataFrame, cfg: SearchConfig
) -> None:
    st.markdown("### 🎯 알고리즘 추천 제목 & 태그")
    source = filtered if not filtered.empty else full
    if source.empty:
        st.info("추천을 만들 데이터가 없습니다.")
        return

    narrative = analyze_narrative(source)
    if not narrative.get("categories"):
        st.info("데이터가 너무 적어 추천을 만들 수 없습니다.")
        return

    titles_list = source["video_title"].fillna("").astype(str).tolist()
    detected_lang = detect_dominant_language(titles_list)

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        seed_theme = st.text_input(
            "강조하고 싶은 주제 / 분위기 (선택)",
            key="rec_seed_theme",
            placeholder="예: 비 오는 새벽, study with me, 잠 못 드는 밤",
            help="비워두면 데이터에서 추출한 지배 서사 그대로 합성합니다.",
        )
    with col2:
        lang_choice = st.selectbox(
            "언어",
            options=["자동 감지", "한국어", "English"],
            index=0,
            key="rec_lang_choice",
        )
    with col3:
        st.write("")
        st.write("")
        regen = st.button("🔄 다시 생성", use_container_width=True, key="rec_regen")

    if "rec_regen_counter" not in st.session_state:
        st.session_state.rec_regen_counter = 0
    if regen:
        st.session_state.rec_regen_counter += 1

    lang_code = (
        "ko" if lang_choice == "한국어"
        else "en" if lang_choice == "English"
        else detected_lang
    )

    # 같은 검색 결과 안에서는 동일한 시드일 때 같은 추천이 나오도록,
    # 검색 키워드 + 재생성 카운터 + 시드 테마를 해시해 random_state 로 사용.
    seed_base = (
        "|".join(cfg.keywords)
        + f"|{lang_code}"
        + f"|{seed_theme}"
        + f"|{st.session_state.rec_regen_counter}"
    )
    random_state = abs(hash(seed_base)) % (2**32)

    recommendations = generate_titles(
        narrative,
        n=5,
        seed_theme=seed_theme or None,
        random_state=random_state,
        lang=lang_code,
        existing_titles=titles_list,
    )

    st.markdown("#### ✍️ 추천 제목 5개")
    if not recommendations:
        st.warning(
            "현재 데이터에서 모든 슬롯을 채울 만한 카테고리 시그널이 부족합니다. "
            "키워드를 좀 더 좁히거나 필터를 완화해보세요."
        )
    else:
        for i, rec in enumerate(recommendations, 1):
            st.markdown(f"**{i}.** {rec['title']}")

        st.download_button(
            "📥 제목 5개 텍스트 다운로드",
            data="\n".join(r["title"] for r in recommendations).encode("utf-8"),
            file_name=f"recommended_titles_{datetime.now():%Y%m%d_%H%M%S}.txt",
            mime="text/plain",
            key="rec_download_titles",
        )

    st.markdown("#### 🏷️ 추천 태그")
    tags = generate_tags(narrative, cfg.keywords, df=source)
    if not tags:
        st.info("추천 태그를 만들 만한 데이터가 부족합니다.")
    else:
        tag_csv = ", ".join(tags)
        st.code(tag_csv, language=None)
        st.caption(
            f"{len(tags)}개. YouTube Studio 의 태그 필드에 그대로 붙여넣을 수 있습니다 "
            "(쉼표 구분, 500자 한도)."
        )
        st.download_button(
            "📥 태그 텍스트 다운로드",
            data=tag_csv.encode("utf-8"),
            file_name=f"recommended_tags_{datetime.now():%Y%m%d_%H%M%S}.txt",
            mime="text/plain",
            key="rec_download_tags",
        )


def render_thumbnails(
    filtered: pd.DataFrame, full: pd.DataFrame, cfg: SearchConfig
) -> None:
    st.markdown("### 🖼️ 썸네일 분석 (색감 · 구도 · 인물 · 배경)")
    source = filtered if not filtered.empty else full
    if source.empty or "thumbnail_url" not in source.columns:
        st.info("분석할 썸네일이 없습니다.")
        return

    if not _HAS_CV2:
        st.caption(
            "⚠️ `opencv-python-headless` 미설치 — 얼굴 검출이 비활성화됩니다. "
            "색감/구도/배경 분석은 정상 동작합니다."
        )

    max_n = st.slider(
        "분석할 상위 N개 썸네일",
        min_value=5,
        max_value=min(50, len(source)),
        value=min(20, len(source)),
        step=5,
        key="thumb_n",
        help="조회/구독 비율이 높은 순으로 N개를 분석합니다 (다운로드 + 분석에 시간이 소요).",
    )

    candidates = source.head(max_n)
    per_video: list[dict] = []
    progress = st.progress(0, text="썸네일 다운로드 및 분석 중...")
    for i, row in enumerate(candidates.itertuples(index=False), 1):
        url = getattr(row, "thumbnail_url", "")
        result = analyze_thumbnail(url) if url else None
        if result:
            result["video_title"] = row.video_title
            result["channel_title"] = row.channel_title
            result["view_sub_ratio"] = row.view_sub_ratio
            result["thumbnail_url"] = url
            per_video.append(result)
        progress.progress(i / max(len(candidates), 1), text=f"분석 {i}/{len(candidates)}")
    progress.empty()

    if not per_video:
        st.warning(
            "썸네일을 다운로드/분석할 수 없었습니다. 네트워크 또는 URL 접근을 확인해보세요."
        )
        return

    summary = aggregate_thumbnail_signals(per_video)
    st.session_state["thumb_summary"] = summary

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("평균 밝기", f"{summary['brightness_avg']:.2f}", summary["brightness_label"])
    m2.metric("평균 채도", f"{summary['saturation_avg']:.2f}", summary["saturation_label"])
    m3.metric("색온도", f"{summary['warmth_avg']:+.2f}", summary["warmth_label"])
    if _HAS_CV2:
        m4.metric(
            "인물 포함 비율",
            f"{summary['face_present_share']*100:.0f}%",
            f"평균 얼굴 점유 {summary['avg_face_area_ratio']*100:.1f}%",
        )
    else:
        m4.metric("인물 분석", "비활성", "opencv 미설치")

    col_palette, col_zone = st.columns(2)
    with col_palette:
        st.markdown("#### 🎨 대표 색감 (상위 무드)")
        moods = summary["top_moods"]
        if moods:
            st.dataframe(
                pd.DataFrame(moods, columns=["무드", "가중치"]),
                hide_index=True,
                use_container_width=True,
            )
        # 실제 RGB 스와치 미리보기 — 첫 3개 썸네일의 팔레트.
        swatch_cols = st.columns(min(3, len(per_video)))
        for ci, v in enumerate(per_video[:3]):
            with swatch_cols[ci]:
                st.caption(v["video_title"][:30])
                for entry in v["palette"]:
                    r, g, b = entry["rgb"]
                    st.markdown(
                        f"<div style='background:rgb({r},{g},{b});"
                        f"padding:6px;color:#fff;text-shadow:0 0 3px #000;"
                        f"font-size:11px;border-radius:3px;margin-bottom:2px'>"
                        f"{entry['mood']} · {entry['share']*100:.0f}%</div>",
                        unsafe_allow_html=True,
                    )
    with col_zone:
        st.markdown("#### 🧭 포컬 포인트 (rule of thirds)")
        zones = summary["top_zones"]
        if zones:
            st.dataframe(
                pd.DataFrame(zones, columns=["위치", "빈도"]),
                hide_index=True,
                use_container_width=True,
            )
        st.caption(
            f"인물 배치 추정: " + (
                f"중심 인물 위주 ({summary['face_present_share']*100:.0f}% 영상에 얼굴)"
                if _HAS_CV2 and summary["face_present_share"] >= 0.4
                else "환경/오브젝트 중심 (인물 비중 낮음)"
            )
        )

    with st.expander("📸 분석된 썸네일 미리보기"):
        cols = st.columns(4)
        for i, v in enumerate(per_video[:16]):
            with cols[i % 4]:
                try:
                    st.image(v["thumbnail_url"], use_container_width=True)
                except Exception:
                    pass
                st.caption(
                    f"**비율 {v['view_sub_ratio']:.1f}** · 얼굴 {v['face_count']} · "
                    f"{v['composition_zone']}"
                )

    # ---- 썸네일 추천 프롬프트 ----
    st.markdown("#### 🎨 썸네일 추천 프롬프트 (텍스트-투-이미지)")
    narrative = analyze_narrative(source)

    col_t1, col_t2 = st.columns([4, 1])
    with col_t1:
        thumb_seed = st.text_input(
            "강조하고 싶은 비주얼 컨셉 (선택)",
            key="thumb_seed",
            placeholder="예: girl studying with cat, rainy window, candlelit room",
        )
    with col_t2:
        st.write("")
        st.write("")
        thumb_regen = st.button("🔄 다시 생성", use_container_width=True, key="thumb_regen")

    if "thumb_regen_counter" not in st.session_state:
        st.session_state.thumb_regen_counter = 0
    if thumb_regen:
        st.session_state.thumb_regen_counter += 1

    seed_base = (
        "|".join(cfg.keywords)
        + f"|{thumb_seed}"
        + f"|{st.session_state.thumb_regen_counter}"
    )
    random_state = abs(hash(seed_base)) % (2**32)

    prompts = generate_thumbnail_prompts(
        narrative,
        summary,
        n=5,
        seed_theme=thumb_seed or None,
        random_state=random_state,
    )

    if not prompts:
        st.info("프롬프트 생성을 위한 시그널이 부족합니다.")
        return

    for i, p in enumerate(prompts, 1):
        with st.container(border=True):
            st.markdown(f"**Prompt {i}** — {p['summary_ko']}")
            st.code(p["prompt"], language=None)
            with st.expander("Negative prompt"):
                st.code(p["negative_prompt"], language=None)

    payload = "\n\n---\n\n".join(
        f"# {p['style']}\n{p['prompt']}\n\nNegative: {p['negative_prompt']}"
        for p in prompts
    )
    st.download_button(
        "📥 프롬프트 5개 다운로드 (Markdown)",
        data=payload.encode("utf-8"),
        file_name=f"thumbnail_prompts_{datetime.now():%Y%m%d_%H%M%S}.md",
        mime="text/markdown",
        key="thumb_download",
    )


def render_title_patterns(filtered: pd.DataFrame, full: pd.DataFrame) -> None:
    st.markdown("### 🧩 제목 패턴 분석")
    source = filtered if not filtered.empty else full
    label = "필터 통과 영상" if not filtered.empty else "전체 검색 결과 (필터 통과 0건)"
    if source.empty:
        st.info("분석할 제목이 없습니다.")
        return

    patterns = analyze_title_patterns(source)
    st.caption(f"분석 대상: {label} · 제목 {patterns['n_titles']:,}개")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("평균 글자수", patterns["char_length"]["mean"])
    m2.metric("중앙값 단어수", patterns["word_count"]["median"])
    m3.metric("이모지 포함 비율", f"{patterns['emoji_share']*100:.1f}%")
    m4.metric("괄호/기호 포함 비율", f"{patterns['bracket_share']*100:.1f}%")

    tabs = st.tabs(["단어 (1-gram)", "구문 (2-gram)", "구문 (3-gram)", "🚀 고성과 단어"])

    for tab, key, title in zip(
        tabs[:3],
        ["unigrams", "bigrams", "trigrams"],
        ["단어 빈도", "2-gram 빈도", "3-gram 빈도"],
    ):
        with tab:
            data = patterns[key]
            if not data:
                st.info("데이터 부족")
                continue
            df_ng = pd.DataFrame(data, columns=["패턴", "빈도"])
            st.bar_chart(df_ng.set_index("패턴"), height=320)
            st.dataframe(df_ng, hide_index=True, use_container_width=True)

    with tabs[3]:
        diff = patterns["differential"]
        if not diff:
            st.info(
                "고성과(상위 25%) 그룹과 나머지 그룹에서 유의미한 차이를 보이는 단어가 없습니다. "
                "(샘플이 8개 미만이거나, 동일 단어가 양쪽에 고르게 분포)"
            )
        else:
            st.caption(
                "조회/구독 비율 **상위 25%** 그룹에서 다른 그룹보다 자주 등장하는 단어. "
                "Lift = (상위그룹 등장률) / (그 외 등장률)."
            )
            df_diff = pd.DataFrame(
                diff, columns=["단어", "Lift", "상위그룹 등장", "그 외 등장"]
            )
            st.dataframe(df_diff, hide_index=True, use_container_width=True)
            st.bar_chart(df_diff.set_index("단어")["Lift"], height=320)


# ---------------------------------------------------------------------------
# 핫플리 트렌드 — 장르·국가·기간 필터 + 썸네일 카드 그리드
# ---------------------------------------------------------------------------

# 국가 → (regionCode, languageCode)
_HOTPLI_COUNTRY: dict[str, tuple[str, str]] = {
    "전체": ("", ""),
    "한국": ("KR", "ko"),
    "일본": ("JP", "ja"),
    "미국/영미권": ("US", "en"),
    "유럽": ("GB", "en"),
    "동남아": ("ID", "id"),
    "라틴": ("MX", "es"),
    "인도": ("IN", "hi"),
}

# 국가별 장르 목록 — 선택 국가에 따라 동적으로 바뀜
_HOTPLI_COUNTRY_GENRES: dict[str, list[str]] = {
    "전체": ["전체 (믹스)", "Lo-fi", "재즈", "카페", "공부", "수면", "뉴에이지", "힙합", "클래식"],
    "한국": ["한국 인기", "K-팝", "K-인디", "발라드", "트로트", "한국 R&B", "조선힙합",
             "Lo-fi", "재즈", "카페", "공부", "수면", "뉴에이지"],
    "일본": ["일본 인기", "시티팝", "J-pop", "애니송", "J-rock",
             "Lo-fi", "재즈", "카페", "공부", "수면", "뉴에이지"],
    "미국/영미권": ["미국/영미권 인기", "Hip-hop", "Indie", "R&B", "Country", "Pop",
                   "Lo-fi", "재즈", "클래식", "카페", "공부", "수면", "뉴에이지"],
    "유럽": ["유럽 인기", "팝", "일렉트로닉", "클래식", "재즈", "카페", "공부", "수면"],
    "동남아": ["동남아 인기", "팝", "인디", "전통음악", "카페", "공부", "수면"],
    "라틴": ["라틴 인기", "레게톤", "살사", "보사노바", "팝", "카페", "수면"],
    "인도": ["인도 인기", "볼리우드", "인디팝", "클래식", "명상", "카페", "수면"],
}

# 장르 → YouTube 검색 키워드 매핑
_HOTPLI_GENRE_KEYWORDS: dict[str, list[str]] = {
    # 전체
    "전체 (믹스)": ["music playlist", "음악 플레이리스트"],
    "Lo-fi": ["lofi music", "lo-fi chill", "lofi hip hop"],
    "재즈": ["jazz music", "jazz cafe playlist"],
    "카페": ["cafe music", "coffee shop music"],
    "공부": ["study music", "focus music playlist"],
    "수면": ["sleep music", "relaxing sleep music"],
    "뉴에이지": ["new age music", "instrumental new age"],
    "힙합": ["hip hop playlist", "rap music playlist"],
    "클래식": ["classical music", "orchestra playlist"],
    # 한국
    "한국 인기": ["한국 인기 음악", "Korean popular music playlist"],
    "K-팝": ["K-pop playlist", "K팝 모음"],
    "K-인디": ["K-indie music", "한국 인디 음악"],
    "발라드": ["한국 발라드", "Korean ballad playlist"],
    "트로트": ["트로트 모음", "트로트 플레이리스트"],
    "한국 R&B": ["한국 R&B", "Korean R&B playlist"],
    "조선힙합": ["조선힙합 플레이리스트", "조선힙합"],
    # 일본
    "일본 인기": ["日本 人気 音楽", "Japanese popular music playlist"],
    "시티팝": ["city pop playlist", "シティポップ"],
    "J-pop": ["J-pop playlist", "Jポップ プレイリスト"],
    "애니송": ["anime song playlist", "アニソン"],
    "J-rock": ["J-rock playlist", "日本 ロック"],
    # 미국/영미권
    "미국/영미권 인기": ["US popular music playlist", "American top music"],
    "Hip-hop": ["hip hop playlist", "rap music playlist"],
    "Indie": ["indie music playlist", "indie pop playlist"],
    "R&B": ["R&B playlist", "soul R&B music"],
    "Country": ["country music playlist", "country songs"],
    "Pop": ["pop music playlist", "top pop songs"],
    # 유럽
    "유럽 인기": ["European popular music", "Europe top music playlist"],
    "일렉트로닉": ["electronic music playlist", "EDM playlist"],
    # 동남아
    "동남아 인기": ["Southeast Asia popular music", "OPM playlist"],
    "인디": ["indie music playlist"],
    "전통음악": ["traditional Asian music", "folk music playlist"],
    # 라틴
    "라틴 인기": ["Latin popular music playlist", "musica latina"],
    "레게톤": ["reggaeton playlist", "reggaeton mix"],
    "살사": ["salsa music playlist"],
    "보사노바": ["bossa nova playlist", "bossa nova jazz"],
    # 인도
    "인도 인기": ["Indian popular music playlist", "Bollywood hits"],
    "볼리우드": ["Bollywood songs playlist", "Hindi songs"],
    "인디팝": ["Indian indie pop", "Hindi indie music"],
    "명상": ["Indian meditation music", "yoga music playlist"],
}

_HOTPLI_PERIOD: dict[str, int] = {
    "24시간": 1,
    "7일": 7,
    "14일": 14,
    "30일": 30,
    "90일": 90,
}

_HOTPLI_SORT: dict[str, str] = {
    "조회수 기준": "viewCount",
    "급상승": "date",
    "채널 규모 대비": "viewCount",
}

# 스타일 자동 분류 키워드 (이미지 기준으로 확장)
_HOTPLI_STYLE_KEYWORDS: dict[str, list[str]] = {
    "감성 이미지형": ["감성", "aesthetic", "chill", "playlist", "플레이리스트", "분위기", "이미지"],
    "Lo-fi 캐릭터형": ["lofi", "lo-fi", "lo fi", "anime lofi", "study lofi", "캐릭터"],
    "라이브 송출형": ["live", "라이브", "concert", "공연", "stream", "실황"],
    "장르 마스터형": ["mix", "믹스", "best of", "greatest hits", "명곡", "컬렉션"],
    "하이라이트 메들리형(숏폼)": ["메들리", "medley", "모음", "compilation", "연속듣기", "숏폼", "shorts"],
    "가사 번역 해설형": ["가사", "lyrics", "자막", "번역", "해설", "해석"],
    "라이징 스타 소개형": ["신인", "debut", "new artist", "rising", "떠오르는"],
}


def _classify_style(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    # Lo-fi 캐릭터형을 감성 이미지형보다 먼저 체크 (lo-fi 키워드 겹침 방지)
    for style, keywords in _HOTPLI_STYLE_KEYWORDS.items():
        if any(k.lower() in text for k in keywords):
            return style
    return "감성 이미지형"  # 기본값


def _run_hotpli_search(
    api_key: str,
    genre_kws: list[str],
    region: str,
    language: str,
    days: int,
    sort: str,
    max_results: int = 24,
) -> pd.DataFrame:
    from googleapiclient.discovery import build as yt_build  # type: ignore
    youtube = yt_build("youtube", "v3", developerKey=api_key)

    published_after = (datetime.utcnow() - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    video_ids: list[str] = []
    for kw in genre_kws[:3]:
        try:
            params: dict = dict(
                part="id",
                q=kw,
                type="video",
                videoCategoryId="10",  # Music
                order=sort,
                publishedAfter=published_after,
                maxResults=min(max_results, 50),
            )
            if region:
                params["regionCode"] = region
            if language:
                params["relevanceLanguage"] = language
            resp = youtube.search().list(**params).execute()
            video_ids += [it["id"]["videoId"] for it in resp.get("items", [])]
        except Exception:
            pass

    if not video_ids:
        return pd.DataFrame()

    video_ids = list(dict.fromkeys(video_ids))[:max_results]
    vid_resp = youtube.videos().list(
        part="snippet,statistics,contentDetails",
        id=",".join(video_ids),
    ).execute()

    rows = []
    for item in vid_resp.get("items", []):
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        vid_id = item["id"]
        title = snip.get("title", "")
        desc = snip.get("description", "")
        rows.append({
            "video_id": vid_id,
            "video_title": title,
            "channel_title": snip.get("channelTitle", ""),
            "thumbnail_url": (snip.get("thumbnails") or {}).get("medium", {}).get("url", ""),
            "view_count": int(stats.get("viewCount") or 0),
            "like_count": int(stats.get("likeCount") or 0),
            "comment_count": int(stats.get("commentCount") or 0),
            "published_at": snip.get("publishedAt", "")[:10],
            "video_url": f"https://www.youtube.com/watch?v={vid_id}",
            "style": _classify_style(title, desc),
        })

    return pd.DataFrame(rows)


def render_hotpli_trends() -> None:
    """핫플리 트렌드: 국가 선택 → 국가별 장르 동적 변경 + 기간·정렬·스타일 필터."""
    st.markdown("국가별로 어떤 음악 플레이리스트가 뜨는지 비교해보세요. 국가를 고르면 그 나라에서 실제로 잘 쓰이는 장르가 나옵니다.")

    api_key = (
        st.session_state.get("yt_api_key_input", "")
        or os.getenv("YOUTUBE_API_KEY", "")
        or SAVED_KEYS.get("youtube", "")
    )

    # ── 국가 필터 ──────────────────────────────────────────────
    st.markdown("##### 국가")
    country_sel = st.pills(
        "국가",
        options=list(_HOTPLI_COUNTRY.keys()),
        default="전체",
        key="hotpli_country",
        label_visibility="collapsed",
    )
    active_country = country_sel or "전체"

    # ── 장르 필터 (국가에 따라 동적 변경) ─────────────────────
    genre_options = _HOTPLI_COUNTRY_GENRES.get(active_country, _HOTPLI_COUNTRY_GENRES["전체"])
    # 국가가 바뀌면 이전 장르 선택을 초기화
    prev_country = st.session_state.get("hotpli_prev_country", active_country)
    if prev_country != active_country:
        st.session_state.pop("hotpli_genre", None)
        st.session_state["hotpli_prev_country"] = active_country

    st.markdown("##### 장르")
    genre_sel = st.pills(
        "장르",
        options=genre_options,
        default=genre_options[0],
        key="hotpli_genre",
        label_visibility="collapsed",
    )

    # ── 기간 / 정렬 ────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 기간")
        period_sel = st.pills(
            "기간",
            options=list(_HOTPLI_PERIOD.keys()),
            default="7일",
            key="hotpli_period",
            label_visibility="collapsed",
        )
    with c2:
        st.markdown("##### 정렬")
        sort_sel = st.pills(
            "정렬",
            options=list(_HOTPLI_SORT.keys()),
            default="조회수 기준",
            key="hotpli_sort",
            label_visibility="collapsed",
        )

    # ── 스타일 (결과 후 동적 표시 — 검색 전에는 전체만) ────────
    # 결과가 있으면 실제 분포 기반으로 pill 표시
    _cache_key = f"hotpli_results_{active_country}_{genre_sel}_{period_sel}_{sort_sel}"
    cached_df: pd.DataFrame | None = st.session_state.get(_cache_key)

    if cached_df is not None and not cached_df.empty:
        style_counts = cached_df["style"].value_counts()
        style_options_dynamic = ["전체"] + [
            f"{s} {c}" for s, c in style_counts.items()
        ]
        st.markdown("##### 스타일")
        style_sel_raw = st.pills(
            "스타일",
            options=style_options_dynamic,
            default="전체",
            key=f"hotpli_style_{_cache_key}",
            label_visibility="collapsed",
        )
        # "감성 이미지형 17" → "감성 이미지형" 추출
        style_sel = style_sel_raw.rsplit(" ", 1)[0] if style_sel_raw and style_sel_raw != "전체" else "전체"
    else:
        st.markdown("##### 스타일")
        style_options_static = ["전체"] + list(_HOTPLI_STYLE_KEYWORDS.keys())
        style_sel_raw = st.pills(
            "스타일",
            options=style_options_static,
            default="전체",
            key="hotpli_style_static",
            label_visibility="collapsed",
        )
        style_sel = style_sel_raw or "전체"

    st.divider()

    # ── 검색 실행 버튼 ──────────────────────────────────────────
    if not api_key:
        st.warning("YouTube API 키가 필요합니다. 급상승 채널 발굴 탭 사이드바에서 저장해주세요.")
        return

    run_btn = st.button("🔥 트렌드 검색", type="primary", key="hotpli_run")

    if run_btn:
        region, language = _HOTPLI_COUNTRY.get(active_country, ("", ""))
        active_genre = genre_sel or genre_options[0]
        genre_kws = _HOTPLI_GENRE_KEYWORDS.get(active_genre, ["music playlist"])
        days = _HOTPLI_PERIOD.get(period_sel or "7일", 7)
        sort = _HOTPLI_SORT.get(sort_sel or "조회수 기준", "viewCount")
        with st.spinner("YouTube에서 트렌드 플레이리스트를 가져오는 중..."):
            try:
                df = _run_hotpli_search(api_key, genre_kws, region, language, days, sort)
                st.session_state[_cache_key] = df
                st.rerun()
            except Exception as e:
                st.error(f"검색 오류: {e}")
                return

    df = st.session_state.get(_cache_key)
    if df is None:
        st.info("위 필터를 설정하고 **🔥 트렌드 검색** 버튼을 눌러주세요.")
        return
    if df.empty:
        st.warning("결과가 없습니다. 필터를 바꿔 다시 시도해보세요.")
        return

    # 스타일 필터 적용
    display_df = df.copy()
    if style_sel != "전체":
        display_df = display_df[display_df["style"] == style_sel]

    # 스타일 분포 요약 캡션
    style_counts_all = df["style"].value_counts()
    style_summary_parts = [f"• {s} {c}" for s, c in style_counts_all.items()]
    total = len(df)
    filtered_total = len(display_df)
    filter_label = genre_sel or genre_options[0]
    period_label = period_sel or "7일"
    st.caption(
        f"{active_country} · {filter_label} · {period_label} 인기 영상 **{filtered_total}개** "
        f"(전체 {total}개)  |  스타일: {'  '.join(style_summary_parts)}"
    )

    # ── 썸네일 카드 3열 그리드 ──────────────────────────────────
    COLS = 3
    rows_iter = [
        display_df.iloc[i : i + COLS] for i in range(0, len(display_df), COLS)
    ]
    for row_df in rows_iter:
        cols = st.columns(COLS)
        for col, (_, r) in zip(cols, row_df.iterrows()):
            with col:
                with st.container(border=True):
                    thumb = r.get("thumbnail_url", "")
                    if thumb:
                        st.image(thumb, use_container_width=True)
                    rank_badge = f"#{display_df.index.get_loc(r.name) + 1}"  # type: ignore[arg-type]
                    style_badge = r.get("style", "")
                    st.markdown(
                        f"<span style='background:#e74c3c;color:white;padding:1px 6px;"
                        f"border-radius:4px;font-size:12px;font-weight:bold'>{rank_badge}</span> "
                        f"<span style='background:#f0f0f0;color:#555;padding:1px 6px;"
                        f"border-radius:4px;font-size:11px'>{style_badge}</span>",
                        unsafe_allow_html=True,
                    )
                    title = r["video_title"]
                    st.markdown(
                        f"**[{title[:40]}{'…' if len(title) > 40 else ''}]({r['video_url']})**"
                    )
                    st.caption(
                        f"📺 {r['channel_title']}  \n"
                        f"👁 {int(r['view_count']):,}  💬 {int(r['comment_count']):,}  "
                        f"📅 {r['published_at']}"
                    )

    st.download_button(
        "📥 CSV 다운로드",
        data=display_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"hotpli_trends_{datetime.now():%Y%m%d_%H%M%S}.csv",
        mime="text/csv",
        key="hotpli_csv",
    )


# ---------------------------------------------------------------------------
# 레퍼런스 발굴 탭 (서브탭: 핫플리 트렌드 + 급상승 채널)
# ---------------------------------------------------------------------------

def render_discovery_tab() -> None:
    """레퍼런스 발굴 — 🔥 핫플리 트렌드 / 🔍 급상승 채널 발굴 서브탭."""
    sub_trend, sub_breakout = st.tabs(["🔥 핫플리 트렌드", "🔍 급상승 채널 발굴"])

    with sub_trend:
        render_hotpli_trends()

    with sub_breakout:
        st.caption(
            "YouTube Data API v3 기반. 상황/감정 키워드로 최근 업로드된 영상 중 "
            "'구독자 수 대비 조회수'가 폭발적인 신규 채널을 찾아냅니다."
        )

        new_cfg = render_sidebar()
        if new_cfg is not None:
            st.session_state.active_cfg = new_cfg
            try:
                with st.spinner("YouTube API 호출 및 분석 중..."):
                    st.session_state["disc_df"] = run_pipeline(new_cfg)
            except HttpError as e:
                st.error(f"YouTube API 오류: {e}")
                return
            except Exception as e:
                st.error(f"실행 중 오류: {e}")
                return

        cfg = st.session_state.get("active_cfg")
        df = st.session_state.get("disc_df")
        if cfg is None or df is None:
            st.info("👈 사이드바에서 키워드와 필터를 설정한 뒤 **발굴 시작**을 눌러주세요.")
            return

        if df.empty:
            st.warning("검색 결과가 없습니다. 키워드나 기간을 조정해보세요.")
            return

        filtered = filter_breakout_channels(df, cfg)
        render_results(df, filtered, cfg)


# ---------------------------------------------------------------------------
# AI storytelling tab
# ---------------------------------------------------------------------------

# 프로바이더별 기본 모델. 사용자가 직접 바꿀 수도 있음.
DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o",
}


def _render_seo_card(seo: dict) -> None:
    st.markdown("#### 🔎 [유튜브 SEO]")
    if "_raw" in seo:
        st.warning("JSON 파싱에 실패해 원문을 그대로 표시합니다. 다시 생성을 시도해보세요.")
        st.code(seo["_raw"], language=None)
        return

    headlines = seo.get("thumbnail_headlines", []) or []
    titles = seo.get("titles", []) or []
    description = seo.get("description", "") or ""
    hashtags = seo.get("hashtags", []) or []

    st.markdown("**썸네일 헤드라인**")
    for h in headlines:
        st.markdown(f"- {h}")
    if headlines:
        st.code("\n".join(headlines), language=None)

    st.markdown("**영상 제목 5개**")
    for i, t in enumerate(titles, 1):
        st.markdown(f"{i}. {t}")
    if titles:
        st.code("\n".join(titles), language=None)

    st.markdown("**설명란**")
    st.code(description, language=None)

    st.markdown("**해시태그**")
    tag_line = " ".join(hashtags) if hashtags else ""
    st.code(tag_line, language=None)

    bundle = (
        "## 썸네일 헤드라인\n" + "\n".join(headlines)
        + "\n\n## 영상 제목 5개\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
        + "\n\n## 설명란\n" + description
        + "\n\n## 해시태그\n" + tag_line
    )
    st.download_button(
        "📥 SEO 묶음 다운로드 (.md)",
        data=bundle.encode("utf-8"),
        file_name=f"seo_{datetime.now():%Y%m%d_%H%M%S}.md",
        mime="text/markdown",
        key="story_dl_seo",
    )


def _render_opening_card(opening: str) -> None:
    st.markdown("#### 🎙️ [오프닝 대본]")
    st.caption("AI 음성 더빙용. 한 줄 한 호흡, 마지막 줄에서 음악으로 자연스럽게 연결됩니다.")
    st.code(opening, language=None)
    st.download_button(
        "📥 대본 다운로드 (.txt)",
        data=opening.encode("utf-8"),
        file_name=f"opening_{datetime.now():%Y%m%d_%H%M%S}.txt",
        mime="text/plain",
        key="story_dl_opening",
    )


def _render_lyrics_card(lyrics: str) -> None:
    st.markdown("#### 🎵 [음악 맞춤형 가사 & Style Prompts]")
    style_line = ""
    body = lyrics
    m = re.search(r"^\s*Style\s*Prompts\s*:\s*(.+)$", lyrics, re.MULTILINE | re.IGNORECASE)
    if m:
        style_line = m.group(1).strip()
        body = lyrics[: m.start()].rstrip()

    st.code(body, language=None)
    if style_line:
        st.markdown("**Style Prompts** (Suno/Udio 등 음악 생성용)")
        st.code(style_line, language=None)

    bundle = body + ("\n\nStyle Prompts: " + style_line if style_line else "")
    st.download_button(
        "📥 가사 묶음 다운로드 (.txt)",
        data=bundle.encode("utf-8"),
        file_name=f"lyrics_{datetime.now():%Y%m%d_%H%M%S}.txt",
        mime="text/plain",
        key="story_dl_lyrics",
    )


def render_storytelling_tab() -> None:
    st.subheader("✍️ AI 스토리텔링 & 가사 생성")
    st.caption(
        "채널 컨셉(주제·감정)을 입력하면 SEO 패키지, 오프닝 내레이션, 구조화된 가사를 "
        "한 번에 생성합니다. 대본·가사 톤은 공감·위로·평안함을 기본값으로 유지하며, "
        "청취자의 마음과 몸 컨디션을 묻는 질문을 항상 포함합니다."
    )

    col_p, col_m = st.columns([1, 1])
    with col_p:
        provider_label = st.selectbox(
            "AI 모델",
            options=["Google Gemini (대본·가사 권장)", "OpenAI GPT"],
            index=0,
            key="story_provider",
            help="대본·가사는 Gemini 로 생성하는 것이 권장됩니다.",
        )
    provider = "gemini" if provider_label.startswith("Google") else "openai"
    with col_m:
        model = st.text_input(
            "모델 ID (선택, 비우면 기본값)",
            value="",
            placeholder=DEFAULT_MODELS[provider],
            key="story_model",
        )
    model_final = (model.strip() or DEFAULT_MODELS[provider])

    env_key = (
        os.getenv("GEMINI_API_KEY") if provider == "gemini"
        else os.getenv("OPENAI_API_KEY")
    ) or ""
    api_key = st.text_input(
        f"{'Gemini' if provider == 'gemini' else 'OpenAI'} API 키",
        value=env_key,
        type="password",
        key="story_api_key",
        help=(
            "Gemini: https://aistudio.google.com/app/apikey   "
            "OpenAI: https://platform.openai.com/api-keys"
        ),
    )

    theme = st.text_area(
        "채널의 주제 및 감정",
        value=(
            "아침 산책을 하며 듣기 좋은, 지난 삶을 긍정하게 만드는 따뜻하고 철학적인 이야기. "
            "혼자 걸으며 자신에게 다정하게 말을 거는 듯한 톤, 잔잔한 피아노와 어쿠스틱 기타를 배경으로."
        ),
        height=150,
        key="story_theme",
        help="구체적일수록 결과가 풍부해집니다. 누구를 위해, 어떤 시간/장소/감정인지 함께 적어보세요.",
    )

    col_btn, col_clear = st.columns([1, 1])
    with col_btn:
        run = st.button(
            "🚀 SEO · 대본 · 가사 한 번에 생성",
            type="primary",
            use_container_width=True,
            key="story_run",
        )
    with col_clear:
        clear = st.button(
            "🗑️ 결과 비우기",
            use_container_width=True,
            key="story_clear",
        )

    if clear:
        st.session_state.pop("story_package", None)
        st.session_state.pop("story_theme_used", None)

    if run:
        if not api_key.strip():
            st.error("API 키를 입력해주세요.")
        elif not theme.strip():
            st.error("채널의 주제 및 감정을 입력해주세요.")
        else:
            try:
                with st.spinner(
                    f"{provider_label} 호출 중 — SEO → 오프닝 대본 → 가사 순으로 생성합니다..."
                ):
                    pkg = generate_story_package(
                        provider, api_key.strip(), theme.strip(), model=model_final
                    )
                st.session_state.story_package = pkg
                st.session_state.story_theme_used = theme.strip()
                st.success("생성 완료. 아래 카드에서 확인하고 복사하세요.")
            except RuntimeError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"AI 호출 중 오류: {e}")

    pkg = st.session_state.get("story_package")
    if not pkg:
        st.info(
            "위에 채널 컨셉을 입력하고 **🚀 생성** 버튼을 눌러주세요. "
            "이미 생성한 결과는 '결과 비우기' 전까지 화면에 유지됩니다."
        )
        return

    used = st.session_state.get("story_theme_used", "")
    if used:
        with st.expander("이 결과를 만든 채널 컨셉", expanded=False):
            st.code(used, language=None)

    with st.container(border=True):
        _render_seo_card(pkg.get("seo", {}))
    with st.container(border=True):
        _render_opening_card(pkg.get("opening", "") or "")
    with st.container(border=True):
        _render_lyrics_card(pkg.get("lyrics", "") or "")


# ---------------------------------------------------------------------------
# Audio + Video → MP4 인코딩 (직접 만든 곡 + 배경 영상/이미지 합성)
# ---------------------------------------------------------------------------

IMAGE_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
AUDIO_EXTS: tuple[str, ...] = ("mp3", "wav", "flac", "m4a", "aac", "ogg")
VIDEO_IMAGE_EXTS: tuple[str, ...] = (
    "mp4", "mov", "avi", "mkv", "webm", "png", "jpg", "jpeg", "webp", "bmp"
)


def _find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
# Background job runner — Streamlit 스크립트와 무관하게 ffmpeg 를 백그라운드로 실행.
# 잡 메타는 .streamlit/jobs/*.json 으로 영구화돼 브라우저를 닫아도 살아 남는다.
# ---------------------------------------------------------------------------

JOBS_DIR = os.path.join(".streamlit", "jobs")


def _ensure_jobs_dir() -> None:
    os.makedirs(JOBS_DIR, exist_ok=True)


def _job_meta_path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f"{job_id}.json")


def _job_log_path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f"{job_id}.log")


def _job_progress_path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f"{job_id}.progress")


def _job_workdir(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f"{job_id}_work")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            )
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=10,
            )
        else:
            os.kill(pid, 15)  # SIGTERM
    except Exception:
        pass


def submit_ffmpeg_job(
    cmd: list[str],
    *,
    kind: str,
    title: str,
    output_path: str,
    workdir: str,
    extra: dict | None = None,
) -> str:
    """ffmpeg 명령을 detached 백그라운드 프로세스로 실행하고 job_id 를 반환.

    cmd 에 -progress 옵션이 자동으로 붙어 진행률을 progress 파일로 저장한다.
    """
    _ensure_jobs_dir()
    job_id = uuid.uuid4().hex[:8]
    log_path = _job_log_path(job_id)
    progress_path = _job_progress_path(job_id)

    # ffmpeg 진행률 파이프를 파일로 — Streamlit 이 파싱해서 % 표시.
    final_cmd = list(cmd)
    # 첫 인자가 ffmpeg 면 그 뒤에 -progress 끼워넣기 (없으면 그냥 cmd 그대로).
    if final_cmd and os.path.basename(final_cmd[0]).lower().startswith("ffmpeg"):
        # -progress 와 -nostats 를 -y 다음에 삽입.
        insert_at = 1
        if len(final_cmd) > 1 and final_cmd[1] == "-y":
            insert_at = 2
        final_cmd[insert_at:insert_at] = ["-progress", progress_path, "-nostats"]

    log_f = open(log_path, "w", encoding="utf-8", buffering=1)
    try:
        creationflags = 0
        start_new_session = False
        if sys.platform == "win32":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            )
        else:
            start_new_session = True
        proc = subprocess.Popen(
            final_cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
            close_fds=True,
        )
    except Exception as e:
        log_f.close()
        raise RuntimeError(f"백그라운드 잡 실행 실패: {e}") from e

    meta = {
        "id": job_id,
        "kind": kind,
        "title": title,
        "pid": proc.pid,
        "cmd": final_cmd,
        "log_path": log_path,
        "progress_path": progress_path,
        "output_path": output_path,
        "workdir": workdir,
        "started_at": datetime.now().isoformat(),
        "status": "running",
        "extra": extra or {},
    }
    with open(_job_meta_path(job_id), "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)
    return job_id


def list_jobs() -> list[dict]:
    if not os.path.isdir(JOBS_DIR):
        return []
    jobs = []
    for f in os.listdir(JOBS_DIR):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(JOBS_DIR, f), encoding="utf-8") as fp:
                jobs.append(json.load(fp))
        except Exception:
            continue
    return sorted(jobs, key=lambda j: j.get("started_at", ""), reverse=True)


def refresh_job_status(job: dict) -> dict:
    """PID 와 출력 파일을 보고 running/done/failed 상태를 갱신·저장."""
    status = job.get("status", "running")
    if status in ("done", "failed", "cancelled"):
        return job
    pid = int(job.get("pid", 0))
    alive = _pid_alive(pid)
    if alive:
        return job
    output_path = job.get("output_path", "")
    job["finished_at"] = datetime.now().isoformat()
    if output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        job["status"] = "done"
    else:
        job["status"] = "failed"
    try:
        with open(_job_meta_path(job["id"]), "w", encoding="utf-8") as fp:
            json.dump(job, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return job


def parse_job_progress(progress_path: str) -> dict | None:
    """ffmpeg -progress 출력에서 현재 시간을 파싱.

    파일 형식 예:
        out_time_us=12345678
        out_time=00:00:12.345678
        progress=continue
    """
    if not os.path.exists(progress_path):
        return None
    try:
        with open(progress_path, "rb") as fp:
            fp.seek(0, 2)
            size = fp.tell()
            fp.seek(max(0, size - 4096))
            tail = fp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    info: dict = {}
    for line in tail.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        info[k.strip()] = v.strip()
    if "out_time" in info:
        # H:MM:SS.micro → seconds
        try:
            t = info["out_time"]
            h, m, s = t.split(":")
            info["current_seconds"] = int(h) * 3600 + int(m) * 60 + float(s)
        except (ValueError, AttributeError):
            pass
    return info or None


def cancel_job(job_id: str) -> None:
    job = None
    try:
        with open(_job_meta_path(job_id), encoding="utf-8") as fp:
            job = json.load(fp)
    except Exception:
        return
    if not job:
        return
    _terminate_pid(int(job.get("pid", 0)))
    job["status"] = "cancelled"
    job["finished_at"] = datetime.now().isoformat()
    try:
        with open(_job_meta_path(job_id), "w", encoding="utf-8") as fp:
            json.dump(job, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass


def delete_job(job_id: str, *, remove_files: bool = True) -> None:
    job = None
    try:
        with open(_job_meta_path(job_id), encoding="utf-8") as fp:
            job = json.load(fp)
    except Exception:
        pass
    if job and job.get("status") == "running":
        _terminate_pid(int(job.get("pid", 0)))
    for p in [
        _job_meta_path(job_id),
        _job_log_path(job_id),
        _job_progress_path(job_id),
    ]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
    if remove_files and job:
        workdir = job.get("workdir", "")
        if workdir and os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)


def _ffprobe_duration(path: str) -> float | None:
    """초 단위 길이. ffprobe 없으면 None 반환."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        return float(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None


def concat_audio_files(
    audio_paths: list[str], output_path: str, *, bitrate: str = "320k"
) -> tuple[bool, str]:
    """여러 오디오를 하나로 이어붙임. concat 필터로 재인코딩(샘플레이트 통일)."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다."
    if not audio_paths:
        return False, "이어붙일 오디오가 없습니다."
    if len(audio_paths) == 1:
        try:
            shutil.copyfile(audio_paths[0], output_path)
            return True, "단일 파일 복사 완료."
        except Exception as e:
            return False, f"단일 파일 복사 실패: {e}"

    cmd: list[str] = [ffmpeg, "-y", "-hide_banner"]
    for p in audio_paths:
        cmd += ["-i", p]
    n = len(audio_paths)
    filter_str = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    cmd += [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "aac",
        "-b:a", bitrate,
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60 * 60 * 2)
    except subprocess.TimeoutExpired:
        return False, "오디오 이어붙이기가 2시간 안에 끝나지 않았습니다."
    except FileNotFoundError as e:
        return False, f"ffmpeg 실행 실패 (FileNotFoundError): {e}"
    except Exception as e:
        return False, f"오디오 concat 중 예외: {type(e).__name__}: {e}"
    return proc.returncode == 0, _format_ffmpeg_log(cmd, proc)


def _format_ffmpeg_log(cmd: list[str], proc: subprocess.CompletedProcess) -> str:
    """ffmpeg 결과를 사람이 읽을 수 있는 로그 블록으로 정리한다.

    returncode + 실행한 커맨드 + stdout/stderr 꼬리를 함께 묶어, '(로그 없음)' 처럼
    아무 단서도 없는 실패가 나오지 않도록 한다.
    """
    parts = [f"returncode = {proc.returncode}"]
    parts.append("cmd:\n  " + " ".join(cmd))
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out:
        parts.append("--- stdout (tail) ---\n" + out[-1500:])
    if err:
        parts.append("--- stderr (tail) ---\n" + err[-2500:])
    if not out and not err:
        parts.append("(ffmpeg 가 stdout/stderr 를 출력하지 않았습니다 — 인자 누락/조기 종료 가능성)")
    return "\n\n".join(parts)


def _format_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(tracks: list[dict]) -> str:
    """
    tracks: [{"title": str, "duration": float, "lyrics_lines": list[str]}]
    각 트랙 안에서는 가사 라인을 트랙 길이에 따라 균등 분배,
    트랙 간에는 누적 타임스탬프로 SRT 한 파일을 만든다.
    """
    out: list[str] = []
    cumulative = 0.0
    counter = 1
    for tr in tracks:
        duration = max(float(tr.get("duration", 0) or 0), 0.0)
        lines = [ln.strip() for ln in tr.get("lyrics_lines", []) if ln.strip()]
        if not lines or duration <= 0:
            cumulative += duration
            continue
        per_line = duration / len(lines)
        for i, line in enumerate(lines):
            start = cumulative + i * per_line
            end = cumulative + (i + 1) * per_line
            out.append(str(counter))
            out.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
            out.append(line)
            out.append("")
            counter += 1
        cumulative += duration
    return "\n".join(out).strip() + "\n"


SPEED_PRESETS: dict[str, dict] = {
    "fast": {
        "label": "⚡ 빠른 (8h 영상 ~5분)",
        "preset": "ultrafast",
        "fps_video": 24,
        "fps_static": 1,
        "crf_offset": 0,
    },
    "balanced": {
        "label": "⚖️ 균형 (8h 영상 ~30분)",
        "preset": "veryfast",
        "fps_video": 24,
        "fps_static": 6,
        "crf_offset": 0,
    },
    "quality": {
        "label": "💎 고화질 (8h 영상 ~수시간)",
        "preset": "medium",
        "fps_video": 24,
        "fps_static": 24,
        "crf_offset": 0,
    },
}


def _build_slideshow_cmd(
    image_paths: list[str],
    output_path: str,
    list_path: str,
    *,
    seconds_per_image: float | list[float],
    resolution: str,
    fps: int,
    preset: str,
) -> tuple[list[str], str]:
    """슬라이드쇼 ffmpeg 명령 + concat list 파일 작성. (cmd, list_path) 반환.

    seconds_per_image 는 단일 float 이면 모든 이미지 동일 시간,
    list[float] 이면 이미지별 개별 시간으로 적용.
    """
    ffmpeg = _find_ffmpeg() or "ffmpeg"
    try:
        rw, rh = resolution.lower().split("x")
        rw, rh = int(rw), int(rh)
    except ValueError as e:
        raise ValueError(f"해상도 형식 오류: {resolution!r}") from e

    def _quote(p: str) -> str:
        return p.replace("\\", "/").replace("'", "'\\''")

    if isinstance(seconds_per_image, list):
        if len(seconds_per_image) != len(image_paths):
            raise ValueError(
                f"이미지 수({len(image_paths)})와 개별 시간 리스트 길이"
                f"({len(seconds_per_image)})가 일치하지 않습니다."
            )
        durations = [float(max(0.1, s)) for s in seconds_per_image]
    else:
        durations = [float(seconds_per_image)] * len(image_paths)

    with open(list_path, "w", encoding="utf-8") as fp:
        for p, d in zip(image_paths, durations):
            fp.write(f"file '{_quote(p)}'\n")
            fp.write(f"duration {d}\n")
        fp.write(f"file '{_quote(image_paths[-1])}'\n")

    vf = (
        f"scale={rw}:{rh}:force_original_aspect_ratio=decrease,"
        f"pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
    )
    cmd = [
        ffmpeg, "-y", "-hide_banner",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", "22",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    return cmd, list_path


def build_slideshow_from_images(
    image_paths: list[str],
    output_path: str,
    *,
    seconds_per_image: float = 5.0,
    resolution: str = "1920x1080",
    fps: int = 30,
    preset: str = "medium",
) -> tuple[bool, str]:
    """동기 실행 (백그라운드 잡에서는 _build_slideshow_cmd 만 따로 호출)."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다."
    if not image_paths:
        return False, "슬라이드쇼에 사용할 이미지가 없습니다."

    workdir = os.path.dirname(output_path) or "."
    list_path = os.path.join(workdir, "slideshow_list.txt")
    try:
        cmd, _ = _build_slideshow_cmd(
            image_paths, output_path, list_path,
            seconds_per_image=seconds_per_image,
            resolution=resolution, fps=fps, preset=preset,
        )
    except ValueError as e:
        return False, str(e)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60 * 60,
        )
    except subprocess.TimeoutExpired:
        return False, "슬라이드쇼 생성이 1시간 안에 끝나지 않았습니다."
    except FileNotFoundError as e:
        return False, f"ffmpeg 실행 실패: {e}"
    except Exception as e:
        return False, f"슬라이드쇼 생성 중 예외: {type(e).__name__}: {e}"
    return proc.returncode == 0, _format_ffmpeg_log(cmd, proc)


def _build_audio_only_cmd(
    cycle_audio: str,
    output_path: str,
    *,
    target_duration: float,
    bitrate: str,
) -> list[str]:
    """오디오만 N시간으로 늘려 만드는 ffmpeg 명령. 확장자가 .mp3 면 mp3, 아니면 aac."""
    ffmpeg = _find_ffmpeg() or "ffmpeg"
    cmd = [ffmpeg, "-y", "-hide_banner",
           "-stream_loop", "-1", "-i", cycle_audio,
           "-t", f"{max(0.5, target_duration):.3f}"]
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", bitrate]
    else:
        cmd += ["-c:a", "aac", "-b:a", bitrate]
    cmd += ["-movflags", "+faststart"] if ext in (".m4a", ".mp4") else []
    cmd.append(output_path)
    return cmd


def _build_visual_only_cmd(
    cycle_visual: str,
    output_path: str,
    *,
    target_duration: float,
    is_image: bool,
    resolution: str,
    preset: str,
    framerate: int,
    crf: int,
) -> list[str]:
    """무음 슬라이드/이미지 영상을 target_duration 길이로 만드는 ffmpeg 명령."""
    ffmpeg = _find_ffmpeg() or "ffmpeg"
    try:
        rw, rh = resolution.lower().split("x")
        rw, rh = int(rw), int(rh)
    except ValueError as e:
        raise ValueError(f"해상도 형식 오류: {resolution!r}") from e

    cmd = [ffmpeg, "-y", "-hide_banner"]
    if is_image:
        cmd += ["-loop", "1"]
    else:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", cycle_visual]

    vf = (
        f"scale={rw}:{rh}:force_original_aspect_ratio=decrease,"
        f"pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
    )
    cmd += [
        "-t", f"{max(0.5, target_duration):.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-r", str(framerate),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",  # 무음
    ]
    if is_image:
        cmd += ["-tune", "stillimage", "-g", str(max(framerate * 10, 50))]
    cmd.append(output_path)
    return cmd


def _build_encode_cmd(
    audio_path: str,
    visual_path: str,
    output_path: str,
    *,
    is_image: bool,
    resolution: str,
    audio_bitrate: str,
    crf: int,
    fade_seconds: float,
    audio_duration: float | None,
    subtitles_path: str | None,
    audio_loop_count: int,
    preset: str,
    framerate: int,
) -> list[str]:
    """encode_music_video 용 ffmpeg 인자 리스트만 생성.

    백그라운드 잡 제출 시에도 동일 명령을 재사용한다.
    """
    ffmpeg = _find_ffmpeg() or "ffmpeg"
    try:
        rw, rh = resolution.lower().split("x")
        rw, rh = int(rw), int(rh)
    except ValueError as e:
        raise ValueError(f"해상도 형식 오류: {resolution!r} (예: 1920x1080)") from e

    cmd: list[str] = [ffmpeg, "-y", "-hide_banner"]
    if is_image:
        cmd += ["-loop", "1"]
    else:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", visual_path]

    if audio_loop_count > 1:
        cmd += ["-stream_loop", str(audio_loop_count - 1)]
    cmd += ["-i", audio_path]

    vf_parts = [
        f"scale={rw}:{rh}:force_original_aspect_ratio=decrease",
        f"pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=1",
    ]
    if subtitles_path:
        esc = (
            subtitles_path
            .replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        )
        vf_parts.append(
            f"subtitles='{esc}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF&,"
            "OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,MarginV=60'"
        )
    vf = ",".join(vf_parts)

    cmd += [
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-r", str(framerate),
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        "-shortest",
    ]
    if is_image:
        # 정지 이미지에서 키프레임 간격을 늘려 파일 크기를 줄인다.
        cmd += ["-tune", "stillimage", "-g", str(max(framerate * 10, 50))]

    if fade_seconds > 0 and audio_duration and audio_duration > fade_seconds * 2:
        fade_out_start = max(audio_duration - fade_seconds, 0)
        cmd += [
            "-af",
            f"afade=t=in:st=0:d={fade_seconds},"
            f"afade=t=out:st={fade_out_start}:d={fade_seconds}",
        ]
    cmd.append(output_path)
    return cmd


def encode_music_video(
    audio_path: str,
    visual_path: str,
    output_path: str,
    *,
    is_image: bool,
    resolution: str = "1920x1080",
    audio_bitrate: str = "192k",
    crf: int = 22,
    fade_seconds: float = 0.0,
    audio_duration: float | None = None,
    subtitles_path: str | None = None,
    audio_loop_count: int = 1,
    preset: str = "medium",
    framerate: int = 24,
) -> tuple[bool, str]:
    """ffmpeg 동기 실행. (성공여부, 로그) 반환."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다. 시스템에 ffmpeg 를 설치해주세요."
    try:
        cmd = _build_encode_cmd(
            audio_path, visual_path, output_path,
            is_image=is_image, resolution=resolution,
            audio_bitrate=audio_bitrate, crf=crf,
            fade_seconds=fade_seconds, audio_duration=audio_duration,
            subtitles_path=subtitles_path, audio_loop_count=audio_loop_count,
            preset=preset, framerate=framerate,
        )
    except ValueError as e:
        return False, str(e)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60 * 60 * 8,
        )
    except subprocess.TimeoutExpired:
        return False, "인코딩이 8시간 안에 끝나지 않았습니다."
    except FileNotFoundError as e:
        return False, f"ffmpeg 실행 실패 (FileNotFoundError): {e}"
    except Exception as e:
        return False, f"인코딩 중 예외: {type(e).__name__}: {e}"
    return proc.returncode == 0, _format_ffmpeg_log(cmd, proc)


def _fmt_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "??"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _fmt_chapter_time(seconds: float) -> str:
    """유튜브 챕터 마커 표기 — H:MM:SS / M:SS."""
    s = int(round(max(0.0, seconds)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _clean_track_label(filename: str) -> str:
    name = os.path.splitext(os.path.basename(filename))[0]
    return name.replace("_", " ").replace("-", " ").strip()


def build_tracklist_text(
    track_metas: list[dict],
    *,
    loop_count: int = 1,
    mode: str = "sequential",
    full_expand: bool = False,
    header: str = "🎵 트랙리스트",
) -> str:
    """유튜브 설명란용 트랙리스트 텍스트.

    - single_loop : 1트랙 + 반복 안내
    - sequential  : 누적 시간으로 N곡 나열
    - bundle_loop : 첫 사이클만(기본) 또는 모든 사이클 확장
    """
    if not track_metas:
        return ""
    lines: list[str] = [header]
    if mode == "single_loop":
        m = track_metas[0]
        lines.append(f"{_fmt_chapter_time(0)} - {_clean_track_label(m['name'])}")
        if loop_count > 1:
            lines.append("")
            lines.append(f"(총 {loop_count}회 반복 · 한 곡 {_fmt_duration(m['duration'])})")
        return "\n".join(lines)

    cycle_duration = sum(m["duration"] for m in track_metas)
    cycles = loop_count if (mode == "bundle_loop" and full_expand) else 1
    for c in range(cycles):
        if cycles > 1:
            lines.append("")
            lines.append(f"── 사이클 {c + 1} ──")
        t = c * cycle_duration
        for m in track_metas:
            lines.append(f"{_fmt_chapter_time(t)} - {_clean_track_label(m['name'])}")
            t += m["duration"]
    if mode == "bundle_loop" and not full_expand and loop_count > 1:
        lines.append("")
        lines.append(
            f"(위 {len(track_metas)}곡 묶음을 총 {loop_count}회 반복 · "
            f"한 사이클 {_fmt_duration(cycle_duration)})"
        )
    return "\n".join(lines)


def _pick_target_duration_ui(key_prefix: str, *, cycle_seconds: float | None = None) -> int:
    """공통 '목표 길이' 위젯. (목표 시간(초)) 을 반환.

    빠른 프리셋 칩 + 시간/분 입력 두 칸. cycle_seconds 가 주어지면 반복 회수 미리보기.
    """
    preset_minutes = {
        "15분": 15, "30분": 30, "1시간": 60, "2시간": 120,
        "3시간": 180, "4시간": 240, "8시간": 480, "10시간": 600,
    }
    st.caption("⚡ 빠른 선택")
    cols = st.columns(len(preset_minutes))
    for (label, mins), col in zip(preset_minutes.items(), cols):
        if col.button(label, key=f"{key_prefix}_chip_{label}", use_container_width=True):
            st.session_state[f"{key_prefix}_hours"] = mins // 60
            st.session_state[f"{key_prefix}_minutes"] = mins % 60
            st.rerun()

    t1, t2, t3 = st.columns([1, 1, 2])
    hours_part = t1.number_input(
        "시간", min_value=0, max_value=24, value=1, step=1, key=f"{key_prefix}_hours"
    )
    minutes_part = t2.number_input(
        "분", min_value=0, max_value=59, value=0, step=1, key=f"{key_prefix}_minutes"
    )
    target_seconds = int(hours_part) * 3600 + int(minutes_part) * 60
    if target_seconds <= 0:
        t3.warning("시간 또는 분 중 하나는 0보다 커야 합니다.")
    else:
        info = f"목표 = **{_fmt_duration(target_seconds)}** ({hours_part}시간 {minutes_part}분)"
        if cycle_seconds and cycle_seconds > 0:
            loops = max(1, int(round(target_seconds / cycle_seconds)))
            info += f" · 한 사이클 {_fmt_duration(cycle_seconds)} × **{loops}회 반복**"
        t3.caption(info)
    return target_seconds


def _render_compose_audio_only() -> None:
    """🎵 음악만 — 곡들 이어붙여 목표 시간으로 만드는 워크플로."""
    st.markdown("### 🎵 음악만 — 목표 시간으로 길게 만들기")

    audio_files = st.file_uploader(
        "🎵 음악 파일 (여러 개 — 업로드 순서대로 이어붙임)",
        type=list(AUDIO_EXTS),
        accept_multiple_files=True,
        key="compose_audio_only_files",
    )
    audio_files = audio_files or []

    track_metas: list[dict] = []
    cycle_duration = 0.0
    if audio_files:
        st.markdown("##### 📋 업로드된 트랙")
        probe_dir = tempfile.mkdtemp(prefix="ytmusic_aoprobe_")
        try:
            for idx, f in enumerate(audio_files, 1):
                pth = os.path.join(probe_dir, f.name)
                with open(pth, "wb") as fp:
                    fp.write(f.getbuffer())
                dur = _ffprobe_duration(pth) or 0.0
                cycle_duration += dur
                track_metas.append({"name": f.name, "duration": dur, "index": idx})
            st.dataframe(
                pd.DataFrame(
                    [{"#": m["index"], "파일": m["name"], "길이": _fmt_duration(m["duration"])}
                     for m in track_metas]
                ),
                hide_index=True, use_container_width=True,
            )
            st.caption(
                f"한 사이클 길이: **{_fmt_duration(cycle_duration)}**  ·  {len(audio_files)}곡"
            )
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)

    st.markdown("##### ⏱️ 목표 길이")
    target_seconds = _pick_target_duration_ui(
        "compose_audio_only", cycle_seconds=cycle_duration if cycle_duration > 0 else None,
    )

    st.markdown("##### ⚙️ 인코딩 옵션")
    o1, o2 = st.columns(2)
    with o1:
        out_format = st.selectbox(
            "출력 포맷",
            options=["mp3", "m4a"],
            index=0,
            key="compose_audio_only_format",
            help="유튜브 업로드 용도라면 m4a(aac) 가 약간 효율적, 범용성은 mp3.",
        )
    with o2:
        bitrate = st.selectbox(
            "비트레이트",
            options=["128k", "192k", "256k", "320k"],
            index=2,
            key="compose_audio_only_bitrate",
        )

    if not audio_files:
        st.info("음악 파일을 1개 이상 업로드해주세요.")
        return
    if target_seconds <= 0:
        return

    if st.button(
        "🚀 음악 잡 제출 (백그라운드)",
        type="primary",
        use_container_width=True,
        key="compose_audio_only_run",
    ):
        _ensure_jobs_dir()
        pre_job_id = uuid.uuid4().hex[:8]
        workdir = _job_workdir(pre_job_id)
        os.makedirs(workdir, exist_ok=True)

        audio_paths: list[str] = []
        for f in audio_files:
            p = os.path.join(workdir, f.name)
            with open(p, "wb") as fp:
                fp.write(f.getbuffer())
            audio_paths.append(p)

        cycle_audio = os.path.join(workdir, "cycle.m4a")
        if len(audio_paths) > 1:
            with st.spinner(f"🎚️ 오디오 {len(audio_paths)}곡 이어붙이는 중..."):
                ok, log = concat_audio_files(audio_paths, cycle_audio, bitrate=bitrate)
            if not ok:
                st.error("오디오 이어붙이기 실패")
                with st.expander("ffmpeg 로그", expanded=True):
                    st.code(log or "(없음)", language=None)
                shutil.rmtree(workdir, ignore_errors=True)
                return
        else:
            cycle_audio = audio_paths[0]

        measured = _ffprobe_duration(cycle_audio) or cycle_duration or 0.0
        loops_estimate = max(1, int(round(target_seconds / measured))) if measured else 1
        output_path = os.path.join(workdir, f"music.{out_format}")
        cmd = _build_audio_only_cmd(
            cycle_audio, output_path,
            target_duration=float(target_seconds),
            bitrate=bitrate,
        )

        tracklist_text = build_tracklist_text(
            track_metas, loop_count=1, mode="sequential",
        )
        job_title = (
            f"🎵 음악만 · {len(audio_files)}곡 · 목표 {_fmt_duration(target_seconds)} "
            f"· {out_format.upper()} {bitrate}"
        )
        try:
            job_id = submit_ffmpeg_job(
                cmd,
                kind="compose_audio",
                title=job_title,
                output_path=output_path,
                workdir=workdir,
                extra={
                    "duration": target_seconds,
                    "resolution": f"{out_format.upper()} {bitrate}",
                    "loop_count": loops_estimate,
                    "track_count": len(audio_files),
                    "mode": "audio_only",
                    "tracklist": tracklist_text,
                },
            )
        except RuntimeError as e:
            st.error(str(e))
            shutil.rmtree(workdir, ignore_errors=True)
            return

        st.session_state["compose_last_job_id"] = job_id
        st.success(
            f"✅ 잡 `{job_id}` 제출됨 — 예상 길이 {_fmt_duration(target_seconds)}.  \n"
            f"📦 **인코딩 잡** 탭에서 진행 상황을 확인하세요."
        )


def _render_compose_visual_only() -> None:
    """🖼️ 영상만 (무음) — 이미지/영상으로 슬라이드쇼 만들기."""
    st.markdown("### 🖼️ 영상만 (무음) — 슬라이드쇼/영상 길게 만들기")

    visual_uploaded = st.file_uploader(
        "🖼️ 배경 — 영상 1개 / 이미지 1장 / 이미지 여러 장(슬라이드쇼)",
        type=list(VIDEO_IMAGE_EXTS),
        accept_multiple_files=True,
        key="compose_visual_only_files",
        help="이미지를 여러 장 드래그하면 슬라이드쇼로 합성합니다.",
    )
    visual_files: list = list(visual_uploaded or [])

    def _is_image_name(n: str) -> bool:
        return n.lower().endswith(IMAGE_EXTS)

    is_slideshow = len(visual_files) > 1 and all(_is_image_name(f.name) for f in visual_files)
    if len(visual_files) > 1 and not is_slideshow:
        st.warning(
            f"⚠️ 영상과 이미지가 섞여 있어 첫 파일(`{visual_files[0].name}`)만 사용합니다."
        )
        visual_files = visual_files[:1]
        is_slideshow = False

    # 슬라이드 시간 설정
    per_image_durations: list[float] = []
    seconds_per_image = 5.0
    if is_slideshow:
        st.markdown(f"##### 🖼️ 슬라이드쇼 — 이미지 {len(visual_files)}장")
        per_image_mode = st.radio(
            "이미지별 표시 시간",
            options=["uniform", "individual"],
            format_func=lambda k: {
                "uniform": "🟰 모두 같은 시간 (한 값으로 적용)",
                "individual": "🎚️ 이미지별로 다른 시간 (개별 지정)",
            }[k],
            horizontal=True,
            key="compose_vo_per_image_mode",
        )
        if per_image_mode == "uniform":
            seconds_per_image = st.number_input(
                "각 이미지당 표시 시간 (초)",
                min_value=0.5, max_value=600.0, value=5.0, step=0.5,
                key="compose_vo_seconds",
            )
            per_image_durations = [seconds_per_image] * len(visual_files)
        else:
            st.caption("각 이미지마다 표시 시간을 따로 지정하세요 (초).")
            ind_cols = st.columns(min(4, len(visual_files)))
            for i, vf in enumerate(visual_files):
                with ind_cols[i % len(ind_cols)]:
                    d = st.number_input(
                        f"{i + 1}. {vf.name[:18]}",
                        min_value=0.5, max_value=3600.0, value=5.0, step=0.5,
                        key=f"compose_vo_dur_{i}",
                    )
                    per_image_durations.append(float(d))
        cycle_visual = sum(per_image_durations) if per_image_durations else 0
        st.caption(
            f"슬라이드쇼 한 사이클: ≈ **{_fmt_duration(cycle_visual)}** "
            f"({len(visual_files)}장)"
        )
    elif visual_files:
        # 단일 영상 또는 단일 이미지
        f = visual_files[0]
        if _is_image_name(f.name):
            st.caption(f"📷 정지 이미지: `{f.name}` — 목표 시간만큼 그대로 유지합니다.")
        else:
            st.caption(f"🎬 영상: `{f.name}` — 목표 시간만큼 자동 루프합니다.")

    st.markdown("##### ⏱️ 목표 길이")
    target_seconds = _pick_target_duration_ui("compose_visual_only")

    st.markdown("##### ⚙️ 인코딩 옵션")
    speed_label_to_key = {v["label"]: k for k, v in SPEED_PRESETS.items()}
    sp_col, _ = st.columns([2, 3])
    with sp_col:
        speed_label = st.radio(
            "인코딩 속도 ↔ 화질",
            options=list(speed_label_to_key.keys()),
            index=0,
            key="compose_vo_speed",
        )
    speed_key = speed_label_to_key[speed_label]
    speed_cfg = SPEED_PRESETS[speed_key]

    o1, o2 = st.columns(2)
    with o1:
        resolution = st.selectbox(
            "해상도",
            options=["1920x1080", "1280x720", "3840x2160", "2560x1440"],
            index=0,
            key="compose_vo_resolution",
        )
    with o2:
        crf = st.slider(
            "비디오 품질 (CRF)",
            min_value=18, max_value=30, value=22, step=1,
            key="compose_vo_crf",
        )

    if not visual_files:
        st.info("영상 또는 이미지를 업로드해주세요.")
        return
    if target_seconds <= 0:
        return

    if st.button(
        "🚀 무음 영상 잡 제출 (백그라운드)",
        type="primary",
        use_container_width=True,
        key="compose_visual_only_run",
    ):
        _ensure_jobs_dir()
        pre_job_id = uuid.uuid4().hex[:8]
        workdir = _job_workdir(pre_job_id)
        os.makedirs(workdir, exist_ok=True)

        if is_slideshow:
            image_paths: list[str] = []
            for vf in visual_files:
                p = os.path.join(workdir, vf.name)
                with open(p, "wb") as fp:
                    fp.write(vf.getbuffer())
                image_paths.append(p)
            slideshow_path = os.path.join(workdir, "slideshow.mp4")
            with st.spinner(
                f"🖼️ 슬라이드쇼 합성 중 — {len(image_paths)}장 (개별 시간 적용)"
            ):
                ok_s, log_s = build_slideshow_from_images(
                    image_paths, slideshow_path,
                    seconds_per_image=(
                        per_image_durations if per_image_durations
                        else seconds_per_image
                    ),
                    resolution=resolution,
                    preset=speed_cfg["preset"],
                )
            if not ok_s or not os.path.exists(slideshow_path):
                st.error("슬라이드쇼 합성 실패")
                with st.expander("ffmpeg 로그", expanded=True):
                    st.code(log_s or "(로그 없음)", language=None)
                shutil.rmtree(workdir, ignore_errors=True)
                return
            cycle_visual = slideshow_path
            is_image = False
        else:
            f = visual_files[0]
            cycle_visual = os.path.join(workdir, f.name)
            with open(cycle_visual, "wb") as fp:
                fp.write(f.getbuffer())
            is_image = _is_image_name(f.name)

        framerate = speed_cfg["fps_static"] if is_image else speed_cfg["fps_video"]
        output_path = os.path.join(workdir, "visual.mp4")
        try:
            cmd = _build_visual_only_cmd(
                cycle_visual, output_path,
                target_duration=float(target_seconds),
                is_image=is_image,
                resolution=resolution,
                preset=speed_cfg["preset"],
                framerate=framerate,
                crf=int(crf),
            )
        except ValueError as e:
            st.error(str(e))
            shutil.rmtree(workdir, ignore_errors=True)
            return

        job_title = (
            f"🖼️ 영상만 · {len(visual_files)}개 입력 · 목표 {_fmt_duration(target_seconds)} "
            f"· {resolution} · {speed_cfg['label']}"
        )
        try:
            job_id = submit_ffmpeg_job(
                cmd,
                kind="compose_visual",
                title=job_title,
                output_path=output_path,
                workdir=workdir,
                extra={
                    "duration": target_seconds,
                    "resolution": resolution,
                    "loop_count": 1,
                    "track_count": len(visual_files),
                    "mode": "visual_only",
                    "tracklist": "",
                    "speed_preset": speed_key,
                },
            )
        except RuntimeError as e:
            st.error(str(e))
            shutil.rmtree(workdir, ignore_errors=True)
            return

        st.session_state["compose_last_job_id"] = job_id
        st.success(
            f"✅ 잡 `{job_id}` 제출됨 — 예상 길이 {_fmt_duration(target_seconds)}.  \n"
            f"📦 **인코딩 잡** 탭에서 진행 상황을 확인하세요."
        )


def render_compose_tab() -> None:
    st.subheader("🎬 영상 합성 (인코딩)")
    st.caption(
        "음악·영상·이미지를 자유롭게 조합해 원하는 길이로 인코딩합니다. "
        "모든 인코딩은 백그라운드 잡으로 실행되어 다른 탭에서 작업해도 끊기지 않습니다."
    )

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        st.error(
            "⚠️ 시스템에 **ffmpeg** 가 설치되어 있지 않습니다. "
            "설치 후 페이지를 새로고침해주세요."
        )
        with st.expander("ffmpeg 설치 가이드"):
            st.code(
                "# macOS (Homebrew)\nbrew install ffmpeg\n\n"
                "# Ubuntu / Debian\nsudo apt-get install -y ffmpeg\n\n"
                "# Windows (winget)\nwinget install --id=Gyan.FFmpeg -e\n\n"
                "# Windows (Scoop)\nscoop install ffmpeg",
                language="bash",
            )
        return
    st.caption(f"✓ ffmpeg 감지됨: `{ffmpeg}`")

    # ---- 출력 종류 (최상단) ----
    output_type = st.radio(
        "📦 출력 종류",
        options=["av", "audio", "visual"],
        format_func=lambda k: {
            "av":     "🎬 음악 + 영상 (MP4) — 곡들 + 배경을 합쳐 긴 뮤직비디오",
            "audio":  "🎵 음악만 (MP3/M4A) — 곡들 이어붙이고 N시간 길이로",
            "visual": "🖼️ 영상만 (MP4, 무음) — 이미지/영상으로 슬라이드쇼 N시간",
        }[k],
        index=0,
        key="compose_output_type",
        help="음악만 / 영상만 출력도 가능합니다.",
    )

    if output_type == "audio":
        _render_compose_audio_only()
        return
    if output_type == "visual":
        _render_compose_visual_only()
        return

    # ---- 합성 모드 ----
    mode_labels = {
        "single_loop": "🎵 단일 곡 반복 — 한 곡을 N번 반복해 긴 영상으로",
        "sequential":  "🔗 여러 곡 순차 이어붙이기 — 각 곡을 한 번씩",
        "bundle_loop": "🔁 묶음 반복 — 여러 곡을 한 사이클로 묶어 N번 반복",
    }
    mode = st.radio(
        "합성 모드",
        options=list(mode_labels.keys()),
        format_func=lambda k: mode_labels[k],
        index=1,
        key="compose_mode",
    )

    multi_allowed = mode in ("sequential", "bundle_loop")
    uploaded = st.file_uploader(
        ("🎵 음악 파일 (여러 개 — 업로드 순서대로 이어붙임)"
         if multi_allowed else "🎵 음악 파일 (1개)"),
        type=list(AUDIO_EXTS),
        accept_multiple_files=multi_allowed,
        key=f"compose_audio_{mode}",
    )
    if uploaded is None:
        audio_files: list = []
    elif isinstance(uploaded, list):
        audio_files = uploaded
    else:
        audio_files = [uploaded]

    visual_uploaded = st.file_uploader(
        "🖼️ 배경 — 영상 1개 / 이미지 1장 / 이미지 여러 장(슬라이드쇼)",
        type=list(VIDEO_IMAGE_EXTS),
        accept_multiple_files=True,
        key="compose_visuals_multi",
        help="이미지를 여러 장 드래그하면 슬라이드쇼 영상으로 자동 합성합니다. "
             "영상이 오디오보다 짧으면 자동 루프됩니다.",
    )
    visual_files: list = list(visual_uploaded or [])

    def _is_image_name(n: str) -> bool:
        return n.lower().endswith(IMAGE_EXTS)

    is_slideshow = len(visual_files) > 1 and all(_is_image_name(f.name) for f in visual_files)
    has_mixed = (
        len(visual_files) > 1
        and not is_slideshow
    )
    if has_mixed:
        st.warning(
            f"⚠️ 영상과 이미지가 섞여 있어 첫 번째 파일(`{visual_files[0].name}`)만 사용합니다. "
            "슬라이드쇼는 **이미지만 여러 장** 업로드했을 때 자동으로 만들어집니다."
        )
        visual_files = visual_files[:1]
        is_slideshow = False

    seconds_per_image = 5.0
    slide_auto = False
    if is_slideshow:
        st.markdown(f"##### 🖼️ 슬라이드쇼 — 이미지 {len(visual_files)}장 감지")
        slide_c1, slide_c2 = st.columns([1, 2])
        with slide_c1:
            slide_auto = st.checkbox(
                "오디오 길이에 맞춰 자동 분배",
                value=False,
                key="compose_slide_auto",
                help="체크 시 (최종 영상 길이 ÷ 이미지 수) 로 각 이미지 표시 시간을 계산.",
            )
        with slide_c2:
            if slide_auto:
                st.caption(
                    "자동 분배 모드 — 인코딩 시점에 (최종 영상 길이 ÷ 이미지 수) 로 결정됩니다."
                )
            else:
                seconds_per_image = st.number_input(
                    "각 이미지당 표시 시간 (초)",
                    min_value=0.5, max_value=600.0, value=5.0, step=0.5,
                    key="compose_slide_seconds",
                    help="총 슬라이드쇼 길이가 오디오보다 짧으면 자동으로 반복됩니다.",
                )
        total_slide = seconds_per_image * len(visual_files) if not slide_auto else None
        if total_slide:
            st.caption(
                f"슬라이드쇼 한 사이클: ≈ **{_fmt_duration(total_slide)}** "
                f"({len(visual_files)}장 × {seconds_per_image:.1f}초)"
            )

    visual_file = visual_files[0] if visual_files else None

    # ---- 곡 메타 (길이) 미리보기 ----
    track_metas: list[dict] = []
    cycle_duration = 0.0
    if audio_files:
        st.markdown("##### 📋 업로드된 트랙")
        probe_dir = tempfile.mkdtemp(prefix="ytmusic_probe_")
        try:
            for idx, f in enumerate(audio_files, 1):
                pth = os.path.join(probe_dir, f.name)
                with open(pth, "wb") as fp:
                    fp.write(f.getbuffer())
                dur = _ffprobe_duration(pth) or 0.0
                cycle_duration += dur
                track_metas.append({"name": f.name, "duration": dur, "index": idx})
            st.dataframe(
                pd.DataFrame(
                    [
                        {"#": m["index"], "파일": m["name"], "길이": _fmt_duration(m["duration"])}
                        for m in track_metas
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                f"한 사이클 길이: **{_fmt_duration(cycle_duration)}**  ·  {len(audio_files)}곡"
            )
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)

    # ---- 반복 / 목표 시간 ----
    loop_count = 1
    if mode in ("single_loop", "bundle_loop") and cycle_duration > 0:
        st.markdown("##### 🔁 반복 / 목표 길이")
        method = st.radio(
            "지정 방식",
            options=["target", "count"],
            format_func=lambda k: {
                "target": "🎯 목표 영상 시간으로 지정 (반복 회수 자동 계산)",
                "count":  "🔢 반복 회수로 직접 지정",
            }[k],
            horizontal=True,
            key="compose_loop_method",
        )
        if method == "target":
            # 빠른 프리셋 버튼 — 한 번에 흔히 쓰는 길이 선택.
            preset_minutes = {
                "15분": 15, "30분": 30, "1시간": 60, "2시간": 120,
                "3시간": 180, "4시간": 240, "8시간": 480, "10시간": 600,
            }
            st.caption("⚡ 빠른 선택")
            preset_cols = st.columns(len(preset_minutes))
            for (label, mins), col in zip(preset_minutes.items(), preset_cols):
                if col.button(label, key=f"compose_target_preset_{label}", use_container_width=True):
                    st.session_state["compose_target_hours_int"] = mins // 60
                    st.session_state["compose_target_minutes_int"] = mins % 60
                    st.rerun()

            time_c1, time_c2, time_c3 = st.columns([1, 1, 2])
            with time_c1:
                hours_part = st.number_input(
                    "시간",
                    min_value=0, max_value=24, value=1, step=1,
                    key="compose_target_hours_int",
                )
            with time_c2:
                minutes_part = st.number_input(
                    "분",
                    min_value=0, max_value=59, value=0, step=1,
                    key="compose_target_minutes_int",
                )
            target_seconds = hours_part * 3600 + minutes_part * 60
            if target_seconds <= 0:
                st.warning("목표 시간이 0 입니다. 시간 또는 분 중 하나는 0보다 커야 합니다.")
                target_seconds = max(int(cycle_duration), 60)
            loop_count = max(1, int(round(target_seconds / cycle_duration)))
            with time_c3:
                st.caption(
                    f"목표 = **{_fmt_duration(target_seconds)}** "
                    f"({hours_part}시간 {minutes_part}분)"
                )
        else:
            loop_count = st.slider(
                "반복 회수",
                min_value=1, max_value=500, value=4,
                key="compose_loop_count",
            )
        actual = loop_count * cycle_duration
        st.info(
            f"→ 반복 **{loop_count}회**  ·  최종 영상 길이 ≈ **{_fmt_duration(actual)}**  ·  "
            f"한 사이클 {_fmt_duration(cycle_duration)}"
        )
    elif mode == "sequential":
        st.caption("📝 순차 모드 — 반복 없이 곡들이 한 번씩 재생됩니다.")

    # ---- 트랙리스트 미리보기 (설명란 복사용) ----
    if track_metas:
        full_expand = False
        if mode == "bundle_loop" and loop_count > 1:
            full_expand = st.checkbox(
                "모든 사이클의 타임스탬프 펼치기",
                value=False,
                key="compose_full_expand",
                help="체크 시 모든 N×M 타임스탬프 나열. 기본은 첫 사이클만 + 반복 안내.",
            )
        tracklist = build_tracklist_text(
            track_metas, loop_count=loop_count, mode=mode, full_expand=full_expand
        )
        st.markdown("##### 📜 트랙리스트 (유튜브 설명란 복사용)")
        st.code(tracklist, language="text")
        st.caption(
            "위 박스 오른쪽 위 📋 아이콘으로 클립보드 복사. "
            "유튜브 설명란에 그대로 붙여넣으면 첫 사이클 타임스탬프가 챕터 마커로 인식됩니다."
        )

    # ---- 인코딩 옵션 ----
    st.markdown("##### ⚙️ 인코딩 옵션")
    speed_label_to_key = {v["label"]: k for k, v in SPEED_PRESETS.items()}
    sp_col, _ = st.columns([2, 3])
    with sp_col:
        speed_label = st.radio(
            "인코딩 속도 ↔ 화질",
            options=list(speed_label_to_key.keys()),
            index=0,
            key="compose_speed_preset",
            horizontal=False,
            help=(
                "정지 이미지나 슬라이드쇼는 화면이 거의 안 바뀌니 '빠른' 모드여도 "
                "유튜브 시청 화질에는 영향이 거의 없습니다. 영상 배경(움직임 있음)일 땐 '균형' 권장."
            ),
        )
    speed_key = speed_label_to_key[speed_label]
    speed_cfg = SPEED_PRESETS[speed_key]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        resolution = st.selectbox(
            "해상도",
            options=["1920x1080", "1280x720", "3840x2160", "2560x1440"],
            index=0,
            key="compose_resolution",
        )
    with col2:
        audio_bitrate = st.selectbox(
            "오디오 비트레이트",
            options=["128k", "192k", "256k", "320k"],
            index=1,
            key="compose_audio_bitrate",
        )
    with col3:
        crf = st.slider(
            "비디오 품질 (CRF)",
            min_value=18, max_value=30, value=22, step=1,
            key="compose_crf",
            help="낮을수록 고화질·큰 파일. 18=시각적 무손실, 22=권장, 28=용량 우선.",
        )
    with col4:
        fade = st.number_input(
            "페이드 인/아웃 (초)",
            min_value=0.0, max_value=10.0, value=0.0, step=0.5,
            key="compose_fade",
        )

    run = st.button(
        "🚀 인코딩 잡 제출 (백그라운드 실행)",
        type="primary",
        use_container_width=True,
        key="compose_run",
        help="제출 후에는 📦 인코딩 잡 탭에서 진행 상황을 확인할 수 있습니다. "
             "브라우저를 닫거나 다른 탭에서 작업해도 인코딩은 계속됩니다.",
    )

    if not run:
        if st.session_state.get("compose_last_job_id"):
            jid = st.session_state["compose_last_job_id"]
            st.info(
                f"🔄 마지막으로 제출한 잡 `{jid}` 은(는) **📦 인코딩 잡** 탭에서 확인하세요."
            )
        return

    if not audio_files or not visual_files:
        st.error("음악(1개 이상)과 배경 파일(영상 1개 또는 이미지 1~여러 장)을 모두 업로드해주세요.")
        return

    # 잡 전용 영구 워크디렉터리 — 임시폴더 자동 정리에 안 영향받게.
    _ensure_jobs_dir()
    pre_job_id = uuid.uuid4().hex[:8]  # 잡 id 미리 잡아 워크디렉터리 명명에 사용
    workdir = _job_workdir(pre_job_id)
    os.makedirs(workdir, exist_ok=True)

    audio_paths: list[str] = []
    for f in audio_files:
        p = os.path.join(workdir, f.name)
        with open(p, "wb") as fp:
            fp.write(f.getbuffer())
        audio_paths.append(p)

    is_image = False
    if is_slideshow:
        slide_image_paths: list[str] = []
        for vf in visual_files:
            p = os.path.join(workdir, vf.name)
            with open(p, "wb") as fp:
                fp.write(vf.getbuffer())
            slide_image_paths.append(p)
        visual_path = ""
    else:
        visual_path = os.path.join(workdir, visual_file.name)
        with open(visual_path, "wb") as fp:
            fp.write(visual_file.getbuffer())
        is_image = visual_file.name.lower().endswith(IMAGE_EXTS)

    # 1) 한 사이클 합본 — sync (보통 분 단위 이내).
    cycle_audio = os.path.join(workdir, "cycle.m4a")
    if len(audio_paths) > 1:
        with st.spinner(f"🎚️ 오디오 {len(audio_paths)}곡 이어붙이는 중..."):
            ok, log = concat_audio_files(audio_paths, cycle_audio, bitrate=audio_bitrate)
        if not ok:
            st.error("오디오 이어붙이기 실패")
            with st.expander("ffmpeg 로그", expanded=True):
                st.code(log or "(없음)", language=None)
            shutil.rmtree(workdir, ignore_errors=True)
            return
    else:
        cycle_audio = audio_paths[0]

    measured_cycle = _ffprobe_duration(cycle_audio) or cycle_duration or 0.0
    total_duration = measured_cycle * loop_count

    # 1.5) 슬라이드쇼 — sync (이미지 수가 적으면 빠름).
    if is_slideshow:
        if slide_auto and total_duration > 0:
            spi = max(0.5, total_duration / len(slide_image_paths))
        else:
            spi = float(seconds_per_image)
        slideshow_path = os.path.join(workdir, "slideshow.mp4")
        with st.spinner(
            f"🖼️ 슬라이드쇼 합성 중 — {len(slide_image_paths)}장 × {spi:.1f}초"
        ):
            ok_s, log_s = build_slideshow_from_images(
                slide_image_paths, slideshow_path,
                seconds_per_image=spi,
                resolution=resolution,
                preset=speed_cfg["preset"],
            )
        if not ok_s or not os.path.exists(slideshow_path):
            st.error("슬라이드쇼 영상 합성에 실패했습니다.")
            with st.expander("ffmpeg 로그", expanded=True):
                st.code(log_s or "(로그 없음)", language=None)
            shutil.rmtree(workdir, ignore_errors=True)
            return
        visual_path = slideshow_path
        is_image = False

    # 2) 메인 인코딩 — 백그라운드 잡 제출.
    output_path = os.path.join(workdir, "output.mp4")
    framerate = speed_cfg["fps_static"] if is_image else speed_cfg["fps_video"]
    try:
        encode_cmd = _build_encode_cmd(
            cycle_audio, visual_path, output_path,
            is_image=is_image,
            resolution=resolution,
            audio_bitrate=audio_bitrate,
            crf=int(crf),
            fade_seconds=float(fade),
            audio_duration=total_duration,
            subtitles_path=None,
            audio_loop_count=loop_count,
            preset=speed_cfg["preset"],
            framerate=framerate,
        )
    except ValueError as e:
        st.error(f"인코딩 명령 생성 실패: {e}")
        shutil.rmtree(workdir, ignore_errors=True)
        return

    tracklist_text = build_tracklist_text(
        track_metas,
        loop_count=loop_count,
        mode=mode,
        full_expand=st.session_state.get("compose_full_expand", False),
    )

    job_title = (
        f"{len(audio_files)}곡 × {loop_count}회 · "
        f"{_fmt_duration(total_duration)} · {resolution} · {speed_cfg['label']}"
    )
    try:
        job_id = submit_ffmpeg_job(
            encode_cmd,
            kind="compose",
            title=job_title,
            output_path=output_path,
            workdir=workdir,
            extra={
                "duration": total_duration,
                "resolution": resolution,
                "loop_count": loop_count,
                "track_count": len(audio_files),
                "mode": mode,
                "tracklist": tracklist_text,
                "speed_preset": speed_key,
            },
        )
    except RuntimeError as e:
        st.error(str(e))
        shutil.rmtree(workdir, ignore_errors=True)
        return

    st.session_state["compose_last_job_id"] = job_id
    st.success(
        f"✅ 잡 `{job_id}` 제출됨 — 예상 길이 {_fmt_duration(total_duration)}.  \n"
        f"📦 **인코딩 잡** 탭에서 진행 상황을 확인하세요. "
        f"브라우저를 닫거나 다른 탭에서 작업해도 인코딩은 계속됩니다."
    )


def _render_compose_result() -> None:
    info = st.session_state.get("compose_output")
    if not info:
        return
    path = info["path"]
    if not os.path.exists(path):
        st.warning("이전 결과 파일이 더 이상 존재하지 않습니다 (임시 디렉터리 정리됨).")
        st.session_state.pop("compose_output", None)
        return

    meta_cols = st.columns(4)
    meta_cols[0].metric("파일 크기", f"{info['size_mb']} MB")
    meta_cols[1].metric("해상도", info["resolution"])
    meta_cols[2].metric("최종 길이", _fmt_duration(info.get("duration") or 0))
    meta_cols[3].metric("반복 회수", f"{info.get('loop_count', 1)}회")

    if info["size_mb"] <= 500:
        try:
            st.video(path)
        except Exception:
            st.caption("미리보기를 표시할 수 없습니다. 다운로드해서 확인해주세요.")
    else:
        st.caption("📦 파일이 커서 인라인 미리보기는 생략합니다. 다운로드해서 확인해주세요.")

    with open(path, "rb") as fp:
        st.download_button(
            "📥 MP4 다운로드",
            data=fp.read(),
            file_name=f"music_video_{datetime.now():%Y%m%d_%H%M%S}.mp4",
            mime="video/mp4",
            type="primary",
            use_container_width=True,
            key="compose_download_mp4",
        )

    if info.get("tracklist"):
        st.markdown("##### 📜 트랙리스트 (유튜브 설명란 복사용)")
        st.code(info["tracklist"], language="text")
        st.caption("📋 우측 상단 복사 아이콘으로 클립보드에 복사됩니다.")

    if st.button("🗑️ 결과 비우기 (임시 파일 삭제)", key="compose_cleanup"):
        shutil.rmtree(info["workdir"], ignore_errors=True)
        st.session_state.pop("compose_output", None)
        st.rerun()


# ---------------------------------------------------------------------------
# Jobs tab — 백그라운드 인코딩 잡 대시보드
# ---------------------------------------------------------------------------


def _fmt_eta(current_s: float, total_s: float, elapsed_s: float) -> str:
    if current_s <= 0 or total_s <= 0:
        return "??"
    rate = current_s / elapsed_s if elapsed_s > 0 else 0
    if rate <= 0:
        return "??"
    remaining = (total_s - current_s) / rate
    if remaining < 0:
        remaining = 0
    return _fmt_duration(remaining)


def render_jobs_tab() -> None:
    st.subheader("📦 인코딩 잡 대시보드")
    st.caption(
        "여기서 모든 백그라운드 인코딩 작업을 관리합니다. "
        "브라우저를 닫거나 다른 탭에서 작업해도 진행 중인 잡은 그대로 계속 돌아갑니다."
    )

    top_c1, top_c2, top_c3 = st.columns([1, 1, 4])
    if top_c1.button("🔄 새로 고침", key="jobs_refresh", use_container_width=True):
        st.rerun()
    auto_refresh = top_c2.checkbox(
        "자동 새로고침 (5초)",
        value=False,
        key="jobs_auto_refresh",
        help="진행 중인 잡이 있을 때 5초마다 페이지를 다시 그립니다.",
    )

    jobs = [refresh_job_status(j) for j in list_jobs()]
    running = [j for j in jobs if j.get("status") == "running"]
    finished = [j for j in jobs if j.get("status") != "running"]

    top_c3.markdown(
        f"**진행 중**: {len(running)}개  ·  **완료/실패**: {len(finished)}개"
    )

    if not jobs:
        st.info(
            "아직 제출된 잡이 없습니다. **🎬 영상 합성** 탭에서 인코딩을 시작하면 여기에 표시돼요."
        )
        return

    # 일괄 정리
    with st.expander("🧹 일괄 정리"):
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ 완료된 잡만 삭제 (입력 파일은 보존)", key="jobs_clean_done"):
            for j in finished:
                if j.get("status") == "done":
                    delete_job(j["id"], remove_files=False)
            st.rerun()
        if cc2.button("🗑️ 실패/취소된 잡 + 임시파일 삭제", key="jobs_clean_failed"):
            for j in finished:
                if j.get("status") in ("failed", "cancelled"):
                    delete_job(j["id"], remove_files=True)
            st.rerun()

    for job in jobs:
        _render_job_card(job)

    if auto_refresh and running:
        # Streamlit autorefresh — 5초 후 rerun.
        import time as _time
        _time.sleep(5)
        st.rerun()


def _render_job_card(job: dict) -> None:
    status = job.get("status", "running")
    status_icon = {
        "running": "🔄",
        "done": "✅",
        "failed": "❌",
        "cancelled": "⏹️",
    }.get(status, "•")
    job_id = job.get("id", "????")
    title = job.get("title", "")
    started_at = job.get("started_at", "")

    with st.container(border=True):
        st.markdown(
            f"### {status_icon} `{job_id}` · {status.upper()}"
        )
        st.caption(f"{title}  ·  시작: {started_at}")

        extra = job.get("extra") or {}
        expected_total = float(extra.get("duration") or 0)

        if status == "running":
            # 진행률 표시
            progress_info = parse_job_progress(job.get("progress_path", "")) or {}
            current = float(progress_info.get("current_seconds") or 0)
            try:
                from datetime import datetime as _dt
                started_dt = _dt.fromisoformat(started_at)
                elapsed = (_dt.now() - started_dt).total_seconds()
            except Exception:
                elapsed = 0
            if expected_total > 0 and current > 0:
                pct = min(1.0, current / expected_total)
                st.progress(
                    pct,
                    text=(
                        f"{int(pct * 100)}%  ·  "
                        f"인코딩 {_fmt_duration(current)} / {_fmt_duration(expected_total)}  ·  "
                        f"경과 {_fmt_duration(elapsed)}  ·  남은 시간 ≈ {_fmt_eta(current, expected_total, elapsed)}"
                    ),
                )
            else:
                st.progress(
                    0.0,
                    text=(
                        f"준비 중... (경과 {_fmt_duration(elapsed)})  ·  "
                        f"PID {job.get('pid')}"
                    ),
                )

            cc1, cc2 = st.columns(2)
            if cc1.button("⏹️ 잡 취소", key=f"job_cancel_{job_id}"):
                cancel_job(job_id)
                st.rerun()
            with cc2.expander("최근 로그 보기"):
                log_path = job.get("log_path", "")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, "rb") as fp:
                            fp.seek(0, 2)
                            size = fp.tell()
                            fp.seek(max(0, size - 4000))
                            tail = fp.read().decode("utf-8", errors="replace")
                        st.code(tail or "(아직 출력 없음)", language=None)
                    except OSError:
                        st.caption("로그 파일을 읽을 수 없습니다.")
                else:
                    st.caption("(로그 파일 없음)")

        elif status == "done":
            output_path = job.get("output_path", "")
            if os.path.exists(output_path):
                size_mb = os.path.getsize(output_path) / 1024 / 1024
                m1, m2, m3 = st.columns(3)
                m1.metric("파일 크기", f"{size_mb:.1f} MB")
                m2.metric("최종 길이", _fmt_duration(expected_total))
                m3.metric("해상도", extra.get("resolution", "?"))
                if size_mb <= 500:
                    try:
                        st.video(output_path)
                    except Exception:
                        st.caption("미리보기를 표시할 수 없습니다.")
                else:
                    st.caption("📦 파일이 커서 인라인 미리보기는 생략합니다.")
                with open(output_path, "rb") as fp:
                    st.download_button(
                        "📥 MP4 다운로드",
                        data=fp.read(),
                        file_name=f"music_video_{job_id}.mp4",
                        mime="video/mp4",
                        type="primary",
                        use_container_width=True,
                        key=f"job_download_{job_id}",
                    )
                tracklist = extra.get("tracklist") or ""
                if tracklist:
                    st.markdown("**📜 트랙리스트 (설명란 복사용)**")
                    st.code(tracklist, language="text")
            else:
                st.warning(
                    "결과 파일이 더 이상 존재하지 않습니다 — 임시 폴더가 정리되었을 수 있습니다."
                )

        else:  # failed / cancelled
            log_path = job.get("log_path", "")
            if os.path.exists(log_path):
                with st.expander("ffmpeg 로그 (끝 4KB)", expanded=True):
                    try:
                        with open(log_path, "rb") as fp:
                            fp.seek(0, 2)
                            size = fp.tell()
                            fp.seek(max(0, size - 4000))
                            tail = fp.read().decode("utf-8", errors="replace")
                        st.code(tail or "(로그 없음)", language=None)
                    except OSError:
                        st.caption("로그 파일을 읽을 수 없습니다.")

        # 삭제 (모든 상태에 대해)
        if status != "running":
            del_c1, del_c2 = st.columns([1, 1])
            if del_c1.button("🗑️ 이 잡 + 결과 파일 삭제", key=f"job_del_full_{job_id}"):
                delete_job(job_id, remove_files=True)
                st.rerun()
            if del_c2.button("📋 잡 기록만 삭제 (파일 보존)", key=f"job_del_meta_{job_id}"):
                delete_job(job_id, remove_files=False)
                st.rerun()


# ---------------------------------------------------------------------------
# Lyric auto-sync — Whisper API 로 가사 타임라인 정렬해 SRT 생성
# ---------------------------------------------------------------------------

WHISPER_MAX_BYTES = 25 * 1024 * 1024  # OpenAI Whisper API 업로드 한도


def extract_audio_track(input_path: str, output_path: str) -> tuple[bool, str]:
    """영상에서 오디오만 뽑아 MP3 로 저장."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다."
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-i", input_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", "192k", "-ar", "44100",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return False, "오디오 추출이 15분 안에 끝나지 않았습니다."
    return proc.returncode == 0, (proc.stderr or "")[-2000:]


def compress_audio_for_whisper(input_path: str, output_path: str) -> tuple[bool, str]:
    """Whisper 25MB 한도에 맞도록 모노 64kbps 22kHz MP3 로 다운샘플."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다."
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-i", input_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", "64k",
        "-ac", "1", "-ar", "22050",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return False, "오디오 압축이 15분 안에 끝나지 않았습니다."
    return proc.returncode == 0, (proc.stderr or "")[-2000:]


def _clean_proc_log(text: str, keep: int = 800) -> str:
    """subprocess 로그에서 tqdm 진행바 조각을 제거하고 의미있는 끝부분만 남긴다."""
    if not text:
        return ""
    # 진행바는 \r 로 갱신되므로 \r 기준으로도 쪼갠다.
    parts = re.split(r"[\r\n]+", text)
    meaningful = [
        p.strip() for p in parts
        if p.strip()
        and "%|" not in p
        and "it/s" not in p
        and "seconds/s" not in p
        and not re.match(r"^\d+%", p.strip())
    ]
    out = "\n".join(meaningful).strip()
    return out[-keep:] if out else text[-keep:]


def _find_vocals_stem(outdir: str) -> str | None:
    """demucs 출력 폴더에서 vocals 스템 파일을 찾는다."""
    for root, _dirs, files in os.walk(outdir):
        for name in ("vocals.wav", "vocals.mp3", "vocals.flac"):
            if name in files:
                return os.path.join(root, name)
    return None


def demucs_available() -> bool:
    """Demucs(보컬 분리) 패키지 설치 여부."""
    import importlib.util
    return importlib.util.find_spec("demucs") is not None


def separate_vocals(audio_path: str, outdir: str) -> tuple[str | None, str]:
    """Demucs 로 반주를 제거하고 보컬 스템만 추출한다. (vocals_path|None, log).

    `python -m demucs --two-stems=vocals` 를 호출해 보컬/반주 2-stem 으로 분리하고
    생성된 vocals 파일 경로를 돌려준다. 미설치/실패 시 (None, 정리된 로그).
    """
    if not demucs_available():
        return None, "demucs 미설치"

    # 한글/공백 경로와 torchaudio 의존을 피하려고 ASCII 이름으로 복사 후 처리한다.
    in_ext = os.path.splitext(audio_path)[1].lower() or ".mp3"
    safe_in = os.path.join(
        os.path.dirname(outdir) or tempfile.gettempdir(),
        "demucs_input" + in_ext,
    )
    try:
        shutil.copyfile(audio_path, safe_in)
    except OSError:
        safe_in = audio_path

    # --mp3: wav 저장(torchaudio→torchcodec 의존) 대신 lameenc 로 mp3 저장 → 호환성 ↑
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems=vocals",
        "--mp3", "--mp3-bitrate", "128",
        "-o", outdir,
        safe_in,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return None, "보컬 분리가 30분 안에 끝나지 않았습니다."

    # returncode 와 무관하게 결과 파일이 생겼으면 그대로 사용한다.
    found = _find_vocals_stem(outdir)
    if found:
        return found, "ok"

    log = _clean_proc_log((proc.stderr or "") + "\n" + (proc.stdout or ""))
    if "torchcodec" in log.lower():
        log += (
            "\n\n💡 torchaudio 저장 백엔드 문제입니다. "
            "최신 코드는 mp3 로 저장하도록 우회했으니, 대시보드 실행 .bat 을 다시 "
            "더블클릭해 최신 코드를 받은 뒤 재시도하세요."
        )
    elif "lameenc" in log.lower():
        log += (
            "\n\n💡 mp3 인코더(lameenc)가 없습니다. "
            "'보컬분리_설치.bat' 을 다시 더블클릭하면 함께 설치됩니다."
        )
    return None, log or "분리 결과(vocals)를 찾지 못했습니다."


def whisper_transcribe(
    audio_path: str, api_key: str, language: str | None = None
) -> dict:
    """OpenAI Whisper API 호출. segment + word level 타임스탬프 포함."""
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "`openai` 패키지가 필요합니다. `pip install openai>=1.30.0` 후 재시도하세요."
        ) from e

    client = OpenAI(api_key=api_key)
    kwargs: dict = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment", "word"],
    }
    if language:
        kwargs["language"] = language

    with open(audio_path, "rb") as fp:
        result = client.audio.transcriptions.create(file=fp, **kwargs)

    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(result)


def whisper_transcribe_local(
    audio_path: str,
    *,
    model_size: str = "small",
    language: str | None = None,
    device: str = "auto",
    progress_cb=None,
) -> dict:
    """faster-whisper 로 로컬에서 추론. OpenAI API 와 동일한 dict 형식 반환.

    첫 호출 시 모델을 자동 다운로드(small 462MB, medium 1.5GB, large-v3 3GB).
    같은 모델은 ~/.cache/huggingface 에 캐시돼 이후엔 즉시 로드.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "`faster-whisper` 패키지가 설치되어 있지 않습니다.\n"
            "터미널에서 다음 명령으로 설치 후 다시 시도하세요:\n\n"
            "    pip install faster-whisper\n\n"
            "설치 후 앱을 재시작해주세요."
        ) from e

    # 디바이스/연산 정밀도 자동 선택.
    if device == "auto":
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                device, compute_type = "cuda", "float16"
            else:
                device, compute_type = "cpu", "int8"
        except ImportError:
            device, compute_type = "cpu", "int8"
    else:
        compute_type = "float16" if device == "cuda" else "int8"

    if progress_cb:
        progress_cb(f"모델 로드 중 ({model_size}, {device}/{compute_type})...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    if progress_cb:
        progress_cb("오디오 분석 중 (Whisper 추론)...")
    segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language=language,
        # 음악에서 보컬 구간을 '무음'으로 오판해 잘리지 않도록 VAD 를 완화.
        vad_filter=True,
        vad_parameters=dict(threshold=0.2, min_silence_duration_ms=700),
        beam_size=5,
        # 노래에서 한 번 헷갈리면 반복/붕괴되며 이후 가사를 아예 못 적는 현상을 방지.
        condition_on_previous_text=False,
        # 음악 구간을 무음으로 잘못 버리지 않게 임계값 완화 (곡 끝까지 인식).
        no_speech_threshold=0.85,
        # 반복되는 후렴구 가사도 '환각'으로 오판해 버리지 않게 완화.
        compression_ratio_threshold=2.8,
        log_prob_threshold=-2.0,
    )

    seg_list: list[dict] = []
    word_list: list[dict] = []
    # 제너레이터를 소진하면서 progress 업데이트.
    for seg in segments:
        seg_list.append({
            "id": int(getattr(seg, "id", len(seg_list))),
            "start": float(seg.start),
            "end": float(seg.end),
            "text": (seg.text or "").strip(),
        })
        if seg.words:
            for w in seg.words:
                # 안전 가드 — None 인 경우 스킵.
                if w.start is None or w.end is None:
                    continue
                word_list.append({
                    "word": (w.word or "").strip(),
                    "start": float(w.start),
                    "end": float(w.end),
                })

    return {
        "segments": seg_list,
        "words": word_list,
        "language": getattr(info, "language", language),
        "duration": float(getattr(info, "duration", 0) or 0),
    }


def whisper_segments_to_srt(segments: list[dict]) -> str:
    """Whisper segments → SRT 그대로 변환 (가사 미입력 모드)."""
    out: list[str] = []
    counter = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0) or 0)
        end = float(seg.get("end", start) or start)
        if end <= start:
            end = start + 0.5
        out.append(str(counter))
        out.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
        out.append(text)
        out.append("")
        counter += 1
    return "\n".join(out).strip() + "\n"


def align_lyrics_to_segments(
    lyrics_lines: list[str],
    segments: list[dict],
    total_duration: float | None = None,
) -> str:
    """
    사용자가 직접 쓴 가사 라인들을 Whisper 가 잡은 구간 타임스탬프에 정렬한다.

    - 라인 수와 구간 수가 같으면 1:1 매핑
    - 라인이 더 적으면 인접한 구간들을 묶어서 매핑
    - 라인이 더 많으면 한 구간을 길이로 비례 분할해 여러 라인에 분배
    """
    lines = [ln.strip() for ln in lyrics_lines if ln.strip()]
    if not lines or not segments:
        return whisper_segments_to_srt(segments)

    L = len(lines)
    N = len(segments)
    out: list[str] = []
    counter = 1

    if L == N:
        for line, seg in zip(lines, segments):
            start = float(seg.get("start", 0) or 0)
            end = float(seg.get("end", start) or start)
            if end <= start:
                end = start + 0.5
            out.append(str(counter))
            out.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
            out.append(line)
            out.append("")
            counter += 1
    elif L < N:
        # 라인 1개당 N/L 개의 구간을 그룹화.
        step = N / L
        for i, line in enumerate(lines):
            s_idx = int(round(i * step))
            e_idx = int(round((i + 1) * step)) - 1
            e_idx = min(max(e_idx, s_idx), N - 1)
            start = float(segments[s_idx].get("start", 0) or 0)
            end = float(segments[e_idx].get("end", start) or start)
            if end <= start:
                end = start + 0.5
            out.append(str(counter))
            out.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
            out.append(line)
            out.append("")
            counter += 1
    else:  # L > N — 한 구간을 여러 라인으로 쪼갬
        line_cursor = 0
        for seg_idx, seg in enumerate(segments):
            seg_start = float(seg.get("start", 0) or 0)
            seg_end = float(seg.get("end", seg_start) or seg_start)
            if seg_end <= seg_start:
                seg_end = seg_start + 0.5

            # 이 구간이 흡수해야 할 라인 개수.
            target = int(round((seg_idx + 1) * L / N)) - int(round(seg_idx * L / N))
            target = max(1, target)
            sub_lines = lines[line_cursor : line_cursor + target]
            line_cursor += target
            if not sub_lines:
                continue
            sub_dur = (seg_end - seg_start) / len(sub_lines)
            for j, line in enumerate(sub_lines):
                s = seg_start + j * sub_dur
                e = seg_start + (j + 1) * sub_dur
                out.append(str(counter))
                out.append(f"{_format_srt_time(s)} --> {_format_srt_time(e)}")
                out.append(line)
                out.append("")
                counter += 1
        # 남은 라인이 있으면 마지막 구간 끝 ~ 곡 끝까지 고르게 분배 (끝부분 가사 누락 방지).
        if line_cursor < L:
            tail_lines = lines[line_cursor:]
            seg_end = float(segments[-1].get("end", 0) or 0)
            span_end = (
                float(total_duration)
                if total_duration and float(total_duration) > seg_end
                else seg_end + 3.0 * len(tail_lines)
            )
            per = max(0.8, (span_end - seg_end) / len(tail_lines))
            tail_start = seg_end
            for line in tail_lines:
                tail_end = tail_start + per
                out.append(str(counter))
                out.append(
                    f"{_format_srt_time(tail_start)} --> {_format_srt_time(tail_end)}"
                )
                out.append(line)
                out.append("")
                counter += 1
                tail_start = tail_end

    return "\n".join(out).strip() + "\n"


def detect_vocal_phrases(
    envelope, duration: float, *,
    thresh_ratio: float = 0.12, min_phrase: float = 0.6, min_gap: float = 0.30,
) -> list[tuple[float, float]]:
    """진폭 envelope 에서 '노래하는 구간'(보컬 에너지가 있는 구간)을 찾는다.

    무슨 단어인지 인식하지 않고 소리가 있는 구간만 검출하므로, Whisper 가
    가사를 못 알아듣는 곡에서도 동작한다. (보컬 분리된 트랙이면 더 정확)
    """
    if envelope is None or duration <= 0:
        return []
    env = np.asarray(envelope, dtype=np.float32)
    n = len(env)
    if n == 0:
        return []
    # 약 0.1초 창으로 평활화해 잡음으로 인한 잘게 쪼개짐 방지.
    w = max(1, int(n / duration * 0.1))
    if w > 1:
        env = np.convolve(env, np.ones(w, dtype=np.float32) / w, mode="same")
    ref = float(np.percentile(env, 95)) or float(env.max()) or 1.0
    if ref <= 0:
        return []
    active = (env / ref) > thresh_ratio
    dt = duration / n

    phrases: list[list[float]] = []
    cur: list[float] | None = None
    for idx, a in enumerate(active):
        if a:
            t = idx * dt
            if cur is None:
                cur = [t, t + dt]
            else:
                cur[1] = t + dt
        elif cur is not None:
            phrases.append(cur)
            cur = None
    if cur is not None:
        phrases.append(cur)

    # 짧은 무음 간격(min_gap 미만)은 한 구간으로 병합.
    merged: list[list[float]] = []
    for p in phrases:
        if merged and p[0] - merged[-1][1] < min_gap:
            merged[-1][1] = p[1]
        else:
            merged.append(p[:])
    # 너무 짧은 구간은 제거.
    merged = [p for p in merged if (p[1] - p[0]) >= min_phrase]
    return [(round(s, 3), round(e, 3)) for s, e in merged]


def align_lyrics_to_phrases(
    lyrics_lines: list[str],
    phrases: list[tuple[float, float]],
    duration: float | None,
) -> str:
    """감지된 보컬 구간에 내 가사를 순서대로 배치한 SRT."""
    lines = [ln.strip() for ln in lyrics_lines if ln.strip()]
    if not lines:
        return ""
    if not phrases:
        D = float(duration or 0) or len(lines) * 3.0
        return _even_distribute_lyrics(lines, 0.0, 0.97 * D)

    L, P = len(lines), len(phrases)
    rows: list[dict] = []
    if L == P:
        for line, (s, e) in zip(lines, phrases):
            rows.append({"start": s, "end": e, "text": line})
    elif L < P:
        # 가사보다 보컬 구간이 많으면 구간을 묶어 한 줄에 매핑.
        for i, line in enumerate(lines):
            s_idx = int(round(i * P / L))
            e_idx = min(max(int(round((i + 1) * P / L)) - 1, s_idx), P - 1)
            rows.append({
                "start": phrases[s_idx][0], "end": phrases[e_idx][1], "text": line,
            })
    else:
        # 가사가 더 많으면 한 구간을 여러 줄로 분할.
        cursor = 0
        for j, (s, e) in enumerate(phrases):
            target = max(1, int(round((j + 1) * L / P)) - int(round(j * L / P)))
            sub = lines[cursor:cursor + target]
            cursor += target
            if not sub:
                continue
            d = (e - s) / len(sub)
            for k, line in enumerate(sub):
                rows.append({
                    "start": s + k * d, "end": s + (k + 1) * d, "text": line,
                })
        if cursor < L:  # 남은 줄은 마지막 구간 끝 ~ 곡 끝에 분배.
            tail = lines[cursor:]
            last_e = phrases[-1][1]
            D = float(duration or 0)
            span_end = 0.97 * D if D > last_e else last_e + 2.0 * len(tail)
            per = max(0.8, (span_end - last_e) / len(tail))
            ts = last_e
            for line in tail:
                rows.append({"start": ts, "end": ts + per, "text": line})
                ts += per
    return _rows_to_srt(rows)


def _norm_text(s: str) -> str:
    """매칭용 정규화: 소문자 + 구두점 제거 + 공백 정리."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def align_lyrics_by_similarity(
    lyrics_lines: list[str], segments: list[dict]
) -> str:
    """Whisper 가 곡 전체에서 들은 구간마다, 내 가사 중 가장 비슷한 줄을 매칭한다.

    Whisper 가 후렴 반복까지 음향으로 감지하므로, 반복되는 구간에는 같은 가사 줄이
    자동으로 다시 채워진다. 텍스트는 내 가사 원본을 그대로 사용 → 정확.
    """
    import difflib

    lines = [ln.strip() for ln in lyrics_lines if ln.strip()]
    if not lines or not segments:
        return ""
    norm_lines = [_norm_text(l) for l in lines]

    cues: list[dict] = []
    for seg in segments:
        s = float(seg.get("start", 0) or 0)
        e = float(seg.get("end", s) or s)
        if e <= s:
            e = s + 0.5
        seg_norm = _norm_text(seg.get("text", ""))
        best_i, best_r = 0, -1.0
        for i, nl in enumerate(norm_lines):
            if not nl:
                continue
            r = difflib.SequenceMatcher(None, seg_norm, nl).ratio()
            if r > best_r:
                best_r, best_i = r, i
        cues.append({"start": s, "end": e, "text": lines[best_i]})

    # 연속으로 같은 가사 줄이 매칭되면 하나로 합친다.
    merged: list[dict] = []
    for c in cues:
        if merged and merged[-1]["text"] == c["text"]:
            merged[-1]["end"] = c["end"]
        else:
            merged.append(dict(c))
    return _rows_to_srt(merged)


def _parse_srt_time(ts: str) -> float:
    """SRT 타임스탬프 → 초. '00:01:23,456' → 83.456"""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _parse_srt_starts(srt_text: str) -> list[float]:
    """SRT 텍스트에서 자막 시작 시각 목록 추출."""
    return [
        _parse_srt_time(m.group(1))
        for m in re.finditer(r"(\d+:\d+:\d+,\d+)\s+-->", srt_text)
    ]


def _rows_to_srt(rows: list[dict]) -> str:
    """[{start, end, text}] → SRT 문자열."""
    out: list[str] = []
    for i, r in enumerate(rows, 1):
        out.append(str(i))
        out.append(
            f"{_format_srt_time(r['start'])} --> {_format_srt_time(r['end'])}"
        )
        out.append(r["text"])
        out.append("")
    return "\n".join(out).strip() + "\n"


def _parse_srt_cues(srt_text: str) -> list[dict]:
    """SRT 텍스트 → [{start, end, text}] (재생 동기화 플레이어용)."""
    cues: list[dict] = []
    for raw in re.split(r"\n\n+", srt_text.strip()):
        lines = raw.strip().splitlines()
        if len(lines) < 2:
            continue
        idx = 1 if re.match(r"^\d+$", lines[0].strip()) else 0
        if idx >= len(lines):
            continue
        m = re.match(
            r"(\d+:\d+:\d+,\d+)\s+-->\s+(\d+:\d+:\d+,\d+)", lines[idx].strip()
        )
        if not m:
            continue
        text = " ".join(ln.strip() for ln in lines[idx + 1:] if ln.strip())
        cues.append({
            "start": _parse_srt_time(m.group(1)),
            "end": _parse_srt_time(m.group(2)),
            "text": text,
        })
    return cues


def _even_distribute_lyrics(
    lyrics_lines: list[str], start: float, end: float
) -> str:
    """가사 라인들을 [start, end] 구간에 시간 기준으로 고르게 배치한 SRT."""
    lines = [ln.strip() for ln in lyrics_lines if ln.strip()]
    if not lines:
        return ""
    if end <= start:
        end = start + len(lines) * 2.0
    per = (end - start) / len(lines)
    rows = []
    for i, line in enumerate(lines):
        rows.append({
            "start": start + i * per,
            "end": start + (i + 1) * per,
            "text": line,
        })
    return _rows_to_srt(rows)


def _ensure_lyrics_cover_song(
    srt_text: str,
    lyrics_lines: list[str],
    total_duration: float | None,
) -> tuple[str, bool]:
    """Whisper 가 곡 앞부분만 인식해 가사가 앞에 몰린 경우,
    가사를 곡 전체(보컬 시작 ~ 곡 끝 부근)에 고르게 다시 펼친다.

    반환: (보정된 SRT, 보정여부)
    """
    D = float(total_duration or 0)
    if D <= 0:
        return srt_text, False
    cues = _parse_srt_cues(srt_text)
    if not cues:
        return srt_text, False
    onset = float(cues[0]["start"])
    last_end = float(cues[-1]["end"])
    # 자막이 곡의 70% 지점 이전에서 끝나면 = 뒷부분을 못 잡은 것으로 보고 곡 끝까지 펼친다.
    if last_end >= 0.7 * D:
        return srt_text, False
    new_srt = _even_distribute_lyrics(lyrics_lines, onset, 0.97 * D)
    if not new_srt:
        return srt_text, False
    return new_srt, True


def _encode_player_audio(audio_path: str) -> tuple[bytes | None, str]:
    """재생 플레이어 내장용 오디오를 만든다.

    브라우저 호환을 위해 가능하면 mono 96kbps mp3 로 재인코딩하고,
    실패하면 원본 바이트를 그대로 사용한다. (bytes, mime) 반환.
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        out = audio_path + "_player.mp3"
        try:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-i", audio_path,
                "-vn", "-ac", "1", "-b:a", "96k", out,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=180)
            if proc.returncode == 0 and os.path.exists(out):
                with open(out, "rb") as fp:
                    data = fp.read()
                return data, "audio/mpeg"
        except Exception:
            pass
        finally:
            try:
                if os.path.exists(out):
                    os.unlink(out)
            except OSError:
                pass
    # Fallback: 원본 바이트.
    try:
        with open(audio_path, "rb") as fp:
            data = fp.read()
        ext = os.path.splitext(audio_path)[1].lower().lstrip(".")
        mime = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
            "aac": "audio/aac", "ogg": "audio/ogg", "flac": "audio/flac",
        }.get(ext, "audio/mpeg")
        return data, mime
    except OSError:
        return None, "audio/mpeg"


def _word_level_align(lyrics_lines: list[str], words: list[dict]) -> str:
    """
    Whisper word-level 타임스탬프를 이용해 각 가사 라인의 SRT 시각을 결정한다.
    단어 목록을 라인 수로 균등 분할해 첫 단어의 start ~ 마지막 단어의 end 를 사용.
    """
    lines = [ln.strip() for ln in lyrics_lines if ln.strip()]
    if not lines or not words:
        return ""
    L, W = len(lines), len(words)
    out: list[str] = []
    for i, line in enumerate(lines):
        w0 = int(round(i * W / L))
        w1 = min(int(round((i + 1) * W / L)) - 1, W - 1)
        w1 = max(w1, w0)
        start = float(words[w0].get("start", 0) or 0)
        end = float(words[w1].get("end", start) or start)
        if end <= start:
            end = start + 0.3
        out.append(str(i + 1))
        out.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
        out.append(line)
        out.append("")
    return "\n".join(out).strip() + "\n"


def _chorus_correct_srt(srt_text: str) -> str:
    """
    반복 가사 라인 보정: 같은 텍스트의 재등장 구간이 첫 등장 duration 의 30% 미만이면
    첫 등장의 duration 을 복사해 자연스럽게 이어붙인다.
    """
    blocks: list[dict] = []
    for raw in re.split(r"\n\n+", srt_text.strip()):
        sub = raw.strip().splitlines()
        if len(sub) < 3:
            continue
        try:
            int(sub[0].strip())
        except ValueError:
            continue
        m = re.match(r"(\d+:\d+:\d+,\d+)\s+-->\s+(\d+:\d+:\d+,\d+)", sub[1].strip())
        if not m:
            continue
        s_str, e_str = m.group(1), m.group(2)
        blocks.append({
            "s_str": s_str, "e_str": e_str,
            "start": _parse_srt_time(s_str),
            "end": _parse_srt_time(e_str),
            "text": "\n".join(sub[2:]).strip(),
        })
    if not blocks:
        return srt_text

    first: dict[str, dict] = {}
    for blk in blocks:
        key = re.sub(r"\s+", " ", blk["text"].lower()).strip()
        if key not in first:
            first[key] = blk

    corrected: list[dict] = []
    prev_end = 0.0
    for blk in blocks:
        key = re.sub(r"\s+", " ", blk["text"].lower()).strip()
        ref = first[key]
        ref_dur = ref["end"] - ref["start"]
        cur_dur = blk["end"] - blk["start"]
        if ref is not blk and ref_dur > 0 and cur_dur < ref_dur * 0.3:
            new_start = max(prev_end + 0.05, blk["start"])
            new_end = new_start + ref_dur
            blk = dict(blk)
            blk["start"] = new_start
            blk["end"] = new_end
            blk["s_str"] = _format_srt_time(new_start)
            blk["e_str"] = _format_srt_time(new_end)
        prev_end = blk["end"]
        corrected.append(blk)

    out = []
    for i, blk in enumerate(corrected):
        out.append(str(i + 1))
        out.append(f"{blk['s_str']} --> {blk['e_str']}")
        out.append(blk["text"])
        out.append("")
    return "\n".join(out).strip() + "\n"


def extract_waveform_data(
    audio_path: str, n_points: int = 900
) -> tuple["np.ndarray | None", float]:
    """ffmpeg 으로 단채널 PCM WAV 추출 후 진폭 envelope 반환. (envelope, duration_sec)"""
    import wave as _wave
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None, 0.0
    wav_path = audio_path + "_wf_tmp.wav"
    try:
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-i", audio_path,
            "-vn", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "11025",
            wav_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0 or not os.path.exists(wav_path):
            return None, 0.0
        with _wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            sr = wf.getframerate()
            duration = n_frames / max(sr, 1)
            raw = wf.readframes(n_frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return None, duration
        chunk = max(1, len(samples) // n_points)
        envelope = np.array(
            [np.max(np.abs(samples[i * chunk: (i + 1) * chunk]))
             for i in range(min(n_points, len(samples) // chunk))],
            dtype=np.float32,
        )
        return envelope, duration
    except Exception:
        return None, 0.0
    finally:
        try:
            if os.path.exists(wav_path):
                os.unlink(wav_path)
        except OSError:
            pass


_SYNC_PLAYER_TEMPLATE = """
<div id="lp-root" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
     'Malgun Gothic',sans-serif;color:#e6e6e6;">
  <audio id="lp-aud" controls preload="auto" style="width:100%;outline:none;"
         src="__AUDIO_SRC__"></audio>
  <div style="display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap;">
    <button id="lp-play" style="background:#1f6feb;color:#fff;border:none;
      border-radius:6px;padding:6px 14px;cursor:pointer;font-size:14px;font-weight:700;">
      ▶ 재생 / ⏸</button>
    <button id="lp-add" style="background:#238636;color:#fff;border:none;
      border-radius:6px;padding:6px 14px;cursor:pointer;font-size:14px;font-weight:700;">
      ➕ 지금 줄 추가</button>
    <button id="lp-zout" style="background:#21262d;color:#ddd;border:1px solid #333;
      border-radius:6px;padding:6px 10px;cursor:pointer;font-size:14px;">🔍−</button>
    <button id="lp-zin" style="background:#21262d;color:#ddd;border:1px solid #333;
      border-radius:6px;padding:6px 10px;cursor:pointer;font-size:14px;">🔍＋</button>
    <button id="lp-zfit" style="background:#21262d;color:#ddd;border:1px solid #333;
      border-radius:6px;padding:6px 10px;cursor:pointer;font-size:13px;">전체</button>
    <span id="lp-time" style="margin-left:auto;color:#7fd4ff;font-size:14px;
      font-variant-numeric:tabular-nums;">0:00.0 / 0:00</span>
  </div>
  <div id="lp-wrap" style="overflow-x:auto;overflow-y:hidden;margin-top:6px;
       border-radius:8px;background:#161b22;">
    <canvas id="lp-wave" style="height:140px;display:block;cursor:pointer;"></canvas>
  </div>
  <div id="lp-now" style="text-align:center;font-size:20px;font-weight:700;
       min-height:30px;margin:10px 4px 6px;line-height:1.4;color:#fff;">
  </div>
  <div id="lp-list" style="max-height:240px;overflow-y:auto;padding:4px;
       background:#0e1117;border-radius:8px;border:1px solid #222;">
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin-top:10px;flex-wrap:wrap;">
    <button id="lp-dl" style="background:#fa5252;color:#fff;border:none;
      border-radius:6px;padding:8px 16px;cursor:pointer;font-size:14px;font-weight:700;">
      📥 SRT 다운로드</button>
    <button id="lp-copy" style="background:#21262d;color:#ddd;border:1px solid #333;
      border-radius:6px;padding:8px 14px;cursor:pointer;font-size:14px;">📋 복사</button>
    <span id="lp-msg" style="color:#7ee787;font-size:13px;"></span>
  </div>
  <textarea id="lp-srt" readonly style="display:none;width:100%;height:120px;
    margin-top:8px;background:#0e1117;color:#ddd;border:1px solid #333;border-radius:6px;
    font-size:12px;"></textarea>
</div>
<script>
(function(){
  const D = __PAYLOAD__;
  const aud = document.getElementById('lp-aud');
  const cv  = document.getElementById('lp-wave');
  const wrap= document.getElementById('lp-wrap');
  const now = document.getElementById('lp-now');
  const list= document.getElementById('lp-list');
  const timeEl = document.getElementById('lp-time');
  const msg = document.getElementById('lp-msg');
  const srtArea = document.getElementById('lp-srt');
  const ctx = cv.getContext('2d');
  const env = D.envelope || [];
  const dur = D.duration || (aud.duration || 0);

  // 편집 가능한 자막 항목 (시작시간 + 텍스트). 시작시간 순으로 유지.
  let items = (D.cues || []).map(c => ({start: +c.start || 0, text: c.text || ''}));
  items.sort((a,b)=>a.start-b.start);

  function fmt(t){
    if(!isFinite(t)) t=0;
    const m=Math.floor(t/60), s=t-m*60;
    return m+':'+(s<10?'0':'')+s.toFixed(1);
  }
  function fmtShort(t){
    if(!isFinite(t)) t=0;
    const m=Math.floor(t/60), s=Math.floor(t%60);
    return m+':'+(s<10?'0':'')+s;
  }
  function pad(n,l){ n=String(Math.floor(n)); while(n.length<l) n='0'+n; return n; }
  function srtTime(t){
    if(!isFinite(t)||t<0) t=0;
    const h=Math.floor(t/3600), m=Math.floor((t%3600)/60), s=Math.floor(t%60);
    const ms=Math.round((t-Math.floor(t))*1000);
    return pad(h,2)+':'+pad(m,2)+':'+pad(s,2)+','+pad(ms,3);
  }

  // ----- 리스트(편집 행) 렌더 -----
  let rowsUI = [];
  function render(){
    list.innerHTML=''; rowsUI=[];
    items.forEach((it, idx) => {
      const row=document.createElement('div');
      row.style.cssText='display:flex;gap:6px;align-items:center;margin:2px 0;';
      const tb=document.createElement('button');
      tb.textContent='▶ '+fmt(it.start);
      tb.style.cssText='background:#21262d;color:#9cf;border:1px solid #333;'+
        'border-radius:5px;padding:4px 6px;cursor:pointer;font-size:12px;'+
        'min-width:64px;font-variant-numeric:tabular-nums;';
      tb.onclick=()=>{ aud.currentTime=it.start; aud.play(); };
      const inp=document.createElement('input');
      inp.type='text'; inp.value=it.text; inp.placeholder='여기에 가사 입력';
      inp.style.cssText='flex:1;background:#161b22;color:#fff;border:1px solid #2a3340;'+
        'border-radius:5px;padding:6px 8px;font-size:15px;';
      inp.oninput=()=>{ it.text=inp.value; };
      const del=document.createElement('button');
      del.textContent='✕';
      del.style.cssText='background:#2d2230;color:#f88;border:1px solid #533;'+
        'border-radius:5px;padding:4px 8px;cursor:pointer;font-size:12px;';
      del.onclick=()=>{ items.splice(idx,1); render(); };
      row.appendChild(tb); row.appendChild(inp); row.appendChild(del);
      list.appendChild(row);
      rowsUI.push({row, inp, start: it.start});
    });
    active = -1;
  }
  let active=-1;
  render();

  function setActive(i){
    if(i===active) return;
    if(active>=0 && rowsUI[active]) rowsUI[active].row.style.background='transparent';
    active=i;
    if(i>=0 && rowsUI[i]){
      rowsUI[i].row.style.background='#1f6feb33';
      now.textContent = items[i].text || '(가사 입력)';
    } else { now.textContent=''; }
  }
  function curIndex(t){
    let last=-1;
    for(let i=0;i<items.length;i++){ if(t>=items[i].start-0.01) last=i; else break; }
    return last;
  }

  // ----- 줄 추가 -----
  document.getElementById('lp-add').onclick=()=>{
    const t=aud.currentTime||0;
    items.push({start:t, text:''});
    items.sort((a,b)=>a.start-b.start);
    render();
    const i=items.findIndex(it=>Math.abs(it.start-t)<0.0001 && it.text==='');
    if(rowsUI[i]){ rowsUI[i].row.scrollIntoView({block:'nearest'}); rowsUI[i].inp.focus(); }
    msg.textContent='줄 추가됨 ('+fmt(t)+')'; setTimeout(()=>msg.textContent='',1500);
  };

  // ----- 재생/일시정지 -----
  document.getElementById('lp-play').onclick=()=>{ if(aud.paused) aud.play(); else aud.pause(); };
  document.addEventListener('keydown',(e)=>{
    if(e.code==='Space' && e.target.tagName!=='INPUT' && e.target.tagName!=='TEXTAREA'){
      e.preventDefault(); if(aud.paused) aud.play(); else aud.pause();
    }
  });

  // ----- SRT 만들기/내보내기 -----
  function buildSRT(){
    const arr=items.filter(it=>(it.text||'').trim()!=='').slice().sort((a,b)=>a.start-b.start);
    let out='';
    for(let i=0;i<arr.length;i++){
      const s=arr[i].start;
      let e=(i+1<arr.length)? arr[i+1].start-0.05 : ((dur||s+3));
      if(e<=s) e=s+1.5;
      out += (i+1)+'\\n'+srtTime(s)+' --> '+srtTime(e)+'\\n'+arr[i].text.trim()+'\\n\\n';
    }
    return out.trim()+'\\n';
  }
  document.getElementById('lp-dl').onclick=()=>{
    const txt=buildSRT();
    if(txt.trim()===''){ msg.style.color='#f88'; msg.textContent='가사를 먼저 입력하세요'; return; }
    try{
      const blob=new Blob([txt],{type:'application/x-subrip;charset=utf-8'});
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url; a.download='lyrics.srt'; document.body.appendChild(a); a.click();
      setTimeout(()=>{URL.revokeObjectURL(url); a.remove();},1000);
      msg.style.color='#7ee787'; msg.textContent='다운로드 시작!';
    }catch(err){
      // 다운로드가 막히면 텍스트로 보여줌.
      srtArea.style.display='block'; srtArea.value=txt; srtArea.select();
      msg.style.color='#7ee787'; msg.textContent='아래 칸의 내용을 복사해 .srt 로 저장하세요';
    }
  };
  document.getElementById('lp-copy').onclick=()=>{
    const txt=buildSRT();
    if(txt.trim()===''){ msg.style.color='#f88'; msg.textContent='가사를 먼저 입력하세요'; return; }
    const done=()=>{ msg.style.color='#7ee787'; msg.textContent='복사됨!'; };
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).then(done, ()=>{
        srtArea.style.display='block'; srtArea.value=txt; srtArea.select(); done();
      });
    } else {
      srtArea.style.display='block'; srtArea.value=txt; srtArea.select();
      try{ document.execCommand('copy'); }catch(e){}
      done();
    }
  };

  // ----- 파형 + 줌 -----
  let W=0, H=0, W0=0, zoom=1, dpr=window.devicePixelRatio||1;
  function resize(){
    W0=wrap.clientWidth||600; W=Math.max(W0, Math.floor(W0*zoom)); H=140;
    cv.style.width=W+'px'; cv.width=Math.max(1,Math.floor(W*dpr));
    cv.height=Math.max(1,Math.floor(H*dpr)); ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function setZoom(z){
    const dd=dur||aud.duration||1; const center=(aud.currentTime||0)/dd;
    zoom=Math.min(60,Math.max(1,z)); resize();
    wrap.scrollLeft=Math.max(0, center*W - W0/2);
  }
  document.getElementById('lp-zin').onclick =()=>setZoom(zoom*1.7);
  document.getElementById('lp-zout').onclick=()=>setZoom(zoom/1.7);
  document.getElementById('lp-zfit').onclick=()=>setZoom(1);
  window.addEventListener('resize', resize);
  resize();

  function draw(){
    const t=aud.currentTime||0; const dd=dur||aud.duration||1;
    ctx.clearRect(0,0,W,H);
    const n=env.length||1, bw=W/n;
    for(let i=0;i<n;i++){
      const a=env[i]||0, bh=Math.max(1,a*(H*0.9));
      ctx.fillStyle=((i/n)*dd<=t)?'#4CAF50':'#2e7d4f';
      ctx.fillRect(i*bw,(H-bh)/2,Math.max(1,bw*0.9),bh);
    }
    ctx.fillStyle='rgba(255,112,67,0.6)';
    items.forEach(it=>{ if(it.start>=0&&it.start<=dd) ctx.fillRect((it.start/dd)*W,0,1,H); });
    const px=(t/dd)*W;
    ctx.fillStyle='#fff'; ctx.fillRect(px-1,0,2,H);
    ctx.fillStyle='#ff5252'; ctx.beginPath(); ctx.arc(px,6,4,0,Math.PI*2); ctx.fill();
    if(!aud.paused && zoom>1){
      const vw=wrap.clientWidth, p=vw*0.15;
      if(px<wrap.scrollLeft+p || px>wrap.scrollLeft+vw-p) wrap.scrollLeft=Math.max(0,px-vw*0.3);
    }
    timeEl.textContent=fmt(t)+' / '+fmtShort(dd);
    setActive(curIndex(t));
    requestAnimationFrame(draw);
  }
  cv.addEventListener('click',(e)=>{
    const r=cv.getBoundingClientRect();
    const frac=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width));
    const dd=dur||aud.duration||0; if(dd>0){ aud.currentTime=frac*dd; aud.play(); }
  });
  requestAnimationFrame(draw);
})();
</script>
"""


def _render_sync_player(info: dict) -> None:
    """오디오 재생 + 파형 재생헤드 + 실시간 가사 하이라이트 + 클릭 탐색."""
    import streamlit.components.v1 as components

    audio_b64 = info.get("audio_b64")
    cues = info.get("cues") or []
    waveform = info.get("waveform") or {}
    if not audio_b64:
        st.info("재생용 오디오를 준비하지 못했습니다. 아래 정적 파형으로 확인하세요.")
        return

    payload = {
        "envelope": waveform.get("envelope") or [],
        "duration": float(
            waveform.get("duration") or info.get("duration") or 0
        ),
        "cues": cues,
    }
    src = f"data:{info.get('audio_mime', 'audio/mpeg')};base64,{audio_b64}"
    html = (
        _SYNC_PLAYER_TEMPLATE
        .replace("__AUDIO_SRC__", src)
        .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    )
    components.html(html, height=720, scrolling=False)
    st.caption(
        "▶ 재생하다가 한 줄이 시작되는 순간 **`➕ 지금 줄 추가`** 를 누르면 그 시점에 자막 줄이 "
        "생깁니다. 아래 칸에 가사를 입력하세요. (스페이스바 = 재생/일시정지) 다 만들면 "
        "**`📥 SRT 다운로드`** 로 받아 캡컷에 넣으면 됩니다. 🔍＋ 로 파형을 확대하면 정밀하게 "
        "맞출 수 있고, ▶ 시간칩이나 가사 줄을 누르면 그 구간이 재생됩니다."
    )


def render_sync_tab() -> None:
    st.subheader("🎤 가사 자동 동기화 → SRT (CapCut/Premiere 임포트용)")
    st.caption(
        "음악(또는 영상)을 업로드하면 Whisper 가 가사를 부르는 정확한 시점을 잡아 "
        "타임라인이 맞아떨어지는 SRT 자막을 만들어줍니다. "
        "**로컬 Whisper(무료)** 또는 **OpenAI API(유료, 빠름)** 중 선택할 수 있습니다."
    )

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        st.error("⚠️ ffmpeg 가 필요합니다. (오디오 추출/압축에 사용)")
        return

    # ---- 엔진 선택 ----
    engine = st.radio(
        "🎙️ Whisper 엔진",
        options=["local", "openai"],
        format_func=lambda k: {
            "local":  "💻 로컬 Whisper (무료) — 본인 컴퓨터에서 추론, API 키 불필요",
            "openai": "🌐 OpenAI Whisper API (유료, ~$0.03/5분) — 빠르고 설치 불필요",
        }[k],
        index=0,
        key="sync_engine",
        help=(
            "로컬: faster-whisper 패키지 필요 (`pip install faster-whisper`). "
            "첫 실행 시 모델을 자동 다운로드합니다. 같은 모델은 한 번만 받으면 영구 사용. "
            "OpenAI: 빠르고 설정이 간단하지만 곡당 약 40원."
        ),
    )

    api_key = ""
    model_size = "small"
    if engine == "openai":
        default_key = os.getenv("OPENAI_API_KEY", "") or SAVED_KEYS.get("openai", "")
        api_key = st.text_input(
            "OpenAI API 키",
            value=default_key,
            type="password",
            key="sync_api_key",
            help=(
                "https://platform.openai.com/api-keys 에서 발급. "
                "whisper-1 모델은 약 $0.006/분 입니다 (5분 곡 ≈ $0.03)."
            ),
        )
        save_col, clear_col = st.columns(2)
        if save_col.button("💾 OpenAI 키 저장", key="sync_openai_save"):
            if api_key.strip():
                save_key("openai", api_key.strip())
                SAVED_KEYS["openai"] = api_key.strip()
                st.success("저장됨.")
            else:
                st.warning("키가 비어 있습니다.")
        if clear_col.button(
            "🗑️ 해지", key="sync_openai_clear",
            disabled=not SAVED_KEYS.get("openai"),
        ):
            clear_key("openai")
            SAVED_KEYS.pop("openai", None)
            st.rerun()
    else:
        # 로컬 모델 크기 선택
        model_options = {
            "tiny":     "tiny (75MB) · 매우 빠름 · 한국어 정확도 낮음",
            "base":     "base (142MB) · 빠름 · 한국어 보통",
            "small":    "✓ small (462MB) · 균형 · 한국어 권장 (기본)",
            "medium":   "medium (1.5GB) · 느림 · 한국어 매우 정확",
            "large-v3": "large-v3 (3GB) · 매우 느림 · 최고 정확도",
        }
        model_size = st.selectbox(
            "🧠 로컬 모델 크기",
            options=list(model_options.keys()),
            format_func=lambda k: model_options[k],
            index=2,
            key="sync_local_model",
            help=(
                "모델은 첫 사용 시 ~/.cache/huggingface 에 자동 다운로드됩니다. "
                "한 번 받으면 다시 받지 않아요. 한국어 가사면 small 또는 medium 추천."
            ),
        )
        # faster-whisper 설치 여부 체크
        try:
            import faster_whisper  # noqa: F401
            st.caption("✓ faster-whisper 감지됨 — 바로 사용 가능합니다.")
        except ImportError:
            st.warning(
                "⚠️ `faster-whisper` 패키지가 설치되어 있지 않습니다.\n\n"
                "터미널에서 다음 명령으로 설치하세요:\n"
                "```\npip install faster-whisper\n```\n"
                "설치 후 앱을 재시작해주세요. (OpenAI API 옵션은 설치 없이 바로 사용 가능)"
            )

    # ---- 보컬 분리 (Demucs) — 정확도 향상 옵션 ----
    demucs_ok = demucs_available()
    use_demucs = st.checkbox(
        "🎤 보컬 분리로 정확도 높이기 (반주 제거 후 인식)",
        value=demucs_ok,
        key="sync_demucs",
        disabled=not demucs_ok,
        help=(
            "Demucs 로 반주를 제거하고 보컬만 Whisper 에 넣어 인식 정확도를 크게 높입니다. "
            "곡당 1~3분 정도 더 걸립니다. 재생 플레이어와 파형은 원곡 그대로 유지됩니다."
        ),
    )
    if not demucs_ok:
        st.info(
            "🎤 **보컬 분리를 켜려면 한 번만 설치하면 됩니다.**\n\n"
            "프로젝트 폴더의 **`보컬분리_설치.bat` 파일을 더블클릭**하세요. "
            "(설치 후 대시보드를 다시 실행하면 이 체크박스가 켜집니다.)\n\n"
            "직접 설치하려면 터미널에서 `pip install demucs` 도 가능합니다. "
            "설치 전에는 원곡 그대로 인식합니다 — 가사를 직접 붙여넣으면 분리 없이도 정확합니다."
        )
    elif use_demucs:
        st.caption("✓ Demucs 감지됨 — 반주를 제거하고 보컬만 인식합니다. (가사 없는 곡에 특히 유용)")

    audio_file = st.file_uploader(
        "🎵 음악 또는 영상 파일",
        type=["mp3", "wav", "m4a", "flac", "ogg", "aac", "mp4", "mov", "webm", "mkv"],
        key="sync_audio",
        help="MP4/MOV 영상이면 자동으로 오디오만 추출합니다. (25MB 초과 시 자동 압축)",
    )

    col1, col2 = st.columns(2)
    with col1:
        lang_options = [
            ("🌐 자동 감지 (다국어·혼합 가사 권장)", None),
            ("한국어 (ko)", "ko"),
            ("English (en)", "en"),
            ("日本語 (ja)", "ja"),
            ("中文 / 대만 (zh)", "zh"),
            ("Español (es)", "es"),
            ("हिन्दी / Hindi (hi)", "hi"),
            ("Português (pt)", "pt"),
            ("Français (fr)", "fr"),
            ("Deutsch (de)", "de"),
            ("Italiano (it)", "it"),
            ("Bahasa Indonesia (id)", "id"),
            ("Tiếng Việt (vi)", "vi"),
            ("ภาษาไทย (th)", "th"),
            ("Русский (ru)", "ru"),
            ("العربية (ar)", "ar"),
        ]
        lang_pick = st.selectbox(
            "언어",
            options=lang_options,
            format_func=lambda x: x[0],
            index=0,
            key="sync_lang",
            help=(
                "단일 언어 곡이면 해당 언어를 직접 고르면 정확도가 가장 높습니다. "
                "여러 언어가 섞인 가사(예: 한국어+영어, 일본어+영어)는 '🌐 자동 감지'를 쓰세요. "
                "어떤 언어든 정확한 텍스트가 필요하면 아래 '가사' 칸에 직접 붙여넣는 것이 가장 정확합니다."
            ),
        )
    with col2:
        mode = st.radio(
            "동기화 모드",
            options=[
                "🎯 보컬 구간 자동 감지 (권장)",
                "Whisper 인식 결과만 사용",
            ],
            index=0,
            key="sync_mode",
            help=(
                "• 🎯 보컬 구간 자동 감지: Whisper 가 가사를 못 알아들어도 동작합니다. "
                "노래하는 구간(소리 에너지)을 곡 끝까지 찾습니다.\n"
                "   - 가사를 비워두면 → 각 구간을 **빈 자막 칸**으로 만들어 주고, 아래 표에서 "
                "직접 가사를 입력하면 됩니다. (가사 시작점만 잡아줌)\n"
                "   - 가사를 입력하면 → 감지한 구간에 내 가사를 순서대로 배치합니다.\n"
                "   - **보컬 분리(🎤)를 켜면 구간 감지가 훨씬 정확해집니다.**\n"
                "• Whisper 인식 결과만: 가사 없이 Whisper 가 들은 그대로 받아쓰기."
            ),
        )

    user_lyrics = st.text_area(
        "📝 가사 (한 줄 = 한 자막 라인) — 어떤 언어·혼합 가사도 OK",
        value="",
        height=240,
        key="sync_lyrics",
        placeholder=(
            "한 줄에 한 자막. 언어가 섞여도 그대로 적으면 됩니다:\n"
            "今夜も星が綺麗だね\n"
            "But I'm still thinking of you\n"
            "Bajo la luna seguiré\n"
            "..."
        ),
        help=(
            "여기에 가사를 붙여넣으면 언어가 몇 개 섞이든 텍스트가 100% 정확하게 들어가고, "
            "Whisper 는 타이밍만 맞춥니다. 비워두면 Whisper 가 들은 그대로(자동 감지) SRT 를 만듭니다. "
            "라인 수가 Whisper 구간 수와 달라도 자동으로 그룹화/분할됩니다."
        ),
    )

    with st.expander("⚙️ 고급 정렬 옵션", expanded=False):
        align_precision = st.radio(
            "정렬 정밀도",
            options=[
                "Segment 단위 (기본)",
                "Word 단위 (정밀) — 단어별 타임스탬프 사용",
            ],
            index=0,
            key="sync_precision",
            help=(
                "Word 단위: Whisper 가 각 단어의 발음 시작·끝을 개별로 잡아 "
                "라인을 Segment 단위보다 훨씬 정밀하게 맞춥니다. "
                "가사를 직접 입력한 경우에만 적용됩니다."
            ),
        )
        chorus_correct = st.checkbox(
            "후렴구 자동 보정",
            value=True,
            key="sync_chorus",
            help=(
                "반복되는 가사 라인(후렴구)이 재등장할 때 Whisper 가 잡은 구간 길이가 "
                "첫 번째 등장보다 너무 짧으면(30% 미만) 첫 번째 duration 을 복사해 보정합니다."
            ),
        )

    run = st.button(
        "🚀 동기화 시작",
        type="primary",
        use_container_width=True,
        key="sync_run",
    )

    if not run:
        if st.session_state.get("sync_srt"):
            _render_sync_result()
        return

    if not audio_file:
        st.error("음악(또는 영상) 파일을 업로드하세요.")
        return
    if engine == "openai" and not api_key.strip():
        st.error("OpenAI API 키가 필요합니다. (또는 위에서 '💻 로컬 Whisper' 를 선택하세요)")
        return

    workdir = tempfile.mkdtemp(prefix="ytmusic_sync_")
    try:
        src_path = os.path.join(workdir, audio_file.name)
        with open(src_path, "wb") as fp:
            fp.write(audio_file.getbuffer())

        # 영상이면 오디오 추출.
        is_video = audio_file.name.lower().endswith(
            (".mp4", ".mov", ".webm", ".mkv", ".avi")
        )
        if is_video:
            audio_path = os.path.join(workdir, "extracted.mp3")
            with st.spinner("🎬 영상에서 오디오 추출 중..."):
                ok, log = extract_audio_track(src_path, audio_path)
            if not ok:
                st.error("오디오 추출 실패")
                with st.expander("ffmpeg 로그", expanded=True):
                    st.code(log or "(없음)", language=None)
                return
        else:
            audio_path = src_path

        # 재생 플레이어/파형은 원곡(audio_path)을 그대로 쓰고,
        # Whisper 입력만 transcribe_path 로 따로 둔다.
        transcribe_path = audio_path

        # 보컬 분리 (Demucs) — 반주를 제거하고 보컬만 인식에 사용.
        if use_demucs and demucs_available():
            demucs_out = os.path.join(workdir, "demucs")
            with st.spinner(
                "🎤 보컬 분리 중 (Demucs)... 곡당 1~3분 소요. "
                "첫 실행이면 모델 다운로드가 먼저 진행돼요."
            ):
                vocal_path, dlog = separate_vocals(audio_path, demucs_out)
            if vocal_path:
                transcribe_path = vocal_path
                st.caption("✓ 보컬 분리 완료 — 반주를 제거한 보컬로 인식합니다.")
            else:
                st.warning("보컬 분리에 실패해 원곡 그대로 인식합니다. 아래 사유를 확인하세요.")
                with st.expander("🔎 보컬 분리 실패 사유 (전체 로그)", expanded=True):
                    st.code(dlog or "(로그 없음)", language=None)

        precomputed_cues = None
        phrase_mode = mode.startswith("🎯")

        if phrase_mode:
            # 인식에 의존하지 않음 — 보컬 에너지로 '노래하는 구간'을 곡 끝까지 찾는다.
            lyrics_lines = [ln for ln in user_lyrics.splitlines() if ln.strip()]
            with st.spinner("🎯 보컬 구간(부르는 부분) 감지 중..."):
                ph_env, ph_dur = extract_waveform_data(transcribe_path, n_points=6000)
            phrases = detect_vocal_phrases(ph_env, ph_dur)
            # 감지가 전혀 안 되면 4초 간격의 빈 슬롯이라도 만들어 둔다.
            if not phrases and ph_dur and ph_dur > 0:
                step = 4.0
                k = int(ph_dur // step) + 1
                phrases = [
                    (round(i * step, 2), round(min((i + 1) * step, ph_dur), 2))
                    for i in range(k)
                ]
            segments = []
            result = {"duration": ph_dur, "language": None, "segments": [], "words": []}
            src_label = (
                "보컬분리" if (use_demucs and transcribe_path != audio_path) else "원곡"
            )
            if lyrics_lines:
                srt_text = align_lyrics_to_phrases(lyrics_lines, phrases, ph_dur)
                line_count = srt_text.count(" --> ")
                method = (
                    f"🎯 {src_label} 보컬구간 {len(phrases)}개 · 내 가사 배치 "
                    f"→ 자막 {line_count}줄"
                )
            else:
                # 가사 없음 → 각 보컬 구간을 '빈 자막 칸'으로 만든다. 표에서 직접 입력.
                precomputed_cues = [
                    {"start": float(s), "end": float(e), "text": ""}
                    for (s, e) in phrases
                ]
                srt_text = _rows_to_srt(precomputed_cues)
                line_count = len(precomputed_cues)
                method = (
                    f"🎯 {src_label} 보컬구간 {len(phrases)}개 감지 — "
                    f"아래 ✏️ 표에서 각 구간에 가사를 입력하세요"
                )
            if not phrases:
                st.warning(
                    "보컬 구간을 감지하지 못했습니다. '🎤 보컬 분리'를 켜고 다시 시도해보세요."
                )
        else:
            # OpenAI 만 25MB 한도. 로컬은 제한 없음.
            if engine == "openai" and os.path.getsize(transcribe_path) > WHISPER_MAX_BYTES:
                compressed = os.path.join(workdir, "compressed.mp3")
                with st.spinner(
                    f"📦 파일이 25MB 를 넘어 mono 64kbps 로 압축 중... "
                    f"({os.path.getsize(transcribe_path)/1024/1024:.1f}MB)"
                ):
                    ok, log = compress_audio_for_whisper(transcribe_path, compressed)
                if not ok or os.path.getsize(compressed) > WHISPER_MAX_BYTES:
                    st.error(
                        f"파일이 너무 큽니다 ({os.path.getsize(transcribe_path)/1024/1024:.1f}MB). "
                        "25MB 이하로 직접 줄여서 다시 시도해주세요. "
                        "(또는 '💻 로컬 Whisper' 로 전환하면 용량 제한 없음)"
                    )
                    return
                transcribe_path = compressed

            # Whisper 호출 — 엔진별 분기.
            size_mb = os.path.getsize(transcribe_path) / 1024 / 1024
            if engine == "local":
                spinner_msg = (
                    f"💻 로컬 Whisper 로 분석 중... ({model_size} 모델, {size_mb:.1f}MB)\n\n"
                    "첫 실행이면 모델 다운로드(수 분)가 먼저 진행돼요. "
                    "이후엔 캐시에서 즉시 로드됩니다."
                )
                with st.spinner(spinner_msg):
                    try:
                        result = whisper_transcribe_local(
                            transcribe_path,
                            model_size=model_size,
                            language=lang_pick[1],
                        )
                    except RuntimeError as e:
                        st.error(str(e))
                        return
                    except Exception as e:
                        st.error(f"로컬 Whisper 추론 실패: {type(e).__name__}: {e}")
                        return
            else:
                with st.spinner(
                    f"🎤 OpenAI Whisper API 가 가사 타이밍을 분석 중... "
                    f"(업로드 {size_mb:.1f}MB · 곡 길이의 5~15% 소요)"
                ):
                    try:
                        result = whisper_transcribe(
                            transcribe_path, api_key.strip(), language=lang_pick[1]
                        )
                    except Exception as e:
                        st.error(f"Whisper API 호출 실패: {e}")
                        return

            segments = result.get("segments") or []
            if not segments:
                st.warning("Whisper 가 음성 구간을 찾지 못했습니다. (반주만 있는 구간일 수 있음)")
                return

            words: list[dict] = result.get("words") or []
            use_word_level = (
                align_precision.startswith("Word")
                and bool(words)
                and user_lyrics.strip()
                and not mode.startswith("Whisper 인식 결과만")
            )

            engine_label = "💻 로컬" if engine == "local" else "🌐 OpenAI"
            if engine == "local":
                engine_label += f"({model_size})"

            fill_mode = mode.startswith("내 가사로 곡 전체")

            if mode.startswith("Whisper 인식 결과만") or not user_lyrics.strip():
                srt_text = whisper_segments_to_srt(segments)
                method = f"{engine_label} · Whisper 직접 변환 · {len(segments)}구간"
                line_count = len(segments)
            elif fill_mode:
                lyrics_lines = [ln for ln in user_lyrics.splitlines() if ln.strip()]
                srt_text = align_lyrics_by_similarity(lyrics_lines, segments)
                line_count = srt_text.count(" --> ")
                method = (
                    f"{engine_label} · 곡 전체 자동 채움(반복 매칭) · "
                    f"가사 {len(lyrics_lines)}줄 → {len(segments)}구간 → 자막 {line_count}줄"
                )
            elif use_word_level:
                lyrics_lines = [ln for ln in user_lyrics.splitlines() if ln.strip()]
                srt_text = _word_level_align(lyrics_lines, words)
                line_count = len(lyrics_lines)
                method = f"{engine_label} · Word 단위 정밀 정렬 · {line_count}줄 → {len(words)}단어"
            else:
                lyrics_lines = [ln for ln in user_lyrics.splitlines() if ln.strip()]
                srt_text = align_lyrics_to_segments(
                    lyrics_lines, segments, result.get("duration")
                )
                line_count = len(lyrics_lines)
                method = f"{engine_label} · 가사 정렬 · 입력 {line_count}줄 → Whisper {len(segments)}구간"

            # 곡 끝까지 커버 보정 — '정렬' 모드에서 Whisper 가 앞부분만 잡아 가사가
            # 앞에 몰린 경우 곡 전체에 고르게 펼친다. (자동 채움 모드는 이미 곡 전체 커버)
            if user_lyrics.strip() and not mode.startswith("Whisper 인식 결과만") and not fill_mode:
                srt_text, stretched = _ensure_lyrics_cover_song(
                    srt_text, lyrics_lines, result.get("duration")
                )
                if stretched:
                    method += " + 곡 전체 커버 보정"

            # 후렴구 보정 ('정렬' 모드에서만 — 자동 채움은 Whisper 타이밍을 그대로 사용)
            if (
                chorus_correct and user_lyrics.strip()
                and not mode.startswith("Whisper 인식 결과만") and not fill_mode
            ):
                srt_text = _chorus_correct_srt(srt_text)
                method += " + 후렴구 보정"

        # 파형 추출 + 재생 플레이어용 오디오 인코딩 (workdir 정리 전)
        with st.spinner("🎵 파형 추출 중... (시각화용)"):
            envelope, wav_dur = extract_waveform_data(audio_path)
        with st.spinner("🔊 재생 플레이어 준비 중..."):
            player_bytes, player_mime = _encode_player_audio(audio_path)
        waveform = {
            "envelope": envelope.tolist() if envelope is not None else None,
            "duration": wav_dur or float(result.get("duration") or 0),
            "srt_starts": _parse_srt_starts(srt_text),
        }

        st.session_state["sync_srt"] = {
            "content": srt_text,
            "segments": segments,
            "method": method,
            "duration": result.get("duration"),
            "language_detected": result.get("language"),
            "line_count": line_count,
            "audio_filename": audio_file.name,
            "waveform": waveform,
            "cues": (
                precomputed_cues if precomputed_cues is not None
                else _parse_srt_cues(srt_text)
            ),
            "audio_b64": (
                base64.b64encode(player_bytes).decode("ascii")
                if player_bytes else None
            ),
            "audio_mime": player_mime,
        }
        st.success(f"✅ 동기화 완료 — {method}")
        _render_sync_result()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _render_sync_editor(info: dict) -> None:
    """가사·타이밍을 표에서 직접 수정 → SRT/플레이어에 즉시 반영."""
    st.caption(
        "각 줄은 노래에서 감지한 **가사 구간(시작~끝 시간)** 입니다. **'가사' 칸이 비어 있으면 "
        "그 구간에 들리는 가사를 직접 입력**하세요. 위 플레이어에서 그 줄을 클릭하면 해당 "
        "구간이 재생됩니다. 시작/끝 시간 조정·행 추가/삭제도 가능합니다. 다 채우면 아래 "
        "**적용** 버튼을 누르세요. (시간 단위: 초)"
    )
    cues = info.get("cues") or []
    df = pd.DataFrame(
        [
            {
                "시작(초)": round(float(c.get("start", 0) or 0), 2),
                "끝(초)": round(float(c.get("end", 0) or 0), 2),
                "가사": c.get("text", ""),
            }
            for c in cues
        ],
        columns=["시작(초)", "끝(초)", "가사"],
    )

    rev = info.get("editor_rev", 0)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"sync_editor_{rev}",
        column_config={
            "시작(초)": st.column_config.NumberColumn(
                "시작(초)", min_value=0.0, step=0.1, format="%.2f"
            ),
            "끝(초)": st.column_config.NumberColumn(
                "끝(초)", min_value=0.0, step=0.1, format="%.2f"
            ),
            "가사": st.column_config.TextColumn("가사", width="large"),
        },
    )

    if st.button(
        "✅ 수정 내용 적용 (SRT·플레이어 갱신)",
        type="primary",
        use_container_width=True,
        key=f"sync_editor_apply_{rev}",
    ):
        rows: list[dict] = []
        for _, r in edited.iterrows():
            text = str(r.get("가사") or "").strip()
            if not text:
                continue
            try:
                s = float(r.get("시작(초)") or 0)
            except (TypeError, ValueError):
                s = 0.0
            try:
                e = float(r.get("끝(초)") or 0)
            except (TypeError, ValueError):
                e = s
            if s < 0:
                s = 0.0
            if e <= s:
                e = s + 2.0
            rows.append({"start": s, "end": e, "text": text})

        if not rows:
            st.warning("가사가 비어 있습니다. 최소 한 줄은 있어야 합니다.")
            return

        rows.sort(key=lambda x: x["start"])
        info["content"] = _rows_to_srt(rows)
        info["cues"] = rows
        info["line_count"] = len(rows)
        info["editor_rev"] = rev + 1
        if info.get("waveform"):
            info["waveform"]["srt_starts"] = [r["start"] for r in rows]
        st.session_state["sync_srt"] = info
        st.success("✅ 적용 완료 — 위 플레이어와 SRT 다운로드에 반영했습니다.")
        st.rerun()


def _render_sync_result() -> None:
    info = st.session_state.get("sync_srt")
    if not info:
        return

    c1, c2, c3, c4 = st.columns(4)
    if info.get("duration"):
        secs = float(info["duration"])
        c1.metric("곡 길이", f"{int(secs // 60)}:{int(secs % 60):02d}")
    c2.metric("Whisper 구간", len(info["segments"]))
    c3.metric("자막 라인", info.get("line_count", 0))
    if info.get("language_detected"):
        c4.metric("감지 언어", info["language_detected"])

    st.download_button(
        "📥 SRT 다운로드 (CapCut 임포트용)",
        data=info["content"].encode("utf-8"),
        file_name=(
            f"lyrics_synced_"
            f"{os.path.splitext(info.get('audio_filename', 'song'))[0]}_"
            f"{datetime.now():%Y%m%d_%H%M%S}.srt"
        ),
        mime="application/x-subrip",
        type="primary",
        use_container_width=True,
        key="sync_download",
    )

    # 재생 플레이어 (오디오 + 실시간 가사 싱크)
    if info.get("audio_b64") and info.get("cues"):
        with st.expander("▶️ 재생하며 가사 싱크 확인", expanded=True):
            _render_sync_player(info)

    # 가사·타이밍 직접 수정 → 100% 만들기
    if info.get("cues"):
        with st.expander("✏️ 가사·타이밍 직접 수정 → 정확도 100% 만들기", expanded=True):
            _render_sync_editor(info)

    with st.expander("📄 생성된 SRT 미리보기", expanded=True):
        preview = info["content"]
        if len(preview) > 8000:
            preview = preview[:8000] + "\n\n...(이하 생략, 전체는 다운로드로 확인)"
        st.code(preview, language=None)

    st.caption(
        "💡 **CapCut 임포트 방법**: 캡컷에서 '자막' → '자막 가져오기 (SRT)' → 다운로드한 .srt 선택. "
        "타임라인에 자동 배치되며, 폰트/색/위치는 그대로 편집할 수 있습니다."
    )

    if st.button("🗑️ 결과 비우기", key="sync_cleanup"):
        st.session_state.pop("sync_srt", None)
        st.rerun()


# ---------------------------------------------------------------------------
# Title Lab tab — 수동 붙여넣기 → 공식 추출 → 신규 제목 생성
# ---------------------------------------------------------------------------


def _parse_title_lab_input(text: str) -> pd.DataFrame:
    """탭 5 입력 파서.

    한 줄당 한 제목. 옵션으로 `제목 | 조회수 | 구독자` 형식을 허용해
    view_sub_ratio 가 있으면 고성과 단어/서사 lift 분석을 함께 켠다.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            continue
        parts = [p.strip() for p in ln.split("|")]
        title = parts[0]
        views: int | None = None
        subs: int | None = None
        try:
            if len(parts) >= 2 and parts[1]:
                views = int(parts[1].replace(",", "").replace(" ", ""))
            if len(parts) >= 3 and parts[2]:
                subs = int(parts[2].replace(",", "").replace(" ", ""))
        except ValueError:
            views = subs = None
        ratio = (views / subs) if (views is not None and subs and subs > 0) else None
        rows.append({
            "video_title": title,
            "view_count": views,
            "subscriber_count": subs,
            "view_sub_ratio": ratio,
        })
    return pd.DataFrame(rows)


def render_title_lab_tab() -> None:
    st.subheader("🧪 제목 공식 발굴 & 생성")
    st.caption(
        "직접 모은 제목들을 붙여넣어 빈출 단어·서사 골격·페르소나를 추출하고, "
        "그 공식을 그대로 적용해 새 제목을 합성합니다."
    )

    with st.expander("ℹ️ 입력 형식 도움말", expanded=False):
        st.markdown(
            "- **기본**: 제목 한 줄에 하나씩 붙여넣기. 보통 10개 이상이 권장.\n"
            "- **고성과 표시(선택)**: `제목 | 조회수 | 구독자` 형식을 섞으면 "
            "view/sub 비율 상위 25% 그룹에서 두드러진 단어와 서사를 'Lift' 로 따로 뽑습니다.\n"
            "- 예시:\n"
            "  ```\n"
            "  비 오는 새벽 카페에서 듣는 lofi\n"
            "  잠 안 올 때 듣기 좋은 피아노 | 120000 | 1500\n"
            "  Rainy night jazz for studying | 800000 | 12000\n"
            "  ```"
        )

    titles_text = st.text_area(
        "분석할 제목 목록",
        height=260,
        placeholder="제목 1\n제목 2\n제목 3 | 50000 | 800\n...",
        key="title_lab_input",
    )

    df = _parse_title_lab_input(titles_text)

    if df.empty:
        st.info("위 박스에 제목을 붙여넣은 뒤 **🔍 패턴 분석하기** 버튼을 눌러주세요.")
        return

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("입력 제목 수", len(df))
    ratio_n = int(df["view_sub_ratio"].notna().sum())
    m2.metric("성과 지표 포함", f"{ratio_n}개")
    m3.metric("평균 글자수", f"{df['video_title'].str.len().mean():.1f}자")
    avg_words = df["video_title"].apply(lambda t: len(tokenize_title(t))).mean()
    m4.metric("평균 단어수", f"{avg_words:.1f}개")

    # view_sub_ratio 가 일부에만 있으면 lift 분석은 해당 행만 사용.
    df_for_analysis = df.copy()
    if df_for_analysis["view_sub_ratio"].isna().all():
        df_for_analysis = df_for_analysis.drop(columns=["view_sub_ratio"])

    analyze_clicked = st.button(
        "🔍 패턴 분석하기", type="primary", use_container_width=True
    )

    if analyze_clicked:
        with st.spinner("토큰화·서사 태깅·골격 추출 중..."):
            patterns = analyze_title_patterns(df_for_analysis)
            narrative = analyze_narrative(df_for_analysis)
            summary = summarize_story(narrative)
        st.session_state["title_lab_result"] = {
            "patterns": patterns,
            "narrative": narrative,
            "summary": summary,
            "lang_hint": detect_dominant_language(df["video_title"].tolist()),
            "existing_titles": df["video_title"].tolist(),
        }
        # 새 분석을 했으니 이전 시드는 초기화 — 분석 후 한 번 더 눌러야 새 시드로 생성.
        st.session_state.pop("title_lab_seed", None)

    result = st.session_state.get("title_lab_result")
    if not result:
        return

    patterns = result["patterns"]
    narrative = result["narrative"]
    summary = result["summary"]

    st.divider()
    st.markdown("### 📊 추출된 제목 공식")

    if summary:
        st.success(f"**지배 서사 한 줄 요약**: {summary}")
    else:
        st.warning(
            "사전 어휘와 일치하는 단서가 적습니다. "
            "한국어/영어 제목을 더 추가하면 서사 골격이 잡힙니다."
        )

    # 카테고리별 1위 (공식의 슬롯값들)
    cats = narrative.get("categories", {})
    cat_items = [
        (cat, items[0][0], items[0][1]) for cat, items in cats.items() if items
    ]
    if cat_items:
        st.markdown("#### 🧩 카테고리별 1위 (공식 슬롯값)")
        cat_df = pd.DataFrame(cat_items, columns=["카테고리", "대표 단서", "빈도"])
        st.dataframe(cat_df, use_container_width=True, hide_index=True)

    # 서사 골격 = 공식
    skeletons = narrative.get("skeletons", [])
    if skeletons:
        st.markdown("#### 🦴 자주 등장하는 서사 골격 (= 공식)")
        skel_df = pd.DataFrame(skeletons, columns=["서사 골격", "빈도"])
        st.dataframe(skel_df, use_container_width=True, hide_index=True)

    skel_lift = narrative.get("skeleton_lift", [])
    if skel_lift:
        st.markdown("#### 🚀 고성과 서사 (Lift ≥ 1.5)")
        lift_df = pd.DataFrame(
            skel_lift, columns=["서사 골격", "Lift", "상위 등장", "하위 등장"]
        )
        st.dataframe(lift_df, use_container_width=True, hide_index=True)

    personas = narrative.get("personas", [])
    if personas:
        st.markdown("#### 🎯 청자 페르소나")
        st.write(
            " · ".join(f"**{p}** ({c})" for p, c in personas[:10])
        )

    cooccur = narrative.get("cooccurrence", [])
    if cooccur:
        with st.expander("🔗 카테고리 동시 출현 (어떤 조합이 자주 묶이는가)"):
            co_df = pd.DataFrame(cooccur, columns=["조합", "빈도"])
            st.dataframe(co_df, use_container_width=True, hide_index=True)

    # n-gram 빈도
    if patterns:
        st.markdown("#### 🔤 빈출 단어 / 구문")
        ng_tabs = st.tabs(["1-gram", "2-gram", "3-gram"])
        for tab_, key in zip(ng_tabs, ["unigrams", "bigrams", "trigrams"]):
            with tab_:
                data = patterns.get(key, [])
                if data:
                    st.dataframe(
                        pd.DataFrame(data, columns=["토큰", "빈도"]),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("데이터가 부족합니다.")

        cl = patterns.get("char_length", {})
        wc = patterns.get("word_count", {})
        if cl and wc:
            st.caption(
                f"🧮 글자수 평균 **{cl.get('mean', 0)}** "
                f"(중앙값 {cl.get('median', 0)}, 범위 {cl.get('min', 0)}~{cl.get('max', 0)})  ·  "
                f"단어수 평균 **{wc.get('mean', 0)}** (중앙값 {wc.get('median', 0)})  ·  "
                f"이모지 포함 {patterns.get('emoji_share', 0):.0%}  ·  "
                f"괄호/대괄호 포함 {patterns.get('bracket_share', 0):.0%}"
            )

    diff = patterns.get("differential", []) if patterns else []
    if diff:
        st.markdown("#### 💎 고성과 단어 (조회/구독 상위 25% 그룹)")
        diff_df = pd.DataFrame(diff, columns=["단어", "Lift", "상위 등장", "하위 등장"])
        st.dataframe(diff_df, use_container_width=True, hide_index=True)

    # ----- 생성 영역 -----
    st.divider()
    st.markdown("### ✨ 공식 기반 새 제목 생성")

    gen_c1, gen_c2, gen_c3 = st.columns([2, 1, 1])
    with gen_c1:
        seed_theme = st.text_input(
            "시드 테마 (선택)",
            placeholder="예: 비 오는 새벽 / late night drive",
            key="title_lab_seed_theme",
        )
    with gen_c2:
        n_titles = st.slider("생성 개수", 3, 20, 8, key="title_lab_n")
    with gen_c3:
        lang_options = {
            f"자동 감지 ({result['lang_hint']})": result["lang_hint"],
            "한국어": "ko",
            "English": "en",
        }
        lang_label = st.selectbox(
            "언어", list(lang_options.keys()), key="title_lab_lang"
        )
        lang = lang_options[lang_label]

    btn_c1, btn_c2 = st.columns([1, 1])
    if btn_c1.button("🎲 제목 생성 / 다시 생성", use_container_width=True):
        st.session_state["title_lab_seed"] = random.randint(0, 999_999)
    if btn_c2.button("🧹 결과 초기화", use_container_width=True):
        st.session_state.pop("title_lab_seed", None)
        st.rerun()

    seed_val = st.session_state.get("title_lab_seed")
    if seed_val is None:
        st.info("**🎲 제목 생성** 버튼을 누르면 공식에서 새 제목을 합성합니다.")
        return

    generated = generate_titles(
        narrative,
        n=n_titles,
        seed_theme=(seed_theme or None),
        random_state=seed_val,
        lang=lang,
        existing_titles=result["existing_titles"],
    )

    if not generated:
        st.warning(
            "패턴 시그널이 약해 제목 합성에 실패했습니다. "
            "장르·시간·활동 등 단서가 들어간 제목을 더 추가해 보세요."
        )
        return

    st.caption(f"🌱 seed = `{seed_val}`  ·  같은 입력 + 같은 seed 면 결과가 재현됩니다.")

    for i, item in enumerate(generated, 1):
        with st.container(border=True):
            st.markdown(f"**#{i}**")
            st.code(item["title"], language="text")

    bundle = "\n".join(f"{i}. {item['title']}" for i, item in enumerate(generated, 1))
    st.download_button(
        "📥 전체 제목 .txt 로 다운로드",
        data=bundle.encode("utf-8"),
        file_name="title_lab_results.txt",
        mime="text/plain",
        use_container_width=True,
    )

    # 보너스: 태그도 같은 공식에서 뽑아 준다.
    tags = generate_tags(narrative, [], df=df_for_analysis)
    if tags:
        with st.expander("🏷️ 같은 공식으로 만든 추천 해시태그"):
            st.code(" ".join(f"#{t}" for t in tags), language="text")


@st.cache_data(show_spinner=False)
def _load_vocab() -> dict:
    return suno_studio.load_vocab()


# 차원 → (한국어 라벨, 단일선택 여부)
_STUDIO_DIMS: list[tuple[str, str, bool]] = [
    ("rhythm", "리듬 패턴", False),
    ("instruments", "악기", False),
    ("solo", "솔로/간주", False),
    ("vocal_ensemble", "보컬 편성", True),
    ("vocal_gender", "보컬 성별", True),
    ("vocal_register", "음색/음역", True),
    ("vocal_technique", "보컬 기교", False),
    ("production", "프로덕션/음향", False),
]


def _studio_picks_card(vocab: dict, preset_key: str, picks: dict, idx: int) -> None:
    prompt = suno_studio.picks_to_prompt(vocab, preset_key, picks)
    st.code(prompt, language=None)


def render_suno_studio_tab() -> None:
    st.subheader("🎚️ Suno 프롬프트 스튜디오")
    st.caption(
        "나라·무드·보컬(편성/성별/음색)·악기·솔로·리듬·빠르기를 골라 Suno 스타일 프롬프트를 "
        "즉시 조립하고, 마음에 드는 조합과 '비슷한 유형'의 변주를 여러 개 생성(벤치마킹)합니다."
    )

    vocab = _load_vocab()
    presets = suno_studio.list_presets(vocab)
    moods = suno_studio.list_moods(vocab)

    top = st.columns([1, 1])
    with top[0]:
        preset_key = st.selectbox(
            "나라/장르 프리셋",
            options=[k for k, _ in presets],
            format_func=lambda k: dict(presets)[k],
            key="ss_preset",
        )
    with top[1]:
        mood = st.selectbox(
            "무드/정서",
            options=[s for s, _ in moods],
            format_func=lambda s: dict(moods)[s],
            key="ss_mood",
        )

    country = vocab["presets"][preset_key].get("country")

    st.markdown("##### 🎛️ 수동 조합")
    picks: dict[str, list[str]] = {"mood": [mood]}
    dim_cols = st.columns(2)
    for i, (dim, label, _single) in enumerate(_STUDIO_DIMS):
        cands = suno_studio.candidates(vocab, dim, country=country, mood=mood)
        label_map = {c["suno"]: c["ko"] for c in cands}
        with dim_cols[i % 2]:
            chosen = st.multiselect(
                label,
                options=list(label_map.keys()),
                format_func=lambda s, m=label_map: m[s],
                key=f"ss_dim_{dim}",
            )
        picks[dim] = chosen

    lo_bpm, hi_bpm = suno_studio.mood_bpm_range(vocab, mood)
    bpm = st.slider(
        f"빠르기 BPM  (이 무드 권장: {lo_bpm}~{hi_bpm})",
        min_value=50, max_value=160, value=(lo_bpm + hi_bpm) // 2, key="ss_bpm",
    )
    picks["_bpm"] = [str(bpm)]

    st.markdown("**📋 조합된 Suno 프롬프트**")
    prompt = suno_studio.picks_to_prompt(vocab, preset_key, picks)
    st.code(prompt, language=None)

    hook = st.text_input("한국어 후렴구(hook) 아이디어 (선택)", key="ss_hook",
                         placeholder="예: 얼씨구 좋다, 달려보자 인생길")

    dl = f"# Suno 프롬프트\n\n## Style\n{prompt}\n"
    if hook.strip():
        dl += f"\n## Korean Hook\n{hook.strip()}\n"
    st.download_button("⬇️ 프롬프트 다운로드 (.md)", dl,
                       file_name="suno_prompt.md", key="ss_dl")

    st.divider()
    st.markdown("##### 🎲 자동 추천 · 🔁 벤치마킹 변주")
    act = st.columns([1, 1, 2])
    with act[0]:
        seed = st.number_input("시드", value=7, step=1, key="ss_seed")
    with act[1]:
        n_var = st.number_input("변주 개수", value=5, min_value=1, max_value=20,
                                step=1, key="ss_nvar")
    with act[2]:
        lock_opts = st.multiselect(
            "변주 시 고정할 차원 (정체성 보존)",
            options=["mood", "vocal_gender", "vocal_register", "rhythm"],
            default=["mood", "vocal_gender"],
            key="ss_lock",
        )

    btns = st.columns(2)
    if btns[0].button("🎲 무드 기반 자동 조합 추천", key="ss_auto_btn"):
        auto = suno_studio.auto_select(vocab, preset_key, mood, seed=int(seed))
        st.session_state["ss_auto_result"] = (preset_key, auto)
    if btns[1].button("🔁 위 수동 조합과 비슷한 변주 생성", key="ss_var_btn"):
        variations = suno_studio.generate_variations(
            vocab, preset_key, picks, n=int(n_var),
            lock=set(lock_opts), seed=int(seed),
        )
        st.session_state["ss_var_result"] = (preset_key, variations)

    auto_res = st.session_state.get("ss_auto_result")
    if auto_res:
        st.markdown("**🎲 자동 추천 조합**")
        _studio_picks_card(vocab, auto_res[0], auto_res[1], 0)

    var_res = st.session_state.get("ss_var_result")
    if var_res:
        pk, variations = var_res
        st.markdown(f"**🔁 벤치마킹 변주 {len(variations)}개**")
        md_lines = ["# Suno 벤치마킹 변주\n"]
        for i, var in enumerate(variations, 1):
            p = suno_studio.picks_to_prompt(vocab, pk, var)
            st.markdown(f"변주 {i}")
            st.code(p, language=None)
            md_lines.append(f"## 변주 {i}\n{p}\n")
        st.download_button("⬇️ 변주 전체 다운로드 (.md)", "\n".join(md_lines),
                           file_name="suno_variations.md", key="ss_var_dl")

    # ----- 📒 나만의 레시피 (저장·불러오기·블렌딩) -----
    st.divider()
    st.markdown("##### 📒 나만의 레시피")
    st.caption("마음에 든 조합을 이름 붙여 저장하고, 여러 레시피를 섞어 새 조합을 만듭니다.")

    def _recipe_prompt(rec: dict) -> str:
        p = dict(rec.get("picks", {}))
        if rec.get("bpm"):
            p["_bpm"] = [str(rec["bpm"])]
        return suno_studio.picks_to_prompt(vocab, rec.get("preset", preset_key), p)

    save_cols = st.columns([2, 1])
    with save_cols[0]:
        rcp_name = st.text_input("레시피 이름", key="ss_rcp_name",
                                 placeholder="예: 내 트로트 황금레시피 v1")
    with save_cols[1]:
        st.write("")
        st.write("")
        if st.button("💾 현재 조합 저장", key="ss_rcp_save"):
            if not any(picks.get(d) for d, _, _ in _STUDIO_DIMS):
                st.warning("저장할 조합이 비어 있습니다. 위에서 항목을 골라주세요.")
            else:
                rec = recipes.save_recipe(
                    rcp_name or "이름없는 레시피", preset_key, picks,
                    bpm=bpm, hook=hook,
                )
                st.success(f"저장됨: {rec['name']}")

    saved = recipes.list_recipes()
    if not saved:
        st.info("아직 저장된 레시피가 없습니다. 위에서 조합을 만들고 저장해보세요.")
        return

    label_map = {r["id"]: f"{r['name']}  ·  {dict(presets).get(r['preset'], r['preset'])}"
                 for r in saved}

    load_cols = st.columns([3, 1])
    with load_cols[0]:
        sel_id = st.selectbox("저장된 레시피", options=list(label_map.keys()),
                              format_func=lambda i: label_map[i], key="ss_rcp_sel")
    with load_cols[1]:
        st.write("")
        st.write("")
        if st.button("🗑️ 삭제", key="ss_rcp_del"):
            if recipes.delete_recipe(sel_id):
                st.success("삭제됨.")
                st.rerun()

    sel = recipes.get_recipe(sel_id)
    if sel:
        st.code(_recipe_prompt(sel), language=None)
        if st.button("🔁 이 레시피로 변주 생성", key="ss_rcp_var"):
            sel_picks = dict(sel.get("picks", {}))
            if sel.get("bpm"):
                sel_picks["_bpm"] = [str(sel["bpm"])]
            st.session_state["ss_var_result"] = (
                sel.get("preset", preset_key),
                suno_studio.generate_variations(
                    vocab, sel.get("preset", preset_key), sel_picks,
                    n=int(n_var), lock=set(lock_opts), seed=int(seed),
                ),
            )
            st.rerun()

    if len(saved) >= 2:
        st.markdown("**🧪 레시피 블렌딩**")
        blend_ids = st.multiselect("섞을 레시피 (2개 이상)", options=list(label_map.keys()),
                                   format_func=lambda i: label_map[i], key="ss_blend_sel")
        if st.button("🧪 블렌딩", key="ss_blend_btn"):
            chosen = [r for r in saved if r["id"] in blend_ids]
            if len(chosen) < 2:
                st.warning("2개 이상 골라주세요.")
            else:
                pk, blended = recipes.blend_recipes(chosen, seed=int(seed))
                st.session_state["ss_blend_result"] = (pk, blended)
        blend_res = st.session_state.get("ss_blend_result")
        if blend_res:
            pk, blended = blend_res
            st.code(suno_studio.picks_to_prompt(vocab, pk, blended), language=None)
            bname = st.text_input("블렌딩 결과 저장 이름", key="ss_blend_name",
                                  placeholder="예: 눈물+흥 블렌드")
            if st.button("💾 블렌딩을 레시피로 저장", key="ss_blend_save"):
                bpm_b = int(blended["_bpm"][0]) if blended.get("_bpm") else None
                rec = recipes.save_recipe(bname or "블렌드 레시피", pk, blended, bpm=bpm_b)
                st.success(f"저장됨: {rec['name']}")


def render_reverse_tab() -> None:
    st.subheader("🔎 곡 역설계 (메타데이터 → Suno picks)")
    st.caption(
        "유튜브 곡의 제목·태그·설명·댓글을 Gemini 가 분석해 통제 어휘(vocab) 안에서 스타일을 "
        "추출합니다. 오디오 다운로드 없이(ToS 안전) picks 로 변환 → 레시피로 저장하면 자산이 됩니다. "
        "사전에 없던 표현은 '새 어휘 후보'로 모아 vocab 보완에 씁니다."
    )

    vocab = _load_vocab()
    presets = suno_studio.list_presets(vocab)

    c1, c2 = st.columns([1, 1])
    with c1:
        preset_key = st.selectbox(
            "나라/장르 프리셋", options=[k for k, _ in presets],
            format_func=lambda k: dict(presets)[k], key="rev_preset",
        )
    with c2:
        source_id = st.text_input("영상 URL 또는 ID (자산 연결용, 선택)", key="rev_src")

    title = st.text_input("제목", key="rev_title")
    cc = st.columns([1, 1])
    with cc[0]:
        channel = st.text_input("채널명 (선택)", key="rev_channel")
    with cc[1]:
        tags = st.text_input("태그 (쉼표로 구분, 선택)", key="rev_tags")
    description = st.text_area("설명 (선택)", key="rev_desc", height=80)
    comments = st.text_area("상위 댓글 (한 줄에 하나, 선택)", key="rev_comments", height=100)

    key = st.text_input(
        "Gemini API 키", type="password",
        value=os.getenv("GEMINI_API_KEY", ""), key="rev_key",
        help=".env 의 GEMINI_API_KEY 를 기본값으로 불러옵니다. 키는 저장/커밋되지 않습니다.",
    )
    model = st.text_input("모델 ID", value=analyzer.DEFAULT_MODEL, key="rev_model")

    if st.button("🔎 분석하기", key="rev_run"):
        if not title.strip():
            st.warning("최소한 제목은 입력해주세요.")
        elif not key.strip():
            st.warning("Gemini API 키가 필요합니다. (.env 의 GEMINI_API_KEY 또는 위 입력)")
        else:
            meta = {
                "title": title.strip(),
                "channel": channel.strip(),
                "tags": [t.strip() for t in tags.split(",") if t.strip()],
                "description": description.strip(),
                "comments": [c.strip() for c in comments.splitlines() if c.strip()],
            }
            try:
                with st.spinner("Gemini 분석 중..."):
                    result = analyzer.analyze_metadata(
                        meta, vocab, preset_hint=preset_key,
                        api_key=key.strip(), model=model.strip() or analyzer.DEFAULT_MODEL,
                    )
                st.session_state["rev_result"] = result
            except Exception as e:
                st.error(f"분석 실패: {type(e).__name__}: {e}")

    result = st.session_state.get("rev_result")
    if result:
        st.markdown("**📋 추출된 Suno 프롬프트**")
        prompt = suno_studio.picks_to_prompt(vocab, result["preset"], result["picks"])
        st.code(prompt, language=None)
        meta_cols = st.columns(3)
        meta_cols[0].metric("무드", result.get("mood") or "-")
        meta_cols[1].metric("BPM", result.get("bpm") or "-")
        meta_cols[2].metric("프리셋", result["preset"])
        if result.get("rationale"):
            st.caption(f"근거: {result['rationale']}")

        new_terms = result.get("new_terms") or {}
        if new_terms:
            st.markdown("**🧩 새 어휘 후보 (vocab 보완용)**")
            st.caption("아래 표현들은 사전에 없어 picks 에 미반영되었습니다. 검토 후 vocab.json 에 추가하세요.")
            st.json(new_terms)

        rname = st.text_input("레시피 이름", key="rev_rcp_name",
                              placeholder="예: 비오는밤 색소폰 트로트")
        if st.button("💾 이 결과를 레시피로 저장", key="rev_rcp_save"):
            rec = recipes.save_recipe(
                rname or (title.strip() or "역설계 레시피"),
                result["preset"], result["picks"],
                bpm=result.get("bpm"),
                source_video_id=source_id.strip() or None,
                notes=result.get("rationale", ""),
            )
            st.success(f"저장됨: {rec['name']}  (스튜디오 탭에서 변주·블렌딩 가능)")


def render_review_tab() -> None:
    st.subheader("🙋 검수 큐 (합산 상위 후보)")
    st.caption(
        "오케스트레이터(orchestrator.py)가 매일 쌓은 정량+정성 합산 상위 후보입니다. "
        "승인하면 역설계 분석 → 레시피로 보내 생성 자산에 편입합니다."
    )

    db_path = st.text_input("데이터 토대 DB 경로", value=str(store.DB_PATH), key="rv_db")
    if not os.path.exists(db_path):
        st.info("DB 가 아직 없습니다. 먼저 `python orchestrator.py --once --keywords ...` 로 "
                "수집·채점하세요.")
        return

    try:
        cands = scorer.ranked_candidates(limit=30, db_path=db_path)
    except Exception as e:
        st.error(f"랭킹 조회 실패: {e}")
        return
    if not cands:
        st.info("합산 후보가 없습니다 (정량+정성이 모두 매겨진 영상 필요). "
                "orchestrator 로 collect→score 를 먼저 돌리세요.")
        return

    key = st.text_input(
        "Gemini API 키 (역설계용)", type="password",
        value=os.getenv("GEMINI_API_KEY", ""), key="rv_key",
        help=".env 의 GEMINI_API_KEY 기본값. 키는 저장/커밋되지 않습니다.",
    )
    vocab = _load_vocab()
    decisions = store.latest_reviews("video", path=db_path)
    badge = {"approved": "✅ 승인됨", "rejected": "❌ 반려됨"}

    st.divider()
    for c in cands:
        vid = c["video_id"]
        status = decisions.get(vid, "")
        with st.container(border=True):
            head = f"**[{(c.get('total_score') or 0):.1f}]** {c.get('title','')}"
            if status:
                head += f"  ·  {badge.get(status, status)}"
            st.markdown(head)
            st.caption(
                f"{c.get('channel_title','')}  ·  정량 {c.get('quant_score')} · "
                f"정성 {c.get('qual_score')} · {c.get('mood')} · {c.get('emotion_summary','')}"
            )
            cols = st.columns([1, 1, 2])
            if cols[0].button("✅ 승인", key=f"rv_appr_{vid}"):
                store.add_review(item_type="video", item_id=vid, decision="approved",
                                 path=db_path)
                st.rerun()
            if cols[1].button("❌ 반려", key=f"rv_rej_{vid}"):
                store.add_review(item_type="video", item_id=vid, decision="rejected",
                                 path=db_path)
                st.rerun()
            if cols[2].button("🔎 역설계 → 레시피 저장", key=f"rv_rev_{vid}"):
                if not key.strip():
                    st.warning("역설계에는 Gemini API 키가 필요합니다.")
                else:
                    video = store.get_video(vid, path=db_path) or {}
                    comments = [cc["text"] for cc in store.get_comments(vid, path=db_path)
                                if cc.get("text")]
                    meta = {
                        "title": video.get("title", ""),
                        "channel": video.get("channel_title", ""),
                        "description": video.get("description", ""),
                        "comments": comments,
                    }
                    try:
                        with st.spinner("Gemini 역설계 분석 중..."):
                            result = analyzer.analyze_metadata(
                                meta, vocab, api_key=key.strip())
                        rec = recipes.save_recipe(
                            video.get("title", "") or vid, result["preset"],
                            result["picks"], bpm=result.get("bpm"),
                            source_video_id=vid, notes=result.get("rationale", ""),
                        )
                        store.add_review(item_type="video", item_id=vid,
                                         decision="approved",
                                         note=f"recipe:{rec['id']}", path=db_path)
                        st.success(f"레시피 저장됨: {rec['name']} — 스튜디오 탭에서 변주·블렌딩 가능")
                        if result.get("new_terms"):
                            st.caption(f"새 어휘 후보(보완): {result['new_terms']}")
                    except Exception as e:
                        st.error(f"역설계 실패: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 채널·영상 분석 탭
# ---------------------------------------------------------------------------

def render_channel_analysis_tab() -> None:
    """채널 URL 또는 채널 ID로 채널 통계·영상 목록·조회 추이를 분석한다."""
    st.caption("채널 URL 또는 영상 URL을 입력하면 채널 통계, 인기 영상, 조회 추이를 한눈에 볼 수 있습니다.")

    api_key = (
        st.session_state.get("yt_api_key_input", "")
        or os.getenv("YOUTUBE_API_KEY", "")
        or SAVED_KEYS.get("youtube", "")
    )
    if not api_key:
        st.warning("YouTube API 키가 필요합니다. 레퍼런스 발굴 탭 사이드바에서 저장해주세요.")
        return

    # ── 입력 ──────────────────────────────────────────────────
    url_input = st.text_input(
        "채널 URL 또는 영상 URL 입력",
        placeholder="예: https://www.youtube.com/@channelname  또는  https://youtu.be/xxxxx",
        key="ca_url",
    )
    col_a, col_b = st.columns([2, 1])
    max_videos = col_a.slider("분석할 최근 영상 수", 10, 50, 20, step=5, key="ca_max_vid")
    run_btn = col_b.button("📊 분석 시작", type="primary", key="ca_run", use_container_width=True)

    if not run_btn:
        if "ca_result" not in st.session_state:
            st.info("채널 URL 또는 영상 URL을 입력하고 **분석 시작**을 눌러주세요.")
        # 이전 결과가 있으면 아래서 계속 표시됨
    else:
        if not url_input.strip():
            st.warning("URL을 입력해주세요.")
            return

        def _extract_channel_id(url: str, youtube) -> str | None:
            """URL에서 채널 ID를 추출. 영상 URL이면 해당 채널 ID를 반환."""
            import re as _re
            # 영상 URL
            vm = _re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
            if vm:
                vid_id = vm.group(1)
                resp = youtube.videos().list(part="snippet", id=vid_id).execute()
                items = resp.get("items", [])
                return items[0]["snippet"]["channelId"] if items else None
            # @handle
            hm = _re.search(r"@([\w.-]+)", url)
            if hm:
                resp = youtube.search().list(
                    part="snippet", q=f"@{hm.group(1)}", type="channel", maxResults=1
                ).execute()
                items = resp.get("items", [])
                return items[0]["snippet"]["channelId"] if items else None
            # /channel/ID
            cm = _re.search(r"/channel/([A-Za-z0-9_-]+)", url)
            if cm:
                return cm.group(1)
            # /c/ or /user/
            sm = _re.search(r"(?:/c/|/user/)([^/?&]+)", url)
            if sm:
                resp = youtube.search().list(
                    part="snippet", q=sm.group(1), type="channel", maxResults=1
                ).execute()
                items = resp.get("items", [])
                return items[0]["snippet"]["channelId"] if items else None
            return None

        try:
            from googleapiclient.discovery import build as yt_build  # type: ignore
            youtube = yt_build("youtube", "v3", developerKey=api_key)

            with st.spinner("채널 정보 가져오는 중..."):
                channel_id = _extract_channel_id(url_input.strip(), youtube)
                if not channel_id:
                    st.error("채널을 찾을 수 없습니다. URL을 확인해주세요.")
                    return

                # 채널 기본 정보
                ch_resp = youtube.channels().list(
                    part="snippet,statistics,brandingSettings",
                    id=channel_id,
                ).execute()
                ch_items = ch_resp.get("items", [])
                if not ch_items:
                    st.error("채널 정보를 불러올 수 없습니다.")
                    return
                ch = ch_items[0]
                ch_snip = ch.get("snippet", {})
                ch_stats = ch.get("statistics", {})

                # 최근 영상 목록
                search_resp = youtube.search().list(
                    part="id",
                    channelId=channel_id,
                    order="date",
                    type="video",
                    maxResults=max_videos,
                ).execute()
                vid_ids = [it["id"]["videoId"] for it in search_resp.get("items", [])]

                vid_details: list[dict] = []
                if vid_ids:
                    vd_resp = youtube.videos().list(
                        part="snippet,statistics,contentDetails",
                        id=",".join(vid_ids),
                    ).execute()
                    vid_details = vd_resp.get("items", [])

            st.session_state["ca_result"] = {
                "channel_id": channel_id,
                "ch_snip": ch_snip,
                "ch_stats": ch_stats,
                "vid_details": vid_details,
            }
        except Exception as e:
            st.error(f"오류: {e}")
            return

    result = st.session_state.get("ca_result")
    if not result:
        return

    ch_snip = result["ch_snip"]
    ch_stats = result["ch_stats"]
    vid_details = result["vid_details"]

    # ── 채널 헤더 ──────────────────────────────────────────────
    st.divider()
    hcol1, hcol2 = st.columns([1, 4])
    thumb_url = (ch_snip.get("thumbnails") or {}).get("medium", {}).get("url", "")
    if thumb_url:
        hcol1.image(thumb_url, width=100)
    with hcol2:
        st.markdown(f"## {ch_snip.get('title', '채널명 없음')}")
        st.caption(ch_snip.get("description", "")[:200])

    # ── 채널 통계 카드 ─────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("구독자수", f"{int(ch_stats.get('subscriberCount') or 0):,}")
    m2.metric("총 조회수", f"{int(ch_stats.get('viewCount') or 0):,}")
    m3.metric("영상 수", f"{int(ch_stats.get('videoCount') or 0):,}")
    avg_views = (
        int(ch_stats.get("viewCount") or 0) // max(int(ch_stats.get("videoCount") or 1), 1)
    )
    m4.metric("영상당 평균 조회", f"{avg_views:,}")

    if not vid_details:
        st.info("분석할 영상이 없습니다.")
        return

    # ── 영상 데이터프레임 ──────────────────────────────────────
    rows = []
    for item in vid_details:
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        vid_id = item["id"]
        pub = snip.get("publishedAt", "")[:10]
        view = int(stats.get("viewCount") or 0)
        like = int(stats.get("likeCount") or 0)
        comment = int(stats.get("commentCount") or 0)
        subs = int(ch_stats.get("subscriberCount") or 1)
        rows.append({
            "thumbnail": (snip.get("thumbnails") or {}).get("medium", {}).get("url", ""),
            "제목": snip.get("title", ""),
            "업로드일": pub,
            "조회수": view,
            "좋아요": like,
            "댓글": comment,
            "조회/구독(배)": round(view / max(subs, 1), 2),
            "좋아요율(%)": round(like / max(view, 1) * 100, 2),
            "url": f"https://www.youtube.com/watch?v={vid_id}",
        })
    df_vids = pd.DataFrame(rows)

    # ── 조회수 추이 차트 ───────────────────────────────────────
    st.markdown("### 📈 최근 영상 조회수 추이")
    chart_df = df_vids[["업로드일", "조회수"]].copy()
    chart_df["업로드일"] = pd.to_datetime(chart_df["업로드일"])
    chart_df = chart_df.sort_values("업로드일")
    st.line_chart(chart_df.set_index("업로드일")["조회수"])

    # ── 인기 영상 TOP 5 썸네일 ────────────────────────────────
    st.markdown("### 🏆 인기 영상 TOP 5")
    top5 = df_vids.nlargest(5, "조회수")
    t_cols = st.columns(5)
    for col, (_, r) in zip(t_cols, top5.iterrows()):
        with col:
            if r["thumbnail"]:
                st.image(r["thumbnail"], use_container_width=True)
            title = r["제목"]
            st.markdown(
                f"**[{title[:28]}{'…' if len(title) > 28 else ''}]({r['url']})**"
            )
            st.caption(f"👁 {int(r['조회수']):,}")

    # ── 전체 영상 테이블 ───────────────────────────────────────
    st.markdown("### 📋 전체 영상 목록")
    sort_col = st.selectbox(
        "정렬 기준",
        ["조회수", "좋아요", "댓글", "조회/구독(배)", "좋아요율(%)", "업로드일"],
        key="ca_sort",
    )
    df_show = df_vids.sort_values(sort_col, ascending=False).reset_index(drop=True)
    st.dataframe(
        df_show.drop(columns=["url"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "thumbnail": st.column_config.ImageColumn("썸네일"),
            "제목": st.column_config.TextColumn("제목", width="large"),
            "조회수": st.column_config.NumberColumn("조회수", format="%d"),
            "좋아요": st.column_config.NumberColumn("좋아요", format="%d"),
            "댓글": st.column_config.NumberColumn("댓글", format="%d"),
            "조회/구독(배)": st.column_config.NumberColumn("조회/구독(배)", format="%.2f"),
            "좋아요율(%)": st.column_config.NumberColumn("좋아요율(%)", format="%.2f%%"),
        },
    )

    # ── 요약 인사이트 ─────────────────────────────────────────
    with st.expander("💡 채널 인사이트 요약"):
        top_vid = df_vids.loc[df_vids["조회수"].idxmax()]
        avg_v = int(df_vids["조회수"].mean())
        avg_like = round(df_vids["좋아요율(%)"].mean(), 2)
        st.markdown(
            f"- 분석 영상 **{len(df_vids)}개** 평균 조회수: **{avg_v:,}**\n"
            f"- 평균 좋아요율: **{avg_like}%**\n"
            f"- 최고 조회 영상: **{top_vid['제목'][:50]}** ({int(top_vid['조회수']):,}회)\n"
            f"- 조회/구독 최고: **{df_vids['조회/구독(배)'].max():.2f}배**"
        )

    st.download_button(
        "📥 CSV 다운로드",
        data=df_show.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"channel_analysis_{datetime.now():%Y%m%d_%H%M%S}.csv",
        mime="text/csv",
        key="ca_csv",
    )


# ---------------------------------------------------------------------------
# 스톡 미디어 (Pexels)
# ---------------------------------------------------------------------------

def _pexels_search(api_key: str, query: str, media_type: str, per_page: int = 20, page: int = 1) -> dict:
    import urllib.request as _ur
    import urllib.parse as _up
    base = "https://api.pexels.com/videos/search" if media_type == "video" else "https://api.pexels.com/v1/search"
    url = f"{base}?query={_up.quote(query)}&per_page={per_page}&page={page}"
    req = _ur.Request(url, headers={"Authorization": api_key})
    with _ur.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def render_stock_media_tab() -> None:
    """Pexels 스톡 이미지·동영상 검색 및 미리보기."""
    st.title("📸 스톡 미디어")
    st.caption("Pexels에서 무료 스톡 이미지·동영상을 검색하고 채널 배경으로 활용하세요.")

    api_key = os.getenv("PEXELS_API_KEY") or SAVED_KEYS.get("pexels", "")
    if not api_key:
        st.warning(
            "Pexels API 키가 필요합니다. **🔑 API 연결** 메뉴에서 키를 저장해주세요.\n\n"
            "무료 발급: [www.pexels.com/api](https://www.pexels.com/api)"
        )
        return

    # ── 검색 설정 ──────────────────────────────────────────────
    with st.container(border=True):
        col_q, col_type, col_n = st.columns([3, 1, 1])
        query = col_q.text_input(
            "🔎 검색어",
            placeholder="예: rain cafe, lofi music, nature landscape",
            key="pex_query",
            label_visibility="collapsed",
        )
        media_type = col_type.radio(
            "유형", ["이미지", "동영상"], horizontal=True, key="pex_type"
        )
        per_page = col_n.selectbox("개수", [12, 20, 40], index=1, key="pex_per_page")
        run = st.button("📸 검색", type="primary", key="pex_run", use_container_width=False)

    if not run and "pex_result" not in st.session_state:
        st.info("검색어를 입력하고 **📸 검색** 버튼을 눌러주세요.")
        return

    if run:
        if not query.strip():
            st.warning("검색어를 입력해주세요.")
            return
        _type = "video" if media_type == "동영상" else "photo"
        with st.spinner(f"Pexels에서 {media_type} 검색 중..."):
            try:
                data = _pexels_search(api_key, query.strip(), _type, per_page)
                st.session_state["pex_result"] = {"data": data, "type": _type, "query": query}
            except Exception as e:
                st.error(f"검색 오류: {e}")
                return

    result = st.session_state.get("pex_result")
    if not result:
        return

    data   = result["data"]
    _type  = result["type"]
    _query = result["query"]

    # ── 결과 헤더 ──────────────────────────────────────────────
    total = data.get("total_results", 0)
    st.caption(f"**'{_query}'** 검색 결과 총 **{total:,}개** 중 {len(data.get('photos' if _type == 'photo' else 'videos', []))}개 표시")
    st.divider()

    # ── 이미지 그리드 ──────────────────────────────────────────
    if _type == "photo":
        items = data.get("photos", [])
        COLS = 4
        for i in range(0, len(items), COLS):
            cols = st.columns(COLS)
            for col, item in zip(cols, items[i:i+COLS]):
                with col:
                    thumb = item["src"]["medium"]
                    original = item["src"]["original"]
                    photographer = item.get("photographer", "")
                    pexels_url = item.get("url", "")
                    st.image(thumb, use_container_width=True)
                    st.caption(f"📷 {photographer}")
                    c1, c2 = st.columns(2)
                    c1.markdown(f"[원본]({original})")
                    c2.markdown(f"[Pexels]({pexels_url})")

    # ── 동영상 그리드 ──────────────────────────────────────────
    else:
        items = data.get("videos", [])
        COLS = 3
        for i in range(0, len(items), COLS):
            cols = st.columns(COLS)
            for col, item in zip(cols, items[i:i+COLS]):
                with col:
                    with st.container(border=True):
                        # 썸네일 이미지
                        thumb = item.get("image", "")
                        if thumb:
                            st.image(thumb, use_container_width=True)

                        duration = item.get("duration", 0)
                        mins, secs = divmod(int(duration), 60)
                        user = item.get("user", {}).get("name", "")
                        pexels_url = item.get("url", "")

                        st.caption(f"⏱ {mins}:{secs:02d}  |  📹 {user}")

                        # 최적 파일 선택 (HD 우선)
                        files = sorted(
                            item.get("video_files", []),
                            key=lambda f: f.get("width", 0),
                            reverse=True,
                        )
                        hd_file = next((f for f in files if f.get("quality") in ("hd", "sd")), None)
                        if hd_file:
                            dl_url = hd_file.get("link", "")
                            w = hd_file.get("width", 0)
                            h = hd_file.get("height", 0)
                            st.markdown(f"[▶ 재생/다운로드 ({w}×{h})]({dl_url})")
                        st.markdown(f"[Pexels 페이지]({pexels_url})")


# ---------------------------------------------------------------------------
# 레퍼런스 채널 모니터
# ---------------------------------------------------------------------------

_REF_CHANNELS_FILE = pathlib.Path(__file__).parent / "reference_channels.json"

# Suno 제작 목적 기본 카테고리
_REF_CATEGORIES = [
    "K-팝 / 아이돌", "트로트", "발라드", "K-인디", "한국 R&B·힙합",
    "동요·키즈", "Lo-fi·카페", "재즈", "클래식·뉴에이지",
    "시티팝·J-팝", "팝·EDM", "직접 입력",
]


def _load_ref_channels() -> list[dict]:
    if _REF_CHANNELS_FILE.exists():
        try:
            return json.loads(_REF_CHANNELS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_ref_channels(channels: list[dict]) -> None:
    _REF_CHANNELS_FILE.write_text(
        json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _resolve_channel_id(url: str, youtube) -> tuple[str, str]:
    """URL/핸들 → (channel_id, channel_title). 실패 시 ('', '')."""
    import re as _re
    # 영상 URL
    vm = _re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if vm:
        r = youtube.videos().list(part="snippet", id=vm.group(1)).execute()
        items = r.get("items", [])
        if items:
            snip = items[0]["snippet"]
            return snip["channelId"], snip["channelTitle"]
    # @handle
    hm = _re.search(r"@([\w.-]+)", url)
    if hm:
        r = youtube.search().list(part="snippet", q=f"@{hm.group(1)}", type="channel", maxResults=1).execute()
        items = r.get("items", [])
        if items:
            s = items[0]["snippet"]
            return s["channelId"], s["channelTitle"]
    # /channel/ID
    cm = _re.search(r"/channel/([A-Za-z0-9_-]+)", url)
    if cm:
        cid = cm.group(1)
        r = youtube.channels().list(part="snippet", id=cid).execute()
        items = r.get("items", [])
        if items:
            return cid, items[0]["snippet"]["title"]
    # 직접 channel ID
    if _re.match(r"^UC[A-Za-z0-9_-]{22}$", url.strip()):
        cid = url.strip()
        r = youtube.channels().list(part="snippet", id=cid).execute()
        items = r.get("items", [])
        if items:
            return cid, items[0]["snippet"]["title"]
    return "", ""


def _fetch_channel_latest(youtube, channel_id: str, max_videos: int = 10) -> list[dict]:
    """채널의 최신 영상 목록 + 통계 반환."""
    try:
        s_resp = youtube.search().list(
            part="id", channelId=channel_id, order="date",
            type="video", maxResults=max_videos,
        ).execute()
        vid_ids = [it["id"]["videoId"] for it in s_resp.get("items", [])]
        if not vid_ids:
            return []
        v_resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(vid_ids),
        ).execute()
        rows = []
        for item in v_resp.get("items", []):
            snip  = item.get("snippet", {})
            stats = item.get("statistics", {})
            rows.append({
                "video_id":      item["id"],
                "title":         snip.get("title", ""),
                "thumbnail":     (snip.get("thumbnails") or {}).get("medium", {}).get("url", ""),
                "published_at":  snip.get("publishedAt", "")[:16].replace("T", " "),
                "view_count":    int(stats.get("viewCount") or 0),
                "like_count":    int(stats.get("likeCount") or 0),
                "comment_count": int(stats.get("commentCount") or 0),
                "video_url":     f"https://www.youtube.com/watch?v={item['id']}",
                "fetched_at":    datetime.utcnow().strftime("%Y-%m-%d"),
            })
        return rows
    except Exception:
        return []


def render_reference_monitor_tab() -> None:
    """레퍼런스 채널 모니터 — 채널 저장·카테고리 분류·최신 업로드 대시보드."""

    api_key = (
        st.session_state.get("yt_api_key_input", "")
        or os.getenv("YOUTUBE_API_KEY", "")
        or SAVED_KEYS.get("youtube", "")
    )

    channels = _load_ref_channels()

    sub_manage, sub_dashboard = st.tabs(["⚙️ 채널 관리", "📊 업로드 대시보드"])

    # ── 채널 관리 탭 ──────────────────────────────────────────
    with sub_manage:
        st.markdown("### 채널 추가")
        st.caption(f"현재 저장된 채널: **{len(channels)}개** (권장 최대 50개)")

        with st.container(border=True):
            new_url = st.text_input(
                "채널 URL / @핸들 / 채널ID",
                placeholder="예: @채널명  또는  https://www.youtube.com/@...",
                key="rm_new_url",
            )

            st.markdown("**카테고리** — 아래에서 클릭하거나 직접 입력")
            # 빠른 선택 버튼 (직접 입력 제외)
            preset_cols = st.columns(6)
            quick_cats = [c for c in _REF_CATEGORIES if c != "직접 입력"]
            for i, cat in enumerate(quick_cats):
                if preset_cols[i % 6].button(cat, key=f"qcat_{i}", use_container_width=True):
                    st.session_state["rm_cat_input"] = cat

            # 카테고리 텍스트 입력 (자유 입력)
            cat_input = st.text_input(
                "카테고리 입력",
                value=st.session_state.get("rm_cat_input", ""),
                placeholder="위에서 클릭하거나 직접 입력 (예: 샹송, 동요, 뉴에이지)",
                key="rm_cat_input",
                label_visibility="collapsed",
            )

            add_btn = st.button("➕ 채널 추가", type="primary", key="rm_add")

        if add_btn:
            if not api_key:
                st.error("YouTube API 키가 필요합니다. 🔑 API 연결 메뉴에서 저장해주세요.")
            elif not new_url.strip():
                st.warning("채널 URL을 입력해주세요.")
            elif not cat_input.strip():
                st.warning("카테고리를 선택하거나 입력해주세요.")
            elif len(channels) >= 80:
                st.warning("최대 80개 채널까지 저장 가능합니다.")
            else:
                from googleapiclient.discovery import build as yt_build  # type: ignore
                youtube = yt_build("youtube", "v3", developerKey=api_key)
                with st.spinner("채널 정보 확인 중..."):
                    cid, ctitle = _resolve_channel_id(new_url.strip(), youtube)
                if not cid:
                    st.error("채널을 찾을 수 없습니다. URL을 확인해주세요.")
                elif any(c["channel_id"] == cid for c in channels):
                    st.warning(f"이미 저장된 채널입니다: {ctitle}")
                else:
                    final_cat = cat_input.strip()
                    channels.append({
                        "channel_id": cid,
                        "channel_title": ctitle,
                        "category": final_cat or "기타",
                        "added_at": datetime.utcnow().strftime("%Y-%m-%d"),
                    })
                    _save_ref_channels(channels)
                    st.success(f"✅ 추가됨: **{ctitle}** → [{final_cat or '기타'}]")
                    st.rerun()

        # 카테고리별 채널 목록
        st.divider()
        st.markdown("### 저장된 채널 목록")
        if not channels:
            st.info("아직 저장된 채널이 없습니다. 위에서 채널을 추가해보세요.")
        else:
            cats = sorted(set(c["category"] for c in channels))
            for cat in cats:
                cat_channels = [c for c in channels if c["category"] == cat]
                with st.expander(f"**{cat}** ({len(cat_channels)}개)", expanded=True):
                    for ch in cat_channels:
                        col_t, col_d, col_del = st.columns([4, 2, 1])
                        col_t.markdown(
                            f"[{ch['channel_title']}](https://www.youtube.com/channel/{ch['channel_id']})"
                        )
                        col_d.caption(f"추가일: {ch.get('added_at','')}")
                        if col_del.button("🗑️", key=f"del_{ch['channel_id']}"):
                            channels = [c for c in channels if c["channel_id"] != ch["channel_id"]]
                            _save_ref_channels(channels)
                            st.rerun()

    # ── 업로드 대시보드 탭 ────────────────────────────────────
    with sub_dashboard:
        if not channels:
            st.info("먼저 **⚙️ 채널 관리** 탭에서 채널을 추가해주세요.")
            return

        # ── 자동 수집 데이터 확인 ──────────────────────────────
        _latest_file   = pathlib.Path(__file__).parent / "ref_data" / "latest.json"
        _history_file  = pathlib.Path(__file__).parent / "ref_data" / "history.json"
        auto_data: dict = {}
        if _latest_file.exists():
            try:
                auto_data = json.loads(_latest_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if auto_data:
            collected_at = auto_data.get("collected_at", "")
            st.success(f"🤖 GitHub Actions 자동 수집 데이터  ·  마지막 수집: **{collected_at}**")
        else:
            st.info("💡 자동 수집 데이터가 없습니다. GitHub Actions 설정 후 매일 자동 수집됩니다. 지금은 아래 **수동 새로고침**을 사용하세요.")

        # 조회수 추이 (history.json)
        history_data: list = []
        if _history_file.exists():
            try:
                history_data = json.loads(_history_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        # ── 필터 ──────────────────────────────────────────────
        all_cats = ["전체"] + sorted(set(c["category"] for c in channels))
        col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
        cat_filter = col_f1.selectbox("카테고리 필터", all_cats, key="rm_dash_cat")
        max_vid    = col_f2.selectbox("채널당 영상 수", [5, 10, 20], index=1, key="rm_dash_n")
        refresh_btn = col_f3.button("🔄 수동 새로고침", type="secondary", key="rm_refresh", use_container_width=True)

        filtered_channels = (
            channels if cat_filter == "전체"
            else [c for c in channels if c["category"] == cat_filter]
        )

        # 자동 수집 데이터 → session_state에 로드
        if auto_data and "rm_dashboard_data" not in st.session_state:
            st.session_state["rm_dashboard_data"] = {
                cid: ch_data["videos"]
                for cid, ch_data in auto_data.get("channels", {}).items()
            }
            st.session_state["rm_dashboard_channels"] = channels

        # 수동 새로고침
        if refresh_btn:
            if not api_key:
                st.warning("YouTube API 키가 필요합니다. 🔑 API 연결 메뉴에서 저장해주세요.")
            else:
                from googleapiclient.discovery import build as yt_build  # type: ignore
                youtube = yt_build("youtube", "v3", developerKey=api_key)
                data_new: dict[str, list] = {}
                prog = st.progress(0, text="채널 데이터 수집 중...")
                for i, ch in enumerate(filtered_channels):
                    prog.progress((i + 1) / max(len(filtered_channels), 1),
                                  text=f"수집 중: {ch['channel_title']}")
                    data_new[ch["channel_id"]] = _fetch_channel_latest(youtube, ch["channel_id"], max_vid)
                prog.empty()
                st.session_state["rm_dashboard_data"] = data_new
                st.session_state["rm_dashboard_channels"] = filtered_channels

        data        = st.session_state.get("rm_dashboard_data", {})
        dash_channels = st.session_state.get("rm_dashboard_channels", filtered_channels)

        # 카테고리 필터 적용
        if cat_filter != "전체":
            dash_channels = [c for c in dash_channels if c["category"] == cat_filter]

        if not data:
            st.info("🔄 수동 새로고침 버튼을 눌러 데이터를 불러오세요.")
            return

        # ── 상단 요약 통계 ────────────────────────────────────
        total_vids = sum(len(data.get(c["channel_id"], [])) for c in dash_channels)
        active_chs = sum(1 for c in dash_channels if data.get(c["channel_id"]))
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("📡 모니터링 채널", f"{active_chs}개")
        s2.metric("🎬 수집된 영상", f"{total_vids}개")
        all_views = sum(
            v["view_count"]
            for c in dash_channels
            for v in data.get(c["channel_id"], [])
        )
        s3.metric("👁 총 조회수", f"{all_views:,}")
        collected_at = auto_data.get("collected_at", "수동 수집") if auto_data else "수동 수집"
        s4.metric("🕐 마지막 수집", collected_at[:10] if collected_at else "-")

        st.divider()

        # 조회수 추이 차트 (history 있을 때만)
        if history_data and len(history_data) >= 2:
            with st.expander("📈 조회수 추이 (최근 30일)", expanded=False):
                import pandas as _pd2
                chart_rows = []
                for h in history_data:
                    for cid, s in h.get("summary", {}).items():
                        chart_rows.append({"날짜": h["date"], "채널": s["channel_title"],
                                           "조회수": s.get("latest_views", 0)})
                if chart_rows:
                    df_chart = _pd2.DataFrame(chart_rows)
                    df_pivot = df_chart.pivot(index="날짜", columns="채널", values="조회수").fillna(0)
                    st.line_chart(df_pivot)

        # ── 카테고리 탭 분류 ──────────────────────────────────
        cats_in_data = ["전체"] + sorted(set(
            c["category"] for c in dash_channels if data.get(c["channel_id"])
        ))
        cat_tabs = st.tabs(cats_in_data)

        def _render_channel_cards(ch_list: list) -> None:
            for ch in ch_list:
                videos = data.get(ch["channel_id"], [])
                if not videos:
                    continue
                latest   = videos[0]
                avg_views = int(sum(v["view_count"] for v in videos) / max(len(videos), 1))
                max_views = max(v["view_count"] for v in videos)

                # ── 채널 헤더 ─────────────────────────────────
                st.markdown(f"""
<div style="background:linear-gradient(90deg,#1a1a2e,#16213e);
            border-radius:12px;padding:14px 18px;margin:12px 0 6px 0;
            border-left:4px solid #e74c3c;">
  <span style="font-size:17px;font-weight:800;color:#fff;">📺 {ch['channel_title']}</span>
  <span style="background:#333;color:#aaa;font-size:11px;border-radius:8px;
               padding:2px 8px;margin-left:8px;">{ch['category']}</span>
  <span style="color:#888;font-size:12px;margin-left:12px;">
    최신 업로드: {latest['published_at'][:10]}
  </span>
</div>
""", unsafe_allow_html=True)

                # ── 채널 메트릭 ───────────────────────────────
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                mc1.metric("최신 조회수",   f"{latest['view_count']:,}")
                mc2.metric("최신 좋아요",   f"{latest['like_count']:,}")
                mc3.metric("최신 댓글",     f"{latest['comment_count']:,}")
                mc4.metric("평균 조회수",   f"{avg_views:,}")
                mc5.metric("최고 조회수",   f"{max_views:,}")

                # ── 썸네일 카드 그리드 ────────────────────────
                COLS = 4
                for i in range(0, len(videos), COLS):
                    cols = st.columns(COLS)
                    for col, vid in zip(cols, videos[i:i+COLS]):
                        with col:
                            thumb = vid.get("thumbnail", "")
                            url   = vid.get("video_url", "#")
                            title = vid.get("title", "")
                            views = vid.get("view_count", 0)
                            likes = vid.get("like_count", 0)
                            cmts  = vid.get("comment_count", 0)
                            pub   = vid.get("published_at", "")[:10]

                            if thumb:
                                st.markdown(
                                    f'<a href="{url}" target="_blank">'
                                    f'<img src="{thumb}" style="width:100%;border-radius:8px;'
                                    f'margin-bottom:4px;transition:opacity .2s;">'
                                    f'</a>',
                                    unsafe_allow_html=True,
                                )
                            # 제목
                            st.markdown(
                                f'<a href="{url}" target="_blank" '
                                f'style="font-size:12px;font-weight:700;color:#fff;'
                                f'text-decoration:none;line-height:1.4;">'
                                f'{title[:38]}{"…" if len(title)>38 else ""}</a>',
                                unsafe_allow_html=True,
                            )
                            # 통계
                            like_rate = round(likes / max(views, 1) * 100, 1)
                            st.markdown(
                                f'<div style="font-size:11px;color:#aaa;margin-top:3px;">'
                                f'👁 {views:,} &nbsp;💬 {cmts:,} &nbsp;👍 {like_rate}%<br>'
                                f'📅 {pub}</div>',
                                unsafe_allow_html=True,
                            )
                st.divider()

        # 전체 탭
        with cat_tabs[0]:
            _render_channel_cards(dash_channels)

        # 카테고리별 탭
        for tab, cat in zip(cat_tabs[1:], cats_in_data[1:]):
            with tab:
                _render_channel_cards([c for c in dash_channels if c["category"] == cat])

        # 전체 CSV 다운로드
        all_rows = []
        for ch in dash_channels:
            for vid in data.get(ch["channel_id"], []):
                all_rows.append({**vid, "channel_title": ch["channel_title"], "category": ch["category"]})
        if all_rows:
            st.divider()
            st.download_button(
                "📥 전체 데이터 CSV 다운로드",
                data=pd.DataFrame(all_rows).to_csv(index=False).encode("utf-8-sig"),
                file_name=f"reference_monitor_{datetime.now():%Y%m%d}.csv",
                mime="text/csv",
            )


_MONEY_CODE_FILE = pathlib.Path(__file__).parent / "money_codes.json"


def _load_money_codes() -> list[dict]:
    if _MONEY_CODE_FILE.exists():
        try:
            return json.loads(_MONEY_CODE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_money_codes(codes: list[dict]) -> None:
    _MONEY_CODE_FILE.write_text(
        json.dumps(codes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def render_money_code_tab() -> None:
    """💰 머니코드 — 나만의 Suno 스타일 공식을 등록·관리·적용하는 탭."""

    st.markdown("""
<style>
.mc-card { background:linear-gradient(135deg,#1a1a2e,#16213e);
           border:1.5px solid #f0c040; border-radius:14px;
           padding:16px 18px; margin-bottom:12px; }
.mc-name { font-size:18px; font-weight:900; color:#f0c040; margin-bottom:4px; }
.mc-tags { background:#111; border-radius:8px; padding:8px 12px;
           font-size:12px; color:#7fff7f; font-family:monospace;
           word-break:break-all; margin:8px 0; }
.mc-desc { font-size:13px; color:#ccc; margin-top:4px; }
.mc-badge { display:inline-block; background:#e74c3c; color:#fff;
            font-size:10px; font-weight:700; border-radius:8px;
            padding:2px 8px; margin-right:4px; }
</style>
""", unsafe_allow_html=True)

    st.markdown("## 💰 머니코드")
    st.caption("검증된 나만의 Suno 스타일 공식을 저장해두고, 곡 생성 시 한 번에 적용하세요.")

    codes = _load_money_codes()

    # ── 새 머니코드 등록 ──────────────────────────────────────
    with st.expander("➕ 새 머니코드 등록", expanded=len(codes) == 0):
        with st.container(border=True):
            mc_name = st.text_input(
                "공식 이름 *",
                placeholder="예: 트로트 황금공식, 새벽감성 A, 드라이브 힙합",
                key="mc_new_name",
            )
            mc_tags = st.text_area(
                "Suno 스타일 태그 * (영문, Suno에 바로 붙여넣을 내용)",
                height=90,
                placeholder="예: trot, female vocal, emotional, piano, haegeum, reverb, 90 BPM, cinematic, warm",
                key="mc_new_tags",
            )
            mc_desc = st.text_input(
                "설명 (선택) — 언제 쓰는 공식인지",
                placeholder="예: 50~60대 타겟, 이별·그리움 테마, 조회수 높았던 스타일",
                key="mc_new_desc",
            )

            # 카테고리 빠른 선택
            st.markdown("**카테고리 (선택)**")
            mc_cat_presets = ["트로트","발라드","K-Pop","Lo-fi","드라이브","새벽감성","힐링","파티","명상","직접 입력"]
            mc_cat_cols = st.columns(5)
            for i, cat in enumerate(mc_cat_presets[:10]):
                if mc_cat_cols[i % 5].button(cat, key=f"mc_cat_{i}", use_container_width=True):
                    st.session_state["mc_new_cat_val"] = cat
            mc_cat = st.text_input(
                "카테고리",
                value=st.session_state.get("mc_new_cat_val", ""),
                key="mc_new_cat",
                label_visibility="collapsed",
                placeholder="카테고리 입력 또는 위에서 클릭",
            )

            # 고정 태그 (항상 포함)
            mc_fixed = st.text_input(
                "🔒 고정 태그 (곡 생성 시 항상 강제 포함)",
                placeholder="예: no rap, no spoken word, instrumental only",
                key="mc_new_fixed",
            )

            # 금지 태그
            mc_banned = st.text_input(
                "🚫 금지 태그 (이 키워드가 스타일에 들어가지 않도록 AI에 전달)",
                placeholder="예: metal, aggressive, fast tempo",
                key="mc_new_banned",
            )

            if st.button("💾 머니코드 저장", type="primary", use_container_width=True, key="mc_save"):
                if not mc_name.strip():
                    st.error("공식 이름을 입력해주세요.")
                elif not mc_tags.strip():
                    st.error("Suno 스타일 태그를 입력해주세요.")
                else:
                    # 중복 이름 체크
                    if any(c["name"] == mc_name.strip() for c in codes):
                        st.error(f"'{mc_name}' 이름이 이미 존재합니다. 다른 이름을 사용하세요.")
                    else:
                        codes.append({
                            "name":        mc_name.strip(),
                            "tags":        mc_tags.strip(),
                            "description": mc_desc.strip(),
                            "category":    mc_cat.strip(),
                            "fixed_tags":  mc_fixed.strip(),
                            "banned_tags": mc_banned.strip(),
                            "created_at":  datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "use_count":   0,
                        })
                        _save_money_codes(codes)
                        st.success(f"✅ '{mc_name}' 머니코드가 저장되었습니다!")
                        # 입력 초기화
                        for k in ["mc_new_name","mc_new_tags","mc_new_desc","mc_new_cat","mc_new_fixed","mc_new_banned","mc_new_cat_val"]:
                            st.session_state.pop(k, None)
                        st.rerun()

    st.divider()

    if not codes:
        st.info("아직 등록된 머니코드가 없습니다. 위에서 첫 번째 공식을 등록해보세요!")
        return

    # ── 필터 ─────────────────────────────────────────────────
    all_cats = ["전체"] + sorted(set(c.get("category","기타") or "기타" for c in codes))
    f1, f2 = st.columns([2, 2])
    cat_f   = f1.selectbox("카테고리 필터", all_cats, key="mc_filter_cat")
    sort_f  = f2.selectbox("정렬", ["최근 등록순","많이 쓴 순","이름순"], key="mc_filter_sort")

    filtered = [c for c in codes if cat_f == "전체" or c.get("category","기타") == cat_f]
    if sort_f == "많이 쓴 순":
        filtered = sorted(filtered, key=lambda x: x.get("use_count", 0), reverse=True)
    elif sort_f == "이름순":
        filtered = sorted(filtered, key=lambda x: x["name"])
    else:
        filtered = list(reversed(filtered))

    st.markdown(f"**{len(filtered)}개** 머니코드")
    st.divider()

    # ── 머니코드 카드 목록 ────────────────────────────────────
    for idx, code in enumerate(filtered):
        real_idx = codes.index(code)
        cat_label  = code.get("category","") or ""
        fixed_tags = code.get("fixed_tags","") or ""
        banned_tags= code.get("banned_tags","") or ""
        use_count  = code.get("use_count", 0)

        with st.container(border=True):
            h1, h2 = st.columns([7, 3])
            with h1:
                st.markdown(
                    f'<div class="mc-name">💰 {code["name"]}</div>'
                    + (f'<span class="mc-badge">{cat_label}</span>' if cat_label else "")
                    + (f'<div class="mc-desc">{code["description"]}</div>' if code.get("description") else ""),
                    unsafe_allow_html=True,
                )
            with h2:
                st.caption(f"사용 {use_count}회 · {code.get('created_at','')}")

            # 스타일 태그
            st.markdown("**🎨 스타일 태그**")
            st.markdown(f'<div class="mc-tags">{code["tags"]}</div>', unsafe_allow_html=True)

            # 고정/금지 태그
            if fixed_tags or banned_tags:
                t1, t2 = st.columns(2)
                if fixed_tags:
                    t1.markdown(f"🔒 **고정:** `{fixed_tags}`")
                if banned_tags:
                    t2.markdown(f"🚫 **금지:** `{banned_tags}`")

            # 액션 버튼
            b1, b2, b3, b4 = st.columns(4)

            # 복사용 코드
            b1.code(code["tags"], language=None)

            # Suno 곡 생성에 적용
            if b2.button("🎵 곡 생성에 적용", key=f"mc_apply_{idx}", use_container_width=True, type="primary"):
                st.session_state["sg_money_code"] = code
                codes[real_idx]["use_count"] = use_count + 1
                _save_money_codes(codes)
                st.session_state["nav_menu"] = "음악 만들기"
                st.toast(f"✅ '{code['name']}' 적용! Suno 곡 생성 탭으로 이동합니다.")
                st.rerun()

            # 편집
            if b3.button("✏️ 편집", key=f"mc_edit_{idx}", use_container_width=True):
                st.session_state[f"mc_editing_{real_idx}"] = True

            # 삭제
            if b4.button("🗑️ 삭제", key=f"mc_del_{idx}", use_container_width=True):
                st.session_state[f"mc_confirm_del_{real_idx}"] = True

            # 편집 폼
            if st.session_state.get(f"mc_editing_{real_idx}"):
                with st.container(border=True):
                    st.markdown("**✏️ 편집**")
                    e_tags = st.text_area("스타일 태그", value=code["tags"], key=f"mc_e_tags_{real_idx}", height=80)
                    e_desc = st.text_input("설명", value=code.get("description",""), key=f"mc_e_desc_{real_idx}")
                    e_fixed  = st.text_input("고정 태그", value=code.get("fixed_tags",""), key=f"mc_e_fixed_{real_idx}")
                    e_banned = st.text_input("금지 태그", value=code.get("banned_tags",""), key=f"mc_e_banned_{real_idx}")
                    ec1, ec2 = st.columns(2)
                    if ec1.button("💾 저장", key=f"mc_e_save_{real_idx}", use_container_width=True, type="primary"):
                        codes[real_idx]["tags"]        = e_tags.strip()
                        codes[real_idx]["description"] = e_desc.strip()
                        codes[real_idx]["fixed_tags"]  = e_fixed.strip()
                        codes[real_idx]["banned_tags"] = e_banned.strip()
                        _save_money_codes(codes)
                        st.session_state.pop(f"mc_editing_{real_idx}", None)
                        st.success("저장 완료!")
                        st.rerun()
                    if ec2.button("취소", key=f"mc_e_cancel_{real_idx}", use_container_width=True):
                        st.session_state.pop(f"mc_editing_{real_idx}", None)
                        st.rerun()

            # 삭제 확인
            if st.session_state.get(f"mc_confirm_del_{real_idx}"):
                st.warning(f"**'{code['name']}'** 을 삭제할까요?")
                dc1, dc2 = st.columns(2)
                if dc1.button("✅ 삭제 확인", key=f"mc_del_ok_{real_idx}", use_container_width=True, type="primary"):
                    codes.pop(real_idx)
                    _save_money_codes(codes)
                    st.session_state.pop(f"mc_confirm_del_{real_idx}", None)
                    st.rerun()
                if dc2.button("취소", key=f"mc_del_cancel_{real_idx}", use_container_width=True):
                    st.session_state.pop(f"mc_confirm_del_{real_idx}", None)
                    st.rerun()

    st.divider()

    # ── 전체 내보내기/가져오기 ────────────────────────────────
    col_ex, col_im = st.columns(2)
    with col_ex:
        st.download_button(
            "📥 전체 머니코드 내보내기 (JSON)",
            data=json.dumps(codes, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"money_codes_{datetime.now():%Y%m%d}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_im:
        up = st.file_uploader("📤 머니코드 JSON 가져오기", type="json", key="mc_import")
        if up:
            try:
                imported = json.loads(up.read().decode("utf-8"))
                existing_names = {c["name"] for c in codes}
                added = 0
                for ic in imported:
                    if ic.get("name") and ic["name"] not in existing_names:
                        codes.append(ic)
                        added += 1
                _save_money_codes(codes)
                st.success(f"✅ {added}개 머니코드를 가져왔습니다!")
                st.rerun()
            except Exception as e:
                st.error(f"가져오기 실패: {e}")


def render_suno_generator_tab() -> None:
    """Suno 곡 생성기 — 옵션 pills 선택 → AI가 10곡 가사+스타일 생성 → Suno 전송."""

    # ── 스타일 ─────────────────────────────────────────────────
    st.markdown("""
<style>
.sg-title { font-size:28px; font-weight:900; margin:0; }
.sg-sub   { font-size:14px; color:#888; margin-bottom:16px; }
.sg-step  { display:inline-block; background:#e74c3c; color:#fff;
            font-size:11px; font-weight:700; border-radius:12px;
            padding:3px 10px; margin-bottom:8px; }
.ref-banner { background:#fffbe6; border:1.5px solid #f0c040;
              border-radius:12px; padding:14px 18px; margin-bottom:18px; }
.song-card  { background:#f8f9fa; border-radius:10px; padding:14px 16px;
              margin-bottom:8px; border-left:4px solid #e74c3c; }
</style>
""", unsafe_allow_html=True)

    st.markdown('<div class="sg-title">🎵 음악 만들기</div>', unsafe_allow_html=True)
    st.markdown('<div class="sg-sub">플레이리스트 에이전트처럼 세밀하게 옵션을 골라 노래 10곡 만들기!</div>', unsafe_allow_html=True)

    gemini_key = os.getenv("GEMINI_API_KEY") or SAVED_KEYS.get("gemini", "")
    openai_key = os.getenv("OPENAI_API_KEY") or SAVED_KEYS.get("openai", "")
    if not gemini_key and not openai_key:
        st.warning("🔑 Gemini 또는 OpenAI API 키가 필요합니다. 왼쪽 메뉴 **API 연결**에서 키를 등록하세요.")

    # ── 머니코드 적용 배너 ────────────────────────────────────
    mc_applied = st.session_state.get("sg_money_code")
    if mc_applied:
        with st.container(border=True):
            st.markdown(
                f'<div style="background:linear-gradient(90deg,#1a1200,#2a2000);'
                f'border:1.5px solid #f0c040;border-radius:10px;padding:12px 16px;">'
                f'<span style="color:#f0c040;font-size:16px;font-weight:900;">💰 머니코드 적용 중: {mc_applied["name"]}</span><br>'
                f'<span style="color:#7fff7f;font-size:12px;font-family:monospace;">{mc_applied["tags"]}</span>'
                + (f'<br><span style="color:#aaa;font-size:11px;">🔒 고정: {mc_applied["fixed_tags"]}</span>' if mc_applied.get("fixed_tags") else "")
                + (f'&nbsp;&nbsp;<span style="color:#f88;font-size:11px;">🚫 금지: {mc_applied["banned_tags"]}</span>' if mc_applied.get("banned_tags") else "")
                + f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("❌ 머니코드 해제", key="sg_mc_clear"):
                st.session_state.pop("sg_money_code", None)
                st.rerun()
    else:
        mc_codes = _load_money_codes()
        if mc_codes:
            mc_names = ["선택 안 함"] + [c["name"] for c in mc_codes]
            mc_sel = st.selectbox("💰 머니코드 적용 (선택)", mc_names, key="sg_mc_select")
            if mc_sel != "선택 안 함":
                chosen = next(c for c in mc_codes if c["name"] == mc_sel)
                st.session_state["sg_money_code"] = chosen
                st.rerun()

    # ── 레퍼런스 채널 스타일 배너 ──────────────────────────────
    ref_channels = _load_ref_channels()
    if ref_channels:
        with st.container(border=False):
            st.markdown(
                f'<div class="ref-banner">'
                f'<b>💾 레퍼런스 채널 스타일로 만들기</b><br>'
                f'저장된 채널 <b>{len(ref_channels)}개</b>의 스타일을 분석해 자동으로 옵션을 채울 수 있어요.<br>'
                f'<small>📡 레퍼런스 기획 → 레퍼런스 분석 탭에서 채널을 분석·저장하면 그 채널의 장르·무드·BPM·스타일을 한 번에 적용할 수 있어요.</small>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("🔗 레퍼런스 분석하러 가기", key="sg_goto_ref"):
                st.session_state["nav_menu"] = "레퍼런스 채널"
                st.rerun()
    else:
        st.info("💡 **레퍼런스 채널 스타일로 만들기** — 레퍼런스 채널을 저장하면 그 채널의 장르·무드·스타일을 한 번에 적용할 수 있어요!")

    st.divider()

    # ══════════════════════════════════════════════════════════
    # STEP 1 : 음악 옵션 고르기
    # ══════════════════════════════════════════════════════════
    st.markdown('<span class="sg-step">🎛️ STEP 1 : 음악 옵션 고르기</span>', unsafe_allow_html=True)

    def _pills(label: str, options: list, key: str, default: list | None = None) -> list:
        """멀티 pills — st.pills multiselect 래퍼."""
        return st.pills(label, options, selection_mode="multi", default=default or [], key=key)

    with st.container(border=True):
        # 장르 (Suno 공식 태그 기준)
        st.markdown("**🎸 장르**")
        st.caption("Suno 공식 스타일 태그 기준 — 선택한 태그가 그대로 Suno Style 칸에 들어갑니다.")
        sg_genres = _pills("장르", [
            # 한국/아시아
            "K-Pop","J-Pop","트로트","Modern Bollywood",
            # 팝/인디
            "Pop","Alternative Pop","Indie","New Wave",
            # R&B/소울/힙합
            "R&B","Soul","Hip Hop","Rap","Trap","Funk",
            # 록/메탈
            "Rock","Punk","Grunge","Heavy Metal","Ska",
            # 전자음악
            "EDM","Electronic","Synthwave","House","Techno","Cinematic Dubstep","Drum And Bass","Chillhop",
            # 재즈/블루스/어쿠스틱
            "Jazz","Blues","Folk","Bluegrass","Gospel","Acoustic Cover","A Capella",
            # 클래식/명상
            "Classical","Opera","Meditation","Ambient","Focus","Sleep",
            # 월드뮤직
            "Latin","Reggae","Reggaeton","Afrobeats","Bossa Nova",
            # 로파이/기타
            "Lofi Beats",
        ], key="sg_genres", default=["K-Pop","트로트"])

        st.divider()

        # 언어
        st.markdown("**🌏 언어**")
        sg_lang = st.pills("언어", ["한국어","English","日本語","中文","Español","Français","한+영 혼합"],
                           selection_mode="single", default="한국어", key="sg_lang")

        st.divider()

        # 보컬
        st.markdown("**🎤 보컬**")
        sg_vocal = _pills("보컬", ["여자 솔로","남자 솔로","남녀 듀엣","코러스","보이그룹","혼성 그룹","어린이 보컬","래퍼"],
                          key="sg_vocal", default=["여자 솔로"])

        st.divider()

        # 템포 / BPM
        st.markdown("**🥁 템포 / BPM**")
        sg_bpm = st.pills("템포", [
            "매우 느림 (40-50 BPM)","재즈 노름 (50-70 BPM)","느름 (70-90 BPM)",
            "보통 (90-110 BPM)","업비트 (110-130 BPM)","매우 빠름 (130-150 BPM)",
        ], selection_mode="single", default="보통 (90-110 BPM)", key="sg_bpm")

        st.divider()

        # 분위기 / 무드
        st.markdown("**🌙 분위기 / 무드**")
        sg_mood = _pills("분위기", [
            "밝고 신나는","슬프고 감성적인","몽환적인","에너지 넘치고 활력찬","지성적이고 편안한",
            "자유롭고 힘찬","카페 느낌","이별·그리움","흥겨운","노스탤직","무겁고 웅장한","공격적",
            "클래식·우아한","일렉트로닉","청량한","따뜻한","새벽감성",
        ], key="sg_mood", default=["밝고 신나는"])

        st.divider()

        # 시대감 / 스타일
        st.markdown("**🕰️ 시대감 / 스타일**")
        sg_era = st.pills("시대감", ["현대 (2020s)","2010s","2000s","90s 레트로","80s 레트로","70s 빈티지","시대 무관","미래형"],
                          selection_mode="single", default="현대 (2020s)", key="sg_era")

        st.divider()

        # 상황 / 주제
        st.markdown("**🎬 상황 / 주제**")
        sg_situation = _pills("상황", [
            "공부·집중","드라이브","카페에서","늦은 밤","이른 아침","비 오는 날","여행","운동·워크아웃",
            "파티","데이트","이별","힐링","명상","가족·추억","친구와 함께",
        ], key="sg_situation", default=["드라이브"])

        st.divider()

        # 곡당 길이
        c_len, c_spacer = st.columns([2, 1])
        with c_len:
            sg_duration = st.slider("🕒 곡당 길이 (Suno 생성 시간)", min_value=60, max_value=300,
                                    value=180, step=30, key="sg_duration",
                                    format="%d초")
            mins, secs = divmod(sg_duration, 60)
            st.caption(f"→ **{mins}분 {secs:02d}초** | Suno API V3/V3.5+ 기준. 길수록 토큰 소모가 늘어납니다.")

        st.divider()

        # 주제 / 컨텐 (가사 내용)
        sg_theme = st.text_area(
            "📝 주제 / 컨텐 (가사 내용, 선택)",
            height=80,
            placeholder="예: 고향 가는 길, 보고 싶은 엄마, 새벽 포장마차에서 혼술...",
            key="sg_theme",
        )

        # 악기 / 사운드 디테일
        sg_instrument = st.text_area(
            "🎹 악기 / 사운드 디테일 (선택)",
            height=70,
            placeholder="예: piano, acoustic guitar, soft drums, reverb, warm bass",
            key="sg_instrument",
        )

        st.divider()

        # ── 트로트 전용 가사 옵션 ──────────────────────────────
        st.markdown("**🎤 트로트 전용 가사 옵션**")

        trot_col1, trot_col2 = st.columns(2)

        with trot_col1:
            # 감탄사 / 반복구
            st.markdown("**감탄사 · 반복구** (후렴에 삽입)")
            exclaim_presets = [
                "없음", "예뻐 예뻐", "얼씨구 얼씨구", "좋다 좋아",
                "아이고 아이고", "어머 어머", "와~야 와~야",
                "짝짝꿍 짝짝꿍", "흥이야 흥", "직접 입력",
            ]
            exclaim_sel = st.pills(
                "감탄사", exclaim_presets, selection_mode="single",
                default="없음", key="sg_exclaim",
            )
            if exclaim_sel == "직접 입력":
                sg_exclaim = st.text_input("감탄사 직접 입력", placeholder="예: 아리랑 아리랑", key="sg_exclaim_custom")
            else:
                sg_exclaim = exclaim_sel if exclaim_sel != "없음" else ""

            # 사투리 지역
            st.markdown("**사투리 지역** (후렴구에 반영)")
            dialect_opts = [
                "없음 (표준어)", "경상도 (거마이 좋다~)", "전라도 (거시기~)",
                "충청도 (그려~ 그려~)", "강원도 (글쎄요~)", "제주도 (헤여~)",
                "서울 신촌 (야 진짜~)", "직접 입력",
            ]
            dialect_sel = st.pills(
                "사투리", dialect_opts, selection_mode="single",
                default="없음 (표준어)", key="sg_dialect",
            )
            if dialect_sel == "직접 입력":
                sg_dialect = st.text_input("사투리 직접 입력", placeholder="예: 부산 (~했나예)", key="sg_dialect_custom")
            else:
                sg_dialect = "" if dialect_sel == "없음 (표준어)" else dialect_sel

        with trot_col2:
            # 가사 구조
            st.markdown("**가사 구조**")
            struct_opts = [
                "8섹션 풀구조 (V1-PC1-C1-V2-PC2-C2-Br-C3)",
                "4섹션 (V1-C1-V2-C2)",
                "6섹션 (V1-C1-V2-C2-Br-C3)",
            ]
            sg_structure = st.pills(
                "구조", struct_opts, selection_mode="single",
                default="8섹션 풀구조 (V1-PC1-C1-V2-PC2-C2-Br-C3)", key="sg_structure",
            )

            # 숏폼 바이럴 느낌
            sg_viral = st.toggle("🔥 숏폼 바이럴 코믹 느낌", value=False, key="sg_viral",
                                  help="코러스에 코믹하고 귀에 착착 감기는 반복구 강화")

            # 음절 밀도
            st.markdown("**음절 밀도**")
            sg_syllable = st.pills(
                "음절",
                ["촘촘 (빠른 랩핏)", "보통", "여유 (긴 멜로디)"],
                selection_mode="single", default="보통", key="sg_syllable",
            )

            # 후렴 반복 강도
            st.markdown("**후렴 반복 강도**")
            sg_repeat = st.pills(
                "반복",
                ["1회", "2회 반복", "3회 강하게"],
                selection_mode="single", default="2회 반복", key="sg_repeat",
            )

    st.divider()

    gen_btn = st.button("🎵 가사 + 스타일 만들기 ✨", type="primary", use_container_width=True, key="sg_gen")

    # ── 생성 로직 ──────────────────────────────────────────────
    if gen_btn:
        if not sg_genres:
            st.error("장르를 1개 이상 선택해주세요.")
            st.stop()
        if not gemini_key and not openai_key:
            st.error("Gemini 또는 OpenAI API 키를 먼저 등록해주세요.")
            st.stop()

        bpm_str   = sg_bpm or "보통 (90-110 BPM)"
        sg_exclaim  = st.session_state.get("sg_exclaim_custom", "") if st.session_state.get("sg_exclaim") == "직접 입력" else (st.session_state.get("sg_exclaim","") if st.session_state.get("sg_exclaim","") != "없음" else "")
        sg_dialect  = st.session_state.get("sg_dialect_custom", "") if st.session_state.get("sg_dialect") == "직접 입력" else (st.session_state.get("sg_dialect","") if st.session_state.get("sg_dialect","") not in ("없음 (표준어)","") else "")
        sg_structure = st.session_state.get("sg_structure", "8섹션 풀구조 (V1-PC1-C1-V2-PC2-C2-Br-C3)")
        sg_viral    = st.session_state.get("sg_viral", False)
        sg_syllable = st.session_state.get("sg_syllable", "보통")
        sg_repeat   = st.session_state.get("sg_repeat", "2회 반복")

        mc = st.session_state.get("sg_money_code")
        mc_block = ""
        if mc:
            mc_block = f"""
머니코드 (반드시 스타일 태그에 통합할 것):
- 기본 스타일 공식: {mc['tags']}
{"- 고정 태그 (반드시 포함): " + mc['fixed_tags'] if mc.get('fixed_tags') else ""}
{"- 금지 태그 (절대 사용 금지): " + mc['banned_tags'] if mc.get('banned_tags') else ""}
"""

        # 구조 매핑
        struct_map = {
            "8섹션 풀구조 (V1-PC1-C1-V2-PC2-C2-Br-C3)":
                "[Verse 1] → [Pre-Chorus 1] → [Chorus 1] → [Verse 2] → [Pre-Chorus 2] → [Chorus 2] → [Bridge] → [Chorus 3]",
            "4섹션 (V1-C1-V2-C2)":
                "[Verse 1] → [Chorus 1] → [Verse 2] → [Chorus 2]",
            "6섹션 (V1-C1-V2-C2-Br-C3)":
                "[Verse 1] → [Chorus 1] → [Verse 2] → [Chorus 2] → [Bridge] → [Chorus 3]",
        }
        structure_str = struct_map.get(sg_structure or "", struct_map["8섹션 풀구조 (V1-PC1-C1-V2-PC2-C2-Br-C3)"])

        trot_block = ""
        if sg_exclaim or sg_dialect or sg_viral:
            exclaim_rule = ""
            if sg_exclaim:
                exclaim_rule = f"""
【감탄사 반복구 사용 규칙】
- 지정 감탄사: 「{sg_exclaim}」
- 반드시 가사의 **감정 흐름과 맥락에 어울리는 순간**에만 배치하세요.
  ✅ 좋은 예: 그리운 엄마 이야기 → "보고 싶어 보고 싶어 / {sg_exclaim} {sg_exclaim}"
  ❌ 나쁜 예: 이별 슬픔 가사 중간에 뜬금없이 "{sg_exclaim}" 삽입
- 코러스 감정이 터지는 지점에서 {sg_repeat} 반복
- 감탄사 앞뒤 가사가 자연스럽게 이어지도록 연결어 사용
"""
            dialect_rule = ""
            if sg_dialect:
                dialect_rule = f"""
【사투리 사용 규칙】
- 지정 사투리: {sg_dialect}
- 사투리는 **가사의 상황·감정과 100% 어울리는 표현**으로 골라서 사용하세요.
  예) 전라도 "거시기" → 말 못할 감정이 복받치는 장면에 자연스럽게
  예) 경상도 "머라카노" → 황당하거나 놀라운 상황에 리액션으로
  예) 충청도 "그려~" → 느긋하고 여유로운 장면에서 공감 표현으로
- 코믹하되 억지스럽지 않게, 그 지역 사람이 실제로 쓰는 말투로
- 사투리 단어 1~2개로 충분, 전체 가사를 사투리로 쓰지 말 것
"""
            viral_rule = ""
            if sg_viral:
                viral_rule = """
【숏폼 바이럴 규칙】
- 코러스 첫 줄은 3초 안에 귀에 꽂히는 훅(hook)으로 시작
- 댓글에 "ㅋㅋㅋ 이거 귀에서 안 떠남"이 달릴 만큼 중독성 있게
- 과장된 감탄·반복·라임이 자연스럽게 웃음을 유발
- 틱톡/릴스에서 립싱크 챌린지가 될 만한 구간 1개 포함
"""
            trot_block = f"""
{exclaim_rule}{dialect_rule}{viral_rule}
【공통 작사 원칙】
- 감탄사·사투리는 절대 억지로 끼워 넣지 말고, 그 자리에 없으면 어색할 때만 사용
- 가사 전체의 감정 흐름(설정→고조→폭발→여운)이 끊기지 않아야 함
- 음절 밀도: {sg_syllable} (촘촘=빠른 랩핏 / 여유=긴 호흡 멜로디)
"""

        prompt = f"""
당신은 한국 트로트 전문 작사가이자 Suno AI 프롬프트 엔지니어입니다.
아래 조건으로 서로 다른 **10곡**의 제목, Suno 스타일 태그, 가사를 JSON으로 작성하세요.

【음악 옵션】
- 장르: {', '.join(sg_genres)}
- 언어: {sg_lang or '한국어'}
- 보컬: {', '.join(sg_vocal) if sg_vocal else '여자 솔로'}
- 템포/BPM: {bpm_str}
- 분위기: {', '.join(sg_mood) if sg_mood else '밝고 신나는'}
- 시대감: {sg_era or '현대 (2020s)'}
- 상황/주제: {', '.join(sg_situation) if sg_situation else '자유롭게'}
- 곡 길이: {mins}분 {secs:02d}초
- 가사 내용: {sg_theme or '자유롭게'}
- 악기 디테일: {sg_instrument or '자유롭게'}
{mc_block}
【가사 구조 — 반드시 이 순서로, 섹션 태그 포함】
{structure_str}

각 섹션 앞에 반드시 Suno 구조 태그를 붙이세요:
[Verse 1], [Pre-Chorus 1], [Chorus 1], [Verse 2], [Pre-Chorus 2], [Chorus 2], [Bridge], [Chorus 3]

【각 섹션 작사 가이드】
- [Verse]: 구체적 장면 묘사 (추상 X, 감각적 이미지 O) — "새벽 3시 포장마차 연기 냄새" 같은 식
- [Pre-Chorus]: 감정 고조, 코러스로 이어지는 브릿지 역할, 짧고 강하게
- [Chorus]: 핵심 감정 한 줄 + 감탄사 반복구, 누구나 따라 부를 수 있게
- [Bridge]: 반전 또는 절정 감정, 멜로디 변화 암시
- [Chorus 3]: 마지막 클라이맥스, 앞 코러스보다 강렬하게
{trot_block}
【스타일 태그 규칙】
- 영문, Suno에 바로 붙여넣을 수 있는 형식
- 예: "trot, female vocal, emotional, piano, haegeum, reverb, 85 BPM, cinematic"

JSON 스키마 (배열, 10개):
[
  {{
    "num": 1,
    "title_ko": "한국어 제목",
    "title_en": "English Title",
    "style_tags": "suno style tags in english",
    "lyrics": "섹션 태그 포함 전체 가사"
  }},
  ...
]

반드시 JSON 배열만 출력하세요. 다른 텍스트 없음.
""".strip()

        with st.spinner("🎵 AI가 10곡을 작곡 중입니다... 잠시만 기다려주세요!"):
            songs = None
            try:
                raw, used = _ai_generate(prompt, gemini_key, openai_key, temperature=0.9)
                if used == "openai" and gemini_key:
                    st.info("ℹ️ Gemini 키 오류로 OpenAI로 자동 전환했습니다.")

                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                songs = json.loads(raw.strip())
                st.session_state["sg_songs"] = songs
                st.session_state["sg_meta"] = {
                    "genres": sg_genres, "lang": sg_lang, "vocal": sg_vocal,
                    "bpm": bpm_str, "mood": sg_mood, "era": sg_era,
                    "situation": sg_situation, "theme": sg_theme,
                }
            except RuntimeError as e:
                st.error(str(e))
                if "API_KEY_SERVICE_BLOCKED" in str(e) or "차단" in str(e):
                    with st.expander("🔧 Gemini API 활성화 방법"):
                        st.markdown("""
**원인:** Gemini API 키에 `Generative Language API` 서비스가 차단되어 있습니다.

**해결 방법 (택1):**

**방법 1 — Gemini API 활성화 (권장)**
1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. 좌측 메뉴 → **API 및 서비스** → **라이브러리**
3. `Generative Language API` 검색 → **사용 설정** 클릭
4. API 키에 제한이 있다면: **사용자 인증 정보** → 해당 키 → API 제한 → 목록에 추가

**방법 2 — AI Studio 키 새로 발급**
1. [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) 접속
2. 새 키 발급 → 앱 **API 연결** 메뉴에서 교체

**방법 3 — OpenAI 키 등록**
- OpenAI API 키를 등록하면 Gemini 없이도 바로 사용 가능합니다.
""")
                st.stop()
            except Exception as e:
                st.error(f"생성 실패: {e}")
                st.stop()

    # ── 결과 표시 ──────────────────────────────────────────────
    songs = st.session_state.get("sg_songs")
    meta  = st.session_state.get("sg_meta", {})

    if songs:
        st.success(f"✅ {len(songs)}곡 생성 완료!")
        # 스타일 요약 배너
        tags_preview = ""
        if songs:
            tags_preview = songs[0].get("style_tags", "")
        if tags_preview:
            with st.container(border=True):
                st.caption("**생성된 스타일 태그 (첫 번째 곡 기준)**")
                st.code(tags_preview, language=None)
                st.caption("→ Suno AI 'Style' 칸에 그대로 붙여넣기!")

        # 노래 리스트 헤더
        c_h1, c_h2 = st.columns([3, 1])
        c_h1.markdown(f"### {len(songs)} 노래 리스트")
        # 플레이리스트 저장 (session_state)
        if c_h2.button("🎵 플레이리스트로 저장", key="sg_save_pl", use_container_width=True):
            saved = st.session_state.get("sg_playlists", [])
            saved.append({"meta": meta, "songs": songs, "saved_at": datetime.now().isoformat()})
            st.session_state["sg_playlists"] = saved
            st.toast(f"플레이리스트 저장 완료! (총 {len(saved)}개)")

        # 곡 아코디언
        for song in songs:
            num  = song.get("num", "")
            t_ko = song.get("title_ko", "")
            t_en = song.get("title_en", "")
            with st.expander(f"**{num:02d}.** {t_ko}  ·  *{t_en}*"):
                sc1, sc2 = st.columns([3, 2])
                with sc1:
                    st.markdown("**🎨 Suno 스타일 태그**")
                    st.code(song.get("style_tags", ""), language=None)
                with sc2:
                    st.markdown("**📋 제목 (복사용)**")
                    st.code(t_ko, language=None)
                    st.code(t_en, language=None)
                st.markdown("**📝 가사**")
                lyrics = song.get("lyrics", "")
                st.text_area(f"가사_{num}", value=lyrics, height=220, key=f"sg_lyrics_{num}", label_visibility="collapsed")

        st.divider()

        # ══════════════════════════════════════════════════════
        # STEP 2 : 실제 노래 만들기 (선택)
        # ══════════════════════════════════════════════════════
        st.markdown('<span class="sg-step">🎵 STEP 2 : 실제 노래 만들기 (선택)</span>', unsafe_allow_html=True)
        st.caption("가사를 만든 후, 각 노래 옆 버튼으로 전체 파일로이 만들 수 있어요!")

        col_s1, col_s2, col_s3 = st.columns(3)

        with col_s1:
            with st.container(border=True):
                st.markdown("#### 🤖 Suno API")
                st.caption("전체 Suno V3 이상으로 자동 노래 생성 (3~4분). **별도 API 필요**")
                st.markdown("✅ **kie.ai** 필요")
                kieai_key = st.text_input("kie.ai API 키", type="password", key="sg_kieai_key",
                                          placeholder="kie.ai API 키 입력")
                if st.button("🎵 Suno API로 전체 생성", key="sg_suno_api", use_container_width=True,
                              type="primary", disabled=not kieai_key):
                    st.info("Suno API 연동 기능은 곧 지원 예정입니다.")

        with col_s2:
            with st.container(border=True):
                st.markdown("#### 🎼 Lyria 3 Pro")
                st.caption("Google의 전문 음악 AI, Gemini 이용. 가사→음악 자동 변환")
                st.markdown(f"✅ **Gemini** 붙잡아 {'필요' if not gemini_key else '✓ 연결됨'}")
                if st.button("🎼 Lyria로 생성", key="sg_lyria", use_container_width=True,
                              disabled=not gemini_key):
                    st.info("Lyria 3 Pro 연동 기능은 곧 지원 예정입니다.")

        with col_s3:
            with st.container(border=True):
                st.markdown("#### ✋ 사용 안함 (수동)")
                st.caption("Suno 사이트에서 직접 붙여넣고 생성. **100% 무료**")
                st.markdown("✅ **100%** 무료")
                st.markdown("""
**사용법:**
1. 위 각 곡의 '스타일 태그' 복사
2. [suno.com](https://suno.com) → Custom Mode ON
3. Style 칸에 태그, Lyrics 칸에 가사 붙여넣기
4. Generate!
""")
                # 전체 가사+태그 다운로드
                all_text = "\n\n".join([
                    f"{'='*50}\n{s.get('num'):02d}. {s.get('title_ko')} / {s.get('title_en')}\n"
                    f"[Style] {s.get('style_tags','')}\n\n{s.get('lyrics','')}"
                    for s in songs
                ])
                st.download_button(
                    "📥 전체 가사+태그 TXT 다운로드",
                    data=all_text.encode("utf-8"),
                    file_name=f"suno_songs_{datetime.now():%Y%m%d_%H%M}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

        st.divider()

        # JSON 다운로드
        st.download_button(
            "📥 전체 JSON 다운로드",
            data=json.dumps(songs, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"suno_songs_{datetime.now():%Y%m%d_%H%M}.json",
            mime="application/json",
        )


def render_channel_planning_tab() -> None:
    """AI 채널 기획안 생성기 — 채널 컨셉 입력 → 완성형 기획안 자동 출력."""

    st.markdown("## 🏗️ AI 채널 기획안 생성기")
    st.caption("채널 컨셉을 입력하면 채널명·슬로건·제목 공식·성장전략·수익화 아이디어를 AI가 완성형으로 작성해줍니다.")

    gemini_key = os.getenv("GEMINI_API_KEY") or SAVED_KEYS.get("gemini", "")
    openai_key = os.getenv("OPENAI_API_KEY") or SAVED_KEYS.get("openai", "")

    if not gemini_key and not openai_key:
        st.warning("🔑 Gemini 또는 OpenAI API 키가 필요합니다. 왼쪽 메뉴 **API 연결**에서 키를 등록하세요.")

    st.divider()

    # ── 입력 폼 ───────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("### 📝 채널 컨셉 입력")
        col_a, col_b = st.columns(2)
        with col_a:
            genre = st.selectbox(
                "주요 장르",
                ["트로트", "발라드", "K-팝", "K-인디", "클래식", "재즈", "Lo-fi", "시티팝", "R&B", "힙합", "뉴에이지", "CCM", "동요", "직접 입력"],
                key="cp_genre",
            )
            if genre == "직접 입력":
                genre = st.text_input("장르 직접 입력", key="cp_genre_custom", placeholder="예: 70~80년대 팝")
            channel_style = st.selectbox(
                "채널 스타일",
                ["감성 힐링형", "노래 모음 플레이리스트", "가사/해석 해설형", "라이브 공연 중심", "AI 커버송", "오리지널 창작", "악기 연주 (반주/MIDI)"],
                key="cp_style",
            )
        with col_b:
            target_age = st.selectbox(
                "타겟 연령대",
                ["전 연령", "10~20대", "20~30대", "30~40대 (밀레니얼)", "40~50대", "50~70대 (중장년)"],
                key="cp_target",
            )
            platform_goal = st.selectbox(
                "주요 목표",
                ["구독자 성장 (알고리즘)", "유입 → 수익화", "팬덤 구축", "브랜드 인지도", "Suno 음원 홍보"],
                key="cp_goal",
            )
        mood_keywords = st.text_input(
            "감성 키워드 (3~5개, 쉼표로 구분)",
            value="",
            placeholder="예: 새벽, 위로, 따뜻함, 그리움",
            key="cp_mood",
        )
        extra_note = st.text_area(
            "추가 특이사항 (선택)",
            height=80,
            placeholder="예: 창업 비용 0원, AI 음악 100%, 5070 타겟, 매주 1편 업로드 예정",
            key="cp_extra",
        )

    st.divider()
    gen_btn = st.button("✨ AI 기획안 생성", type="primary", use_container_width=True, key="cp_gen")

    if gen_btn:
        if not genre or not mood_keywords.strip():
            st.error("장르와 감성 키워드는 필수입니다.")
            st.stop()

        prompt_text = f"""
당신은 유튜브 음악 채널 전문 기획자입니다.
아래 정보를 바탕으로 완성형 채널 기획안을 JSON 형식으로 작성하세요.

입력 정보:
- 주요 장르: {genre}
- 채널 스타일: {channel_style}
- 타겟 연령대: {target_age}
- 주요 목표: {platform_goal}
- 감성 키워드: {mood_keywords}
- 추가 사항: {extra_note or '없음'}

다음 JSON 스키마를 정확히 따르세요:
{{
  "channel_names": ["채널명1", "채널명2", "채널명3"],
  "slogans": ["슬로건1", "슬로건2"],
  "channel_description": "채널 소개글 (100~150자)",
  "differentiators": ["차별화 포인트1", "차별화 포인트2", "차별화 포인트3"],
  "series_ideas": [
    {{"title": "시리즈명", "concept": "한 줄 설명"}},
    {{"title": "시리즈명", "concept": "한 줄 설명"}},
    {{"title": "시리즈명", "concept": "한 줄 설명"}}
  ],
  "title_formulas": [
    {{"formula": "공식 패턴", "example": "실제 예시 제목"}},
    {{"formula": "공식 패턴", "example": "실제 예시 제목"}},
    {{"formula": "공식 패턴", "example": "실제 예시 제목"}},
    {{"formula": "공식 패턴", "example": "실제 예시 제목"}},
    {{"formula": "공식 패턴", "example": "실제 예시 제목"}}
  ],
  "thumbnail_direction": "썸네일 방향성 및 디자인 가이드 (2~3문장)",
  "growth_strategies": [
    {{"area": "전략 분야", "action": "구체적 실행 방안"}},
    {{"area": "전략 분야", "action": "구체적 실행 방안"}},
    {{"area": "전략 분야", "action": "구체적 실행 방안"}},
    {{"area": "전략 분야", "action": "구체적 실행 방안"}},
    {{"area": "전략 분야", "action": "구체적 실행 방안"}}
  ],
  "monetization_ideas": [
    {{"method": "수익화 방법", "detail": "상세 설명"}},
    {{"method": "수익화 방법", "detail": "상세 설명"}},
    {{"method": "수익화 방법", "detail": "상세 설명"}},
    {{"method": "수익화 방법", "detail": "상세 설명"}}
  ]
}}

반드시 JSON만 출력하세요. 다른 텍스트는 넣지 마세요.
""".strip()

        plan_data = None
        with st.spinner("AI가 채널 기획안을 작성 중입니다..."):
            try:
                raw, used = _ai_generate(prompt_text, gemini_key, openai_key, temperature=0.8)
                if used == "openai" and gemini_key:
                    st.info("ℹ️ Gemini 키 오류로 OpenAI로 자동 전환했습니다.")

                # JSON 파싱
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                plan_data = json.loads(raw.strip())
                st.session_state["cp_last_plan"] = plan_data
                st.session_state["cp_last_meta"] = {
                    "genre": genre, "style": channel_style,
                    "target": target_age, "mood": mood_keywords,
                }
            except RuntimeError as e:
                st.error(str(e))
                st.stop()
            except Exception as e:
                st.error(f"생성 실패: {e}")
                st.stop()

    # ── 결과 표시 ─────────────────────────────────────────────
    plan = st.session_state.get("cp_last_plan")
    meta = st.session_state.get("cp_last_meta", {})

    if plan:
        st.success("✅ 채널 기획안이 완성되었습니다!")
        st.caption(f"장르: **{meta.get('genre','')}** · 스타일: **{meta.get('style','')}** · 타겟: **{meta.get('target','')}** · 키워드: *{meta.get('mood','')}*")
        st.divider()

        # ── 채널명 후보 ──────────────────────────────────────
        st.markdown("### 📺 채널명 후보")
        names = plan.get("channel_names", [])
        name_cols = st.columns(len(names)) if names else []
        for i, (col, name) in enumerate(zip(name_cols, names)):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{name}**")
                    st.code(name, language=None)

        st.divider()

        # ── 슬로건 ──────────────────────────────────────────
        st.markdown("### 💬 슬로건 후보")
        for slogan in plan.get("slogans", []):
            sl_c1, sl_c2 = st.columns([10, 1])
            sl_c1.markdown(f'> *"{slogan}"*')
            sl_c2.code(slogan, language=None)

        st.divider()

        # ── 채널 소개글 ──────────────────────────────────────
        st.markdown("### 📄 채널 소개글")
        desc = plan.get("channel_description", "")
        with st.container(border=True):
            st.write(desc)
            st.code(desc, language=None)

        st.divider()

        # ── 차별화 포인트 ─────────────────────────────────────
        col_diff, col_series = st.columns(2)
        with col_diff:
            st.markdown("### ⭐ 차별화 포인트")
            for point in plan.get("differentiators", []):
                st.markdown(f"⭐ {point}")

        with col_series:
            st.markdown("### 🎬 시리즈 콘텐츠 아이디어")
            for i, series in enumerate(plan.get("series_ideas", []), 1):
                st.markdown(f"**{i}. {series.get('title','')}**")
                st.caption(series.get("concept", ""))

        st.divider()

        # ── 영상 제목 공식 ────────────────────────────────────
        st.markdown("### 🏷️ 영상 제목 공식 5가지")
        for i, tf in enumerate(plan.get("title_formulas", []), 1):
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                c1.markdown(f"**공식 {i}**")
                c1.code(tf.get("formula", ""), language=None)
                c2.markdown("**예시 제목**")
                c2.info(tf.get("example", ""))

        st.divider()

        # ── 썸네일 방향성 ─────────────────────────────────────
        st.markdown("### 🖼️ 썸네일 방향성")
        with st.container(border=True):
            st.write(plan.get("thumbnail_direction", ""))

        st.divider()

        # ── 초기 성장 전략 ────────────────────────────────────
        st.markdown("### 🚀 초기 성장 전략")
        gs_cols = st.columns(2)
        for i, gs in enumerate(plan.get("growth_strategies", [])):
            with gs_cols[i % 2]:
                with st.container(border=True):
                    st.markdown(f"**{gs.get('area','')}**")
                    st.write(gs.get("action", ""))

        st.divider()

        # ── 수익화 아이디어 ────────────────────────────────────
        st.markdown("### 💰 수익화 아이디어")
        mon_cols = st.columns(2)
        for i, mon in enumerate(plan.get("monetization_ideas", [])):
            with mon_cols[i % 2]:
                with st.container(border=True):
                    st.markdown(f"**{mon.get('method','')}**")
                    st.caption(mon.get("detail", ""))

        st.divider()

        # ── 전체 기획안 JSON 다운로드 ─────────────────────────
        plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 기획안 JSON 다운로드",
            data=plan_json.encode("utf-8"),
            file_name=f"channel_plan_{meta.get('genre','')}_{datetime.now():%Y%m%d_%H%M}.json",
            mime="application/json",
        )


def main() -> None:
    st.set_page_config(
        page_title="유튜브 음악 채널 자동화",
        page_icon="🎵",
        layout="wide",
    )

    # ── 사이드바 스타일 ────────────────────────────────────────
    st.sidebar.markdown("""
<style>
[data-testid="stSidebar"] { min-width: 230px; max-width: 230px; }
div[data-testid="stSidebarNav"] { display: none; }
.sb-logo   { font-size: 20px; font-weight: 900; color: #fff; margin-bottom: 2px; }
.sb-sub    { font-size: 11px; color: #aaa; margin-bottom: 4px; }
.sb-label  { font-size: 10px; color: #888; font-weight: 700;
             letter-spacing: 1px; margin: 10px 0 4px 0; }
.badge     { display:inline-block; background:#e74c3c; color:#fff;
             font-size:10px; font-weight:700; border-radius:10px;
             padding:1px 6px; margin-left:6px; vertical-align:middle; }
.api-row   { display:flex; align-items:center; gap:6px;
             font-size:13px; color:#ccc; margin:3px 0; }
.dot-on    { width:8px;height:8px;border-radius:50%;
             background:#2ecc71;display:inline-block;flex-shrink:0; }
.dot-off   { width:8px;height:8px;border-radius:50%;
             background:#e74c3c;display:inline-block;flex-shrink:0; }
</style>
""", unsafe_allow_html=True)

    # ── 로고 ──────────────────────────────────────────────────
    st.sidebar.markdown(
        '<div class="sb-logo">🎵 유튜브 자동화</div>'
        '<div class="sb-sub">음악 채널 자동 생산 시스템</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.divider()

    # ── 분석 기록 배지 카운트 ──────────────────────────────────
    # session_state에 캐시된 검색 결과 수를 배지로 표시
    history_count = sum(
        1 for k in st.session_state
        if k.startswith("hotpli_results_") or k == "ca_result"
    )

    # ── 메뉴 정의 ─────────────────────────────────────────────
    st.sidebar.markdown('<div class="sb-label">★ MENU</div>', unsafe_allow_html=True)

    ref_count = len(_load_ref_channels())

    _NAV = [
        ("🏠", "홈", None),
        ("🔍", "채널·영상 분석", None),
        ("⚡", "핫플리 트렌드", None),
        ("📡", "레퍼런스 채널", ref_count if ref_count else None),
        ("📸", "스톡 미디어", None),
        ("🕐", "분석 기록", history_count if history_count else None),
        ("📋", "평가 가이드라인", None),
        ("🔑", "API 연결", None),
    ]

    if "nav_menu" not in st.session_state:
        st.session_state["nav_menu"] = "홈"

    for icon, label, badge in _NAV:
        is_active = st.session_state["nav_menu"] == label
        btn_label = f"{icon}  {label}" + (f"  [{badge}]" if badge else "")
        if st.sidebar.button(
            btn_label,
            key=f"nav_{label}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["nav_menu"] = label
            st.rerun()

    # ── 구분선 + 기타 기능 ────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.markdown('<div class="sb-label">🎛️ 제작 도구</div>', unsafe_allow_html=True)

    _TOOLS = [
        ("🎵", "음악 만들기"),
        ("🎬", "영상 만들기"),
        ("🗂️", "메타데이터"),
    ]
    for icon, label in _TOOLS:
        is_active = st.session_state["nav_menu"] == label
        if st.sidebar.button(
            f"{icon}  {label}",
            key=f"nav_{label}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["nav_menu"] = label
            st.rerun()

    # ── API 연결 상태 ──────────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.markdown('<div class="sb-label">API CONNECTION STATUS</div>', unsafe_allow_html=True)

    yt_key     = bool(st.session_state.get("yt_api_key_input") or os.getenv("YOUTUBE_API_KEY") or SAVED_KEYS.get("youtube"))
    gem_key    = bool(os.getenv("GEMINI_API_KEY") or SAVED_KEYS.get("gemini"))
    oai_key    = bool(os.getenv("OPENAI_API_KEY") or SAVED_KEYS.get("openai"))
    pexels_key = bool(os.getenv("PEXELS_API_KEY") or SAVED_KEYS.get("pexels"))

    def _dot(on: bool) -> str:
        return f'<span class="{"dot-on" if on else "dot-off"}"></span>'

    st.sidebar.markdown(
        f'<div class="api-row">{_dot(gem_key)} Gemini</div>'
        f'<div class="api-row">{_dot(False)} Suno (kie.ai)</div>'
        f'<div class="api-row">{_dot(yt_key)} YouTube</div>'
        f'<div class="api-row">{_dot(oai_key)} OpenAI</div>'
        f'<div class="api-row">{_dot(pexels_key)} Pexels</div>',
        unsafe_allow_html=True,
    )

    # ── 라우팅 ────────────────────────────────────────────────
    nav = st.session_state.get("nav_menu", "홈")

    # 홈
    if nav == "홈":
        st.title("🎵 유튜브 음악 채널 자동화 대시보드")
        st.caption("왼쪽 메뉴에서 원하는 기능을 선택하세요.")
        st.divider()
        r1c1, r1c2, r1c3 = st.columns(3)
        r1c1.info("🔍 **채널·영상 분석**\n\n채널 URL로 통계·인기영상·조회 추이 분석")
        r1c2.info("⚡ **핫플리 트렌드**\n\n국가·장르별 지금 뜨는 플레이리스트 탐색")
        r1c3.info("🕐 **분석 기록**\n\n이전 검색·분석 결과 모아보기")
        r2c1, r2c2, r2c3 = st.columns(3)
        r2c1.info("🎵 **음악 만들기**\n\nAI 스토리텔링 · Suno 스튜디오 · 역설계")
        r2c2.info("🎬 **영상 만들기**\n\n영상 합성 · 인코딩 잡 · 가사 동기화")
        r2c3.info("🗂️ **메타데이터**\n\n제목 공식 Lab")

    # 채널·영상 분석
    elif nav == "채널·영상 분석":
        st.title("🔍 채널·영상 분석")
        render_channel_analysis_tab()

    # 핫플리 트렌드
    elif nav == "핫플리 트렌드":
        st.title("⚡ 핫플리 트렌드")
        st.caption("국가별로 어떤 음악 플레이리스트가 뜨는지 비교해보세요.")
        # 사이드바에 급상승 채널 발굴 검색 설정도 노출
        tab_hot, tab_breakout = st.tabs(["🔥 핫플리 트렌드", "🔍 급상승 채널 발굴"])
        with tab_hot:
            render_hotpli_trends()
        with tab_breakout:
            new_cfg = render_sidebar()
            if new_cfg is not None:
                st.session_state.active_cfg = new_cfg
                try:
                    with st.spinner("YouTube API 호출 및 분석 중..."):
                        st.session_state["disc_df"] = run_pipeline(new_cfg)
                except Exception as e:
                    st.error(f"오류: {e}")
            cfg = st.session_state.get("active_cfg")
            df  = st.session_state.get("disc_df")
            if cfg is None or df is None:
                st.info("👈 사이드바에서 키워드와 필터를 설정하고 **발굴 시작**을 누르세요.")
            elif df.empty:
                st.warning("검색 결과가 없습니다.")
            else:
                render_results(df, filter_breakout_channels(df, cfg), cfg)

    # 분석 기록
    elif nav == "분석 기록":
        st.title("🕐 분석 기록")
        st.caption("이 세션에서 실행한 검색·분석 결과를 모아볼 수 있습니다.")
        st.divider()
        found = False
        # 핫플리 트렌드 캐시
        hotpli_keys = [k for k in st.session_state if k.startswith("hotpli_results_")]
        if hotpli_keys:
            found = True
            st.markdown("### ⚡ 핫플리 트렌드 검색 기록")
            for k in hotpli_keys:
                df_h = st.session_state[k]
                meta = k.replace("hotpli_results_", "")
                parts = meta.split("_")
                label = " · ".join(p for p in parts if p)
                with st.expander(f"🔍 {label}  —  {len(df_h)}개 결과", expanded=True):
                    if isinstance(df_h, pd.DataFrame) and not df_h.empty:
                        # 썸네일 카드 그리드 (3열)
                        cols_per_row = 3
                        rows = [df_h.iloc[i:i+cols_per_row] for i in range(0, len(df_h), cols_per_row)]
                        for row_df in rows:
                            card_cols = st.columns(cols_per_row)
                            for col, (_, row) in zip(card_cols, row_df.iterrows()):
                                with col:
                                    thumb = row.get("thumbnail", "")
                                    url   = row.get("video_url", "#")
                                    title = row.get("video_title", "")
                                    ch    = row.get("channel_title", "")
                                    views = row.get("view_count", 0)
                                    pub   = row.get("published_at", "")
                                    if thumb:
                                        st.markdown(
                                            f'<a href="{url}" target="_blank">'
                                            f'<img src="{thumb}" style="width:100%;border-radius:8px;margin-bottom:4px;">'
                                            f'</a>',
                                            unsafe_allow_html=True,
                                        )
                                    st.markdown(
                                        f'<a href="{url}" target="_blank" style="font-size:13px;font-weight:600;color:#fff;text-decoration:none;">'
                                        f'{title[:40]}{"…" if len(title)>40 else ""}</a>',
                                        unsafe_allow_html=True,
                                    )
                                    st.caption(f"📺 {ch}  ·  👁 {int(views):,}  ·  {pub}")
        # 채널 분석 캐시
        if st.session_state.get("ca_result"):
            found = True
            st.markdown("### 🔍 채널 분석 기록")
            r = st.session_state["ca_result"]
            ch = r.get("ch_snip", {})
            stats = r.get("ch_stats", {})
            st.markdown(
                f"**{ch.get('title', '채널명 없음')}**  ·  "
                f"구독자 {int(stats.get('subscriberCount') or 0):,}  ·  "
                f"총 조회수 {int(stats.get('viewCount') or 0):,}"
            )
        if not found:
            st.info("아직 분석 기록이 없습니다. 채널·영상 분석 또는 핫플리 트렌드를 먼저 실행해보세요.")

    # 평가 가이드라인
    elif nav == "평가 가이드라인":
        st.title("📋 평가 가이드라인")
        st.caption("레퍼런스 영상의 점수 체계와 평가 기준을 안내합니다.")
        st.divider()
        with st.container(border=True):
            st.markdown("### 📊 합산 점수 체계 (총 100점)")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**🔢 정량 점수 (55점) — 자동 계산**")
                st.markdown(
                    "- 구독자 대비 조회수 비율 (≤ 30점)\n"
                    "- 시간당 조회수 · 바이럴 속도 (≤ 25점)"
                )
            with c2:
                st.markdown("**🧠 정성 점수 (45점) — Gemini AI**")
                st.markdown(
                    "- 댓글 반응 강도 (≤ 20점)\n"
                    "- 5070 세대 정서 환기력 (≤ 15점)\n"
                    "- 무대/연주 에너지 (≤ 10점)"
                )
        with st.container(border=True):
            st.markdown("### 🎯 검수 큐 기준")
            st.markdown(
                "- **합산 70점 이상** → 우선 승인 대상\n"
                "- **합산 50~70점** → 검토 후 판단\n"
                "- **합산 50점 미만** → 반려 권장\n"
                "- 조회/구독 **2배 이상** → 급상승 채널로 별도 관리"
            )
        with st.container(border=True):
            st.markdown("### ⚡ 핫플리 트렌드 스타일 분류")
            for style, kws in _HOTPLI_STYLE_KEYWORDS.items():
                st.markdown(f"- **{style}**: {', '.join(kws[:4])} 등")

    # API 연결
    elif nav == "API 연결":
        st.title("🔑 API 연결")
        st.caption("각 서비스의 API 키를 입력하고 저장하면 모든 세션에서 자동으로 불러옵니다.")
        st.divider()

        def _key_section(title: str, key_name: str, env_var: str, help_text: str, link: str) -> None:
            saved = SAVED_KEYS.get(key_name, "")
            current = os.getenv(env_var, "") or saved
            with st.container(border=True):
                st.markdown(f"#### {title}")
                st.caption(help_text)
                val = st.text_input(f"{title} 키", value=current, type="password", key=f"api_{key_name}")
                c1, c2 = st.columns(2)
                if c1.button("💾 저장", key=f"save_{key_name}", use_container_width=True):
                    if val.strip():
                        save_key(key_name, val.strip())
                        SAVED_KEYS[key_name] = val.strip()
                        st.success("저장되었습니다.")
                    else:
                        st.warning("키 값이 비어 있습니다.")
                if c2.button("🗑️ 해지", key=f"clear_{key_name}", use_container_width=True, disabled=not saved):
                    clear_key(key_name)
                    SAVED_KEYS.pop(key_name, None)
                    st.info("삭제되었습니다.")
                    st.rerun()
                st.caption(f"발급: {link}")

        _key_section(
            "🎬 YouTube Data API v3", "youtube", "YOUTUBE_API_KEY",
            "레퍼런스 발굴·핫플리 트렌드·채널 분석에 사용됩니다.",
            "console.cloud.google.com",
        )
        _key_section(
            "🤖 Gemini API", "gemini", "GEMINI_API_KEY",
            "정성 점수 채점·역설계·AI 스토리텔링에 사용됩니다.",
            "aistudio.google.com/app/apikey",
        )
        _key_section(
            "💬 OpenAI API", "openai", "OPENAI_API_KEY",
            "Whisper 가사 동기화·AI 스토리텔링(대체)에 사용됩니다.",
            "platform.openai.com/api-keys",
        )
        _key_section(
            "📸 Pexels API", "pexels", "PEXELS_API_KEY",
            "스톡 이미지·동영상 검색에 사용됩니다. 무료 플랜으로도 충분합니다.",
            "www.pexels.com/api",
        )

    # 레퍼런스 채널 모니터
    elif nav == "레퍼런스 채널":
        st.title("📡 레퍼런스 채널 모니터")
        st.caption("Suno 제작 참고 채널을 장르별로 저장하고, 최신 업로드를 한눈에 모니터링합니다.")
        render_reference_monitor_tab()

    # 스톡 미디어
    elif nav == "스톡 미디어":
        render_stock_media_tab()

    # 음악 만들기
    elif nav == "음악 만들기":
        st.title("🎵 음악 만들기")
        tab_suno_gen, tab_money, tab_plan, tab_story, tab_studio, tab_rev, tab_sync, tab_review = st.tabs([
            "🎵 Suno 곡 생성",
            "💰 머니코드",
            "🏗️ AI 채널 기획안",
            "✍️ AI 스토리텔링 & 가사 생성",
            "🎚️ Suno 프롬프트 스튜디오",
            "🔎 곡 역설계",
            "🎤 가사 자동 동기화 (SRT)",
            "🙋 검수 큐",
        ])
        with tab_suno_gen: render_suno_generator_tab()
        with tab_money:   render_money_code_tab()
        with tab_plan:    render_channel_planning_tab()
        with tab_story:   render_storytelling_tab()
        with tab_studio:  render_suno_studio_tab()
        with tab_rev:     render_reverse_tab()
        with tab_sync:    render_sync_tab()
        with tab_review:  render_review_tab()

    # 영상 만들기
    elif nav == "영상 만들기":
        st.title("🎬 영상 만들기")
        tab_compose, tab_jobs = st.tabs(["🎬 영상 합성 (인코딩)", "📦 인코딩 잡"])
        with tab_compose: render_compose_tab()
        with tab_jobs:    render_jobs_tab()

    # 메타데이터
    elif nav == "메타데이터":
        st.title("🗂️ 메타데이터")
        render_title_lab_tab()


if __name__ == "__main__":
    main()
