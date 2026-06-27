"""Gemini로 식품 상세페이지 카피를 생성한다.

카피 설계 원칙(=식품의 본질):
  맛있겠다 → 먹고 싶다 → 사고 싶다 → 사야겠다
이 4단 깔때기를 각 섹션에 의도적으로 배치한다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


COPY_SYSTEM = """너는 한국의 식품 상세페이지 카피라이터다.
모든 카피는 다음 심리 흐름을 의도적으로 따라야 한다:

  [1단계 맛있겠다]  시각·감각 자극. 눈으로 침이 고이게.
  [2단계 먹고 싶다] 식감·풍미 묘사. 입에 넣은 그 순간을 상상하게.
  [3단계 사고 싶다] 신선도·산지·희소성·품질 근거. 다른 곳과의 차이.
  [4단계 사야겠다] 가격 정당화 + 안심(보관·배송·보장).

규칙:
- 과장 광고 금지(의학적 효능 단정 X). 식약처/표시광고법 위반 표현 금지.
- 짧고 강한 카피. 한 문장은 짧게, 끊어 읽히게.
- 5070 고객도 이해 가능한 쉬운 단어. 영어/신조어 최소화.
- 출력은 반드시 JSON. 추가 설명/마크다운 없이 JSON만.
"""

COPY_USER_TEMPLATE = """제품 정보:
- 카테고리: {category}
- 사용자가 적은 이름/키워드: {raw_name}
- 메모(원산지·중량·특징 등 자유): {note}

다음 JSON 스키마로 작성하라. 각 필드의 톤은 주석을 따른다.

