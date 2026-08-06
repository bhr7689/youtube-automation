"""🏷️ SRE-OS 카테고리별 공식 — 카테고리(대분류)의 여러 채널을 표본으로 '그 계열의 승리공식'.

원본 Multi-Source Pattern 을 카테고리 규모로 확장. 다중 소스 비교(compare_sources)는
'전부 등장(교집합)'이라 표본이 20+개면 공통이 비어버린다. 카테고리 공식은 대신
**빈도 기반**(과반/임계 이상 등장)으로 지배 신호·트리거·구조를 뽑는다.

→ 스포츠는 "공식·순간·하이라이트", 지식은 "몰랐던 사실·호기심 격차", 감동은 "사연·반전"
  처럼 카테고리마다 공식이 다르게 나온다.

순수 로직 + 주입(수집/분석 함수) → 키/네트워크 없이 테스트 가능.
실제 수집은 사장님 PC(RSS·유튜브 접근)에서 완전 동작.
"""
from __future__ import annotations

from collections import Counter


def aggregate_category(reports: list[dict], min_ratio: float = 0.4) -> dict:
    """여러 SRE 리포트 → 빈도 기반 카테고리 공식.

    각 신호/트리거/구조단계가 표본의 min_ratio(기본 40%) 이상에서 등장하면 '지배 패턴'.
    반환은 winning_formula 와 같은 모양({signals,triggers,stages,summary,sourceCount})
    이라 그대로 생성에 주입(inject) 가능.
    """
    n = len(reports)
    if n == 0:
        return {"signals": [], "triggers": [], "stages": [],
                "summary": "표본 없음", "sourceCount": 0, "avgScore": 0}

    sig_c, trg_c, stg_c = Counter(), Counter(), Counter()
    scores = []
    for rep in reports:
        re_ = rep.get("reverseEngineering", {})
        for s in (re_.get("viralDNA", {}) or {}).get("signals", []):
            sig_c[s] += 1
        for t in (re_.get("viewerPsychology", {}) or {}).get("triggers", []):
            trg_c[t] += 1
        seen_stage = {x.get("stage") for x in
                      (re_.get("contentStructure", {}) or {}).get("stages", [])
                      if isinstance(x, dict)}
        for st in seen_stage:
            stg_c[st] += 1
        sc = (rep.get("scores", {}).get("viralPotential", {}) or {}).get("score")
        if isinstance(sc, (int, float)):
            scores.append(sc)

    thresh = max(1, round(n * min_ratio))

    def dominant(counter):
        return [{"name": k, "count": v, "ratio": round(v / n, 2)}
                for k, v in counter.most_common() if v >= thresh]

    sig = dominant(sig_c)
    trg = dominant(trg_c)
    stg = dominant(stg_c)
    avg = round(sum(scores) / len(scores)) if scores else 0

    bits = []
    if sig:
        bits.append("지배 신호: " + ", ".join(x["name"] for x in sig[:3]))
    if trg:
        bits.append("지배 트리거: " + ", ".join(x["name"] for x in trg[:3]))
    if stg:
        bits.append("핵심 구조: " + " → ".join(x["name"] for x in stg))
    summary = " · ".join(bits) or f"표본 {n}개 — 지배 패턴 약함(임계 {int(min_ratio*100)}%)"

    return {
        # winning_formula 호환 필드(생성 주입용) — 이름만 추림
        "signals": [x["name"] for x in sig],
        "triggers": [x["name"] for x in trg],
        "stages": [x["name"] for x in stg],
        "summary": summary,
        "sourceCount": n,
        # 상세(화면 표시용) — 빈도·비율 포함
        "signalDetail": sig, "triggerDetail": trg, "stageDetail": stg,
        "avgScore": avg,
        "threshold": thresh, "minRatio": min_ratio,
    }


