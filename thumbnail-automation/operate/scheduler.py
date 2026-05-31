import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import schedule

from core.store import init_db, list_channels, get_stats
from core.utils import setup_logging
from core.config import ROOT_DIR

logger = logging.getLogger(__name__)

LOG_PATH = ROOT_DIR / "data" / "scheduler_log.jsonl"


def _log(task, status, detail=""):
    entry = {"ts": datetime.utcnow().isoformat(), "task": task, "status": status, "detail": detail}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("[%s] %s — %s", task, status, detail)


def task_detect_new_uploads():
    try:
        from operate.youtube_trend_watcher import detect_new_uploads, save_trending_thumbnails
        channels = list_channels()
        if not channels:
            _log("detect_uploads", "skip", "등록된 채널 없음"); return
        new_vids = detect_new_uploads([c["channel_id"] for c in channels], since_hours=24)
        if new_vids:
            save_trending_thumbnails(new_vids, download=True)
            _auto_analyze(limit=len(new_vids))
            _log("detect_uploads", "ok", f"새 업로드 {len(new_vids)}개 감지·분석")
        else:
            _log("detect_uploads", "ok", "새 업로드 없음")
    except Exception as e:
        _log("detect_uploads", "error", str(e))


def task_pinterest_trends():
    try:
        from collect.pinterest_collector import collect_pinterest_trends
        n = collect_pinterest_trends(max_per_keyword=10, download=True)
        _log("pinterest", "ok", f"{n}개 핀 수집")
    except Exception as e:
        _log("pinterest", "error", str(e))


def task_trending_thumbnails():
    try:
        from operate.youtube_trend_watcher import fetch_trending, save_trending_thumbnails
        videos = fetch_trending(region="KR", max_results=30)
        saved = save_trending_thumbnails(videos, download=True)
        _auto_analyze(limit=saved)
        _log("trending", "ok", f"급상승 {saved}개 수집·분석")
    except Exception as e:
        _log("trending", "error", str(e))


def task_pattern_mining():
    try:
        from generate.pattern_miner import mine_patterns
        from generate.feedback_learner import learn_from_approved
        patterns = mine_patterns()
        feedback = learn_from_approved()
        _log("pattern_mining", "ok", f"패턴샘플={patterns.get('sample_count',0)}, 승인학습={feedback.get('sample_count',0)}")
    except Exception as e:
        _log("pattern_mining", "error", str(e))


def task_peak_time_alert():
    try:
        from operate.youtube_trend_watcher import get_upload_timing_advice, extract_trend_keywords
        timing = get_upload_timing_advice()
        keywords = extract_trend_keywords(limit=50)
        _log("peak_alert", "ok", timing["advice"])
    except Exception as e:
        _log("peak_alert", "error", str(e))


def task_daily_report():
    try:
        from operate.reporter import generate_daily_report
        report = generate_daily_report()
        _log("daily_report", "ok", f"승인:{report.get('approved',0)}, 분석:{report.get('analyzed',0)}")
    except Exception as e:
        _log("daily_report", "error", str(e))


def _auto_analyze(limit=20):
    try:
        from analyze.vision_analyzer import analyze_batch
        done = analyze_batch(limit=limit)
        if done:
            _log("auto_analyze", "ok", f"{done}개 분석")
    except Exception as e:
        _log("auto_analyze", "error", str(e))


TASKS = {
    "detect": task_detect_new_uploads, "pinterest": task_pinterest_trends,
    "trend": task_trending_thumbnails, "pattern": task_pattern_mining,
    "peak": task_peak_time_alert, "report": task_daily_report,
}


def run_all():
    logger.info("=== 전체 태스크 1회 실행 ===")
    for name, fn in TASKS.items():
        logger.info(">> %s", name)
        fn()
    stats = get_stats()
    logger.info("완료 | 채널:%d 썸네일:%d 분석:%d 생성:%d 승인:%d",
        stats["channels"], stats["thumbnails"], stats["analyzed"], stats["generated"], stats["approved"])


def start_scheduler():
    logger.info("=== 스케줄러 데모나 시작 ===")
    schedule.every().day.at("06:00").do(task_detect_new_uploads)
    schedule.every().day.at("08:00").do(task_pinterest_trends)
    schedule.every().day.at("10:00").do(task_trending_thumbnails)
    schedule.every().day.at("14:00").do(task_pattern_mining)
    schedule.every().day.at("19:00").do(task_peak_time_alert)
    schedule.every().day.at("23:00").do(task_daily_report)
    schedule.every(6).hours.do(task_detect_new_uploads)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    setup_logging("INFO")
    init_db()
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--task", choices=list(TASKS.keys()))
    args = parser.parse_args()
    if args.task:
        TASKS[args.task]()
    elif args.run_now:
        run_all()
    elif args.watch:
        start_scheduler()
    else:
        parser.print_help()
