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


# 시드 — 4개 시즌. 사용자가 골라서 시작하거나 복제해서 새 시즌 만들 수 있음.
SEED_SIGNATURES: dict[str, dict] = {
    # 1) 첫 시드 — 사용자가 명시한 스텔라장식 프렌치 샹송 카페
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
        "accent_palette": [
            "delicate glockenspiel chimes",
            "soft vibraphone",
            "muted trumpet whispers",
            "gentle flute breaths",
            "warm cello swells",
            "tiny celeste sparkles",
            "soft brushed cymbal washes (very subtle, no rhythm)",
        ],
        "section_recipes": {
            "Intro": "soft piano alone, accordion enters gently, warm string pad embraces like sunshine",
            "Verse": "piano + airy whispering vocal, upright bass walks quietly in the background",
            "Pre-Chorus": "strings swell warmly, accordion grows in romance",
            "Chorus": "full ensemble warmly together, vocal sweet and airy, accordion sings the heart",
            "Break": "charming accordion solo, piano playfully softly accompanies, contrabass plucking, very spacious and relaxed",
            "Bridge": "instruments thin out, only piano and whispering vocal, intimate moment",
            "Outro": "vocal fades very slowly into warm piano and string resonance",
        },
        "stage_direction_palette": [
            "Sing with a warm smile, clear sweet and airy voice, very relaxed storytelling",
            "Whispering, gentle and soft, like reading an old letter",
            "Sweet and Airy",
            "Slower",
            "Slightly playful, with a tender smile",
            "Hushed, almost a sigh",
            "Fading Out",
        ],
    },
    # 2) 5070 트로트 시즌 — 시골 봄날 회상
    "hometown_memory_cafe": {
        "name": "Hometown Memory Café",
        "started": "2026-06-27",
        "day_count": 1,
        "primary_language": "한국어",
        "core_instruments": [
            "warm nylon acoustic guitar (gentle fingerpicking)",
            "soft accordion melody",
            "warm upright bass",
            "subtle string pad (40s strings)",
        ],
        "excluded_instruments": ["electric drums", "synthesizers", "electric guitar"],
        "vocal": "warm female vocal in her 40s, gentle vibrato, nostalgic tone, sincere storytelling",
        "mood": "nostalgic, tender, springtime in the countryside, gentle longing for mother",
        "tempo_label": "mid-tempo, walking pace 88 BPM",
        "bpm_range": [82, 94],
        "reference_artist": "Lee Mi-ja, Joo Hyun-mi",
        "accent_palette": [
            "soft harmonica solo",
            "wooden flute breath",
            "single mandolin tremolo",
            "warm cello legato",
            "tiny glockenspiel chimes",
            "soft brushed snare washes",
        ],
        "section_recipes": {
            "Intro": "warm guitar fingerpicking alone, accordion enters slowly, gentle string pad sunshine",
            "Verse": "guitar + warm female vocal, upright bass walks softly",
            "Pre-Chorus": "strings swell gently, accordion warmly grows",
            "Chorus": "full ensemble together warmly, accordion sings the heart, vocal full of emotion",
            "Break": "warm harmonica solo, guitar gently accompanies, very spacious",
            "Bridge": "vocal alone with soft guitar, intimate and tender",
            "Outro": "vocal slowly fades, guitar remains in warm resonance",
        },
        "stage_direction_palette": [
            "Sing with tender warmth, like remembering mother",
            "Slower, nostalgic",
            "Hushed, almost in tears",
            "With gentle smile",
            "Tenderly",
            "Fading Out",
        ],
    },
    # 3) 발라드 / 도시 야경
    "midnight_city_lounge": {
        "name": "Midnight City Lounge",
        "started": "2026-06-27",
        "day_count": 1,
        "primary_language": "한국어",
        "core_instruments": [
            "soft electric piano (Rhodes-like, warm)",
            "warm upright bass",
            "lush string pad",
            "very subtle brushed drums (slow, no strong rhythm)",
        ],
        "excluded_instruments": ["distorted guitar", "synth lead"],
        "vocal": "warm male vocal in his 30s, breathy, intimate, late-night radio host tone",
        "mood": "city night, melancholic, intimate, smoky lounge atmosphere",
        "tempo_label": "slow tempo 72 BPM",
        "bpm_range": [68, 78],
        "reference_artist": "Sung Si-kyung, Toy",
        "accent_palette": [
            "muted trumpet whispers",
            "soft tenor sax breath",
            "vibraphone shimmer",
            "warm cello swells",
            "delicate piano arpeggio",
            "subtle synth pad shimmer",
        ],
        "section_recipes": {
            "Intro": "electric piano alone, soft pads in distance, rainy night atmosphere",
            "Verse": "piano + intimate breathy vocal, bass walks quietly",
            "Pre-Chorus": "strings enter gently, brushed drums whisper",
            "Chorus": "full ensemble warmly together, vocal opens with emotion, lush strings",
            "Break": "muted trumpet solo, piano playfully softly underneath",
            "Bridge": "drums drop out, only piano and vocal, intimate confession",
            "Outro": "vocal fades into warm piano and string resonance",
        },
        "stage_direction_palette": [
            "Breathy, intimate, like whispering to one person",
            "Slower, melancholic",
            "Hushed",
            "With quiet emotion",
            "Smoky lounge tone",
            "Fading Out",
        ],
    },
    # 4) 7080 포크 / 따스한 토요일 아침
    "saturday_morning_cafe": {
        "name": "Saturday Morning Café",
        "started": "2026-06-27",
        "day_count": 1,
        "primary_language": "한국어",
        "core_instruments": [
            "bright acoustic guitar (gentle strumming)",
            "warm upright bass",
            "soft harmonica accents",
            "subtle warm pad",
        ],
        "excluded_instruments": ["electric drums", "synth bass", "distortion"],
        "vocal": "warm folksy vocal, natural and unforced, like singing to a friend over coffee",
        "mood": "warm Saturday morning, sunlight through curtain, nostalgic 70s 80s folk",
        "tempo_label": "mid-tempo 95 BPM, easy walking pace",
        "bpm_range": [90, 102],
        "reference_artist": "Kim Kwang-seok, Yoo Jae-ha",
        "accent_palette": [
            "soft harmonica solo",
            "single mandolin pluck",
            "warm whistling melody",
            "tiny vibraphone chimes",
            "soft hand percussion (shaker)",
            "warm flute breath",
        ],
        "section_recipes": {
            "Intro": "acoustic guitar strumming alone, warm pad in distance, sunlight feel",
            "Verse": "guitar + warm folksy vocal, bass walks easily",
            "Pre-Chorus": "harmonica enters gently, pad warmth grows",
            "Chorus": "full ensemble together brightly, vocal natural and warm",
            "Break": "harmonica solo, guitar gently accompanies",
            "Bridge": "vocal alone with soft guitar, intimate moment",
            "Outro": "vocal fades into warm guitar resonance",
        },
        "stage_direction_palette": [
            "Sing naturally, like to a friend",
            "Warm and relaxed",
            "Slightly playful",
            "With gentle smile",
            "Slower",
            "Fading Out",
        ],
    },
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


