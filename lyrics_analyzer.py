"""가사 본문 → 작사 스타일 분석 (Gemini).

`analyzer.py` 가 메타데이터→Suno picks 라면, 이 모듈은 **가사 본문→작사 패턴**이다.
결과는 차원별 picks 형식의 dict 와, AI 작사가에게 그대로 줄 수 있는 writer_prompt
문자열을 함께 반환한다. 장르별로 누적해두면 "이 장르의 작사 화법"이 데이터화된다.

LLM 은 주입 가능(llm_call) — 헤드리스 테스트 시 스텁을 넣는다.
"""

from __future__ import annotations

import json
import re

DEFAULT_MODEL = "gemini-2.0-flash"

# 분석할 작사 차원 (모두 자유 어휘 — vocab.json 제약 없음)
DIMS = [
    "tone",          # 정서/톤 (애절, 흥, 회한, 위로 등)
    "perspective",   # 시점 (1인칭 화자, 어머니에게, 떠난 이에게 등)
    "themes",        # 주제 (어머니, 고향, 이별, 회한, 새 출발 등)
    "imagery",       # 이미지/비유 (계절, 풍경, 사물, 색감)
    "rhyme",         # 운율/어미 패턴 (~다, ~네, ~지요, 반복 후렴)
    "structure",     # 구조 패턴 (벌스-후렴-브릿지, AABA, 후렴 반복 횟수)
    "vocabulary",    # 자주 쓰는 어휘/관용구
]


def build_prompt(lyrics: str, *, title: str = "", genre: str = "") -> str:
    """Gemini 에게 줄 분석 지시문. 가사 본문은 끝부분에서 잘라 컨텍스트 보호."""
    lyrics_block = (lyrics or "")[:4000].strip()
    head = []
    if title:
        head.append(f"- 곡 제목: {title}")
    if genre:
        head.append(f"- 장르(사용자 지정): {genre}")
    head_block = "\n".join(head) if head else "(메타 없음)"

    return f"""당신은 한국 대중가요(특히 5070 트로트·발라드)의 작사를 깊이 분석하는
작사가입니다. 아래 가사 본문을 읽고, 이 곡의 작사 스타일을 데이터화하세요.
목표는 "이 스타일로 새 가사를 써 줄 AI 작사가에게 줄 프롬프트"를 만드는 것입니다.

[곡 정보]
{head_block}

[가사 본문]
{lyrics_block}

[지시사항]
1. 다음 차원을 각 영어 또는 짧은 한글 표현 2~6개로 채우세요(자유 어휘):
   - tone (정서/톤)
   - perspective (화자 시점)
   - themes (주제)
   - imagery (이미지·비유)
   - rhyme (운율/어미 패턴)
   - structure (구조 패턴)
   - vocabulary (자주 쓰는 어휘/관용구)
2. summary: 한 줄(한국어, 30자 내외)로 이 곡의 작사 화법을 요약.
3. writer_prompt: 다른 AI에게 이 스타일로 작사하라고 시킬 때 그대로 붙여넣을
   페르소나+지시문(한국어, 4~8문장). 예시 가사 한두 줄을 참고 인용해 톤을 살리세요.
4. rationale: 위 분석의 핵심 근거 한 줄.

[반드시 아래 JSON 만 출력 — 마크다운/설명 금지]
{{
  "summary": "...",
  "patterns": {{
    "tone": [], "perspective": [], "themes": [], "imagery": [],
    "rhyme": [], "structure": [], "vocabulary": []
  }},
  "writer_prompt": "...",
  "rationale": "..."
}}"""


def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _clean_list(xs) -> list[str]:
    out: list[str] = []
    for x in xs or []:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


def parse(raw: str) -> dict:
    data = _loads(raw)
    patterns_in = data.get("patterns") or {}
    patterns: dict[str, list[str]] = {}
    for d in DIMS:
        cleaned = _clean_list(patterns_in.get(d, []))
        if cleaned:
            patterns[d] = cleaned
    return {
        "summary": (data.get("summary") or "").strip(),
        "patterns": patterns,
        "writer_prompt": (data.get("writer_prompt") or "").strip(),
        "rationale": (data.get("rationale") or "").strip(),
    }


def gemini_call(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        generation_config={"temperature": 0.5, "response_mime_type": "application/json"},
    )
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def analyze_lyrics(
    lyrics: str,
    *,
    title: str = "",
    genre: str = "",
    llm_call=None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """가사 본문 → 작사 패턴 + writer_prompt. llm_call 주입 시 헤드리스 가능."""
    if not (lyrics or "").strip():
        raise ValueError("가사 본문이 비어 있습니다.")
    prompt = build_prompt(lyrics, title=title, genre=genre)
    if llm_call is None:
        if not api_key:
            raise ValueError("api_key 또는 llm_call 중 하나가 필요합니다.")
        raw = gemini_call(prompt, api_key=api_key, model=model)
    else:
        raw = llm_call(prompt)
    return parse(raw)


if __name__ == "__main__":
    sample = """엄마가 보고 싶어 눈을 감으면
어릴 적 그 집 마당이 떠올라요
바람 따라 흩어진 꽃잎처럼
지나간 시간들이 그립습니다"""

    def stub(_p: str) -> str:
        return json.dumps({
            "summary": "회상·그리움 1인칭 화자, 자연 이미지 풍부",
            "patterns": {
                "tone": ["회상", "그리움", "잔잔한 슬픔"],
                "perspective": ["1인칭 화자", "어머니에게"],
                "themes": ["어머니", "유년", "지나간 시간"],
                "imagery": ["꽃잎", "바람", "마당"],
                "rhyme": ["~요 어미", "~다 어미"],
                "structure": ["벌스 중심", "후렴 부재"],
                "vocabulary": ["눈을 감으면", "그립습니다"],
            },
            "writer_prompt": "당신은 5070 세대를 위한 한국 트로트·발라드 작사가입니다. ...",
            "rationale": "엄마/유년/마당/바람 등 회상 어휘 집중",
        }, ensure_ascii=False)

    out = analyze_lyrics(sample, title="엄마생각", genre="트로트", llm_call=stub)
    print(json.dumps(out, ensure_ascii=False, indent=2))
