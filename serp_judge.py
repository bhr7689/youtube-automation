"""🧠 SERP 판정 — 후보 제목의 '시크릿 검색 상위결과'가 고조회 풀인지 판정.

엔진의 심장(A-9). 제목 생성은 후보일 뿐, **채택은 SERP가 결정한다.**

핵심 질문(사장님 본질 목표):
  "내 제목으로 (시크릿 모드) 검색했을 때 상위에 고조회 영상이 뜨는가,
   아니면 신생·저조회 채널 영상만 뜨는가?"
  → 고조회·강채널이 상위면 채택(그 풀에 묶임), 신생 저조회가 상위면 탈락(약한 검색어).

입력: serp_probe.py(Playwright 시크릿) 또는 YouTube API가 모은 상위N 결과 리스트.
      각 항목 = {title, views, published_at(ISO), subscribers, channel_age_months}
출력: fit_score(0~100) · verdict(adopt/regenerate) · 지표 · 사람이 읽는 사유.

순수 로직 — 네트워크·키 불필요. 데모/목 데이터로 바로 검증 가능.
"""
from __future__ import annotations
import datetime as _dt
import re
from statistics import median

# ── 임계값 (사장님 채널 규모에 맞게 조정 가능) ──────────────
STRONG_SUBS = 50_000       # 이 이상이면 '강채널'
NEW_LOW_SUBS = 5_000       # 이 미만 + 저조회면 '신생 저조회'
NEW_LOW_VIEWS = 10_000     # 저조회 기준
GOOD_MEDIAN_VIEWS = 100_000  # 상위 중앙값 조회수 '충분' 기준
FIT_ADOPT = 55             # 이 점수 이상이면 채택


def _days_since(iso: str) -> float:
    try:
        t = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo:
            t = t.replace(tzinfo=None)
        return max(0.5, (_dt.datetime.utcnow() - t).total_seconds() / 86400)
    except Exception:
        return 90.0


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w가-힣ぁ-んァ-ヶ一-龥]+", str(text).lower()) if len(w) > 1}


def judge(results: list[dict], my_keywords: list[str] | None = None) -> dict:
    """상위N 검색결과 → Fit 점수 + 채택/탈락 판정."""
    n = len(results)
    if n == 0:
        return {"fit_score": 0, "verdict": "regenerate", "n": 0,
                "reasons": ["검색 결과가 없음 — 너무 좁은/이상한 제목일 수 있음"],
                "metrics": {}}

    views = [max(0, int(r.get("views") or 0)) for r in results]
    med_views = median(views)
    velocities = [v / _days_since(r.get("published_at", "")) for v, r in zip(views, results)]
    med_velocity = median(velocities)

    strong = sum(1 for r in results if (r.get("subscribers") or 0) >= STRONG_SUBS)
    strong_ratio = strong / n

    new_low = sum(1 for r, v in zip(results, views)
                  if (r.get("subscribers") or 0) < NEW_LOW_SUBS and v < NEW_LOW_VIEWS)
    new_low_ratio = new_low / n

    # 내 키워드가 상위 제목에 얼마나 재등장하나(= 내가 그 풀 소속인가)
    mine = set()
    for k in (my_keywords or []):
        mine |= _tokens(k)
    if mine:
        hits = sum(1 for r in results if _tokens(r.get("title", "")) & mine)
        keyword_reappear = hits / n
    else:
        keyword_reappear = 0.0

    # ── 정규화(0~1) ──
    f_views = min(1.0, med_views / GOOD_MEDIAN_VIEWS)
    f_velo = min(1.0, med_velocity / 3000)          # 3천 조회/일이면 만점
    f_strong = strong_ratio
    f_kw = keyword_reappear

    # ── Fit 점수 (신생저조회 점유율이 킬러 음수가중) ──
    raw = (f_views * 0.30 + f_velo * 0.25 + f_strong * 0.20 + f_kw * 0.15
           - new_low_ratio * 0.30)
    fit = round(max(0.0, min(1.0, raw)) * 100)

    verdict = "adopt" if fit >= FIT_ADOPT and new_low_ratio < 0.4 else "regenerate"

    reasons = []
    if new_low_ratio >= 0.4:
        reasons.append(f"🚫 상위 {n}개 중 {new_low}개가 신생·저조회 채널({new_low_ratio:.0%}) "
                       "— 약한 검색어라 이 제목은 고조회 풀에 못 묶임 → 재작성")
    if med_views >= GOOD_MEDIAN_VIEWS:
        reasons.append(f"✅ 상위 중앙값 조회수 {med_views:,.0f} — 고조회 풀")
    elif med_views < NEW_LOW_VIEWS:
        reasons.append(f"⚠️ 상위 중앙값 조회수 {med_views:,.0f} — 규모가 약함")
    if strong_ratio >= 0.3:
        reasons.append(f"✅ 강채널 비율 {strong_ratio:.0%}(구독 {STRONG_SUBS:,}+) — 대형영상 연관추천 유리")
    if my_keywords:
        reasons.append(f"🔑 내 키워드 상위 제목 재등장 {keyword_reappear:.0%}")
    if not reasons:
        reasons.append("판정 근거 부족 — 상위 결과가 애매함")

    return {
        "fit_score": fit,
        "verdict": verdict,
        "n": n,
        "metrics": {
            "median_views": round(med_views),
            "median_velocity_per_day": round(med_velocity),
            "strong_channel_ratio": round(strong_ratio, 2),
            "new_low_ratio": round(new_low_ratio, 2),
            "keyword_reappear": round(keyword_reappear, 2),
        },
        "reasons": reasons,
    }


