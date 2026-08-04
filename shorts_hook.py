"""🎬 쇼츠 후킹 대본 생성기 — 사장님 프롬프트를 엔진화(공정사용 재구성).

사장님이 실전에서 쓰던 "한국 쇼츠 바이럴 후킹 작가" 프롬프트를 SRE 엔진에 통합.
입력: [영상 설명] + [댓글 반응] + [방향성/제목] + [톤 옵션]
출력(구조화 JSON): 댓글분석 3줄 / 후킹제목 10 / 추천 3(+이유) / 쇼츠 대본 / 5줄 TTS / 댓글유도 5

원본 프롬프트에 제가 얹은 개선:
- **구조화 JSON** 강제 → 매번 같은 형식(복붙블록·타 도구 연동). 원본은 자유텍스트였음.
- **공정사용 가드 내장** → 해석/감상/비교/댓글해석 중 최소 1개 강제 + 원본 대사 복제 금지.
- **Mock First** → 키 없어도 규칙기반으로 전 블록 채움. 키 있으면 LLM 심화.
- **카테고리 공식 주입**(선택) → 계열별 지배 트리거를 훅에 계승.

프롬프트는 레지스트리(PROMPT_V*)로 버전 고정 — 코드에 하드코딩하되 편집 가능.
llm_json 주입(=sre_provider) → 없으면 규칙기반. 순수 로직 self-test 포함.
"""
from __future__ import annotations

import re
from collections import Counter

PROMPT_VERSION = "v1"

# ── 톤 옵션(기본 = 사장님 프롬프트 값) ──────────────────────────
DEFAULT_TONE = [
    "반말 느낌", "짧고 간결하게", "감정 먼저", "설명은 과하지 않게",
    "쇼츠 TTS로 읽기 좋게", "10~20초 안에", "한 문장씩 짧게", "댓글 달고 싶게",
    "원본 매력 인정 + 내 해석/의견", "왜 좋은지 딱딱하게 말고 쇼츠 감성으로",
]

# 공정사용 요소(최소 1개 강제) — 원본 프롬프트 [작성 기준]
FAIRUSE_ELEMENTS = ["내 해석", "내 감상", "장면 비교", "댓글 반응 해석", "왜 좋아하는지 짧은 분석"]

SYSTEM = (
    "너는 한국 유튜브 쇼츠에 최적화된 바이럴 후킹 작가이자 쇼츠 대본 기획자다. "
    "제공된 영상은 해외/국내에서 반응이 있던 짧은 바이럴 영상이다. 단순 재업/복붙 소개가 "
    "아니라, 한국 시청자가 첫 1~2초에 멈추고 끝까지 보고 댓글을 남기고 싶게 '공정사용 느낌'의 "
    "쇼츠로 재구성한다. 장면 설명보다 감정·반전·공감·묘한 만족감·웃긴 포인트·댓글 반응을 "
    "중심으로 잡아라. 반드시 해석/감상/장면 비교/댓글 반응 해석/왜 좋은지 짧은 분석 중 "
    "최소 1개를 넣고, 원본의 대사·자막을 그대로 복제하지 마라(일반화된 내 해석만). "
    "말투는 실제 한국 쇼츠에서 들릴 법하게, 반말·짧게 끊어서. 제목은 설명형보다 감정·반전·"
    "궁금증이 느껴지게. **대본(script)은 한 줄이 약 1.5초에 읽히도록 아주 짧게 끊어라"
    "(한 줄 = 한 호흡, 6~14자 권장). 10~20초면 7~13줄.** 반드시 아래 JSON 스키마 그대로 "
    "한국어로 채워라(코드펜스 금지):\n"
    '{"commentAnalysis":{"emotion":"","keywords":[],"coreReason":""},'
    '"titles":["10개"],"top3":[{"title":"","why":""}],'
    '"script":["한 문장씩 짧게, 10~20초 분량"],'
    '"tts5":["5줄, 리듬감"],"commentBait":["5개, 자기 생각 남기고 싶게"]}'
)


def build_prompt(video_desc: str, comments: str = "", direction: str = "",
                 tone: list[str] | None = None, extra_notes: str = "") -> str:
    """LLM 에 줄 user 프롬프트 조립(사장님 [입력]/[톤]/[기준] 구조 유지)."""
    tone = tone or DEFAULT_TONE
    parts = [
        "[영상 설명]", video_desc.strip() or "(설명 없음)", "",
        "[댓글 반응]", comments.strip() or "(댓글 없음 — 영상 설명에서 감정 추론)", "",
        "[내가 쓰고 싶은 제목/방향성]", direction.strip() or "(자유 — 감정·반전 우선)", "",
        "[원하는 톤]", " · ".join(tone), "",
        "[공정사용 필수] 다음 중 최소 1개 포함: " + ", ".join(FAIRUSE_ELEMENTS),
    ]
    if extra_notes.strip():
        parts += ["", "[이 계열의 검증된 승리공식 — 훅에 계승]", extra_notes.strip()]
    return "\n".join(parts)


