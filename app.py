"""
급상승 레퍼런스 채널 발굴 대시보드 (Trending Reference Channel Discovery Dashboard)

YouTube Data API v3 를 사용해 특정 키워드(상황/감정 기반)로 최근 N일 내 업로드된
영상을 검색하고, '구독자 수 대비 조회수' 비율이 폭발적인 신규/소형 채널만 필터링해
리스트업하는 Streamlit 대시보드입니다.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import isodate
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

DEFAULT_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

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


def main() -> None:
    st.set_page_config(
        page_title="급상승 레퍼런스 채널 발굴",
        page_icon="🎵",
        layout="wide",
    )

    st.title("🎵 급상승 레퍼런스 채널 발굴 대시보드")
    st.caption(
        "YouTube Data API v3 기반. 상황/감정 키워드로 최근 업로드된 영상 중 "
        "'구독자 수 대비 조회수'가 폭발적인 신규 채널을 찾아냅니다."
    )

    cfg = render_sidebar()
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


if __name__ == "__main__":
    main()
