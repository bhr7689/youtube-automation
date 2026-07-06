"""3축(장르×상황×감정) 조합 → 검색어 자동 생성 엔진."""
from __future__ import annotations

import json
import os
import random

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taxonomies.json")
_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is None:
        with open(_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def _vocab(tag: dict, lang: str) -> list[str]:
    return tag.get("vocab", {}).get(lang, [])


def generate_queries(
    category: str = "music_playlist",
    genres: list[str] | None = None,
    situations: list[str] | None = None,
    emotions: list[str] | None = None,
    langs: list[str] | None = None,
    limit: int = 10,
    seed: int | None = None,
) -> list[str]:
    """칩 선택 → 검색어 조합. 축이 비어 있어도 동작(있는 축만 조합)."""
    cat = load()["categories"][category]
    axes = cat["axes"]
    langs = langs or ["ko"]
    rnd = random.Random(seed)

    g_tags = [axes["genre"]["tags"][k] for k in (genres or []) if k in axes["genre"]["tags"]]
    s_tags = [axes["situation"]["tags"][k] for k in (situations or []) if k in axes["situation"]["tags"]]
    e_tags = [axes["emotion"]["tags"][k] for k in (emotions or []) if k in axes["emotion"]["tags"]]

    out: list[str] = []

    def _add(q: str):
        q = " ".join(q.split())
        if q and q not in out:
            out.append(q)

    suffixes = cat.get("suffixes", {})

    for lang in langs:
        sfx = suffixes.get(lang, [])
        g_names = [t["label"] if lang == "ko" else (_vocab(t, lang)[:1] or [t["label"]])[0] for t in g_tags]

        # 템플릿 1: [감정 문구] + [장르]
        for gt, gname in zip(g_tags, g_names):
            for et in e_tags:
                for phrase in rnd.sample(_vocab(et, lang), min(2, len(_vocab(et, lang)))):
                    _add(f"{phrase} {gname if lang == 'ko' else ''}".strip()
                         if lang != "ko" else f"{phrase} {gname}")
        # 템플릿 2: [상황 문구] + [장르]
        for gt, gname in zip(g_tags, g_names):
            for st_ in s_tags:
                for phrase in rnd.sample(_vocab(st_, lang), min(2, len(_vocab(st_, lang)))):
                    _add(f"{phrase} {gname}" if lang == "ko" else f"{gname} {phrase}")
        # 템플릿 3: [장르] + 서픽스
        for gname in g_names:
            if sfx:
                _add(f"{gname} {rnd.choice(sfx)}")
        # 템플릿 4: 장르 고유 문구 (이미지 채록 어휘 직접 활용)
        for gt in g_tags:
            for phrase in rnd.sample(_vocab(gt, lang), min(2, len(_vocab(gt, lang)))):
                _add(phrase)
        # 템플릿 5: 장르 없이 감정×상황
        if not g_tags:
            for et in e_tags:
                for st_ in s_tags:
                    ev = _vocab(et, lang)
                    sv = _vocab(st_, lang)
                    if ev and sv:
                        _add(f"{rnd.choice(ev)} {rnd.choice(sv)} {rnd.choice(sfx) if sfx else ''}")
            for t in e_tags + s_tags:
                for phrase in rnd.sample(_vocab(t, lang), min(2, len(_vocab(t, lang)))):
                    _add(f"{phrase} {rnd.choice(sfx)}" if sfx else phrase)

    return out[:limit]
