import logging
from core.utils import safe_json_loads

logger = logging.getLogger(__name__)


def score_ctr(analysis, hook, prompt):
    breakdown = {}
    total = 0
    face = analysis.get("layer3_face") or {}
    if isinstance(face, str): face = safe_json_loads(face, {})
    face_score = 0
    if face.get("has_face"):
        face_score += 10
        if face.get("gaze_direction") == "camera": face_score += 8
        elif face.get("gaze_direction") in ("left", "right"): face_score += 4
        face_score += {"extreme": 7, "intense": 5, "moderate": 3, "subtle": 1}.get(face.get("emotion_intensity", "moderate"), 0)
    breakdown["얼굴/시선"] = min(face_score, 25)
    total += breakdown["얼굴/시선"]

    color = analysis.get("layer2_colors") or {}
    if isinstance(color, str): color = safe_json_loads(color, {})
    c_score = {"very_high": 20, "high": 15, "medium": 8, "low": 3}.get(color.get("contrast_level", "medium"), 8)
    sat = color.get("saturation", "normal")
    if sat == "vivid": c_score = min(c_score + 3, 20)
    if sat == "muted": c_score = max(c_score - 5, 0)
    breakdown["색상대비"] = c_score
    total += c_score

    text = analysis.get("layer9_text") or {}
    if isinstance(text, str): text = safe_json_loads(text, {})
    t_score = 0
    if text.get("has_text"):
        t_score += 8
        if text.get("size_relative") in ("large", "dominant"): t_score += 6
        if text.get("has_stroke") or text.get("has_shadow"): t_score += 4
        char_count = text.get("char_count", 0)
        if 5 <= char_count <= 20: t_score += 2
        elif char_count > 30: t_score -= 2
    breakdown["텍스트가독성"] = max(min(t_score, 20), 0)
    total += breakdown["텍스트가독성"]

    hook_type = hook.get("hook_type", "")
    h_score = 10 if hook_type else 0
    if hook.get("source") == "ai": h_score += 5
    if hook.get("expected_effect"): h_score += 5
    breakdown["한끗차별화"] = min(h_score, 20)
    total += breakdown["한끗차별화"]

    comp = analysis.get("layer1_composition") or {}
    if isinstance(comp, str): comp = safe_json_loads(comp, {})
    co_score = {"high": 12, "medium": 7, "low": 3}.get(comp.get("tension_level", "medium"), 7)
    if comp.get("type") in ("diagonal", "close_up_fill"): co_score = min(co_score + 3, 15)
    breakdown["구도완성도"] = min(co_score, 15)
    total += breakdown["구도완성도"]

    total = min(total, 100)
    if total >= 85: grade = "S — 최상위 클릭율 예상"
    elif total >= 70: grade = "A — 높은 클릭율 예상"
    elif total >= 55: grade = "B — 평균 이상"
    elif total >= 40: grade = "C — 개선 필요"
    else: grade = "D — 전면 재설계 권장"

    advice = []
    if breakdown["얼굴/시선"] < 15:
        advice.append("인물 시선을 카메라 정면으로 바꾸거나 감정 강도를 높이세요.")
    if breakdown["색상대비"] < 12:
        advice.append("배경과 인물의 색상 대비를 높여 시선을 집중시키세요.")
    if breakdown["텍스트가독성"] < 10:
        advice.append("텍스트에 굵은 외곽선을 추가하거나 크기를 키우세요.")
    if breakdown["한끗차별화"] < 10:
        advice.append("한 끗 아이디어를 더 구체적으로 구현하세요.")
    return {"total": total, "breakdown": breakdown, "grade": grade, "advice": advice}


def format_score_report(score_result):
    lines = [f"📊 CTR 예측 점수: {score_result['total']}점 / 100점",
             f"🏆 등급: {score_result['grade']}", "", "📋 항목별 점수:"]
    for k, v in score_result["breakdown"].items():
        bar = "█" * (v // 4) + "░" * (5 - v // 4)
        lines.append(f"  {k:<12} {bar} {v}점")
    if score_result["advice"]:
        lines += ["", "💬 개선 조언:"]
        for a in score_result["advice"]:
            lines.append(f"  • {a}")
    return "\n".join(lines)
