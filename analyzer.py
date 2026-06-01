"""곡 역설계 분석기 — 유튜브 메타데이터 → Suno 스타일 picks 추출.

ToS 안전(오디오 다운로드 X). 영상의 제목/설명/태그/댓글 같은 메타데이터를 Gemini 에
주고, 통제 어휘(vocab.json) 안에서 차원별로 고르게 한다. 결과는 스튜디오의 picks
형식이라 그대로 변주·블렌딩·레시피 저장이 가능하고, 사전에 없는 '새 어휘 후보'도
함께 받아 vocab 보완(데이터 풍부화)에 쓴다.

LLM 호출은 주입(llm_call) 가능 — 헤드리스 테스트 시 스텁을 넣는다.
"""

from __future__ import annotations

import json
import re

DEFAULT_MODEL = "gemini-2.0-flash"

# 분석 대상 차원 (mood/bpm 은 별도 처리)
ANALYZE_DIMS = [
    "rhythm", "instruments", "solo",
    "vocal_ensemble", "vocal_gender", "vocal_register", "vocal_technique",
    "production",
]


def _allowed_terms(vocab: dict, dim: str) -> list[str]:
    return [it["suno"] for it in vocab["dimensions"].get(dim, [])]


def build_prompt(meta: dict, vocab: dict, *, preset_hint: str | None = None) -> str:
    moods = [m["suno"] for m in vocab["dimensions"]["mood"]]
    presets = list(vocab["presets"].keys())
    allowed = {d: _allowed_terms(vocab, d) for d in ANALYZE_DIMS}

    meta_lines = [
        f"- 제목: {meta.get('title', '')}",
        f"- 채널: {meta.get('channel', '')}",
        f"- 태그: {', '.join(meta.get('tags', []) or [])}",
        f"- 설명: {(meta.get('description', '') or '')[:1200]}",
    ]
    comments = meta.get("comments") or []
    if comments:
        joined = "\n".join(f"  · {c}" for c in comments[:20])
        meta_lines.append(f"- 상위 댓글:\n{joined}")

    audio = meta.get("audio_features") or {}
    if audio:
        audio_bits: list[str] = []
        if audio.get("tempo_bpm"):
            audio_bits.append(f"BPM≈{audio['tempo_bpm']:.0f}")
        if audio.get("key_label"):
            audio_bits.append(f"키={audio['key_label']}")
        if audio.get("duration_sec"):
            audio_bits.append(f"길이={int(audio['duration_sec'])}초")
        if audio.get("rms_mean") is not None:
            audio_bits.append(f"평균에너지={audio['rms_mean']:.3f}")
        if audio.get("spectral_centroid_mean") is not None:
            audio_bits.append(f"스펙트럴센트로이드={audio['spectral_centroid_mean']:.0f}Hz")
        if audio.get("onset_rate") is not None:
            audio_bits.append(f"어택밀도={audio['onset_rate']}/초")
        if audio_bits:
            meta_lines.append("- 실측 오디오 특성: " + ", ".join(audio_bits))

    lyrics_excerpt = (meta.get("lyrics_excerpt") or "").strip()
    if lyrics_excerpt:
        meta_lines.append(f"- 가사 일부:\n  {lyrics_excerpt[:600]}")

    meta_block = "\n".join(meta_lines)

    allowed_block = json.dumps(
        {"mood": moods, "presets": presets, **allowed}, ensure_ascii=False, indent=2
    )

    audio_note = (
        "\n* 실측 BPM/키가 주어졌으면 picks 의 bpm 은 그 값을 따르고, rhythm/mood 는 "
        "BPM 범위와 모드(major/minor)에 부합하는 어휘를 골라주세요."
    ) if audio else ""

    return f"""당신은 한국 5070 시니어 트로트 음악을 분석하는 음악 기획자입니다.
아래 유튜브 영상 메타데이터(그리고 가능한 경우 실측 오디오 특성·가사 일부)를 보고,
이 곡의 음악 스타일을 추정해 Suno 프롬프트 빌딩블록으로 변환하세요.{audio_note}

[메타데이터]
{meta_block}

[허용 어휘 — 각 차원은 아래 목록 안에서만 고르세요]
{allowed_block}

[규칙]
- mood 는 목록에서 정확히 하나만 선택.
- preset 은 presets 중 하나(한국 트로트면 kr_trot).
- 각 차원(rhythm, instruments, solo, vocal_ensemble, vocal_gender, vocal_register,
  vocal_technique, production)은 허용 목록의 문자열을 그대로(정확히) 골라 배열로.
  확신이 없으면 빈 배열.
- 목록에 없지만 이 곡에 꼭 맞는 표현이 떠오르면 new_terms 에 차원별로 적어주세요
  (사전 보완용. 영어 Suno 스타일 표현으로).
- bpm 은 정수로 추정.
- 반드시 아래 JSON 만 출력(설명/마크다운 금지):

{{
  "preset": "kr_trot",
  "mood": "<목록의 mood 중 하나>",
  "bpm": 0,
  "picks": {{ "rhythm": [], "instruments": [], "solo": [], "vocal_ensemble": [],
              "vocal_gender": [], "vocal_register": [], "vocal_technique": [],
              "production": [] }},
  "new_terms": {{ }},
  "rationale": "<한 줄 근거>"
}}"""


