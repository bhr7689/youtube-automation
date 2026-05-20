"""
급상승 레퍼런스 채널 발굴 대시보드 (Trending Reference Channel Discovery Dashboard)

YouTube Data API v3 를 사용해 특정 키워드(상황/감정 기반)로 최근 N일 내 업로드된
영상을 검색하고, '구독자 수 대비 조회수' 비율이 폭발적인 신규/소형 채널만 필터링해
리스트업하는 Streamlit 대시보드입니다.
"""

from __future__ import annotations

import os
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

    with st.expander("🔬 전체 검색 결과 보기 (필터 적용 전)"):
        st.dataframe(df, use_container_width=True, hide_index=True)


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
