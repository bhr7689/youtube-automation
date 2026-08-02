"""🔗 SRE-OS Phase 3 — URL 자동수집 · 다중 소스 비교 · A/B/C/D 성과 승자판정.

원본 스펙 채택 원칙:
- **Multi-Source Pattern**: 여러 소스를 비교해 공통 패턴 vs 개별 특성 vs 검증필요를 분리.
- **Experiment-Driven**: 전략은 가설 → 실제 성과로 승자 판정 → 학습 자산으로 축적.

기존 자산 재사용:
- 자막: `transcript_probe.get_lyrics`(youtube-transcript-api → Whisper 폴백)
- 메타(제목/작성자): 키 없는 **oEmbed**(youtube.com/oembed) — API 쿼터 불필요
- 학습 축적: `asset_ledger`(있으면) 에 승자 기록

⚠️ 웹 컨테이너는 프록시가 유튜브를 차단할 수 있어 수집이 실패할 수 있다(정상). 그 경우
限界를 명시하고 사용자가 자막을 직접 붙여넣는 폴백을 제공한다. 사장님 PC(일본쇼츠실행.bat)
에서는 yt-dlp/transcript 가 로컬로 동작해 완전 수집된다.

stdlib + 기존 모듈만 사용(런타임·FastAPI·cron 공용).
"""
from __future__ import annotations

import json
import re
import urllib.request

try:
    import transcript_probe as TP
except Exception:
    TP = None
try:
    import asset_ledger
except Exception:
    asset_ledger = None


# ── URL → video_id ────────────────────────────────────────────
_VID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/v/)([A-Za-z0-9_-]{11})")


def extract_video_id(url: str) -> str | None:
    """watch?v= · youtu.be · shorts · embed URL 에서 11자 video_id 추출."""
    if not url:
        return None
    u = url.strip()
    m = _VID_RE.search(u)
    if m:
        return m.group(1)
    # 순수 11자 ID 를 그대로 준 경우
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", u):
        return u
    return None


