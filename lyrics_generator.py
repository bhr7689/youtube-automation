"""작사가 페르소나 + 곡 길이/구조 → Gemini → N개 가사 변주.

- analyzer.py: 메타→Suno picks
- lyrics_analyzer.py: 가사→작사 패턴 (역추출)
- lyrics_generator.py: 작사 패턴/페르소나 → 새 가사 (정생성)

옵션:
- duration_sec: 곡 길이 목표 → 절·후렴 구조 자동 매핑
- n: 같은 페르소나로 몇 개의 다른 가사를 받을지
- theme: 주제 힌트(선택). 비워두면 페르소나가 알아서 결정

LLM 주입(llm_call) 가능 — 헤드리스 테스트용.
"""

from __future__ import annotations

import json
import re

DEFAULT_MODEL = "gemini-2.0-flash"


# 한국 가요 평균 기준: 1절 ≈ 30~40초, 후렴 ≈ 25초, 브릿지 ≈ 25초
DURATION_PRESETS: dict[int, dict] = {
    150: {"verses": 2, "chorus_reps": 2, "bridge": 0, "approx_lines": 14, "label": "2분 30초 (짧은 곡)"},
    180: {"verses": 3, "chorus_reps": 2, "bridge": 0, "approx_lines": 18, "label": "3분 (표준)"},
    210: {"verses": 3, "chorus_reps": 3, "bridge": 0, "approx_lines": 22, "label": "3분 30초"},
    240: {"verses": 4, "chorus_reps": 3, "bridge": 1, "approx_lines": 26, "label": "4분 (긴 트로트)"},
    270: {"verses": 4, "chorus_reps": 3, "bridge": 1, "approx_lines": 30, "label": "4분 30초"},
    300: {"verses": 5, "chorus_reps": 3, "bridge": 1, "approx_lines": 34, "label": "5분 (대곡)"},
    360: {"verses": 6, "chorus_reps": 4, "bridge": 1, "approx_lines": 42, "label": "6분 (서사 대곡)"},
}


def pick_structure(duration_sec: int) -> dict:
    """가장 가까운 길이 프리셋을 선택. 없으면 가장 근접한 것."""
    if duration_sec in DURATION_PRESETS:
        return DURATION_PRESETS[duration_sec]
    closest = min(DURATION_PRESETS.keys(), key=lambda k: abs(k - int(duration_sec)))
    return DURATION_PRESETS[closest]


def build_prompt(
    *,
    persona: str,
    structure: dict,
    duration_sec: int,
    n: int = 3,
    theme: str = "",
    genre: str = "",
    language: str = "한국어",
) -> str:
    """Gemini 에 줄 가사 생성 지시문.

    language: 출력 가사의 언어. "한국어"가 기본. 다른 언어(예: "프랑스어",
    "멕시코식 스페인어", "힌디어", "대만식 중국어(번체)" 등)를 주면 페르소나의
    정서·구조는 유지하되 그 언어의 자연스러운 가요 운율로 작사합니다.
    """
    persona_block = (persona or "").strip()
    if not persona_block:
        persona_block = "당신은 한국 5070 세대를 위한 트로트·발라드 작사가입니다."

    theme_block = f"- 주제 힌트(반드시 이 안에서): {theme.strip()}" if theme.strip() else "- 주제: 페르소나에 어울리는 것으로 자유롭게."
    genre_block = f"- 장르 라벨: {genre.strip()}" if genre.strip() else ""

    structure_desc = (
        f"벌스 {structure['verses']}개, 후렴 {structure['chorus_reps']}회 반복"
        + (f", 브릿지 1개" if structure.get('bridge') else "")
    )

    lang = (language or "한국어").strip()
    if lang == "한국어":
        language_rules = (
            "- **한국어로 작성**. 자연스러운 한국 가요 어순.\n"
            "- 페르소나의 어미·운율 습관을 일관되게 사용."
        )
    else:
        language_rules = (
            f"- **{lang}로 작성**. 그 언어 원어민이 자연스럽게 부를 수 있는 가요 운율·어순으로.\n"
            f"- 페르소나의 정서·이미지·서사 구조는 유지하되, 한국어 어미를 그대로 옮기지 말고\n"
            f"  {lang} 가요·시 전통의 자연스러운 표현으로 옮길 것.\n"
            f"- 음절 수가 {lang} 노래 가창에 맞게 적절해야 함(너무 긴 줄 피하기).\n"
            f"- 결과는 반드시 {lang}로만, 한국어 단어를 섞지 말 것\n"
            f"  (제목 title 과 주제 theme 도 {lang}로 작성)."
        )

    return f"""{persona_block}

이 페르소나의 화법으로 새 가사를 작사합니다. 같은 화자·정서·운율을 유지하되,
{n}개의 서로 다른 가사를 만드세요. 각각은 주제·풍경·결말이 달라야 합니다.

[곡 길이 / 구조 목표]
- 약 {duration_sec}초 분량 ({structure.get('label','')})
- 구조: {structure_desc}
- 총 가사 줄 수 약 {structure.get('approx_lines', 18)}줄

[주제 / 장르]
{theme_block}
{genre_block}

[작사 규칙]
{language_rules}
- 후렴은 같은 글이 그대로 반복되어야 함(가사 안에서 후렴이 반복될 때 동일 텍스트).
- 같은 줄이 의미 없이 반복되는 자동 자막 스타일 금지.
- 결과 가사들은 같은 페르소나지만 충분히 다른 이야기로.

[반드시 아래 JSON 만 출력 — 마크다운/설명/주석 금지]
{{
  "variants": [
    {{
      "title": "<곡 제목>",
      "theme": "<이 가사의 주제 한 줄>",
      "sections": [
        {{"section": "verse 1", "lines": ["...", "..."]}},
        {{"section": "chorus", "lines": ["...", "..."]}},
        ... (구조 목표대로)
      ],
      "lyrics_text": "<위 sections 를 줄바꿈으로 이어붙인 전체 가사>"
    }}
    // {n}개
  ]
}}"""


