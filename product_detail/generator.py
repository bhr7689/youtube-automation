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

try:
    from openai import OpenAI as _OpenAI
except Exception:  # pragma: no cover
    _OpenAI = None


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

[카피 품질 — 읽는 사람이 "정말 그렇구나" 해야 한다]
- 클리셰 금지: "최고의", "엄선한", "프리미엄", "특별한", "놓치지 마세요",
  "지금 바로", "품격 있는" — 어느 제품에나 붙는 말은 전부 금지.
- 훅(hook_section)은 반드시 다음 셋 중 하나로 만든다:
  ① 경험 공감 — 고객이 이미 겪어본 순간을 짚는다.
     예) "수박, 잘라보기 전엔 모르죠. 그래서 저희는 당도를 재고 보냅니다."
  ② 의외의 사실 — 몰랐던 사실 하나로 고개를 끄덕이게.
     예) "수박은 따는 순간부터 당도가 떨어집니다. 그래서 새벽에 따서 바로 보냅니다."
  ③ 구체적 감각 — 숫자·장면이 보이는 묘사.
     예) "칼끝이 닿자마자 쩍 — 잘 익은 수박은 소리부터 다릅니다."
- 모든 주장 뒤에는 근거 하나를 붙인다(산지·시간·숫자·방법).
  근거를 못 대는 형용사는 쓰지 않는다. "달아요" (X) → "12브릭스, 딴 지 48시간" (O)
- 한 문장 = 한 생각. 읽다가 숨차면 실패작이다.
"""

COPY_USER_TEMPLATE = """제품 정보:
- 카테고리: {category}
- 사용자가 적은 이름/키워드: {raw_name}
- 메모(원산지·중량·특징 등 자유): {note}

다음 JSON 스키마로 작성하라. 각 필드의 톤은 주석을 따른다.
모든 텍스트는 한국어. image_prompts 만 영문 (Gemini 이미지 생성용).

