"""📎 레퍼런스 제목 코퍼스 — 제목 조합의 '첫 단계 기준(BASIS)'.

사장님 방법(원본): 내가 만든 어휘가 아니라, **고조회 레퍼런스 제목들을 조합·재조합**해
첫 제목을 만들고 → 시크릿 SERP 검증 → 고조회와 묶이는 제목으로 재조합.
그래서 제목 생성의 기준 = 이 레퍼런스 코퍼스다.

코퍼스는 2가지로 쌓인다:
  ① 실시간 자동 수집 — youtube_client.search(regionCode)로 상위 제목 수집 (PC/키)
  ② 직접 첨부 — 사장님이 캡처·정리한 제목을 붙여넣기 (add_titles)

시드 = 사장님이 실제로 주셨던 여름 재즈 플리 제목들.
저장 = ref_titles.json (git 추적 — cron/수동이 쌓아 앱과 공유).
순수 로직 — 키 없이 시드·첨부만으로 즉시 동작.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path

STORE = Path(__file__).with_name("ref_titles.json")

# ── 시드: 사장님이 준 실제 고조회 레퍼런스 제목 ──────────────
SEED_REF = {
    "KR": [
        "Playlist 시원하게 한입 베어 무는 수박, 달콤한 청량한 여름 재즈 플리 | Sweet & Refreshing Summer Jazz Playlist",
        "Playlist | 청량한 재즈 끝판왕 🍧 듣는 순간 산뜻 시원해지는 보사노바 여름 재즈 | Jazz background music for work, focus",
        "Playlist | 화창한 여름엔 상큼한 재즈가 최고잖아 🍋 시원하고 경쾌한 청량한 여름 재즈 BGM | 카페, 매장 | Summer Jazz",
        "Playlist | 여름 재즈 끝판왕 플리 🍉 여름에 듣기 좋은 청량한 재즈 플레이리스트 | Summer Jazz Instrumental Music",
        "Playlist | 과즙 가득한 상큼한 여름 재즈 🍑 시원해지는 여름 감성 BGM | 매장, 카페 | Summer Jazz",
        "Playlist | 훌쩍 바다로 떠나고 싶은 여름 🌊 듣기만 해도 시원해지는 청량한 재즈 | Summer Jazz",
        "[Playlist] 무더운 여름을 식혀줄 청량한 재즈 모음 | Summer Jazz Playlist",
    ],
    "JP": [
        "Playlist | 冷たいスイカをひと口 🍉 甘くて爽やかな洋楽夏のジャズ作業用BGM | Summer Jazz",
        "[Playlist] 暑い夏に聴きたい爽やかなジャズ 🍉 作業用・勉強用・カフェBGM | Summer Jazz Music",
    ],
    "US": [
        "Playlist | A Sip of Refreshing Watermelon 🍉 Sweet and Cool Summer Jazz | Summer Jazz Background Music",
        "Playlist | A Good Day 🍉 A refreshing bite of watermelon and sweet uplifting summer jazz | Summer Jazz BGM",
    ],
}

# 상황/용도(목적성) 키워드 — 나라별. 제목·태그의 '연관추천 묶임' 핵심.
PURPOSE = {
    "KR": ["공부할 때", "일할 때", "작업용", "카페", "매장", "집중", "휴식", "드라이브", "카페 BGM", "매장 BGM"],
    "JP": ["作業用", "勉強用", "カフェBGM", "店舗BGM", "集中", "リラックス", "睡眠用"],
    "US": ["for work", "for study", "for focus", "for relaxing", "for sleep", "cafe", "background music"],
}
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F1E6-\U0001F1FF]")


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(d: dict) -> None:
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        x = (x or "").strip()
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out


def all_titles(country: str) -> list[str]:
    """시드 + 저장(첨부/자동수집) 합본."""
    co = country.upper()
    stored = _load().get(co, {}).get("titles", [])
    return _dedup(SEED_REF.get(co, []) + stored)


# ── ② 직접 첨부 ────────────────────────────────────────────
def add_titles(country: str, titles: list[str], source: str = "manual") -> int:
    """사장님이 캡처·정리한 레퍼런스 제목을 코퍼스에 추가(첨부)."""
    co = country.upper()
    data = _load()
    entry = data.setdefault(co, {"titles": [], "sources": []})
    before = set(entry["titles"])
    entry["titles"] = _dedup(entry["titles"] + [t for t in titles if t and t.strip()])
    added = len(set(entry["titles"]) - before)
    if added:
        entry["sources"].append({"source": source, "added": added})
    _save(data)
    return added


# ── ① 실시간 자동 수집 (키/PC) ─────────────────────────────
def collect_auto(country: str, keywords: list[str], fetch=None, want: int = 40) -> int:
    """youtube_client 로 그 나라 상위 제목을 실시간 수집해 코퍼스에 추가.
    fetch(keyword, country) -> list[str] 주입 가능(테스트). 없으면 youtube_client 시도.
    키/네트워크 없으면 0 반환(안전 스킵)."""
    f = fetch or _default_fetch
    titles: list[str] = []
    for kw in keywords:
        try:
            titles += (f(kw, country) or [])
        except Exception:
            pass
        if len(titles) >= want:
            break
    return add_titles(country, titles[:want], source="auto")


def _default_fetch(keyword: str, country: str) -> list[str]:
    """기본 수집기 — youtube_client.search_videos 사용(있으면). 없으면 []."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).with_name("jpshorts") / "backend"))
        import youtube_client as yc
        lang = {"KR": "ko", "JP": "ja", "US": "en"}.get(country.upper(), "ko")
        cards = yc.search_videos(keyword, lang=lang)  # regionCode 자동
        return [c.get("title", "") for c in (cards or []) if c.get("title")]
    except Exception:
        return []


