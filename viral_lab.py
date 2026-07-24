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


# ── 톤 프리셋 (병맛부터 감성까지) — 생성 시 톤 보존 + 클릭 심리 주입 ──
# (label, tone_line, punchy) — tone_line 은 concept_maker.build_vibe_notes 에 주입
VIBE_TONES: dict[str, tuple[str, str, bool]] = {
    "auto": ("🪞 레퍼런스 그대로",
             "톤 지시: 레퍼런스의 결을 있는 그대로 미러링하라. 별도 강제 톤 없이, 위 표본이 "
             "감성이면 감성·병맛이면 병맛·충격이면 충격으로 따라가라.", False),
    "byungmat": ("🤪 병맛 살려",
                 "톤 지시: 이 세트는 '병맛·날것·과장·유머' 결을 최대한 살린다. 어색함·엉뚱함·"
                 "B급 감성을 두려워 말고 밀어붙여라. 절대 예쁘게·고급스럽게 순화하지 마라.", True),
    "shock": ("😱 더 자극적으로",
              "톤 지시: 이 세트는 '충격·자극·반전' 결을 극대화한다. 시선을 강제로 붙잡는 "
              "이미지·카피로, 안 누르고는 못 배기게 만들어라.", True),
    "gamsung": ("🌙 감성 유지",
                "톤 지시: 이 세트는 감성·무드 결을 유지하되, 제목·썸네일에 클릭 심리 트리거는 "
                "확실히 심는다(감성인데 궁금해서 누르게).", False),
}
VIBE_INTENSITY: dict[str, str] = {
    "약": "강도=약: 은은하게, 과함 금지. 트리거는 넣되 티 안 나게.",
    "중": "강도=중: 균형 있게. 눈에 띄되 과장은 통제.",
    "강": "강도=강: 최대치로 밀어붙여라. 밋밋하면 실패다.",
}


def vibe_brief(tone: str = "auto", intensity: str = "중") -> dict:
    """톤·강도 선택 → 생성 프롬프트 주입용 브리프.

    반환: {tone_line, intensity_line, punchy, label}
      - tone_line/intensity_line → concept_maker.build_vibe_notes 에 넣음
      - punchy → generate_report(punchy_overlay=) : 썸네일 문구를 밈/클릭베이트 스타일로
    """
    label, tone_line, punchy = VIBE_TONES.get(tone, VIBE_TONES["auto"])
    intensity_line = VIBE_INTENSITY.get(intensity, VIBE_INTENSITY["중"])
    if intensity == "강":
        punchy = True
    return {"tone_line": tone_line, "intensity_line": intensity_line,
            "punchy": punchy, "label": label}


def _median(nums: list[int]) -> int:
    if not nums:
        return 0
    s = sorted(nums)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) // 2


# ── 🧩 같은 풍끼리 묶기 (스타일 클러스터링, 헤드리스·무료) ──────
def _style_signature(v: dict) -> tuple[str, str]:
    """제목에서 (테마, 문형) 시그니처 추출 → 같은 풍끼리 묶는 키.

    테마 = 장르어 > 상황어 > 감각어 순 첫 히트(없으면 '기타').
    문형 = 질문형 / 감탄형 / 이모지형 / 서술형.
    """
    a = T.analyze_title(v.get("title", ""))
    if a["genre"]:
        theme = a["genre"][0]
    elif a["situation"]:
        theme = a["situation"][0]
    elif a["sensory"]:
        theme = a["sensory"][0]
    else:
        theme = "기타"
    # 이모지 유무는 '다른 풍'이 아니라 갈림 원인 후보 → 문형에서 제외(같이 묶이게)
    if a["question"]:
        form = "질문형"
    elif a["exclaim"]:
        form = "감탄형"
    else:
        form = "서술형"
    return theme, form


def cluster_by_style(videos: list[dict], min_views: int = MIN_VIEWS) -> list[dict]:
    """1만+ 를 같은 풍(테마·문형)끼리 묶는다. 큰 묶음(격차 큰 것 우선)부터 정렬.

    각 묶음: {label, theme, form, formula, size, videos(조회수순),
             top, bottom, views_max, views_min, spread(최대/최소 배수)}
    """
    hits = filter_hits(videos, min_views)
    groups: dict[tuple[str, str], list[dict]] = {}
    for v in hits:
        groups.setdefault(_style_signature(v), []).append(v)

    clusters = []
    for (theme, form), vids in groups.items():
        vids.sort(key=lambda x: x["views"], reverse=True)
        agg = T.aggregate_titles(vids)
        vmax = vids[0]["views"]
        vmin = vids[-1]["views"]
        clusters.append({
            "label": f"{theme} · {form}",
            "theme": theme, "form": form,
            "formula": T.formula_line(agg),
            "size": len(vids),
            "videos": vids,
            "top": vids[0],
            "bottom": vids[-1],
            "views_max": vmax,
            "views_min": vmin,
            "spread": round(vmax / vmin, 1) if vmin else None,
        })
    # 여러 개 + 격차 큰 묶음을 위로(분석 가치 순)
    clusters.sort(key=lambda c: (c["size"] >= 2, c["spread"] or 0, c["size"]),
                  reverse=True)
    return clusters