{{
  "product_name": "최종 제품명 (15자 이내, 신선·산지 느낌)",
  "subtitle": "부제 (20자 이내, 1단계 맛있겠다 자극)",
  "hero_headline": "히어로 한 줄 카피 (12자 이내, 임팩트)",
  "hero_sub": "히어로 보조 카피 (25자 이내, 산지/신선/오늘 잡은 식)",
  "appeals": [
    "소구점1 (10자 이내, 예: 새벽 직송)",
    "소구점2",
    "소구점3"
  ],
  "taste_section": {{
    "title": "맛 섹션 제목 (먹고 싶다 단계, 15자 이내)",
    "body": "맛/식감/향 묘사 2~3문장. 입에 넣은 그 순간을 상상하게."
  }},
  "fresh_section": {{
    "title": "신선/산지 섹션 제목 (사고 싶다 단계, 15자 이내)",
    "body": "산지·새벽잡이·콜드체인 등 신선도 근거 2~3문장."
  }},
  "spec_section": {{
    "title": "제품 정보 섹션 제목 (15자 이내)",
    "items": [
      {{"label": "원산지", "value": "예: 통영 욕지도"}},
      {{"label": "중량", "value": "예: 1kg (2~3마리)"}},
      {{"label": "포장", "value": "예: 진공·아이스팩"}},
      {{"label": "보관", "value": "예: 냉동 -18℃ 6개월"}}
    ]
  }},
  "cook_section": {{
    "title": "조리 섹션 제목 (먹고 싶다 재점화, 15자 이내)",
    "tips": [
      "조리법1 한 줄 (예: 굽기 - 중불 4분, 비린내 0)",
      "조리법2",
      "조리법3"
    ]
  }},
  "trust_section": {{
    "title": "안심 섹션 제목 (사야겠다 단계, 15자 이내)",
    "points": [
      "신선도 불만족 시 100% 환불",
      "오전 10시 전 주문 시 당일 출고",
      "수산물 이력관리 정품"
    ]
  }},
  "cta": "구매 버튼 카피 (10자 이내, 행동 촉구)",
  "image_prompts": {{
    "hero": "히어로 이미지 영문 프롬프트 (식욕 자극 메인 컷)",
    "close_up": "클로즈업 디테일 컷 영문 프롬프트 (질감·윤기)",
    "cook_example": "조리 완성 컷 영문 프롬프트 (식탁 연출)"
  }}
}}
"""


@dataclass
class CopyResult:
    product_name: str = ""
    subtitle: str = ""
    hero_headline: str = ""
    hero_sub: str = ""
    appeals: list = field(default_factory=list)
    taste_section: dict = field(default_factory=dict)
    fresh_section: dict = field(default_factory=dict)
    spec_section: dict = field(default_factory=dict)
    cook_section: dict = field(default_factory=dict)
    trust_section: dict = field(default_factory=dict)
    cta: str = "지금 구매하기"
    image_prompts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _strip_codefence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _fallback_copy(raw_name: str, category: str, note: str) -> CopyResult:
    """Gemini 키가 없거나 실패했을 때 쓰는 안전 폴백 — 식품 톤 유지."""
    name = raw_name.strip() or "오늘의 신선한 제철 식품"
    return CopyResult(
        product_name=name[:15],
        subtitle="산지에서 바로, 신선함 그대로",
        hero_headline="오늘 잡은 신선함",
        hero_sub="새벽 산지직송, 식탁까지 신선하게",
        appeals=["새벽 산지직송", "당일 진공포장", "신선도 100% 보장"],
        taste_section={
            "title": "한 입에 퍼지는 진짜 맛",
            "body": (
                "입에 넣자마자 부드럽게 퍼지는 풍미. 비린내 없이 깔끔하고, "
                "씹을수록 깊어지는 단맛이 살아 있어요. 가족 모두가 좋아하는 그 맛."
            ),
        },
        fresh_section={
            "title": "새벽 산지에서 바로",
            "body": (
                "오늘 새벽 산지에서 직접 받아 콜드체인으로 보냅니다. "
                "유통 단계를 줄여, 신선함이 그대로 식탁에 닿습니다."
            ),
        },
        spec_section={
            "title": "제품 정보",
            "items": [
                {"label": "원산지", "value": note or "국내산"},
                {"label": "중량", "value": "1kg"},
                {"label": "포장", "value": "진공포장 · 아이스팩"},
                {"label": "보관", "value": "냉동 -18℃ 6개월"},
            ],
        },
        cook_section={
            "title": "이렇게 드시면 더 맛있어요",
            "tips": [
                "구이 — 중불 4~5분, 노릇하게",
                "찜 — 양념과 함께 10분, 부드럽게",
                "탕 — 무·파와 함께 시원하게",
            ],
        },
        trust_section={
            "title": "안심하고 받으세요",
            "points": [
                "신선도 불만족 시 100% 환불",
                "오전 10시 전 주문 시 당일 출고",
                "원산지·이력 정품 보장",
            ],
        },
        cta="지금 신선하게 받기",
        image_prompts={
            "hero": (
                "Hyper-realistic top-down food photography of fresh Korean seafood, "
                "glossy texture, soft natural light, wooden cutting board, "
                "appetizing, magazine quality, shallow depth of field"
            ),
            "close_up": (
                "Extreme close-up macro shot showing fresh texture and moisture, "
                "natural daylight, vivid colors, mouth-watering detail"
            ),
            "cook_example": (
                "Beautifully plated Korean home-style dish on ceramic plate, "
                "steam rising, warm dinner table setting, cinematic light"
            ),
        },
    )


def generate_copy(
    raw_name: str,
    category: str = "수산물",
    note: str = "",
    api_key: Optional[str] = None,
    model: str = "gemini-2.0-flash",
) -> CopyResult:
    """Gemini로 식품 상세페이지 카피를 한 번에 생성한다."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or genai is None:
        return _fallback_copy(raw_name, category, note)

    try:
        genai.configure(api_key=key)
        prompt = COPY_USER_TEMPLATE.format(
            category=category or "식품",
            raw_name=raw_name or "",
            note=note or "",
        )
        gm = genai.GenerativeModel(
            model_name=model,
            system_instruction=COPY_SYSTEM,
            generation_config={"response_mime_type": "application/json"},
        )
        resp = gm.generate_content(prompt)
        text = _strip_codefence(getattr(resp, "text", "") or "")
        data = json.loads(text)
        result = _fallback_copy(raw_name, category, note)
        for k, v in data.items():
            if hasattr(result, k) and v:
                setattr(result, k, v)
        return result
    except Exception:
        return _fallback_copy(raw_name, category, note)
