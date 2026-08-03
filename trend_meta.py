"""📡 트렌드 적응 — 지금 뜨는 '컨셉 축'을 감지해 엔진에 먹인다.

기획 의도(사장님 질문의 답): 알고리즘은 시기별로 변한다.
  때로는 과일(수박), 때로는 카페 분위기, 때로는 비/난로가 뜬다.
  → 컨셉을 **하드코딩하지 않는다.** 현재 상위 영상에서 뜨는 테마·키워드를 읽어 갱신한다.

원칙: **공식(밀도형 제목·3계층·SERP 판정)은 고정, 재료(어떤 테마가 hot인지)는 유동.**

3가지 신호:
  ① 트렌드 하베스트 — 상위 제목에서 반복 테마 추출 (extract_hot_themes)
  ② SERP 판정 = 적응 신호 — 테마가 식으면(신생저조회만) 다른 테마로 교체 (serp_judge 연동)
  ③ 계절 프라이어 — 라이브 데이터 없을 때만 쓰는 약한 폴백 (SEASONAL_PRIOR)

저장: trend_meta.json (seed + 자동갱신 — nation_prompts 방식). cron 이 갱신·커밋해 앱과 공유.
순수 로직 — 키/네트워크 없이 데모·검증 가능.
"""
from __future__ import annotations
import datetime as _dt
import json
import re
from collections import Counter
from pathlib import Path

STORE = Path(__file__).with_name("trend_meta.json")

# ── 계절 프라이어(폴백만) — 월 → 우선 테마축 ──────────────
SEASONAL_PRIOR = {
    1: ["난로", "새벽", "카페"], 2: ["카페", "새벽"], 3: ["카페", "벚꽃"],
    4: ["벚꽃", "카페"], 5: ["레몬", "카페"], 6: ["수박", "바다", "레몬"],
    7: ["수박", "바다"], 8: ["수박", "메론소다", "바다"], 9: ["복숭아", "카페"],
    10: ["카페", "비"], 11: ["카페", "비", "난로"], 12: ["난로", "새벽", "카페"],
}

# ── 테마 감지 사전 — 상위 제목에 이 단어가 자주 나오면 그 테마가 hot ──
THEME_KEYWORDS = {
    "수박": ["수박", "watermelon", "スイカ"],
    "레몬": ["레몬", "lemon", "レモン"],
    "복숭아": ["복숭아", "peach", "桃"],
    "메론소다": ["메론소다", "melon soda", "メロンソーダ"],
    "바다": ["바다", "ocean", "beach", "海", "seaside"],
    "카페": ["카페", "cafe", "café", "カフェ", "coffee"],
    "비": ["비 오는", "rain", "rainy", "雨"],
    "새벽": ["새벽", "late night", "midnight", "dawn", "夜", "深夜"],
    "난로": ["난로", "벽난로", "fireplace", "暖炉", "cozy fire"],
    "벚꽃": ["벚꽃", "cherry blossom", "桜", "sakura"],
}

DEFAULT_THEME = "수박"


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fresh(iso: str, days: int = 3) -> bool:
    try:
        t = _dt.datetime.fromisoformat(iso)
        return (_dt.datetime.utcnow() - t).days < days
    except Exception:
        return False


# ── ① 트렌드 하베스트 — 상위 제목에서 뜨는 테마 추출 ──────────
def extract_hot_themes(top_titles: list[str], top_n: int = 3) -> list[dict]:
    """현재 상위 영상 제목들 → 어떤 테마가 뜨고 있나(빈도순)."""
    text = " ".join(top_titles).lower()
    scores = Counter()
    for theme, kws in THEME_KEYWORDS.items():
        for kw in kws:
            scores[theme] += len(re.findall(re.escape(kw.lower()), text))
    ranked = [{"theme": t, "hits": c} for t, c in scores.most_common() if c > 0]
    return ranked[:top_n]