def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _section_to_text(sec: dict) -> str:
    label = sec.get("section", "")
    lines = [str(line).strip() for line in (sec.get("lines") or []) if str(line).strip()]
    body = "\n".join(lines)
    return f"[{label}]\n{body}" if label else body


def _reconstruct_text(sections: list[dict]) -> str:
    return "\n\n".join(_section_to_text(s) for s in sections if s)


def parse(raw: str, *, expected: int = 0) -> list[dict]:
    """JSON → 변주 리스트. lyrics_text 가 비어 있으면 sections 로 재구성."""
    data = _loads(raw)
    variants = data.get("variants") or []
    out: list[dict] = []
    for v in variants:
        sections = v.get("sections") or []
        text = (v.get("lyrics_text") or "").strip()
        if not text and sections:
            text = _reconstruct_text(sections)
        if not text:
            continue
        out.append({
            "title": (v.get("title") or "").strip() or "(제목없음)",
            "theme": (v.get("theme") or "").strip(),
            "sections": sections,
            "lyrics_text": text,
        })
    if expected and out and len(out) < expected:
        # 부족하면 부족한 대로 반환 — 호출 측에서 추가 호출 결정
        pass
    return out


def gemini_call(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        generation_config={"temperature": 0.85, "response_mime_type": "application/json"},
    )
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def generate_lyrics(
    *,
    persona: str,
    duration_sec: int = 240,
    n: int = 3,
    theme: str = "",
    genre: str = "",
    language: str = "한국어",
    llm_call=None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> list[dict]:
    """페르소나 + 길이/주제 → N개 가사 변주.

    Gemini 가 큰 N 에서 품질이 떨어지므로, 호출 측에서 5개씩 끊어 여러 번
    호출하고 결과를 합치는 것을 권장(이 함수는 단일 호출).
    """
    if not (persona or "").strip():
        raise ValueError("persona(작사가 페르소나)가 필요합니다.")
    structure = pick_structure(duration_sec)
    prompt = build_prompt(
        persona=persona, structure=structure, duration_sec=duration_sec,
        n=n, theme=theme, genre=genre, language=language,
    )
    if llm_call is None:
        if not api_key:
            raise ValueError("api_key 또는 llm_call 중 하나가 필요합니다.")
        raw = gemini_call(prompt, api_key=api_key, model=model)
    else:
        raw = llm_call(prompt)
    return parse(raw, expected=n)


if __name__ == "__main__":
    persona = (
        "당신은 한국 5070 세대를 위한 트로트 작사가입니다. "
        "회상·그리움을 1인칭으로 잔잔하게 그리고, 어머니·고향·계절 이미지를 즐겨 씁니다."
    )

    def stub(_p: str) -> str:
        return json.dumps({"variants": [
            {
                "title": "엄마의 봄",
                "theme": "유년의 봄날 기억",
                "sections": [
                    {"section": "verse 1", "lines": ["엄마 손 잡고 걷던", "그 봄날의 마당"]},
                    {"section": "chorus", "lines": ["봄이 오면 생각나요", "엄마의 그 손길이"]},
                    {"section": "verse 2", "lines": ["바람에 흔들리던", "꽃잎 같은 미소"]},
                    {"section": "chorus", "lines": ["봄이 오면 생각나요", "엄마의 그 손길이"]},
                ],
                "lyrics_text": "",
            },
            {
                "title": "고향의 강",
                "theme": "고향 강가에서의 회상",
                "sections": [
                    {"section": "verse 1", "lines": ["굽이굽이 흐르는", "고향의 그 강물"]},
                    {"section": "chorus", "lines": ["흘러간 세월처럼", "강물도 흐르네"]},
                ],
                "lyrics_text": "",
            },
        ]}, ensure_ascii=False)

    out = generate_lyrics(persona=persona, duration_sec=240, n=2, llm_call=stub)
    print(f"{len(out)}개 생성")
    for i, v in enumerate(out, 1):
        print(f"\n=== {i}. {v['title']} ({v['theme']}) ===")
        print(v["lyrics_text"])
