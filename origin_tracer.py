"""🕵️ 원본·최초 역추적 오케스트레이터 — 발견한 쇼츠 → (지문+렌즈) → 원본·최초 판정.

흐름(사장님 지적 반영: 원본은 안 줘도 됨, 발견한 쇼츠만):
  1. 쇼츠 지문(프레임 dHash)  ← sig_fn (yt-dlp+ffmpeg+frame_fingerprint, 사장님 PC)
  2. 같은 장면 후보 발굴        ← serp_fn (SerpAPI 구글 렌즈, 썸네일 질의)
  3. 후보 다운로드 → 지문 대조 → 진짜 같은 콘텐츠만 남김(우연·무관 배제)
  4. 검증 통과분 날짜순:
       가장 이른 롱폼 = 원본,  가장 이른 쇼츠 = 제일 먼저 숏폼화(답)

모든 무거운 I/O(다운로드·렌즈·메타)는 주입 → 순수 오케스트레이션만 여기서 테스트.
신뢰도 정직: 지문 검증되면 HIGH 가능, 지문 못 뜨면(다운 실패) 렌즈 후보만 → LOW + 경고.
"""
from __future__ import annotations

import re
from datetime import datetime

import frame_fingerprint as fp

_VID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")


def _extract_id(url: str) -> str:
    m = _VID.search(url or "")
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", (url or "").strip()):
        return url.strip()
    return ""