# ── 규칙기반 폴백(키 없이 전 블록 채움) ─────────────────────────
_LAUGH = ("ㅋㅋ", "ㅎㅎ", "웃", "빵터", "개웃", "미쳤")
_WARM = ("감동", "눈물", "따뜻", "좋다", "좋음", "사랑", "설레", "힐링", "귀엽")
_WOW = ("대박", "ㄷㄷ", "소름", "쩐다", "미쳤", "실화", "레전드", "지린")
_STOP = {"이거", "진짜", "그냥", "너무", "이건", "저건", "완전", "약간", "근데", "그리고",
         "https", "www", "youtube", "com", "shorts"}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w가-힣]+", (text or "").lower())


def _emotion(comments: str) -> str:
    t = comments
    if any(k in t for k in _LAUGH):
        return "웃김·유쾌 (빵 터지는 재미)"
    if any(k in t for k in _WARM):
        return "따뜻함·감동 (뭉클·힐링)"
    if any(k in t for k in _WOW):
        return "놀람·감탄 (ㄷㄷ·소름)"
    return "묘한 만족감·몰입 (설명 안 되는 좋음)"


def _keywords(comments: str, desc: str, k: int = 6) -> list[str]:
    c = Counter(w for w in _tokens(comments + " " + desc)
                if len(w) >= 2 and w not in _STOP)
    return [w for w, _ in c.most_common(k)]


def _rule_titles(desc: str, direction: str, emotion: str) -> list[str]:
    kws = _keywords("", desc, 3)
    core = direction.strip() or (kws[0] if kws else "이 장면")
    base = [
        f"{core} 이거 나만 좋아함?",
        f"설명은 안 되는데 그냥 좋음 ㅋㅋ",
        f"{core} 이 장면에서 멈췄다;;",
        f"이거 보고 댓글 안 달 수가 없음",
        f"{core} 진짜 이래서 터진 거였네 ㄷㄷ",
        f"솔직히 이거 감성 미쳤지 않냐",
        f"끝까지 봐야 이해되는 영상",
        f"{core} 마지막에 소름 돋음",
        f"이걸 왜 계속 돌려보게 되지",
        f"{core} 이 반전 예상한 사람?",
    ]
    return base[:10]


def _rule_script(desc: str, emotion: str, direction: str) -> list[str]:
    core = (direction.strip() or "이 장면")
    # 한 줄 = 한 호흡(약 1.5초). 짧게 끊음.
    return [
        "잠깐, 이거 봐.",
        "처음엔 별거 아닌 줄.",
        "근데 여기서 멈췄어.",
        f"{core}.",
        "이게 진짜 포인트야.",
        "설명은 안 되는데,",
        "그냥 계속 보게 됨.",
        "너도 느껴지지?",
    ]


def with_timecodes(lines: list[str], pace: float = 1.5) -> list[dict]:
    """대본 각 줄에 시작 시각 부여(한 줄당 pace 초). 쇼츠 TTS 자막 타이밍용."""
    out = []
    for i, ln in enumerate(lines):
        t = round(i * pace, 2)
        mm, ss = divmod(t, 60)
        label = f"{int(mm):02d}:{ss:04.1f}" if mm else f"{ss:.1f}s"
        out.append({"at": t, "label": label, "line": ln})
    return out


