import json
import logging
from datetime import datetime
from pathlib import Path

from core.store import get_stats, get_conn
from core.config import ROOT_DIR

logger = logging.getLogger(__name__)


def generate_daily_report():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    stats = get_stats()
    with get_conn() as conn:
        today_thumbs = conn.execute("SELECT COUNT(*) FROM thumbnails WHERE collected_at >= ?",
            (datetime.utcnow().strftime("%Y-%m-%d"),)).fetchone()[0]
        today_analyzed = conn.execute("SELECT COUNT(*) FROM analysis WHERE analyzed_at >= ?",
            (datetime.utcnow().strftime("%Y-%m-%d"),)).fetchone()[0]
        today_approved = conn.execute("SELECT COUNT(*) FROM generated_thumbnails WHERE status='approved' AND created_at >= ?",
            (datetime.utcnow().strftime("%Y-%m-%d"),)).fetchone()[0]
        top_generated = conn.execute("""
            SELECT g.gen_id, g.hook_type, g.ctr_score, g.image_path, t.title, c.name as channel_name
            FROM generated_thumbnails g
            JOIN analysis a ON a.analysis_id = g.analysis_id
            JOIN thumbnails t ON t.thumb_id = a.thumb_id
            JOIN channels c ON c.channel_id = t.channel_id
            WHERE g.status = 'pending'
            ORDER BY g.ctr_score DESC LIMIT 5
        """).fetchall()
        top_cats = conn.execute("SELECT category, COUNT(*) as cnt FROM channels GROUP BY category ORDER BY cnt DESC LIMIT 5").fetchall()

    from operate.youtube_trend_watcher import get_upload_timing_advice, extract_trend_keywords
    timing = get_upload_timing_advice()
    keywords = extract_trend_keywords(limit=100)
    strategy = _build_strategy(stats, timing, keywords)

    report = {"date": today, "cumulative": stats,
        "today": {"collected": today_thumbs, "analyzed": today_analyzed, "approved": today_approved},
        "top_candidates": [dict(r) for r in top_generated],
        "top_categories": [dict(r) for r in top_cats],
        "upload_timing": timing, "trend_keywords": keywords[:10], "strategy": strategy}

    path = ROOT_DIR / "data" / f"daily_report_{today}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _build_strategy(stats, timing, keywords):
    advice = []
    pending = stats.get("pending", 0)
    approved = stats.get("approved", 0)
    if pending > 10:
        advice.append(f"🔴 검수 대기 {pending}개 — 빨리 검수해 좋은 썸네일을 업로드 타이밍에 맞춰세요.")
    if approved == 0:
        advice.append("💡 아직 승인된 썸네일이 없습니다. 이미지 생성 후 검수 탭에서 최소 1개를 승인하면 피드백 학습이 시작됩니다.")
    advice.append(f"⏰ {timing['advice']}")
    if keywords:
        kw_str = ", ".join([k["keyword"] for k in keywords[:5]])
        advice.append(f"🔥 지금 뜨는 키워드: {kw_str} — 썸네일 텍스트에 반영하세요.")
    if stats.get("thumbnails", 0) < 100:
        advice.append(f"📊 수집 썸네일 {stats.get('thumbnails',0)}개 — 100개 이상 수집해야 패턴 마이닝 정확도가 높아집니다.")
    advice.append("🎯 알고리즘 핵심: CTR 3% 이상 유지 → 썸네일 클릭율이 노출 확대의 열쇠.")
    advice.append("🎨 A/B 원칙: 같은 영상에 썸네일 2~3개 변형 테스트 → 클릭율 높은 것으로 교체.")
    return advice


def format_report_text(report):
    lines = [f"📊 일일 리포트 — {report['date']}", "=" * 50, "",
        f"📈 오늘 현황",
        f"  수집: {report['today']['collected']}개  분석: {report['today']['analyzed']}개  승인: {report['today']['approved']}개",
        "", "📦 누적 현황",
        f"  채널: {report['cumulative']['channels']}  썸네일: {report['cumulative']['thumbnails']}  분석: {report['cumulative']['analyzed']}  승인: {report['cumulative']['approved']}",
        "", "🔥 트렌드 키워드"]
    for kw in report.get("trend_keywords", [])[:5]:
        lines.append(f"  #{kw['keyword']} ({kw['count']}회)")
    lines += ["", "🎯 오늘의 알고리즘 전략"]
    for s in report.get("strategy", []):
        lines.append(f"  {s}")
    return "\n".join(lines)
