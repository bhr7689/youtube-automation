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
import re

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F1E6-\U0001F1FF]")

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
    # ── 비-과일 테마(알고리즘 변화 대응 — 같은 공식에 슬롯) ──
    "카페": {"emoji": "☕", "phrase": "창가의 따뜻한 카페 한 잔", "adj": ["포근한", "잔잔한"],
             "mood": ["포근한", "잔잔한", "따뜻한", "아늑한"], "desc_open": "포근한 어느 날,",
             "genre": ["카페 재즈", "보사노바", "재즈 플레이리스트"], "en_tail": ["Cafe Jazz", "Jazz Playlist", "Chill Jazz BGM"]},
    "비": {"emoji": "🌧️", "phrase": "비 오는 날 창가", "adj": ["차분한", "촉촉한"],
           "mood": ["차분한", "촉촉한", "잔잔한", "고요한"], "desc_open": "비 내리는 날,",
           "genre": ["비 오는 날 재즈", "잔잔한 재즈", "보사노바"], "en_tail": ["Rainy Jazz", "Chill Jazz", "Jazz Playlist"]},
    "새벽": {"emoji": "🌙", "phrase": "고요한 새벽 감성", "adj": ["잔잔한", "몽환적인"],
             "mood": ["잔잔한", "몽환적인", "고요한", "깊은"], "desc_open": "고요한 새벽,",
             "genre": ["새벽 감성 재즈", "잔잔한 재즈", "Lofi 재즈"], "en_tail": ["Late Night Jazz", "Lofi Jazz", "Chill Jazz"]},
    "난로": {"emoji": "🔥", "phrase": "따뜻한 난로 앞", "adj": ["포근한", "아늑한"],
             "mood": ["포근한", "아늑한", "따뜻한", "나른한"], "desc_open": "추운 겨울,",
             "genre": ["겨울 재즈", "따뜻한 재즈", "보사노바"], "en_tail": ["Winter Jazz", "Cozy Jazz", "Jazz Playlist"]},
}


# ══════════════════════════════════════════════════════════
# 🎯 3계층 키워드 모델 (제목·설명·태그에 모두 심는다)
#   ① 메인(검색량 핵심)  ② 감성/상황(클릭률)  ③ 영문/글로벌(해외 유입)
#   → 인기 영상과 공통 키워드 조합을 만들어 '연관 동영상'에 묶이게 함
# ══════════════════════════════════════════════════════════
TIERS = {
    "KR": {
        "main": ["playlist", "플리", "여름 재즈", "여름 음악", "재즈 플레이리스트"],
        "emotion": ["시원한 음악", "청량한 재즈", "달콤한", "수박", "일할 때 듣는 음악",
                    "공부할 때 듣는 음악", "드라이브", "카페 BGM"],
        "global": ["Summer Jazz", "Summer Jazz Playlist", "BGM", "Chill", "Jazz Playlist"],
    },
    "JP": {
        "main": ["playlist", "プレイリスト", "夏のジャズ", "洋楽ジャズ", "作業用BGM"],
        "emotion": ["爽やかなジャズ", "涼しげな", "スイカ", "勉強用BGM", "カフェBGM",
                    "店舗BGM", "リラックス ジャズ", "テンションが上がる"],
        "global": ["Summer Jazz", "Summer Jazz Music", "BGM", "Chill", "Jazz Playlist"],
    },
    "US": {
        "main": ["playlist", "summer jazz", "jazz playlist", "background music"],
        "emotion": ["relaxing jazz", "chill jazz", "refreshing", "watermelon",
                    "music for work", "study music", "cafe music", "for relaxing"],
        "global": ["Summer Jazz", "BGM", "Chill", "Bossa Nova", "Lofi", "instrumental"],
    },
}


def keyword_tiers(country: str = "KR") -> dict:
    """그 나라의 3계층 키워드(화면 표시용 — 어떤 계층을 심었는지 투명하게)."""
    return TIERS.get(country.upper(), TIERS["KR"])


