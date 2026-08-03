"""🏛️ 자산 원장(Asset Ledger) — 우리가 검증한 데이터를 '우리만의 자산'으로 축적.

사장님 전략: 데이터를 계속 추적해 우리만의 자산으로 만든다.
  유튜브 알고리즘 생태계를 니치×나라 단위로 하나씩 점령해 나간다.

복리 구조(해자):
  ① 제목 생성(레퍼런스 조합) → ② SERP 검증 → ③ 채택되면 이 원장에 '검증 자산'으로 기록
  → ④ 다음 생성 때 이 검증 자산이 외부 레퍼런스보다 먼저 재료로 재투입 (우리 것이 더 강함)
  → 니치별로 '점령' 축적 → 점령 지도로 진척 가시화.

저장: asset_ledger.json (git 추적 — cron/앱/PC 가 함께 쌓아 공유하는 공동 자산).
순수 로직 — 키/네트워크 불필요.
"""
from __future__ import annotations
import datetime as _dt
import json
from collections import defaultdict
from pathlib import Path

STORE = Path(__file__).with_name("asset_ledger.json")

# 점령 판정 임계
CONQUER_MIN_PROVEN = 2     # 검증 자산 N개 이상
CONQUER_MIN_FIT = 60       # 평균 SERP Fit
PROVEN_MIN_FIT = 55        # 이 이상이면 '검증 자산'


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"events": []}


def _save(d: dict) -> None:
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def record(country: str, niche: str, title: str, fit: float | None = None,
           verdict: str = "", adopted: bool = False, meta: dict | None = None) -> dict:
    """제목 시도/채택을 자산으로 기록. adopted=True + fit≥임계 = 검증 자산."""
    d = _load()
    ev = {
        "ts": _dt.datetime.utcnow().isoformat(timespec="seconds"),
        "country": country.upper(), "niche": niche, "title": title,
        "fit": fit, "verdict": verdict, "adopted": bool(adopted),
        "proven": bool(adopted and (fit or 0) >= PROVEN_MIN_FIT),
        "meta": meta or {},
    }
    d["events"].append(ev)
    _save(d)
    return ev


def winners(country: str, niche: str | None = None, limit: int = 20) -> list[str]:
    """우리 검증 자산(채택·고Fit) 제목 — 다음 생성의 1순위 재료로 재투입."""
    co = country.upper()
    evs = [e for e in _load()["events"]
           if e["country"] == co and e.get("proven")
           and (niche is None or e["niche"] == niche)]
    evs.sort(key=lambda e: (e.get("fit") or 0), reverse=True)
    seen, out = set(), []
    for e in evs:
        if e["title"] not in seen:
            seen.add(e["title"]); out.append(e["title"])
        if len(out) >= limit:
            break
    return out


def territory_map(targets: dict | None = None) -> list[dict]:
    """점령 지도 — (나라×니치)별 점령/개척중/미개척 + 검증자산·평균Fit."""
    agg = defaultdict(lambda: {"attempts": 0, "proven": 0, "fits": []})
    for e in _load()["events"]:
        k = (e["country"], e["niche"])
        agg[k]["attempts"] += 1
        if e.get("proven"):
            agg[k]["proven"] += 1
            if e.get("fit") is not None:
                agg[k]["fits"].append(e["fit"])   # 점령 평균은 '검증 자산'만

    rows = []
    keys = set(agg.keys())
    if targets:
        for co, niches in targets.items():
            for n in niches:
                keys.add((co.upper(), n))
    for (co, n) in sorted(keys):
        a = agg.get((co, n), {"attempts": 0, "proven": 0, "fits": []})
        avg = round(sum(a["fits"]) / len(a["fits"])) if a["fits"] else 0
        if a["proven"] >= CONQUER_MIN_PROVEN and avg >= CONQUER_MIN_FIT:
            status = "🟩 점령"
        elif a["attempts"] > 0:
            status = "🟨 개척중"
        else:
            status = "⬜ 미개척"
        rows.append({"country": co, "niche": n, "status": status,
                     "proven": a["proven"], "attempts": a["attempts"], "avg_fit": avg})
    return rows


