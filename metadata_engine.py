"""🌐 국가별 메타데이터 엔진 — 🇰🇷 한국 먼저.

사장님 규칙(A-8 최우선): **감성 문장보다 유저가 실제 검색하는 단어 밀도가 우선.**
  → '검색어 밀도형' 제목(옵션2)을 1순위 기본, '감성형'(옵션1)은 보조.
채널 정체성: 무가사 여름/계절 재즈·BGM 플레이리스트.

이 모듈이 하는 일:
  1) 곡 컨셉(과일/계절) + 국가 → 그 나라 실검색어로 제목 후보 생성(밀도형/감성형)
  2) 설명글 4단 + 태그(한/영) + 해시태그 3~5개
  3) serp_judge 로 후보 채택/재작성 판정 연결(SERP 데이터가 있을 때)

LLM 키가 있으면 concept_maker 로 실생성 확장 가능(옵션). 없어도 규칙 기반으로 바로 동작.
JP·US 는 다음 단계에서 같은 구조로 추가.
"""
from __future__ import annotations
import itertools

# ── 🇰🇷 한국 어휘 (실검색어 중심) ─────────────────────────────
KR = {
    # 목적성 키워드 = 유저가 실제로 검색하는 3대장 계열 (밀도형의 핵심)
    "purpose": ["공부할 때 듣는 음악", "일할 때 듣는 음악", "카페 음악", "매장 BGM",
                "집중 음악", "휴식 음악", "드라이브", "작업용 BGM"],
    "purpose_short": ["공부할 때", "일할 때", "카페 BGM", "매장 BGM", "집중", "휴식", "드라이브"],
    "genre": ["여름 재즈", "재즈 플레이리스트", "보사노바", "여름 보사노바"],
    "mood": ["시원한", "청량한", "달콤한", "잔잔한", "경쾌한", "상큼한", "과즙 가득한"],
    "en_tail": ["Summer Jazz", "Summer Jazz BGM", "Jazz Playlist", "Chill Summer Jazz"],
}

# 컨셉(과일/계절) — 제목·썸네일 소재 일치축
CONCEPTS = {
    "수박": {"emoji": "🍉", "phrase": "수박 한 입", "adj": ["시원한", "달콤한"]},
    "레몬": {"emoji": "🍋", "phrase": "톡 쏘는 레몬", "adj": ["상큼한", "과즙 가득한"]},
    "복숭아": {"emoji": "🍑", "phrase": "달콤한 복숭아", "adj": ["달콤한", "부드러운"]},
    "바다": {"emoji": "🌊", "phrase": "바다로 떠나는 여름", "adj": ["청량한", "시원한"]},
    "풋사과": {"emoji": "🍏", "phrase": "아삭한 풋사과", "adj": ["상큼한", "경쾌한"]},
    "메론소다": {"emoji": "🍹", "phrase": "톡톡 메론소다", "adj": ["청량한", "시원한"]},
}


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def generate_titles_kr(concept: str = "수박", n_search: int = 5, n_emotion: int = 5) -> dict:
    """🇰🇷 한국 제목 후보. 검색형(밀도형) 우선 + 감성형 보조."""
    c = CONCEPTS.get(concept, CONCEPTS["수박"])
    emoji, phrase = c["emoji"], c["phrase"]
    genres = KR["genre"]; en = KR["en_tail"]; purp = KR["purpose_short"]; mood = KR["mood"]

    # ── 검색형(밀도형) — 목적성 키워드 나열(옵션2). 사장님 1순위 ──
    # 형식: [Playlist] {형용사}{장르} {이모지} {용도1}·{용도2}·{용도3} | {영문}
    search = []
    combos = itertools.cycle([
        ("공부할 때", "일할 때", "카페 BGM"),
        ("작업용 BGM", "공부할 때", "매장 BGM"),
        ("집중", "휴식", "카페 음악"),
        ("드라이브", "카페 BGM", "매장 음악"),
        ("공부할 때", "카페 BGM", "집중"),
    ])
    for i in range(n_search):
        g = genres[i % len(genres)]; e = en[i % len(en)]; m = mood[i % len(mood)]
        p1, p2, p3 = next(combos)
        search.append(f"[Playlist] {m} {g} {emoji} {p1}·{p2}·{p3} | {e}")

    # ── 감성형(문장형) — 보조(옵션1). 브랜딩/추천 유입 ──
    # 형식: Playlist | {형용사} {컨셉 문구} {이모지} {형용사2} {장르} | {영문}
    emotion = []
    for i in range(n_emotion):
        m1 = c["adj"][i % len(c["adj"])]; m2 = mood[(i + 2) % len(mood)]
        g = genres[i % len(genres)]; e = en[i % len(en)]
        emotion.append(f"Playlist | {m1} {phrase} {emoji} {m2} {g} | {e}")

    # SERP 검증에 넣을 내 핵심 키워드(제목이 이 풀에 묶여야 함)
    my_keywords = _dedup(genres + [f"{p} 음악" for p in ["공부할 때", "일할 때"]]
                         + ["카페 BGM", "작업용 BGM", concept])

    return {
        "country": "KR",
        "concept": concept,
        "search_titles": search,      # 밀도형 (1순위)
        "emotion_titles": emotion,    # 감성형 (보조)
        "my_keywords": my_keywords,
        "thumb_text": f"{phrase} {emoji}",   # 썸네일에 얹을 문구(제목과 소재 일치)
    }


