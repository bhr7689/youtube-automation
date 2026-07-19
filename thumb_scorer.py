"""thumb_scorer.py — 생성한 썸네일 '이미지'를 GPT-4o Vision 이 재채점.

CTR 의 1번 레버는 썸네일 이미지. 만든 이미지를 실제로 보고
사람이 피드에서 클릭할지를 냉정하게 채점 + 개선 팁.
5기준(각 0-20, 합 100): 시선집중·대비/색팝·감정/무드·소형가독성·제목일치.
키 없으면 None(=UI 안내). Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import re

CRIT = ["focal", "contrast", "emotion", "readability", "title_match"]
LAB = {"focal": "시선집중", "contrast": "대비·색팝", "emotion": "감정·무드",
       "readability": "소형가독성", "title_match": "제목일치"}

# 고CTR 썸네일 생성 지시 (생성 프롬프트에 주입)
CTR_DIRECTIVE = ("High-CTR YouTube thumbnail: ONE clear focal subject, bold high contrast, "
                 "vivid pop colors, strong mood and emotion, clean uncluttered composition "
                 "that reads instantly at tiny mobile size, cinematic lighting.")


def _is_img(u: str) -> bool:
    return isinstance(u, str) and (u.startswith("http")
                                   or bool(re.match(r"data:image/(png|jpe?g|webp)", u, re.I)))


def score(image_ref: str, title: str, genre: str = "", pattern: dict | None = None) -> dict | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or not _is_img(image_ref):
        return None
    tp = (pattern or {}).get("thumbnail_pattern", {})
    brief = " / ".join(filter(None, [tp.get("composition", ""), tp.get("mood", "")])) or "(패턴 없음)"
    prompt = f"""너는 유튜브 CTR 전문가다. 아래 '{genre}' 썸네일 이미지가 피드에서
사람이 클릭할지를 냉정히 채점하라. 제목: "{title}"
이 장르 승리 썸네일 패턴: {brief}

5기준(각 0-20):
- focal: 시선집중(0.5초에 눈이 어디로 가나, 초점 하나로 명확한가)
- contrast: 대비·색팝(피드에서 튀는가, 경쟁 썸네일 사이에서 눈에 띄나)
- emotion: 감정·무드(정서가 살아있나, 분위기가 전달되나)
- readability: 소형 가독성(폰 작은 크기에서도 뭔지 읽히나, 안 뭉개지나)
- title_match: 제목과의 일치(이미지가 제목이 말하는 장면·감정과 맞나)

JSON만:
{{"focal":0,"contrast":0,"emotion":0,"readability":0,"title_match":0,
  "tips":["개선점1","개선점2","개선점3"],"verdict":"한 줄 총평"}}"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_ref, "detail": "low"}}]}],
            temperature=0.3, max_tokens=600, response_format={"type": "json_object"})
        d = json.loads(r.choices[0].message.content or "{}")
        for c in CRIT:
            d[c] = int(d.get(c, 0) or 0)
        d["total"] = sum(d[c] for c in CRIT)
        d.setdefault("tips", [])
        d.setdefault("verdict", "")
        return d
    except Exception:                   # noqa: BLE001
        return None