{{
  "product_name": "최종 제품명 (15자 이내, 신선·산지 느낌)",
  "subtitle": "부제 (20자 이내, 1단계 맛있겠다 자극)",
  "hero_headline": "히어로 한 줄 카피 (12자 이내, 임팩트)",
  "hero_sub": "히어로 보조 카피 (25자 이내, 산지/신선/오늘 잡은 식)",
  "hook_section": {{
    "kicker": "후크 윗 한 줄 (10자, 예: 한 번 먹으면)",
    "title": "큰 후크 헤드라인 (18자, 1단계 맛있겠다 폭격)",
    "body": "후크 보조 1~2문장. 침이 고이는 묘사."
  }},
  "appeals": [
    "소구점1 (10자 이내, 예: 새벽 직송)",
    "소구점2",
    "소구점3"
  ],
  "taste_section": {{
    "title": "맛 섹션 제목 (먹고 싶다 단계, 15자 이내)",
    "body": "맛/식감/향 묘사 2~3문장. 입에 넣은 그 순간을 상상하게."
  }},
  "size_section": {{
    "title": "크기·중량 섹션 제목 (15자 이내, 예: 손에 잡히는 크기)",
    "body": "사이즈·실측 묘사 1~2문장.",
    "items": [
      {{"label": "한 개 크기", "value": "예: 손바닥 한 뼘"}},
      {{"label": "1박스", "value": "예: 약 8~12개"}},
      {{"label": "총 중량", "value": "예: 3kg"}}
    ]
  }},
  "fresh_section": {{
    "title": "신선/산지 섹션 제목 (사고 싶다 단계, 15자 이내)",
    "body": "산지·새벽잡이·콜드체인 등 신선도 근거 2~3문장."
  }},
  "farm_section": {{
    "title": "생산자/농장 섹션 제목 (15자 이내, 예: 직접 키운 농부)",
    "body": "생산자 이야기/철학 2~3문장. 신뢰감 형성."
  }},
  "cook_section": {{
    "title": "조리 섹션 제목 (먹고 싶다 재점화, 15자 이내)",
    "tips": [
      "조리법1 한 줄 (예: 굽기 - 중불 4분, 비린내 0)",
      "조리법2",
      "조리법3"
    ]
  }},
  "spec_section": {{
    "title": "제품 정보 섹션 제목 (15자 이내)",
    "items": [
      {{"label": "원산지", "value": ""}},
      {{"label": "중량", "value": ""}},
      {{"label": "포장", "value": ""}},
      {{"label": "보관", "value": ""}}
    ]
  }},
  "package_section": {{
    "title": "포장/배송 섹션 제목 (15자 이내)",
    "body": "박스·아이스팩·신선유지 묘사 1~2문장."
  }},
  "reviews_section": {{
    "title": "후기 섹션 제목 (15자 이내, 예: 먼저 받아본 분들)",
    "items": [
      {{"name": "김○○", "stars": 5, "text": "리뷰 한 줄 (자연스럽게, 과장 X)"}},
      {{"name": "이○○", "stars": 5, "text": "리뷰 한 줄"}},
      {{"name": "박○○", "stars": 5, "text": "리뷰 한 줄"}}
    ]
  }},
  "trust_section": {{
    "title": "안심 섹션 제목 (사야겠다 단계, 15자 이내)",
    "points": [
      "신선도 불만족 시 100% 환불",
      "오전 10시 전 주문 시 당일 출고",
      "원산지·이력 정품 보장"
    ]
  }},
  "cta": "구매 버튼 카피 (10자 이내, 행동 촉구)",
  "image_prompts": {{
    "hero": "히어로 영문 프롬프트 (식욕 자극 메인 컷)",
    "close_up": "클로즈업 영문 프롬프트 (질감·윤기·한 입 베어문 단면)",
    "size_compare": "크기 비교 영문 프롬프트 (손에 든 컷 또는 자/동전 옆 실측)",
    "farm": "농장/산지 영문 프롬프트 (밭/바다/생산자 손)",
    "package": "포장/박스 영문 프롬프트 (배송 박스, 아이스팩, 정성 포장)",
    "cook_example": "조리 완성 영문 프롬프트 (식탁 연출, 김 모락)"
  }}
}}
"""


@dataclass
class CopyResult:
    product_name: str = ""
    subtitle: str = ""
    hero_headline: str = ""
    hero_sub: str = ""
    hook_section: dict = field(default_factory=dict)
    appeals: list = field(default_factory=list)
    taste_section: dict = field(default_factory=dict)
    size_section: dict = field(default_factory=dict)
    fresh_section: dict = field(default_factory=dict)
    farm_section: dict = field(default_factory=dict)
    cook_section: dict = field(default_factory=dict)
    spec_section: dict = field(default_factory=dict)
    package_section: dict = field(default_factory=dict)
    reviews_section: dict = field(default_factory=dict)
    trust_section: dict = field(default_factory=dict)
    cta: str = "지금 구매하기"
    image_prompts: dict = field(default_factory=dict)
    provider: str = "fallback"

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
        hook_section={
            "kicker": "알고 계셨나요",
            "title": "맛은 따는 순간부터 달라집니다",
            "body": "그래서 새벽에 수확해 그날 바로 보냅니다. 밭에서 식탁까지, 시간을 줄인 만큼 맛이 남습니다.",
        },
        appeals=["새벽 산지직송", "당일 진공포장", "신선도 100% 보장"],
        taste_section={
            "title": "한 입에 퍼지는 진짜 맛",
            "body": (
                "입에 넣자마자 부드럽게 퍼지는 풍미. 비린내 없이 깔끔하고, "
                "씹을수록 깊어지는 단맛이 살아 있어요. 가족 모두가 좋아하는 그 맛."
            ),
        },
        size_section={
            "title": "보기 좋은 실한 크기",
            "body": "손에 잡히는 묵직한 사이즈. 한 입에 풍성하게 즐기세요.",
            "items": [
                {"label": "한 개 크기", "value": "손바닥 한 뼘"},
                {"label": "1박스", "value": "약 8~12개"},
                {"label": "총 중량", "value": "약 3kg"},
            ],
        },
        fresh_section={
            "title": "새벽 산지에서 바로",
            "body": (
                "오늘 새벽 산지에서 직접 받아 콜드체인으로 보냅니다. "
                "유통 단계를 줄여, 신선함이 그대로 식탁에 닿습니다."
            ),
        },
        farm_section={
            "title": "직접 키운 농부의 손",
            "body": (
                "30년 외길, 한 농가가 정성으로 키웠습니다. "
                "땅과 햇볕, 시간을 들인 만큼 맛이 정직합니다."
            ),
        },
        cook_section={
            "title": "이렇게 드시면 더 맛있어요",
            "tips": [
                "구이 — 중불 4~5분, 노릇하게",
                "찜 — 양념과 함께 10분, 부드럽게",
                "탕 — 무·파와 함께 시원하게",
            ],
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
        package_section={
            "title": "정성스러운 포장",
            "body": "전용 박스에 아이스팩과 함께. 받으시는 그 순간까지 신선하게.",
        },
        reviews_section={
            "title": "먼저 받아본 분들",
            "items": [
                {"name": "김○○", "stars": 5, "text": "신선해서 비린내 하나 없어요. 재구매!"},
                {"name": "이○○", "stars": 5, "text": "포장이 꼼꼼하고, 양도 푸짐했어요."},
                {"name": "박○○", "stars": 5, "text": "부모님 선물했는데 너무 좋아하셨어요."},
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
                "Hyper-realistic top-down food photography of fresh Korean food, "
                "glossy texture, soft natural light, wooden cutting board, "
                "appetizing, magazine quality, shallow depth of field"
            ),
            "close_up": (
                "Extreme close-up macro shot showing fresh texture and moisture, "
                "natural daylight, vivid colors, mouth-watering detail, "
                "one piece bitten open showing the inside"
            ),
            "size_compare": (
                "A hand holding the product to show its size, natural daylight, "
                "lifestyle shot, clean background, sense of scale"
            ),
            "farm": (
                "Korean farm or sea origin scene, farmer's hands harvesting, "
                "warm golden hour light, documentary feel, trust-building"
            ),
            "package": (
                "A delivery box with the product carefully packaged with ice packs, "
                "clean white studio background, soft shadow, premium feel"
            ),
            "cook_example": (
                "Beautifully plated Korean home-style dish on ceramic plate, "
                "steam rising, warm dinner table setting, cinematic light"
            ),
        },
        provider="fallback",
    )


def _merge_into(base: CopyResult, data: dict, provider: str) -> CopyResult:
    for k, v in (data or {}).items():
        if hasattr(base, k) and v:
            setattr(base, k, v)
    base.provider = provider
    return base


def _gen_gemini(raw_name, category, note, key, model) -> Optional[CopyResult]:
    if not key or genai is None:
        return None
    try:
        genai.configure(api_key=key)
        prompt = COPY_USER_TEMPLATE.format(
            category=category or "식품", raw_name=raw_name or "", note=note or "",
        )
        gm = genai.GenerativeModel(
            model_name=model,
            system_instruction=COPY_SYSTEM,
            generation_config={"response_mime_type": "application/json"},
        )
        resp = gm.generate_content(prompt)
        text = _strip_codefence(getattr(resp, "text", "") or "")
        return _merge_into(_fallback_copy(raw_name, category, note),
                           json.loads(text), provider="gemini")
    except Exception:
        return None


def _gen_openai(raw_name, category, note, key, model) -> Optional[CopyResult]:
    if not key or _OpenAI is None:
        return None
    try:
        client = _OpenAI(api_key=key)
        prompt = COPY_USER_TEMPLATE.format(
            category=category or "식품", raw_name=raw_name or "", note=note or "",
        )
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": COPY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        text = _strip_codefence(resp.choices[0].message.content or "")
        return _merge_into(_fallback_copy(raw_name, category, note),
                           json.loads(text), provider="openai")
    except Exception:
        return None


def generate_copy(
    raw_name: str,
    category: str = "수산물",
    note: str = "",
    api_key: Optional[str] = None,
    model: str = "gemini-2.0-flash",
    provider: str = "gemini",
) -> CopyResult:
    """단일 LLM으로 카피 생성. provider='gemini'|'openai'.

    실패/키 없음 → 안전 폴백.
    """
    if provider == "openai":
        key = api_key or os.getenv("OPENAI_API_KEY")
        out = _gen_openai(raw_name, category, note, key, model or "gpt-4o-mini")
    else:
        key = api_key or os.getenv("GEMINI_API_KEY")
        out = _gen_gemini(raw_name, category, note, key, model or "gemini-2.0-flash")
    return out or _fallback_copy(raw_name, category, note)


def generate_copy_compare(
    raw_name: str,
    category: str = "수산물",
    note: str = "",
    gemini_key: Optional[str] = None,
    openai_key: Optional[str] = None,
    gemini_model: str = "gemini-2.0-flash",
    openai_model: str = "gpt-4o-mini",
) -> dict:
    """두 모델로 동시 생성. 비교 후 사용자 선택용.

    반환: {"gemini": CopyResult|None, "openai": CopyResult|None}
    키가 없거나 실패한 쪽은 None.
    """
    return {
        "gemini": _gen_gemini(
            raw_name, category, note,
            gemini_key or os.getenv("GEMINI_API_KEY"), gemini_model,
        ),
        "openai": _gen_openai(
            raw_name, category, note,
            openai_key or os.getenv("OPENAI_API_KEY"), openai_model,
        ),
    }
