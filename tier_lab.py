"""tier_lab.py — 조회수 구간 × 장르별 썸네일·제목 분석 순수 로직.

Streamlit 비의존 · 헤드리스 테스트 가능.
- 발행 6개월 이내 필터
- 9단계 구간(1천/3천/5천/1만/3만/5만/10만/20만/30만+) 버킷팅
- 제목 토큰·이모지·감각어·상황어·장르어 추출 및 집계 = 승리 공식
- 썸네일↔제목 일치성(휴리스틱) 채점

플레이리스트(무드·미학) 채널 1차 대상. 인물 채널에도 동작.
"""
from __future__ import annotations

import datetime as _dt
import re
from collections import Counter

# ── 9단계 구간 (절대값, 6개월 내라 나이 통제됨) ─────────────────
# (하한, 라벨) — 큰 값부터 검사
TIERS: list[tuple[int, str]] = [
    (300_000, "30만+"),
    (200_000, "20만+"),
    (100_000, "10만+"),
    (50_000, "5만+"),
    (30_000, "3만+"),
    (10_000, "1만+"),
    (5_000, "5천+"),
    (3_000, "3천+"),
    (1_000, "1천+"),
]
TIER_ORDER = [t[1] for t in TIERS] + ["1천 미만"]
LOW_TIERS = {"1천+", "3천+", "5천+"}  # 신생 초기 상승 구간


def tier_of(views: int) -> str:
    for lo, label in TIERS:
        if views >= lo:
            return label
    return "1천 미만"


# ── 6개월 이내 필터 ───────────────────────────────────────────
def _parse_date(s: str) -> _dt.date | None:
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def within_months(published: str, months: int = 6, today: _dt.date | None = None) -> bool:
    d = _parse_date(published)
    if d is None:
        return False
    today = today or _dt.date.today()
    return d >= today - _dt.timedelta(days=months * 30)


def filter_recent(videos: list[dict], months: int = 6,
                  today: _dt.date | None = None) -> list[dict]:
    return [v for v in videos if within_months(v.get("published", ""), months, today)]


def days_since(published: str, today: _dt.date | None = None) -> int | None:
    d = _parse_date(published)
    if d is None:
        return None
    return ((today or _dt.date.today()) - d).days


def views_per_day(views: int, published: str, today: _dt.date | None = None) -> float:
    """일 평균 조회수 = 바이럴 속도(신선도 보정 보조지표)."""
    dd = days_since(published, today)
    if not dd:
        return float(views)
    return round(views / dd, 1)


# ── 구간 버킷팅 ───────────────────────────────────────────────
def bucket_by_tier(videos: list[dict], today: _dt.date | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {label: [] for label in TIER_ORDER}
    for v in videos:
        views = int(v.get("views", 0) or 0)
        vv = {**v, "tier": tier_of(views),
              "vpd": views_per_day(views, v.get("published", ""), today)}
        out[vv["tier"]].append(vv)
    return out


# ── 제목 분석 어휘 사전 (한국어 플레이리스트 시드) ──────────────
SENSORY_WORDS = [
    "울컥", "소름", "먹먹", "촉촉", "잔잔", "몽글", "포근", "설렘", "아련", "그리움",
    "쓸쓸", "나른", "따뜻", "시린", "쌀쌀", "달달", "짜릿", "울림", "여운", "감성", "청량",
]
SITUATION_WORDS = [
    "새벽", "밤", "아침", "저녁", "퇴근", "출근", "드라이브", "카페", "창가", "비",
    "눈", "가을", "겨울", "봄", "여름", "휴식", "잠들기", "공부", "혼자", "일요일",
    "산책", "커피", "위스키", "노을", "야경", "바다", "여행", "파리", "도쿄", "숲",
]
GENRE_WORDS = [
    "재즈", "jazz", "로파이", "lofi", "시티팝", "citypop", "발라드", "인디", "ost",
    "피아노", "보사노바", "bossa", "어쿠스틱", "팝송", "뉴에이지", "클래식", "classical",
    "샹송", "chanson", "프렌치팝", "왈츠", "waltz", "rnb", "알앤비", "하우스", "house",
]
VOLUME_WORDS = ["시간", "연속", "모음", "베스트", "playlist", "플레이리스트", "mix", "믹스"]

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF☀-➿⭐❤]", flags=re.UNICODE)
_TOKEN_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)  # 유니코드 단어 2자+ (다국어)
_QUESTION_RE = re.compile(r"[?？]")
_EXCLAIM_RE = re.compile(r"[!！]")


def extract_emojis(text: str) -> list[str]:
    return _EMOJI_RE.findall(text or "")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text or "")


def _hits(low: str, vocab: list[str]) -> list[str]:
    return [w for w in vocab if w.lower() in low]


def analyze_title(title: str) -> dict:
    t = title or ""
    low = t.lower()
    emojis = extract_emojis(t)
    return {
        "title": t, "length": len(t), "tokens": tokenize(t),
        "emojis": emojis, "emoji_count": len(emojis),
        "sensory": _hits(low, SENSORY_WORDS), "situation": _hits(low, SITUATION_WORDS),
        "genre": _hits(low, GENRE_WORDS), "volume": _hits(low, VOLUME_WORDS),
        "question": bool(_QUESTION_RE.search(t)), "exclaim": bool(_EXCLAIM_RE.search(t)),
    }


def _pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


