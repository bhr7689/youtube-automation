"""오케스트레이터 — 매일 자동: collect → score → 합산 랭킹.

파이썬-우선 자동화의 지휘자. 수집(collect.py)과 정성 채점(score.py)을 순서대로
실행하고, 스테이지별 실패를 격리(한 단계가 죽어도 나머지 진행)하며, 실행 이력을
orchestrator_log.jsonl 에 append 한다. 끝에 정량+정성 합산 상위 후보를 보여준다.

스케줄링은 두 가지:
  - cron 으로 매일 호출(권장):   python orchestrator.py --once --keywords "..."
  - 자체 폴링 데몬:             python orchestrator.py --watch --interval 86400 --keywords "..."

키는 환경변수(.env) 또는 --youtube-key/--gemini-key. 키가 없으면 해당 스테이지를
건너뛰고 경고만 남긴다(예: Gemini 키 없으면 수집만 수행).

cron 예시 (매일 새벽 5시):
  0 5 * * * cd /path/to/repo && /usr/bin/python orchestrator.py --once \
            --keywords "트로트 발라드,효도 트로트" --comments >> cron.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import collect
import score as scorer
import store

LOG_PATH = Path(__file__).parent / "orchestrator_log.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def run_cycle(
    *,
    keywords: tuple[str, ...],
    days: int = 14,
    max_results: int = 50,
    order: str = "relevance",
    region: str = "KR",
    language: str = "ko",
    collect_comments: bool = True,
    max_comments: int = 50,
    top_n_comments: int = 20,
    score_limit: int = 50,
    youtube_key: str | None = None,
    gemini_key: str | None = None,
    db_path=store.DB_PATH,
    stages: tuple[str, ...] = ("collect", "score"),
    top: int = 10,
    log_path=LOG_PATH,
) -> dict:
    """1 사이클 실행. 스테이지별 실패는 격리해 result['stages'][x]['error'] 로 보고."""
    store.init_db(db_path)
    result: dict = {"started_at": _now(), "stages": {}}

    if "collect" in stages:
        if not youtube_key:
            log("⚠️  collect 건너뜀: YOUTUBE_API_KEY 없음.")
            result["stages"]["collect"] = {"skipped": "no_youtube_key"}
        elif not keywords:
            log("⚠️  collect 건너뜀: 키워드 없음.")
            result["stages"]["collect"] = {"skipped": "no_keywords"}
        else:
            log(f"▶ collect 시작 (키워드 {len(keywords)}개, 최근 {days}일)...")
            try:
                cfg = collect.CollectConfig(
                    keywords=keywords, days=days, max_results_per_keyword=max_results,
                    order=order, region_code=region, language=language,
                    collect_comments=collect_comments, max_comments_per_video=max_comments,
                    top_n_for_comments=top_n_comments,
                )
                result["stages"]["collect"] = collect.collect(
                    cfg, api_key=youtube_key, db_path=db_path)
                c = result["stages"]["collect"]
                log(f"✅ collect: 영상 {c['videos_collected']}개, 댓글 {c['comments_added']}개")
            except Exception as e:
                log(f"❌ collect 실패: {e}")
                result["stages"]["collect"] = {"error": traceback.format_exc().splitlines()[-1]}

    if "score" in stages:
        if not gemini_key:
            log("⚠️  score 건너뜀: GEMINI_API_KEY 없음.")
            result["stages"]["score"] = {"skipped": "no_gemini_key"}
        else:
            log("▶ score 시작 (미채점 영상 정성 분석)...")
            try:
                result["stages"]["score"] = scorer.score_pending(
                    api_key=gemini_key, limit=score_limit, db_path=db_path)
                s = result["stages"]["score"]
                log(f"✅ score: 대상 {s['pending']}개, 채점 {s['scored']}개, 캐시 {s['cache_size']}건")
            except Exception as e:
                log(f"❌ score 실패: {e}")
                result["stages"]["score"] = {"error": traceback.format_exc().splitlines()[-1]}

    try:
        result["ranking"] = scorer.ranked_candidates(limit=top, db_path=db_path)
    except Exception:
        result["ranking"] = []
    result["counts"] = store.counts(db_path)
    result["finished_at"] = _now()

    try:
        with Path(log_path).open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in result.items() if k != "ranking"},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass
    return result


def print_ranking(ranking: list[dict]) -> None:
    if not ranking:
        log("합산 랭킹: (정량+정성이 모두 있는 영상 없음)")
        return
    print("\n=== 정량+정성 합산 상위 후보 ===")
    for r in ranking:
        print(f"  [{(r.get('total_score') or 0):.1f}] {r.get('title','')}  "
              f"(정량 {r.get('quant_score')}, 정성 {r.get('qual_score')}, {r.get('mood')})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="오케스트레이터 — collect→score 매일 자동")
    p.add_argument("--keywords", default="", help="쉼표로 구분한 검색 키워드")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--max", type=int, default=50)
    p.add_argument("--order", default="relevance", choices=["relevance", "date", "viewCount"])
    p.add_argument("--region", default="KR")
    p.add_argument("--language", default="ko")
    p.add_argument("--comments", action="store_true", default=True)
    p.add_argument("--no-comments", dest="comments", action="store_false")
    p.add_argument("--max-comments", type=int, default=50)
    p.add_argument("--top-n-comments", type=int, default=20)
    p.add_argument("--score-limit", type=int, default=50)
    p.add_argument("--stage", default="all", choices=["all", "collect", "score"])
    p.add_argument("--top", type=int, default=10, help="랭킹 출력 개수")
    p.add_argument("--db", default=str(store.DB_PATH))
    p.add_argument("--youtube-key", default=os.getenv("YOUTUBE_API_KEY", ""))
    p.add_argument("--gemini-key", default=os.getenv("GEMINI_API_KEY", ""))
    p.add_argument("--once", action="store_true", help="1 사이클 후 종료 (cron 용)")
    p.add_argument("--watch", action="store_true", help="데몬: --interval 마다 반복")
    p.add_argument("--interval", type=float, default=86400.0, help="watch 간격(초, 기본 1일)")
    args = p.parse_args(argv)

    stages = ("collect", "score") if args.stage == "all" else (args.stage,)
    keywords = tuple(k.strip() for k in args.keywords.split(",") if k.strip())

    def cycle() -> dict:
        res = run_cycle(
            keywords=keywords, days=args.days, max_results=args.max, order=args.order,
            region=args.region, language=args.language, collect_comments=args.comments,
            max_comments=args.max_comments, top_n_comments=args.top_n_comments,
            score_limit=args.score_limit, youtube_key=args.youtube_key,
            gemini_key=args.gemini_key, db_path=args.db, stages=stages, top=args.top,
        )
        print_ranking(res.get("ranking", []))
        return res

    if args.watch:
        log(f"👀 오케스트레이터 데몬 시작 (간격 {args.interval}s). Ctrl+C 로 중단.")
        try:
            while True:
                cycle()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("데몬 종료.")
            return 0

    cycle()
    return 0


if __name__ == "__main__":
    sys.exit(main())
