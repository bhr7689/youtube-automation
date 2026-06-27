"""오늘의 시그니처 — 채널 사운드 정체성.

같은 시그니처로 매일 곡을 쌓아 채널 정체성을 만든다.
- 핵심 악기 / 보컬 / 분위기 / 템포 는 고정
- 곡마다 액센트 악기 1개 / 미세 BPM / 강도만 미묘하게 변주
- 절대 금지 악기(`excluded_instruments`)는 모든 곡에서 등장 금지

저장: daily_signature.json
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

SIG_PATH = Path(__file__).resolve().parent / "daily_signature.json"


# 첫 시드 — 사용자가 명시한 스텔라장식 프렌치 샹송 카페
SEED_SIGNATURES: dict[str, dict] = {
    "parisian_chanson_cafe": {
        "name": "Parisian Chanson Café",
        "started": "2026-06-27",
        "day_count": 1,
        "primary_language": "프랑스어",
        "core_instruments": [
            "soft warm acoustic piano",
            "bright romantic accordion",
            "quiet upright bass (background)",
            "subtle warm string pad",
        ],
        "excluded_instruments": ["drums", "guitars"],
        "vocal": "whispering and airy female vocal, clear and sweet voice, cute and lovely tone",
        "mood": "charming, cozy, heartwarming, dreamy, minimalist french chanson",
        "tempo_label": "very slow tempo, walking pace",
        "bpm_range": [60, 72],
        "reference_artist": "Stella Jang",
        # 곡마다 살짝 변주할 수 있는 액센트 (no drums / no guitars 룰 유지)
        "accent_palette": [
            "delicate glockenspiel chimes",
            "soft vibraphone",
            "muted trumpet whispers",
            "gentle flute breaths",
            "warm cello swells",
            "tiny celeste sparkles",
            "soft brushed cymbal washes (very subtle, no rhythm)",
        ],
        # 섹션별 사운드 레시피 — 가사 안 괄호 지문 작성에 참고
        "section_recipes": {
            "Intro": "soft piano alone, accordion enters gently, warm string pad embraces like sunshine",
            "Verse": "piano + airy whispering vocal, upright bass walks quietly in the background",
            "Pre-Chorus": "strings swell warmly, accordion grows in romance",
            "Chorus": "full ensemble warmly together, vocal sweet and airy, accordion sings the heart",
            "Break": "charming accordion solo, piano playfully softly accompanies, contrabass plucking, very spacious and relaxed",
            "Bridge": "instruments thin out, only piano and whispering vocal, intimate moment",
            "Outro": "vocal fades very slowly into warm piano and string resonance",
        },
        # Stage Direction 어휘 풀 — 가사 섹션 머리에 [대괄호]로 박는 보컬 연기 지시
        "stage_direction_palette": [
            "Sing with a warm smile, clear sweet and airy voice, very relaxed storytelling",
            "Whispering, gentle and soft, like reading an old letter",
            "Sweet and Airy",
            "Slower",
            "Slightly playful, with a tender smile",
            "Hushed, almost a sigh",
            "Fading Out",
        ],
    }
}


# ────────────────────────────────────────────────────────────────────────────
# 저장 / 불러오기
# ────────────────────────────────────────────────────────────────────────────
def load_signatures() -> dict:
    if SIG_PATH.exists():
        try:
            data = json.loads(SIG_PATH.read_text(encoding="utf-8"))
            if "series" in data and "current" in data:
                return data
        except Exception:
            pass
    data = {"current": "parisian_chanson_cafe", "series": SEED_SIGNATURES.copy()}
    save_signatures(data)
    return data


def save_signatures(data: dict) -> None:
    SIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_current(data: dict | None = None) -> dict:
    data = data or load_signatures()
    sid = data.get("current")
    return data.get("series", {}).get(sid, {})


def set_current(series_id: str) -> dict:
    data = load_signatures()
    if series_id in data.get("series", {}):
        data["current"] = series_id
        save_signatures(data)
    return data


def upsert_series(series_id: str, signature: dict) -> dict:
    data = load_signatures()
    data["series"][series_id] = signature
    save_signatures(data)
    return data


def increment_day(series_id: str | None = None) -> int:
    """오늘 곡 1개 생성 완료 시 day_count + 1."""
    data = load_signatures()
    sid = series_id or data.get("current")
    sig = data.get("series", {}).get(sid)
    if not sig:
        return 0
    sig["day_count"] = int(sig.get("day_count", 0)) + 1
    save_signatures(data)
    return sig["day_count"]


# ────────────────────────────────────────────────────────────────────────────
# 곡별 변주: 액센트 선택
# ────────────────────────────────────────────────────────────────────────────
def pick_accent(signature: dict, *, seed: int | None = None) -> str:
    palette = signature.get("accent_palette") or []
    if not palette:
        return ""
    rng = random.Random(seed) if seed is not None else random
    return rng.choice(palette)


# ────────────────────────────────────────────────────────────────────────────
# Suno "Style of Music" 텍스트 빌드 (시그니처 + 곡별 액센트 + 언어)
# ────────────────────────────────────────────────────────────────────────────
def build_suno_style(
    signature: dict,
    *,
    accent: str = "",
    language_english: str = "",
    day_no: int | None = None,
) -> str:
    parts: list[str] = []
    series_name = signature.get("name", "")
    if series_name:
        day = day_no if day_no is not None else signature.get("day_count", 1)
        parts.append(f"{series_name} (Day {day})")

    excluded = signature.get("excluded_instruments") or []
    if excluded:
        parts.append("strictly no " + ", no ".join(excluded))

    parts.extend(signature.get("core_instruments") or [])

    tempo = signature.get("tempo_label", "")
    if tempo:
        parts.append(tempo)
    mood = signature.get("mood", "")
    if mood:
        parts.append(mood)
    vocal = signature.get("vocal", "")
    if vocal:
        parts.append(vocal)
    ref = signature.get("reference_artist", "")
    if ref:
        parts.append(f"{ref} style")

    if language_english:
        parts.append(f"pure {language_english} lyrics, sung in {language_english}")

    if accent:
        parts.append(f"[today's accent: {accent}]")

    return ", ".join(p for p in parts if str(p).strip())


# ────────────────────────────────────────────────────────────────────────────
# 가사 LLM에 박아 줄 시그니처 요약 — 사운드 지문/Stage Direction 자동 작성용
# ────────────────────────────────────────────────────────────────────────────
def signature_brief_for_prompt(signature: dict, *, accent: str = "") -> str:
    recipes = signature.get("section_recipes") or {}
    recipes_block = "\n".join(f"  · {k}: {v}" for k, v in recipes.items())
    stages = signature.get("stage_direction_palette") or []
    stages_block = "\n".join(f"  · {s}" for s in stages)
    excluded = ", ".join(signature.get("excluded_instruments") or [])
    excluded_line = f"\n절대 금지 악기(모든 섹션에서 등장 금지): {excluded}" if excluded else ""

    return f"""[오늘의 시그니처 사운드 — 모든 가사가 이 위에서 동작해야 함]
시리즈: {signature.get('name', '')}
핵심 악기(이것만 사용): {", ".join(signature.get('core_instruments') or [])}{excluded_line}
보컬: {signature.get('vocal', '')}
분위기: {signature.get('mood', '')}
템포: {signature.get('tempo_label', '')}
레퍼런스 아티스트 톤: {signature.get('reference_artist', '') or '(자유)'}
오늘의 액센트 (이 한 가지 악기만 살짝 추가 허용): {accent or '(없음)'}

[섹션별 사운드 레시피 — 가사 안 괄호 () 사운드 지문을 작성할 때 이 레시피 위에서 변주]
{recipes_block}

[가능한 Stage Direction 어휘 — 섹션 머리에 대괄호 [ ] 로 박을 보컬 연기 지시]
{stages_block}
"""


if __name__ == "__main__":
    sig = get_current()
    accent = pick_accent(sig, seed=42)
    print("=== Suno Style of Music ===")
    print(build_suno_style(sig, accent=accent, language_english="French"))
    print("\n=== Signature Brief (for LLM) ===")
    print(signature_brief_for_prompt(sig, accent=accent))