def aggregate_titles(videos: list[dict]) -> dict:
    """구간(또는 장르) 내 제목들의 공통 패턴 = 승리 공식 요약."""
    n = len(videos)
    if n == 0:
        return {"n": 0}
    tok, emo, sens, situ, genre, vol = (Counter() for _ in range(6))
    lengths, q, ex, analyzed = [], 0, 0, []
    for v in videos:
        a = analyze_title(v.get("title", ""))
        analyzed.append(a)
        lengths.append(a["length"])
        tok.update(a["tokens"]); emo.update(a["emojis"]); sens.update(a["sensory"])
        situ.update(a["situation"]); genre.update(a["genre"]); vol.update(a["volume"])
        q += a["question"]; ex += a["exclaim"]
    stop = {w.lower() for w in GENRE_WORDS} | {"플레이리스트", "playlist"}
    top_tok = [(w, c) for w, c in tok.most_common(30) if w.lower() not in stop][:12]
    return {
        "n": n, "avg_length": round(sum(lengths) / n, 1),
        "avg_emoji": round(sum(emo.values()) / n, 2),
        "top_tokens": top_tok, "top_emojis": emo.most_common(6),
        "sensory": sens.most_common(8), "situation": situ.most_common(8),
        "genre": genre.most_common(6), "volume": vol.most_common(5),
        "sensory_pct": _pct(sum(1 for a in analyzed if a["sensory"]), n),
        "situation_pct": _pct(sum(1 for a in analyzed if a["situation"]), n),
        "emoji_pct": _pct(sum(1 for a in analyzed if a["emojis"]), n),
        "question_pct": _pct(q, n), "exclaim_pct": _pct(ex, n),
    }


def formula_line(agg: dict) -> str:
    """집계 → 사람이 읽는 한 줄 승리 공식."""
    if not agg or agg.get("n", 0) == 0:
        return "표본 없음"
    parts = []
    if agg["situation"]:
        parts.append("상황[" + "·".join(w for w, _ in agg["situation"][:3]) + "]")
    if agg["sensory"]:
        parts.append("감각[" + "·".join(w for w, _ in agg["sensory"][:3]) + "]")
    if agg["top_emojis"]:
        parts.append("이모지 " + "".join(w for w, _ in agg["top_emojis"][:2]))
    parts.append(f"길이~{int(agg['avg_length'])}자")
    return " + ".join(parts)


def tier_report(videos: list[dict], months: int = 6,
                today: _dt.date | None = None) -> dict:
    """6개월 필터 → 구간 버킷 → 구간별 제목 공식."""
    recent = filter_recent(videos, months, today)
    buckets = bucket_by_tier(recent, today)
    report = {}
    for label in TIER_ORDER:
        vids = sorted(buckets[label], key=lambda v: v.get("views", 0), reverse=True)
        agg = aggregate_titles(vids)
        report[label] = {"videos": vids, "count": len(vids), "titles": agg,
                         "formula": formula_line(agg), "is_low": label in LOW_TIERS}
    return {"total": len(recent), "dropped_old": len(videos) - len(recent),
            "tiers": report}


# ── 썸네일 ↔ 제목 일치성 (휴리스틱, LLM 없이도 동작) ────────────
def consistency_heuristic(title: str, thumb_text: str = "",
                          thumb_tags: list[str] | None = None) -> dict:
    """썸네일 문구/태그와 제목의 정렬도. 0~100.
    감정·주제 일치는 높을수록, 정보 상보성은 '중복=낭비'로 역방향."""
    a = analyze_title(title)
    tt = analyze_title(thumb_text)
    tags = " ".join(thumb_tags or []).lower()

    title_emo, thumb_emo = set(a["sensory"]), set(tt["sensory"]) | {w for w in SENSORY_WORDS if w in tags}
    emo = 25 if (title_emo & thumb_emo) else (12 if (title_emo or thumb_emo) else 6)

    title_situ, thumb_situ = set(a["situation"]), set(tt["situation"]) | {w for w in SITUATION_WORDS if w in tags}
    topic = 25 if (title_situ & thumb_situ) else (12 if (title_situ or thumb_situ) else 6)

    title_toks, thumb_toks = set(a["tokens"]), set(tt["tokens"])
    if not thumb_toks:
        compl = 10
    else:
        ov = len(title_toks & thumb_toks) / max(1, len(thumb_toks))
        compl = 8 if ov >= 0.9 else (14 if ov == 0 else 25)

    tgt = 25 if (set(a["genre"]) & (set(tt["genre"]) | {w for w in GENRE_WORDS if w in tags})) else 14

    notes = []
    if emo < 15:
        notes.append("썸네일과 제목의 감정 톤이 다릅니다 — 같은 정서로 맞추세요.")
    if topic < 15:
        notes.append("썸네일 장면과 제목 상황이 어긋납니다 — 같은 장면을 가리키게 하세요.")
    if compl <= 8:
        notes.append("썸네일 문구가 제목과 거의 같아 정보가 낭비됩니다 — 문구엔 제목에 없는 한마디를.")
    elif compl == 14:
        notes.append("썸네일 문구가 제목과 무관합니다 — 연결고리를 만드세요.")
    if not notes:
        notes.append("감정·주제는 일치하고 문구는 새 정보를 줍니다 — 이상적입니다.")
    return {"total": emo + topic + compl + tgt, "emotion": emo, "topic": topic,
            "complement": compl, "target": tgt, "notes": notes}
