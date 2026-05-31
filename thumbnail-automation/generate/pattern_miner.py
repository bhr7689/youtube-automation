import json
import logging
from collections import Counter

from core.store import get_conn
from core.utils import safe_json_loads

logger = logging.getLogger(__name__)


def mine_patterns(min_view_count=50_000, limit=200):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT a.layer1_composition, a.layer2_colors, a.layer3_face, a.layer8_background,
                   a.layer9_text, a.layer10_emotion, a.layer11_trigger, t.view_count
            FROM analysis a
            JOIN thumbnails t ON t.thumb_id = a.thumb_id
            WHERE t.view_count >= ?
            ORDER BY t.view_count DESC LIMIT ?
        """, (min_view_count, limit)).fetchall()
    if not rows:
        return {}
    comp_types, gaze_dirs, emotions = Counter(), Counter(), Counter()
    bg_types, text_pos, triggers, color_temps = Counter(), Counter(), Counter(), Counter()
    for row in rows:
        comp = safe_json_loads(row["layer1_composition"], {})
        color = safe_json_loads(row["layer2_colors"], {})
        face = safe_json_loads(row["layer3_face"], {})
        bg = safe_json_loads(row["layer8_background"], {})
        text = safe_json_loads(row["layer9_text"], {})
        if comp.get("type"): comp_types[comp["type"]] += 1
        if face.get("gaze_direction"): gaze_dirs[face["gaze_direction"]] += 1
        if face.get("emotion"): emotions[face["emotion"]] += 1
        if bg.get("type"): bg_types[bg["type"]] += 1
        if text.get("position"): text_pos[text["position"]] += 1
        if row["layer11_trigger"]: triggers[row["layer11_trigger"]] += 1
        if color.get("color_temperature"): color_temps[color["color_temperature"]] += 1
    total = len(rows)
    def top(counter, n=3):
        return [{"value": k, "count": v, "pct": round(v/total*100)} for k, v in counter.most_common(n)]
    return {"sample_count": total, "min_view_count": min_view_count,
        "composition": top(comp_types), "gaze": top(gaze_dirs), "emotion": top(emotions),
        "background": top(bg_types), "text_position": top(text_pos),
        "triggers": top(triggers), "color_temp": top(color_temps)}


def pattern_to_hook_hint(patterns):
    if not patterns:
        return ""
    lines = [f"[DB 패턴 인사이트 — 고조회수 {patterns.get('sample_count',0)}개 기준]"]
    if patterns.get("gaze"):
        t = patterns["gaze"][0]
        lines.append(f"• 시선: {t['value']} ({t['pct']}% 사용)")
    if patterns.get("composition"):
        t = patterns["composition"][0]
        lines.append(f"• 구도: {t['value']} ({t['pct']}%)")
    if patterns.get("triggers"):
        t = patterns["triggers"][0]
        lines.append(f"• 주 트리거: {t['value']} ({t['pct']}%)")
    if patterns.get("color_temp"):
        t = patterns["color_temp"][0]
        lines.append(f"• 색온도: {t['value']} ({t['pct']}%)")
    return "\n".join(lines)