def _srt_ts(sec: float) -> str:
    """초 → SRT 타임스탬프 HH:MM:SS,mmm."""
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(lines: list[str], pace: float = 1.5, gap: float = 0.0) -> str:
    """대본 줄들 → SRT 자막(한 줄당 pace 초). 캡컷/프리미어에 바로 임포트.

    gap>0 이면 자막 사이 간격(초). 빈 줄은 건너뛴다.
    """
    blocks, idx, t = [], 1, 0.0
    for ln in lines:
        ln = (ln or "").strip()
        if not ln:
            continue
        start, end = t, t + pace
        blocks.append(f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{ln}")
        idx += 1
        t = end + gap
    return "\n\n".join(blocks) + "\n"


def _rule_tts5(desc: str, direction: str) -> list[str]:
    core = direction.strip() or "이 장면"
    return [
        "이거 그냥 지나치지 마.",
        f"{core}, 여기서 멈췄다.",
        "이 부분이 진짜 핵심.",
        "설명은 안 되는데 좋음.",
        "너는 어땠어?",
    ]


def _rule_bait() -> list[str]:
    return [
        "이거 나만 기분 좋아짐?",
        "너희는 어느 장면이 제일 좋았음?",
        "이거 진짜 감성 미쳤지 않냐?",
        "솔직히 몇 번 돌려봤는지 댓글 ㄱㄱ",
        "이 느낌 아는 사람 손?",
    ]


def _rule_based(video_desc: str, comments: str, direction: str) -> dict:
    emotion = _emotion(comments or video_desc)
    kws = _keywords(comments, video_desc)
    return {
        "commentAnalysis": {
            "emotion": emotion,
            "keywords": kws,
            "coreReason": "장면 자체보다 '왜 멈춰서 봤는지'(감정·묘한 만족감)가 끌리는 핵심.",
        },
        "titles": _rule_titles(video_desc, direction, emotion),
        "top3": [
            {"title": "설명은 안 되는데 그냥 좋음 ㅋㅋ", "why": "궁금증+공감 동시 자극, 클릭 부담 0."},
            {"title": (direction.strip() or "이 장면") + " 이거 나만 좋아함?",
             "why": "'나만?' 이 댓글을 부른다(공감 유도)."},
            {"title": "끝까지 봐야 이해되는 영상", "why": "완주 유도 — 3초 이탈 방지."},
        ],
        "script": _rule_script(video_desc, emotion, direction),
        "tts5": _rule_tts5(video_desc, direction),
        "commentBait": _rule_bait(),
        "_engine": "rule",
    }


# ── 외부 진입점 ───────────────────────────────────────────────
def generate(video_desc: str, comments: str = "", direction: str = "",
             tone: list[str] | None = None, extra_notes: str = "",
             pace: float = 1.5, llm_json=None) -> dict:
    """영상+댓글+방향 → 쇼츠 후킹 세트. llm_json(system,user)->dict 있으면 LLM, 없으면 규칙기반.

    LLM 결과는 규칙기반을 backbone 으로 병합(누락 필드 방어) → 항상 전 블록 채움.
    대본은 한 줄당 pace(기본 1.5)초로 타임코드 부여(scriptTimed·totalSec).
    """
    base = _rule_based(video_desc, comments, direction)
    if not llm_json:
        return _finalize(base, pace)
    user = build_prompt(video_desc, comments, direction, tone, extra_notes)
    try:
        out = llm_json(SYSTEM, user)
    except Exception:
        out = None
    if not isinstance(out, dict):
        base["_engine"] = "rule(llm 실패 폴백)"
        return _finalize(base, pace)

    # LLM 값으로 덮되, 비면 규칙기반 유지(스키마 100% 보장)
    def pick(key, sub=None):
        v = out.get(key)
        if sub is not None:
            v = (v or {}).get(sub) if isinstance(out.get(key), dict) else None
        return v

    ca = out.get("commentAnalysis") or {}
    merged = {
        "commentAnalysis": {
            "emotion": ca.get("emotion") or base["commentAnalysis"]["emotion"],
            "keywords": ca.get("keywords") or base["commentAnalysis"]["keywords"],
            "coreReason": ca.get("coreReason") or base["commentAnalysis"]["coreReason"],
        },
        "titles": (out.get("titles") or [])[:10] or base["titles"],
        "top3": (out.get("top3") or [])[:3] or base["top3"],
        "script": out.get("script") or base["script"],
        "tts5": (out.get("tts5") or [])[:5] or base["tts5"],
        "commentBait": (out.get("commentBait") or [])[:5] or base["commentBait"],
        "_engine": "llm",
    }
    return _finalize(merged, pace)


def _finalize(result: dict, pace: float) -> dict:
    """대본에 1.5초 페이스 타임코드 부여 + 총 길이 계산."""
    lines = result.get("script", [])
    result["pace"] = pace
    result["scriptTimed"] = with_timecodes(lines, pace)
    result["totalSec"] = round(len(lines) * pace, 1)
    return result


# ── 🔊 TTS (한국어 음성) — OpenAI tts-1 ────────────────────────
# OpenAI TTS 는 한국어 지원. VOICEVOX(일본어)와 달리 쇼츠 한국어 낭독에 적합.
TTS_VOICES = [
    {"id": "nova", "name": "Nova (밝고 또렷, 여성)"},
    {"id": "shimmer", "name": "Shimmer (부드러운 여성)"},
    {"id": "alloy", "name": "Alloy (중성·차분)"},
    {"id": "onyx", "name": "Onyx (저음 남성)"},
    {"id": "echo", "name": "Echo (남성)"},
    {"id": "fable", "name": "Fable (내레이션형)"},
]


def synthesize(text: str, voice: str = "nova", api_key: str | None = None,
               fmt: str = "mp3", speed: float = 1.0) -> bytes | None:
    """대본 텍스트 → 한국어 음성 bytes. 키 없거나 실패하면 None(폴백 신호).

    쇼츠 낭독은 연속 오디오로 나오고, 자막 타이밍(1.5초)은 SRT 가 담당한다.
    """
    key = (api_key or "").strip()
    text = (text or "").strip()
    if not key or not text:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.audio.speech.create(
            model="tts-1", voice=voice if voice in {v["id"] for v in TTS_VOICES} else "nova",
            input=text[:4000], response_format=fmt,
            speed=min(4.0, max(0.25, speed)))
        return resp.content                      # bytes
    except Exception:
        return None


# ── 자기검증 ──────────────────────────────────────────────────
if __name__ == "__main__":
    desc = ("오래된 흑백 사진을 AI로 복원하니 갑자기 컬러 인물이 살아 움직이는 것처럼 보임. "
            "마지막에 할머니가 웃는 장면.")
    comments = "와 이거 실화냐 ㄷㄷ / 눈물 남 진짜 / 옛날이랑 요즘 복원 수준 차이 미쳤다 ㅋㅋ / 할머니 웃는 거 뭉클"

    # 규칙기반
    r = generate(desc, comments, direction="옛날과 달라진 요즘 복원 수준 ㄷㄷ")
    assert r["_engine"] == "rule"
    assert len(r["titles"]) == 10 and len(r["top3"]) == 3
    assert len(r["tts5"]) == 5 and len(r["commentBait"]) == 5
    assert r["script"] and r["commentAnalysis"]["keywords"]
    # 1.5초 페이스 타임코드
    assert r["pace"] == 1.5 and len(r["scriptTimed"]) == len(r["script"])
    assert r["scriptTimed"][0]["at"] == 0.0 and r["scriptTimed"][1]["at"] == 1.5
    assert r["totalSec"] == round(len(r["script"]) * 1.5, 1)
    print("대본 타이밍:", [(x["label"], x["line"]) for x in r["scriptTimed"][:3]], f"… 총 {r['totalSec']}초")
    print("감정:", r["commentAnalysis"]["emotion"])
    print("키워드:", r["commentAnalysis"]["keywords"])
    print("추천 제목:", r["top3"][0]["title"], "—", r["top3"][0]["why"])
    print("TTS 5줄:", r["tts5"])

    # LLM stub(dict 반환) → 병합
    def _stub(system, user):
        assert "공정사용" in system and "영상 설명" in user
        return {"commentAnalysis": {"emotion": "감탄", "keywords": ["복원", "할머니"],
                                    "coreReason": "시간을 되돌린 듯한 감동"},
                "titles": [f"T{i}" for i in range(10)],
                "top3": [{"title": "A", "why": "x"}, {"title": "B", "why": "y"},
                         {"title": "C", "why": "z"}],
                "script": ["s1", "s2"], "tts5": [f"t{i}" for i in range(5)],
                "commentBait": [f"b{i}" for i in range(5)]}
    r2 = generate(desc, comments, direction="복원", llm_json=_stub)
    assert r2["_engine"] == "llm" and r2["commentAnalysis"]["emotion"] == "감탄"
    assert len(r2["titles"]) == 10 and r2["script"] == ["s1", "s2"]

    # LLM 실패 → 규칙기반 폴백
    r3 = generate(desc, comments, llm_json=lambda s, u: None)
    assert r3["_engine"].startswith("rule") and len(r3["titles"]) == 10

    # build_prompt 에 카테고리 공식 주입
    p = build_prompt(desc, comments, "복원", extra_notes="지배 트리거: 과장/극단, 호기심 격차")
    assert "승리공식" in p and "과장/극단" in p

    # SRT — 1.5초 페이스, 캡컷용
    srt = to_srt(["잠깐, 이거 봐.", "여기서 멈췄어.", "", "너도 느껴지지?"], pace=1.5)
    assert "00:00:00,000 --> 00:00:01,500" in srt
    assert "00:00:01,500 --> 00:00:03,000" in srt   # 빈 줄 건너뛰고 연속
    assert srt.count("-->") == 3, "빈 줄 제외 3개 자막"
    print("\nSRT 미리보기:\n" + srt)

    # TTS — 키 없으면 None(폴백), 빈 텍스트도 None
    assert synthesize("안녕", api_key="") is None
    assert synthesize("", api_key="sk-x") is None
    assert len(TTS_VOICES) >= 4
    print("✅ TTS 폴백(무키/빈텍스트) 확인")

    print("✅ shorts_hook self-test 통과 — 규칙기반/LLM/폴백/공식주입/SRT/TTS")
