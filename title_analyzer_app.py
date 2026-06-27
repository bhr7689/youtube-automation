"""제목 알고리즘 분석 앱 — 유튜브 제목 여러 개를 넣으면 '잘 먹히는 공식'을 뽑아준다.

실행: streamlit run title_analyzer_app.py
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from typing import Optional

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

st.set_page_config(
    page_title="제목 알고리즘 분석",
    page_icon="🔬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
.main .block-container {
    max-width: 480px;
    padding-top: 1.2rem;
    padding-bottom: 6rem;
}
.stButton button {
    width: 100%;
    height: 3.4rem;
    font-size: 1.15rem;
    font-weight: 700;
    border-radius: 12px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: white;
    border: none;
}
.stButton button:hover {
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
    color: white;
}
h1 { font-size: 1.7rem !important; }
h2 { font-size: 1.25rem !important; margin-top: 1.5rem !important; }
h3 { font-size: 1.05rem !important; }

.metric-card {
    background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%);
    border: 1px solid #ddd6fe;
    border-radius: 14px;
    padding: 14px 16px;
    margin: 8px 0;
}
.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
}
.metric-label {
    font-size: 0.95rem;
    color: #4b5563;
    font-weight: 600;
}
.metric-value {
    font-size: 1.1rem;
    color: #4338ca;
    font-weight: 800;
}
.formula-card {
    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
    border: 2px solid #fbbf24;
    border-radius: 14px;
    padding: 16px 18px;
    margin: 14px 0;
    font-size: 1.05rem;
    line-height: 1.6;
    color: #78350f;
    font-weight: 600;
}
.tag {
    display: inline-block;
    padding: 4px 10px;
    margin: 3px;
    border-radius: 16px;
    background: #ede9fe;
    color: #5b21b6;
    font-size: 0.9rem;
    font-weight: 600;
}
.tag-hot {
    background: #fee2e2;
    color: #991b1b;
}
.score-big {
    font-size: 2.6rem;
    font-weight: 900;
    color: #4338ca;
    text-align: center;
    line-height: 1;
}
.score-sub {
    font-size: 0.9rem;
    text-align: center;
    color: #6b7280;
    margin-bottom: 12px;
}
.title-row {
    background: #fafafa;
    border-radius: 10px;
    padding: 10px 12px;
    margin: 6px 0;
    border-left: 4px solid #8b5cf6;
}
.title-row .t {
    font-size: 0.95rem;
    color: #1f2937;
    margin-bottom: 4px;
}
.title-row .s {
    font-size: 0.8rem;
    color: #6b7280;
}
.bar-bg {
    background: #f3f4f6;
    border-radius: 8px;
    height: 22px;
    margin: 4px 0;
    position: relative;
    overflow: hidden;
}
.bar-fg {
    background: linear-gradient(90deg, #8b5cf6, #6366f1);
    height: 100%;
    border-radius: 8px;
}
.bar-text {
    position: absolute;
    left: 10px;
    top: 0;
    line-height: 22px;
    font-size: 0.85rem;
    font-weight: 700;
    color: #1f2937;
    z-index: 2;
}
.caption-small {
    font-size: 0.82rem;
    color: #6b7280;
    text-align: center;
    margin-top: 14px;
}
.seed-card {
    background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
    border: 2px solid #10b981;
    border-radius: 14px;
    padding: 14px 16px;
    margin: 12px 0;
}
.seed-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: #065f46;
    margin-bottom: 8px;
}
.seed-chip {
    display: inline-block;
    padding: 8px 14px;
    margin: 4px;
    border-radius: 18px;
    background: #10b981;
    color: white;
    font-size: 1.0rem;
    font-weight: 700;
    box-shadow: 0 2px 4px rgba(16,185,129,0.3);
}
.seed-chip-2 {
    background: #34d399;
    font-size: 0.95rem;
}
.gem-row {
    background: linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%);
    border-radius: 10px;
    padding: 12px 14px;
    margin: 8px 0;
    border-left: 4px solid #f97316;
}
.gem-title {
    font-size: 0.98rem;
    color: #7c2d12;
    font-weight: 700;
    margin-bottom: 4px;
}
.gem-stats {
    font-size: 0.85rem;
    color: #9a3412;
}
.gem-ratio {
    display: inline-block;
    padding: 3px 9px;
    background: #f97316;
    color: white;
    border-radius: 12px;
    font-weight: 800;
    font-size: 0.85rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# 유틸: URL → 제목 추출 (YouTube oEmbed, API 키 불필요)
# ============================================================
YT_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(line: str) -> Optional[str]:
    m = YT_URL_RE.search(line)
    return m.group(1) if m else None


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_title_from_url(url: str) -> Optional[str]:
    """oEmbed로 제목 가져오기. 실패하면 None."""
    try:
        endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
            {"url": url, "format": "json"}
        )
        req = urllib.request.Request(endpoint, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("title")
    except Exception:
        return None


def parse_input_lines(raw: str) -> tuple[list[str], list[str]]:
    """입력 줄을 (제목 리스트, 실패한 URL 리스트)로 변환."""
    titles: list[str] = []
    failed: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        vid = extract_video_id(line)
        if vid or line.startswith("http"):
            url = line
            if vid and not line.startswith("http"):
                url = f"https://www.youtube.com/watch?v={vid}"
            title = fetch_title_from_url(url)
            if title:
                titles.append(title)
            else:
                failed.append(line)
        else:
            titles.append(line)
    return titles, failed


# ============================================================
# 카테고리 검색: YouTube Data API v3로 인기 영상 제목 수집
# ============================================================
def _parse_iso_duration_to_seconds(s: str) -> Optional[int]:
    """ISO 8601 'PT#H#M#S' → 초. 실패시 None."""
    if not s:
        return None
    try:
        import isodate
        return int(isodate.parse_duration(s).total_seconds())
    except Exception:
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
        if not m:
            return None
        h, mi, se = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mi * 60 + se


def _fetch_durations(youtube, video_ids: list[str]) -> dict[str, int]:
    """videos.list(contentDetails) 로 ID→초 매핑."""
    result: dict[str, int] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = youtube.videos().list(
            part="contentDetails", id=",".join(chunk), maxResults=50
        ).execute()
        for item in resp.get("items", []):
            vid = item.get("id")
            dur = item.get("contentDetails", {}).get("duration")
            secs = _parse_iso_duration_to_seconds(dur)
            if vid and secs is not None:
                result[vid] = secs
    return result


@st.cache_data(show_spinner=False, ttl=1800)
def search_videos_by_category(
    category: str,
    api_key: str,
    *,
    order: str = "viewCount",
    days: int = 30,
    max_results: int = 30,
    region_code: str = "KR",
    language: str = "ko",
) -> tuple[list[dict], Optional[str]]:
    """카테고리 검색 → [{title, duration_s, video_id}, ...]"""
    try:
        from googleapiclient.discovery import build
    except Exception as e:
        return [], f"googleapiclient 모듈이 없어요: {e}"

    try:
        from datetime import datetime, timedelta, timezone
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

        youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        videos: list[dict] = []
        page_token = None
        while len(videos) < max_results:
            page_size = min(50, max_results - len(videos))
            resp = youtube.search().list(
                part="snippet",
                q=category,
                type="video",
                order=order,
                publishedAfter=published_after,
                maxResults=page_size,
                regionCode=region_code or None,
                relevanceLanguage=language or None,
                pageToken=page_token,
            ).execute()
            for item in resp.get("items", []):
                vid = item.get("id", {}).get("videoId")
                title = item.get("snippet", {}).get("title")
                if vid and title:
                    videos.append({"video_id": vid, "title": title, "duration_s": None})
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        if videos:
            durations = _fetch_durations(youtube, [v["video_id"] for v in videos])
            for v in videos:
                v["duration_s"] = durations.get(v["video_id"])
        return videos, None
    except Exception as e:
        return [], str(e)


@st.cache_data(show_spinner=False, ttl=900)
def fetch_hidden_gems(
    api_key: str,
    *,
    region_code: str = "KR",
    language: str = "ko",
    days: int = 7,
    pool_size: int = 200,
    top_n: int = 30,
    min_ratio: float = 2.0,
    min_views: int = 5000,
    keyword: str = "",
) -> tuple[list[dict], Optional[str]]:
    """구독자 대비 조회수가 폭발하는 영상 발굴.

    1) 최근 N일 영상을 viewCount 정렬로 풀(pool) 수집
    2) videos.list 로 viewCount + duration + channelId
    3) channels.list 로 subscriberCount
    4) viral_ratio = viewCount / max(subscriberCount, 100) 계산
    5) min_ratio 이상 + min_views 이상만 남기고 ratio 내림차순 정렬, top_n 반환

    반환 dict: title, duration_s, video_id, channel_title, view_count,
              subscriber_count, viral_ratio
    """
    try:
        from googleapiclient.discovery import build
    except Exception as e:
        return [], f"googleapiclient 모듈이 없어요: {e}"

    try:
        from datetime import datetime, timedelta, timezone
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

        youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)

        # 1) 후보 ID 풀
        candidate_ids: list[str] = []
        page_token = None
        while len(candidate_ids) < pool_size:
            page_size = min(50, pool_size - len(candidate_ids))
            resp = youtube.search().list(
                part="id",
                q=keyword or "",
                type="video",
                order="viewCount",
                publishedAfter=published_after,
                maxResults=page_size,
                regionCode=region_code or None,
                relevanceLanguage=language or None,
                pageToken=page_token,
            ).execute()
            for item in resp.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid:
                    candidate_ids.append(vid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        if not candidate_ids:
            return [], None

        # 2) videos.list 로 통계+길이+채널
        videos_map: dict[str, dict] = {}
        for i in range(0, len(candidate_ids), 50):
            chunk = candidate_ids[i : i + 50]
            resp = youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(chunk),
                maxResults=50,
            ).execute()
            for item in resp.get("items", []):
                vid = item.get("id")
                snip = item.get("snippet", {})
                stat = item.get("statistics", {})
                cd = item.get("contentDetails", {})
                videos_map[vid] = {
                    "video_id": vid,
                    "title": snip.get("title", ""),
                    "channel_id": snip.get("channelId"),
                    "channel_title": snip.get("channelTitle", ""),
                    "published_at": (snip.get("publishedAt", "") or "")[:10],
                    "thumbnail_url": (
                        snip.get("thumbnails", {}).get("medium", {}).get("url")
                        or snip.get("thumbnails", {}).get("default", {}).get("url")
                        or ""
                    ),
                    "view_count": int(stat.get("viewCount", 0) or 0),
                    "like_count": int(stat.get("likeCount", 0) or 0),
                    "comment_count": int(stat.get("commentCount", 0) or 0),
                    "duration_s": _parse_iso_duration_to_seconds(cd.get("duration", "")),
                }

        # 3) channels.list 로 구독자 수 + 채널 영상 총 개수
        channel_ids = list({v["channel_id"] for v in videos_map.values() if v.get("channel_id")})
        sub_map: dict[str, int] = {}
        chan_videos_map: dict[str, int] = {}
        hidden_sub_channels: set[str] = set()
        for i in range(0, len(channel_ids), 50):
            chunk = channel_ids[i : i + 50]
            resp = youtube.channels().list(
                part="statistics", id=",".join(chunk), maxResults=50,
            ).execute()
            for item in resp.get("items", []):
                cid = item.get("id")
                stat = item.get("statistics", {})
                hidden = stat.get("hiddenSubscriberCount", False)
                chan_videos_map[cid] = int(stat.get("videoCount", 0) or 0)
                if hidden:
                    hidden_sub_channels.add(cid)
                    continue
                sub_map[cid] = int(stat.get("subscriberCount", 0) or 0)

        # 4) 비율 계산 + 필터
        results = []
        for v in videos_map.values():
            cid = v.get("channel_id")
            if not cid or cid in hidden_sub_channels:
                continue
            subs = sub_map.get(cid, 0)
            views = v["view_count"]
            if views < min_views:
                continue
            denom = max(subs, 100)
            ratio = views / denom
            if ratio < min_ratio:
                continue
            v["subscriber_count"] = subs
            v["channel_video_count"] = chan_videos_map.get(cid, 0)
            v["viral_ratio"] = ratio
            results.append(v)

        results.sort(key=lambda x: x["viral_ratio"], reverse=True)
        return results[:top_n], None
    except Exception as e:
        return [], str(e)


@st.cache_data(show_spinner=False, ttl=1800)
def fetch_trending_videos(
    api_key: str,
    *,
    region_code: str = "KR",
    max_results: int = 30,
    category_id: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """한국 인기 급상승 → [{title, duration_s, video_id}, ...]"""
    try:
        from googleapiclient.discovery import build
    except Exception as e:
        return [], f"googleapiclient 모듈이 없어요: {e}"

    try:
        youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        videos: list[dict] = []
        page_token = None
        while len(videos) < max_results:
            page_size = min(50, max_results - len(videos))
            resp = youtube.videos().list(
                part="snippet,contentDetails,statistics",
                chart="mostPopular",
                regionCode=region_code,
                maxResults=page_size,
                videoCategoryId=category_id,
                pageToken=page_token,
            ).execute()
            for item in resp.get("items", []):
                vid = item.get("id")
                snip = item.get("snippet", {})
                stat = item.get("statistics", {})
                title = snip.get("title")
                secs = _parse_iso_duration_to_seconds(
                    item.get("contentDetails", {}).get("duration", "")
                )
                if vid and title:
                    videos.append({
                        "video_id": vid, "title": title, "duration_s": secs,
                        "channel_title": snip.get("channelTitle", ""),
                        "channel_id": snip.get("channelId", ""),
                        "published_at": (snip.get("publishedAt", "") or "")[:10],
                        "thumbnail_url": (
                            snip.get("thumbnails", {}).get("medium", {}).get("url")
                            or snip.get("thumbnails", {}).get("default", {}).get("url")
                            or ""
                        ),
                        "view_count": int(stat.get("viewCount", 0) or 0),
                        "like_count": int(stat.get("likeCount", 0) or 0),
                        "comment_count": int(stat.get("commentCount", 0) or 0),
                    })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return videos, None
    except Exception as e:
        return [], str(e)


# ============================================================
# 분석 함수
# ============================================================
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F2FF"
    "]",
    flags=re.UNICODE,
)
NUMBER_RE = re.compile(r"\d+")
BRACKET_RE = re.compile(r"[\[\(\{【〈《][^\]\)\}】〉》]+[\]\)\}】〉》]")
HANGUL_WORD_RE = re.compile(r"[가-힣]+")
ENG_WORD_RE = re.compile(r"[A-Za-z]+")

STOPWORDS = {
    "그", "이", "저", "것", "수", "들", "더", "또", "및", "위", "왜",
    "the", "a", "an", "of", "to", "in", "on", "for", "with", "and", "or",
    "official", "mv", "live", "ver", "version",
}

HOOK_WORDS = [
    "충격", "역대", "최고", "최초", "단독", "공개", "라이브", "신곡",
    "감동", "눈물", "전설", "명곡", "원조", "1위", "TOP", "BEST",
    "리메이크", "신청곡", "이별", "사랑", "엄마", "아빠", "고향",
    "트로트", "발라드", "메들리", "효도",
]


def analyze_titles(titles: list[str]) -> dict:
    if not titles:
        return {}

    lengths = [len(t) for t in titles]
    has_emoji = [bool(EMOJI_RE.search(t)) for t in titles]
    has_number = [bool(NUMBER_RE.search(t)) for t in titles]
    has_bracket = [bool(BRACKET_RE.search(t)) for t in titles]
    has_excl = [("!" in t) for t in titles]
    has_quest = [("?" in t) for t in titles]
    has_pipe = [any(c in t for c in "|｜/┃") for t in titles]
    has_hyphen = [any(c in t for c in "-—–") for t in titles]

    all_emojis = []
    for t in titles:
        all_emojis.extend(EMOJI_RE.findall(t))
    emoji_top = Counter(all_emojis).most_common(8)

    word_counter: Counter[str] = Counter()
    for t in titles:
        for w in HANGUL_WORD_RE.findall(t):
            if len(w) >= 2 and w not in STOPWORDS:
                word_counter[w] += 1
        for w in ENG_WORD_RE.findall(t):
            wl = w.lower()
            if len(wl) >= 2 and wl not in STOPWORDS:
                word_counter[wl] += 1

    bracket_contents = []
    for t in titles:
        for m in BRACKET_RE.findall(t):
            inner = re.sub(r"[\[\(\{【〈《\]\)\}】〉》]", "", m).strip()
            if inner:
                bracket_contents.append(inner)
    bracket_top = Counter(bracket_contents).most_common(6)

    hook_hits = Counter()
    for t in titles:
        for hw in HOOK_WORDS:
            if hw.lower() in t.lower():
                hook_hits[hw] += 1

    first_words = []
    for t in titles:
        clean = re.sub(r"^[\[\(\{【〈《][^\]\)\}】〉》]+[\]\)\}】〉》]\s*", "", t)
        clean = EMOJI_RE.sub("", clean).strip()
        first = clean.split()[0] if clean.split() else ""
        if first:
            first_words.append(first)
    first_top = Counter(first_words).most_common(5)

    n = len(titles)
    return {
        "n": n,
        "len_avg": sum(lengths) / n,
        "len_min": min(lengths),
        "len_max": max(lengths),
        "emoji_pct": sum(has_emoji) / n * 100,
        "number_pct": sum(has_number) / n * 100,
        "bracket_pct": sum(has_bracket) / n * 100,
        "excl_pct": sum(has_excl) / n * 100,
        "quest_pct": sum(has_quest) / n * 100,
        "pipe_pct": sum(has_pipe) / n * 100,
        "hyphen_pct": sum(has_hyphen) / n * 100,
        "emoji_top": emoji_top,
        "word_top": word_counter.most_common(12),
        "bracket_top": bracket_top,
        "hook_hits": hook_hits.most_common(8),
        "first_top": first_top,
        "titles": titles,
        "lengths": lengths,
    }


def build_formula(r: dict) -> tuple[str, list[str]]:
    """분석 결과 → '제목 공식' 한 줄 + 핵심 인사이트 리스트."""
    parts = []
    insights = []

    if r["bracket_pct"] >= 40 and r["bracket_top"]:
        top_bracket = r["bracket_top"][0][0]
        parts.append(f"[{top_bracket}]")
        insights.append(f"📦 대괄호로 카테고리 표시가 {r['bracket_pct']:.0f}%")

    if r["emoji_pct"] >= 30 and r["emoji_top"]:
        top_em = r["emoji_top"][0][0]
        parts.append(top_em)
        insights.append(f"✨ 이모지 사용률 {r['emoji_pct']:.0f}% — 가장 인기 {top_em}")

    if r["hook_hits"]:
        hot_word = r["hook_hits"][0][0]
        parts.append(hot_word)
        insights.append(f"🔥 후킹 단어 TOP: {hot_word} ({r['hook_hits'][0][1]}번)")

    if r["word_top"]:
        core_word = r["word_top"][0][0]
        if core_word not in [p for p in parts]:
            parts.append(core_word)

    if r["number_pct"] >= 40:
        parts.append("(숫자N)")
        insights.append(f"🔢 숫자 사용률 {r['number_pct']:.0f}% — 순위/연도/개수")

    if r["pipe_pct"] >= 30:
        parts.append("| 부제")
        insights.append(f"➖ 구분자(|/) 사용률 {r['pipe_pct']:.0f}%")

    if r["excl_pct"] >= 30:
        parts.append("!")
    if r["quest_pct"] >= 20:
        insights.append(f"❓ 의문형 제목 {r['quest_pct']:.0f}%")

    insights.append(f"📏 평균 길이 {r['len_avg']:.0f}자 (최소 {r['len_min']} / 최대 {r['len_max']})")

    formula = " ".join(parts) if parts else "(뚜렷한 패턴이 적어요 — 더 많은 제목을 넣어보세요)"
    return formula, insights


# ============================================================
# 시드 키워드 후보 추출 (단어 + 2-gram 결합)
# ============================================================
SEED_BLOCKLIST = {
    # 영어/공통
    "ft", "feat", "official", "audio", "video", "mv", "live", "lyrics",
    "shorts", "short", "youtube", "vlog", "ep", "full", "ver", "version",
    "the", "and", "for", "with", "you", "your", "are", "was", "were",
    "this", "that", "but", "from", "have", "has", "not", "all", "new",
    # 한국어
    "그녀의", "그리고", "이렇게", "그래서", "내가",
    # 스페인어/포르투갈어
    "el", "la", "los", "las", "de", "en", "del", "que", "por",
    "para", "con", "una", "uno", "se", "lo", "su", "mi", "te",
    "do", "da", "os", "as", "no", "na",
    # 일본어 조사/공통
    "の", "は", "を", "に", "が", "と", "で", "へ", "や", "も",
    # 힌디어/인도
    "है", "के", "की", "का", "में", "और", "से", "को",
}

# 유니코드 친화 단어 정규식: 모든 알파벳/한자/한글/히라가나/카타가나/힌디/태국 등을 잡음 (숫자/언더스코어 제외).
WORD_RE = re.compile(r"[^\W\d_]+", flags=re.UNICODE)


def extract_seed_keywords(titles: list[str], top_n: int = 12) -> list[tuple[str, int]]:
    """제목에서 알고리즘 시드 후보를 추출 (단어 + 인접 2-gram).
    한국어/영어/일본어/힌디/스페인어/포르투갈어 모두 작동."""
    if not titles:
        return []
    word_c: Counter[str] = Counter()
    bigram_c: Counter[str] = Counter()
    for t in titles:
        tokens: list[str] = []
        for m in WORD_RE.findall(t):
            ml = m.lower()
            if len(ml) < 2:
                continue
            if ml in STOPWORDS or ml in SEED_BLOCKLIST:
                continue
            tokens.append(m if any(0xAC00 <= ord(c) <= 0xD7A3 or 0x3040 <= ord(c) <= 0x9FFF
                                    or 0x0900 <= ord(c) <= 0x097F or 0x0E00 <= ord(c) <= 0x0E7F
                                    for c in m) else ml)
        for tok in tokens:
            word_c[tok] += 1
        for a, b in zip(tokens, tokens[1:]):
            bigram_c[f"{a} {b}"] += 1

    seeds: list[tuple[str, int]] = []
    seen_terms: set[str] = set()
    # 2회 이상 등장한 2-gram을 우선 (구체적인 시드일수록 가치 높음)
    for term, c in bigram_c.most_common():
        if c < 2:
            break
        seeds.append((term, c))
        for w in term.split():
            seen_terms.add(w)
    for term, c in word_c.most_common():
        if c < 2:
            continue
        if term in seen_terms:
            continue
        seeds.append((term, c))
        seen_terms.add(term)
    seeds.sort(key=lambda x: x[1], reverse=True)
    return seeds[:top_n]


# ============================================================
# 결과 렌더링
# ============================================================
def render_seed_block(videos: list[dict]):
    """결과 최상단에 '시드 키워드 후보' 카드 — 다음 영상 제목에 바로 쓰는 핵심 출력."""
    titles = [v["title"] for v in videos]
    seeds = extract_seed_keywords(titles, top_n=12)
    if not seeds:
        return
    chips = ""
    max_c = seeds[0][1]
    for term, c in seeds:
        cls = "seed-chip" if c >= max(2, max_c * 0.6) else "seed-chip seed-chip-2"
        chips += f"<span class='{cls}'>{term} · {c}</span>"
    st.markdown(
        "<div class='seed-card'>"
        "<div class='seed-title'>🎯 시드 키워드 후보 — 이걸 다음 영상 제목에 써보세요</div>"
        f"{chips}"
        "</div>",
        unsafe_allow_html=True,
    )


def render_hidden_gems(videos: list[dict]):
    """히든 젬 영상 카드 — 채널/구독자/조회수/배수 표시."""
    if not videos or "viral_ratio" not in videos[0]:
        return
    st.markdown("### 💎 히든 젬 — 작은 채널인데 알고리즘이 밀어주는 영상")
    for v in videos:
        ratio = v.get("viral_ratio", 0)
        subs = v.get("subscriber_count", 0)
        views = v.get("view_count", 0)

        def fmt(n: int) -> str:
            if n >= 10_000_000:
                return f"{n/10_000_000:.1f}천만"
            if n >= 10_000:
                return f"{n/10_000:.1f}만"
            if n >= 1_000:
                return f"{n/1_000:.1f}K"
            return str(n)

        ratio_txt = f"⚡ {ratio:.0f}배" if ratio >= 1 else f"⚡ {ratio:.1f}배"
        st.markdown(
            f"<div class='gem-row'>"
            f"<div class='gem-title'>{v['title']}</div>"
            f"<div class='gem-stats'>"
            f"<span class='gem-ratio'>{ratio_txt}</span> &nbsp;"
            f"📺 {v.get('channel_title','')} · 구독자 {fmt(subs)} → 조회수 {fmt(views)}"
            f"</div></div>",
            unsafe_allow_html=True,
        )


def render_notion_save_panel(videos: list[dict], *, search_label: str,
                              default_main: str = "유튜브 플레이리스트",
                              default_middle: str = "", default_sub: str = ""):
    """결과 위에 'Notion에 저장' 패널 — 토큰·DB·카테고리 입력 + 버튼."""
    if not videos:
        return
    with st.expander(f"💾 이 결과 {len(videos)}개 영상을 Notion에 저장", expanded=False):
        env_token = os.environ.get("NOTION_TOKEN", "").strip()
        env_db = os.environ.get("NOTION_REFERENCE_VIDEOS_DB_ID", "").strip()

        notion_token = st.text_input(
            "Notion Token", value=env_token, type="password",
            help=".env 에 NOTION_TOKEN 적어두면 자동 채워져요.",
        )
        notion_db = st.text_input(
            "Reference Videos DB ID", value=env_db,
            help="DB 페이지 URL 의 32자 hex (예: notion.so/2026/abcd1234.../?v=… 의 abcd1234…)",
        )
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            main_cat = st.text_input("대 카테고리", value=default_main, key="save_main")
        with col_b:
            middle_cat = st.text_input("중 카테고리", value=default_middle, key="save_middle")
        with col_c:
            sub_cat = st.text_input("소 카테고리", value=default_sub, key="save_sub")
        kw_label = st.text_input(
            "Search Keyword 라벨", value=search_label,
            help="이 결과가 어떤 검색 조건으로 나온 것인지 라벨링하는 텍스트. Notion에서 필터·정렬용.",
        )

        if st.button("💾 Notion에 저장하기", key=f"notion_save_{search_label}", type="primary"):
            if not notion_token or not notion_db:
                st.error("Notion Token 과 DB ID 를 입력해주세요.")
                return
            try:
                from keyword_collector import upsert_videos
            except Exception as e:
                st.error(f"keyword_collector import 실패: {e}")
                return
            kw_row = {
                "keyword": kw_label,
                "main": main_cat or None,
                "middle": middle_cat or None,
                "sub": sub_cat or None,
            }
            with st.spinner(f"{len(videos)}개 영상 Notion 저장 중…"):
                try:
                    created, skipped = upsert_videos(
                        notion_token, notion_db, videos, kw_row, kw_label,
                    )
                except Exception as e:
                    st.error(f"저장 실패: {e}")
                    return
            st.success(f"✅ 신규 {created}건 · 기존 업데이트 {skipped}건 저장 완료")
            st.balloons()


def render_videos_table(videos: list[dict], title: str = ""):
    """HiView 스타일의 표 — 썸네일/제목/조회수/구독자/실적도/게시일/좋아요/댓글/길이/채널."""
    if not videos:
        return
    try:
        import pandas as pd
    except Exception:
        st.warning("pandas 가 없어서 표 모드를 못 띄워요. 카드 모드로 보세요.")
        return

    has_lang = any(v.get("search_lang_label") for v in videos)
    rows = []
    for v in videos:
        dur = v.get("duration_s")
        if dur is not None:
            m, s = divmod(int(dur), 60)
            dur_txt = f"{m}:{s:02d}"
        else:
            dur_txt = "-"
        ratio = v.get("viral_ratio")
        row = {
            "썸네일": v.get("thumbnail_url", ""),
            "제목": v["title"],
            "🔗": f"https://www.youtube.com/watch?v={v.get('video_id','')}",
            "조회수": v.get("view_count") or 0,
            "구독자": v.get("subscriber_count") or 0,
            "⚡실적도": ratio if ratio else 0,
            "게시일": v.get("published_at", "") or "",
            "👍좋아요": v.get("like_count") or 0,
            "💬댓글": v.get("comment_count") or 0,
            "길이": dur_txt,
            "채널": v.get("channel_title", ""),
        }
        if has_lang:
            row["🌐 언어"] = v.get("search_lang_label", "")
            row["검색어"] = v.get("search_query", "")
        rows.append(row)

    df = pd.DataFrame(rows)
    if title:
        st.markdown(f"### {title}")
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        height=min(620, 80 + 70 * len(rows)),
        column_config={
            "썸네일": st.column_config.ImageColumn("썸네일", width="small"),
            "제목":   st.column_config.TextColumn("제목", width="large"),
            "🔗":    st.column_config.LinkColumn("🔗", display_text="열기", width="small"),
            "조회수": st.column_config.NumberColumn("조회수", format="%d"),
            "구독자": st.column_config.NumberColumn("구독자", format="%d"),
            "⚡실적도": st.column_config.NumberColumn("⚡실적도", format="%.1f배"),
            "게시일": st.column_config.TextColumn("게시일", width="small"),
            "👍좋아요": st.column_config.NumberColumn("👍좋아요", format="%d"),
            "💬댓글": st.column_config.NumberColumn("💬댓글", format="%d"),
            "길이":   st.column_config.TextColumn("길이", width="small"),
            "채널":   st.column_config.TextColumn("채널", width="medium"),
            "🌐 언어": st.column_config.TextColumn("🌐 언어", width="small"),
            "검색어": st.column_config.TextColumn("검색어", width="medium"),
        },
    )
    st.caption("💡 각 컬럼 헤더 클릭하면 정렬돼요. 🔗 '열기' 누르면 새 탭에서 영상이 뜹니다.")


def _render_bar(label: str, pct: float):
    st.markdown(
        f"<div class='bar-bg'><span class='bar-text'>{label} · {pct:.0f}%</span>"
        f"<div class='bar-fg' style='width:{min(pct,100):.0f}%'></div></div>",
        unsafe_allow_html=True,
    )


def render_analysis(videos: list[dict], section_label: str = "", *, color: str = "purple"):
    """videos: [{title, duration_s}] — 분석 결과 한 섹션을 렌더링."""
    titles = [v["title"] for v in videos]
    if len(titles) < 2:
        st.info(f"{section_label} — 영상이 {len(titles)}개라 패턴 분석은 건너뛸게요.")
        return

    r = analyze_titles(titles)

    if section_label:
        st.markdown(f"## {section_label}")
    st.markdown(
        f"<div class='score-big'>{r['n']}</div>"
        f"<div class='score-sub'>개 영상 제목 분석</div>",
        unsafe_allow_html=True,
    )

    formula, insights = build_formula(r)

    st.markdown("### 🎯 제목 공식")
    st.markdown(f"<div class='formula-card'>{formula}</div>", unsafe_allow_html=True)

    st.markdown("### 💎 핵심 인사이트")
    for ins in insights:
        st.markdown(f"- {ins}")

    st.markdown("### 📊 특수문자/요소 사용률")
    _render_bar("이모지", r["emoji_pct"])
    _render_bar("숫자", r["number_pct"])
    _render_bar("대괄호 [ ]", r["bracket_pct"])
    _render_bar("느낌표 !", r["excl_pct"])
    _render_bar("물음표 ?", r["quest_pct"])
    _render_bar("구분자 |/", r["pipe_pct"])

    if r["word_top"]:
        st.markdown("### 🔑 알고리즘이 댕겨오는 키워드 TOP")
        tags_html = ""
        max_count = r["word_top"][0][1]
        for w, c in r["word_top"]:
            hot = "tag-hot" if c >= max(2, max_count * 0.5) else ""
            tags_html += f"<span class='tag {hot}'>{w} · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["hook_hits"]:
        st.markdown("### 🔥 후킹 단어 (감정/매력 유발)")
        tags_html = ""
        for w, c in r["hook_hits"]:
            tags_html += f"<span class='tag tag-hot'>{w} · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["bracket_top"]:
        st.markdown("### 📦 대괄호 안에 자주 들어가는 말")
        tags_html = ""
        for w, c in r["bracket_top"]:
            tags_html += f"<span class='tag'>[{w}] · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["emoji_top"]:
        st.markdown("### ✨ 자주 쓰는 이모지")
        tags_html = ""
        for em, c in r["emoji_top"]:
            tags_html += f"<span class='tag'>{em} · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["first_top"]:
        st.markdown("### 👀 제목 첫 단어 패턴")
        tags_html = ""
        for w, c in r["first_top"]:
            tags_html += f"<span class='tag'>{w}… · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    with st.expander(f"📋 분석한 제목 {len(videos)}개 펼쳐보기"):
        sorted_videos = sorted(videos, key=lambda v: -len(v["title"]))
        for v in sorted_videos:
            t = v["title"]
            ln = len(t)
            dur = v.get("duration_s")
            if dur is not None:
                m, s = divmod(int(dur), 60)
                dur_txt = f" · ⏱ {m}:{s:02d}"
            else:
                dur_txt = ""
            st.markdown(
                f"<div class='title-row'><div class='t'>{t}</div>"
                f"<div class='s'>길이 {ln}자{dur_txt}</div></div>",
                unsafe_allow_html=True,
            )


def split_shorts_longs(videos: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(쇼츠 <60s, 롱폼 ≥60s, 길이 모름)"""
    shorts, longs, unknown = [], [], []
    for v in videos:
        d = v.get("duration_s")
        if d is None:
            unknown.append(v)
        elif d < 60:
            shorts.append(v)
        else:
            longs.append(v)
    return shorts, longs, unknown