# ── oEmbed 로 제목/작성자(키 불필요) ───────────────────────────
def fetch_oembed(video_id: str, timeout: float = 8.0) -> dict:
    """youtube oEmbed — API 키 없이 제목·채널명 획득. 실패 시 {} (프록시 차단 등)."""
    url = ("https://www.youtube.com/oembed?format=json&url="
           f"https://www.youtube.com/watch?v={video_id}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return {"title": data.get("title", ""), "author": data.get("author_name", "")}
    except Exception as e:   # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


# ── URL 소스 수집(메타 + 자막) ────────────────────────────────
def collect_source(url: str, *, allow_whisper: bool = False,
                   openai_key: str | None = None) -> dict:
    """URL → {ok, video_id, title, author, transcript, source, kind, text, error, degraded}.

    text = 분석에 넣을 본문(제목 + 자막). 자막 실패해도 제목만이라도 반환(degraded).
    """
    vid = extract_video_id(url)
    if not vid:
        return {"ok": False, "error": "URL 에서 video_id 를 찾지 못했어요(watch?v=·youtu.be·shorts 지원)."}

    meta = fetch_oembed(vid)
    title = meta.get("title", "")
    author = meta.get("author", "")

    transcript, tsource, terror = "", "", ""
    if TP is not None:
        try:
            r = TP.get_lyrics(vid, allow_whisper=allow_whisper, openai_key=openai_key)
            transcript, tsource, terror = r.text, r.source, r.error
        except Exception as e:   # noqa: BLE001
            terror = f"{type(e).__name__}: {str(e)[:150]}"
    else:
        terror = "transcript_probe 미로드"

    # 분석 본문 조립: 제목(있으면) + 자막
    parts = []
    if title:
        parts.append(title)
    if transcript:
        parts.append(transcript)
    text = "\n".join(parts).strip()

    degraded = not transcript          # 자막 못 받으면 degraded(제목만)
    ok = bool(text)
    err = ""
    if not transcript:
        err = ("자막 자동수집 실패 — " + (terror or "이 환경(웹)에서 유튜브 접근 차단")
               + ". 사장님 PC 에서 실행하거나 자막을 직접 붙여넣어 주세요.")
    return {
        "ok": ok, "video_id": vid, "title": title, "author": author,
        "transcript": transcript, "source": tsource,
        "kind": "transcript" if transcript else "idea",
        "text": text, "error": err if not ok or degraded else "",
        "degraded": degraded,
        "meta_error": meta.get("error", ""),
    }


# ── 다중 소스 비교(공통 패턴 vs 개별 특성) ──────────────────────
def _axis_items(report: dict, axis: str, key: str) -> list[str]:
    v = (report.get("reverseEngineering", {}).get(axis, {}) or {}).get(key, [])
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


def compare_sources(reports: list[dict], labels: list[str] | None = None) -> dict:
    """여러 SRE 리포트를 비교 → 공통(전부 등장) / 개별(고유) / 검증필요 분리.

    비교 축: 바이럴 신호·심리 트리거·구조 단계. + 점수 스프레드.
    """
    n = len(reports)
    labels = labels or [f"소스{i+1}" for i in range(n)]
    if n < 2:
        return {"ok": False, "error": "비교하려면 소스가 2개 이상 필요해요.", "count": n}

    def collect(axis, key):
        per = []
        for rep in reports:
            per.append(set(_axis_items(rep, axis, key)))
        common = set.intersection(*per) if per else set()
        individual = []
        for i, s in enumerate(per):
            uniq = s - set.union(*[p for j, p in enumerate(per) if j != i]) if n > 1 else s
            individual.append({"label": labels[i], "unique": sorted(uniq)})
        allseen = set.union(*per) if per else set()
        # 일부(전부는 아님) 등장 = 검증필요(시장 일반인지 개별인지 불명)
        partial = sorted(allseen - common - set().union(*[set(x["unique"]) for x in individual]))
        return {"common": sorted(common), "individual": individual, "partial": partial}

    stages_axis = []
    for rep in reports:
        st = {x.get("stage") for x in
              (rep.get("reverseEngineering", {}).get("contentStructure", {}) or {}).get("stages", [])
              if isinstance(x, dict)}
        stages_axis.append(st)
    common_stages = sorted(set.intersection(*stages_axis)) if stages_axis else []

    scores = [(labels[i], (r.get("scores", {}).get("viralPotential", {}) or {}).get("score", 0))
              for i, r in enumerate(reports)]
    scores_sorted = sorted(scores, key=lambda kv: -kv[1])

    return {
        "ok": True, "count": n, "labels": labels,
        "viralSignals": collect("viralDNA", "signals"),
        "psychTriggers": collect("viewerPsychology", "triggers"),
        "commonStages": common_stages,
        "scores": scores_sorted,
        "topLabel": scores_sorted[0][0] if scores_sorted else "",
        "summary": _compare_summary(collect("viralDNA", "signals"),
                                    collect("viewerPsychology", "triggers"),
                                    common_stages, scores_sorted),
    }


def _compare_summary(vs, pt, stages, scores) -> str:
    bits = []
    if vs["common"]:
        bits.append(f"공통 바이럴 신호 {len(vs['common'])}종({', '.join(vs['common'][:3])})")
    if pt["common"]:
        bits.append(f"공통 심리 트리거 {len(pt['common'])}종")
    if stages:
        bits.append(f"공통 구조 {len(stages)}단계")
    if scores:
        bits.append(f"최고 점수 소스={scores[0][0]}({scores[0][1]})")
    return " · ".join(bits) or "공통 패턴이 뚜렷하지 않음 — 소재가 서로 다른 계열"


# ── A/B/C/D 성과 승자판정 ─────────────────────────────────────
def judge_experiment(entries: list[dict], *, higher_is_better: bool = True,
                     country: str | None = None, niche: str | None = None,
                     record: bool = False) -> dict:
    """전략별 실측 성과로 승자 판정.

    entries: [{"strategy":"A","metricName":"3초 유지율","value":62.0,
               "title":"...","note":""}, ...]
    반환: {ok, winner, ranking, delta, reasons, recorded}
    """
    valid = [e for e in entries
             if isinstance(e.get("value"), (int, float))]
    if len(valid) < 1:
        return {"ok": False, "error": "성과 값(value)이 있는 전략이 최소 1개 필요해요."}

    ranking = sorted(valid, key=lambda e: e["value"], reverse=higher_is_better)
    winner = ranking[0]
    reasons = []
    if len(ranking) >= 2:
        gap = winner["value"] - ranking[1]["value"]
        pct = (abs(gap) / (abs(ranking[1]["value"]) or 1)) * 100
        reasons.append(
            f"1위 {winner['strategy']}({winner['value']}) vs 2위 "
            f"{ranking[1]['strategy']}({ranking[1]['value']}) — 차이 {gap:+.2f} ({pct:.0f}%)")
        if pct < 5:
            reasons.append("격차 5% 미만 — 통계적으로 접전, A/B 추가 관찰 권장.")
        else:
            reasons.append(f"{winner['strategy']} 각도가 이 소재에서 유의미하게 우세 → 시리즈화 후보.")
    else:
        reasons.append(f"단일 전략({winner['strategy']}) 성과만 입력됨 — 비교군 추가 시 판정 신뢰↑.")

    recorded = False
    # 학습 자산: 승자 제목을 원장에 기록(있고, 채택 신호가 명확할 때)
    if record and asset_ledger and country and niche and winner.get("title"):
        try:
            asset_ledger.record(country, niche, winner["title"],
                                fit=float(winner["value"]), verdict="adopt", adopted=True)
            recorded = True
        except Exception:
            recorded = False

    return {
        "ok": True,
        "winner": {"strategy": winner["strategy"], "value": winner["value"],
                   "title": winner.get("title", ""),
                   "metricName": winner.get("metricName", "")},
        "ranking": [{"strategy": e["strategy"], "value": e["value"],
                     "title": e.get("title", "")} for e in ranking],
        "reasons": reasons,
        "recorded": recorded,
    }


# ── 자기검증 ──────────────────────────────────────────────────
if __name__ == "__main__":
    # 1) URL 파싱
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=5") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("그냥 텍스트") is None
    print("✅ URL→video_id 추출 5종 통과")

    # 2) collect_source — 잘못된 URL
    bad = collect_source("아무거나")
    assert not bad["ok"] and "video_id" in bad["error"]
    print("✅ 잘못된 URL 안전 실패")

    # 3) 다중 소스 비교 — 합성 리포트 2개
    def mk(signals, triggers, stages, score):
        return {
            "reverseEngineering": {
                "viralDNA": {"signals": signals},
                "viewerPsychology": {"triggers": triggers},
                "contentStructure": {"stages": [{"stage": s} for s in stages]},
            },
            "scores": {"viralPotential": {"score": score}},
        }
    r1 = mk(["숫자(구체성)", "짧은 훅"], ["호기심 격차", "반전"], ["hook", "reveal"], 82)
    r2 = mk(["숫자(구체성)", "질문형"], ["호기심 격차", "공감/이입"], ["hook", "payoff"], 71)
    cmp = compare_sources([r1, r2], ["A영상", "B영상"])
    assert cmp["ok"] and cmp["count"] == 2
    assert "숫자(구체성)" in cmp["viralSignals"]["common"], "공통 신호 잡아야"
    assert "호기심 격차" in cmp["psychTriggers"]["common"]
    assert cmp["commonStages"] == ["hook"]
    assert cmp["topLabel"] == "A영상", "점수 높은 쪽이 top"
    # 개별 특성
    a_uniq = next(x["unique"] for x in cmp["viralSignals"]["individual"] if x["label"] == "A영상")
    assert "짧은 훅" in a_uniq
    print(f"✅ 다중 소스 비교 — {cmp['summary']}")

    # 4) A/B/C/D 승자판정
    j = judge_experiment([
        {"strategy": "A", "metricName": "3초 유지율", "value": 62.0, "title": "체험 인증 …"},
        {"strategy": "D", "metricName": "3초 유지율", "value": 71.0, "title": "호기심 …"},
        {"strategy": "C", "metricName": "3초 유지율", "value": 48.0, "title": "팩트 …"},
    ])
    assert j["ok"] and j["winner"]["strategy"] == "D"
    assert j["ranking"][0]["strategy"] == "D" and j["ranking"][-1]["strategy"] == "C"
    print(f"✅ 승자판정 — {j['winner']['strategy']} 승 ({j['reasons'][0]})")

    print("\n✅ sre_sources self-test 통과 — URL수집·다중비교·승자판정")
