import json
import logging
from pathlib import Path
from datetime import datetime

from google import genai
from google.genai import types
from PIL import Image
import httpx

from core.config import GEMINI_API_KEY, ANALYSIS_MODEL
from core.store import init_db, list_unanalyzed_thumbnails, insert_analysis, get_conn
from core.utils import new_id, url_hash, setup_logging

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

ANALYSIS_PROMPT = """
당신은 유튜브 썸네일 전문 분석가입니다.
아래 썸네일 이미지를 12개 레이어로 초정밀 분석하세요.
결과는 반드시 JSON 형식으로만 출력하세요 (설명 텍스트 없이).

{
  "layer1_composition": {"type": "center_heavy|rule_of_thirds|diagonal|leading_lines|symmetry|close_up_fill", "subject_position": "center|left|right|top|bottom", "empty_space_pct": 0, "tension_level": "low|medium|high"},
  "layer2_colors": {"primary_hex": "#XXXXXX", "secondary_hex": "#XXXXXX", "accent_hex": "#XXXXXX", "contrast_level": "low|medium|high|very_high", "color_temperature": "warm|neutral|cool", "saturation": "muted|normal|vivid"},
  "layer3_face": {"has_face": true, "face_count": 1, "gaze_direction": "camera|left|right|up|down|none", "emotion": "joy|sadness|surprise|fear|anger|disgust|neutral|anticipation|none", "emotion_intensity": "subtle|moderate|intense|extreme", "mouth_open": true, "eye_scale": "normal|enlarged|squinted"},
  "layer4_hair": {"has_hair": true, "style": "short|medium|long|updo|hat|none", "color": "black|brown|blonde|gray|white|colored|none", "volume": "flat|normal|voluminous", "face_cover_pct": 0},
  "layer5_feature": {"items": [], "attention_grabbing": true, "description": ""},
  "layer6_objects": {"has_animal": false, "animal_type": "none", "has_food": false, "has_text_prop": false, "other_items": [], "object_count": 0},
  "layer7_layout": {"elements": [], "dominant_element": "face|text|object|background", "eye_flow": "left_to_right"},
  "layer8_background": {"type": "solid_color|gradient|real_photo|cg|blur|pattern", "brightness": "dark|medium|bright", "contrast_with_subject": "low|medium|high", "complexity": "simple|moderate|complex"},
  "layer9_text": {"has_text": true, "language": "korean|english|both|none", "font_style": "serif|sans-serif|display|handwritten|none", "size_relative": "small|medium|large|dominant", "position": "top|center|bottom|overlay|none", "color": "#XXXXXX", "has_stroke": true, "has_shadow": false, "char_count": 0, "content_sample": ""},
  "layer10_emotion": {"primary": "nostalgia|joy|gratitude|desire|curiosity|fear|excitement|calm|sadness", "secondary": "none", "overall_mood": ""},
  "layer11_trigger": "이 썸네일의 주 클릭 트리거",
  "layer12_hook": "이 썸네일에서 빠진 것, CTR을 높일 한 끗 아이디어"
}
"""


def _load_image(local_path, image_url):
    if local_path and Path(local_path).exists():
        return Image.open(local_path).convert("RGB")
    if image_url:
        try:
            resp = httpx.get(image_url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            from io import BytesIO
            return Image.open(BytesIO(resp.content)).convert("RGB")
        except Exception as e:
            logger.warning("이미지 URL 로드 실패: %s", e)
    return None


def _call_gemini(image):
    try:
        resp = _client.models.generate_content(model=ANALYSIS_MODEL, contents=[ANALYSIS_PROMPT, image])
        text = resp.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        logger.warning("Gemini 호출 실패: %s", e)
        return None


def analyze_thumbnail(thumb, llm_call=None):
    image = _load_image(thumb.get("local_path"), thumb.get("image_url"))
    if image is None:
        return None
    if llm_call:
        layers = llm_call(image)
    else:
        if not GEMINI_API_KEY:
            return None
        layers = _call_gemini(image)
    if not layers:
        return None
    analysis_id = "an_" + url_hash(thumb["thumb_id"] + datetime.utcnow().isoformat())
    row = {"analysis_id": analysis_id, "thumb_id": thumb["thumb_id"],
        "layer1_composition": layers.get("layer1_composition"),
        "layer2_colors": layers.get("layer2_colors"),
        "layer3_face": layers.get("layer3_face"),
        "layer4_hair": layers.get("layer4_hair"),
        "layer5_feature": layers.get("layer5_feature"),
        "layer6_objects": layers.get("layer6_objects"),
        "layer7_layout": layers.get("layer7_layout"),
        "layer8_background": layers.get("layer8_background"),
        "layer9_text": layers.get("layer9_text"),
        "layer10_emotion": layers.get("layer10_emotion"),
        "layer11_trigger": layers.get("layer11_trigger", ""),
        "layer12_hook": layers.get("layer12_hook", ""),
        "analyzed_at": datetime.utcnow().isoformat()}
    insert_analysis(row)
    return row


def analyze_batch(limit=20, llm_call=None):
    thumbnails = list_unanalyzed_thumbnails(limit=limit)
    if not thumbnails:
        return 0
    done = 0
    for thumb in thumbnails:
        if analyze_thumbnail(thumb, llm_call=llm_call):
            done += 1
    return done


def get_analysis_with_thumbnail(analysis_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT a.*, t.title, t.image_url, t.local_path, t.view_count, t.like_count,
                   t.comment_count, t.published_at, c.name as channel_name
            FROM analysis a
            JOIN thumbnails t ON t.thumb_id = a.thumb_id
            JOIN channels c ON c.channel_id = t.channel_id
            WHERE a.analysis_id = ?
        """, (analysis_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    for k in ["layer1_composition","layer2_colors","layer3_face","layer4_hair",
               "layer5_feature","layer6_objects","layer7_layout","layer8_background",
               "layer9_text","layer10_emotion"]:
        if isinstance(result.get(k), str):
            try:
                result[k] = json.loads(result[k])
            except Exception:
                pass
    return result


def list_analyses(limit=50):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT a.analysis_id, a.layer10_emotion, a.layer11_trigger, a.layer12_hook,
                   a.analyzed_at, t.title, t.image_url, t.local_path, t.view_count,
                   t.comment_count, t.published_at, c.name as channel_name
            FROM analysis a
            JOIN thumbnails t ON t.thumb_id = a.thumb_id
            JOIN channels c ON c.channel_id = t.channel_id
            ORDER BY a.analyzed_at DESC LIMIT ?
        """, (limit,)).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        if isinstance(r.get("layer10_emotion"), str):
            try:
                r["layer10_emotion"] = json.loads(r["layer10_emotion"])
            except Exception:
                pass
        results.append(r)
    return results
