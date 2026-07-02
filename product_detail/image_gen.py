"""Gemini로 제품 디테일 이미지를 생성한다.

업로드한 원본 사진을 '참고 베이스'로 두고, 동일 제품의
다른 컷(클로즈업·조리예시·연출컷)을 생성한다.

google-genai SDK 우선, 실패 시 google-generativeai로 폴백.
이미지 생성이 안 되면 원본 사진을 그대로 반환(안전 폴백).
"""
from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from typing import Optional

from PIL import Image

try:
    from google import genai as genai_v2
    from google.genai import types as genai_types
except Exception:  # pragma: no cover
    genai_v2 = None
    genai_types = None


# Gemini 의 이미지 생성 가능 모델 후보 (위에서부터 시도)
IMAGE_MODELS = [
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-preview-image-generation",
    "imagen-3.0-generate-002",
]


@dataclass
class GeneratedImage:
    label: str
    image: Image.Image
    is_generated: bool  # True=AI 생성, False=원본 그대로(폴백)


def _to_pil(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _extract_image_bytes(resp) -> Optional[bytes]:
    """Gemini 응답에서 첫 이미지 바이트를 꺼낸다."""
    try:
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    raw = inline.data
                    if isinstance(raw, str):
                        return base64.b64decode(raw)
                    return raw
    except Exception:
        pass
    return None


# 슬롯별 '어떤 사진이 어울리는가' 가이드 — 큐레이션 프롬프트에 사용
SLOT_GUIDE = {
    "hero": "메인 히어로 — 가장 식욕을 자극하는 압도적 한 컷 (윤기·색감·전체 모습 최고인 사진)",
    "close_up": "질감 클로즈업 — 단면·속살·육즙·촉촉함이 가까이 보이는 사진",
    "size_compare": "크기 비교 — 손·식탁·다른 물체와 함께 있어 크기가 가늠되는 사진",
    "farm": "산지/생산 — 밭·바다·농장·생산자·수확 장면 느낌의 사진",
    "package": "포장/박스 — 배송 박스·포장 상태가 보이는 사진",
    "cook_example": "조리/활용 — 완성 요리·상차림·먹기 직전 모습의 사진",
}


def curate_images(
    files: list,          # [(filename, PIL.Image), ...]
    api_key: Optional[str] = None,
    model: str = "gemini-2.0-flash",
) -> Optional[dict]:
    """Gemini 비전으로 사진을 보고 슬롯 배정을 추천받는다.

    반환 dict:
      {"assign": {slot: filename|None}, "skip": [filename...], "reason": str}
    키 없음/실패 시 None (호출부는 순서 배치로 폴백).
    """
    import json as _json

    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or genai_v2 is None or not files:
        return None

    guide = "\n".join(f"- {k}: {v}" for k, v in SLOT_GUIDE.items())
    names = [n for n, _ in files[:12]]
    prompt = (
        "너는 식품 상세페이지 아트디렉터다. 위 사진들을 보고 아래 자리에 "
        "가장 어울리는 사진을 하나씩 골라라. 목표는 단 하나 — 고객이 먹고 싶어지게.\n\n"
        f"[자리 가이드]\n{guide}\n\n"
        "규칙:\n"
        "- 어울리는 사진이 없는 자리는 null (그 자리는 AI가 새로 그린다)\n"
        "- 화질이 나쁘거나 식욕을 떨어뜨리는 사진(어둡고 흐릿함, 지저분한 배경)은 skip에 넣어라\n"
        "- 같은 사진을 두 자리에 쓰지 마라\n"
        f"- 파일명은 반드시 이 중에서: {names}\n\n"
        '출력(JSON만): {"assign": {"hero": "파일명|null", "close_up": "...", '
        '"size_compare": "...", "farm": "...", "package": "...", "cook_example": "..."}, '
        '"skip": ["파일명"], "reason": "한 줄 설명"}'
    )

    try:
        client = genai_v2.Client(api_key=key)
        contents = []
        for name, img in files[:12]:
            contents.append(f"[파일명: {name}]")
            contents.append(img)
        contents.append(prompt)
        cfg = None
        if genai_types is not None:
            cfg = genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        resp = client.models.generate_content(model=model, contents=contents, config=cfg)
        text = (getattr(resp, "text", "") or "").strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = _json.loads(text)
        assign = data.get("assign") or {}
        # 파일명 검증 + 중복 제거
        valid = set(names)
        seen: set = set()
        cleaned = {}
        for slot in SLOT_GUIDE:
            v = assign.get(slot)
            if isinstance(v, str) and v in valid and v not in seen:
                cleaned[slot] = v
                seen.add(v)
            else:
                cleaned[slot] = None
        return {
            "assign": cleaned,
            "skip": [s for s in (data.get("skip") or []) if s in valid],
            "reason": str(data.get("reason") or ""),
        }
    except Exception:
        return None


def generate_detail_images(
    base_image: Image.Image,
    prompts: dict,
    api_key: Optional[str] = None,
    max_count: int = 6,
) -> list[GeneratedImage]:
    """업로드 이미지를 기반으로 디테일 컷을 생성한다.

    prompts: {"hero": "...", "close_up": "...", "cook_example": "..."}
    """
    labels = list(prompts.items())[:max_count]
    key = api_key or os.getenv("GEMINI_API_KEY")
    out: list[GeneratedImage] = []

    if not key or genai_v2 is None:
        # 폴백: 원본 사진을 모든 슬롯에 사용
        for label, _ in labels:
            out.append(GeneratedImage(label=label, image=base_image, is_generated=False))
        return out

    client = genai_v2.Client(api_key=key)

    for label, prompt in labels:
        img: Optional[Image.Image] = None
        for model in IMAGE_MODELS:
            try:
                contents = [
                    base_image,
                    (
                        "Keep the same product/subject as the reference image. "
                        "Re-render this scene: " + prompt +
                        " . Photo-realistic, mouth-watering Korean food photography, "
                        "natural light, magazine quality. No text overlay."
                    ),
                ]
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ) if genai_types else None,
                )
                data = _extract_image_bytes(resp)
                if data:
                    img = _to_pil(data)
                    break
            except Exception:
                continue

        if img is None:
            out.append(GeneratedImage(label=label, image=base_image, is_generated=False))
        else:
            out.append(GeneratedImage(label=label, image=img, is_generated=True))

    return out
