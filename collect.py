"""수집기 — YouTube 검색 → 통계/댓글 수집 → 데이터 토대(store) 적재.

파이썬-우선 자동화의 1단계. 공식 YouTube Data API v3 만 사용(스크래핑 X = 정확).
매일 돌려도 store 의 멱등성(video_id 중복 차단) 덕에 낭비가 없고, 수집할 때마다
video_stats 에 시계열이 쌓여 바이럴 속도를 계산할 수 있다.

정량 점수(0~55)는 여기서 계산(0원, 결정론적):
  - view_subscriber_ratio (최대 30)
  - viral_speed = 시간당 조회수 (최대 25)
정성 점수(댓글 감성 등, Gemini)는 다음 단계 score.py 가 채운다.

실행:
  python collect.py --keywords "트로트 발라드,효도 트로트" --days 14 --max 50 --comments
  GEMINI/YOUTUBE 키는 환경변수 또는 --api-key.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import isodate

import store

MAX_IDS_PER_REQUEST = 50

# 정량 점수 튜닝 상수 (도메인에 맞춰 조정 가능).
RATIO_FULL = 5.0      # 조회/구독 비율이 이 값이면 30점 만점
SPEED_FULL = 500.0    # 시간당 조회수가 이 값이면 25점 만점


@dataclass
class CollectConfig:
    keywords: tuple[str, ...]
    days: int = 14
    max_results_per_keyword: int = 50
    order: str = "relevance"        # date | viewCount | relevance
    region_code: str = "KR"
    language: str = "ko"
    collect_comments: bool = False
    max_comments_per_video: int = 50
    top_n_for_comments: int = 20    # 정량 상위 N개만 댓글 수집(쿼터 절약)


# ---------------------------------------------------------------------------
# YouTube API
# ---------------------------------------------------------------------------

def build_client(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def search_video_ids(youtube, cfg: CollectConfig) -> list[str]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=cfg.days)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    ids: list[str] = []
    seen: set[str] = set()
    for keyword in cfg.keywords:
        page_token = None
        collected = 0
        while collected < cfg.max_results_per_keyword:
            page_size = min(50, cfg.max_results_per_keyword - collected)
            resp = youtube.search().list(
                part="id", q=keyword, type="video", order=cfg.order,
                publishedAfter=published_after, maxResults=page_size,
                regionCode=cfg.region_code or None,
                relevanceLanguage=cfg.language or None, pageToken=page_token,
            ).execute()
            items = resp.get("items", [])
            for it in items:
                vid = it.get("id", {}).get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    ids.append(vid)
            collected += len(items)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    return ids


def fetch_video_details(youtube, video_ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for chunk in _chunks(video_ids, MAX_IDS_PER_REQUEST):
        resp = youtube.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(chunk),
            maxResults=MAX_IDS_PER_REQUEST,
        ).execute()
        out.extend(resp.get("items", []))
    return out


def fetch_channel_details(youtube, channel_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for chunk in _chunks(list(dict.fromkeys(channel_ids)), MAX_IDS_PER_REQUEST):
        resp = youtube.channels().list(
            part="snippet,statistics", id=",".join(chunk),
            maxResults=MAX_IDS_PER_REQUEST,
        ).execute()
        for it in resp.get("items", []):
            out[it["id"]] = it
    return out


def fetch_comments(youtube, video_id: str, max_comments: int = 50) -> list[dict]:
    """상위 댓글 수집. 댓글 비활성화 영상은 빈 리스트(예외 흡수)."""
    comments: list[dict] = []
    page_token = None
    try:
        while len(comments) < max_comments:
            resp = youtube.commentThreads().list(
                part="snippet", videoId=video_id, maxResults=min(100, max_comments),
                order="relevance", textFormat="plainText", pageToken=page_token,
            ).execute()
            for it in resp.get("items", []):
                top = it.get("snippet", {}).get("topLevelComment", {})
                sn = top.get("snippet", {})
                comments.append({
                    "comment_id": top.get("id") or it.get("id"),
                    "author": sn.get("authorDisplayName"),
                    "text": sn.get("textDisplay"),
                    "like_count": sn.get("likeCount"),
                    "published_at": sn.get("publishedAt"),
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except Exception:
        return comments
    return comments[:max_comments]


# ---------------------------------------------------------------------------
# 매핑 / 점수 (순수 함수 — 헤드리스 테스트)
# ---------------------------------------------------------------------------

def parse_duration_seconds(iso_duration: str | None) -> int:
    if not iso_duration:
        return 0
    try:
        return int(isodate.parse_duration(iso_duration).total_seconds())
    except Exception:
        return 0


def to_rows(videos: list[dict], channels: dict[str, dict],
            keyword: str = "") -> list[dict]:
    """YouTube API 아이템 → store.upsert_videos 행 형식."""
    rows: list[dict] = []
    for v in videos:
        sn = v.get("snippet", {})
        stats = v.get("statistics", {})
        content = v.get("contentDetails", {})
        ch = channels.get(sn.get("channelId"), {})
        c_stats = ch.get("statistics", {})
        rows.append({
            "video_id": v.get("id"),
            "channel_id": sn.get("channelId"),
            "channel_title": sn.get("channelTitle", ""),
            "title": sn.get("title", ""),
            "description": sn.get("description", ""),
            "published_at": sn.get("publishedAt", ""),
            "duration_sec": parse_duration_seconds(content.get("duration")),
            "region": sn.get("defaultAudioLanguage") or "",
            "search_keyword": keyword,
            "subscriber_count": int(c_stats.get("subscriberCount", 0) or 0),
            "view_count": int(stats.get("viewCount", 0) or 0),
            "like_count": int(stats.get("likeCount", 0) or 0),
            "comment_count": int(stats.get("commentCount", 0) or 0),
        })
    return rows


def _hours_since(published_at: str | None, now: datetime | None = None) -> float:
    if not published_at:
        return 0.0
    now = now or datetime.now(timezone.utc)
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max((now - pub).total_seconds() / 3600.0, 0.0)


def compute_quant_score(row: dict, now: datetime | None = None) -> float:
    """정량 점수 0~55. view/sub 비율(≤30) + 시간당 조회수(≤25)."""
    views = row.get("view_count", 0) or 0
    subs = row.get("subscriber_count", 0) or 0
    ratio = views / subs if subs > 0 else float(views)
    score_ratio = min(ratio / RATIO_FULL * 30.0, 30.0)

    hours = _hours_since(row.get("published_at"), now)
    vph = views / hours if hours > 0 else float(views)
    score_speed = min(vph / SPEED_FULL * 25.0, 25.0)
    return round(score_ratio + score_speed, 2)


# ---------------------------------------------------------------------------
# 오케스트레이션
# ---------------------------------------------------------------------------

def gather(youtube, cfg: CollectConfig) -> tuple[list[dict], dict[str, dict]]:
    ids = search_video_ids(youtube, cfg)
    if not ids:
        return [], {}
    videos = fetch_video_details(youtube, ids)
    channel_ids = [v.get("snippet", {}).get("channelId") for v in videos]
    channels = fetch_channel_details(youtube, [c for c in channel_ids if c])
    return videos, channels


def store_results(rows: list[dict], *, db_path=store.DB_PATH,
                  now: datetime | None = None) -> None:
    store.upsert_videos(rows, path=db_path)
    for r in rows:
        if r.get("video_id"):
            store.set_quant_score(r["video_id"], compute_quant_score(r, now), path=db_path)


def collect(cfg: CollectConfig, *, api_key: str | None = None, youtube=None,
            db_path=store.DB_PATH) -> dict:
    """전체 수집 1회. youtube 클라이언트 주입 시 테스트 가능."""
    store.init_db(db_path)
    if youtube is None:
        if not api_key:
            raise ValueError("api_key 또는 youtube 클라이언트가 필요합니다.")
        youtube = build_client(api_key)

    videos, channels = gather(youtube, cfg)
    keyword_label = ", ".join(cfg.keywords)
    rows = to_rows(videos, channels, keyword_label)
    store_results(rows, db_path=db_path)

    comments_added = 0
    if cfg.collect_comments and rows:
        ranked = sorted(rows, key=lambda r: compute_quant_score(r), reverse=True)
        for r in ranked[: cfg.top_n_for_comments]:
            vid = r.get("video_id")
            if not vid:
                continue
            cs = fetch_comments(youtube, vid, cfg.max_comments_per_video)
            comments_added += store.add_comments(vid, cs, path=db_path)

    return {
        "videos_collected": len(rows),
        "comments_added": comments_added,
        "counts": store.counts(db_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="YouTube 수집기 → SQLite 자산 적재")
    p.add_argument("--keywords", required=True, help="쉼표로 구분한 검색 키워드")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--max", type=int, default=50, help="키워드당 최대 결과 수")
    p.add_argument("--order", default="relevance", choices=["relevance", "date", "viewCount"])
    p.add_argument("--region", default="KR")
    p.add_argument("--language", default="ko")
    p.add_argument("--comments", action="store_true", help="상위 영상 댓글도 수집")
    p.add_argument("--max-comments", type=int, default=50)
    p.add_argument("--top-n-comments", type=int, default=20)
    p.add_argument("--db", default=str(store.DB_PATH))
    p.add_argument("--api-key", default=os.getenv("YOUTUBE_API_KEY", ""))
    args = p.parse_args(argv)

    if not args.api_key:
        print("YOUTUBE_API_KEY 가 필요합니다 (.env 또는 --api-key).", file=sys.stderr)
        return 2

    cfg = CollectConfig(
        keywords=tuple(k.strip() for k in args.keywords.split(",") if k.strip()),
        days=args.days, max_results_per_keyword=args.max, order=args.order,
        region_code=args.region, language=args.language,
        collect_comments=args.comments, max_comments_per_video=args.max_comments,
        top_n_for_comments=args.top_n_comments,
    )
    summary = collect(cfg, api_key=args.api_key, db_path=args.db)
    print(f"수집 완료: 영상 {summary['videos_collected']}개, "
          f"댓글 {summary['comments_added']}개")
    print(f"자산 현황: {summary['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
