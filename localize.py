"""localize.py — 현지 정서 '번안'(직역 아님) 모듈.

핵심: 그 나라 현지인이 실제로 검색·사용하는 감성 언어, 현지 유튜브 음악 채널이
쓰는 자연스러운 말투로 옮긴다. 직역 금지. 어느 나라든 현지 실사용 언어로.
Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import re
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

REGION_NAME = {
    "KR": "한국어", "JP": "일본어", "US": "영어", "TW": "대만 번체중국어",
    "FR": "프랑스어", "ES": "스페인어", "BR": "브라질 포르투갈어", "VN": "베트남어",
    "ID": "인도네시아어", "TH": "태국어", "HI": "힌디어",
}


def available() -> bool:
    """번안 가능한 LLM 키가 있는지. UI가 '키 없음' 안내에 사용."""
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return False
    s = CM.llm_status()
    return bool(s.get("openai") or s.get("gemini"))


def _coerce(d, n: int) -> dict[int, str]:
    """LLM이 돌려준 다양한 JSON 모양을 {index: 번안문} 으로 통일.

    허용 모양:
      {"t":[{"i":0,"tx":"..."}]}   (원래 스키마)
      {"t":["a","b",...]}          (문자열 리스트)
      {"result":[...]}/{"items":[...]}/{"translations":[...]}  (다른 키)
      {"0":"a","1":"b"}            (인덱스 키 dict)
      ["a","b",...]                (최상위 리스트)
    """
    out: dict[int, str] = {}
    if d is None:
        return out
    # 최상위가 dict면 리스트를 담은 첫 값을 찾는다
    arr = None
    if isinstance(d, list):
        arr = d
    elif isinstance(d, dict):
        for key in ("t", "result", "results", "items", "translations", "data", "list"):
            if isinstance(d.get(key), list):
                arr = d[key]
                break
        if arr is None:
            # 인덱스 키 dict ({"0":"...","1":"..."}) 처리
            for k, v in d.items():
                if str(k).isdigit() and isinstance(v, str):
                    out[int(k)] = v.strip()
            if out:
                return out
            # dict 안에 리스트가 하나라도 있으면 그걸 사용
            arr = next((v for v in d.values() if isinstance(v, list)), None)
    if not isinstance(arr, list):
        return out
    for idx, item in enumerate(arr):
        if isinstance(item, str):
            out[idx] = item.strip()
        elif isinstance(item, dict):
            i = item.get("i", item.get("index", idx))
            tx = item.get("tx") or item.get("text") or item.get("t") or item.get("value") or ""
            try:
                out[int(i)] = str(tx).strip()
            except (ValueError, TypeError):
                out[idx] = str(tx).strip()
    # 인덱스가 범위를 벗어난 잡음 제거
    return {k: v for k, v in out.items() if 0 <= k < n and v}


def _parse(raw: str, n: int) -> dict[int, str]:
    """LLM 원문 → {index: 번안}. 여러 파싱 경로로 방어."""
    if not raw:
        return {}
    d = None
    try:
        d = json.loads(raw)
    except Exception:                   # noqa: BLE001
        try:
            import concept_maker as CM
            d = CM._parse_json(raw)
        except Exception:               # noqa: BLE001
            d = None
    if d is None:                       # 최후: 본문에서 첫 {…} 또는 […] 덩어리 추출
        m = re.search(r"[\{\[].*[\}\]]", raw, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
            except Exception:           # noqa: BLE001
                d = None
    return _coerce(d, n)


def _call_chunk(pairs: list[tuple[int, str]], name: str, context: str) -> dict[int, str]:
    """(원본인덱스, 원문) 묶음 하나를 번안 → {원본인덱스: 번안}. 로컬 0..k 로 번호 매겨 안정 매핑."""
    import concept_maker as CM
    local = [t for _, t in pairs]
    items = "\n".join(f"{i}. {t}" for i, t in enumerate(local))
    prompt = (
        f"너는 {name} 원어민 카피라이터다. 아래 {len(local)}개의 {context}를 **{name}로 번안**하라.\n"
        f"⚠️ 절대 직역·기계번역식으로 옮기지 마라. {name}권 현지인이 실제로 검색하고, "
        f"현지 유튜브 음악 채널이 실제로 쓰는 감성적이고 자연스러운 표현·말투·정서로 다시 써라. "
        f"계절·날씨·시간대·감정의 현지 뉘앙스를 살리고, 이모지·기호는 원문 느낌을 해치지 않는 선에서 유지해도 된다.\n"
        f"⚠️ 반드시 {len(local)}개 **전부**, 각 번호(i)를 그대로 붙여 빠짐없이 번안하라. 하나도 빼먹지 마라.\n\n"
        f"원문:\n{items}\n\n"
        f"반드시 이 JSON만 출력: {{\"t\":[{{\"i\":0,\"tx\":\"번안된 {name} 문구\"}}]}}")
    got = _parse(CM._llm(prompt, json_mode=True), len(local))
    return {pairs[li][0]: tx for li, tx in got.items() if 0 <= li < len(pairs) and tx}


def localize_batch(texts: list[str], target: str = "KR",
                   context: str = "유튜브 음악 플레이리스트 제목",
                   chunk: int = 6) -> dict[int, str]:
    """문구들을 target 나라의 현지 실사용 정서로 번안. 키 없으면 빈 dict.

    큰 목록에서 LLM이 일부 항목을 누락하는 문제를 막기 위해 작은 덩어리로 나눠 호출하고,
    그래도 빠진 인덱스는 한 번 더 재시도한다.
    """
    name = REGION_NAME.get(target, target)
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return {}
    if not (CM.llm_status().get("openai") or CM.llm_status().get("gemini")):
        return {}
    idxed = [(i, t) for i, t in enumerate(texts) if (t or "").strip()]
    if not idxed:
        return {}

    out: dict[int, str] = {}
    for k in range(0, len(idxed), chunk):        # 작은 덩어리로 안정 호출
        out.update(_call_chunk(idxed[k:k + chunk], name, context))

    missing = [p for p in idxed if p[0] not in out]   # 누락 인덱스 1회 재시도(더 잘게)
    if missing:
        for k in range(0, len(missing), 3):
            out.update(_call_chunk(missing[k:k + 3], name, context))
    return out


def localize(text: str, target: str = "KR") -> str:
    return localize_batch([text], target).get(0, text)
