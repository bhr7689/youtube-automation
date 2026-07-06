"""📚 대본 코퍼스 — 터진 숏폼 대본 수집 + 훅·구조 규칙 학습.

사용자 확정 워크플로(2026-07-05):
  급등 숏폼 → 원본 롱폼 찾기 → 터진 대본+댓글 참고 → 시선 비틀기+교육 가치 대본
  → 대본 문장 ↔ 원본 장면 앵커 매칭 → 컷편집.
  이 모듈은 그 기반: 장르별 터진 숏폼 대본(목표 500)을 모으고,
  훅 유형·구조를 통계로 추출해 '터지는 대본 규칙'을 만든다.

'학습' = 파인튜닝 X. (1)대본별 특징 추출 → (2)코퍼스 통계 → (3)규칙 JSON
→ (4)대본 생성 프롬프트 주입. (K-Trot lyrics_library 통합 페르소나 패턴)
쇼츠에 자막 없는 경우가 많으므로 수율은 기록하고 스킵(원본 롱폼 자막 경로는 scriptwriter 쪽).
"""
from __future__ import annotations

import json
import os
import re
import statistics
from collections import Counter

import store
import youtube_client as yc

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hook_rules")


def _rules_path(genre: str = "") -> str:
    """카테고리별 규칙 파일 — 카테고리가 섞이지 않게 각자 저장."""
    safe = re.sub(r"[^\w가-힣-]", "_", genre.strip()) or "all"
    return os.path.join(RULES_DIR, f"{safe}.json")


# 하위 호환(renderer 등 외부 참조용)
RULES_PATH = _rules_path("all")

# 장르 시드 검색어 (사용자 채널 = 감동·인생교훈. 필요 시 확장)
GENRE_QUERIES = {
    "heartwarming": ["emotional reunion shorts", "heartwarming moment", "감동 실화 쇼츠",
                     "wholesome shorts", "感動 ショート"],
    "life_lesson": ["life lesson shorts", "인생 교훈 쇼츠", "wisdom shorts",
                    "motivational story shorts", "人生の教訓"],
}


# ── 훅 유형 분류 (다국어 휴리스틱 — 결정론적) ───────────

HOOK_TYPES = {
    "question":  ("질문형", "궁금증을 던져 스크롤을 멈춤"),
    "shock":     ("충격 선언형", "믿기 힘든 사실을 첫 문장에 배치"),
    "number":    ("숫자형", "구체적 숫자로 신뢰·호기심"),
    "negation":  ("금지·경고형", "'절대 ~하지 마라' 류"),
    "address":   ("호명형", "'당신/너'를 직접 부름"),
    "cliffhang": ("결말 암시형", "끝을 암시해 완주 유도"),
    "scene":     ("장면 돌입형", "설명 없이 사건 한가운데서 시작"),
}

_PAT = {
    "question": re.compile(r"[?？]$|^(왜|어떻게|무엇|누가|what|why|how|did you|have you|どうして|なぜ)", re.I),
    "shock": re.compile(r"(!|！|충격|믿을 수 없|미쳤|no way|insane|unbelievable|shocking|衝撃|信じられ)", re.I),
    "number": re.compile(r"\d"),
    "negation": re.compile(r"(절대|하지 마|말 것|never|don'?t|stop doing|してはいけない|絶対に)", re.I),
    "address": re.compile(r"(당신|여러분|너는|you |your |あなた)", re.I),
    "cliffhang": re.compile(r"(마지막|끝까지|결말|until the end|wait for|最後まで|the end will)", re.I),
}


def classify_hook(first_line: str) -> list[str]:
    types = [k for k, p in _PAT.items() if p.search(first_line.strip())]
    return types or ["scene"]


def extract_features(transcript: list[dict], duration_sec: int) -> dict:
    """대본(자막 세그먼트 리스트) → 구조 특징. transcript = [{t,dur,text},...]"""
    texts = [s.get("text", "").strip() for s in transcript if s.get("text", "").strip()]
    if not texts:
        return {}
    first = texts[0]
    total_chars = sum(len(t) for t in texts)
    return {
        "first_line": first,
        "first_len": len(first),
        "hook_types": classify_hook(first),
        "line_count": len(texts),
        "avg_line_len": round(total_chars / len(texts), 1),
        "duration_sec": duration_sec,
        "chars_per_sec": round(total_chars / max(duration_sec, 1), 1),
        "has_cta": bool(re.search(r"(구독|팔로우|subscribe|follow|フォロー|チャンネル登録)",
                                  " ".join(texts[-2:]), re.I)),
    }


# ── 수집 ───────────────────────────────────────────────

