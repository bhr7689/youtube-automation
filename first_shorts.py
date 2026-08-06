"""🥇 누가 먼저 숏폼화했나 — 원본 롱폼 → 파생 쇼츠들 중 '가장 이른' 것 판정(Phase 1).

사장님 요구: 원본 영상을 주면, 그걸 제일 먼저 숏폼화(쇼츠화)한 채널·링크를 찾는다.

Phase 1 = **메타 기반**(제목 유사도 + 날짜 순). 영상/오디오 지문 검증은 Phase 2.
그래서 신뢰도는 MEDIUM 이하로 정직하게 표기하고, "지문 미검증·삭제본 가능"을 항상 명시한다.

핵심 규칙:
- 파생 쇼츠는 반드시 **원본 이후**에 올라온다 → 원본 날짜보다 이른 건 제외(원본을 못 가리킴).
- 제목/키워드가 원본과 **유사**해야 파생 후보(무관 영상 배제).
- 검증 통과분을 **날짜 오름차순** → 최상단 = '가장 먼저 숏폼화'.
- 100% 최초 단정 금지 — "지금 공개적으로 확인 가능한 가장 이른 파생"만.

순수 로직 + 수집함수 주입(테스트는 stub, 백엔드는 youtube_client). stdlib 만.
"""
from __future__ import annotations

import re
from datetime import datetime

_WORD = re.compile(r"[\w가-힣ぁ-んァ-ヶ一-龠]+", re.UNICODE)
_STOP = {"shorts", "short", "youtube", "official", "the", "a", "of", "and",
         "영상", "쇼츠", "숏츠", "구독", "공식"}


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")
            if len(w) >= 2 and w.lower() not in _STOP}


def _similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return round(inter / len(a | b), 3)


def _parse_dt(s: str):
    """ISO/날짜 문자열 → naive datetime(tz 제거해 비교 통일). 실패 시 None."""
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            return None
    if dt is not None and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)     # naive 로 통일(일 단위 비교라 충분)
    return dt


def _shorts_url(video_id: str) -> str:
    return f"https://www.youtube.com/shorts/{video_id}"


def _is_shortish(c: dict) -> bool:
    """쇼츠(파생) 후보인지 — is_short True 또는 길이 ≤180초, 정보 없으면 통과."""
    if c.get("is_short"):
        return True
    dur = c.get("duration_sec")
    if isinstance(dur, (int, float)) and dur > 0:
        return dur <= 180
    return True   # 정보 없으면 배제하지 않음(관대)


def find_first_shorts(original: dict, candidates: list[dict], *,
                      min_ratio: float = 0.18, max_timeline: int = 40) -> dict:
    """원본 + 파생 후보들 → 최초 숏폼화 판정 + 타임라인.

    original: {title, keywords?(list), published_at?(ISO), video_id?, url?, channel_id?}
    candidates: youtube_client.search_videos 형 [{video_id,title,channel_title,channel_id,
                 published_at,is_short,duration_sec,thumb,views}]
    """
    orig_tokens = _tokens(original.get("title", ""))
    for k in original.get("keywords", []) or []:
        orig_tokens |= _tokens(k)
    orig_dt = _parse_dt(original.get("published_at", ""))
    orig_vid = original.get("video_id", "")

    matched = []
    for c in candidates:
        vid = c.get("video_id", "")
        if vid and vid == orig_vid:
            continue                          # 원본 자신 제외
        if not _is_shortish(c):
            continue                          # 쇼츠 아님(롱폼) 제외
        sim = _similarity(orig_tokens, _tokens(c.get("title", "")))
        if sim < min_ratio:
            continue                          # 주제 무관 배제
        c_dt = _parse_dt(c.get("published_at", ""))
        after_original = True
        gap_days = None
        if orig_dt and c_dt:
            if c_dt < orig_dt:
                continue                      # 원본보다 이른 건 파생 아님
            gap_days = (c_dt.date() - orig_dt.date()).days   # 달력 날짜 차이(직관적)
            after_original = True
        matched.append({
            "video_id": vid,
            "url": c.get("url") or (_shorts_url(vid) if vid else ""),
            "title": c.get("title", ""),
            "channel": c.get("channel_title", ""),
            "channel_id": c.get("channel_id", ""),
            "published_at": c.get("published_at", ""),
            "similarity": sim,
            "gapDays": gap_days,
            "views": c.get("views"),
            "thumb": c.get("thumb", ""),
            "_dt": c_dt,
        })

    # 날짜 오름차순(가장 이른 것 먼저). 날짜 없는 건 뒤로.
    matched.sort(key=lambda m: (m["_dt"] is None, m["_dt"] or datetime.max))
    for m in matched:
        m.pop("_dt", None)

    first = matched[0] if matched else None

    # 신뢰도 — Phase 1(지문 없음)은 최대 MEDIUM. 정직 표기.
    confidence = None
    if first:
        strong = first["similarity"] >= 0.45 and len(matched) >= 3 and bool(orig_dt)
        confidence = "MEDIUM" if strong else "LOW"

    notes = [
        "메타(제목 유사도·업로드 날짜) 기반 판정 — 영상/오디오 지문 미검증(Phase 2 예정).",
        "여기 나온 건 '지금 공개적으로 확인되는 가장 이른 파생 쇼츠'예요. "
        "이미 삭제·비공개된 더 이른 영상이 있을 수 있어요.",
    ]
    if not orig_dt:
        notes.append("원본 업로드 날짜 미확인 — '원본 이후' 필터를 못 걸어 결과에 오차가 있을 수 있어요.")
    if not matched:
        notes.append("유사한 파생 쇼츠를 못 찾음 — 키워드를 바꾸거나 YouTube 키로 실검색하세요(사장님 PC).")

    return {
        "ok": bool(first),
        "original": {
            "title": original.get("title", ""),
            "url": original.get("url", ""),
            "published_at": original.get("published_at", ""),
        },
        "firstShort": first,
        "timeline": matched[:max_timeline],
        "matchedCount": len(matched),
        "confidence": confidence,
        "notes": notes,
    }