def _parse_dt(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            return None
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def _is_short(meta: dict) -> bool:
    if meta.get("is_short"):
        return True
    d = meta.get("duration_sec")
    return isinstance(d, (int, float)) and 0 < d <= 180


def trace(short_url: str, *, sig_fn, serp_fn, meta_fn,
          extra_ids=None, per_frame_thresh: float = 0.82,
          min_coverage: float = 0.5, max_candidates: int = 15) -> dict:
    """발견한 쇼츠 → 원본·최초 역추적.

    sig_fn(video_id)  -> list[int]      # 다운로드+프레임 지문(사장님 PC). 실패 시 []
    serp_fn(video_id) -> {youtube:[id]} # 구글 렌즈 후보(serp_lens.find_candidate_videos)
    meta_fn(video_id) -> dict           # {title,published_at,duration_sec,is_short,channel,url}
    """
    vid = _extract_id(short_url)
    if not vid:
        return {"ok": False, "error": "쇼츠 URL 에서 video_id 를 못 찾았어요."}

    notes = []
    query_sig = []
    try:
        query_sig = sig_fn(vid) or []
    except Exception:
        query_sig = []
    fingerprinted = len(query_sig) >= 3
    if not fingerprinted:
        notes.append("발견한 쇼츠를 다운로드/지문화하지 못했어요(웹 환경 제한). "
                     "사장님 PC 에서 실행하면 화면 지문 대조가 켜져요 — 지금은 렌즈 후보만 표시.")

    # 후보 수집: 렌즈 + 추가(자막/핸들 등 외부 주입)
    cand_ids = []
    try:
        sr = serp_fn(vid) or {}
        cand_ids += [i for i in sr.get("youtube", []) if i and i != vid]
    except Exception as e:
        notes.append(f"렌즈 후보 발굴 실패: {str(e)[:80]}")
    for i in (extra_ids or []):
        if i and i != vid and i not in cand_ids:
            cand_ids.append(i)
    cand_ids = cand_ids[:max_candidates]
    if not cand_ids:
        notes.append("같은 장면 후보를 못 찾았어요 — SerpAPI 키/썸네일 접근을 확인하세요.")

    verified, unverified = [], []
    for cid in cand_ids:
        meta = {}
        try:
            meta = meta_fn(cid) or {}
        except Exception:
            meta = {}
        item = {
            "video_id": cid,
            "url": meta.get("url") or f"https://www.youtube.com/watch?v={cid}",
            "title": meta.get("title", ""),
            "channel": meta.get("channel", ""),
            "published_at": meta.get("published_at", ""),
            "is_short": _is_short(meta),
            "duration_sec": meta.get("duration_sec"),
            "coverage": None,
        }
        if fingerprinted:
            try:
                csig = sig_fn(cid) or []
            except Exception:
                csig = []
            if csig:
                m = fp.contains(query_sig, csig, per_frame_thresh=per_frame_thresh)
                item["coverage"] = m["coverage"]
                (verified if m["coverage"] >= min_coverage else unverified).append(item)
            else:
                unverified.append(item)      # 다운 실패 → 미검증
        else:
            unverified.append(item)          # 지문 없음 → 렌즈 후보(미검증)

    pool = verified if verified else unverified
    _dt = lambda x: (_parse_dt(x["published_at"]) or datetime.max)
    pool_sorted = sorted(pool, key=lambda x: (_parse_dt(x["published_at"]) is None, _dt(x)))

    longs = [c for c in pool_sorted if not c["is_short"]]
    shorts = [c for c in pool_sorted if c["is_short"]]
    original = longs[0] if longs else None
    first_short = shorts[0] if shorts else (pool_sorted[0] if pool_sorted else None)

    # 신뢰도
    confidence = None
    if first_short:
        if verified and fingerprinted:
            confidence = "HIGH" if (first_short.get("coverage") or 0) >= 0.7 else "MEDIUM"
        else:
            confidence = "LOW"

    notes.append("여기 나온 최초는 '지금 공개적으로 확인되는' 것 — 삭제·비공개된 더 이른 영상은 알 수 없어요.")
    if verified:
        notes.insert(0, f"화면 지문으로 {len(verified)}개가 '같은 콘텐츠'로 검증됨.")

    return {
        "ok": bool(first_short),
        "input": {"video_id": vid, "url": short_url},
        "fingerprinted": fingerprinted,
        "original": original,          # 가장 이른 롱폼(원본 추정)
        "firstShort": first_short,     # 가장 이른 쇼츠(최초 숏폼화)
        "timeline": pool_sorted,
        "verifiedCount": len(verified),
        "candidateCount": len(cand_ids),
        "confidence": confidence,
        "notes": notes,
    }


# ── 자기검증(stub I/O) ────────────────────────────────────────
if __name__ == "__main__":
    # 지문 stub: 같은 '콘텐츠 키'면 동일 프레임 지문 세트 반환
    CONTENT = {
        "SHORT_INPUT": "catreact", "FIRST_SHORT": "catreact",
        "LATER_SHORT": "catreact", "ORIG_LONG": "catreact",
        "UNRELATED0": "dogbath",
    }
    from PIL import Image
    def _frames_for(key):
        # 콘텐츠 키를 시드로 서로 다른(하지만 키 내에선 동일) 프레임 생성
        base = sum(ord(c) for c in key)
        imgs = []
        for k in range(6):
            im = Image.new("L", (64, 64))
            px = im.load()
            for y in range(64):
                for x in range(64):
                    px[x, y] = (base + x * (k + 1)) % 256
            imgs.append(im)
        return fp.frame_hashes(imgs)
    SIGS = {vid: _frames_for(CONTENT[vid]) for vid in CONTENT}

    META = {
        "FIRST_SHORT": {"title": "고양이 리액션 ㅋㅋ", "channel": "채널Y",
                        "published_at": "2023-05-03", "is_short": True, "url": "u/FIRST"},
        "LATER_SHORT": {"title": "고양이 눈 리액션", "channel": "채널Z",
                        "published_at": "2023-05-08", "is_short": True, "url": "u/LATER"},
        "ORIG_LONG": {"title": "고양이 눈 리액션 원본 12분", "channel": "원본채널",
                      "published_at": "2023-05-01", "duration_sec": 720, "url": "u/ORIG"},
        "UNRELATED0": {"title": "강아지 목욕", "channel": "무관",
                       "published_at": "2023-04-01", "is_short": True, "url": "u/UNREL"},
    }

    def sig_fn(vid): return SIGS.get(vid, [])
    def serp_fn(vid): return {"youtube": ["FIRST_SHORT", "LATER_SHORT", "ORIG_LONG", "UNRELATED0"]}
    def meta_fn(vid): return META.get(vid, {})

    r = trace("https://youtube.com/shorts/SHORT_INPUT", sig_fn=sig_fn, serp_fn=serp_fn, meta_fn=meta_fn)
    assert r["ok"] and r["fingerprinted"], r
    # 무관(다른 콘텐츠)은 지문 대조에서 탈락
    assert r["verifiedCount"] == 3, r["verifiedCount"]
    assert all(t["video_id"] != "UNRELATED0" for t in r["timeline"]), "무관 배제"
    # 최초 숏폼화 = 채널Y(05-03), 원본 롱폼 = 05-01
    assert r["firstShort"]["channel"] == "채널Y", r["firstShort"]
    assert r["original"]["channel"] == "원본채널", r["original"]
    assert r["confidence"] == "HIGH", r["confidence"]
    print(f"🎬 원본 롱폼: {r['original']['channel']} ({r['original']['published_at']})")
    print(f"🥇 최초 숏폼화: {r['firstShort']['channel']} ({r['firstShort']['published_at']}) "
          f"신뢰도 {r['confidence']} · 지문 검증 {r['verifiedCount']}개")

    # 지문 못 뜨는 경우(웹) → 렌즈 후보만, LOW + 경고
    r2 = trace("https://youtube.com/shorts/SHORT_INPUT", sig_fn=lambda v: [], serp_fn=serp_fn, meta_fn=meta_fn)
    assert r2["ok"] and not r2["fingerprinted"] and r2["confidence"] == "LOW"
    assert any("지문화하지 못" in n for n in r2["notes"])
    print(f"\n(웹) 지문 없이 렌즈 후보만 — 신뢰도 {r2['confidence']}, 후보 {r2['candidateCount']}개")

    print("\n✅ origin_tracer self-test 통과 — 지문검증·무관배제·원본/최초 판정·신뢰도·웹폴백")
