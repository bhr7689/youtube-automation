"""✍️ 대본 작성기 — 시선 비틀기 + 교육 가치 + 3초 훅 + 원본 앵커.

사용자 확정 워크플로(2026-07-05):
  입력 = 원본 롱폼 자막(시간정보) + 터진 숏폼 대본 + 그 댓글
  출력 = 새 대본. 조건:
    ① 터진 숏폼 대본과 '일치 금지' (유사도 게이트, 초과 시 구조 바꿔 재생성)
    ② 교육적 가치 필수 (인생 교훈·심리·지혜 관점으로 시선 비틀기)
    ③ 첫 문장 3초 훅 (script_corpus 학습 규칙 주입)
    ④ 각 문장에 원본 타임스탬프 앵커 [MM:SS] → 컷편집이 정확히 그 장면을 자름

Gemini 없으면 결정론적 데모 폴백(앵커·게이트 로직은 동일하게 작동 → 파이프라인 검증).
"""
from __future__ import annotations

import re

import script_corpus
import translator

SIM_THRESHOLD = 0.35   # 게이트②: 터진 대본과 3-gram 유사도 상한

ANGLES = {
    "lesson":  "인생 교훈 — 이 장면이 가르쳐 주는 삶의 지혜를 중심으로",
    "psychology": "심리 분석 — 인물의 마음과 행동 이유를 풀어내는 시점으로",
    "hidden":  "숨은 디테일 — 대부분이 놓친 장면 뒤의 사실을 중심으로",
    "senior":  "시니어 공감 — 부모·세월·가족의 시선으로 재해석",
}


# ── 게이트②: 유사도 (문자 3-gram 자카드 — 언어 무관) ────

def _ngrams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"[\s\W]+", "", text.lower())
    return {t[i:i + n] for i in range(len(t) - n + 1)} if len(t) >= n else {t}


def similarity(a: str, b: str) -> float:
    A, B = _ngrams(a), _ngrams(b)
    if not A or not B:
        return 0.0
    return round(len(A & B) / len(A | B), 3)


# ── 앵커 파싱 ───────────────────────────────────────────

_ANCHOR = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.+)$")


def parse_anchored(script: str) -> list[dict]:
    """'[MM:SS] 문장' 줄들 → [{jp/text, src_anchor_ms}]. 앵커 없는 줄은 anchor=None."""
    out = []
    for ln in script.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = _ANCHOR.match(ln)
        if m:
            ms = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
            out.append({"text": m.group(3).strip(), "src_anchor_ms": ms})
        else:
            out.append({"text": ln, "src_anchor_ms": None})
    return out


def _fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"[{s // 60:02d}:{s % 60:02d}]"


# ── 대본 생성 ───────────────────────────────────────────

def write_script(source_transcript: list[dict], viral_script: str = "",
                 comments: list[str] | None = None, angle: str = "lesson",
                 language: str = "ko", loop: bool = True) -> dict:
    """시선 비틀기 대본 생성 + 게이트(훅·유사도) 통과 확인.

    source_transcript: 원본 롱폼 자막 [{t,dur,text}] — 사실 그라운딩 + 앵커 원천.
    viral_script: 터진 숏폼 대본(참고·일치 금지 대상). comments: 그 댓글.
    """
    rules_block = script_corpus.rules_prompt_block() or ""
    angle_desc = ANGLES.get(angle, ANGLES["lesson"])
    comments = comments or []

    script = _generate(source_transcript, viral_script, comments,
                       angle_desc, rules_block, language, loop)
    sim = similarity(script, viral_script) if viral_script else 0.0
    retried = False
    if viral_script and sim > SIM_THRESHOLD:
        # 게이트② 초과 → 구조를 바꿔 1회 재생성
        retried = True
        script = _generate(source_transcript, viral_script, comments,
                           angle_desc + " (앞의 시도와 전개 순서를 완전히 바꿔서)",
                           rules_block, language, loop)
        sim = similarity(script, viral_script)

    sentences = parse_anchored(script)
    anchored = sum(1 for s in sentences if s["src_anchor_ms"] is not None)
    first = sentences[0]["text"] if sentences else ""
    return {
        "script": script,
        "sentences": sentences,
        "gates": {
            "similarity": sim, "similarity_ok": sim <= SIM_THRESHOLD,
            "similarity_retried": retried,
            "hook_types": script_corpus.classify_hook(first),
            "hook_len": len(first),
            "anchored_pct": round(100 * anchored / max(len(sentences), 1)),
        },
        "angle": angle,
        "gemini": translator.has_gemini(),
    }


