"""테무 한국 셀러용 카피 자동 생성 (Gemini / GPT).

가이드 1단계의 권장 형식대로:
- 제목 5단 구조 (브랜드+세부정보+적용범위+제품유형+주요특징/기능/장점)
- 상세 설명
- 세부 정보 키-값 (재질/스타일/관리법 등 카테고리에 맞게)
- 옵션 변형 후보 (색상/사이즈)
모든 출력은 한국어. 키 없거나 호출 실패 시 안전 폴백.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from .schema import (
    TemuListing,
    TitleParts,
    AttributeRow,
    SkuRow,
)

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None

try:
    from openai import OpenAI as _OpenAI
except Exception:  # pragma: no cover
    _OpenAI = None


SYSTEM_PROMPT_BASE = """너는 테무(Temu) 한국 셀러센터에 상품을 등록하는 카피라이터다.
모든 출력은 한국어. 과장 광고·의학적 효능 단정 금지.
표시광고법·전자상거래법을 위반하는 표현은 쓰지 않는다.
구매자가 검색 키워드로 잘 찾을 수 있도록, 제품군의 핵심 키워드를 자연스럽게 녹인다.

제목 형식은 반드시 5단 구조를 따른다:
  [브랜드] + [세부정보] + [적용범위] + [제품유형] + [주요 특징/기능/장점]
예) 'ABC + 듀얼 존 와인 쿨러 및 음료 냉장고 + 독립형 또는 카운터탑 냉장고, 유리문 및 LED 조명
     + 78캔 및 20병 용량, 24인치 + 스테인리스 스틸'
제목 전체는 500자 이내.

출력은 오직 JSON. 마크다운/설명 금지.
"""

# 식품·음료 카테고리에 추가되는 톤 가이드 — 의식의 흐름(맛있겠다 → 먹고 싶다 → 사야겠다)
SYSTEM_PROMPT_FOOD_ADDON = """

[식품·음료 추가 규칙]
식품의 본질은 "맛있다 + 맛있어 보인다"이다. 카피는 다음 의식의 흐름을 자극해야 한다:

  ① 맛있겠다  — 눈으로 침이 고이게 (감각 묘사: 빨갛게 잘 익은, 한 입 베어물면 과즙이…)
  ② 먹고 싶다 — 식감/풍미가 입에 그려지게 (아삭함, 단맛, 시원함, 향)
  ③ 사고 싶다 — 산지·신선도·당도·품질 근거 (산지, 수확 시점, 당도 Brix, 보관)
  ④ 사야겠다 — 가격 정당화 + 안심 (가족·여름·계절·선물 맥락 + 신선 보장·환불)

이 흐름을 다음 필드에 반드시 녹여라:
  - title_parts.features  → ①+③ 키워드(예: '한 입 가득 시원한 단맛, 산지직송')
  - description           → 시작 한 줄은 ① 감각 묘사로 식욕을 자극.
                            이어서 ②③④ 순서로 자연스럽게 흐르도록.
                            • 불릿 3~5개 권장.
  - attributes            → '당도(Brix)', '원산지', '수확 시점', '보관 방법',
                            '먹는 방법(차게/슬라이스)' 같은 식품 특화 속성 우선.
"""


def _system_prompt(category: str) -> str:
    cat = (category or "").lower()
    if "식품" in cat or "음료" in cat or "food" in cat:
        return SYSTEM_PROMPT_BASE + SYSTEM_PROMPT_FOOD_ADDON
    return SYSTEM_PROMPT_BASE

USER_TEMPLATE = """제품 정보:
- 카테고리: {category}
- 사용자가 적은 이름/키워드: {raw_name}
- 브랜드: {brand}
- 메모(특징/스펙/소재 자유롭게): {note}

아래 스키마로 한국어 JSON 만들어:

{{
  "title_parts": {{
    "brand": "브랜드명 (없으면 '')",
    "details": "세부정보 (제품의 본질/카테고리, 30~80자)",
    "applicable": "적용범위/사용 환경 (20~60자)",
    "product_type": "제품 유형·사양·사이즈 등 (20~60자)",
    "features": "주요 특징/기능/장점 (20~60자, 키워드 풍부)"
  }},
  "description": "상세 설명 200~500자. 1) 핵심 가치 2) 주요 특징 3~5개 (•로 시작) 3) 사용 안내.",
  "attributes": [
    {{"label": "재질", "value": "예: 스테인리스 스틸"}},
    {{"label": "스타일", "value": "예: 모던"}},
    {{"label": "관리법", "value": "예: 손세척, 부드러운 천"}},
    {{"label": "원산지", "value": "예: 대한민국"}},
    {{"label": "포함 구성품", "value": "예: 본체 1, 사용설명서 1"}}
  ],
  "option_axis_1": "1차 옵션 축 이름 (예: 색상, 용량, 향)",
  "option_axis_2": "2차 옵션 축 이름 (없으면 '')",
  "option_values_1": ["옵션1 값", "옵션1 값2"],
  "option_values_2": ["옵션2 값", "옵션2 값2"]
}}
"""


def _strip_codefence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _fallback_food(raw_name: str, brand: str) -> TemuListing:
    """식품·음료용 폴백 — 4단 깔때기(맛있겠다→먹고싶다→사고싶다→사야겠다) 반영."""
    name = raw_name.strip() or "신선한 제철 식품"
    parts = TitleParts(
        brand=brand.strip(),
        details=f"{name} 산지직송 신선 식품",
        applicable="가정용·선물용·여름 제철",
        product_type="제철 한정 수량",
        features="한 입 가득 시원한 단맛 · 산지 직송 · 신선도 보장",
    )
    return TemuListing(
        category="식품·음료",
        title_parts=parts,
        brand_name=brand.strip(),
        description=(
            f"{name} — 한 조각 베어무는 순간, 입안 가득 시원한 과즙이 퍼집니다.\n\n"
            "• 빨갛게 잘 익은 속살, 보기만 해도 침이 고이는 색감\n"
            "• 아삭하게 씹히는 식감 + 진한 단맛, 가족 모두 좋아하는 그 맛\n"
            "• 산지에서 새벽 수확 → 콜드체인으로 신선하게 배송\n"
            "• 차게 보관 후 큼직하게 슬라이스하면 한여름의 별미\n"
            "• 신선도 불만족 시 100% 환불 — 안심하고 주문하세요"
        ),
        itc_code="Gen Standard",
        attributes=[
            AttributeRow("원산지", "국내산 (상세 페이지 참조)"),
            AttributeRow("수확 시점", "주문 후 산지 수확"),
            AttributeRow("당도(Brix)", "11~13"),
            AttributeRow("중량", "1통 약 7~9kg"),
            AttributeRow("보관 방법", "냉장 보관 (개봉 후 2~3일 내 섭취)"),
            AttributeRow("먹는 방법", "차게 보관 후 슬라이스"),
        ],
        option_axis_1="중량",
        option_axis_2="",
        skus=[
            SkuRow(color="7~8kg", size="", qty=30, price_krw=0,
                   weight_g=7500, length_cm=30, width_cm=30, height_cm=30),
            SkuRow(color="8~9kg", size="", qty=20, price_krw=0,
                   weight_g=8500, length_cm=32, width_cm=32, height_cm=32),
        ],
    )


def _fallback_generic(raw_name: str, category: str, brand: str) -> TemuListing:
    raw_name = (raw_name or "").strip() or "신상품"
    parts = TitleParts(
        brand=brand.strip(),
        details=raw_name,
        applicable=f"{category} 사용자에게 적합" if category else "일상 사용에 적합",
        product_type="다용도",
        features="고급 마감 · 사용 편리 · 가성비 우수",
    )
    return TemuListing(
        category=category or "",
        title_parts=parts,
        brand_name=brand.strip(),
        description=(
            f"{raw_name}\n\n"
            "• 핵심 가치: 일상에서 바로 쓸 수 있는 실용적인 디자인\n"
            "• 주요 특징: 깔끔한 마감, 사용 편리, 안정적인 품질\n"
            "• 사용 안내: 사용 전 포장을 확인하시고 상세 사양을 참고하세요."
        ),
        itc_code="Gen Standard",
        attributes=[
            AttributeRow("재질", "상세 페이지 참조"),
            AttributeRow("스타일", "모던"),
            AttributeRow("관리법", "부드러운 천으로 닦기"),
            AttributeRow("원산지", "상세 페이지 참조"),
            AttributeRow("포함 구성품", "본체 1, 사용설명서 1"),
        ],
        option_axis_1="색상",
        option_axis_2="사이즈",
        skus=[
            SkuRow(color="기본", size="단일", qty=50, price_krw=0, weight_g=300,
                   length_cm=20, width_cm=15, height_cm=10),
        ],
    )


def _fallback(raw_name: str, category: str, brand: str, note: str) -> TemuListing:
    cat = (category or "").lower()
    if "식품" in cat or "음료" in cat or "food" in cat:
        return _fallback_food(raw_name, brand)
    return _fallback_generic(raw_name, category, brand)


def _gen_gemini(raw_name, category, brand, note, key, model) -> Optional[dict]:
    if not key or genai is None:
        return None
    try:
        genai.configure(api_key=key)
        prompt = USER_TEMPLATE.format(
            category=category or "", raw_name=raw_name or "",
            brand=brand or "", note=note or "",
        )
        gm = genai.GenerativeModel(
            model_name=model,
            system_instruction=_system_prompt(category),
            generation_config={"response_mime_type": "application/json"},
        )
        resp = gm.generate_content(prompt)
        return json.loads(_strip_codefence(getattr(resp, "text", "")))
    except Exception:
        return None


def _gen_openai(raw_name, category, brand, note, key, model) -> Optional[dict]:
    if not key or _OpenAI is None:
        return None
    try:
        client = _OpenAI(api_key=key)
        prompt = USER_TEMPLATE.format(
            category=category or "", raw_name=raw_name or "",
            brand=brand or "", note=note or "",
        )
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _system_prompt(category)},
                {"role": "user", "content": prompt},
            ],
        )
        return json.loads(_strip_codefence(resp.choices[0].message.content or ""))
    except Exception:
        return None


def _apply(listing: TemuListing, data: dict) -> TemuListing:
    """LLM 응답 dict 를 listing 에 머지. 누락 필드는 폴백 값 유지."""
    if not data:
        return listing
    tp = data.get("title_parts") or {}
    if tp:
        for k in ("brand", "details", "applicable", "product_type", "features"):
            if tp.get(k):
                setattr(listing.title_parts, k, tp[k])
    if data.get("description"):
        listing.description = data["description"]
    attrs = data.get("attributes") or []
    if attrs:
        listing.attributes = [
            AttributeRow(label=a.get("label", ""), value=a.get("value", ""))
            for a in attrs if a.get("label")
        ]
    if data.get("option_axis_1"):
        listing.option_axis_1 = data["option_axis_1"]
    if "option_axis_2" in data:
        listing.option_axis_2 = data.get("option_axis_2") or ""

    # 옵션 값들로 SKU 매트릭스 생성 (기본 가격/수량은 0)
    v1 = data.get("option_values_1") or []
    v2 = data.get("option_values_2") or []
    if v1:
        new_skus: list[SkuRow] = []
        if v2:
            for c in v1:
                for s in v2:
                    new_skus.append(SkuRow(color=str(c), size=str(s), qty=10))
        else:
            for c in v1:
                new_skus.append(SkuRow(color=str(c), size="", qty=10))
        if new_skus:
            listing.skus = new_skus
    return listing


def generate_listing(
    raw_name: str,
    category: str = "",
    brand: str = "",
    note: str = "",
    *,
    provider: str = "gemini",
    gemini_key: Optional[str] = None,
    openai_key: Optional[str] = None,
    gemini_model: str = "gemini-2.0-flash",
    openai_model: str = "gpt-4o-mini",
) -> TemuListing:
    """provider: 'gemini' | 'openai'. 키 없으면 안전 폴백."""
    listing = _fallback(raw_name, category, brand, note)
    if provider == "openai":
        data = _gen_openai(
            raw_name, category, brand, note,
            openai_key or os.getenv("OPENAI_API_KEY"), openai_model,
        )
    else:
        data = _gen_gemini(
            raw_name, category, brand, note,
            gemini_key or os.getenv("GEMINI_API_KEY"), gemini_model,
        )
    return _apply(listing, data or {})


def generate_listing_compare(
    raw_name: str,
    category: str = "",
    brand: str = "",
    note: str = "",
    *,
    gemini_key: Optional[str] = None,
    openai_key: Optional[str] = None,
) -> dict:
    """양쪽 모두 호출 후 비교용 dict 반환."""
    return {
        "gemini": generate_listing(
            raw_name, category, brand, note,
            provider="gemini", gemini_key=gemini_key, openai_key=openai_key,
        ),
        "openai": generate_listing(
            raw_name, category, brand, note,
            provider="openai", gemini_key=gemini_key, openai_key=openai_key,
        ),
    }
