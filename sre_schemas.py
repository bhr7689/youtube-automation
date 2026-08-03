"""🧬 SRE-OS 출력 스키마 + 검증 — Shorts Reverse Engineering Operating System.

원본 스펙 §17(구조화 JSON 출력)을 기존 프로젝트에 맞춰 큐레이션한 스키마.
목적: 런타임(sre_runtime)의 최종 산출물이 **항상 같은 모양**이 되도록 계약을 고정.
      키가 없어도(Mock/규칙기반) 이 스키마를 100% 채운다.

stdlib 만 사용 — pydantic/외부 의존 없음(런타임·테스트·cron 어디서든 import 가능).

리포트 최상위 구조:
  reverseEngineering : 역설계 6축 (contentStructure/viralDNA/viewerPsychology/
                        emotionDNA/languageDNA/voiceDNA)
  scores             : viralPotential(0~100, confidence, factors)
  strategies         : A/B/C/D (경험/스토리/사실/호기심) — 각자 실험(가설) 포함
  localizations      : 시장별(KR/JP…) 대본 골격 + SEO 패키지
  experiments        : 전략별 실험을 한 곳에 모은 목록
  critic             : 유사성/안전 검수 (LOW~BLOCKED + verificationRequired)
  metadata           : runId/idempotencyKey/provider/mock/agentRuns/createdAt/version
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"

# ── 통제 어휘(enum) ────────────────────────────────────────────
INPUT_KINDS = ("script", "transcript", "keyword", "idea")
STRATEGY_KEYS = ("A", "B", "C", "D")
STRATEGY_LABELS = {
    "A": "경험(Experience)",   # 1인칭 체험·감각 재현
    "B": "스토리(Story)",       # 서사·전개·반전
    "C": "사실(Fact)",          # 정보·근거·권위
    "D": "호기심(Curiosity)",   # 정보 격차·미완결
}
# 콘텐츠 구조 7단계 (쇼츠 문법) — A03 분해 축
STRUCTURE_STAGES = (
    "hook", "setup", "escalation", "reveal", "payoff", "cta", "loop",
)
SIMILARITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "BLOCKED")


# ── 빈 골격 생성기(모든 필드를 안전 기본값으로 채운 뼈대) ──────────
def empty_experiment() -> dict:
    """실험 = 가설 한 덩어리 (원본 원칙: 모든 전략은 검증 가능한 가설)."""
    return {
        "hypothesis": "",       # 무엇이 통할 것이라 보는가
        "metric": "",           # 무엇으로 측정하는가 (예: 3초 유지율)
        "failureMode": "",      # 어떻게 실패할 수 있는가
        "duration": "",         # 관찰 기간 (예: 업로드 후 48시간)
        "successCriteria": "",  # 성공 기준 (예: 유지율 60%+)
        "nextAction": "",       # 성공/실패 시 다음 행동
    }


def empty_strategy(key: str) -> dict:
    return {
        "key": key,
        "label": STRATEGY_LABELS.get(key, key),
        "angle": "",            # 이 전략의 핵심 각도(한 줄)
        "hook": "",             # 0~3초 후킹 문구
        "title": "",            # 제목 후보
        "thumbText": "",        # 썸네일 위 문구
        "outline": [],          # 섹션 골격(list[str])
        "rationale": "",        # 왜 이 각도가 이 소재에 통하는가
        "experiment": empty_experiment(),
    }


def empty_localization(market: str) -> dict:
    return {
        "market": market,
        "script": [],           # 섹션별 대본 골격 [{stage, text}]
        "seo": {},              # metadata_team 산출(제목/설명/태그/해시태그/썸네일)
        "notes": "",            # 현지화 뉘앙스 메모
    }


def empty_report() -> dict:
    """스키마 v1.0 전체 뼈대 — 런타임이 이 위에 값을 채운다."""
    return {
        "reverseEngineering": {
            "contentStructure": {"stages": [], "summary": ""},
            "viralDNA": {"signals": [], "formula": "", "confidence": 0.0},
            "viewerPsychology": {"triggers": [], "summary": ""},
            "emotionDNA": {"curve": [], "arc": "", "summary": ""},
            "languageDNA": {"register": "", "sentenceLen": 0.0,
                            "imperativeRatio": 0.0, "markers": []},
            "voiceDNA": {"pace": "", "pauseDensity": 0.0,
                         "emphasis": [], "summary": ""},
        },
        "scores": {
            "viralPotential": {"score": 0, "confidence": 0.0, "factors": []},
        },
        "strategies": {k: empty_strategy(k) for k in STRATEGY_KEYS},
        "localizations": {},
        "experiments": [],
        "critic": {
            "similarityRisk": "LOW",
            "notes": [],
            "verificationRequired": [],
        },
        "metadata": {
            "runId": "",
            "idempotencyKey": "",
            "provider": "mock",
            "mock": True,
            "agentRuns": [],
            "createdAt": "",
            "schemaVersion": SCHEMA_VERSION,
        },
    }


# ── 검증 ──────────────────────────────────────────────────────
class SchemaError(ValueError):
    """리포트가 계약을 위반했을 때."""


def validate_report(report: dict) -> list[str]:
    """스키마 위반 목록을 반환(빈 리스트 = 통과). 예외 대신 목록으로 —
    런타임이 부분 실패를 기록하고도 계속 진행할 수 있게."""
    errs: list[str] = []

    def need(cond: bool, msg: str):
        if not cond:
            errs.append(msg)

    need(isinstance(report, dict), "report 는 dict 여야 함")
    if not isinstance(report, dict):
        return errs

    # 최상위 키
    for key in ("reverseEngineering", "scores", "strategies",
                "localizations", "experiments", "critic", "metadata"):
        need(key in report, f"최상위 키 누락: {key}")

    # 역설계 6축
    re_ = report.get("reverseEngineering", {})
    for axis in ("contentStructure", "viralDNA", "viewerPsychology",
                 "emotionDNA", "languageDNA", "voiceDNA"):
        need(axis in re_, f"reverseEngineering 축 누락: {axis}")

    # 콘텐츠 구조 단계는 통제 어휘 안에서만
    for st in re_.get("contentStructure", {}).get("stages", []):
        stage = st.get("stage") if isinstance(st, dict) else None
        need(stage in STRUCTURE_STAGES, f"알 수 없는 구조 단계: {stage}")

    # 점수 0~100
    vp = report.get("scores", {}).get("viralPotential", {})
    sc = vp.get("score")
    need(isinstance(sc, (int, float)) and 0 <= sc <= 100,
         f"viralPotential.score 는 0~100: {sc}")
    conf = vp.get("confidence")
    need(isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0,
         f"viralPotential.confidence 는 0.0~1.0: {conf}")

    # 전략 A/B/C/D 모두 존재 + 실험 필드 완비
    strat = report.get("strategies", {})
    for k in STRATEGY_KEYS:
        need(k in strat, f"전략 누락: {k}")
        s = strat.get(k, {})
        exp = s.get("experiment", {})
        for f in ("hypothesis", "metric", "failureMode",
                  "duration", "successCriteria", "nextAction"):
            need(f in exp, f"전략 {k} 실험 필드 누락: {f}")

    # 크리틱 위험도 어휘
    risk = report.get("critic", {}).get("similarityRisk")
    need(risk in SIMILARITY_LEVELS, f"알 수 없는 유사성 위험도: {risk}")

    # 메타데이터 필수
    md = report.get("metadata", {})
    for f in ("runId", "idempotencyKey", "provider", "mock",
              "agentRuns", "createdAt", "schemaVersion"):
        need(f in md, f"metadata 필드 누락: {f}")

    return errs


def assert_valid(report: dict) -> dict:
    """검증 실패 시 예외. 성공 시 report 그대로 반환(체이닝용)."""
    errs = validate_report(report)
    if errs:
        raise SchemaError("SRE 리포트 스키마 위반:\n  - " + "\n  - ".join(errs))
    return report


# ── 자기검증 ──────────────────────────────────────────────────
if __name__ == "__main__":
    rep = empty_report()
    # 빈 골격은 필수 키를 모두 갖췄지만 값이 비어 통과해야 함
    errs = validate_report(rep)
    assert errs == [], f"빈 골격이 통과 못함: {errs}"
    assert set(rep["strategies"]) == set(STRATEGY_KEYS)
    assert rep["metadata"]["schemaVersion"] == SCHEMA_VERSION

    # 위반 감지 확인
    bad = empty_report()
    bad["scores"]["viralPotential"]["score"] = 999
    bad["critic"]["similarityRisk"] = "???"
    bad["reverseEngineering"]["contentStructure"]["stages"] = [{"stage": "nope"}]
    errs2 = validate_report(bad)
    assert any("score" in e for e in errs2)
    assert any("위험도" in e for e in errs2)
    assert any("구조 단계" in e for e in errs2)
    print("✅ sre_schemas self-test 통과 — 빈 골격 유효 + 위반 3종 감지")
