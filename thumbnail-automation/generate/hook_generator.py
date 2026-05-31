import json
import logging
import random
from pathlib import Path

from core.config import VOCAB_DIR, HOOK_TYPES, GEMINI_API_KEY, ANALYSIS_MODEL
from core.utils import safe_json_loads

logger = logging.getLogger(__name__)

_HOOK_TYPES_PATH = VOCAB_DIR / "hook_types.json"
_EMOTION_MAP_PATH = VOCAB_DIR / "emotion_map.json"

def _load_vocab():
    hook_data = json.loads(_HOOK_TYPES_PATH.read_text(encoding="utf-8"))
    emot_data = json.loads(_EMOTION_MAP_PATH.read_text(encoding="utf-8"))
    return {h["id"]: h for h in hook_data["hook_types"]}, emot_data["emotion_map"]

HOOKS_MAP, EMOTION_MAP = _load_vocab()


def _pick_hook_type(analysis):
    emo_raw = analysis.get("layer10_emotion") or {}
    if isinstance(emo_raw, str):
        emo_raw = safe_json_loads(emo_raw, {})
    primary_emo = emo_raw.get("primary", "joy")
    preferred = EMOTION_MAP.get(primary_emo, {}).get("preferred_hook", HOOK_TYPES)
    face = analysis.get("layer3_face") or {}
    if isinstance(face, str):
        face = safe_json_loads(face, {})
    if face.get("emotion_intensity") == "extreme" and "감정과잉" in preferred:
        preferred = [h for h in preferred if h != "감정과잉"] or HOOK_TYPES
    return preferred[0] if preferred else random.choice(HOOK_TYPES)


def _build_rule_based_idea(analysis, hook_type):
    hook_cfg = HOOKS_MAP.get(hook_type, {})
    examples = hook_cfg.get("examples", [])
    face = safe_json_loads(analysis.get("layer3_face"), {}) if isinstance(analysis.get("layer3_face"), str) else (analysis.get("layer3_face") or {})
    text_layer = safe_json_loads(analysis.get("layer9_text"), {}) if isinstance(analysis.get("layer9_text"), str) else (analysis.get("layer9_text") or {})
    ideas = []
    if hook_type == "시선강탈":
        if face.get("gaze_direction") != "camera":
            ideas.append("인물 시선을 카메라 정면으로 바꾸어 시청자와 눈을 맞춰게 한다")
        ideas.append("한쪽 눈썬만 올린 비대칭 표정으로 '이게 담지?' 반응을 유도한다")
    elif hook_type == "감정과잉":
        ideas.append("눈가에 눈물 한 방울을 추가해 감동 포인트를 시각화한다")
        ideas.append("손을 가슴에 억는 제스처를 넣어 감정 뫰입감을 높인다")
    elif hook_type == "정보불완전":
        if text_layer.get("has_text"):
            ideas.append("텍스트 끝을 '...' 또는 '?' 로 끔어 궁금증을 유발한다")
        ideas.append("인물 얼굴 일부를 프레임 밖으로 잘라 '더 보고 싶다' 심리를 자극한다")
    elif hook_type == "비현실대비":
        ideas.append("전통 한복 의상에 사이버팱크 조명/배경을 합성해 인지 충돌을 만든다")
        ideas.append("트로트 가수에게 힙합 액세서리(체인, 선글라스)를 추가해 반전미를 준다")
    elif hook_type == "레트로리마스터":
        ideas.append("VHS 노이즈 필터를 인물 주변에만 적용하고 텍스트는 선명하게 유지한다")
        ideas.append("70~80년대 컴러 그레이딩(세피아/바랜 색감)으로 그리움을 자극한다")
    chosen = ideas[0] if ideas else (examples[0] if examples else "차별화 요소 추가")
    return f"[{hook_type}] {chosen}"


_HOOK_PROMPT_TEMPLATE = """
당신은 유튜브 썸네일 CTR 전문가입니다.
다음 정보를 바탕으로 클릭율을 높이는 "나만의 한 끗" 아이디어를 생성하세요.

[분석 요약]
- 감정: {emotion}
- 현재 클릭 트리거: {trigger}
- 인물 시선: {gaze}
- 텍스트 유무: {has_text}
- 배경 유형: {bg_type}
- Layer 12 기초 제안: {layer12}

[한 끗 유형]: {hook_type}
[유형 설명]: {hook_desc}

형식:
💡 한 끗: [구체적 구현 방법]
📈 기대 효과: [CTR 상승 이유]
"""