def category_formula(channels: list[dict], sample_fn, analyze_fn, *,
                     per_channel: int = 3, max_channels: int = 10,
                     min_ratio: float = 0.4) -> dict:
    """카테고리 채널들 → 표본 수집 → 분석 → 빈도 집계 → 공식.

    sample_fn(channel) -> list[str]  (채널의 최근 제목/텍스트 표본)
    analyze_fn(text)   -> dict        (SRE 리포트)
    수집·분석은 주입(테스트 시 stub). 실패한 채널은 건너뛰고 완주.
    """
    reports, contributors, sampled, failed = [], [], 0, 0
    for ch in channels[:max_channels]:
        try:
            texts = sample_fn(ch) or []
        except Exception:
            failed += 1
            continue
        picked = 0
        for t in texts:
            if not (t or "").strip():
                continue
            try:
                rep = analyze_fn(t)
            except Exception:
                continue
            reports.append(rep)
            sampled += 1
            picked += 1
            if picked >= per_channel:
                break
        if picked:
            contributors.append(ch.get("title") or ch.get("name") or "?")

    if len(reports) < 2:
        return {
            "ok": False, "sampled": sampled, "channelsTried": len(channels[:max_channels]),
            "failed": failed,
            "note": "표본 부족(2개 이상 필요) — 이 환경(웹)은 유튜브 차단으로 수집이 막힐 수 있어요. "
                    "사장님 PC(일본쇼츠실행.bat)에서 실행하면 RSS 로 자동 수집됩니다.",
        }

    formula = aggregate_category(reports, min_ratio=min_ratio)
    return {
        "ok": True,
        "sampled": sampled,
        "contributorCount": len(contributors),
        "contributors": contributors,
        "winningFormula": formula,
    }


# ── 자기검증(stub 수집·분석) ──────────────────────────────────
if __name__ == "__main__":
    # 스포츠 계열: '공식/순간/하이라이트' 신호 반복
    def _rep(signals, triggers, stages, score):
        return {"reverseEngineering": {
                    "viralDNA": {"signals": signals},
                    "viewerPsychology": {"triggers": triggers},
                    "contentStructure": {"stages": [{"stage": s} for s in stages]}},
                "scores": {"viralPotential": {"score": score}}}

    sports = [
        _rep(["숫자(구체성)", "짧은 훅(3초 내 읽힘)"], ["과장/극단"], ["hook", "payoff"], 80),
        _rep(["숫자(구체성)", "질문형"], ["과장/극단", "공감/이입"], ["hook", "reveal"], 72),
        _rep(["숫자(구체성)"], ["과장/극단"], ["hook"], 68),
        _rep(["감정 이모지"], ["호기심 격차"], ["setup"], 40),
    ]
    agg = aggregate_category(sports, min_ratio=0.5)
    print("스포츠 공식:", agg["summary"])
    assert "숫자(구체성)" in agg["signals"], "과반 등장 신호가 잡혀야"
    assert "과장/극단" in agg["triggers"]
    assert "hook" in agg["stages"]
    assert agg["sourceCount"] == 4 and agg["avgScore"] > 0

    # category_formula — stub 수집/분석
    channels = [{"title": "FORMULA 1"}, {"title": "NBA"}, {"title": "UFC"}]
    titles = {
        "FORMULA 1": ["F1 역대급 추월 순간", "이 숫자 실화? 최고 속도"],
        "NBA": ["믿기지 않는 버저비터 순간", "역대 최고 덩크 TOP"],
        "UFC": ["3초 KO 최강 한 방", "왜 아무도 못 막았나"],
    }
    def sample_fn(ch): return titles.get(ch["title"], [])
    def analyze_fn(t):  # 아주 단순한 규칙(제목→신호)
        sig, trg = [], []
        if any(c.isdigit() for c in t): sig.append("숫자(구체성)")
        if "순간" in t or "TOP" in t or "최고" in t: sig.append("과장/극단")
        if "왜" in t or "?" in t or "실화" in t: trg.append("호기심 격차")
        if "최강" in t or "역대" in t: trg.append("과장/극단")
        return _rep(sig, trg, ["hook"], 70)
    out = category_formula(channels, sample_fn, analyze_fn, per_channel=2, min_ratio=0.3)
    assert out["ok"] and out["sampled"] == 6, out
    print("카테고리 공식:", out["winningFormula"]["summary"])
    assert out["winningFormula"]["signals"], "지배 신호가 나와야"

    # 표본 부족 → graceful
    bad = category_formula([{"title": "X"}], lambda c: [], lambda t: _rep([], [], [], 0))
    assert not bad["ok"] and "표본 부족" in bad["note"]

    print("\n✅ sre_category self-test 통과 — 빈도 집계 + 카테고리 공식 + graceful")
