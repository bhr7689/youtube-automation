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
@st.cache_data(show_spinner=False, ttl=1800)
def search_titles_by_category(
    category: str,
    api_key: str,
    *,
    order: str = "viewCount",
    days: int = 30,
    max_results: int = 30,
    region_code: str = "KR",
    language: str = "ko",
) -> tuple[list[str], Optional[str]]:
    """카테고리 키워드 → YouTube 검색 → 제목 리스트. (titles, error_or_None)"""
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
        titles: list[str] = []
        page_token = None
        while len(titles) < max_results:
            page_size = min(50, max_results - len(titles))
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
                snippet = item.get("snippet", {})
                title = snippet.get("title")
                if title:
                    titles.append(title)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return titles, None
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
# UI
# ============================================================
st.title("🔬 제목 알고리즘 분석")
st.markdown("'잘 먹히는 유튜브 제목 공식'을 뽑아드려요.")

mode = st.radio(
    "어떻게 분석할까요?",
    ["📂 카테고리로 자동 수집", "✍️ 제목/URL 직접 붙여넣기"],
    horizontal=False,
    label_visibility="visible",
)

titles: list[str] = []
failed: list[str] = []
go = False

if mode.startswith("📂"):
    st.markdown(
        "원하는 **카테고리/키워드**를 적으면 유튜브에서 인기 영상 제목을 모아 분석해요."
    )
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
        max_results = st.selectbox("몇 개 모을까요", [20, 30, 50], index=1)
    days = st.slider("최근 며칠 안의 영상", 7, 365, 30, step=7)

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        st.warning(
            "🔑 `YOUTUBE_API_KEY` 가 설정 안 됐어요. 아래에 임시로 넣어주세요."
        )
        api_key = st.text_input("YOUTUBE_API_KEY", type="password")

    go = st.button("🔬 카테고리 분석하기")
    if go:
        if not category.strip():
            st.warning("카테고리를 적어주세요.")
            st.stop()
        if not api_key:
            st.error("YouTube API 키가 필요해요.")
            st.stop()
        with st.spinner(f"'{category}' 유튜브에서 인기 제목 모으는 중…"):
            titles, err = search_titles_by_category(
                category.strip(),
                api_key,
                order=order,
                days=days,
                max_results=max_results,
            )
        if err:
            st.error(f"수집 실패: {err}")
            st.stop()
        if not titles:
            st.error("결과가 없어요. 다른 키워드로 다시 시도해보세요.")
            st.stop()
        st.success(f"✅ '{category}' 영상 제목 {len(titles)}개 수집 완료")

else:
    st.markdown("유튜브 **URL** 이나 **제목**을 한 줄에 하나씩 넣어주세요.")
    with st.expander("💡 예시 보기 (눌러서 펴기)"):
        st.code(
            "[효도트로트] 엄마가 들으면 눈물 흘리는 명곡 메들리 🎵\n"
            "https://www.youtube.com/watch?v=xxxxxxxxxxx\n"
            "✨ 1980년대 최고의 발라드 BEST 30 ✨\n"
            "[라이브] 신청곡 모음 | 트로트 메들리\n"
            "충격! 이 노래 듣고 울었습니다",
            language="text",
        )
    raw_input = st.text_area(
        "분석할 제목 / URL",
        height=220,
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

if go and titles:
    if len(titles) < 2:
        st.error("분석하려면 제목이 2개 이상 필요해요.")
        st.stop()
    r = analyze_titles(titles)

    st.markdown("---")
    st.markdown(f"<div class='score-big'>{r['n']}</div>", unsafe_allow_html=True)
    st.markdown("<div class='score-sub'>개의 제목을 분석했어요</div>", unsafe_allow_html=True)

    formula, insights = build_formula(r)

    st.markdown("## 🎯 제목 공식")
    st.markdown(f"<div class='formula-card'>{formula}</div>", unsafe_allow_html=True)

    st.markdown("## 💎 핵심 인사이트")
    for ins in insights:
        st.markdown(f"- {ins}")

    st.markdown("## 📊 특수문자/요소 사용률")

    def render_bar(label: str, pct: float):
        st.markdown(
            f"<div class='bar-bg'><span class='bar-text'>{label} · {pct:.0f}%</span>"
            f"<div class='bar-fg' style='width:{min(pct,100):.0f}%'></div></div>",
            unsafe_allow_html=True,
        )

    render_bar("이모지", r["emoji_pct"])
    render_bar("숫자", r["number_pct"])
    render_bar("대괄호 [ ]", r["bracket_pct"])
    render_bar("느낌표 !", r["excl_pct"])
    render_bar("물음표 ?", r["quest_pct"])
    render_bar("구분자 |/", r["pipe_pct"])

    if r["word_top"]:
        st.markdown("## 🔑 자주 쓰는 단어 TOP")
        tags_html = ""
        max_count = r["word_top"][0][1]
        for w, c in r["word_top"]:
            hot = "tag-hot" if c >= max(2, max_count * 0.5) else ""
            tags_html += f"<span class='tag {hot}'>{w} · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["hook_hits"]:
        st.markdown("## 🔥 후킹 단어 (감정/매력 유발)")
        tags_html = ""
        for w, c in r["hook_hits"]:
            tags_html += f"<span class='tag tag-hot'>{w} · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["bracket_top"]:
        st.markdown("## 📦 대괄호 안에 자주 들어가는 말")
        tags_html = ""
        for w, c in r["bracket_top"]:
            tags_html += f"<span class='tag'>[{w}] · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["emoji_top"]:
        st.markdown("## ✨ 자주 쓰는 이모지")
        tags_html = ""
        for em, c in r["emoji_top"]:
            tags_html += f"<span class='tag'>{em} · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    if r["first_top"]:
        st.markdown("## 👀 제목 첫 단어 패턴")
        tags_html = ""
        for w, c in r["first_top"]:
            tags_html += f"<span class='tag'>{w}… · {c}</span>"
        st.markdown(tags_html, unsafe_allow_html=True)

    st.markdown("## 📋 분석한 제목들")
    sorted_titles = sorted(
        zip(r["titles"], r["lengths"]), key=lambda x: x[1], reverse=True
    )
    for t, ln in sorted_titles:
        st.markdown(
            f"<div class='title-row'><div class='t'>{t}</div>"
            f"<div class='s'>길이 {ln}자</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<div class='caption-small'>💡 더 많은 제목을 넣을수록 공식이 정확해져요</div>",
        unsafe_allow_html=True,
    )