def _generate(transcript, viral_script, comments, angle_desc, rules_block,
              language, loop: bool = True) -> str:
    src_lines = "\n".join(f"{_fmt_ts(s['t'])} {s['text']}" for s in transcript[:150])
    top_comments = "\n".join(f"- {c}" for c in comments[:10])
    lang_name = {"ko": "한국어", "ja": "일본어", "en": "영어"}.get(language, "한국어")
    prompt = (
        f"너는 시니어 대상 감동·교훈 쇼츠 채널의 작가다. {lang_name}로 쇼츠 대본을 써라.\n\n"
        f"[원본 롱폼 자막 — 유일한 사실 근거. 여기 없는 사실 창작 금지]\n{src_lines}\n\n"
        + (f"[터진 숏폼 대본 — 참고만. 표현·전개를 그대로 쓰면 안 됨(일치 금지)]\n{viral_script}\n\n" if viral_script else "")
        + (f"[그 영상의 댓글 — 시청자가 반응한 지점]\n{top_comments}\n\n" if top_comments else "")
        + (rules_block + "\n\n" if rules_block else "")
        + f"[시선 비틀기] {angle_desc} 다시 이야기하라.\n"
        "[필수 조건]\n"
        "1. 첫 문장 = 3초 훅. 스크롤을 멈추게.\n"
        "2. 교육적 가치(교훈·지혜·심리 통찰)가 뼈대일 것.\n"
        "3. 터진 대본과 문장·전개가 겹치지 않게.\n"
        "4. 각 문장 앞에 그 문장이 가리키는 원본 장면의 타임스탬프를 [MM:SS] 로 붙여라.\n"
        "   (원본 자막의 시간에서 고를 것. 모든 문장에 반드시.)\n"
        "5. 7~12문장, 마지막은 따뜻한 마무리.\n"
        + ("6. 🔁 루프 구조: 마지막 문장이 첫 문장(훅)으로 자연스럽게 이어지게 — "
           "영상이 다시 시작돼도 어색하지 않아야 재시청이 돈다.\n" if loop else "")
        + "\n[대본]"
    )
    out = translator._gemini(prompt, temperature=0.8)
    return out if out else _demo_script(transcript, angle_desc)


def _demo_script(transcript, angle_desc) -> str:
    """데모: 원본 자막에서 실제 타임스탬프를 골라 앵커 형식 그대로 재현."""
    picks = transcript[:: max(len(transcript) // 8, 1)][:8] if transcript else []
    lines = ["[00:00] 이 3초 뒤, 모두가 울게 됩니다."]
    tmpl = ["여기서 그는 아무 말도 하지 못했다고 합니다.",
            "심리학에서는 이 순간을 '억눌린 그리움의 해방'이라 부릅니다.",
            "하지만 진짜 교훈은 그 다음 장면에 있습니다.",
            "우리가 놓치고 사는 것은 대단한 것이 아니라, 곁에 있는 사람입니다.",
            "그 한마디가 40년의 세월을 녹였다고 전해집니다.",
            "지금 떠오르는 그 사람에게, 오늘 안부를 전해 보세요.",
            "늦었다고 생각한 순간이, 사실 가장 빠른 때입니다."]
    for i, seg in enumerate(picks[1:8]):
        lines.append(f"{_fmt_ts(seg['t'])} {tmpl[i % len(tmpl)]}")
    lines.append(f"{_fmt_ts(picks[-1]['t'] if picks else 0)} 오늘도 수고 많으셨습니다.")
    return "\n".join(lines)


# ── 앵커 유지 일본어 변환 (문장별 1:1) ──────────────────

def translate_anchored(sentences: list[dict], target: str = "ja") -> list[dict]:
    """앵커를 유지한 채 문장별 번역. Gemini 없으면 데모 일본어."""
    texts = [s["text"] for s in sentences]
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"{translator.SENIOR_JA_TONE}\n\n다음 번호 문장들을 같은 번호로 일본어 번역하라. "
        f"번호와 문장만 출력.\n\n{numbered}"
    )
    out = translator._gemini(prompt, temperature=0.4)
    ja_map: dict[int, str] = {}
    if out:
        for ln in out.splitlines():
            m = re.match(r"^(\d+)[.)]\s*(.+)$", ln.strip())
            if m:
                ja_map[int(m.group(1))] = m.group(2).strip()
    demo_ja = ["この3秒後、誰もが涙します。", "彼は何も言えなかったそうです。",
               "心理学ではこれを「抑えた想いの解放」と呼びます。",
               "本当の教訓は次の場面にあります。",
               "私たちが見失っているのは、そばにいる人です。",
               "その一言が40年の歳月を溶かしたと伝えられています。",
               "今、思い浮かんだあの人に安否を伝えてみてください。",
               "遅いと思った瞬間が、実は一番早い時です。", "お疲れさまでした。"]
    out_sents = []
    for i, s in enumerate(sentences):
        jp = ja_map.get(i + 1) or demo_ja[i % len(demo_ja)]
        out_sents.append({"id": i + 1, "src": s["text"], "jp": jp,
                          "src_anchor_ms": s.get("src_anchor_ms")})
    return out_sents