def _tier_tags(country: str, extra: list[str] | None = None) -> list[str]:
    """3계층 전부 + 컨셉/추가어를 합친 태그 세트 (연관추천 묶임 최적)."""
    t = keyword_tiers(country)
    return _dedup(t["main"] + t["emotion"] + t["global"] + (extra or []))


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
    en = c.get("en_tail", KR["en_tail"]); purp = KR["purpose_short"]
    genres = c.get("genre", KR["genre"]); mood = c.get("mood", KR["mood"])

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
        f"{c.get('desc_open', '무더운 여름,')} {c['phrase']}의 {c['adj'][0]} 감성으로 "
        f"지친 하루를 채워주는 재즈 플레이리스트입니다. {c['emoji']}🍹\n\n"
        "공부할 때, 일할 때, 카페·매장 배경음악(BGM)으로, 또는 휴식·드라이브할 때 "
        "편안하게 감상해 보세요.\n\n"
        + build_hashtags_kr(concept) + "\n\n"
        "--------------------------------------------------\n"
        "[Tracklist]\n00:00 곡 제목 1\n03:15 곡 제목 2\n..."
    )


def build_tags_kr(concept: str = "수박") -> list[str]:
    """🇰🇷 태그 — 3계층(메인·감성상황·영문글로벌) + 컨셉."""
    return _tier_tags("KR", ["매장 음악", "작업용 BGM", "집중 음악", "휴식 음악",
                             concept, f"{concept} 재즈"])


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
        "keyword_tiers": keyword_tiers("KR"),
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
    """🇯🇵 태그 — 3계층 + 洋楽/3대장 + 컨셉 (예시 그대로)."""
    jp = CONCEPTS_JP.get(concept, CONCEPTS_JP["수박"])["jp"]
    return _tier_tags("JP", ["勉強用", "洋楽", "夏 BGM", jp, f"{jp}ジャズ"])


def build_hashtags_jp(concept: str = "수박") -> str:
    """🇯🇵 해시태그 — 3대장 + 洋楽ジャズ 도배(예시 그대로)."""
    jp = CONCEPTS_JP.get(concept, CONCEPTS_JP["수박"])["jp"]
    tags = ["#作業用BGM", "#勉強用BGM", "#カフェBGM", "#夏のジャズ",
            f"#{jp}ジャズ", "#SummerJazz", "#洋楽ジャズ", "#ジャズプレイリスト"]
    return " ".join(tags)


def generate_package_jp(concept: str = "수박") -> dict:
    t = generate_titles_jp(concept)
    return {**t, "description": build_description_jp(concept),
            "tags": build_tags_jp(concept), "hashtags": build_hashtags_jp(concept),
            "keyword_tiers": keyword_tiers("JP")}


# ══════════════════════════════════════════════════════════
# 🇺🇸 미국/영어권 — use-case first (언제·왜 듣는지 앞세움)
# ══════════════════════════════════════════════════════════
CONCEPTS_US = {
    "수박": {"en": "watermelon", "emoji": "🍉", "phrase": "A Sweet Bite of Watermelon",
             "adj": "Cool & Refreshing"},
    "레몬": {"en": "lemon", "emoji": "🍋", "phrase": "A Splash of Fresh Lemon",
             "adj": "Zesty & Refreshing"},
    "복숭아": {"en": "peach", "emoji": "🍑", "phrase": "A Sweet Ripe Peach",
               "adj": "Sweet & Mellow"},
    "바다": {"en": "ocean", "emoji": "🌊", "phrase": "An Escape to the Summer Sea",
             "adj": "Cool & Breezy"},
    "풋사과": {"en": "green apple", "emoji": "🍏", "phrase": "A Crisp Green Apple",
               "adj": "Crisp & Upbeat"},
    "메론소다": {"en": "melon soda", "emoji": "🍹", "phrase": "A Fizzy Melon Soda",
                 "adj": "Cool & Bubbly"},
}