def filter_by_length(videos: list[dict], length_mode: str) -> list[dict]:
    """length_mode: 'all' | 'shorts' | 'longs'"""
    if length_mode == "shorts":
        return [v for v in videos if (v.get("duration_s") or 99999) < 60]
    if length_mode == "longs":
        return [v for v in videos if (v.get("duration_s") or 0) >= 60]
    return videos


def render_with_split(videos: list[dict], length_mode: str, *,
                      show_gems: bool = False, view_mode: str = "table",
                      search_label: str = "", category_default: tuple = ("", "", "")):
    """선택한 길이 필터로 한 번 렌더링."""
    shorts, longs, unknown = split_shorts_longs(videos)
    has_dur = any(v.get("duration_s") is not None for v in videos)

    if has_dur:
        st.markdown(
            f"<div style='text-align:center;font-size:0.95rem;color:#6b7280;'>"
            f"수집 {len(videos)}개 · ⚡쇼츠 {len(shorts)} · 📹롱폼 {len(longs)}"
            + (f" · ❓길이모름 {len(unknown)}" if unknown else "")
            + "</div>",
            unsafe_allow_html=True,
        )

    filtered = filter_by_length(videos, length_mode)
    label = {"all": "🎬 전체", "shorts": "⚡ 쇼츠만 (60초 미만)", "longs": "📹 롱폼만 (60초 이상)"}[length_mode]

    if not filtered:
        st.warning(f"{label} 조건에 맞는 영상이 없어요. 다른 옵션으로 다시 시도해보세요.")
        return

    st.markdown("---")
    if search_label:
        m, mi, s = (category_default + ("", "", ""))[:3]
        render_notion_save_panel(
            filtered, search_label=search_label,
            default_main=m or "유튜브 플레이리스트",
            default_middle=mi, default_sub=s,
        )
    render_seed_block(filtered)

    if view_mode == "table":
        render_videos_table(filtered, title=f"📊 {label} · {len(filtered)}개")
    else:
        if show_gems:
            render_hidden_gems(filtered)
        render_analysis(filtered, label)