# ── 패턴 추출 — 레퍼런스에서 '조합의 재료'를 뽑는다 ──────────
def extract_patterns(country: str) -> dict:
    """레퍼런스 제목들 → prefix/이모지/영문꼬리/감성어/상황어/핵심토큰."""
    co = country.upper()
    titles = all_titles(co)
    try:
        import metadata_engine as ME
        tier = ME.keyword_tiers(co)
        main_kw = set(map(str.lower, tier["main"])); emo_kw = set(map(str.lower, tier["emotion"]))
    except Exception:
        main_kw, emo_kw = set(), set()

    prefixes, emojis, tails, situations, tokens = [], [], [], [], Counter()
    for t in titles:
        m = re.match(r"^\[?Playlist\]?", t, re.I)
        if m:
            prefixes.append(m.group(0))
        emojis += _EMOJI.findall(t)
        if "|" in t:
            tails.append(t.rsplit("|", 1)[1].strip())
        low = t.lower()
        for p in PURPOSE.get(co, []):
            if p.lower() in low:
                situations.append(p)
        for w in re.findall(r"[\w가-힣ぁ-んァ-ヶ一-龥]+", t):
            if len(w) > 1:
                tokens[w] += 1

    def _rank(seq, k=8):
        return [x for x, _ in Counter(seq).most_common(k)]

    common_tokens = [w for w, c in tokens.most_common(30)
                     if w.lower() not in {"playlist", "bgm", "summer", "jazz", "music", "여름", "재즈"}]
    return {
        "country": co,
        "n_titles": len(titles),
        "prefixes": _rank(prefixes) or ["[Playlist]"],
        "emojis": _rank(emojis) or ["🍉"],
        "tails": _dedup(tails) or ["Summer Jazz"],
        "situations": _dedup(situations),
        "common_tokens": common_tokens[:14],
        "emotion_tokens": [w for w in common_tokens if w.lower() in emo_kw][:8],
    }


# ── 첫 단계 제목 조합 — 레퍼런스 재료로 재조합 ──────────────
def combine_titles(country: str, concept: str | None = None, n: int = 5) -> list[str]:
    """레퍼런스 패턴을 재조합해 첫 제목 후보 생성(사장님 방법의 1단계).
    이후 serp_judge 로 검증 → 채택. (concept 이모지/문구는 metadata_engine 재사용)"""
    co = country.upper()
    pat = extract_patterns(co)
    import metadata_engine as ME
    cmap = {"KR": ME.CONCEPTS, "JP": ME.CONCEPTS_JP, "US": ME.CONCEPTS_US}[co]
    c = cmap.get(concept, next(iter(cmap.values())))
    emoji = c.get("emoji", (pat["emojis"] or ["🍉"])[0])

    prefix = pat["prefixes"][0]
    tails = pat["tails"] or ["Summer Jazz"]
    situ = pat["situations"] or PURPOSE.get(co, ["카페"])[:3]
    sep = "・" if co == "JP" else (", " if co == "US" else "·")
    # 감성어(레퍼런스에서 뽑은 실제 표현) — 없으면 concept adj
    emos = pat["emotion_tokens"] or c.get("adj", ["시원한"])

    out = []
    for i in range(n):
        emo = emos[i % len(emos)]
        s = situ[i % max(1, len(situ)):] + situ[:i % max(1, len(situ))]
        s3 = sep.join(_dedup(s)[:3]) if s else sep.join(situ[:3])
        tail = tails[i % len(tails)]
        lead = f"{emo} 여름 재즈" if co == "KR" else (
               f"{emo}夏のジャズ" if co == "JP" else f"{emo} Summer Jazz")
        out.append(f"{prefix} {lead} {emoji} {s3} | {tail}")
    return out


# ── 자기검증 ───────────────────────────────────────────────
if __name__ == "__main__":
    for co in ("KR", "JP", "US"):
        print(f"\n=== {co} (레퍼런스 {len(all_titles(co))}개) ===")
        pat = extract_patterns(co)
        print("  상황어:", pat["situations"])
        print("  이모지:", pat["emojis"], "| 영문꼬리:", pat["tails"][:2])
        print("  조합 후보:")
        for t in combine_titles(co, n=3):
            print("   ", t)

    # 첨부 테스트
    n = add_titles("KR", ["Playlist | 새로 캡처한 청량 수박 재즈 🍉 공부할 때 | Summer Jazz"], source="manual")
    print(f"\n첨부 추가: {n}개, 총 {len(all_titles('KR'))}개")
    assert n == 1
    # 자동수집 (키 없으면 0) — 안전 스킵 확인
    got = collect_auto("KR", ["여름 재즈"], fetch=lambda k, c: [])
    print("자동수집(빈 fetch):", got, "개")
    # 정리
    if STORE.exists():
        STORE.unlink()
    print("\n✅ ref_titles self-test 통과 — 레퍼런스 조합 + 첨부 + 자동수집 훅")