# ── 🔬 같은 풍인데 조회수가 갈리는 이유 — 정량 유추(무료) ──────
def _days_since(iso: str) -> int | None:
    return T.days_since((iso or "")[:10])


def diff_hypotheses(cluster: dict) -> list[str]:
    """묶음 안에서 상위(고조회) vs 하위(저조회)를 비교해 정량 원인 가설 생성.

    구독자/채널평균대비 배수/신선도(경과일)/제목 요소 차이를 근거로 유추.
    시각 원인(색상·헤어·배경 등)은 별도 👁Vision(concept_maker.explain_view_gap_vision).
    """
    vids = cluster.get("videos", [])
    if len(vids) < 2:
        return ["표본이 1개뿐이라 갈림 비교가 어렵습니다. 같은 풍 영상이 2개 이상 모이면 원인을 유추합니다."]
    top, bot = vids[0], vids[-1]
    out: list[str] = []

    # 1) 구독자 수 차이 — 같은 풍이어도 구독 기반이 크면 초기 노출이 유리
    ts, bs = int(top.get("subscribers", 0) or 0), int(bot.get("subscribers", 0) or 0)
    if ts and bs:
        if ts >= bs * 2:
            out.append(f"👥 구독자 격차: 상위 채널 {ts:,}명 vs 하위 {bs:,}명 — "
                       "구독 기반이 큰 쪽이 초기 노출·추천에서 유리했을 가능성이 큽니다.")
        elif bs >= ts * 2:
            out.append(f"👥 역전 신호: 하위 영상 채널({bs:,}명)이 구독자가 더 많은데도 조회수가 낮음 "
                       f"→ 구독자 탓이 아니라 **썸네일·제목·주제** 자체의 흡인력 차이일 확률이 높습니다.")

    # 2) 채널 평균 대비 배수 — 자기 채널에서 얼마나 튀었나(구독자 규모 보정)
    tm, bm = top.get("multiplier"), bot.get("multiplier")
    if tm and bm:
        if tm >= bm * 1.5:
            out.append(f"🚀 자기채널 대비 배수: 상위 {tm}배 vs 하위 {bm}배 — 상위 썸네일·제목이 "
                       "그 채널의 평소 성적마저 뛰어넘음(구독자 규모와 무관한 콘텐츠 자체의 힘).")

    # 3) 신선도 — 오래된 영상은 조회수를 오래 쌓았을 수도(반대로 최신인데 높으면 진짜 강함)
    td, bd = _days_since(top.get("published", "")), _days_since(bot.get("published", ""))
    if td is not None and bd is not None:
        if td > bd * 1.5 and bd >= 0:
            out.append(f"🕰️ 노출 기간: 상위 영상이 {td}일로 하위({bd}일)보다 오래 노출됨 — "
                       "격차의 일부는 '쌓인 시간' 때문일 수 있어 하루 평균으로도 봐야 합니다.")
        elif bd > td * 1.5 and td >= 0:
            out.append(f"🔥 최신 폭발: 상위 영상이 {td}일밖에 안 됐는데 하위({bd}일)를 이미 앞섬 "
                       "→ 최근 트렌드·후킹이 제대로 먹힌 강한 신호.")

    # 4) 제목 요소 차이 — 상위엔 있고 하위엔 없는 것
    at, ab = T.analyze_title(top.get("title", "")), T.analyze_title(bot.get("title", ""))
    gained = []
    if at["emojis"] and not ab["emojis"]:
        gained.append("이모지")
    only_sit = set(at["situation"]) - set(ab["situation"])
    only_sen = set(at["sensory"]) - set(ab["sensory"])
    if only_sit:
        gained.append("상황어(" + "·".join(list(only_sit)[:2]) + ")")
    if only_sen:
        gained.append("감각어(" + "·".join(list(only_sen)[:2]) + ")")
    if at["question"] and not ab["question"]:
        gained.append("질문형 후킹")
    if gained:
        out.append("📝 제목 차이: 상위 제목엔 있고 하위엔 없는 요소 — " + ", ".join(gained) +
                   ". 이 후킹 요소가 클릭률을 갈랐을 수 있습니다.")

    # 5) 시각 원인은 이미지로만 판별 가능 — 안내
    out.append("🎨 색상·인물 헤어스타일/헤어색·배경·표정·텍스트 등 **시각 원인**은 아래 "
               "'👁 GPT 로 시각 원인 유추' 버튼으로 상·하위 썸네일을 직접 비교해 확인하세요.")
    return out


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

    # 클러스터 + 갈림 유추
    demo2 = demo + [{"video_id": "d", "title": "새벽 감성 재즈 라디오", "views": 11000,
                     "subscribers": 3000, "multiplier": 1.0,
                     "published_at": _dt.date.today().isoformat(), "thumb": "http://x/d.jpg"}]
    cl = cluster_by_style(demo2)
    jazz = [c for c in cl if c["theme"] == "재즈" and c["size"] >= 2]
    assert jazz, cl                                       # 재즈 2개가 한 묶음
    hyp = diff_hypotheses(jazz[0])
    assert any(("이모지" in h or "구독자" in h) for h in hyp), hyp
    print("클러스터:", [(c["label"], c["size"]) for c in cl])
    print("self-test OK")
