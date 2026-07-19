"""localize.py — 현지 정서 '번안'(직역 아님) 모듈.

핵심: 그 나라 현지인이 실제로 검색·사용하는 감성 언어, 현지 유튜브 음악 채널이
쓰는 자연스러운 말투로 옮긴다. 직역 금지. 어느 나라든 현지 실사용 언어로.
Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

REGION_NAME = {
    "KR": "한국어", "JP": "일본어", "US": "영어", "TW": "대만 번체중국어",
    "FR": "프랑스어", "ES": "스페인어", "BR": "브라질 포르투갈어", "VN": "베트남어",
    "ID": "인도네시아어", "TH": "태국어", "HI": "힌디어",
}


def localize_batch(texts: list[str], target: str = "KR",
                   context: str = "유튜브 음악 플레이리스트 제목") -> dict[int, str]:
    """문구들을 target 나라의 현지 실사용 정서로 번안. 키 없으면 빈 dict."""
    name = REGION_NAME.get(target, target)
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return {}
    if not (CM.llm_status().get("openai") or CM.llm_status().get("gemini")):
        return {}
    items = "\n".join(f"{i}. {t}" for i, t in enumerate(texts) if t)
    if not items.strip():
        return {}
    prompt = (
        f"다음 {context}들을 **{name}로 번안**하라. 절대 직역하지 마라.\n"
        f"{name}권 현지인이 실제로 검색하고, 현지 유튜브 음악 채널이 실제로 쓰는 "
        f"감성적이고 자연스러운 표현·말투·정서로 옮겨라. 계절·날씨·시간대의 정서 뉘앙스를 살려라.\n\n"
        f"{items}\n\nJSON만: {{\"t\":[{{\"i\":0,\"tx\":\"번안 결과\"}}]}}")
    raw = CM._llm(prompt, json_mode=True)
    if not raw:
        return {}
    try:
        d = json.loads(raw) if raw.strip().startswith("{") else (CM._parse_json(raw) or {})
        return {int(x["i"]): x.get("tx", "") for x in d.get("t", []) if "i" in x}
    except Exception:                   # noqa: BLE001
        return {}


def localize(text: str, target: str = "KR") -> str:
    return localize_batch([text], target).get(0, text)
