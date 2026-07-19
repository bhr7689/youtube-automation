"""title_digest.py — 모은 제목들의 '표기·정서 패턴' 요약.

일본 등 현지 제목을 여러 개 모아 보고: 앞머리에 뭘 쓰나, 어떤 감정어, 어떻게
표기(괄호·구분자·이모지)하나를 한눈에 익히게 한다. 순수 로직 + 옵션 LLM 요약.
"""
from __future__ import annotations

import re
from collections import Counter

import tier_lab as T

_LEAD_BRACKET = re.compile(r"^\s*[\[\【（(]([^\]\】）)]{1,20})[\]\】）)]")
_BRACKET = re.compile(r"[\[\]\【\】（）()]")
_SEP = re.compile(r"[|｜·・:：/]")
_EMOJI = T._EMOJI_RE


def leading(title: str) -> str:
    """제목 앞머리 키워드(괄호 안 or 앞 2토큰)."""
    m = _LEAD_BRACKET.match(title or "")
    if m:
        return m.group(1).strip()
    toks = T.tokenize(title or "")
    return " ".join(toks[:2]) if toks else ""


def digest(titles: list[str]) -> dict:
    titles = [t for t in titles if t]
    n = len(titles)
    if not n:
        return {"n": 0}
    agg = T.aggregate_titles([{"title": t} for t in titles])
    leads = Counter(leading(t) for t in titles if leading(t))
    return {
        "n": n,
        "avg_length": agg.get("avg_length"),
        "leading": leads.most_common(8),
        "sensory": agg.get("sensory", []),
        "situation": agg.get("situation", []),
        "emojis": agg.get("top_emojis", []),
        "top_tokens": agg.get("top_tokens", []),
        "bracket_pct": round(100 * sum(1 for t in titles if _BRACKET.search(t)) / n),
        "sep_pct": round(100 * sum(1 for t in titles if _SEP.search(t)) / n),
        "emoji_pct": round(100 * sum(1 for t in titles if _EMOJI.search(t)) / n),
    }


def native_summary(titles: list[str], region_name: str = "현지") -> str | None:
    """LLM: 이 나라 제목의 정서·표기 관습을 한국어로 요약. 키 없으면 None."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "jpshorts", "backend"))
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return None
    if not (CM.llm_status().get("openai") or CM.llm_status().get("gemini")):
        return None
    items = "\n".join(f"- {t}" for t in titles[:25] if t)
    prompt = (f"다음은 {region_name} 유튜브 음악 채널 제목들이다. 이 나라 사람들이 "
              f"제목을 쓸 때의 **정서·표기 관습**을 한국어로 4~6줄로 정리해라: "
              f"① 앞머리에 주로 뭘 쓰나(대괄호/상황/브랜드) ② 자주 쓰는 감정·계절어 "
              f"③ 이모지·구분자 표기법 ④ 우리가 벤치마킹할 포인트.\n\n{items}")
    return CM._llm(prompt) or None