# ── 자기검증(stub 후보) ───────────────────────────────────────
if __name__ == "__main__":
    original = {
        "title": "고양이가 처음 눈을 본 순간 리액션",
        "published_at": "2023-05-01T09:00:00Z",
        "video_id": "ORIG0000000",
        "url": "https://youtube.com/watch?v=ORIG0000000",
    }
    cands = [
        # 무관(배제)
        {"video_id": "x1", "title": "강아지 목욕 브이로그", "channel_title": "무관채널",
         "published_at": "2023-05-02T00:00:00Z", "is_short": True},
        # 원본보다 이른 것(배제)
        {"video_id": "x2", "title": "고양이 눈 리액션 순간", "channel_title": "이른채널",
         "published_at": "2023-04-20T00:00:00Z", "is_short": True},
        # 파생 — 가장 이른(최초)
        {"video_id": "FIRST00", "title": "고양이 처음 눈 본 리액션 순간 ㅋㅋ", "channel_title": "채널Y",
         "published_at": "2023-05-03T00:00:00Z", "is_short": True, "views": 120000},
        # 파생 — 그 다음
        {"video_id": "SECOND0", "title": "눈 처음 본 고양이 리액션", "channel_title": "채널Z",
         "published_at": "2023-05-06T00:00:00Z", "is_short": True},
        # 롱폼(쇼츠 아님, 배제)
        {"video_id": "long1", "title": "고양이 눈 리액션 모음 30분", "channel_title": "롱폼채널",
         "published_at": "2023-05-10T00:00:00Z", "is_short": False, "duration_sec": 1800},
    ]
    r = find_first_shorts(original, cands)
    assert r["ok"], r
    assert r["firstShort"]["channel"] == "채널Y", r["firstShort"]
    assert r["firstShort"]["video_id"] == "FIRST00"
    assert r["firstShort"]["gapDays"] == 2, r["firstShort"]["gapDays"]
    ids = [t["video_id"] for t in r["timeline"]]
    assert ids == ["FIRST00", "SECOND0"], ids       # 무관·이른것·롱폼 전부 배제, 날짜순
    assert "shorts/FIRST00" in r["firstShort"]["url"]
    assert r["confidence"] in ("LOW", "MEDIUM")
    print(f"🥇 최초 숏폼화: {r['firstShort']['channel']} "
          f"({r['firstShort']['published_at'][:10]}, 원본 +{r['firstShort']['gapDays']}일) "
          f"신뢰도 {r['confidence']}")
    print(f"🕰️ 타임라인: " + " → ".join(
        f"{t['channel']}({t['published_at'][:10]})" for t in r["timeline"]))

    # 날짜 없는 원본 → 필터 완화 + 경고
    r2 = find_first_shorts({"title": "고양이 눈 리액션"}, cands)
    assert any("날짜 미확인" in n for n in r2["notes"])
    # 매칭 없음
    r3 = find_first_shorts({"title": "완전 다른 주제 우주 로켓"}, cands)
    assert not r3["ok"] and any("못 찾" in n for n in r3["notes"])
    print("\n✅ first_shorts self-test 통과 — 유사도·원본이후·쇼츠필터·날짜순 최초·신뢰도·한계고지")
