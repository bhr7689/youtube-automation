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
