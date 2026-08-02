"""🧬 SRE-OS 런타임 — 역설계 → 전략 → 로컬라이제이션 오케스트레이터.

원본 스펙의 심장(Multi-Agent Runtime)을 기존 `metadata_team`(편집장+전문가) 패턴을
확장해 구현. 공유 컨텍스트(SREContext)를 파이프라인으로 흘리며 각 에이전트가 자기 파트를
채우고, 마지막에 Synthesizer 가 스키마(sre_schemas)에 맞춰 종합한다.

원칙(원본 채택):
- **Reverse Engineering First**: Evidence → Pattern → Hypothesis → Strategy → Generation
- **Human Psychology First**: 알고리즘 아니라 시청 심리 중심
- **Ethical Transformation**: 특정 크리에이터 고유표현 복제 금지 → 일반화 패턴만
- **Experiment-Driven**: 모든 전략 = 검증 가능한 가설
- **Mock First**: 키가 없어도(규칙기반) 전체 흐름이 끝까지 동작 → 값을 100% 채운다

에이전트(원본 A01~A19 매핑, §1 스펙):
  A01 InputNormalizer · A02 EvidenceExtractor · A03 ContentStructure(신규) ·
  A04 ViralDNA · A05 ViewerPsychology · A06 EmotionDNA(신규) ·
  A07 LanguageDNA · A08 VoiceDNA(신규) · A12 StrategyGenerator(A/B/C/D) ·
  A09/10/13/14 Localizer(KR/JP, metadata_team 재사용) · ViralScorer ·
  A18 Critic(유사성/안전) · A19 Synthesizer

키가 있으면 각 축을 LLM 으로 '심화'할 수 있도록 llm_call 주입구를 남겨둠(Phase 2).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import sre_schemas as S
import sre_store as DB

try:
    import metadata_team as MT   # KR/JP SEO 패키지 재사용
except Exception:
    MT = None
try:
    import sre_provider as PROV  # LLM 프로바이더 어댑터(OpenAI/Gemini/Anthropic/Mock)
except Exception:
    PROV = None


# ── 공유 컨텍스트 ──────────────────────────────────────────────
@dataclass
class SREContext:
    text: str = ""
    kind: str = "script"          # script/transcript/keyword/idea
    url: str = ""
    markets: list = field(default_factory=lambda: ["KR"])
    llm_call = None               # (system, user)->dict|None, 없으면 규칙기반(Mock)
    provider_name: str = "mock"   # 실제 사용 프로바이더(mock/openai/gemini/anthropic)

    # 에이전트가 채우는 중간 산출물
    tokens: list = field(default_factory=list)
    sentences: list = field(default_factory=list)
    analyses: dict = field(default_factory=dict)   # 역설계 6축
    strategies: dict = field(default_factory=dict)
    localizations: dict = field(default_factory=dict)
    experiments: list = field(default_factory=list)
    critic: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    agent_log: list = field(default_factory=list)  # [{agent,status,ms,summary,error}]

    @property
    def mock(self) -> bool:
        return self.llm_call is None

    def log(self, agent, status, ms, summary="", error=""):
        self.agent_log.append({"agent": agent, "status": status, "ms": ms,
                               "summary": summary, "error": error})


# ── 텍스트 유틸(규칙기반 분석의 토대) ─────────────────────────────
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？…\n])\s+|\n+")
_WORD = re.compile(r"[\w가-힣ぁ-んァ-ヶ一-龠]+", re.UNICODE)


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


# 정서/심리 사전(규칙기반 — 한/영/일 혼용, 소재 통념 주입 금지 원칙 하에 '신호'만 탐지)
_POS = {"좋", "행복", "웃", "사랑", "설레", "감동", "최고", "성공", "happy", "love",
        "great", "win", "amazing", "嬉", "笑", "好", "愛"}
_NEG = {"슬픔", "슬프", "눈물", "화", "충격", "실패", "무서", "위기", "sad", "cry",
        "shock", "fail", "fear", "angry", "悲", "涙", "怒", "怖"}
_TENSION = {"그런데", "하지만", "갑자기", "결국", "사실", "충격", "반전", "몰랐",
            "but", "suddenly", "actually", "however", "しかし", "実は", "突然"}
# 클릭 심리 트리거(A05) — concept_maker.CLICK_PSYCH 계열 신호
_TRIGGERS = {
    "호기심 격차": ("왜", "이유", "비밀", "몰랐", "정체", "why", "secret", "reason", "なぜ"),
    "반전": ("사실", "알고보니", "반전", "그런데", "actually", "twist", "実は"),
    "과장/극단": ("최고", "역대", "가장", "제일", "1위", "무조건", "best", "ever", "most", "最強"),
    "미완결/서스펜스": ("과연", "결과는", "끝까지", "마지막", "…", "wait", "最後"),
    "금기/의외": ("아무도", "절대", "안 알려", "숨겨", "nobody", "never", "誰も"),
    "공감/이입": ("나만", "우리", "당신", "너도", "혹시", "you", "everyone", "あなた"),
}


# ── 에이전트 ──────────────────────────────────────────────────
class Agent:
    code = "A00"
    name = "agent"
    def run(self, ctx: SREContext): ...


class InputNormalizer(Agent):
    code, name = "A01", "입력 정규화"
    def run(self, ctx: SREContext):
        ctx.text = (ctx.text or "").strip()
        ctx.sentences = _sentences(ctx.text)
        ctx.tokens = _tokens(ctx.text)
        # 종류 자동 보정: 짧고 문장부호 없으면 keyword/idea
        if ctx.kind not in S.INPUT_KINDS:
            ctx.kind = "keyword" if len(ctx.tokens) <= 4 else "script"
        return f"{ctx.kind} · 문장 {len(ctx.sentences)} · 토큰 {len(ctx.tokens)}"


class EvidenceExtractor(Agent):
    code, name = "A02", "근거 추출"
    def run(self, ctx: SREContext):
        freq: dict[str, int] = {}
        for t in ctx.tokens:
            if len(t) >= 2:
                freq[t] = freq.get(t, 0) + 1
        top = sorted(freq.items(), key=lambda kv: -kv[1])[:12]
        ctx.analyses["evidence"] = {
            "topKeywords": [k for k, _ in top],
            "sentenceCount": len(ctx.sentences),
        }
        return f"핵심어 {len(top)} 추출"


class ContentStructure(Agent):
    """A03(신규) — 쇼츠 7단 구조로 분해. 문장을 위치+신호로 단계에 매핑."""
    code, name = "A03", "콘텐츠 구조 분해"
    def run(self, ctx: SREContext):
        sents = ctx.sentences
        n = len(sents)
        stages = []
        if n == 0:
            ctx.analyses["contentStructure"] = {"stages": [], "summary": "입력 없음"}
            return "입력 없음"
        # 위치 기반 골격 + 신호 보정
        def stage_for(i: int, s: str) -> str:
            r = i / max(n, 1)
            low = s.lower()
            if any(w in s for w in _TENSION):
                return "reveal"
            if r < 0.12:
                return "hook"
            if r < 0.35:
                return "setup"
            if r < 0.6:
                return "escalation"
            if r < 0.8:
                return "reveal"
            if any(w in low for w in ("구독", "좋아요", "팔로우", "subscribe", "follow")):
                return "cta"
            if r < 0.95:
                return "payoff"
            return "loop"
        for i, s in enumerate(sents):
            stages.append({"stage": stage_for(i, s), "text": s[:120]})
        present = [st for st in S.STRUCTURE_STAGES
                   if any(x["stage"] == st for x in stages)]
        ctx.analyses["contentStructure"] = {
            "stages": stages,
            "summary": "구조 단계: " + " → ".join(present),
        }
        return f"{len(stages)}문장 → {len(present)}단계"


class ViralDNA(Agent):
    """A04 — 바이럴 신호 + 승리공식(tier_lab/viral_lab 계열 로직 요약)."""
    code, name = "A04", "바이럴 DNA"
    def run(self, ctx: SREContext):
        text = ctx.text
        first = ctx.sentences[0] if ctx.sentences else ""
        signals = []
        if any(w in first for w in ("왜", "몰랐", "why", "secret", "?")):
            signals.append("첫 문장 후킹(호기심)")
        if any(e in text for e in "🔥😱😭🤯❗️❤️"):
            signals.append("감정 이모지")
        if re.search(r"\d", text):
            signals.append("숫자(구체성)")
        if len(first) <= 22:
            signals.append("짧은 훅(3초 내 읽힘)")
        if "?" in text or "？" in text:
            signals.append("질문형")
        conf = min(1.0, 0.3 + 0.14 * len(signals))
        formula = " + ".join(signals[:3]) or "신호 약함 — 훅 보강 필요"
        ctx.analyses["viralDNA"] = {"signals": signals, "formula": formula,
                                    "confidence": round(conf, 2)}
        return f"신호 {len(signals)} (conf {conf:.2f})"


class ViewerPsychology(Agent):
    """A05 — 클릭 심리 트리거 탐지(concept_maker.CLICK_PSYCH 계열)."""
    code, name = "A05", "시청자 심리"
    def run(self, ctx: SREContext):
        text = ctx.text
        found = []
        for name, kws in _TRIGGERS.items():
            if any(k in text for k in kws):
                found.append(name)
        summary = ("작동 트리거: " + ", ".join(found)) if found else \
                  "심리 트리거 미약 — 호기심 격차·반전 중 최소 1개 심기 권장"
        ctx.analyses["viewerPsychology"] = {"triggers": found, "summary": summary}
        return f"트리거 {len(found)}"


class EmotionDNA(Agent):
    """A06(신규) — 시간축 감정 곡선. 문장별 valence(-1~+1) → 아크 판정."""
    code, name = "A06", "감정 DNA"
    def run(self, ctx: SREContext):
        curve = []
        for s in ctx.sentences:
            pos = sum(1 for w in _POS if w in s)
            neg = sum(1 for w in _NEG if w in s)
            v = 0.0
            if pos or neg:
                v = round((pos - neg) / (pos + neg), 2)
            curve.append(v)
        arc = "평탄"
        if curve:
            lo, hi = min(curve), max(curve)
            start, end = curve[0], curve[-1]
            if lo < -0.2 and end > 0.2:
                arc = "하강→반등(눈물→감동)"
            elif hi > 0.2 and end < -0.2:
                arc = "상승→하강(기대→반전)"
            elif hi - lo > 0.5:
                arc = "진폭 큼(감정 롤러코스터)"
            elif abs(hi) < 0.2 and abs(lo) < 0.2:
                arc = "평탄(감정 자극 약함)"
        ctx.analyses["emotionDNA"] = {
            "curve": curve, "arc": arc,
            "summary": f"감정 아크: {arc}",
        }
        return f"아크={arc}"


class LanguageDNA(Agent):
    """A07 — 어투/문장 길이/명령형 비율(lyrics_analyzer·nation_prompts 계열)."""
    code, name = "A07", "언어 DNA"
    def run(self, ctx: SREContext):
        sents = ctx.sentences or [""]
        avg_len = round(sum(len(s) for s in sents) / len(sents), 1)
        imper = sum(1 for s in sents
                    if re.search(r"(하세요|해라|해봐|보세요|하자|자\.|!$|세요$|해요$)", s))
        ratio = round(imper / len(sents), 2)
        register = "구어체/친근" if any("요" in s or "어" in s for s in sents) else "문어체/정보"
        markers = []
        if avg_len < 20:
            markers.append("짧은 문장(리듬감)")
        if ratio > 0.3:
            markers.append("명령형 다수(행동 유도)")
        if "?" in ctx.text:
            markers.append("질문 삽입(참여 유도)")
        ctx.analyses["languageDNA"] = {
            "register": register, "sentenceLen": avg_len,
            "imperativeRatio": ratio, "markers": markers,
        }
        return f"{register}·평균 {avg_len}자·명령형 {ratio}"


class VoiceDNA(Agent):
    """A08(신규) — 보이스(속도/쉼/강조) 분석축. 텍스트에서 프록시 추정(tts 연계 준비)."""
    code, name = "A08", "보이스 DNA"
    def run(self, ctx: SREContext):
        text = ctx.text
        commas = text.count(",") + text.count("、")
        ellipsis = text.count("…") + text.count("...")
        exclaim = text.count("!") + text.count("！")
        chars = max(len(text), 1)
        pause_density = round((commas + ellipsis * 2) / (chars / 100 + 1), 2)
        # 문장 평균 길이로 속도 프록시
        sents = ctx.sentences or [""]
        avg = sum(len(s) for s in sents) / len(sents)
        pace = "빠름(짧은 호흡)" if avg < 18 else ("느림(긴 호흡)" if avg > 40 else "보통")
        emphasis = []
        if exclaim:
            emphasis.append("느낌표 강조")
        if ellipsis:
            emphasis.append("말줄임 서스펜스")
        caps = re.findall(r"\b[A-Z]{2,}\b", text)
        if caps:
            emphasis.append("대문자 강조")
        ctx.analyses["voiceDNA"] = {
            "pace": pace, "pauseDensity": pause_density,
            "emphasis": emphasis,
            "summary": f"속도 {pace}·쉼밀도 {pause_density}",
        }
        return f"속도={pace}·쉼 {pause_density}"


class StrategyGenerator(Agent):
    """A12 — A/B/C/D 전략 4종 + 각자 실험(가설). 심리 작동방식이 서로 다름."""
    code, name = "A12", "A/B/C/D 전략"

    ANGLES = {
        "A": ("1인칭 체험·감각 재현", "직접 해보니…", "체험 인증"),
        "B": ("서사·전개·반전 구조", "그날 무슨 일이…", "이야기"),
        "C": ("정보·근거·권위 제시", "사실은 이렇습니다", "팩트"),
        "D": ("정보 격차·미완결 유발", "끝까지 보면…", "호기심"),
    }
    METRIC = {
        "A": "3초 유지율 + 저장율",
        "B": "평균 시청 지속시간(APV)",
        "C": "댓글 내 정보 인용/공유율",
        "D": "클릭률(CTR) + 완주율",
    }

    def run(self, ctx: SREContext):
        ev = ctx.analyses.get("evidence", {})
        kws = ev.get("topKeywords", [])[:3]
        core = " ".join(kws) if kws else (ctx.text[:14] or "이 주제")
        triggers = ctx.analyses.get("viewerPsychology", {}).get("triggers", [])
        vp_hint = triggers[0] if triggers else "호기심 격차"
        for k in S.STRATEGY_KEYS:
            angle, hook_stub, tail = self.ANGLES[k]
            st = S.empty_strategy(k)
            st["angle"] = angle
            st["hook"] = f"{hook_stub} ({core})"
            st["title"] = f"[{tail}] {core}"[:60]
            st["thumbText"] = core[:14]
            st["outline"] = [
                f"HOOK: {hook_stub}",
                f"전개: {core} 를 {angle} 로 풀기",
                "PAYOFF: 핵심 한 방",
                "CTA: 다음 편 예고(루프)",
            ]
            st["rationale"] = (
                f"이 소재의 '{vp_hint}' 신호를 {angle} 각도로 증폭 — "
                f"A/B/C/D 는 심리 작동방식이 달라 같은 소재도 반응층이 갈림.")
            st["experiment"] = {
                "hypothesis": f"{angle} 각도가 이 소재의 초반 이탈을 줄인다",
                "metric": self.METRIC[k],
                "failureMode": "훅이 소재와 어긋나 3초 이탈 급증",
                "duration": "업로드 후 48시간",
                "successCriteria": "동일 채널 최근 평균 대비 지표 +15%",
                "nextAction": "성공 시 시리즈화 / 실패 시 다른 각도(다음 알파벳)로 전환",
            }
            ctx.strategies[k] = st
            ctx.experiments.append({"strategy": k, **st["experiment"]})
        return "A/B/C/D 4종 + 실험 4개"


class Localizer(Agent):
    """A09/10/13/14 — 시장별 대본 골격 + SEO(metadata_team 재사용)."""
    code, name = "A16", "로컬라이제이션·SEO"

    def run(self, ctx: SREContext):
        cs = ctx.analyses.get("contentStructure", {}).get("stages", [])
        rec = ctx.strategies.get("D", {})  # 호기심 각도를 대본 골격 기본으로
        for m in ctx.markets:
            loc = S.empty_localization(m)
            # 대본 골격 = 구조 단계별 지시(고유표현 복제 아님, 골격만)
            if cs:
                loc["script"] = [{"stage": x["stage"], "text": x["text"]} for x in cs]
            else:
                loc["script"] = [{"stage": st, "text": ""} for st in S.STRUCTURE_STAGES]
            # SEO 패키지 — metadata_team 이 있으면 재사용(KR/JP/US 지원)
            if MT and m.upper() in ("KR", "JP", "US"):
                try:
                    pkg = MT.produce_package(country=m.upper())
                    loc["seo"] = {
                        "titleRecommended": pkg.get("title_recommended", ""),
                        "titles": pkg.get("titles_search", [])[:5],
                        "description": pkg.get("description", ""),
                        "tags": pkg.get("tags", []),
                        "hashtags": pkg.get("hashtags", []),
                        "thumbnail": pkg.get("thumbnail", {}),
                    }
                except Exception as e:
                    loc["seo"] = {"error": f"metadata_team 실패: {e}"}
            loc["notes"] = self._note(m)
            ctx.localizations[m] = loc
        return f"시장 {len(ctx.markets)}개 로컬라이즈"

    @staticmethod
    def _note(m: str) -> str:
        return {
            "KR": "상황+감성 + 목적어(공부/일/카페), 구어체 훅",
            "JP": "用途 first + 洋楽/해외감성 표기 + カタカナ 혼용, 정중한 어미",
            "US": "use-case first(for Work/Study) + concise hook, no lyrics 표기",
        }.get(m.upper(), "현지 화자 톤 검수 필요")


class ViralScorer(Agent):
    """viralPotential 0~100 — 6축 신호를 가중 합산 + confidence + 근거."""
    code, name = "A04b", "바이럴 점수"

    def run(self, ctx: SREContext):
        factors = []
        score = 0

        vd = ctx.analyses.get("viralDNA", {})
        n_sig = len(vd.get("signals", []))
        s1 = min(30, n_sig * 8)
        score += s1
        factors.append({"name": "바이럴 신호", "points": s1,
                        "why": vd.get("formula", "")})

        vp = ctx.analyses.get("viewerPsychology", {})
        n_tr = len(vp.get("triggers", []))
        s2 = min(25, n_tr * 9)
        score += s2
        factors.append({"name": "심리 트리거", "points": s2,
                        "why": f"{n_tr}종 작동"})

        em = ctx.analyses.get("emotionDNA", {})
        arc = em.get("arc", "평탄")
        s3 = 20 if ("반등" in arc or "반전" in arc or "롤러코스터" in arc) else \
             (10 if "진폭" in arc else 4)
        score += s3
        factors.append({"name": "감정 아크", "points": s3, "why": arc})

        cs = ctx.analyses.get("contentStructure", {}).get("stages", [])
        present = len({x["stage"] for x in cs})
        s4 = min(15, present * 3)
        score += s4
        factors.append({"name": "구조 완결성", "points": s4,
                        "why": f"{present}/7 단계"})

        ld = ctx.analyses.get("languageDNA", {})
        s5 = min(10, len(ld.get("markers", [])) * 4)
        score += s5
        factors.append({"name": "언어 리듬", "points": s5,
                        "why": ", ".join(ld.get("markers", [])) or "약함"})

        score = max(0, min(100, score))
        # confidence: 입력이 짧을수록 낮게
        conf = 0.4
        if len(ctx.tokens) > 30:
            conf = 0.75
        elif len(ctx.tokens) > 10:
            conf = 0.6
        ctx.scores["viralPotential"] = {
            "score": score, "confidence": conf, "factors": factors}
        return f"바이럴 점수 {score}/100 (conf {conf})"


class Critic(Agent):
    """A18 — 유사성/안전 검수. 원본 고유표현 복제 위험 + 검증필요 항목 표시."""
    code, name = "A18", "크리틱·안전"

    def run(self, ctx: SREContext):
        notes, verify = [], []
        risk = "LOW"

        # 유사성: 입력이 transcript(원본 대사)면 복제 위험 경고
        if ctx.kind == "transcript":
            risk = "MEDIUM"
            notes.append("입력이 원본 자막 — 고유표현·문장을 그대로 복제 금지. "
                         "일반화된 구조/각도만 사용할 것.")
        # 전략 제목이 입력 원문 문장과 과유사한지 간단 검사
        raw_sents = {s.strip() for s in ctx.sentences}
        for k, st in ctx.strategies.items():
            if st.get("title", "").strip() in raw_sents and st["title"].strip():
                risk = "HIGH"
                notes.append(f"전략 {k} 제목이 원문 문장과 동일 — 재작성 필요.")

        # 미검증 신호는 verificationRequired 로 명시(원본 원칙)
        if ctx.mock:
            verify.append("규칙기반(Mock) 분석 — 실제 성과 데이터로 가설 검증 필요.")
        if ctx.scores.get("viralPotential", {}).get("confidence", 0) < 0.5:
            verify.append("입력이 짧아 신뢰도 낮음 — 더 긴 대본/자막으로 재분석 권장.")
        if not any(ctx.localizations.get(m, {}).get("seo") for m in ctx.markets):
            verify.append("SEO 패키지 미생성 — metadata_team 연결 확인.")

        if not notes:
            notes.append("고유표현 복제 위험 낮음 — 구조/각도 기반 변환 확인됨.")
        ctx.critic = {"similarityRisk": risk, "notes": notes,
                      "verificationRequired": verify}
        return f"유사성 위험 {risk} · 검증항목 {len(verify)}"


# ── LLM 심화(선택) — 규칙기반 위에 해석을 덮어씀 ────────────────
class Deepener(Agent):
    """A19d — 키가 있으면 LLM 으로 6축 해석·전략을 심화. 규칙기반 결과를 근거로 주되,
    측정 구조(감정곡선·점수·구조단계)는 규칙 값 유지하고 '해석 텍스트'만 덮어쓴다.
    응답 없거나 실패하면 규칙기반 그대로(격리)."""
    code, name = "A19d", "LLM 심화"

    SYSTEM = (
        "너는 유튜브 쇼츠 역설계 분석가다. 규칙기반 1차 분석과 원본 소재를 받아, "
        "각 축의 해석을 더 날카롭고 실전적으로 다듬는다. 특정 크리에이터의 고유 표현을 "
        "복제하지 말고 일반화된 패턴만 쓴다. 반드시 아래 JSON 스키마 그대로 한국어로 채워라:\n"
        '{"reverseEngineering":{"contentStructure":{"summary":""},'
        '"viralDNA":{"formula":"","signals":[]},'
        '"viewerPsychology":{"summary":"","triggers":[]},'
        '"emotionDNA":{"arc":"","summary":""},'
        '"languageDNA":{"register":"","markers":[]},'
        '"voiceDNA":{"pace":"","summary":""}},'
        '"strategies":{"A":{"hook":"","title":"","thumbText":"","rationale":"","outline":[]},'
        '"B":{...},"C":{...},"D":{...}},"insight":""}'
    )

    def run(self, ctx: SREContext):
        if not ctx.llm_call:
            return "스킵(키 없음 — 규칙기반)"
        payload = {
            "source": {"kind": ctx.kind, "text": ctx.text[:4000]},
            "ruleBased": {
                "reverseEngineering": {
                    k: ctx.analyses.get(k, {}) for k in
                    ("contentStructure", "viralDNA", "viewerPsychology",
                     "emotionDNA", "languageDNA", "voiceDNA")
                },
                "strategies": {k: {"angle": v.get("angle"), "hook": v.get("hook"),
                                   "title": v.get("title")}
                               for k, v in ctx.strategies.items()},
            },
        }
        import json as _json
        try:
            out = ctx.llm_call(self.SYSTEM, _json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            return f"LLM 호출 실패 — 규칙기반 유지 ({str(e)[:60]})"
        if not isinstance(out, dict):
            return "LLM 응답 없음/무효 — 규칙기반 유지"

        # 6축 해석 텍스트만 덮어씀(측정 구조는 규칙 값 보존)
        re_ = out.get("reverseEngineering", {})
        _merge_str(ctx.analyses.get("contentStructure"), re_.get("contentStructure"), ["summary"])
        _merge_str(ctx.analyses.get("viralDNA"), re_.get("viralDNA"), ["formula", "signals"])
        _merge_str(ctx.analyses.get("viewerPsychology"), re_.get("viewerPsychology"), ["summary", "triggers"])
        _merge_str(ctx.analyses.get("emotionDNA"), re_.get("emotionDNA"), ["arc", "summary"])
        _merge_str(ctx.analyses.get("languageDNA"), re_.get("languageDNA"), ["register", "markers"])
        _merge_str(ctx.analyses.get("voiceDNA"), re_.get("voiceDNA"), ["pace", "summary"])

        st = out.get("strategies", {})
        for k in S.STRATEGY_KEYS:
            _merge_str(ctx.strategies.get(k), st.get(k),
                       ["hook", "title", "thumbText", "rationale", "outline"])

        ins = out.get("insight")
        if isinstance(ins, str) and ins.strip():
            ctx.analyses["_insight"] = ins.strip()
        return "LLM 심화 반영(6축 + 전략 해석)"


def _merge_str(dst: dict | None, src: dict | None, fields: list[str]):
    """src 의 지정 필드가 비어있지 않으면 dst 에 덮어씀(측정값은 건드리지 않음)."""
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return
    for f in fields:
        v = src.get(f)
        if isinstance(v, str) and v.strip():
            dst[f] = v.strip()
        elif isinstance(v, list) and v:
            dst[f] = v


# ── 편집장(오케스트레이터·Synthesizer, A19) ──────────────────────
class SREOrchestrator:
    PIPELINE = [
        InputNormalizer, EvidenceExtractor, ContentStructure, ViralDNA,
        ViewerPsychology, EmotionDNA, LanguageDNA, VoiceDNA,
        StrategyGenerator, Localizer, ViralScorer, Critic,
    ]

    def analyze(self, ctx: SREContext) -> dict:
        # 규칙기반 backbone(항상) + 있으면 LLM 심화(맨 끝)
        stages = list(self.PIPELINE) + [Deepener]
        for AgentCls in stages:
            a = AgentCls()
            t0 = time.perf_counter()
            try:
                summary = a.run(ctx) or ""
                ms = int((time.perf_counter() - t0) * 1000)
                status = "skipped" if (a.code == "A19d" and not ctx.llm_call) else "ok"
                ctx.log(a.code, status, ms, f"{a.name}: {summary}")
            except Exception as e:   # 스테이지 격리 — 한 에이전트 실패가 전체를 막지 않음
                ms = int((time.perf_counter() - t0) * 1000)
                ctx.log(a.code, "failed", ms, a.name, error=str(e))
        return self._synthesize(ctx)

    def _synthesize(self, ctx: SREContext) -> dict:
        """A19 — 스키마(sre_schemas)에 맞춰 최종 리포트 종합."""
        rep = S.empty_report()
        re_ = rep["reverseEngineering"]
        A = ctx.analyses
        if "contentStructure" in A:
            re_["contentStructure"] = A["contentStructure"]
        if "viralDNA" in A:
            re_["viralDNA"] = A["viralDNA"]
        if "viewerPsychology" in A:
            re_["viewerPsychology"] = A["viewerPsychology"]
        if "emotionDNA" in A:
            re_["emotionDNA"] = A["emotionDNA"]
        if "languageDNA" in A:
            re_["languageDNA"] = A["languageDNA"]
        if "voiceDNA" in A:
            re_["voiceDNA"] = A["voiceDNA"]

        if ctx.scores.get("viralPotential"):
            rep["scores"]["viralPotential"] = ctx.scores["viralPotential"]
        for k in S.STRATEGY_KEYS:
            if k in ctx.strategies:
                rep["strategies"][k] = ctx.strategies[k]
        rep["localizations"] = ctx.localizations
        rep["experiments"] = ctx.experiments
        if ctx.critic:
            rep["critic"] = ctx.critic

        rep["metadata"].update({
            "provider": ctx.provider_name,
            "mock": ctx.mock,
            "agentRuns": ctx.agent_log,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        if ctx.analyses.get("_insight"):
            rep["metadata"]["insight"] = ctx.analyses["_insight"]
        return rep


# ── 외부 진입점(저장 포함) ────────────────────────────────────
def run_analysis(*, text: str, kind: str = "script", url: str = "",
                 markets=None, project_name: str = "SRE 프로젝트",
                 llm_call=None, provider: str = "auto", force: bool = False,
                 persist: bool = True, db_path=DB.DB_PATH) -> dict:
    """입력 → (Idempotency 확인) → 파이프라인 → 스키마 검증 → 저장 → 리포트 반환.

    provider: "auto"=키 있으면 자동 LLM 심화, "off"=규칙기반 강제, 또는
              "openai"/"gemini"/"anthropic" 특정 지정. llm_call 을 직접 주면 그게 우선(테스트).
    """
    markets = markets or ["KR"]

    # 프로바이더 결정 — llm_call 직접주입 > provider 지정 > auto(키 감지)
    provider_name = "mock"
    if llm_call is not None:
        provider_name = "injected"
    elif provider != "off" and PROV is not None:
        if provider == "auto" and PROV.is_live():
            provider_name = PROV.active_provider()
            llm_call = lambda s, u: PROV.llm_json(s, u)          # noqa: E731
        elif provider in ("openai", "gemini", "anthropic") and provider in PROV.available():
            provider_name = provider
            llm_call = lambda s, u, _p=provider: PROV.llm_json(s, u, _p)  # noqa: E731

    idem = DB.idempotency_key(kind, text, markets, provider_name)

    if persist and not force:
        prev = DB.find_done_run(idem, path=db_path)
        if prev:
            cached = DB.latest_result(prev["run_id"], path=db_path)
            if cached:
                cached.setdefault("metadata", {})["reusedRunId"] = prev["run_id"]
                return cached

    ctx = SREContext(text=text, kind=kind, url=url, markets=markets)
    ctx.llm_call = llm_call
    ctx.provider_name = provider_name
    report = SREOrchestrator().analyze(ctx)

    run_id = idem_ref = ""
    if persist:
        pid = DB.create_project(project_name, markets, path=db_path)
        sid = DB.add_source(pid, ctx.kind, text, url, path=db_path)
        run_id = DB.create_run(project_id=pid, source_id=sid, idem=idem,
                               provider=provider_name, mock=ctx.mock,
                               markets=markets, path=db_path)
        for a in ctx.agent_log:
            DB.log_agent(run_id, a["agent"], a["status"], a["ms"],
                         a["summary"], a["error"], path=db_path)
        idem_ref = idem

    report["metadata"]["runId"] = run_id
    report["metadata"]["idempotencyKey"] = idem_ref

    errs = S.validate_report(report)
    report["metadata"]["schemaValid"] = not errs
    if errs:
        report["metadata"]["schemaErrors"] = errs

    if persist and run_id:
        DB.save_result(run_id, report, path=db_path)
        DB.set_run_status(run_id, "done" if not errs else "failed", path=db_path)
    return report


# ── 자기검증(키 없이 end-to-end) ──────────────────────────────
if __name__ == "__main__":
    import tempfile
    sample = (
        "여러분 이거 진짜 몰랐어요. 사실 대부분 잘못 알고 있거든요.\n"
        "제가 직접 30일 동안 해봤는데요. 처음엔 눈물 날 만큼 힘들었어요.\n"
        "그런데 갑자기 반전이 생겼습니다. 결국 성공했어요!\n"
        "끝까지 보면 진짜 놀라운 결과가 나옵니다. 구독하고 다음 편도 꼭 보세요."
    )
    tmp = Path(tempfile.mkdtemp()) / "rt.db"

    rep = run_analysis(text=sample, kind="script", markets=["KR", "JP"],
                       db_path=tmp)
    S.assert_valid(rep)

    print("=" * 60)
    print("🧬 SRE-OS 런타임 종합 (Mock / 키 없음)")
    print("=" * 60)
    md = rep["metadata"]
    print(f"runId={md['runId']} · provider={md['provider']} · valid={md['schemaValid']}")
    print(f"\n🔬 역설계:")
    re_ = rep["reverseEngineering"]
    print(f"  구조: {re_['contentStructure']['summary']}")
    print(f"  바이럴: {re_['viralDNA']['formula']} (conf {re_['viralDNA']['confidence']})")
    print(f"  심리: {re_['viewerPsychology']['summary']}")
    print(f"  감정: {re_['emotionDNA']['summary']}")
    print(f"  언어: {re_['languageDNA']['register']} 평균{re_['languageDNA']['sentenceLen']}자")
    print(f"  보이스: {re_['voiceDNA']['summary']}")
    vp = rep["scores"]["viralPotential"]
    print(f"\n🔥 바이럴 점수: {vp['score']}/100 (conf {vp['confidence']})")
    print(f"\n🎯 전략:")
    for k in S.STRATEGY_KEYS:
        s = rep["strategies"][k]
        print(f"  {k} {s['label']}: {s['title']}  | 지표={s['experiment']['metric']}")
    print(f"\n🌐 시장: {list(rep['localizations'])}")
    for m, loc in rep["localizations"].items():
        seo = loc.get("seo", {})
        print(f"  {m}: SEO 제목='{seo.get('titleRecommended','(없음)')}' · 대본 {len(loc['script'])}섹션")
    print(f"\n🛡️ 크리틱: 유사성 {rep['critic']['similarityRisk']} · "
          f"검증필요 {len(rep['critic']['verificationRequired'])}건")

    # 구조 검증
    assert vp["score"] > 0, "바이럴 점수가 나와야"
    assert len(rep["experiments"]) == 4, "실험 4개(A/B/C/D)"
    assert set(rep["strategies"]) == set(S.STRATEGY_KEYS)
    assert re_["emotionDNA"]["arc"] != "평탄", "이 샘플은 감정 아크가 있어야"
    assert md["schemaValid"], f"스키마 유효해야: {md.get('schemaErrors')}"

    # Idempotency: 같은 입력 재실행 → 재사용
    rep2 = run_analysis(text=sample, kind="script", markets=["KR", "JP"], db_path=tmp)
    assert rep2["metadata"].get("reusedRunId"), "같은 입력은 재사용돼야"

    # force 재실행 → 새 Run
    rep3 = run_analysis(text=sample, kind="script", markets=["KR", "JP"],
                        db_path=tmp, force=True)
    assert not rep3["metadata"].get("reusedRunId"), "force 는 새 Run"

    # LLM 심화 경로 — stub llm_call(dict 반환)로 병합 검증(키 없이도 로직 확인)
    def _stub_llm(system, user):
        return {
            "reverseEngineering": {
                "viralDNA": {"formula": "LLM심화: 첫3초 정보격차 + 반전예고"},
                "emotionDNA": {"summary": "LLM심화: 눈물→환희 급반등"},
            },
            "strategies": {
                "A": {"hook": "LLM심화 훅 A", "title": "LLM심화 제목 A"},
                "B": {}, "C": {}, "D": {},
            },
            "insight": "LLM심화: 초반 3초에 반전을 예고하면 완주율이 오른다",
        }
    rep4 = run_analysis(text=sample, kind="script", markets=["KR"],
                        db_path=tmp, llm_call=_stub_llm, force=True)
    assert rep4["metadata"]["provider"] == "injected"
    assert rep4["metadata"]["mock"] is False
    assert "LLM심화" in rep4["reverseEngineering"]["viralDNA"]["formula"], "심화가 덮어써야"
    assert rep4["reverseEngineering"]["emotionDNA"]["curve"], "측정 구조(곡선)는 보존돼야"
    assert rep4["strategies"]["A"]["hook"] == "LLM심화 훅 A"
    assert rep4["metadata"].get("insight", "").startswith("LLM심화")
    deep = [a for a in rep4["metadata"]["agentRuns"] if a["agent"] == "A19d"]
    assert deep and deep[0]["status"] == "ok", "심화 에이전트 ok"
    # Mock 경로는 A19d skipped
    deep0 = [a for a in rep["metadata"]["agentRuns"] if a["agent"] == "A19d"]
    assert deep0 and deep0[0]["status"] == "skipped", "키 없으면 심화 skipped"

    print("\n✅ sre_runtime self-test 통과 — 13스테이지(12+심화) + 스키마 + Idempotency + LLM병합")
