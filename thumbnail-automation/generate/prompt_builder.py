import json
import logging

from core.config import VOCAB_DIR, GEMINI_API_KEY, ANALYSIS_MODEL
from core.utils import safe_json_loads

logger = logging.getLogger(__name__)

_EMOTION_MAP = json.loads((VOCAB_DIR / "emotion_map.json").read_text(encoding="utf-8"))["emotion_map"]
_HOOK_TYPES = json.loads((VOCAB_DIR / "hook_types.json").read_text(encoding="utf-8"))["hook_types"]
_HOOK_KW_MAP = {h["id"]: h.get("prompt_keywords", []) for h in _HOOK_TYPES}


def _get(d, *keys, default=""):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d if d is not None else default


def build_prompt_rule_based(analysis, hook):
    def parse(key):
        v = analysis.get(key)
        return safe_json_loads(v, {}) if isinstance(v, str) else (v or {})
    comp = parse("layer1_composition")
    color = parse("layer2_colors")
    face = parse("layer3_face")
    hair = parse("layer4_hair")
    feat = parse("layer5_feature")
    obj = parse("layer6_objects")
    bg = parse("layer8_background")
    text = parse("layer9_text")
    emo = parse("layer10_emotion")

    hook_type = hook.get("hook_type", "")
    hook_idea = hook.get("idea", "")
    hook_kws = _HOOK_KW_MAP.get(hook_type, [])
    primary_emo = emo.get("primary", "joy")
    rec_colors = _EMOTION_MAP.get(primary_emo, {}).get("color_palette", [])

    parts = ["YouTube thumbnail, 16:9 aspect ratio, ultra-detailed, professional quality"]
    comp_map = {"center_heavy": "centered composition", "rule_of_thirds": "rule of thirds composition",
        "diagonal": "dynamic diagonal composition", "close_up_fill": "extreme close-up filling frame",
        "leading_lines": "leading lines composition", "symmetry": "symmetrical composition"}
    if comp.get("type") in comp_map:
        parts.append(comp_map[comp["type"]])
    if face.get("has_face"):
        gaze = face.get("gaze_direction", "camera")
        emo_word = face.get("emotion", "joy")
        intensity = face.get("emotion_intensity", "moderate")
        mouth = "mouth wide open, " if face.get("mouth_open") else ""
        eye = "enlarged eyes, " if face.get("eye_scale") == "enlarged" else ""
        parts.append(f"Korean person, {gaze} gaze, {emo_word} expression, {intensity} intensity, {mouth}{eye}highly expressive face")
    if hair.get("has_hair") and hair.get("style") != "none":
        parts.append(f"{hair.get('style','medium')} hair, {hair.get('color','black')} color")
    if hook_kws:
        parts.append(", ".join(hook_kws[:3]))
    bg_map = {"solid_color": "solid color background", "gradient": f"{bg.get('brightness','dark')} gradient background",
        "real_photo": "blurred real photo background", "cg": "digital art background",
        "blur": "bokeh background, depth of field", "pattern": "patterned background"}
    parts.append(bg_map.get(bg.get("type", "gradient"), "dramatic background"))
    primary_hex = color.get("primary_hex") or (rec_colors[0] if rec_colors else "#FF6B35")
    parts.append(f"color palette: {primary_hex}, high contrast, vivid colors")
    if text.get("has_text"):
        lang = text.get("language", "korean")
        pos = text.get("position", "bottom")
        size = text.get("size_relative", "large")
        stroke = "with bold stroke outline, " if text.get("has_stroke") else ""
        sample = text.get("content_sample", "")
        lang_str = "Korean and English text" if lang == "both" else f"{lang} text"
        parts.append(f"{lang_str} overlay, {size} {pos} text, {stroke}legible typography{', text: ' + sample if sample else ''}")
    if obj.get("has_animal") and obj.get("animal_type") != "none":
        parts.append(f"{obj.get('animal_type')} in scene")
    parts.extend(["sharp focus", "vibrant", "eye-catching", "professional thumbnail design", "click-bait visual", "8k resolution", "studio lighting"])
    dalle_prompt = ", ".join(p for p in parts if p)
    emo_word = face.get("emotion", "joy") if face.get("has_face") else ""
    sd_tags = ["youtube thumbnail", "16:9",
        f"{'korean person' if face.get('has_face') else 'no face'}",
        f"{emo_word if face.get('has_face') else 'dramatic scene'}",
        f"{primary_emo} mood", ", ".join(hook_kws[:2]),
        f"{bg.get('type','gradient')} background", "high contrast", "vivid", "sharp", "professional"]
    sd_prompt = ", ".join(t for t in sd_tags if t.strip())
    negative = ("blurry, low quality, pixelated, watermark, ugly, bad anatomy, deformed, duplicate, "
                "text errors, boring composition, dull colors, dark, underexposed, amateur")
    return {"dalle": dalle_prompt, "sd": sd_prompt, "negative": negative,
        "style_tags": [hook_type] + hook_kws[:3] + [primary_emo], "hook_idea": hook_idea}


def build_prompt_with_ai(analysis, hook):
    if not GEMINI_API_KEY:
        return build_prompt_rule_based(analysis, hook)
    def parse(key):
        v = analysis.get(key)
        return safe_json_loads(v, {}) if isinstance(v, str) else (v or {})
    face = parse("layer3_face")
    bg = parse("layer8_background")
    text = parse("layer9_text")
    emo = parse("layer10_emotion")
    comp = parse("layer1_composition")
    prompt_tmpl = """
당신은 DALL-E 3 이미지 생성 전문가입니다. 아래 정보를 바탕으로 유튜브 썸네일 생성용 프롬프트를 작성하세요.
[썸네일 분석 요약]
- 감정 톤: {emotion}
- 구도: {composition}
- 인물: {face_desc}
- 배경: {bg_desc}
- 현재 텍스트: {text_sample}
- 클릭 트리거: {trigger}
[한 끗 아이디어]
{hook_idea}
[출력 형식 — JSON만 출력]
{{"dalle_prompt": "", "sd_prompt": "", "negative_prompt": "", "key_elements": []}}
"""
    prompt = prompt_tmpl.format(
        emotion=emo.get("primary", "joy"), composition=comp.get("type", "center_heavy"),
        face_desc=f"gaze={face.get('gaze_direction','none')}, emotion={face.get('emotion','none')}" if face.get("has_face") else "no face",
        bg_desc=f"{bg.get('type','gradient')}, {bg.get('brightness','medium')} brightness",
        text_sample=text.get("content_sample", "없음"), trigger=analysis.get("layer11_trigger", ""),
        hook_idea=hook.get("idea", ""))
    try:
        from google import genai as _genai
        client = _genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(model=ANALYSIS_MODEL, contents=prompt)
        raw = resp.text.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        data = json.loads(raw)
        return {"dalle": data.get("dalle_prompt", ""), "sd": data.get("sd_prompt", ""),
            "negative": data.get("negative_prompt", ""), "style_tags": data.get("key_elements", []),
            "hook_idea": hook.get("idea", "")}
    except Exception as e:
        logger.warning("AI 프롬프트 생성 실패: %s", e)
        return build_prompt_rule_based(analysis, hook)


def build_prompt(analysis, hook, use_ai=True):
    if use_ai and GEMINI_API_KEY:
        return build_prompt_with_ai(analysis, hook)
    return build_prompt_rule_based(analysis, hook)
