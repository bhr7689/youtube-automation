"""가사 셀프 평가 — Gemini 가 자기가 만든 가사를 4가지 기준으로 채점.

기준 (각 10점, 합계 40):
1. 운율/형식 — 그 나라 운율 규칙에 맞는가
2. 그 나라스러움 — 모티프·표현이 진짜 그 나라 작사가 느낌인가
3. 정서 전달 — 페르소나·주제가 잘 살아있는가
4. 시그니처 일치 — 사운드 디렉션이 오늘의 시그니처와 맞는가

기본 임계값: 28점 (70%). 그 이하 곡은 호출 측에서 재생성하라.
"""

from __future__ import annotations

import json
import re

DEFAULT_MODEL = "gemini-2.0-flash"

DEFAULT_THRESHOLD = 28  # 40점 만점 중 70%


def build_eval_prompt(
    *,
    variants: list[dict],
    language: str,
    genre: str,
    nation_brief: str = "",
    signature_brief: str = "",
) -> str:
    """변주 N개 → 채점 지시문 (한 번의 호출로 모두 채점)."""
    items_lines = []
    for i, v in enumerate(variants, 1):
        items_lines.append(
            f"--- 곡 {i}: {v.get('title','(제목없음)')} ---\n"
            f"주제: {v.get('theme','')}\n"
            f"{v.get('lyrics_text','')}\n"
        )
    items_block = "\n".join(items_lines)

    return f"""당신은 음악 채널 A&R 디렉터입니다. 아래 {len(variants)}곡의 가사를
**4가지 기준 (각 0-10점, 정수)**으로 엄격하게 채점합니다.

[채점 기준]
1. **rhyme (운율/형식 0-10)**: 그 언어({language})의 가요 운율 규칙·음절 수·압운에 맞는가
2. **nativeness (그 나라스러움 0-10)**: 모티프·표현이 진짜 그 나라 작사가가 쓴 듯한가
3. **emotion (정서 전달 0-10)**: 장르({genre}) 페르소나의 정서·서사가 잘 살아있는가
4. **signature_fit (시그니처 일치 0-10)**: 섹션별 사운드 지문이 시그니처 사운드와 맞는가

[그 나라 작사 DNA 참고]
{nation_brief if nation_brief.strip() else '(없음)'}

[오늘의 시그니처 참고]
{signature_brief if signature_brief.strip() else '(없음)'}

[채점할 가사들]
{items_block}

[채점 규칙]
- 보수적으로. 좋은 가사라도 결점이 있으면 감점.
- 완벽: 10. 좋음: 8. 보통: 6. 부족: 4. 나쁨: 2.
- comment 는 한국어 한 줄로, 가장 큰 문제 또는 강점만.

[반드시 아래 JSON 만 출력 — 마크다운/설명/주석 금지]
{{
  "scores": [
    {{
      "index": 1,
      "rhyme": 0,
      "nativeness": 0,
      "emotion": 0,
      "signature_fit": 0,
      "total": 0,
      "comment": "<한국어 한 줄>"
    }}
    // {len(variants)}개
  ]
}}"""


def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def parse_scores(raw: str, *, n: int) -> list[dict]:
    """LLM 응답 → 점수 리스트(길이 보정).

    각 항목: {"rhyme","nativeness","emotion","signature_fit","total","comment"}
    """
    data = _loads(raw)
    items = data.get("scores") or []
    out: list[dict] = []
    for i in range(n):
        if i < len(items):
            it = items[i]
            r = int(it.get("rhyme", 0))
            nt = int(it.get("nativeness", 0))
            em = int(it.get("emotion", 0))
            sf = int(it.get("signature_fit", 0))
            total = int(it.get("total", r + nt + em + sf))
            comment = str(it.get("comment", "")).strip()
            out.append({
                "rhyme": max(0, min(10, r)),
                "nativeness": max(0, min(10, nt)),
                "emotion": max(0, min(10, em)),
                "signature_fit": max(0, min(10, sf)),
                "total": max(0, min(40, total)),
                "comment": comment,
            })
        else:
            out.append({
                "rhyme": 0, "nativeness": 0, "emotion": 0,
                "signature_fit": 0, "total": 0,
                "comment": "(평가 응답 누락)",
            })
    return out


def gemini_call(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
    )
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def evaluate_variants(
    variants: list[dict],
    *,
    language: str,
    genre: str,
    nation_brief: str = "",
    signature_brief: str = "",
    llm_call=None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> list[dict]:
    """변주 리스트 → 각 변주에 scores 필드 추가한 새 리스트.

    각 항목에 추가되는 키:
    - scores: {"rhyme","nativeness","emotion","signature_fit","total","comment"}
    - score_total: 합계 (편의 alias)
    """
    if not variants:
        return []
    prompt = build_eval_prompt(
        variants=variants,
        language=language, genre=genre,
        nation_brief=nation_brief, signature_brief=signature_brief,
    )
    if llm_call is None:
        if not api_key:
            raise ValueError("api_key 또는 llm_call 중 하나가 필요합니다.")
        raw = gemini_call(prompt, api_key=api_key, model=model)
    else:
        raw = llm_call(prompt)
    scores = parse_scores(raw, n=len(variants))
    return [
        {**v, "scores": s, "score_total": s["total"]}
        for v, s in zip(variants, scores)
    ]


if __name__ == "__main__":
    # 자가 점검 (stub LLM)
    sample = [
        {"title": "엄마의 봄", "theme": "유년의 봄", "lyrics_text": "[Verse 1]\n엄마 손 잡고…"},
        {"title": "고향의 강", "theme": "회상", "lyrics_text": "[Verse 1]\n굽이굽이 흐르는…"},
    ]
    def stub(_p):
        return json.dumps({"scores": [
            {"index": 1, "rhyme": 9, "nativeness": 9, "emotion": 8, "signature_fit": 8, "total": 34, "comment": "운율과 정서가 잘 살아 있음"},
            {"index": 2, "rhyme": 6, "nativeness": 7, "emotion": 5, "signature_fit": 6, "total": 24, "comment": "정서가 약함, 마지막 줄 진부"},
        ]}, ensure_ascii=False)
    scored = evaluate_variants(sample, language="한국어", genre="트로트", llm_call=stub)
    for v in scored:
        print(f"{v['title']} → {v['score_total']}/40  ({v['scores']['comment']})")
