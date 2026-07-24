"""daily_viral_collect.py — 🤖 무인 자동 수집기 (조회수 1만+ 만).

사장님 PC 가 꺼져 있어도 GitHub Actions cron 이 매일 이 스크립트를 돌려,
설정한 키워드로 YouTube 를 조회수순 검색하고 **1만+ 영상만** viral_hits.json 에
누적한다(video_id 멱등). Actions 가 그 JSON 을 커밋 → 사장님이 앱을 켜고
git pull 하면 수집함 탭에서 바로 본다.

환경변수:
  YOUTUBE_API_KEY  (필수 — 없으면 데모 데이터로 돌아 아무것도 저장 안 함)
  VIRAL_KEYWORDS   쉼표구분 키워드. 기본=음악·플레이리스트 시드
  VIRAL_VIDEO_TYPE all | long | shorts   (기본 all)
  VIRAL_PERIOD_DAYS 검색 기간(일). 기본 180(6개월)
  VIRAL_MAX        키워드당 검색 수(기본 50)
  VIRAL_MIN_VIEWS  하한(기본 10000)

로컬 실행:  python daily_viral_collect.py --keywords "재즈 플레이리스트,시티팝"
"""
from __future__ import annotations

import argparse
import os
import sys

import viral_lab as V

# 음악·플레이리스트 채널 시드 키워드 (사장님 주력 장르)
DEFAULT_KEYWORDS = [
    "재즈 플레이리스트", "새벽 감성 플레이리스트", "시티팝 모음", "카페 음악",
    "로파이 플레이리스트", "발라드 모음", "비 오는 날 재즈", "잔잔한 피아노",
    "보사노바 플레이리스트", "샹송 카페",
]


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return [k.strip() for k in raw.split(",") if k.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description="조회수 1만+ 무인 수집기")
    p.add_argument("--keywords", default="", help="쉼표구분 키워드(비우면 env/기본)")
    p.add_argument("--video-type", default=os.environ.get("VIRAL_VIDEO_TYPE", "all"))
    p.add_argument("--period-days", type=int,
                   default=int(os.environ.get("VIRAL_PERIOD_DAYS", "180")))
    p.add_argument("--max", type=int, default=int(os.environ.get("VIRAL_MAX", "50")))
    p.add_argument("--min-views", type=int,
                   default=int(os.environ.get("VIRAL_MIN_VIEWS", str(V.MIN_VIEWS))))
    args = p.parse_args()

    keywords = ([k.strip() for k in args.keywords.split(",") if k.strip()]
                if args.keywords else _env_list("VIRAL_KEYWORDS", DEFAULT_KEYWORDS))

    if not V.has_youtube_key():
        print("⚠️  YOUTUBE_API_KEY 없음 — 데모 모드. 실제 수집을 하지 않고 종료합니다.")
        print("    (GitHub Actions Secrets 또는 .env 에 YOUTUBE_API_KEY 를 넣어주세요.)")
        return 0

    print(f"🔎 수집 시작 — 키워드 {len(keywords)}개, 하한 {args.min_views:,}회, "
          f"기간 {args.period_days}일, 유형 {args.video_type}")
    res = V.collect_cli(keywords, video_type=args.video_type,
                        period_days=args.period_days, max_results=args.max,
                        min_views=args.min_views)
    for k in res["keywords"]:
        print(f"  · {k['keyword']:<20} 검색 {k['raw']:>3} → 1만+ {k['hits']:>3} "
              f"(신규 {k['added']})")
    print(f"✅ 신규 {res['added']}건 추가 · 수집함 총 {res['total']}건 "
          f"· 갱신 {res['updated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