def extract_rising_terms(top_titles: list[str], top_n: int = 12) -> list[str]:
    """상위 제목에서 자주 나오는 일반 키워드(테마 사전 밖) → 3계층 감성/상황 보강용."""
    stop = {"playlist", "플리", "bgm", "music", "the", "for", "and", "jazz",
            "|", "summer", "여름", "재즈", "音楽", "プレイリスト"}
    toks = re.findall(r"[\w가-힣ぁ-んァ-ヶ一-龥]+", " ".join(top_titles).lower())
    c = Counter(t for t in toks if len(t) > 1 and t not in stop)
    return [w for w, _ in c.most_common(top_n)]


# ── 갱신 & 조회 ────────────────────────────────────────────
def refresh(country: str, top_titles: list[str], rising_keywords: list[str] | None = None) -> dict:
    """상위 제목(라이브/캡처)으로 그 나라의 hot 테마·키워드 갱신·저장."""
    data = _load()
    hot = extract_hot_themes(top_titles)
    entry = {
        "updated": _dt.datetime.utcnow().isoformat(timespec="seconds"),
        "hot_themes": [h["theme"] for h in hot] or [DEFAULT_THEME],
        "hot_detail": hot,
        "rising_terms": _dedup((rising_keywords or []) + extract_rising_terms(top_titles)),
    }
    data[country.upper()] = entry
    _save(data)
    return entry


def current_themes(country: str = "KR", month: int | None = None) -> list[str]:
    """지금 밀어야 할 테마축. 저장값(신선)이 있으면 그것, 없으면 계절 프라이어."""
    data = _load().get(country.upper(), {})
    if data and _fresh(data.get("updated", "")) and data.get("hot_themes"):
        return data["hot_themes"]
    m = month or _dt.datetime.utcnow().month
    return SEASONAL_PRIOR.get(m, [DEFAULT_THEME])


def current_theme(country: str = "KR", month: int | None = None) -> str:
    return current_themes(country, month)[0]


def rising_boost(country: str = "KR") -> list[str]:
    """이 시기 뜨는 실검색 키워드(3계층 감성/상황에 앞쪽으로 주입)."""
    data = _load().get(country.upper(), {})
    if data and _fresh(data.get("updated", "")):
        return data.get("rising_terms", [])
    return []


def theme_stale_signal(serp_verdict: str) -> bool:
    """② SERP 판정이 'regenerate'면 = 이 테마가 식음 → 다른 뜨는 테마로 교체 신호."""
    return serp_verdict == "regenerate"


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out


# ── 자기검증 (키·네트워크 불필요) ──────────────────────────
if __name__ == "__main__":
    # 여름: 과일이 상위를 도배 → 수박 감지
    summer_top = ["시원한 수박 여름 재즈 카페 BGM", "수박 한 입 청량한 재즈",
                  "watermelon summer jazz playlist", "여름 바다 재즈 플리"]
    print("여름 상위제목 →", extract_hot_themes(summer_top))
    assert extract_hot_themes(summer_top)[0]["theme"] == "수박"

    # 가을: 카페·비가 상위를 도배 → 카페 감지 (테마 이동!)
    autumn_top = ["비 오는 날 카페 재즈", "따뜻한 카페 BGM 재즈", "cozy cafe jazz rain",
                  "카페에서 듣는 잔잔한 재즈", "가을 카페 감성 플리"]
    print("가을 상위제목 →", extract_hot_themes(autumn_top))
    assert extract_hot_themes(autumn_top)[0]["theme"] == "카페", "카페로 이동 감지돼야"

    e = refresh("KR", autumn_top, rising_keywords=["가을 감성", "빗소리"])
    print("\n갱신됨:", e["hot_themes"], "| rising:", e["rising_terms"][:6])
    print("current_theme(KR) =", current_theme("KR"))
    assert current_theme("KR") == "카페"

    # 계절 프라이어 폴백 (저장 없을 때)
    print("\n계절 프라이어 7월 →", SEASONAL_PRIOR[7], "/ 11월 →", SEASONAL_PRIOR[11])
    print("SERP 식음 신호:", theme_stale_signal("regenerate"))

    # 정리 (테스트 흔적 삭제)
    if STORE.exists():
        STORE.unlink()
    print("\n✅ trend_meta self-test 통과 — 과일↔카페 테마 이동 자동 감지")
