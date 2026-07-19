"""ctr_scorer.py — 생성한 썸네일·제목 후보의 CTR(클릭률) 예측 채점 + 베스트 선별.

조회수 폭발의 레버 = CTR. 생성된 후보들을 발행 전에 채점해 '터질' 것을 고른다.
5기준(각 0-20, 합 100):
  호기심(curiosity) · 감정(emotion) · 명확성(clarity) · 패턴적합(pattern_fit) · 일치성(consistency)
GPT/Gemini 로 배치 채점, 키 없으면 휴리스틱 폴백. Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import tier_lab as T

CRITERIA = ["curiosity", "emotion", "clarity", "pattern_fit", "consistency"]
LABELS = {"curiosity": "호기심", "emotion": "감정", "clarity": "명확성",
          "pattern_fit": "패턴적합", "consistency": "일치성"}


def _pattern_brief(pattern: dict) -> str:
    if not pattern:
        return "(패턴 미저장)"
    tp = pattern.get("title_pattern", {})
    thp = pattern.get("thumbnail_pattern", {})
    bits = []
    if tp:
        bits.append("제목: " + " / ".join(filter(None, [
            tp.get("situation", ""), "·".join(tp.get("sensory", [])[:3]), tp.get("tone", "")])))
    if thp:
        bits.append("썸네일: " + " / ".join(filter(None, [
            thp.get("composition", ""), thp.get("mood", "")])))
    return " | ".join(bits) or "(패턴 요약 없음)"


def _llm_score(sets: list[dict], genre: str, pattern: dict) -> list[dict] | None:
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return None
    if not (CM.llm_status().get("openai") or CM.llm_status().get("gemini")):
        return None
    items = "\n".join(
        f"{i}. 제목:{s.get('title','')} | 썸네일문구:{s.get('thumb_text','')}"
        for i, s in enumerate(sets))
    prompt = f"""너는 유튜브 CTR 전문가다. '{genre}' 장르의 아래 썸네일·제목 후보들이
실제로 클릭을 얼마나 유발할지 냉정하게 채점하라.
이 장르 승리 패턴: {_pattern_brief(pattern)}

각 후보를 5기준(각 0-20)으로:
- curiosity: 호기심 유발(더 보고 싶게 하는 궁금증)
- emotion: 감정 자극(정서 훅)
- clarity: 명확성(0.5초에 이해되는가)
- pattern_fit: 이 장르 승리 패턴과의 적합도
- consistency: 썸네일 문구↔제목 일치·상보

후보:
{items}

JSON만: {{"scores":[{{"i":0,"curiosity":0,"emotion":0,"clarity":0,"pattern_fit":0,"consistency":0,"reason":"한 줄 근거"}}]}}"""
    raw = CM._llm(prompt, json_mode=True)
    if not raw:
        return None
    try:
        data = json.loads(raw) if raw.strip().startswith("{") else (CM._parse_json(raw) or {})
        out = data.get("scores", [])
        return out or None
    except Exception:                   # noqa: BLE001
        return None


def _heuristic_score(s: dict) -> dict:
    """키 없을 때: tier_lab 로직으로 근사 채점."""
    a = T.analyze_title(s.get("title", ""))
    cons = T.consistency_heuristic(s.get("title", ""), s.get("thumb_text", ""))
    curiosity = 12 + (4 if a["question"] else 0) + (4 if a["situation"] else 0)
    emotion = 8 + min(12, 4 * len(a["sensory"]))
    length = a["length"]
    clarity = 20 if 12 <= length <= 30 else (14 if length <= 40 else 8)
    pattern_fit = 10 + (5 if a["situation"] else 0) + (5 if a["genre"] else 0)
    consistency = round(cons["total"] / 5)
    d = {"curiosity": min(20, curiosity), "emotion": min(20, emotion),
         "clarity": clarity, "pattern_fit": min(20, pattern_fit),
         "consistency": min(20, consistency), "reason": "휴리스틱 근사(GPT 키로 정밀화)"}
    d["total"] = sum(d[c] for c in CRITERIA)
    return d


def score_sets(sets: list[dict], genre: str = "", pattern: dict | None = None) -> list[dict]:
    """각 세트에 'score' 부여 후 total 내림차순 정렬. 1위에 winner=True."""
    if not sets:
        return sets
    llm = _llm_score(sets, genre, pattern or {})
    for i, s in enumerate(sets):
        sc = None
        if llm:
            match = next((x for x in llm if x.get("i") == i), None)
            if match:
                sc = {c: int(match.get(c, 0) or 0) for c in CRITERIA}
                sc["reason"] = match.get("reason", "")
                sc["total"] = sum(sc[c] for c in CRITERIA)
        if sc is None:
            sc = _heuristic_score(s)
        s["score"] = sc
    ranked = sorted(sets, key=lambda x: x.get("score", {}).get("total", 0), reverse=True)
    for k, s in enumerate(ranked):
        s["winner"] = (k == 0)
    return ranked