def _fetch_transcript(video_id: str) -> list[dict]:
    """youtube-transcript-api (루트 requirements 에 있음). 없거나 실패 시 []"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segs = YouTubeTranscriptApi().fetch(video_id, languages=["en", "ko", "ja"])
        return [{"t": round(s.start, 2), "dur": round(s.duration, 2), "text": s.text}
                for s in segs]
    except Exception:
        try:  # 구버전 API 호환
            from youtube_transcript_api import YouTubeTranscriptApi
            segs = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "ko", "ja"])
            return [{"t": round(s["start"], 2), "dur": round(s["duration"], 2),
                     "text": s["text"]} for s in segs]
        except Exception:
            return []


def _fetch_comments(video_id: str, n: int = 20) -> list[str]:
    if not yc.has_key():
        return []
    try:
        resp = yc._yt().commentThreads().list(
            part="snippet", videoId=video_id, order="relevance",
            maxResults=min(n, 50), textFormat="plainText").execute()
        return [it["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300]
                for it in resp.get("items", [])]
    except Exception:
        return []


def collect(genre: str = "heartwarming", target: int = 100,
            min_multiplier: float = 2.0) -> dict:
    """장르 시드 검색어로 급등 쇼츠를 모아 자막·댓글·특징을 코퍼스에 적재.

    키 없으면 데모 코퍼스 시드. 자막 없는 영상은 스킵(수율 보고).
    """
    if not yc.has_key():
        n = _seed_demo_corpus(genre)
        rules = learn_rules(genre)   # 🔄 수집 즉시 자동 재학습 — 규칙이 항상 최신
        return {"genre": genre, "added": n, "skipped_no_transcript": 0,
                "total": store.corpus_count(genre), "demo": True,
                "rules_updated": not rules.get("error"),
                "corpus_in_rules": rules.get("corpus_count", 0)}

    queries = GENRE_QUERIES.get(genre, [genre])
    added = skipped = 0
    seen: set[str] = set()
    for q in queries:
        if added >= target:
            break
        cards = yc.search_videos(q, video_type="shorts", order="viewCount",
                                 max_results=min(50, target))
        for c in cards:
            if added >= target:
                break
            vid = c["video_id"]
            if vid in seen:
                continue
            seen.add(vid)
            if (c.get("multiplier") or 0) < min_multiplier:
                continue
            tr = _fetch_transcript(vid)
            if not tr:
                skipped += 1
                continue
            feats = extract_features(tr, c.get("duration_sec", 0))
            feats["tags"] = c.get("keywords", [])   # 업로더 태그 = L1 분류 신호 원천
            store.corpus_add({
                "video_id": vid, "genre": genre, "title": c["title"],
                "channel_title": c["channel_title"], "views": c["views"],
                "multiplier": c.get("multiplier"), "duration_sec": c.get("duration_sec", 0),
                "lang": "", "transcript": tr,
                "comments": _fetch_comments(vid), "features": feats,
            })
            added += 1
    rules = learn_rules(genre)   # 🔄 수집 즉시 자동 재학습
    return {"genre": genre, "added": added, "skipped_no_transcript": skipped,
            "total": store.corpus_count(genre), "demo": False,
            "rules_updated": not rules.get("error"),
            "corpus_in_rules": rules.get("corpus_count", 0)}


# ── 규칙 학습 (코퍼스 통계 → hook_rules.json) ───────────

def learn_rules(genre: str = "") -> dict:
    items = store.corpus_list(genre)
    feats = [i["features"] for i in items if i.get("features")]
    if not feats:
        return {"error": "코퍼스가 비어 있어요 — 먼저 수집하세요.", "count": 0}

    hook_counter: Counter = Counter()
    for f in feats:
        for h in f.get("hook_types", []):
            hook_counter[h] += 1
    n = len(feats)
    first_lens = [f["first_len"] for f in feats if f.get("first_len")]
    line_counts = [f["line_count"] for f in feats if f.get("line_count")]
    cps = [f["chars_per_sec"] for f in feats if f.get("chars_per_sec")]

    # 배수 상위 대본의 첫 문장 샘플 (레퍼런스)
    top = sorted(items, key=lambda i: -(i.get("multiplier") or 0))[:10]
    samples = [{"first_line": (i["features"] or {}).get("first_line", ""),
                "multiplier": i.get("multiplier"), "title": i.get("title", "")}
               for i in top if i.get("features")]

    # 훅 유형별 구조 통계 — 훅이 다르면 본문 구조도 다르다(사용자 토의 2026-07-06)
    by_hook = {}
    for t in hook_counter:
        sub = [f for f in feats if t in f.get("hook_types", [])]
        if sub:
            by_hook[t] = {
                "count": len(sub),
                "line_count_median": int(statistics.median([f["line_count"] for f in sub])),
                "first_len_median": int(statistics.median([f["first_len"] for f in sub])),
            }

    rules = {
        "genre": genre or "all", "corpus_count": n,
        "hook_distribution": [
            {"type": t, "name": HOOK_TYPES[t][0], "desc": HOOK_TYPES[t][1],
             "pct": round(100 * c / n)}
            for t, c in hook_counter.most_common()],
        "first_line_len_median": int(statistics.median(first_lens)) if first_lens else 0,
        "line_count_median": int(statistics.median(line_counts)) if line_counts else 0,
        "chars_per_sec_median": round(statistics.median(cps), 1) if cps else 0,
        "cta_pct": round(100 * sum(1 for f in feats if f.get("has_cta")) / n),
        "by_hook": by_hook,
        "top_samples": samples,
    }
    os.makedirs(RULES_DIR, exist_ok=True)
    with open(_rules_path(genre), "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    return rules


def load_rules(genre: str = "") -> dict | None:
    """카테고리 규칙 로드. 그 카테고리 파일이 없으면 전체(all)로 폴백."""
    for path in (_rules_path(genre), _rules_path("")):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return None


def list_genres() -> list[dict]:
    """카테고리 현황 — 코퍼스 수 + 규칙 학습 여부 (섞임 없이 각자)."""
    genres = set(GENRE_QUERIES)
    for i in store.corpus_list(limit=5000):
        if i.get("genre"):
            genres.add(i["genre"])
    out = []
    for g in sorted(genres):
        r = None
        if os.path.isfile(_rules_path(g)):
            with open(_rules_path(g), encoding="utf-8") as f:
                r = json.load(f)
        out.append({"genre": g, "corpus_count": store.corpus_count(g),
                    "rules_learned": bool(r),
                    "rules_corpus_count": (r or {}).get("corpus_count", 0),
                    "queries": GENRE_QUERIES.get(g, [g])})
    return out


def rules_prompt_block(rules: dict | None = None, genre: str = "") -> str:
    """규칙 → 대본 생성 프롬프트 주입 블록 (카테고리별)."""
    r = rules or load_rules(genre)
    if not r or r.get("error"):
        return ""
    hooks = ", ".join(f"{h['name']}({h['pct']}%)" for h in r.get("hook_distribution", [])[:4])
    samples = "\n".join(f"  - \"{s['first_line']}\" (×{s['multiplier']})"
                        for s in r.get("top_samples", [])[:5] if s.get("first_line"))
    return (
        f"[터지는 대본 규칙 — 실제 급등 쇼츠 {r['corpus_count']}개 분석]\n"
        f"- 훅 유형 분포: {hooks}\n"
        f"- 첫 문장 길이 중앙값: {r['first_line_len_median']}자 (이 안에서 훅 완결)\n"
        f"- 대본 문장 수 중앙값: {r['line_count_median']}줄\n"
        f"- 말 속도 중앙값: 초당 {r['chars_per_sec_median']}자\n"
        f"- 배수 상위 첫 문장 예시:\n{samples}\n"
        "첫 문장(3초)은 위 분포에서 가장 효과적인 훅 유형을 골라 반드시 스크롤을 멈추게 하라."
    )


# ── 데모 코퍼스 시드 (키 없을 때 파이프라인 검증용) ─────

_DEMO_SCRIPTS = [
    ("Why did everyone cry in 10 seconds?", 38.1, ["question"]),
    ("절대 이 영상을 끝까지 보지 마세요", 27.5, ["negation", "address"]),
    ("40 years. That's how long he waited.", 22.0, ["number"]),
    ("この瞬間、審査員全員が泣きました", 18.7, ["shock"]),
    ("She had $3 left when the miracle happened", 15.3, ["number"]),
    ("The ending will change how you see your mother", 12.4, ["cliffhang", "address"]),
    ("당신의 부모님도 이런 적 있으신가요?", 11.2, ["question", "address"]),
    ("He walked on stage. Nobody expected this.", 9.2, ["scene"]),
    ("87세 할머니가 무대에서 한 말", 8.9, ["number"]),
    ("Don't judge anyone until you watch this", 7.8, ["negation", "address"]),
    ("涙なしでは見られない再会", 6.1, ["shock"]),
    ("3 sentences from a janitor that silenced a CEO", 5.4, ["number"]),
]


def _seed_demo_corpus(genre: str) -> int:
    import hashlib
    added = 0
    for i, (first, mult, _types) in enumerate(_DEMO_SCRIPTS):
        vid = "demo_cs_" + hashlib.md5(f"{genre}{i}".encode()).hexdigest()[:8]
        # 첫 줄 + 본문 6~9줄의 데모 자막(시간정보 포함)
        lines = [first] + [f"본문 문장 {j} — 사연 전개." for j in range(1, 7)] + ["오늘도 수고하셨습니다."]
        t, tr = 0.0, []
        for ln in lines:
            dur = round(1.5 + len(ln) * 0.05, 2)
            tr.append({"t": round(t, 2), "dur": dur, "text": ln})
            t += dur
        f = extract_features(tr, int(t))
        f["tags"] = ["heartwarming", "reunion", "family", "life lesson",
                     "감동", "shark tank"][: 3 + i % 3]
        store.corpus_add({
            "video_id": vid, "genre": genre, "title": first[:40],
            "channel_title": "Demo Channel", "views": int(mult * 1_000_000),
            "multiplier": mult, "duration_sec": int(t), "lang": "",
            "transcript": tr, "comments": ["got chills at 0:03", "3초에 소름", "泣いた"],
            "features": f,
        })
        added += 1
    return added