def _slugify(name: str) -> str:
    """시리즈 ID 만들기 — 한글/영문 모두 안전. 공백·특수문자 → _."""
    import re
    s = re.sub(r"[^\w가-힣]+", "_", name.strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "series"


def create_series(name: str, *, base_series_id: str | None = None) -> str:
    """새 시리즈 생성. base_series_id 가 있으면 그 시그니처를 복제(이름·날짜·카운트만 새로).
    없으면 첫 시드(parisian_chanson_cafe)를 빈 베이스로 사용.

    반환: 새 시리즈 ID
    """
    from datetime import date as _date
    data = load_signatures()
    if not name.strip():
        raise ValueError("시리즈 이름을 입력해 주세요.")
    new_id = _slugify(name)
    # 중복 방지
    base_id = new_id
    n = 2
    while new_id in data.get("series", {}):
        new_id = f"{base_id}_{n}"
        n += 1

    # 베이스 결정
    if base_series_id and base_series_id in data.get("series", {}):
        base = data["series"][base_series_id]
    else:
        base = next(iter(SEED_SIGNATURES.values()))
    new_sig = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
               for k, v in base.items()}
    new_sig["name"] = name.strip()
    new_sig["started"] = _date.today().isoformat()
    new_sig["day_count"] = 1
    data.setdefault("series", {})[new_id] = new_sig
    data["current"] = new_id
    save_signatures(data)
    return new_id


def delete_series(series_id: str) -> bool:
    """시리즈 삭제. 마지막 1개는 보호. 현재 시리즈를 삭제하면 다른 것으로 자동 전환."""
    data = load_signatures()
    series = data.get("series", {})
    if series_id not in series:
        return False
    if len(series) <= 1:
        return False  # 마지막 시리즈는 보호
    del series[series_id]
    if data.get("current") == series_id:
        data["current"] = next(iter(series))
    save_signatures(data)
    return True


def list_series() -> list[tuple[str, str, int]]:
    """모든 시리즈 (id, name, day_count) 리스트."""
    data = load_signatures()
    return [
        (sid, sig.get("name", sid), int(sig.get("day_count", 0)))
        for sid, sig in (data.get("series") or {}).items()
    ]


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
