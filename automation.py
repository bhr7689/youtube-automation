#!/usr/bin/env python3
"""무인 자동 수집 오케스트레이터 (cron / 데몬용).

app.py 의 검증된 수집 함수를 재사용해 YouTube 수집 + 정량필터만 수행하고,
결과를 SQLite(ktrot.db)에 적재한다. 유료 LLM(스토리/가사) 호출은 하지 않는다
 — 그건 사람이 검수 후 UI 에서 on-demand 로 돌려 비용을 통제한다.

UI(app.py)는 이 DB 를 즉시 읽으므로 라이브 API 대기로 인한 버퍼링이 없다.

예시:
  # 한 사이클만 (cron 한 줄에 적합)
  python automation.py --once \
      --keywords "비 오는 날 카페,새벽 감성 피아노,rainy night jazz" \
      --days 30 --max 50

  # 데몬처럼 N초마다 반복
  python automation.py --interval 21600   # 6시간마다

cron 예시 (매일 새벽 4시):
  0 4 * * * cd /path/to/youtube-automation && \
      .venv/bin/python automation.py --once \
      --keywords "비 오는 날 카페,새벽 감성 피아노" --days 30 --max 50 >> cron.log 2>&1
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

import store

load_dotenv()


# search.list = 100 units/페이지(최대 50개). videos/channels.list = 1 unit/청크.
SEARCH_COST_PER_PAGE = 100
DAILY_QUOTA = 10_000


def estimate_quota(keyword_count: int, max_results: int) -> int:
    """이번 수집이 소모할 대략적인 YouTube API units 추정치."""
    pages_per_keyword = math.ceil(max_results / 50)
    search_cost = keyword_count * pages_per_keyword * SEARCH_COST_PER_PAGE
    # videos/channels 조회는 1 unit/청크라 사실상 무시 가능하지만 보수적으로 더한다.
    detail_cost = math.ceil(keyword_count * max_results / 50) * 2
    return search_cost + detail_cost


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="YouTube 급상승 레퍼런스 무인 수집 오케스트레이터",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--keywords", required=True,
                   help="쉼표 또는 줄바꿈으로 구분한 키워드")
    p.add_argument("--days", type=int, default=30, help="최근 N일 이내 업로드")
    p.add_argument("--max", dest="max_results", type=int, default=50,
                   help="키워드당 검색 결과 수")
    p.add_argument("--region", default="KR", help="지역 코드 (ISO 3166-1)")
    p.add_argument("--language", default="ko", help="언어 코드")
    p.add_argument("--order", default="viewCount",
                   choices=["date", "viewCount", "relevance"])
    p.add_argument("--max-subscribers", type=int, default=10_000)
    p.add_argument("--min-views", type=int, default=5_000)
    p.add_argument("--min-ratio", type=float, default=2.0)
    p.add_argument("--db", default=store.DEFAULT_DB, help="SQLite 경로")
    p.add_argument("--api-key", default=None,
                   help="미지정 시 환경변수 YOUTUBE_API_KEY 사용")
    p.add_argument("--max-quota", type=int, default=DAILY_QUOTA,
                   help="이 추정 units 를 넘으면 중단(비용 가드)")
    p.add_argument("--top", type=int, default=10, help="요약에 출력할 상위 후보 수")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="한 사이클만 수집하고 종료(기본 동작)")
    mode.add_argument("--interval", type=int, default=0,
                      help="N초마다 반복 실행(데몬). 0 이면 1회만.")
    return p.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def run_once(args: argparse.Namespace, api_key: str) -> int:
    """한 사이클 수집 → SQLite 적재. 종료코드(0=정상)를 반환."""
    # app.py 의 수집 함수 재사용. (@st.cache_data 가 걸린 run_pipeline 은 쓰지 않음.)
    from app import (
        SearchConfig,
        build_client,
        build_dataframe,
        fetch_channel_details,
        fetch_video_details,
        filter_breakout_channels,
        search_video_ids,
    )
    from googleapiclient.errors import HttpError

    keywords = tuple(
        k.strip()
        for k in args.keywords.replace(",", "\n").splitlines()
        if k.strip()
    )
    if not keywords:
        _log("ERROR: 유효한 키워드가 없습니다.")
        return 2

    est = estimate_quota(len(keywords), args.max_results)
    _log(f"키워드 {len(keywords)}개 · 키워드당 최대 {args.max_results}개 "
         f"→ 예상 할당량 ≈ {est:,} units (일일 {DAILY_QUOTA:,})")
    if est > args.max_quota:
        _log(f"ERROR: 예상 할당량 {est:,} > 한도 {args.max_quota:,}. "
             f"--max 를 줄이거나 --max-quota 를 올리세요. 중단합니다.")
        return 3

    cfg = SearchConfig(
        api_key=api_key,
        keywords=keywords,
        days=args.days,
        max_results_per_keyword=args.max_results,
        region_code=args.region.strip().upper(),
        language=args.language.strip().lower(),
        max_subscribers=args.max_subscribers,
        min_views=args.min_views,
        min_view_sub_ratio=args.min_ratio,
        order=args.order,
    )

    try:
        youtube = build_client(cfg.api_key)
        _log("YouTube 검색 중...")
        video_ids = search_video_ids(youtube, cfg)
        if not video_ids:
            _log("검색 결과 0건. (키워드/기간 조정 권장) — 빈 run 저장.")
            store.save_run(__import__("pandas").DataFrame(), _cfg_dict(cfg), db_path=args.db)
            return 0
        _log(f"영상 {len(video_ids)}건 메타 조회 중...")
        videos = fetch_video_details(youtube, video_ids)
        channel_ids = [
            v.get("snippet", {}).get("channelId")
            for v in videos if v.get("snippet")
        ]
        channels = fetch_channel_details(youtube, [c for c in channel_ids if c])
        df = build_dataframe(videos, channels)
    except HttpError as e:
        _log(f"ERROR: YouTube API 오류 — {e}")
        return 4
    except Exception as e:  # noqa: BLE001 - cron 로그에 원인을 남기기 위함
        _log(f"ERROR: 수집 중 예외 — {e}")
        return 5

    filtered = filter_breakout_channels(df, cfg)
    filtered_ids = set(filtered["video_id"].tolist()) if not filtered.empty else set()

    run_id = store.save_run(df, _cfg_dict(cfg), filtered_ids=filtered_ids, db_path=args.db)
    _log(f"저장 완료 — run #{run_id}: 전체 {len(df)}건 / 급상승 후보 {len(filtered)}건 "
         f"→ {args.db}")

    _print_top(filtered if not filtered.empty else df, args.top)
    return 0


def _print_top(df, top: int) -> None:
    if df.empty:
        return
    print("\n  상위 후보 (조회수/구독자 비율 순):")
    cols = df.head(top)
    for i, rec in enumerate(cols.to_dict("records"), 1):
        title = (rec.get("video_title") or "")[:42]
        print(f"  {i:>2}. [{rec.get('view_sub_ratio'):>6}x] "
              f"{rec.get('view_count'):>9,}회 / 구독 {rec.get('subscriber_count'):>7,}  "
              f"{title}")
    print()


def _cfg_dict(cfg) -> dict:
    # api_key 는 의도적으로 제외 — 비밀값은 DB 에 저장하지 않는다.
    return {
        "keywords": list(cfg.keywords),
        "days": cfg.days,
        "max_results_per_keyword": cfg.max_results_per_keyword,
        "region_code": cfg.region_code,
        "language": cfg.language,
        "max_subscribers": cfg.max_subscribers,
        "min_views": cfg.min_views,
        "min_view_sub_ratio": cfg.min_view_sub_ratio,
        "order": cfg.order,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = args.api_key or os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        _log("ERROR: YOUTUBE_API_KEY 가 없습니다. .env 또는 --api-key 로 지정하세요.")
        return 1

    store.init_db(args.db)

    if args.interval and args.interval > 0:
        _log(f"데몬 모드 시작 — {args.interval}초마다 반복 (Ctrl+C 로 종료)")
        while True:
            code = run_once(args, api_key)
            if code not in (0, 4, 5):  # 설정/할당량 오류는 반복해도 의미 없으니 종료
                return code
            _log(f"다음 사이클까지 {args.interval}초 대기...")
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                _log("종료합니다.")
                return 0
    return run_once(args, api_key)


if __name__ == "__main__":
    sys.exit(main())
