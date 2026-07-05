"""🏷️ 제목·키워드 엔진 — 알고리즘 '분류 신호' + 시선 훅 제목 생성.

사용자 토의 확정(2026-07-05):
  알고리즘 선택의 출발 = 키워드(어느 시청자 군집에 테스트될지 정하는 분류 신호).
  당김 자체 = 첫 테스트의 성과(완주율·재시청·스와이프 이탈) → 키워드가 틀리면
  엉뚱한 군집에서 테스트받아 죽는다. 그래서 키워드는 '추측'이 아니라
  급등 데이터(script_corpus 태그 + 제목 토큰)에서 뽑는다.

3층 키워드:
  L1 카테고리(대형) — 분류 신호. 급등 코퍼스 태그 빈도 상위.
  L2 수요(중형)    — 검색·연관 노출. 급등 제목 토큰 빈도 상위.
  L3 차별화(훅)    — 우리 대본의 비틀린 시선(궁금증 생성).
제목 = L1+L2+L3 조합 + 학습 규칙(숫자·길이) 준수 → 후보 N개 + 채점.
성과 보장은 없다 — 대신 후보 다발 생성 + 성과 기록(title_log)으로 조준을 수정한다.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter

import script_corpus
import store
import translator

_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
         "was", "this", "that", "with", "his", "her", "you", "your", "it",
         "shorts", "short", "video", "official"}


# ── L1/L2 키워드 추출 (코퍼스 실데이터) ─────────────────

def gather_keywords(genre: str = "") -> dict:
    items = store.corpus_list(genre)
    tag_counter: Counter = Counter()
    token_counter: Counter = Counter()
    for i in items:
        # L1: 태그(업로더가 넣은 실제 분류 신호)
        feats = i.get("features") or {}
        for c in i.get("comments", []):
            pass  # 댓글은 훅 참고용 — 키워드 집계엔 미사용
        # 코퍼스엔 태그 컬럼이 없어 제목·첫문장 토큰으로 근사 + 카드 keywords 는 수집기에서 features 로
        for tag in feats.get("tags", []):
            tag_counter[tag.lower()] += 1
        # L2: 제목 토큰
        for w in re.findall(r"[\w']+", i.get("title", ""), re.UNICODE):
            w = w.lower()
            if len(w) >= 2 and w not in _STOP and not w.isdigit():
                token_counter[w] += 1
    return {
        "l1_category": [k for k, _ in tag_counter.most_common(12)],
        "l2_demand": [k for k, _ in token_counter.most_common(20)],
        "corpus_count": len(items),
    }


# ── 제목 채점 (학습 규칙 기반 — 결정론적) ───────────────

def score_title(title: str, rules: dict | None = None) -> dict:
    r = rules or script_corpus.load_rules() or {}
    med = r.get("first_line_len_median", 35) or 35
    hooks = script_corpus.classify_hook(title)
    pts = 0
    detail = {}
    # 길이 적합(중앙값 ±40%)
    ok_len = 0.6 * med <= len(title) <= 1.6 * med
    detail["len_fit"] = ok_len
    pts += 30 if ok_len else 10
    # 숫자(급등 제목의 주력 패턴)
    detail["has_number"] = bool(re.search(r"\d", title))
    pts += 25 if detail["has_number"] else 0
    # 훅 유형 매칭(장면돌입 단독보다 명시적 훅 가점)
    detail["hook_types"] = hooks
    pts += 25 if [h for h in hooks if h != "scene"] else 10
    # 궁금증 갭(결말을 말하지 않음 — '전부/결국/결과' 등 스포 단어 감점)
    detail["no_spoiler"] = not re.search(r"(결국|전부 공개|full story|the whole)", title, re.I)
    pts += 20 if detail["no_spoiler"] else 5
    return {"score": min(pts, 100), "detail": detail}


# ── 제목 생성 ───────────────────────────────────────────

def generate_titles(topic: str, script_first_line: str = "", genre: str = "",
                    language: str = "ko", n: int = 5) -> dict:
    kw = gather_keywords(genre)
    rules = script_corpus.load_rules() or {}
    rules_block = script_corpus.rules_prompt_block(rules)
    lang_name = {"ko": "한국어", "ja": "일본어", "en": "영어"}.get(language, "한국어")

    prompt = (
        f"유튜브 쇼츠 제목 {n}개를 {lang_name}로 지어라. 한 줄에 하나, 번호 없이.\n\n"
        f"[주제] {topic}\n"
        + (f"[대본 첫 문장(3초 훅)] {script_first_line}\n" if script_first_line else "")
        + f"[L1 카테고리 키워드 — 1개 이상 반드시 포함(알고리즘 분류 신호)] "
          f"{', '.join(kw['l1_category'][:8]) or '(코퍼스 수집 후 채워짐)'}\n"
        f"[L2 수요 키워드 — 가능하면 포함] {', '.join(kw['l2_demand'][:10])}\n"
        + (rules_block + "\n" if rules_block else "")
        + "[원칙] 제목·첫3초·내용 삼위일치(낚시 금지). 결말은 절대 말하지 않기(궁금증 갭). "
          "숫자가 자연스러우면 포함.\n"
    )
    out = translator._gemini(prompt, temperature=0.9)
    titles = [t.strip().lstrip("0123456789.-) ") for t in (out or "").splitlines() if t.strip()]
    if not titles:
        titles = _demo_titles(topic, language)[:n]
    titles = titles[:n]

    candidates = []
    for t in titles:
        s = score_title(t, rules)
        candidates.append({"title": t, **s})
    candidates.sort(key=lambda c: -c["score"])

    # 해시태그: L1 상위 + #shorts (3~5개)
    tags = ["#shorts"] + [f"#{k.replace(' ', '')}" for k in kw["l1_category"][:4]]
    return {
        "candidates": candidates,
        "hashtags": tags[:5],
        "keywords": kw,
        "gemini": translator.has_gemini(),
        "note": "키워드=분류 신호(출발선). 당김은 첫3초·완주율·루프가 만든다 — "
                "후보를 올리고 성과를 기록해 다음 선택을 조준하라.",
    }


def _demo_titles(topic: str, language: str) -> list[str]:
    t = topic[:14]
    if language == "ja":
        return [f"40年ぶりの再会、審査員が泣いた理由", f"{t}——3秒後、誰もが涙",
                f"87歳が舞台で言った一言", f"この{t}、最後まで見ないで",
                f"誰も気づかなかった{t}の真実"]
    return [f"40년 만의 재회, 심사위원이 운 이유", f"{t} — 3초 뒤 모두가 울었다",
            f"87세가 무대에서 한 한마디", f"이 {t}, 끝까지 보지 마세요",
            f"아무도 눈치채지 못한 {t}의 진실"]


# ── 성과 기록 (피드백 루프 — 진짜 '대안') ───────────────

def log_title(video_id: str, title: str, keywords: list[str],
              views: int = 0, note: str = "") -> None:
    """올린 제목·키워드·성과 기록 → 다음 키워드 선택의 근거."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "title_log.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "video_id": video_id, "title": title,
                            "keywords": keywords, "views": views, "note": note},
                           ensure_ascii=False) + "\n")