def weakest_keywords(title: str, results: list[dict]) -> list[str]:
    """탈락 시: 상위 결과에 거의 안 나오는(= 저조회를 끌어온) 내 키워드 후보를 지목.
    이 키워드를 교체·강화해 재생성하면 됨."""
    toks = [w for w in re.findall(r"[\w가-힣ぁ-んァ-ヶ一-龥]+", title) if len(w) > 1]
    pool = set()
    for r in results:
        pool |= _tokens(r.get("title", ""))
    return [t for t in toks if t.lower() not in pool][:6]


# ── 자기검증 (데모: 고조회 SERP vs 신생 저조회 SERP) ──────────
if __name__ == "__main__":
    good = [  # 고조회·강채널이 상위 → 채택돼야
        {"title": "여름 재즈 카페 BGM", "views": 1_200_000, "published_at": "2025-06-01",
         "subscribers": 300_000, "channel_age_months": 40},
        {"title": "공부할 때 듣는 재즈", "views": 800_000, "published_at": "2025-05-20",
         "subscribers": 150_000, "channel_age_months": 30},
        {"title": "청량한 여름 플레이리스트", "views": 450_000, "published_at": "2025-06-10",
         "subscribers": 90_000, "channel_age_months": 24},
        {"title": "카페 매장 BGM 재즈", "views": 220_000, "published_at": "2025-06-15",
         "subscribers": 60_000, "channel_age_months": 18},
    ]
    bad = [  # 신생 저조회만 상위 → 재작성돼야 (사장님이 겪은 문제)
        {"title": "나만의 감성 수박 재즈 이야기", "views": 320, "published_at": "2025-07-28",
         "subscribers": 45, "channel_age_months": 2},
        {"title": "초보 유튜버 첫 플리", "views": 1_100, "published_at": "2025-07-25",
         "subscribers": 210, "channel_age_months": 3},
        {"title": "브이로그 배경음악 모음", "views": 800, "published_at": "2025-07-30",
         "subscribers": 90, "channel_age_months": 1},
    ]
    mk = ["여름 재즈", "카페 BGM", "공부할 때 듣는 음악"]
    g = judge(good, mk); b = judge(bad, mk)
    print("── 고조회 SERP ──"); print(g["verdict"], g["fit_score"]); [print(" ", r) for r in g["reasons"]]
    print("\n── 신생 저조회 SERP ──"); print(b["verdict"], b["fit_score"]); [print(" ", r) for r in b["reasons"]]
    assert g["verdict"] == "adopt", "고조회는 채택돼야"
    assert b["verdict"] == "regenerate", "신생 저조회는 재작성돼야"
    print("\n약한 키워드 지목:", weakest_keywords("나만의 감성 수박 재즈 이야기", bad))
    print("\n✅ serp_judge self-test 통과")
