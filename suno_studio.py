"""Suno 프롬프트 스튜디오 엔진.

vocab.json(통제 어휘 사전)을 읽어, 차원별 선택을 받아 Suno 스타일 프롬프트로
조립한다. 자동 조합 추천과 '벤치마킹'(마음에 든 조합과 비슷한 변주 N개 생성)을
지원한다. Streamlit 의존성이 없어 헤드리스로 테스트/호출 가능 — app.py 탭과
n8n/Gemini 자동화가 동일 엔진을 공유한다.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

VOCAB_PATH = Path(__file__).parent / "vocab.json"

# 자동 추천/변주에서 다룰 차원과 각 차원에서 뽑을 항목 수(최소, 최대).
_AUTO_PICKS: dict[str, tuple[int, int]] = {
    "rhythm": (1, 1),
    "instruments": (2, 3),
    "solo": (1, 1),
    "vocal_ensemble": (1, 1),
    "vocal_gender": (1, 1),
    "vocal_register": (1, 1),
    "vocal_technique": (1, 2),
    "production": (1, 1),
}


def load_vocab(path: str | Path = VOCAB_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_presets(vocab: dict) -> list[tuple[str, str]]:
    """[(preset_key, 한국어 라벨)] 목록."""
    return [(k, v.get("label", k)) for k, v in vocab["presets"].items()]


def list_moods(vocab: dict) -> list[tuple[str, str]]:
    """[(suno_mood, 한국어 라벨)] 목록."""
    return [(m["suno"], m.get("ko", m["suno"])) for m in vocab["dimensions"]["mood"]]


def mood_bpm_range(vocab: dict, mood_suno: str) -> tuple[int, int]:
    for m in vocab["dimensions"]["mood"]:
        if m["suno"] == mood_suno:
            lo, hi = m.get("bpm", [90, 110])
            return int(lo), int(hi)
    return 90, 110


def _matches(item: dict, country: str | None, mood: str | None) -> bool:
    countries = item.get("country")
    if countries and "*" not in countries and country and country not in countries:
        return False
    moods = item.get("mood")
    if moods and "*" not in moods and mood and mood not in moods:
        return False
    return True


def candidates(
    vocab: dict, dimension: str, *, country: str | None = None, mood: str | None = None
) -> list[dict]:
    """프리셋(나라)과 무드로 필터링된 어휘 후보. [{suno, ko}, ...]."""
    items = vocab["dimensions"].get(dimension, [])
    return [it for it in items if _matches(it, country, mood)]


def compose(
    vocab: dict,
    preset_key: str,
    picks: dict[str, list[str]],
    *,
    bpm: int | None = None,
) -> str:
    """compose_order 순서로 Suno 프롬프트 문자열을 결정론적으로 조립한다.

    picks: {dimension: [suno_term, ...]} (mood 포함). 'genre' 는 프리셋 anchors 사용.
    """
    preset = vocab["presets"][preset_key]
    parts: list[str] = []

    for dim in vocab["compose_order"]:
        if dim == "genre":
            parts.extend(preset.get("anchors", []))
        elif dim == "bpm":
            if bpm:
                parts.append(f"{int(bpm)} BPM")
        else:
            parts.extend(picks.get(dim, []))

    # 순서 유지 중복 제거.
    seen: set[str] = set()
    deduped = [p for p in parts if p and not (p in seen or seen.add(p))]
    return ", ".join(deduped)


def auto_select(
    vocab: dict,
    preset_key: str,
    mood_suno: str,
    *,
    seed: int | None = None,
) -> dict:
    """무드에 맞춰 각 차원에서 무작위로 골라 하나의 조합(picks)을 만든다."""
    rng = random.Random(seed)
    country = vocab["presets"][preset_key].get("country")
    picks: dict[str, list[str]] = {"mood": [mood_suno]}
    for dim, (lo, hi) in _AUTO_PICKS.items():
        pool = [it["suno"] for it in candidates(vocab, dim, country=country, mood=mood_suno)]
        if not pool:
            continue
        k = min(rng.randint(lo, hi), len(pool))
        picks[dim] = rng.sample(pool, k)
    lo_bpm, hi_bpm = mood_bpm_range(vocab, mood_suno)
    picks["_bpm"] = [str(rng.randint(lo_bpm, hi_bpm))]
    return picks


def generate_variations(
    vocab: dict,
    preset_key: str,
    base_picks: dict[str, list[str]],
    *,
    n: int = 5,
    lock: set[str] | None = None,
    seed: int | None = None,
) -> list[dict]:
    """마음에 든 조합(base_picks)과 '비슷한 유형'의 변주 N개를 만든다 (벤치마킹).

    lock 에 든 차원은 그대로 유지(곡의 정체성 보존), 나머지는 같은 무드/나라
    후보에서 다시 샘플링해 변화를 준다. 서로 다른 N개를 보장하려 시도한다.
    """
    rng = random.Random(seed)
    country = vocab["presets"][preset_key].get("country")
    mood = (base_picks.get("mood") or [None])[0]
    lock = lock or {"mood", "vocal_gender"}

    results: list[dict] = []
    signatures: set[tuple] = set()
    attempts = 0
    while len(results) < n and attempts < n * 40:
        attempts += 1
        variant: dict[str, list[str]] = {"mood": base_picks.get("mood", [])}
        for dim, (lo, hi) in _AUTO_PICKS.items():
            if dim in lock:
                variant[dim] = list(base_picks.get(dim, []))
                continue
            pool = [it["suno"] for it in candidates(vocab, dim, country=country, mood=mood)]
            if not pool:
                variant[dim] = list(base_picks.get(dim, []))
                continue
            k = min(rng.randint(lo, hi), len(pool))
            variant[dim] = rng.sample(pool, k)
        # BPM 은 같은 무드 범위 안에서 살짝 흔든다.
        lo_bpm, hi_bpm = mood_bpm_range(vocab, mood) if mood else (90, 110)
        variant["_bpm"] = [str(rng.randint(lo_bpm, hi_bpm))]

        sig = tuple(sorted((d, tuple(sorted(v))) for d, v in variant.items() if d != "_bpm"))
        if sig in signatures:
            continue
        signatures.add(sig)
        results.append(variant)
    return results


def picks_to_prompt(vocab: dict, preset_key: str, picks: dict[str, list[str]]) -> str:
    """picks(_bpm 포함 가능)를 받아 compose 로 최종 프롬프트 생성."""
    bpm = None
    if picks.get("_bpm"):
        try:
            bpm = int(picks["_bpm"][0])
        except (ValueError, IndexError):
            bpm = None
    clean = {k: v for k, v in picks.items() if not k.startswith("_")}
    return compose(vocab, preset_key, clean, bpm=bpm)


if __name__ == "__main__":
    # 헤드리스 데모/테스트.
    v = load_vocab()
    print("프리셋:", list_presets(v))
    print("무드:", [k for k, _ in list_moods(v)])
    print()

    base = auto_select(v, "kr_trot", "tearful, emotional, heartfelt", seed=7)
    print("== 자동 추천 조합 ==")
    print(picks_to_prompt(v, "kr_trot", base))
    print()

    print("== 벤치마킹: 위 조합과 비슷한 변주 4개 (mood·성별 고정) ==")
    for i, var in enumerate(generate_variations(v, "kr_trot", base, n=4, seed=99), 1):
        print(f"{i}. {picks_to_prompt(v, 'kr_trot', var)}")
