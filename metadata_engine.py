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


# ══════════════════════════════════════════════════════════
# 🇯🇵 일본 — 用途(作業用BGM) + 洋楽ジャズ + 시즌(スイカ) 3박자 (A-6/A-8)
# ══════════════════════════════════════════════════════════
JP = {
    # 3대장 목적성 키워드 + 洋楽
    "purpose_short": ["作業用", "勉強用", "カフェBGM", "店舗BGM", "集中", "リラックス"],
    "genre": ["夏のジャズ", "洋楽ジャズ", "ジャズプレイリスト", "ボサノバ", "爽やかなジャズ"],
    "mood": ["爽やかな", "甘くて爽やかな", "涼しげな", "軽快な"],
    "en_tail": ["Summer Jazz", "Summer Jazz Music", "Jazz Playlist", "Chill Summer Jazz"],
}

CONCEPTS_JP = {
    "수박": {"jp": "スイカ", "emoji": "🍉", "phrase": "冷たいスイカをひと口",
             "desc_lead": "冷たいスイカを一口食べたとき", "adj": "爽やかな"},
    "레몬": {"jp": "レモン", "emoji": "🍋", "phrase": "爽やかなレモンをひと搾り",
             "desc_lead": "爽やかなレモンを搾ったとき", "adj": "甘酸っぱくて爽やかな"},
    "복숭아": {"jp": "桃", "emoji": "🍑", "phrase": "甘い桃をひと口",
               "desc_lead": "甘い桃を一口食べたとき", "adj": "まろやかで甘い"},
    "바다": {"jp": "海", "emoji": "🌊", "phrase": "海へ出かけたい夏",
             "desc_lead": "海辺で涼んでいるとき", "adj": "涼しげで爽やかな"},
    "풋사과": {"jp": "青りんご", "emoji": "🍏", "phrase": "シャキッと青りんご",
               "desc_lead": "シャキッと青りんごをかじったとき", "adj": "軽快で爽やかな"},
    "메론소다": {"jp": "メロンソーダ", "emoji": "🍹", "phrase": "シュワっとメロンソーダ",
                 "desc_lead": "シュワっとメロンソーダを飲んだとき", "adj": "爽やかで涼しげな"},
}


def generate_titles_jp(concept: str = "수박", n_search: int = 5, n_emotion: int = 5) -> dict:
    """🇯🇵 일본 제목. 검색형(밀도형=用途 나열) 우선 + 감성형 보조."""
    c = CONCEPTS_JP.get(concept, CONCEPTS_JP["수박"])
    emoji = c["emoji"]; genres = JP["genre"]; en = JP["en_tail"]; mood = JP["mood"]

    # ── 검색형(밀도형) — 用途 나열(작업용·공부용·카페BGM). 洋楽 주입 ──
    # 형식: [Playlist] {상황+무드+장르} {이모지} {用途1・用途2・用途3} | {영문}
    leads = itertools.cycle([
        "暑い夏に聴きたい爽やかなジャズ",
        "夏にぴったりな爽やかな洋楽ジャズ",
        "暑い日に涼しくなる夏の洋楽ジャズ",
        "作業がはかどる爽やかな夏のジャズ",
        "カフェで流れる涼しげな洋楽ジャズ",
    ])
    purposes = itertools.cycle([
        "作業用・勉強用・カフェBGM",
        "作業用BGM・勉強用・店舗BGM",
        "集中・リラックス・カフェBGM",
        "勉強用・作業用・洋楽BGM",
        "作業用・カフェBGM・店舗BGM",
    ])
    search = []
    for i in range(n_search):
        e = en[i % len(en)]
        search.append(f"[Playlist] {next(leads)} {emoji} {next(purposes)} | {e}")

    # ── 감성형 — 문장형(옵션1) 보조 ──
    emotion = []
    for i in range(n_emotion):
        g = genres[i % len(genres)]; e = en[i % len(en)]
        emotion.append(f"Playlist | {c['phrase']} {emoji} {c['adj']}{g} 作業用BGM | {e}")

    my_keywords = _dedup(["夏のジャズ", "作業用BGM", "勉強用BGM", "カフェBGM",
                          "洋楽ジャズ", "洋楽", c["jp"], "Summer Jazz"])
    return {
        "country": "JP", "concept": concept,
        "search_titles": search, "emotion_titles": emotion,
        "my_keywords": my_keywords,
        "thumb_text": f"{c['phrase']} {emoji}",
    }


def build_description_jp(concept: str = "수박") -> str:
    """🇯🇵 설명글 4단 — 사장님 예시 형식 그대로(복사용)."""
    c = CONCEPTS_JP.get(concept, CONCEPTS_JP["수박"])
    return (
        f"暑い夏、{c['desc_lead']}のような、甘くて爽やかな夏のジャズプレイリストです。{c['emoji']}🍹\n\n"
        "仕事や作業に集中できる作業用BGM、勉強用BGM、カフェや店舗のBGM、"
        "リラックスタイムにぜひお楽しみください。\n\n"
        + build_hashtags_jp(concept) + "\n\n"
        "--------------------------------------------------\n"
        "[Tracklist]\n00:00 曲名 1\n03:15 曲名 2\n..."
    )


def build_tags_jp(concept: str = "수박") -> list[str]:
    """🇯🇵 태그 — 3대장 + 洋楽 + 영문 (예시 그대로)."""
    jp = CONCEPTS_JP.get(concept, CONCEPTS_JP["수박"])["jp"]
    return _dedup([
        "作業用BGM", "勉強用BGM", "カフェBGM", "洋楽", "洋楽ジャズ",
        "Playlist", "プレイリスト", "夏のジャズ", jp, "夏 BGM", "爽やかなジャズ",
        "Summer Jazz", "Summer Jazz Music", "店舗BGM", "テンションが上がる", "リラックス ジャズ",
    ])


def build_hashtags_jp(concept: str = "수박") -> str:
    """🇯🇵 해시태그 — 3대장 + 洋楽ジャズ 도배(예시 그대로)."""
    jp = CONCEPTS_JP.get(concept, CONCEPTS_JP["수박"])["jp"]
    tags = ["#作業用BGM", "#勉強用BGM", "#カフェBGM", "#夏のジャズ",
            f"#{jp}ジャズ", "#SummerJazz", "#洋楽ジャズ", "#ジャズプレイリスト"]
    return " ".join(tags)


def generate_package_jp(concept: str = "수박") -> dict:
    t = generate_titles_jp(concept)
    return {**t, "description": build_description_jp(concept),
            "tags": build_tags_jp(concept), "hashtags": build_hashtags_jp(concept)}


# ── 국가 디스패처 ──────────────────────────────────────────
def generate_package(country: str = "KR", concept: str = "수박") -> dict:
    return {"KR": generate_package_kr, "JP": generate_package_jp}.get(
        country.upper(), generate_package_kr)(concept)


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

    print("\n" + "=" * 55)
    jp = generate_package_jp("수박")
    print("🇯🇵 検索型(밀도형) 제목 — 1순위")
    for s in jp["search_titles"]:
        print("  ", s)
    print("\n🇯🇵 感情型 제목 — 보조")
    for s in jp["emotion_titles"][:3]:
        print("  ", s)
    print("\n썸네일 문구:", jp["thumb_text"])
    print("해시태그:", jp["hashtags"])
    print("태그:", ", ".join(jp["tags"]))
    print("\n설명글:\n" + jp["description"])
    for cc in CONCEPTS_JP:
        assert generate_titles_jp(cc)["search_titles"], cc
    print("\n✅ metadata_engine JP self-test 통과")