def build_description_kr(concept: str = "수박") -> str:
    """🇰🇷 설명글 4단(감성 훅 → 핵심 → 사용맥락 → 트랙리스트/CTA)."""
    c = CONCEPTS.get(concept, CONCEPTS["수박"])
    return (
        f"무더운 여름, {c['phrase']}의 {c['adj'][0]} 감성으로 지친 하루를 청량하게 채워주는 "
        f"여름 재즈 플레이리스트입니다. {c['emoji']}🍹\n\n"
        "공부할 때, 일할 때, 카페·매장 배경음악(BGM)으로, 또는 휴식·드라이브할 때 "
        "편안하게 감상해 보세요.\n\n"
        + build_hashtags_kr(concept) + "\n\n"
        "--------------------------------------------------\n"
        "[Tracklist]\n00:00 곡 제목 1\n03:15 곡 제목 2\n..."
    )


def build_tags_kr(concept: str = "수박") -> list[str]:
    """🇰🇷 태그 — 한글 실검색어 + 영문 반반."""
    base = ["playlist", "플리", "여름 재즈", "재즈 플레이리스트",
            "공부할 때 듣는 음악", "일할 때 듣는 음악", "카페 BGM", "매장 음악",
            "작업용 BGM", "집중 음악", "휴식 음악",
            "Summer Jazz", "Summer Jazz Playlist", "Jazz Playlist", "BGM"]
    return _dedup(base + [concept, f"{concept} 재즈"])


def build_hashtags_kr(concept: str = "수박") -> str:
    """🇰🇷 해시태그 3~5개(한/영 반반, 스팸 금지선)."""
    tags = ["#여름재즈", "#플레이리스트", "#SummerJazz", f"#{concept}재즈", "#카페BGM"]
    return " ".join(tags[:5])


def generate_package_kr(concept: str = "수박") -> dict:
    """🇰🇷 업로드 패키지 한 세트(제목 후보 + 설명 + 태그 + 해시태그 + 썸네일 문구)."""
    t = generate_titles_kr(concept)
    return {
        **t,
        "description": build_description_kr(concept),
        "tags": build_tags_kr(concept),
        "hashtags": build_hashtags_kr(concept),
    }


# ── 자기검증 (키·네트워크 불필요) ──────────────────────────
if __name__ == "__main__":
    pkg = generate_package_kr("수박")
    print("🇰🇷 검색형(밀도형) 제목 — 1순위")
    for s in pkg["search_titles"]:
        print("  ", s)
    print("\n🇰🇷 감성형 제목 — 보조")
    for s in pkg["emotion_titles"]:
        print("  ", s)
    print("\n썸네일 문구(제목과 소재 일치):", pkg["thumb_text"])
    print("\n해시태그:", pkg["hashtags"])
    print("태그:", ", ".join(pkg["tags"]))
    print("\n설명글:\n" + pkg["description"])

    # SERP 판정 연결 데모 (신생 저조회 SERP면 재작성 나와야)
    try:
        import serp_judge
        weak_serp = [
            {"title": "나만의 브이로그 배경음악", "views": 400, "published_at": "2025-07-28",
             "subscribers": 60, "channel_age_months": 2},
            {"title": "초보 첫 플리 모음", "views": 900, "published_at": "2025-07-25",
             "subscribers": 120, "channel_age_months": 3},
            {"title": "감성 수박 이야기", "views": 300, "published_at": "2025-07-30",
             "subscribers": 40, "channel_age_months": 1},
        ]
        j = serp_judge.judge(weak_serp, pkg["my_keywords"])
        print(f"\n[SERP 판정 데모] verdict={j['verdict']} fit={j['fit_score']}")
        assert j["verdict"] == "regenerate"
        print("✅ metadata_engine + serp_judge 연결 통과")
    except Exception as e:
        print("serp_judge 연결 스킵:", e)

    for cc in CONCEPTS:
        assert generate_titles_kr(cc)["search_titles"], cc
    print("✅ metadata_engine KR self-test 통과")
