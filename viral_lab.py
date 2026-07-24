"""viral_lab.py — 🔟 조회수 1만 이상만 분석하는 순수 로직 + 무인 수집 저장소.

이 도구의 단 하나의 원칙:
    ▶ 조회수 1만(MIN_VIEWS) 미만 영상은 분석에도, 생성 근거에도 절대 끼지 못한다.
"검증된 성공(1만+)"만 학습해 새 썸네일·제목을 만들기 위함.

Streamlit 비의존 · 헤드리스 테스트 가능. 무거운 의존(youtube_client/concept_maker)은
필요할 때만 지연 import 하므로, 이 파일 자체는 stdlib + tier_lab 만으로 돈다.

구성:
  - search_hits()   : YouTube 조회수순 검색 → 1만+ 만 남김
  - filter_hits()   : 아무 영상 리스트든 1만+ 강한 필터(+정규화·정렬)
  - analyze_hits()  : 1만+ 집합의 제목 승리공식 + 상위 썸네일(tier_lab 재사용)
  - 수집함 JSON 저장소(viral_hits.json): 무인 cron 이 매일 append(video_id 멱등)
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from typing import Any

import tier_lab as T

# ── 이 도구의 심장: 조회수 하한선 ─────────────────────────────
MIN_VIEWS = 10_000

_HERE = os.path.dirname(os.path.abspath(__file__))
HITS_PATH = os.path.join(_HERE, "viral_hits.json")
_BACKEND = os.path.join(_HERE, "jpshorts", "backend")


# ── 무거운 모듈 지연 import (키/네트워크 필요) ────────────────
def _yc():
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    import youtube_client as yc  # noqa: WPS433
    return yc


def has_youtube_key() -> bool:
    try:
        return _yc().has_key()
    except Exception:  # noqa: BLE001
        return False


# ── 정규화 / 필터 ────────────────────────────────────────────
def _views_of(v: dict) -> int:
    try:
        return int(v.get("views", 0) or 0)
    except (TypeError, ValueError):
        return 0


def normalize(card: dict) -> dict:
    """search_videos/캡처/저장소 어느 출처든 tier_lab·화면 공용 형태로 통일.

    tier_lab 은 `published` 키를 쓰는데 youtube_client 는 `published_at` 을 주므로 맞춘다.
    """
    pub = card.get("published") or card.get("published_at") or ""
    return {
        "video_id": card.get("video_id", ""),
        "title": card.get("title", ""),
        "thumb": card.get("thumb", ""),
        "views": _views_of(card),
        "channel_title": card.get("channel_title", ""),
        "channel_id": card.get("channel_id", ""),
        "published": pub,
        "published_at": pub,
        "is_short": bool(card.get("is_short", False)),
        "multiplier": card.get("multiplier"),
        "subscribers": card.get("subscribers", 0),
        "keywords": card.get("keywords", []) or [],
    }


def filter_hits(videos: list[dict], min_views: int = MIN_VIEWS) -> list[dict]:
    """1만+ 강한 필터. 정규화 후 조회수 내림차순 정렬해 반환."""
    out = [normalize(v) for v in (videos or [])]
    out = [v for v in out if v["views"] >= min_views]
    out.sort(key=lambda v: v["views"], reverse=True)
    return out


# ── 검색(온라인) ─────────────────────────────────────────────
def search_hits(keyword: str, video_type: str = "all", period_days: int = 0,
                max_results: int = 50, lang: str = "",
                min_views: int = MIN_VIEWS) -> dict:
    """YouTube 조회수순 검색 → 1만+ 만 남김.

    반환: {keyword, raw, hits, dropped, demo}
      raw    = 검색으로 받은 전체 개수
      hits   = 1만+ 통과분(정규화·정렬)
      dropped= 1만 미만이라 버린 개수
      demo   = 키가 없어 데모 데이터로 돈 경우 True
    """
    yc = _yc()
    cards = yc.search_videos(keyword, video_type=video_type, order="viewCount",
                             max_results=max_results, period_days=period_days,
                             lang=lang)
    hits = filter_hits(cards, min_views)
    return {
        "keyword": keyword,
        "raw": len(cards),
        "hits": hits,
        "dropped": len(cards) - len(hits),
        "demo": not yc.has_key(),
    }


# ── 분석: 1만+ 집합의 승리 공식 ──────────────────────────────
def analyze_hits(videos: list[dict], min_views: int = MIN_VIEWS) -> dict:
    """1만+ 만 골라 제목 승리공식을 집계(tier_lab 재사용)."""
    hits = filter_hits(videos, min_views)
    agg = T.aggregate_titles(hits)
    return {
        "n": len(hits),
        "dropped": len(videos or []) - len(hits),
        "min_views": min_views,
        "formula": T.formula_line(agg),
        "agg": agg,
        "top": hits,                       # 조회수순 정렬 완료
        "median_views": _median([v["views"] for v in hits]),
    }


def _median(nums: list[int]) -> int:
    if not nums:
        return 0
    s = sorted(nums)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) // 2


# ── 무인 수집함 저장소(JSON, git 추적 — cron 이 커밋해 앱과 공유) ──
def load_store() -> dict:
    if not os.path.exists(HITS_PATH):
        return {"updated": "", "hits": []}
    try:
        with open(HITS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("hits"), list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {"updated": "", "hits": []}


def save_store(store: dict) -> None:
    with open(HITS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def add_hits(new_videos: list[dict], keyword: str = "",
             min_views: int = MIN_VIEWS, cap: int = 2000) -> dict:
    """수집분을 저장소에 병합. video_id 로 멱등(중복 안 쌓임), 최신 정보로 갱신.

    반환: {added, updated_count, total}
    """
    store = load_store()
    by_id: dict[str, dict] = {v.get("video_id"): v for v in store["hits"]
                              if v.get("video_id")}
    today = _dt.date.today().isoformat()
    added = 0
    for v in filter_hits(new_videos, min_views):
        vid = v["video_id"]
        if not vid:
            continue
        rec = {**v, "keyword": keyword, "collected": today}
        if vid not in by_id:
            added += 1
        else:
            rec["collected"] = by_id[vid].get("collected", today)  # 최초 수집일 보존
        by_id[vid] = rec
    merged = sorted(by_id.values(), key=lambda v: v.get("views", 0), reverse=True)[:cap]
    store["hits"] = merged
    store["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    save_store(store)
    return {"added": added, "updated_count": len(merged), "total": len(merged)}


def recent_hits(limit: int = 200) -> list[dict]:
    return load_store()["hits"][:limit]


# ── CLI: 무인 수집(cron/Actions 에서 호출) ───────────────────
def collect_cli(keywords: list[str], video_type: str = "all",
                period_days: int = 180, max_results: int = 50,
                min_views: int = MIN_VIEWS) -> dict:
    """키워드들을 검색해 1만+ 만 저장소에 누적. 결과 요약 dict 반환."""
    total_added = 0
    per_kw: list[dict] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        res = search_hits(kw, video_type=video_type, period_days=period_days,
                          max_results=max_results, min_views=min_views)
        stat = add_hits(res["hits"], keyword=kw, min_views=min_views)
        total_added += stat["added"]
        per_kw.append({"keyword": kw, "raw": res["raw"],
                       "hits": len(res["hits"]), "added": stat["added"],
                       "demo": res["demo"]})
    store = load_store()
    return {"added": total_added, "total": len(store["hits"]),
            "keywords": per_kw, "updated": store["updated"]}


if __name__ == "__main__":  # 간이 자기검증
    demo = [
        {"video_id": "a", "title": "새벽 감성 재즈 플레이리스트 🌙", "views": 52000,
         "published_at": _dt.date.today().isoformat(), "thumb": "http://x/a.jpg"},
        {"video_id": "b", "title": "출근길 시티팝 모음", "views": 9800,
         "published_at": _dt.date.today().isoformat(), "thumb": "http://x/b.jpg"},
        {"video_id": "c", "title": "비 오는 날 카페 보사노바", "views": 130000,
         "published_at": _dt.date.today().isoformat(), "thumb": "http://x/c.jpg"},
    ]
    a = analyze_hits(demo)
    assert a["n"] == 2 and a["dropped"] == 1, a          # 9800짜리는 탈락
    assert "새벽" in a["formula"] or a["agg"]["n"] == 2, a
    print("MIN_VIEWS =", MIN_VIEWS)
    print("통과분:", a["n"], "탈락:", a["dropped"], "| 공식:", a["formula"])
    print("self-test OK")