def generate_titles_us(concept: str = "수박", n_search: int = 5, n_emotion: int = 5) -> dict:
    """🇺🇸 영어권 제목. use-case first(밀도형) 우선 + 감성형 보조."""
    c = CONCEPTS_US.get(concept, CONCEPTS_US["수박"])
    emoji = c["emoji"]
    genres = ["Summer Jazz", "Bossa Nova Jazz", "Chill Jazz", "Smooth Jazz"]
    en_tail = ["Summer Jazz BGM", "Jazz Playlist", "Chill Background Music", "Bossa Nova BGM"]

    # ── use-case first(밀도형) — Music for Work/Study/Relax 나열 ──
    leads = itertools.cycle([
        "Refreshing Summer Jazz",
        "Cool Summer Jazz Playlist",
        "Relaxing Summer Bossa Nova",
        "Fresh & Breezy Summer Jazz",
        "Chill Summer Jazz",
    ])
    uses = itertools.cycle([
        "Music for Work, Study & Café",
        "for Work, Focus & Relax",
        "for Study, Café & Chill",
        "for Work, Sleep & Relaxing",
        "for Focus, Café & Good Vibes",
    ])
    search = []
    for i in range(n_search):
        search.append(f"[Playlist] {next(leads)} {emoji} {next(uses)} | {en_tail[i % len(en_tail)]}")

    # ── 감성형(문장형) 보조 ──
    emotion = []
    for i in range(n_emotion):
        g = genres[i % len(genres)]
        emotion.append(f"Playlist | {c['phrase']} {emoji} {c['adj']} {g} | Summer Jazz BGM")

    my_keywords = _dedup(["summer jazz", "jazz playlist", "study music", "cafe music",
                          "background music", "chill jazz", c["en"]])
    return {"country": "US", "concept": concept,
            "search_titles": search, "emotion_titles": emotion,
            "my_keywords": my_keywords, "thumb_text": f"{c['phrase']} {emoji}"}


def build_description_us(concept: str = "수박") -> str:
    """🇺🇸 설명글 4단(영어, 복사용)."""
    c = CONCEPTS_US.get(concept, CONCEPTS_US["수박"])
    return (
        f"A sweet and refreshing summer jazz playlist — like {c['phrase'].lower()} "
        f"on a hot summer day. {c['emoji']}🍹\n\n"
        "Perfect as background music for work, study, focus, at a café or shop, "
        "or during your relaxing moments.\n\n"
        + build_hashtags_us(concept) + "\n\n"
        "--------------------------------------------------\n"
        "[Tracklist]\n00:00 Song Title 1\n03:15 Song Title 2\n..."
    )


def build_tags_us(concept: str = "수박") -> list[str]:
    """🇺🇸 태그 — 3계층 + use-case + 컨셉."""
    en = CONCEPTS_US.get(concept, CONCEPTS_US["수박"])["en"]
    return _tier_tags("US", ["work music", "sleep music", "no lyrics",
                             "Summer Jazz Playlist", en, f"{en} jazz"])


def build_hashtags_us(concept: str = "수박") -> str:
    """🇺🇸 해시태그 3~5개."""
    en = CONCEPTS_US.get(concept, CONCEPTS_US["수박"])["en"]
    cap = en.title().replace(" ", "")
    tags = ["#SummerJazz", "#JazzPlaylist", "#StudyMusic", f"#{cap}Jazz", "#CafeMusic"]
    return " ".join(tags[:5])


def generate_package_us(concept: str = "수박") -> dict:
    t = generate_titles_us(concept)
    return {**t, "description": build_description_us(concept),
            "tags": build_tags_us(concept), "hashtags": build_hashtags_us(concept)}


# ══════════════════════════════════════════════════════════
# 🔗 2차 결착 — 채택된 제목의 키워드로 설명·태그를 재구성
#   흐름: 레퍼런스 조합 → SERP 검증 → 채택 제목 → 그 제목 키워드로 설명·태그 재주입
#   = 제목이 고조회와 묶이면, 같은 키워드를 설명·태그에도 심어 한 번 더 알고리즘에 묶음
# ══════════════════════════════════════════════════════════
_KW_STOP = {"playlist", "bgm", "summer", "jazz", "music", "플리", "the", "for", "and", "a"}


def title_keywords(title: str) -> dict:
    """제목에서 키워드(구/단어)를 뽑는다 — 접두사·이모지·영문꼬리 제거."""
    core = re.sub(r"^\s*\[?\s*[Pp]laylist\s*\]?\s*\|?", "", title)
    if "|" in core:
        core = core.rsplit("|", 1)[0]          # 마지막 영문 꼬리 제거
    core = _EMOJI.sub(" ", core)
    phrases = [re.sub(r"\s+", " ", p.strip()) for p in re.split(r"[·,]", core) if len(p.strip()) >= 2]
    words = [w for w in re.findall(r"[\w가-힣ぁ-んァ-ヶ一-龥]+", core)
             if len(w) > 1 and w.lower() not in _KW_STOP]
    return {"phrases": _dedup(phrases)[:6], "words": _dedup(words)[:10]}


