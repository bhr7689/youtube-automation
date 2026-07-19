"""🌡️ 키워드 레이더 — '지금 당김을 받는' 키워드 탐지 (실데이터).

사용자 통찰(2026-07-05): 플레이리스트 카테고리에서 7월·여름 키워드가 당김을 받는다
— 시기성 키워드 = 수요의 파도. 이를 감이 아니라 데이터로 찾는다.

세 가지 탐지:
  ① rising_keywords(): 최근(7일) 급등 영상 제목·태그 vs 기준선(30~60일 전) 비교
     → 최근 갑자기 급증한 키워드(상승 배율). publishedAfter/Before 로 정확 측정.
  ② keyword_heat(): 키워드 하나 → 최근 2주 그 키워드 영상들의 중앙값 조회수·VPH
     → "지금 이 키워드 넣으면 당김 받나"를 숫자로.
  ③ seasonal_pack(): 이번 달 시기성 키워드 캘린더(한/일/영) — 후보를 주고
     ②로 검증하는 용도. 캘린더 자체는 결정론(키 불필요).
키 없으면 데모 폴백(7월 여름 시나리오 재현).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import random
import re
import statistics
from collections import Counter

import youtube_client as yc

_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "was",
         "this", "that", "with", "his", "her", "you", "your", "it", "at", "by",
         "shorts", "short", "video", "official", "de", "la", "el", "en", "que",
         "이", "그", "저", "수", "것", "들", "은", "는", "을", "를", "の", "は", "が"}

# 캐시 (쿼터 절약 — 상승 키워드는 시간 단위 갱신이면 충분)
_cache: dict[str, tuple[float, dict]] = {}
_TTL = 3600.0


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[\w']+", text, re.UNICODE)
            if len(w) >= 2 and w.lower() not in _STOP and not w.isdigit()]


def _collect_terms(cards: list[dict]) -> Counter:
    """카드들의 제목 토큰 + 태그 → 빈도(조회수 가중 없이 등장 문서수 기준)."""
    c: Counter = Counter()
    for card in cards:
        seen = set(_tokens(card.get("title", "")))
        seen |= {k.lower() for k in card.get("keywords", [])}
        for t in seen:
            c[t] += 1
    return c


# ── ① 떠오르는 키워드 (최근 vs 기준선) ──────────────────

def rising_keywords(category: str, lang: str = "", top_n: int = 20) -> dict:
    import time as _t
    key = f"rising:{category}:{lang}"
    hit = _cache.get(key)
    if hit and _t.time() - hit[0] < _TTL:
        return hit[1]

    if not yc.has_key():
        data = _demo_rising(category)
        _cache[key] = (_t.time(), data)
        return data

    now = dt.datetime.now(dt.timezone.utc)
    recent_cards = _search_window(category, now - dt.timedelta(days=7), now, lang)
    base_cards = _search_window(category, now - dt.timedelta(days=60),
                                now - dt.timedelta(days=30), lang)
    recent, base = _collect_terms(recent_cards), _collect_terms(base_cards)
    n_r, n_b = max(len(recent_cards), 1), max(len(base_cards), 1)

    rows = []
    for term, rc in recent.items():
        if rc < 2:
            continue
        # 문서 비율 기준 상승 배율(라플라스 보정) — 표본 크기 차이 무관
        r_rate = rc / n_r
        b_rate = base.get(term, 0) / n_b
        rise = (r_rate + 0.01) / (b_rate + 0.01)
        ex = next((c["title"] for c in recent_cards
                   if term in _tokens(c["title"]) or
                   term in {k.lower() for k in c.get("keywords", [])}), "")
        rows.append({"keyword": term, "recent_docs": rc,
                     "baseline_docs": base.get(term, 0),
                     "rise": round(rise, 1), "example": ex[:60]})
    rows.sort(key=lambda r: -r["rise"])
    data = {"category": category, "rising": rows[:top_n],
            "recent_sample": n_r, "baseline_sample": n_b, "demo": False,
            "note": "상승 배율 = 최근 7일 등장률 ÷ 30~60일 전 등장률 (실측)"}
    _cache[key] = (_t.time(), data)
    return data


def _search_window(query: str, after: dt.datetime, before: dt.datetime,
                   lang: str) -> list[dict]:
    """기간 창(after~before) 인기 영상 카드 수집 — publishedBefore 지원."""
    yt = yc._yt()
    params = dict(part="id", q=query, type="video", order="viewCount",
                  maxResults=50,
                  publishedAfter=after.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  publishedBefore=before.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if lang and lang in yc.LANG_REGION:
        params["relevanceLanguage"] = lang
        params["regionCode"] = yc.LANG_REGION[lang]
    try:
        resp = yt.search().list(**params).execute()
        ids = [it["id"]["videoId"] for it in resp.get("items", [])
               if it.get("id", {}).get("videoId")]
    except Exception:
        return []
    if not ids:
        return []
    cards = []
    try:
        vresp = yt.videos().list(part="snippet,statistics",
                                 id=",".join(ids[:50])).execute()
        for v in vresp.get("items", []):
            sn = v["snippet"]
            cards.append({"title": sn["title"],
                          "keywords": sn.get("tags", []) or [],
                          "views": int(v.get("statistics", {}).get("viewCount", 0))})
    except Exception:
        pass
    return cards


# ── ② 키워드 히트 체크 ─────────────────────────────────

def keyword_heat(keyword: str, days: int = 14, lang: str = "") -> dict:
    import time as _t
    key = f"heat:{keyword}:{days}:{lang}"
    hit = _cache.get(key)
    if hit and _t.time() - hit[0] < _TTL:
        return hit[1]

    if not yc.has_key():
        data = _demo_heat(keyword)
        _cache[key] = (_t.time(), data)
        return data

    cards = yc.search_videos(keyword, video_type="all", order="viewCount",
                             max_results=30, period_days=days, lang=lang)
    if not cards:
        return {"keyword": keyword, "video_count": 0, "demo": False,
                "note": "최근 기간 표본 없음 — 수요가 약하거나 검색어가 좁아요."}
    views = [c["views"] for c in cards]
    vph = [c.get("vph") or 0 for c in cards]
    mults = [c["multiplier"] for c in cards if c.get("multiplier")]
    data = {
        "keyword": keyword, "days": days, "video_count": len(cards),
        "median_views": int(statistics.median(views)),
        "median_vph": round(statistics.median(vph), 1) if vph else 0,
        "top_multiplier": max(mults) if mults else None,
        "samples": [{"title": c["title"][:60], "views": c["views"]}
                    for c in cards[:5]],
        "demo": False,
        "note": f"최근 {days}일 검색 상위 표본 기준 실측 (중앙값=이상치에 강함)",
    }
    _cache[key] = (_t.time(), data)
    return data


# ── ③ 계절 키워드 캘린더 (결정론 — 키 불필요) ───────────

SEASONAL = {
    1: {"ko": ["새해", "1월", "겨울", "새해 다짐", "신년운세"],
        "ja": ["新年", "正月", "冬", "初詣"], "en": ["new year", "january", "winter"]},
    2: {"ko": ["발렌타인", "2월", "겨울끝", "졸업"],
        "ja": ["バレンタイン", "受験", "卒業"], "en": ["valentine", "february"]},
    3: {"ko": ["봄", "3월", "벚꽃", "개학", "새학기"],
        "ja": ["春", "桜", "卒業式", "新生活"], "en": ["spring", "march", "cherry blossom"]},
    4: {"ko": ["봄나들이", "4월", "벚꽃엔딩", "피크닉"],
        "ja": ["お花見", "新学期", "春風"], "en": ["april", "picnic", "spring vibes"]},
    5: {"ko": ["5월", "가정의달", "어버이날", "초여름"],
        "ja": ["ゴールデンウィーク", "母の日", "初夏"], "en": ["may", "mothers day"]},
    6: {"ko": ["초여름", "6월", "장마", "여름준비"],
        "ja": ["梅雨", "初夏", "6月"], "en": ["june", "early summer", "rainy day"]},
    7: {"ko": ["여름", "7월", "휴가", "바캉스", "여름밤", "열대야", "장마"],
        "ja": ["夏", "7月", "夏休み", "花火", "海"], "en": ["summer", "july", "vacation", "summer night"]},
    8: {"ko": ["여름휴가", "8월", "바다", "한여름", "피서"],
        "ja": ["夏祭り", "お盆", "花火大会", "真夏"], "en": ["august", "beach", "midsummer"]},
    9: {"ko": ["가을", "9월", "초가을", "환절기", "추석"],
        "ja": ["秋", "9月", "月見"], "en": ["september", "autumn", "fall"]},
    10: {"ko": ["가을감성", "10월", "단풍", "할로윈"],
         "ja": ["紅葉", "ハロウィン", "秋の夜"], "en": ["october", "halloween", "cozy fall"]},
    11: {"ko": ["늦가을", "11월", "쌀쌀", "수능", "첫눈"],
         "ja": ["晩秋", "紅葉狩り", "11月"], "en": ["november", "late autumn"]},
    12: {"ko": ["겨울", "12월", "크리스마스", "연말", "캐롤"],
         "ja": ["クリスマス", "年末", "冬", "雪"], "en": ["december", "christmas", "winter", "year end"]},
}


def seasonal_pack(month: int | None = None) -> dict:
    m = month or dt.datetime.now().month
    nxt = m % 12 + 1
    return {
        "month": m,
        "this_month": SEASONAL[m],
        "next_month_preview": SEASONAL[nxt],
        "note": "시기성 키워드는 수요가 오르기 '직전'에 선점하는 게 유리 — "
                "다음 달 키워드를 월말에 미리 심으세요. ②히트 체크로 검증 후 사용.",
    }


# ── 데모 폴백 (7월 여름 시나리오 재현) ──────────────────

def _demo_rising(category: str) -> dict:
    rows = [
        ("여름", 34, 3, 8.4, f"여름밤에 듣는 {category} 모음"),
        ("7월", 21, 1, 7.9, f"7월의 {category} — 밤바람과 함께"),
        ("여름밤", 18, 2, 5.6, f"여름밤 감성 {category}"),
        ("휴가", 14, 2, 4.4, "휴가철에 꼭 듣는 노래"),
        ("바캉스", 9, 1, 3.7, "바캉스 무드 플레이리스트"),
        ("열대야", 8, 1, 3.4, "열대야를 식혀줄 새벽 감성"),
        ("summer", 15, 4, 2.9, "summer night drive playlist"),
        ("장마", 7, 2, 2.6, "장마철 빗소리와 함께"),
    ]
    return {"category": category, "demo": True,
            "recent_sample": 50, "baseline_sample": 50,
            "rising": [{"keyword": k, "recent_docs": r, "baseline_docs": b,
                        "rise": rise, "example": ex}
                       for k, r, b, rise, ex in rows],
            "note": "데모 — 키를 넣으면 최근7일 vs 30~60일전 실측 비교로 바뀝니다"}


def _demo_heat(keyword: str) -> dict:
    rnd = random.Random(int(hashlib.md5(keyword.encode()).hexdigest()[:8], 16))
    season_boost = 3.0 if any(s in keyword for s in
                              ("여름", "7월", "summer", "夏", "휴가")) else 1.0
    mv = int(rnd.uniform(80_000, 900_000) * season_boost)
    return {"keyword": keyword, "days": 14, "video_count": rnd.randint(18, 30),
            "median_views": mv, "median_vph": round(mv / rnd.uniform(100, 300), 1),
            "top_multiplier": round(rnd.uniform(3, 40) * season_boost ** 0.5, 1),
            "samples": [{"title": f"{keyword} 감성 모음 {i+1}", "views": int(mv * rnd.uniform(0.5, 3))}
                        for i in range(3)],
            "demo": True, "note": "데모 — 키를 넣으면 최근 표본 실측으로 바뀝니다"}