def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def parse_and_snap(raw: str, vocab: dict, *, preset_hint: str | None = None) -> dict:
    """Gemini 응답을 vocab 에 맞춰 검증·스냅. 허용 목록 밖 표현은 new_terms 로 회수."""
    data = _loads(raw)
    presets = list(vocab["presets"].keys())
    moods = {m["suno"].lower(): m["suno"] for m in vocab["dimensions"]["mood"]}

    preset = data.get("preset")
    if preset not in presets:
        preset = preset_hint if preset_hint in presets else presets[0]

    mood_raw = (data.get("mood") or "").strip().lower()
    mood = moods.get(mood_raw)

    new_terms: dict[str, list[str]] = {
        k: list(v) for k, v in (data.get("new_terms") or {}).items() if v
    }

    picks: dict[str, list[str]] = {}
    raw_picks = data.get("picks") or {}
    for dim in ANALYZE_DIMS:
        allowed_lower = {t.lower(): t for t in _allowed_terms(vocab, dim)}
        kept: list[str] = []
        for term in raw_picks.get(dim, []) or []:
            canon = allowed_lower.get(str(term).strip().lower())
            if canon and canon not in kept:
                kept.append(canon)
            elif term:
                new_terms.setdefault(dim, [])
                if term not in new_terms[dim]:
                    new_terms[dim].append(term)
        if kept:
            picks[dim] = kept

    if mood:
        picks["mood"] = [mood]
    bpm = data.get("bpm")
    try:
        bpm = int(bpm) if bpm else None
    except (ValueError, TypeError):
        bpm = None
    if bpm:
        picks["_bpm"] = [str(bpm)]

    return {
        "preset": preset,
        "mood": mood,
        "bpm": bpm,
        "picks": picks,
        "new_terms": new_terms,
        "rationale": data.get("rationale", ""),
    }


def gemini_call(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        generation_config={"temperature": 0.4, "response_mime_type": "application/json"},
    )
    resp = m.generate_content(prompt)
    return (resp.text or "").strip()


def analyze_metadata(
    meta: dict,
    vocab: dict,
    *,
    preset_hint: str | None = None,
    llm_call=None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """메타데이터 → picks 추출. llm_call(prompt)->str 주입 시 테스트 가능."""
    prompt = build_prompt(meta, vocab, preset_hint=preset_hint)
    if llm_call is None:
        if not api_key:
            raise ValueError("api_key 또는 llm_call 중 하나가 필요합니다.")
        raw = gemini_call(prompt, api_key=api_key, model=model)
    else:
        raw = llm_call(prompt)
    return parse_and_snap(raw, vocab, preset_hint=preset_hint)


if __name__ == "__main__":
    import suno_studio

    v = suno_studio.load_vocab()
    sample_meta = {
        "title": "[트로트] 비 오는 밤 어머니 생각에 눈물이... 색소폰 트로트 발라드",
        "channel": "추억의 트로트",
        "tags": ["트로트", "색소폰", "발라드", "어머니"],
        "description": "비 오는 밤, 돌아가신 어머니가 그리울 때 듣는 애절한 트로트.",
        "comments": ["눈물이 나네요", "어머니 생각에 펑펑 울었습니다", "색소폰 소리가 가슴을 울려요"],
    }

    def stub(prompt: str) -> str:
        return json.dumps({
            "preset": "kr_trot",
            "mood": "tearful, emotional, heartfelt",
            "bpm": 68,
            "picks": {
                "rhythm": ["slow 6/8 ballad sway"],
                "instruments": ["saxophone solo", "lush strings"],
                "solo": ["saxophone solo"],
                "vocal_gender": ["male vocal"],
                "vocal_register": ["deep low baritone, rich chest voice"],
                "vocal_technique": ["expressive vibrato", "kkeokki note-bending ornamentation"],
                "production": ["warm vintage 80s production"],
            },
            "new_terms": {"instruments": ["rain ambience SFX"]},
            "rationale": "비·어머니·눈물·색소폰 단서 → 애절 발라드 트로트",
        }, ensure_ascii=False)

    result = analyze_metadata(sample_meta, v, llm_call=stub)
    print("preset:", result["preset"], "| mood:", result["mood"], "| bpm:", result["bpm"])
    print("프롬프트:", suno_studio.picks_to_prompt(v, result["preset"], result["picks"]))
    print("새 어휘 후보(보완):", json.dumps(result["new_terms"], ensure_ascii=False))