def genre_playbook(country: str, niche: str) -> dict:
    """📖 장르별 승리 플레이북 — "이 장르에선 어떤 제목이 알고리즘을 타는가"를 축적·요약.
    우리 검증 자산(proven)에서 공통 승리 패턴(키워드·구조·상황어)을 뽑는다."""
    import re
    from collections import Counter
    co = country.upper()
    proven = [e for e in _load()["events"]
              if e["country"] == co and e["niche"] == niche and e.get("proven")]
    if not proven:
        return {"country": co, "niche": niche, "n": 0,
                "note": "아직 검증 자산 없음 — 개척 필요"}
    toks = Counter()
    emojis = Counter()
    prefix = Counter()
    fits = []
    _EMO = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    for e in proven:
        t = e["title"]; fits.append(e.get("fit") or 0)
        m = re.match(r"^\[?Playlist\]?", t, re.I)
        if m:
            prefix[m.group(0)] += 1
        for ch in _EMO.findall(t):
            emojis[ch] += 1
        for w in re.findall(r"[\w가-힣ぁ-んァ-ヶ一-龥]+", t):
            if len(w) > 1 and w.lower() not in {"playlist", "summer", "jazz", "music", "bgm"}:
                toks[w] += 1
    return {
        "country": co, "niche": niche, "n": len(proven),
        "avg_fit": round(sum(fits) / len(fits)),
        "winning_prefix": prefix.most_common(1)[0][0] if prefix else "[Playlist]",
        "winning_emojis": [e for e, _ in emojis.most_common(3)],
        "winning_keywords": [w for w, _ in toks.most_common(10)],
        "best_title": max(proven, key=lambda e: e.get("fit") or 0)["title"],
    }


def stats() -> dict:
    evs = _load()["events"]
    return {
        "total_events": len(evs),
        "proven_assets": sum(1 for e in evs if e.get("proven")),
        "countries": sorted({e["country"] for e in evs}),
        "niches": sorted({e["niche"] for e in evs}),
    }


# ── 자기검증 ───────────────────────────────────────────────
if __name__ == "__main__":
    if STORE.exists():
        STORE.unlink()
    # 여름 재즈 니치를 점령해 가는 과정 시뮬
    record("KR", "여름 재즈", "[Playlist] 청량한 여름 재즈 🍉 공부·일·카페 | Summer Jazz",
           fit=77, verdict="adopt", adopted=True)
    record("KR", "여름 재즈", "[Playlist] 시원한 수박 재즈 🍉 작업용·카페 BGM | Summer Jazz",
           fit=68, verdict="adopt", adopted=True)
    record("KR", "여름 재즈", "감성 문장형 약한 제목", fit=20, verdict="regenerate", adopted=False)
    record("JP", "洋楽ジャズ", "[Playlist] 作業用・勉強用・カフェBGM 🍉 | Summer Jazz",
           fit=72, verdict="adopt", adopted=True)

    print("검증 자산(KR 여름 재즈):")
    for t in winners("KR", "여름 재즈"):
        print("  ✅", t)
    assert len(winners("KR", "여름 재즈")) == 2, "채택·고Fit 2개가 자산이어야"

    print("\n🗺️ 점령 지도:")
    targets = {"KR": ["여름 재즈", "카페 재즈"], "JP": ["洋楽ジャズ"], "US": ["summer jazz"]}
    for r in territory_map(targets):
        print(f"  {r['status']} {r['country']}/{r['niche']} "
              f"(검증 {r['proven']} · 시도 {r['attempts']} · 평균Fit {r['avg_fit']})")

    print("\n📖 장르 플레이북 (KR 여름 재즈) — 이 장르에선 이런 제목이 먹힌다:")
    pb = genre_playbook("KR", "여름 재즈")
    print(f"   검증 {pb['n']}개·평균Fit {pb['avg_fit']} | 승리 이모지 {pb['winning_emojis']}")
    print(f"   승리 키워드: {pb['winning_keywords'][:8]}")
    print(f"   대표 제목: {pb['best_title']}")
    assert pb["n"] == 2 and pb["winning_keywords"]

    st = stats()
    print("\n📊 자산 현황:", st)
    assert st["proven_assets"] == 3
    # 점령: KR 여름 재즈(검증2·평균≥60) = 🟩
    kr = [r for r in territory_map(targets) if r["niche"] == "여름 재즈"][0]
    assert "점령" in kr["status"], kr
    if STORE.exists():
        STORE.unlink()
    print("\n✅ asset_ledger self-test 통과 — 검증자산 축적 + 점령 지도")