_DESC_FN = {}   # 아래에서 채움
_TAGS_FN = {}


def describe_from_title(title: str, country: str = "KR", concept: str = "수박") -> str:
    """채택 제목의 키워드를 설명 최상단(가중 큰 위치)에 재주입 = 2차 결착."""
    kw = title_keywords(title)
    band = " · ".join(kw["phrases"] or kw["words"][:5])
    base = _DESC_FN.get(country.upper(), build_description_kr)(concept)
    return f"🎧 {band}\n\n{base}"


def tags_from_title(title: str, country: str = "KR", concept: str = "수박") -> list[str]:
    """채택 제목의 키워드를 태그 앞쪽에 재주입 = 2차 결착."""
    kw = title_keywords(title)
    base = _TAGS_FN.get(country.upper(), build_tags_kr)(concept)
    return _dedup(kw["words"] + base)


# ── 국가 디스패처 ──────────────────────────────────────────
def generate_package(country: str = "KR", concept: str = "수박") -> dict:
    pkg = {"KR": generate_package_kr, "JP": generate_package_jp,
           "US": generate_package_us}.get(country.upper(), generate_package_kr)(concept)
    pkg["keyword_tiers"] = keyword_tiers(pkg["country"])   # 3계층 투명 표시
    return pkg


# 2차 결착용 빌더 매핑 (builders 정의 이후 채움)
_DESC_FN.update({"KR": build_description_kr, "JP": build_description_jp, "US": build_description_us})
_TAGS_FN.update({"KR": build_tags_kr, "JP": build_tags_jp, "US": build_tags_us})


# ── 🧭 적응형 — 지금 뜨는 테마를 trend_meta 에서 받아 자동 슬롯 ──
def generate_adaptive(country: str = "KR") -> dict:
    """알고리즘 변화 대응: '지금 뜨는 컨셉'을 감지해 같은 공식에 끼워 생성.
    과일이 뜨면 과일을, 카페가 뜨면 카페를 자동으로. (trend_meta 연동)
    라이브/캡처 데이터 없으면 계절 프라이어로 폴백."""
    try:
        import trend_meta
        theme = trend_meta.current_theme(country)
        boost = trend_meta.rising_boost(country)
    except Exception:
        theme, boost = "수박", []
    if theme not in CONCEPTS:      # 아직 문구가 없는 새 테마면 안전 폴백
        theme = "수박"
    pkg = generate_package(country, theme)
    if boost:                      # 이 시기 실검색어를 태그 앞쪽에 주입(3계층 감성/상황 보강)
        pkg["tags"] = _dedup(boost + pkg["tags"])
        pkg["rising_boost"] = boost
    pkg["picked_theme"] = theme
    pkg["theme_source"] = "live/seasonal(trend_meta)"
    return pkg


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

    print("\n" + "=" * 55)
    us = generate_package_us("수박")
    print("🇺🇸 use-case first(밀도형) 제목 — 1순위")
    for s in us["search_titles"]:
        print("  ", s)
    print("\n🇺🇸 emotional 제목 — 보조")
    for s in us["emotion_titles"][:3]:
        print("  ", s)
    print("\n썸네일 문구:", us["thumb_text"])
    print("해시태그:", us["hashtags"])
    print("태그:", ", ".join(us["tags"]))
    print("\n설명글:\n" + us["description"])
    for cc in CONCEPTS_US:
        assert generate_titles_us(cc)["search_titles"], cc

    # 3계층 투명 확인
    print("\n" + "=" * 55)
    for co in ("KR", "JP", "US"):
        t = keyword_tiers(co)
        print(f"🎯 {co} 3계층 — 메인:{len(t['main'])} 감성상황:{len(t['emotion'])} 영문:{len(t['global'])}")
        pkg = generate_package(co, "수박")
        assert pkg["keyword_tiers"] and pkg["tags"] and pkg["description"], co
    print("\n✅ metadata_engine US + 3계층 self-test 통과 (KR/JP/US 완비)")
