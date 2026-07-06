"""번역 엔진 — 영/한 대본 → 시니어 친화 일본어 쇼츠 대본.

설계(ideas/japan_senior_heartwarming.md):
  ① 입력(EN/KO) → ② 한국어 쇼츠 재구성 → ③ 일본어 번역(です/ます 정중체 + 완충표현
  + 금지어 필터) → 문장 단위 분해(TTS·자막의 기본 단위).

GEMINI_API_KEY 가 있으면 Gemini, 없으면 결정론적 데모 폴백(문장 구조는 동일).
"""
from __future__ import annotations

import os
import re

# 시니어 친화 일본어 톤 지시 (게이트3 규칙 일부 공유)
SENIOR_JA_TONE = (
    "일본 시니어(50~70대) 시청자를 위한 따뜻한 내레이션. です/ます 정중체. "
    "단정 대신 완충 표현(~だそうです/~のかもしれません). 과장·자극 금지. "
    "한 문장은 짧게(자막 한 줄에 맞게). 마지막은 긍정 어휘(お疲れさまでした 등)."
)
# 금지어(민감 단정) — 간단 필터
BANNED = ["반드시 낫습니다", "100% 보장", "확실히 돈을 법니다", "絶対に治る", "必ず儲かる"]


def has_gemini() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _gemini(prompt: str, temperature: float = 0.7) -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content(
            prompt, generation_config={"temperature": temperature})
        return (resp.text or "").strip()
    except Exception:
        return None


# ── 문장 분해 / 길이 추정 ───────────────────────────────

def split_sentences(text: str) -> list[str]:
    """일본어/한국어 대본을 문장 단위로 분해(TTS·자막 기본 단위)."""
    # 괄호 안 주석(로마자·직역) 줄은 제거
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("(") and s.endswith(")"):
            continue
        # 파이프(|) 구절 구분자는 공백으로
        s = s.replace("|", " ").strip()
        lines.append(s)
    out: list[str] = []
    for ln in lines:
        parts = re.split(r"(?<=[。！？!?\.])\s*", ln)
        for p in parts:
            p = p.strip()
            if p:
                out.append(p)
    return out


def estimate_duration_ms(text: str, speed: float = 1.2) -> int:
    """일본어 내레이션 대략 길이(문자수 기반). speed=재생속도."""
    n = len([c for c in text if not c.isspace()])
    base = n * 130  # ~7~8 mora/sec 근사
    return max(700, int(base / max(speed, 0.5)))


# ── 번역 단계 ───────────────────────────────────────────

def to_korean_shorts(src: str) -> str:
    """영어(또는 원문) → 쇼츠용 한국어 재구성."""
    prompt = (
        "다음 영상 자막/대본을 유튜브 쇼츠용 한국어 내레이션으로 재구성하라. "
        "3초 훅 → 궁금증 → 전개 → 여운 구조. 시니어 시청자가 편한 담백한 말투. "
        "각 장면을 짧은 문단으로. 원문에 없는 사실은 지어내지 말 것.\n\n"
        f"[원문]\n{src}\n\n[한국어 쇼츠 대본]"
    )
    out = _gemini(prompt)
    if out:
        return out
    return _demo_korean_shorts(src)


def to_korean_literal(src: str) -> str:
    prompt = (
        "다음 영어(또는 원문)를 한국어로 자연스럽게 직역하라. 의역·재구성 없이 "
        "내용 파악용으로.\n\n"
        f"[원문]\n{src}\n\n[한국어 직역]"
    )
    return _gemini(prompt) or _demo_korean_literal(src)


def to_japanese(ko_text: str) -> str:
    prompt = (
        f"{SENIOR_JA_TONE}\n\n"
        "아래 한국어 쇼츠 대본을 일본어 내레이션으로 번역하라. "
        "한 문장씩 줄바꿈. 자막으로 쓸 수 있게 자연스럽고 짧게.\n\n"
        f"[한국어]\n{ko_text}\n\n[일본어 대본]"
    )
    return _gemini(prompt) or _demo_japanese(ko_text)


def auto_translate(src: str) -> dict:
    """전자동: 원문 → 한국어 쇼츠 → 일본어 → 문장 분해."""
    ko = to_korean_shorts(src)
    ja = to_japanese(ko)
    sents = split_sentences(ja)
    return {
        "ko_literal": to_korean_literal(src),
        "ko_shorts": ko,
        "ja": ja,
        "sentences": [{"id": i + 1, "jp": s} for i, s in enumerate(sents)],
        "gemini": has_gemini(),
    }


# ── 품질 점검(게이트3-lite) ─────────────────────────────

def quality_check(ja_text: str) -> dict:
    issues = []
    for b in BANNED:
        if b in ja_text:
            issues.append({"type": "banned", "text": b,
                           "msg": f"단정·과장 표현 '{b}' — 완충 표현으로 바꾸세요."})
    # 너무 긴 문장(자막 부적합)
    for s in split_sentences(ja_text):
        if len(s) > 42:
            issues.append({"type": "too_long", "text": s[:30] + "…",
                           "msg": "문장이 길어요(42자↑) — 자막 두 줄로 나누길 권장."})
    ok = not issues
    return {"ok": ok, "issue_count": len(issues), "issues": issues[:20]}


# ── 데모 폴백 (GEMINI_API_KEY 없을 때) ──────────────────

def _demo_korean_literal(src: str) -> str:
    head = src.strip().splitlines()[0][:40] if src.strip() else "원문"
    return (
        f"[데모 직역] 원문 첫 줄: \"{head}\"\n"
        "영어 원문을 한국어로 그대로 옮긴 내용이 여기 표시됩니다.\n"
        "실제로는 GEMINI_API_KEY 를 넣으면 정확한 직역이 나옵니다."
    )


def _demo_korean_shorts(src: str) -> str:
    return (
        "40년을 떨어져 산 모자가 있었습니다.\n"
        "\"어머니를 다시 볼 수 있을까요?\" 아들은 매일 그 생각뿐이었죠.\n"
        "그리고 오늘, 스튜디오 문이 열립니다.\n"
        "두 사람은 아무 말 없이 서로를 끌어안았습니다.\n"
        "지켜보던 모두의 눈에 눈물이 고였습니다.\n"
        "늦지 않았습니다. 사랑은 언제나 그 자리에 있으니까요.\n"
        "(데모 데이터 — GEMINI_API_KEY 를 넣으면 원문 기반 실제 재구성이 나옵니다.)"
    )


def _demo_japanese(ko_text: str) -> str:
    return (
        "40年間、離れて暮らした母と息子がいました。\n"
        "「母にもう一度会えるでしょうか」息子は毎日そう思っていたそうです。\n"
        "そして今日、スタジオの扉が開きます。\n"
        "二人は何も言わず、ただ抱き合いました。\n"
        "見守っていた皆の目に、涙がにじみました。\n"
        "遅くはありません。愛はいつもそこにあるのですから。\n"
        "お疲れさまでした。"
    )
