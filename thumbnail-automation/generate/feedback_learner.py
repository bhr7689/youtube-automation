import json
import logging
from collections import Counter

from core.store import get_conn
from core.utils import safe_json_loads

logger = logging.getLogger(__name__)


def learn_from_approved(limit=100):
    with get_conn() as conn:
        approved = conn.execute("""
            SELECT g.hook_type, g.ctr_score, g.prompt_text, a.layer10_emotion,
                   a.layer11_trigger, a.layer2_colors
            FROM generated_thumbnails g
            JOIN analysis a ON a.analysis_id = g.analysis_id
            WHERE g.status = 'approved'
            ORDER BY g.ctr_score DESC LIMIT ?
        """, (limit,)).fetchall()
    if not approved:
        return {"sample_count": 0, "insight": "승인된 썸네일이 아직 없습니다."}
    hook_counter, trigger_ctr, color_ctr = Counter(), Counter(), Counter()
    total_ctr = 0.0
    for row in approved:
        if row["hook_type"]: hook_counter[row["hook_type"]] += 1
        if row["layer11_trigger"]: trigger_ctr[row["layer11_trigger"]] += 1
        total_ctr += row["ctr_score"] or 0
        colors = safe_json_loads(row["layer2_colors"], {})
        if colors.get("color_temperature"): color_ctr[colors["color_temperature"]] += 1
    n = len(approved)
    top_hooks = [{"hook": k, "count": v, "pct": round(v/n*100)} for k, v in hook_counter.most_common(3)]
    top_triggers = [{"trigger": k, "count": v} for k, v in trigger_ctr.most_common(3)]
    top_colors = [{"temp": k, "count": v} for k, v in color_ctr.most_common(3)]
    avg_ctr = round(total_ctr / n, 1)
    insight_lines = [f"✅ 승인 {n}개 학습 결과"]
    if top_hooks: insight_lines.append(f"• 최다 승인 한 끗: {top_hooks[0]['hook']} ({top_hooks[0]['pct']}%)")
    if top_triggers: insight_lines.append(f"• 효과적인 트리거: {top_triggers[0]['trigger']}")
    if top_colors: insight_lines.append(f"• 선호 색온도: {top_colors[0]['temp']}")
    insight_lines.append(f"• 평균 CTR 예측 점수: {avg_ctr}점")
    return {"sample_count": n, "avg_ctr": avg_ctr, "top_hooks": top_hooks,
        "top_triggers": top_triggers, "top_colors": top_colors, "insight": "\n".join(insight_lines)}


def get_best_hook_type_from_feedback():
    result = learn_from_approved()
    if result.get("top_hooks"):
        return result["top_hooks"][0]["hook"]
    return None