# ============================================================
# 글로벌 국가 프리셋
# ============================================================
COUNTRIES = [
    ("🇰🇷 한국",          "KR", "ko"),
    ("🇺🇸 미국 (영어)",    "US", "en"),
    ("🇬🇧 영국 (영어)",    "GB", "en"),
    ("🇯🇵 일본",          "JP", "ja"),
    ("🇮🇳 인도 (힌디)",    "IN", "hi"),
    ("🇮🇳 인도 (영어)",    "IN", "en"),
    ("🇲🇽 멕시코 (스페인어)", "MX", "es"),
    ("🇪🇸 스페인 (스페인어)", "ES", "es"),
    ("🇧🇷 브라질 (포르투갈어)", "BR", "pt"),
    ("🇩🇪 독일",          "DE", "de"),
    ("🇫🇷 프랑스",        "FR", "fr"),
    ("🇮🇩 인도네시아",     "ID", "id"),
    ("🇻🇳 베트남",        "VN", "vi"),
    ("🇹🇭 태국",          "TH", "th"),
    ("🇵🇭 필리핀 (영어)",  "PH", "en"),
]
COUNTRY_LABEL_TO_RL = {c[0]: (c[1], c[2]) for c in COUNTRIES}


# ============================================================
# 다국가 비교 렌더링 (🌍 공통 / 🏳️ 국가별 고유)
# ============================================================
def render_multi_country(results: dict[str, list[dict]], length_mode: str,
                          view_mode: str = "table",
                          search_label: str = "",
                          category_default: tuple = ("", "", "")):
    """results: {country_label: [videos]} — 국가별 시드 발굴 결과를 비교."""
    # 1) 길이 필터 적용
    filtered: dict[str, list[dict]] = {
        k: filter_by_length(v, length_mode) for k, v in results.items()
    }
    filtered = {k: v for k, v in filtered.items() if v}
    if not filtered:
        st.warning("선택한 길이 조건에 맞는 영상이 한 국가도 없어요.")
        return

    # 2) 국가별 시드 추출
    country_seeds: dict[str, list[tuple[str, int]]] = {
        c: extract_seed_keywords([v["title"] for v in vids], top_n=20)
        for c, vids in filtered.items()
    }

    # 3) 공통/고유 분리: 2개 이상 국가에서 등장하면 공통
    appear_in: dict[str, set[str]] = {}
    for c, seeds in country_seeds.items():
        for term, _ in seeds:
            appear_in.setdefault(term, set()).add(c)
    common_terms = sorted(
        [(t, cs) for t, cs in appear_in.items() if len(cs) >= 2],
        key=lambda x: (-len(x[1]), x[0]),
    )

    # 4) 헤더
    st.markdown("---")
    st.markdown(
        f"<div style='text-align:center;font-size:1.0rem;color:#4338ca;font-weight:700;'>"
        f"🌍 {len(filtered)}개국 비교 분석"
        "</div>",
        unsafe_allow_html=True,
    )

    # 5) 글로벌 공통 시드
    if common_terms:
        chips = ""
        for term, cs in common_terms[:15]:
            flags = "".join(c.split()[0] for c in sorted(cs))
            chips += (
                f"<span class='seed-chip'>{term} <span style='font-size:0.85em;opacity:0.8'>{flags}</span></span>"
            )
        st.markdown(
            "<div class='seed-card'>"
            "<div class='seed-title'>🌍 글로벌 공통 시드 — 2개국 이상에서 동시에 잡힌 키워드 (안전한 글로벌 제목)</div>"
            f"{chips}"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.info(
            "🌍 2개국 이상에서 공통으로 잡힌 시드가 없어요 — 카테고리 차이가 큰 결과예요."
        )

    # 6) 국가별 고유 시드 + 미니 분석 (또는 표) + 국가별 Notion 저장
    st.markdown("## 🏳️ 국가별 고유 시드 (현지화 제목용)")
    for country, vids in filtered.items():
        if search_label:
            m, mi, s = (category_default + ("", "", ""))[:3]
            render_notion_save_panel(
                vids,
                search_label=f"{search_label} · {country}",
                default_main=m or "유튜브 플레이리스트",
                default_middle=mi, default_sub=s,
            )
        seeds = country_seeds[country]
        unique = [(t, c) for t, c in seeds if len(appear_in.get(t, set())) == 1]
        with st.expander(f"{country} · 영상 {len(vids)}개 · 고유 시드 {len(unique)}개", expanded=True):
            if unique:
                chips = "".join(
                    f"<span class='seed-chip seed-chip-2'>{t} · {c}</span>"
                    for t, c in unique[:12]
                )
                st.markdown(chips, unsafe_allow_html=True)
            else:
                st.markdown(
                    "<span style='color:#6b7280;font-size:0.9rem;'>이 국가만의 고유 시드는 없어요 (공통 시드만 나옴)</span>",
                    unsafe_allow_html=True,
                )
            # 표 모드면 표, 카드 모드면 미니 인사이트
            if view_mode == "table":
                render_videos_table(vids)
            else:
                r = analyze_titles([v["title"] for v in vids])
                if r:
                    st.markdown(
                        f"<div style='font-size:0.88rem;color:#4b5563;margin-top:8px;'>"
                        f"📏 평균 {r['len_avg']:.0f}자 · ✨이모지 {r['emoji_pct']:.0f}% · "
                        f"🔢숫자 {r['number_pct']:.0f}% · 📦대괄호 {r['bracket_pct']:.0f}%"
                        "</div>",
                        unsafe_allow_html=True,
                    )


# ============================================================
# UI
# ============================================================
st.title("🔬 제목 알고리즘 분석")
st.markdown(
    "**시드 키워드를 모를 때** → 앱이 알고리즘이 밀어주는 키워드를 발굴해드려요.\n\n"
    "**시드를 알 때** → 그 키워드의 '제목 공식'을 뽑아드려요."
)

with st.expander("🤖 매일 자동 수집 + Notion 저장 켜는 법 (한 번만 셋업)"):
    st.markdown(
        "**자동 수집 흐름** — GitHub Actions 가 매일 새벽 정해진 시간에 사용자님이 "
        "Notion 의 'Search Keyword Master' DB에 등록한 ACTIVE 키워드들을 모두 검색해서, "
        "결과 영상을 'YouTube Reference Videos' DB에 한 줄씩 자동 저장해줘요.\n\n"
        "**셋업 4단계**\n"
        "1. Notion → Settings → Connections → '+ New integration' → token 복사\n"
        "2. Notion 에 DB 2개 만들기 (Search Keyword Master + YouTube Reference Videos). "
        "   두 DB 모두 우상단 ··· → Connections 에 방금 만든 integration 추가\n"
        "3. GitHub 저장소 → Settings → Secrets → 4개 등록:\n"
        "   `YOUTUBE_API_KEY` · `NOTION_TOKEN` · `NOTION_KEYWORD_MASTER_DB_ID` · "
        "`NOTION_REFERENCE_VIDEOS_DB_ID`\n"
        "4. GitHub 저장소 → Actions 탭 → '📚 키워드별 레퍼런스 영상 수집 (WF-1)' "
        "워크플로우 활성화. 매일 03:30 KST 자동 실행.\n\n"
        "**수동 저장**: 자동 수집을 안 켜도 결과 화면의 **💾 Notion에 저장** 버튼으로 "
        "지금 본 영상을 즉시 DB에 넣을 수 있어요. (Notion DB 만들기는 같은 셋업 필요)"
    )

mode = st.radio(
    "어떻게 분석할까요?",
    [
        "🌐 다국어 자동 번역 + 동시 검색 (글로벌 시야 ⭐)",
        "🪄 시드 키워드 자동 발굴 (추천)",
        "🔥 요즘 알고리즘 트렌드 키워드",
        "📂 카테고리로 자동 수집",
        "✍️ 제목/URL 직접 붙여넣기",
    ],
    horizontal=False,
    label_visibility="visible",
)

length_mode_label = st.radio(
    "어떤 길이로 분석할까요?",
    ["🎬 전체", "⚡ 쇼츠만 (60초 미만)", "📹 롱폼만 (60초 이상)"],
    horizontal=True,
    label_visibility="visible",
    help="유튜브 API 모드에서만 길이 필터가 작동해요. 직접 붙여넣기는 길이 정보가 없어 전체로 처리돼요.",
)
length_mode = (
    "shorts" if length_mode_label.startswith("⚡")
    else "longs" if length_mode_label.startswith("📹")
    else "all"
)

view_mode_label = st.radio(
    "결과를 어떻게 보여드릴까요?",
    ["📊 표 (정렬·비교 쉬움)", "🎴 카드 (시드 키워드 + 인사이트 상세)"],
    horizontal=True,
    label_visibility="visible",
    help="표 모드는 컬럼 헤더 클릭으로 정렬할 수 있어요. 카드 모드는 시드 키워드와 분석 인사이트까지 보여줘요.",
)
view_mode = "table" if view_mode_label.startswith("📊") else "card"

videos: list[dict] = []
go = False


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        st.warning("🔑 `YOUTUBE_API_KEY` 가 설정 안 됐어요. 아래에 임시로 넣어주세요.")
        key = st.text_input("YOUTUBE_API_KEY", type="password")
    return key


show_gems_flag = False
multi_country_results: dict[str, list[dict]] = {}
search_label_for_save = ""
category_default_for_save: tuple = ("", "", "")

if mode.startswith("🌐"):
    st.markdown(
        "**한국어 키워드 하나** 만 적으면 → 선택한 나라 언어로 **자동 번역** → "
        "각 나라 유튜브에서 동시에 검색해서 **한 표로** 보여드려요. "
        "어느 언어 검색에서 잡혔는지 컬럼으로 표시돼요."
    )
    try:
        from multilang_search import LANGUAGES as _ML_LANGS
        ml_labels = [l[0] for l in _ML_LANGS]
    except Exception:
        ml_labels = []
        st.error("multilang_search 모듈을 못 불러왔어요.")

    ko_keyword = st.text_input(
        "한국어 키워드 (또는 어느 언어든)",
        placeholder="예: 여름 플레이리스트, 효도 트로트 메들리, 로파이 카페 음악…",
    )
    selected_ml_labels = st.multiselect(
        "🌍 어느 나라 언어로 동시 검색할까요?",
        options=ml_labels,
        default=[
            "🇰🇷 한국어", "🇺🇸 영어 (미국)", "🇯🇵 일본어",
            "🇲🇽 스페인어 (멕시코)", "🇫🇷 프랑스어",
        ],
        help="번역은 Gemini가 처리해요 — 각 나라 사람들이 실제로 검색창에 칠 만한 자연스러운 표현으로.",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        ml_per_lang = st.selectbox("언어당 영상 수", [10, 15, 20, 30], index=1)
    with col2:
        ml_days = st.selectbox(
            "기간", [7, 14, 30, 60, 90, 365],
            index=2, format_func=lambda d: f"최근 {d}일",
        )
    with col3:
        ml_order = st.selectbox(
            "정렬", ["viewCount", "relevance", "date"],
            format_func=lambda x: {
                "viewCount": "🔥 조회수 순", "relevance": "🎯 관련도 순", "date": "🆕 최신 순",
            }[x],
        )
    ml_min_ratio = st.slider(
        "최소 바이럴 배수 (구독자 대비 조회수)", 0, 50, 0,
        help="0이면 필터 끔. 5 이상이면 알고리즘 푸시 신호.",
    )

    api_key = _get_api_key()
    gemini_key_env = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key_env:
        st.warning("🔑 `GEMINI_API_KEY` 가 설정 안 됐어요. 아래에 임시로 넣어주세요.")
        gemini_key_input = st.text_input("GEMINI_API_KEY", type="password")
    else:
        gemini_key_input = ""

    go = st.button("🌐 번역 + 다국어 동시 검색")
    if go:
        if not ko_keyword.strip():
            st.warning("키워드를 입력해주세요.")
            st.stop()
        if not selected_ml_labels:
            st.warning("언어를 1개 이상 선택해주세요.")
            st.stop()
        if not api_key:
            st.error("YouTube API 키가 필요해요.")
            st.stop()

        gemini_key = (gemini_key_input or gemini_key_env).strip()
        if not gemini_key:
            st.error("Gemini API 키가 필요해요 (번역용).")
            st.stop()

        from multilang_search import translate_keyword, search_multilang
        with st.spinner(f"Gemini로 {len(selected_ml_labels)}개 언어 번역 중…"):
            translations, terr = translate_keyword(
                ko_keyword.strip(), selected_ml_labels, api_key=gemini_key,
            )
        if terr:
            st.warning(f"번역 일부 실패: {terr}")
        if translations:
            st.markdown("### 🌐 번역 결과")
            cols = st.columns(min(3, len(translations)))
            for i, (label, term) in enumerate(translations.items()):
                with cols[i % len(cols)]:
                    st.markdown(
                        f"**{label}**<br>"
                        f"<code style='font-size:0.95rem;'>{term}</code>",
                        unsafe_allow_html=True,
                    )

        with st.spinner(
            f"{len(translations)}개 언어로 유튜브에서 동시 검색 중… (병렬)"
        ):
            videos, err = search_multilang(
                api_key, translations,
                per_lang=ml_per_lang, days=ml_days, order=ml_order,
                min_ratio=float(ml_min_ratio), min_views=0,
            )
        if err:
            st.error(f"검색 실패: {err}")
            st.stop()
        if not videos:
            st.error("결과가 없어요. 기간/배수 조건을 풀어보세요.")
            st.stop()
        st.success(
            f"✅ {len(translations)}개 언어 검색 · 영상 {len(videos)}개 (중복 제거 후)"
        )
        search_label_for_save = (
            f"🌐 {ko_keyword.strip()} · {len(selected_ml_labels)}개국"
        )

elif mode.startswith("🪄"):
    st.markdown(
        "사용자 입력 없이 앱이 직접 찾아드려요. **시드를 모를 때 이걸 쓰세요.**"
    )

    selected_countries = st.multiselect(
        "🌍 어느 나라/언어에서 발굴할까요? (여러 개 선택하면 비교 모드)",
        options=[c[0] for c in COUNTRIES],
        default=["🇰🇷 한국"],
        help="2개 이상 선택하면 글로벌 공통 시드 vs 국가별 고유 시드를 비교해드려요.",
    )
    if not selected_countries:
        st.info("최소 1개 국가를 선택해주세요.")

    sub_mode = st.radio(
        "어디서 발굴할까요?",
        [
            "💎 히든 젬 (구독자 적은데 조회수 폭발) — 추천",
            "📺 메인 피드 (인기 급상승)",
        ],
        horizontal=False,
        label_visibility="visible",
    )
    if sub_mode.startswith("💎"):
        col1, col2 = st.columns(2)
        with col1:
            days = st.selectbox(
                "최근 며칠 영상", [3, 7, 14, 30], index=1,
                format_func=lambda d: f"최근 {d}일",
            )
        with col2:
            top_n = st.selectbox("결과 개수", [15, 30, 50], index=1, key="gem_top")
        min_ratio = st.slider(
            "구독자 대비 조회수 배수 (이상)", 2, 50, 5,
            help="조회수 ÷ 구독자수. 5배 이상이면 '구독자 1000명 채널인데 조회수 5000+' = 알고리즘 푸시 신호",
        )
        min_views = st.select_slider(
            "최소 조회수",
            options=[1000, 5000, 10_000, 50_000, 100_000],
            value=5000,
            format_func=lambda n: f"{n:,}회",
        )
    else:
        col1, _ = st.columns(2)
        with col1:
            top_n = st.selectbox("결과 개수", [20, 30, 50], index=1, key="trend_top")
        days = 0
        min_ratio = 0
        min_views = 0

    api_key = _get_api_key()
    go = st.button("🪄 알고리즘 시드 발굴하기")
    if go:
        if not api_key:
            st.error("YouTube API 키가 필요해요.")
            st.stop()
        if not selected_countries:
            st.error("국가를 1개 이상 선택해주세요.")
            st.stop()

        is_multi = len(selected_countries) >= 2

        for label_country in selected_countries:
            region, lang = COUNTRY_LABEL_TO_RL[label_country]
            if sub_mode.startswith("💎"):
                with st.spinner(
                    f"{label_country} · 최근 {days}일 풀에서 '구독자 대비 폭발' 영상 찾는 중…"
                ):
                    vids, err = fetch_hidden_gems(
                        api_key,
                        region_code=region,
                        language=lang,
                        days=days,
                        pool_size=min(200, top_n * 6),
                        top_n=top_n,
                        min_ratio=float(min_ratio),
                        min_views=int(min_views),
                    )
                show_gems_flag = True
            else:
                with st.spinner(f"{label_country} · 인기 급상승 영상 모으는 중…"):
                    vids, err = fetch_trending_videos(
                        api_key, region_code=region, max_results=top_n
                    )
            if err:
                st.warning(f"{label_country} 수집 실패: {err}")
                continue
            if vids:
                multi_country_results[label_country] = vids
                videos.extend(vids)

        if not multi_country_results:
            st.error("결과가 없어요. 조건(배수/조회수)을 낮춰보거나 다른 국가를 선택해보세요.")
            st.stop()

        # 단일 국가면 비교 모드 끄기
        if not is_multi:
            multi_country_results = {}

        total = sum(len(v) for v in (multi_country_results.values() if multi_country_results else [videos]))
        sub_label = "💎 히든 젬" if sub_mode.startswith("💎") else "📺 인기 급상승"
        st.success(
            f"✅ {sub_label} · {len(selected_countries)}개국 · 영상 {total}개 찾았어요"
        )
        from datetime import datetime as _dt
        search_label_for_save = (
            f"{sub_label} · {','.join(selected_countries)} · {_dt.now().strftime('%Y-%m-%d')}"
        )

elif mode.startswith("🔥"):
    st.markdown(
        "**시드 키워드**를 적으면 그 키워드의 요즘 핫한 영상을 모아 분석해요. "
        "비우면 한국 **인기 급상승** 영상 전반에서 알고리즘이 밀어주는 키워드를 보여드려요."
    )
    seed = st.text_input(
        "시드 키워드 (선택)",
        placeholder="예: 여름, 휴가, 다이어트, 트로트… (비워두면 인기 급상승 전반)",
    )
    col1, col2 = st.columns(2)
    with col1:
        max_results = st.selectbox("몇 개 모을까요", [20, 30, 50], index=1)
    with col2:
        days = st.selectbox(
            "기간 (시드 있을 때만)",
            [7, 14, 30, 60],
            index=1,
            format_func=lambda d: f"최근 {d}일",
        )

    api_key = _get_api_key()
    go = st.button("🔥 트렌드 분석하기")
    if go:
        if not api_key:
            st.error("YouTube API 키가 필요해요.")
            st.stop()
        if seed.strip():
            with st.spinner(f"'{seed}' 트렌드 영상 모으는 중…"):
                videos, err = search_videos_by_category(
                    seed.strip(),
                    api_key,
                    order="viewCount",
                    days=days,
                    max_results=max_results,
                )
        else:
            with st.spinner("한국 인기 급상승 영상 모으는 중…"):
                videos, err = fetch_trending_videos(
                    api_key, max_results=max_results
                )
        if err:
            st.error(f"수집 실패: {err}")
            st.stop()
        if not videos:
            st.error("결과가 없어요.")
            st.stop()
        label = f"'{seed}' 트렌드" if seed.strip() else "한국 인기 급상승"
        st.success(f"✅ {label} 영상 {len(videos)}개 수집 완료")
        search_label_for_save = label

elif mode.startswith("📂"):
    st.markdown("원하는 **카테고리/키워드**의 유튜브 인기 영상 제목을 모아 분석해요.")
    category = st.text_input(
        "카테고리 / 키워드",
        placeholder="예: 트로트 메들리, 효도 노래, 7080 발라드, 먹방, 다이어트…",
    )
    col1, col2 = st.columns(2)
    with col1:
        order = st.selectbox(
            "정렬 기준",
            ["viewCount", "relevance", "date"],
            format_func=lambda x: {
                "viewCount": "🔥 조회수 높은 순",
                "relevance": "🎯 관련도 순",
                "date": "🆕 최신 순",
            }[x],
        )
    with col2:
        max_results = st.selectbox("몇 개 모을까요", [20, 30, 50], index=1, key="cat_max")
    days = st.slider("최근 며칠 안의 영상", 7, 365, 30, step=7)

    api_key = _get_api_key()
    go = st.button("🔬 카테고리 분석하기")
    if go:
        if not category.strip():
            st.warning("카테고리를 적어주세요.")
            st.stop()
        if not api_key:
            st.error("YouTube API 키가 필요해요.")
            st.stop()
        with st.spinner(f"'{category}' 유튜브에서 인기 제목 모으는 중…"):
            videos, err = search_videos_by_category(
                category.strip(),
                api_key,
                order=order,
                days=days,
                max_results=max_results,
            )
        if err:
            st.error(f"수집 실패: {err}")
            st.stop()
        if not videos:
            st.error("결과가 없어요. 다른 키워드로 다시 시도해보세요.")
            st.stop()
        st.success(f"✅ '{category}' 영상 {len(videos)}개 수집 완료")
        search_label_for_save = category.strip()

else:
    st.markdown("유튜브 **URL** 이나 **제목**을 한 줄에 하나씩 넣어주세요.")
    with st.expander("💡 예시 보기"):
        st.code(
            "[효도트로트] 엄마가 들으면 눈물 흘리는 명곡 메들리 🎵\n"
            "https://www.youtube.com/watch?v=xxxxxxxxxxx\n"
            "✨ 1980년대 최고의 발라드 BEST 30 ✨\n"
            "[라이브] 신청곡 모음 | 트로트 메들리\n"
            "충격! 이 노래 듣고 울었습니다",
            language="text",
        )
    raw_input = st.text_area(
        "분석할 제목 / URL", height=220,
        placeholder="제목이나 유튜브 URL을 한 줄에 하나씩…",
    )
    go = st.button("🔬 패턴 분석하기")
    if go:
        if not raw_input.strip():
            st.warning("제목이나 URL을 한 줄 이상 넣어주세요.")
            st.stop()
        with st.spinner("URL에서 제목 가져오는 중…"):
            titles, failed = parse_input_lines(raw_input)
        if failed:
            st.warning(
                f"⚠️ {len(failed)}개 URL은 제목을 못 가져왔어요 (비공개/삭제 영상일 수 있음)"
            )
        videos = [{"title": t, "duration_s": None, "video_id": None} for t in titles]
        from datetime import datetime as _dt
        search_label_for_save = f"수동 입력 · {_dt.now().strftime('%Y-%m-%d')}"

if go and videos:
    if multi_country_results:
        render_multi_country(
            multi_country_results, length_mode, view_mode=view_mode,
            search_label=search_label_for_save,
            category_default=category_default_for_save,
        )
    else:
        render_with_split(
            videos, length_mode, show_gems=show_gems_flag, view_mode=view_mode,
            search_label=search_label_for_save,
            category_default=category_default_for_save,
        )
    st.markdown(
        "<div class='caption-small'>💡 더 많은 영상을 넣을수록 공식이 정확해져요</div>",
        unsafe_allow_html=True,
    )
