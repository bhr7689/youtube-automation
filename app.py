"""
급상승 레퍼런스 채널 발굴 대시보드 (Trending Reference Channel Discovery Dashboard)

YouTube Data API v3 를 사용해 특정 키워드(상황/감정 기반)로 최근 N일 내 업로드된
영상을 검색하고, '구독자 수 대비 조회수' 비율이 폭발적인 신규/소형 채널만 필터링해
리스트업하는 Streamlit 대시보드입니다.
"""

from __future__ import annotations

import io
import os
import random
import re
import shutil
import subprocess
import tempfile
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

from media_core import (
    concat_audio_files,
    encode_music_video,
    generate_srt,
)
from media_core import ffprobe_duration as _ffprobe_duration
from media_core import find_ffmpeg as _find_ffmpeg
from media_core import fmt_duration as _fmt_duration
from media_core import format_srt_time as _format_srt_time

import suno_studio
import recipes
import analyzer
import store
import score as scorer

load_dotenv()

DEFAULT_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

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
        df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
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


def render_sidebar() -> SearchConfig | None:
    st.sidebar.header("🔍 검색 설정")

    api_key = st.sidebar.text_input(
        "YouTube Data API v3 키",
        value=DEFAULT_API_KEY,
        type="password",
        help="https://console.cloud.google.com/ 에서 발급. .env 에 YOUTUBE_API_KEY 로 저장 가능.",
    )

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
    st.sidebar.subheader("⚙️ 고급")
    region = st.sidebar.text_input("지역 코드 (ISO 3166-1)", value="KR")
    language = st.sidebar.text_input("언어 코드 (예: ko, en, ja)", value="ko")
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
        display_cols = [
            "video_title",
            "channel_title",
            "subscriber_count",
            "view_count",
            "view_sub_ratio",
            "like_count",
            "comment_count",
            "published_at",
            "duration_sec",
            "video_url",
            "channel_url",
        ]
        st.dataframe(
            filtered[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "video_url": st.column_config.LinkColumn("영상", display_text="열기"),
                "channel_url": st.column_config.LinkColumn("채널", display_text="열기"),
                "subscriber_count": st.column_config.NumberColumn(format="%d"),
                "view_count": st.column_config.NumberColumn(format="%d"),
                "view_sub_ratio": st.column_config.NumberColumn(format="%.2f"),
                "published_at": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

        st.download_button(
            "📥 CSV 다운로드",
            data=filtered.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"breakout_channels_{datetime.now():%Y%m%d_%H%M%S}.csv",
            mime="text/csv",
        )

    render_title_patterns(filtered, df)
    render_narrative(filtered, df)
    render_recommendations(filtered, df, cfg)
    render_thumbnails(filtered, df, cfg)

    with st.expander("🔬 전체 검색 결과 보기 (필터 적용 전)"):
        st.dataframe(df, use_container_width=True, hide_index=True)


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
            with st.expander("이 제목이 만들어진 근거", expanded=False):
                st.code(rec["template"], language=None)
                st.json(rec["values"])

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


def render_discovery_tab() -> None:
    """기존의 '레퍼런스 발굴' 화면 — 사이드바 + 결과 표 + 분석 + 추천 + 썸네일."""
    st.caption(
        "YouTube Data API v3 기반. 상황/감정 키워드로 최근 업로드된 영상 중 "
        "'구독자 수 대비 조회수'가 폭발적인 신규 채널을 찾아냅니다."
    )

    new_cfg = render_sidebar()
    if new_cfg is not None:
        st.session_state.active_cfg = new_cfg
    cfg = st.session_state.get("active_cfg")
    if cfg is None:
        st.info("👈 사이드바에서 키워드와 필터를 설정한 뒤 **발굴 시작**을 눌러주세요.")
        return

    try:
        with st.spinner("YouTube API 호출 및 분석 중..."):
            df = run_pipeline(cfg)
    except HttpError as e:
        st.error(f"YouTube API 오류: {e}")
        return
    except Exception as e:
        st.error(f"실행 중 오류: {e}")
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


def render_compose_tab() -> None:
    st.subheader("🎬 영상 합성 (MP3 + 배경 → MP4 인코딩)")
    st.caption(
        "직접 만든 곡들을 이어붙여 1시간/3시간/4시간 영상으로 합성하고, "
        "원하면 곡별 가사를 타임라인에 정렬한 SRT 자막까지 함께 만들 수 있습니다."
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

    audio_files = st.file_uploader(
        "🎵 음악 파일 (여러 개 가능 — 업로드한 순서대로 이어붙여집니다)",
        type=list(AUDIO_EXTS),
        accept_multiple_files=True,
        key="compose_audio_multi",
        help="여러 곡을 올리면 ffmpeg concat 으로 한 트랙으로 결합한 뒤 영상에 입힙니다.",
    )
    visual_file = st.file_uploader(
        "🖼️ 배경 영상 또는 이미지 (필수, 1개)",
        type=list(VIDEO_IMAGE_EXTS),
        key="compose_visual",
        help="MP4/MOV 등 영상, 또는 PNG/JPG 같은 정지 이미지 한 장. "
             "영상이 오디오보다 짧으면 자동으로 루프됩니다.",
    )

    # ---- 곡 리스트 + 길이 미리보기 ----
    track_metas: list[dict] = []
    if audio_files:
        st.markdown("##### 📋 업로드된 트랙")
        # 임시 디렉토리 하나를 세션 동안 재사용하지 않고, 길이 확인을 위해
        # 매 렌더마다 짧게 떴다 사라지는 임시 파일로 ffprobe 만 돌린다.
        probe_dir = tempfile.mkdtemp(prefix="ytmusic_probe_")
        try:
            total = 0.0
            for idx, f in enumerate(audio_files, 1):
                pth = os.path.join(probe_dir, f.name)
                with open(pth, "wb") as fp:
                    fp.write(f.getbuffer())
                dur = _ffprobe_duration(pth) or 0.0
                total += dur
                track_metas.append({"name": f.name, "duration": dur, "index": idx})
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "#": m["index"],
                            "파일": m["name"],
                            "길이": _fmt_duration(m["duration"]),
                        }
                        for m in track_metas
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(f"합산 길이: **{_fmt_duration(total)}**  ·  {len(audio_files)}곡")
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)

    # ---- 곡별 가사 (SRT 생성용) ----
    st.markdown("##### 📝 곡별 가사 (선택 — 입력 시 SRT 자막을 함께 생성)")
    st.caption(
        "한 줄에 한 자막 라인. 각 트랙 안에서는 라인을 균등 분배하고, "
        "트랙 간에는 누적 타임스탬프로 이어 붙입니다. "
        "필요하면 생성된 SRT 를 텍스트 에디터에서 수동 미세조정하세요."
    )
    lyrics_by_track: dict[int, str] = {}
    if audio_files:
        for m in track_metas:
            with st.expander(
                f"#{m['index']} {m['name']}  ·  {_fmt_duration(m['duration'])}",
                expanded=False,
            ):
                lyrics_by_track[m["index"]] = st.text_area(
                    "가사 (한 줄 = 한 자막 라인)",
                    value="",
                    height=180,
                    key=f"compose_lyrics_{m['index']}",
                    label_visibility="collapsed",
                )

    # ---- 인코딩 옵션 ----
    st.markdown("##### ⚙️ 인코딩 옵션")
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

    col_a, col_b = st.columns(2)
    with col_a:
        burn_subs = st.checkbox(
            "자막을 영상에 굽기 (Burn-in)",
            value=False,
            key="compose_burn_subs",
            help="체크하면 영상 픽셀에 가사가 직접 새겨집니다. 끄면 SRT 가 별도 파일로만 나와, "
                 "유튜브 업로드 시 자막 트랙으로 따로 첨부하거나 시청자가 토글 가능.",
        )
    with col_b:
        make_srt = st.checkbox(
            "SRT 자막 파일 생성",
            value=True,
            key="compose_make_srt",
            help="가사가 비어 있는 트랙은 자동으로 스킵됩니다.",
        )

    run = st.button(
        "🚀 인코딩 시작",
        type="primary",
        use_container_width=True,
        key="compose_run",
    )

    if not run:
        if st.session_state.get("compose_output"):
            st.info("이전 인코딩 결과가 아래에 남아 있습니다.")
            _render_compose_result()
        return

    if not audio_files or not visual_file:
        st.error("음악(1개 이상)과 배경 파일을 모두 업로드해주세요.")
        return

    workdir = tempfile.mkdtemp(prefix="ytmusic_compose_")
    audio_paths: list[str] = []
    for f in audio_files:
        p = os.path.join(workdir, f.name)
        with open(p, "wb") as fp:
            fp.write(f.getbuffer())
        audio_paths.append(p)

    visual_path = os.path.join(workdir, visual_file.name)
    with open(visual_path, "wb") as fp:
        fp.write(visual_file.getbuffer())

    # 1) 다중 트랙이면 먼저 오디오 concat.
    combined_audio = os.path.join(workdir, "combined.m4a")
    if len(audio_paths) > 1:
        with st.spinner(f"🎚️ 오디오 {len(audio_paths)}곡 이어붙이는 중..."):
            ok, log = concat_audio_files(audio_paths, combined_audio, bitrate=audio_bitrate)
        if not ok:
            st.error("오디오 이어붙이기 실패")
            with st.expander("ffmpeg 로그", expanded=True):
                st.code(log or "(없음)", language=None)
            shutil.rmtree(workdir, ignore_errors=True)
            return
    else:
        combined_audio = audio_paths[0]

    # 2) 길이 측정 + SRT 생성.
    per_track_durations = [_ffprobe_duration(p) or 0.0 for p in audio_paths]
    total_duration = sum(per_track_durations) or _ffprobe_duration(combined_audio)

    srt_path: str | None = None
    srt_content = ""
    if make_srt and any(lyrics_by_track.values()):
        tracks_for_srt = [
            {
                "title": audio_files[i].name,
                "duration": per_track_durations[i],
                "lyrics_lines": (lyrics_by_track.get(i + 1, "") or "").splitlines(),
            }
            for i in range(len(audio_files))
        ]
        srt_content = generate_srt(tracks_for_srt)
        if srt_content.strip():
            srt_path = os.path.join(workdir, "lyrics.srt")
            with open(srt_path, "w", encoding="utf-8") as fp:
                fp.write(srt_content)

    # 3) 영상 인코딩.
    is_image = visual_file.name.lower().endswith(IMAGE_EXTS)
    output_path = os.path.join(workdir, "output.mp4")
    spinner_msg = (
        f"🎬 ffmpeg 인코딩 중... (오디오 {_fmt_duration(total_duration)}). "
        "3~4시간 영상은 1080p 기준 10~30분 이상 걸릴 수 있습니다."
    )
    with st.spinner(spinner_msg):
        ok, log = encode_music_video(
            combined_audio, visual_path, output_path,
            is_image=is_image,
            resolution=resolution,
            audio_bitrate=audio_bitrate,
            crf=int(crf),
            fade_seconds=float(fade),
            audio_duration=total_duration,
            subtitles_path=srt_path if burn_subs else None,
        )

    if not ok or not os.path.exists(output_path):
        st.error("인코딩에 실패했습니다. 아래 ffmpeg 로그를 확인해주세요.")
        with st.expander("ffmpeg stderr 로그", expanded=True):
            st.code(log or "(로그 없음)", language=None)
        shutil.rmtree(workdir, ignore_errors=True)
        return

    file_size_mb = os.path.getsize(output_path) / 1024 / 1024
    st.session_state["compose_output"] = {
        "path": output_path,
        "srt_path": srt_path,
        "srt_content": srt_content,
        "workdir": workdir,
        "size_mb": round(file_size_mb, 1),
        "duration": total_duration,
        "is_image": is_image,
        "resolution": resolution,
        "track_count": len(audio_files),
        "burned": bool(burn_subs and srt_path),
    }
    st.success(
        f"✅ 인코딩 완료 — {file_size_mb:.1f} MB · "
        f"{resolution} · 길이 {_fmt_duration(total_duration)} · {len(audio_files)}곡"
        + ("  · 자막 burn-in" if burn_subs and srt_path else "")
    )
    _render_compose_result()


def _render_compose_result() -> None:
    info = st.session_state.get("compose_output")
    if not info:
        return
    path = info["path"]
    if not os.path.exists(path):
        st.warning("이전 결과 파일이 더 이상 존재하지 않습니다 (임시 디렉터리 정리됨).")
        st.session_state.pop("compose_output", None)
        return

    meta_cols = st.columns(3)
    meta_cols[0].metric("파일 크기", f"{info['size_mb']} MB")
    meta_cols[1].metric("해상도", info["resolution"])
    if info["duration"]:
        meta_cols[2].metric(
            "오디오 길이",
            f"{int(info['duration'] // 60)}:{int(info['duration'] % 60):02d}",
        )

    # 결과 영상이 너무 크면 브라우저 미리보기가 무거워질 수 있어 500MB 이상은 스킵.
    if info["size_mb"] <= 500:
        try:
            st.video(path)
        except Exception:
            st.caption("미리보기를 표시할 수 없습니다. 다운로드해서 확인해주세요.")
    else:
        st.caption("📦 파일이 커서 인라인 미리보기는 생략합니다. 다운로드해서 확인해주세요.")

    dl_cols = st.columns(2)
    with dl_cols[0]:
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
    with dl_cols[1]:
        srt_content = info.get("srt_content") or ""
        if srt_content.strip():
            st.download_button(
                "📥 SRT 자막 다운로드",
                data=srt_content.encode("utf-8"),
                file_name=f"lyrics_{datetime.now():%Y%m%d_%H%M%S}.srt",
                mime="application/x-subrip",
                use_container_width=True,
                key="compose_download_srt",
                help="유튜브 업로드 시 자막 트랙으로 첨부하거나, "
                     "burn-in 옵션 없이 시청자가 토글 가능한 CC 로 사용하세요.",
            )
        else:
            st.caption("자막을 생성하지 않았거나 가사가 비어 있습니다.")

    if info.get("srt_content"):
        with st.expander("생성된 SRT 미리보기", expanded=False):
            preview = info["srt_content"]
            if len(preview) > 4000:
                preview = preview[:4000] + "\n\n...(이하 생략)"
            st.code(preview, language=None)

    if st.button("🗑️ 결과 비우기 (임시 파일 삭제)", key="compose_cleanup"):
        shutil.rmtree(info["workdir"], ignore_errors=True)
        st.session_state.pop("compose_output", None)
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return False, "오디오 압축이 15분 안에 끝나지 않았습니다."
    return proc.returncode == 0, (proc.stderr or "")[-2000:]


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
    lyrics_lines: list[str], segments: list[dict]
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
        # 만약 남은 라인이 있으면 마지막 구간 뒤에 짧게 이어붙임.
        if line_cursor < L:
            tail_start = float(segments[-1].get("end", 0) or 0)
            for line in lines[line_cursor:]:
                tail_end = tail_start + 3.0
                out.append(str(counter))
                out.append(
                    f"{_format_srt_time(tail_start)} --> {_format_srt_time(tail_end)}"
                )
                out.append(line)
                out.append("")
                counter += 1
                tail_start = tail_end

    return "\n".join(out).strip() + "\n"


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


def _render_waveform(waveform: dict) -> None:
    """파형 + SRT 자막 시작 마커 시각화 (matplotlib)."""
    raw_env = waveform.get("envelope")
    duration = float(waveform.get("duration", 0))
    srt_starts: list[float] = waveform.get("srt_starts", [])

    if raw_env is None or duration <= 0:
        st.info("파형 데이터를 사용할 수 없습니다.")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        st.info("파형 시각화: `pip install matplotlib` 후 재시도하세요.")
        return

    envelope = np.array(raw_env, dtype=np.float32)
    times = np.linspace(0, duration, len(envelope))

    fig, ax = plt.subplots(figsize=(12, 2.5))
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#161b22")
    ax.fill_between(times, envelope, alpha=0.75, color="#4CAF50")
    ax.plot(times, envelope, lw=0.5, color="#81C784", alpha=0.85)
    for t in srt_starts[:60]:
        if 0 <= t <= duration:
            ax.axvline(x=t, color="#FF7043", alpha=0.55, lw=0.9)
    ax.set_xlim(0, duration)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("시간 (초)", color="#aaa", fontsize=8)
    ax.tick_params(colors="#aaa", labelsize=7)
    for sp in ax.spines.values():
        sp.set_edgecolor("#333")
    ax.set_title("🎵 파형  ·  🔴 자막 시작 지점", color="#ddd", fontsize=9, pad=6)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def render_sync_tab() -> None:
    st.subheader("🎤 가사 자동 동기화 → SRT (CapCut/Premiere 임포트용)")
    st.caption(
        "음악(또는 영상)을 업로드하면 OpenAI Whisper 가 가사를 부르는 정확한 시점을 잡아 "
        "타임라인이 맞아떨어지는 SRT 자막을 만들어줍니다. 직접 쓴 가사를 정렬할 수도, "
        "Whisper 의 인식 결과를 그대로 받을 수도 있습니다."
    )

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        st.error("⚠️ ffmpeg 가 필요합니다. (오디오 추출/압축에 사용)")
        return

    default_key = os.getenv("OPENAI_API_KEY", "")
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

    audio_file = st.file_uploader(
        "🎵 음악 또는 영상 파일",
        type=["mp3", "wav", "m4a", "flac", "ogg", "aac", "mp4", "mov", "webm", "mkv"],
        key="sync_audio",
        help="MP4/MOV 영상이면 자동으로 오디오만 추출합니다. (25MB 초과 시 자동 압축)",
    )

    col1, col2 = st.columns(2)
    with col1:
        lang_options = [
            ("자동 감지", None), ("한국어 (ko)", "ko"), ("English (en)", "en"),
            ("日本語 (ja)", "ja"), ("中文 (zh)", "zh"),
        ]
        lang_pick = st.selectbox(
            "언어",
            options=lang_options,
            format_func=lambda x: x[0],
            index=1,
            key="sync_lang",
            help="명시하면 Whisper 정확도가 올라갑니다. 영문 가사면 'English' 선택.",
        )
    with col2:
        mode = st.radio(
            "동기화 모드",
            options=["내 가사를 Whisper 타이밍에 정렬", "Whisper 인식 결과만 사용"],
            index=0,
            key="sync_mode",
            help="가사 미입력 시 자동으로 'Whisper 결과만' 모드가 됩니다.",
        )

    user_lyrics = st.text_area(
        "📝 가사 (한 줄 = 한 자막 라인)",
        value="",
        height=240,
        key="sync_lyrics",
        placeholder=(
            "예시:\n"
            "오늘도 비가 내리네\n"
            "창문 너머 잿빛 하늘\n"
            "잠시 멈춰 너를 떠올려\n"
            "..."
        ),
        help="비워두면 Whisper 가 들은 그대로 SRT 가 만들어집니다. "
             "라인 수가 Whisper 구간 수와 달라도 자동으로 그룹화/분할됩니다.",
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
    if not api_key.strip():
        st.error("OpenAI API 키가 필요합니다. (Whisper 호출용)")
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

        # Whisper 25MB 한도 체크. 넘으면 압축.
        if os.path.getsize(audio_path) > WHISPER_MAX_BYTES:
            compressed = os.path.join(workdir, "compressed.mp3")
            with st.spinner(
                f"📦 파일이 25MB 를 넘어 mono 64kbps 로 압축 중... "
                f"({os.path.getsize(audio_path)/1024/1024:.1f}MB)"
            ):
                ok, log = compress_audio_for_whisper(audio_path, compressed)
            if not ok or os.path.getsize(compressed) > WHISPER_MAX_BYTES:
                st.error(
                    f"파일이 너무 큽니다 ({os.path.getsize(audio_path)/1024/1024:.1f}MB). "
                    "25MB 이하로 직접 줄여서 다시 시도해주세요."
                )
                return
            audio_path = compressed

        # Whisper 호출.
        size_mb = os.path.getsize(audio_path) / 1024 / 1024
        with st.spinner(
            f"🎤 Whisper 가 가사 타이밍을 분석 중... "
            f"(업로드 {size_mb:.1f}MB · 곡 길이의 5~15% 소요)"
        ):
            try:
                result = whisper_transcribe(
                    audio_path, api_key.strip(), language=lang_pick[1]
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

        if mode.startswith("Whisper 인식 결과만") or not user_lyrics.strip():
            srt_text = whisper_segments_to_srt(segments)
            method = f"Whisper 직접 변환 · {len(segments)}구간"
            line_count = len(segments)
        elif use_word_level:
            lyrics_lines = [ln for ln in user_lyrics.splitlines() if ln.strip()]
            srt_text = _word_level_align(lyrics_lines, words)
            line_count = len(lyrics_lines)
            method = f"Word 단위 정밀 정렬 · {line_count}줄 → {len(words)}단어"
        else:
            lyrics_lines = [ln for ln in user_lyrics.splitlines() if ln.strip()]
            srt_text = align_lyrics_to_segments(lyrics_lines, segments)
            line_count = len(lyrics_lines)
            method = f"가사 정렬 · 입력 {line_count}줄 → Whisper {len(segments)}구간"

        # 후렴구 보정 (가사 입력 모드에서만)
        if chorus_correct and user_lyrics.strip() and not mode.startswith("Whisper 인식 결과만"):
            srt_text = _chorus_correct_srt(srt_text)
            method += " + 후렴구 보정"

        # 파형 추출 (workdir 정리 전)
        with st.spinner("🎵 파형 추출 중... (시각화용)"):
            envelope, wav_dur = extract_waveform_data(audio_path)
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
        }
        st.success(f"✅ 동기화 완료 — {method}")
        _render_sync_result()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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

    # 파형 시각화
    waveform = info.get("waveform")
    if waveform and waveform.get("envelope"):
        with st.expander("📊 파형 + 자막 시작 마커", expanded=True):
            st.caption(
                "🟢 파형 · 🔴 자막 시작 지점 — 마커와 음악 피크가 잘 맞는지 확인하세요."
            )
            _render_waveform(waveform)

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
# Entry point
# ---------------------------------------------------------------------------


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


def main() -> None:
    st.set_page_config(
        page_title="유튜브 음악 채널 자동화",
        page_icon="🎵",
        layout="wide",
    )

    st.title("🎵 유튜브 음악 채널 자동화 대시보드")

    (tab_discovery, tab_story, tab_compose, tab_sync,
     tab_studio, tab_reverse, tab_review) = st.tabs(
        [
            "🔍 레퍼런스 발굴",
            "✍️ AI 스토리텔링 & 가사 생성",
            "🎬 영상 합성 (인코딩)",
            "🎤 가사 자동 동기화 (SRT)",
            "🎚️ Suno 프롬프트 스튜디오",
            "🔎 곡 역설계",
            "🙋 검수 큐",
        ]
    )
    with tab_discovery:
        render_discovery_tab()
    with tab_story:
        render_storytelling_tab()
    with tab_compose:
        render_compose_tab()
    with tab_sync:
        render_sync_tab()
    with tab_studio:
        render_suno_studio_tab()
    with tab_reverse:
        render_reverse_tab()
    with tab_review:
        render_review_tab()


if __name__ == "__main__":
    main()