def generate_hook_with_ai(analysis, hook_type=None):
    if not GEMINI_API_KEY:
        return _rule_based_hook(analysis, hook_type)
    hook_type = hook_type or _pick_hook_type(analysis)
    hook_cfg = HOOKS_MAP.get(hook_type, {})
    emo_raw = safe_json_loads(analysis.get("layer10_emotion"), {}) if isinstance(analysis.get("layer10_emotion"), str) else (analysis.get("layer10_emotion") or {})
    face = safe_json_loads(analysis.get("layer3_face"), {}) if isinstance(analysis.get("layer3_face"), str) else (analysis.get("layer3_face") or {})
    bg = safe_json_loads(analysis.get("layer8_background"), {}) if isinstance(analysis.get("layer8_background"), str) else (analysis.get("layer8_background") or {})
    text_l = safe_json_loads(analysis.get("layer9_text"), {}) if isinstance(analysis.get("layer9_text"), str) else (analysis.get("layer9_text") or {})
    prompt = _HOOK_PROMPT_TEMPLATE.format(
        emotion=emo_raw.get("primary", "unknown"), trigger=analysis.get("layer11_trigger", ""),
        gaze=face.get("gaze_direction", "unknown"), has_text=text_l.get("has_text", False),
        bg_type=bg.get("type", "unknown"), layer12=analysis.get("layer12_hook", ""),
        hook_type=hook_type, hook_desc=hook_cfg.get("description", ""))
    try:
        from google import genai as _genai
        client = _genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(model=ANALYSIS_MODEL, contents=prompt)
        text = resp.text.strip()
        idea = effect = ""
        for line in text.splitlines():
            if line.startswith("💡 한 끗:"):
                idea = line.replace("💡 한 끗:", "").strip()
            elif line.startswith("📈 기대 효과:"):
                effect = line.replace("📈 기대 효과:", "").strip()
        return {"hook_type": hook_type, "idea": idea or text, "expected_effect": effect, "source": "ai"}
    except Exception as e:
        logger.warning("Gemini 한 끗 생성 실패: %s", e)
        return _rule_based_hook(analysis, hook_type)


def _rule_based_hook(analysis, hook_type=None):
    hook_type = hook_type or _pick_hook_type(analysis)
    return {"hook_type": hook_type, "idea": _build_rule_based_idea(analysis, hook_type), "expected_effect": "", "source": "rule"}


def _build_enriched_context(analysis, category=""):
    lines = []
    try:
        from generate.pattern_miner import mine_patterns, pattern_to_hook_hint
        patterns = mine_patterns()
        if patterns.get("sample_count", 0) > 0:
            lines.append(pattern_to_hook_hint(patterns))
    except Exception:
        pass
    try:
        from generate.feedback_learner import learn_from_approved
        fb = learn_from_approved()
        if fb.get("sample_count", 0) > 0:
            lines.append(fb.get("insight", ""))
    except Exception:
        pass
    try:
        from collect.pinterest_collector import get_trend_colors
        colors = get_trend_colors(category, limit=10)
        if colors:
            lines.append(f"[Pinterest 트렌드 색상] {', '.join(colors[:5])}")
    except Exception:
        pass
    try:
        from generate.custom_hooks import get_custom_hooks_for_category
        custom = get_custom_hooks_for_category(category)
        if custom:
            lines.append(f"[나만의 공식] {' / '.join(h['description'] for h in custom[:3])}")
    except Exception:
        pass
    return "\n".join(lines)


def generate_hook(analysis, hook_type=None, use_ai=True, category=""):
    if not hook_type:
        try:
            from generate.feedback_learner import get_best_hook_type_from_feedback
            hook_type = get_best_hook_type_from_feedback()
        except Exception:
            pass
    enriched_ctx = _build_enriched_context(analysis, category)
    if use_ai and GEMINI_API_KEY:
        result = generate_hook_with_ai(analysis, hook_type)
        if enriched_ctx and result.get("source") == "ai":
            result["context"] = enriched_ctx
        return result
    result = _rule_based_hook(analysis, hook_type)
    if enriched_ctx:
        result["context"] = enriched_ctx
    return result


def list_all_hook_types(include_custom=True):
    base = list(HOOKS_MAP.values())
    if include_custom:
        try:
            from generate.custom_hooks import list_custom_hooks
            base += list_custom_hooks()
        except Exception:
            pass
    return base
