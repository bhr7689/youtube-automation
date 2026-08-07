"""🔎 SerpAPI 구글 렌즈 어댑터 — 이미지(썸네일)로 '같은 장면' 후보 발굴.

'누가 먼저 숏폼화'의 후보 발굴 단계. 발견한 쇼츠의 **썸네일 공개 URL**(i.ytimg.com/...)을
구글 렌즈(SerpAPI)에 넣어 시각적으로 유사한 웹/영상 후보를 모은다. (로컬 프레임을 업로드할
필요 없이, 공개 썸네일 URL 만으로 역이미지 검색이 되는 게 핵심.)

우리 지문 엔진(frame_fingerprint)이 뒤에서 후보를 다운받아 대조해 진짜만 남기므로,
여기선 '넓게 후보를 긁는' 역할.

키: SERPAPI_API_KEY. 없거나 실패하면 None(폴백). stdlib(urllib)만 — requests 불필요.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

SERP_ENDPOINT = "https://serpapi.com/search.json"
_YT_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")


def has_key() -> bool:
    return bool(os.environ.get("SERPAPI_API_KEY", "").strip())


def thumbnail_url(video_id: str, quality: str = "hqdefault") -> str:
    """YouTube 공개 썸네일 URL(렌즈 질의용). maxresdefault/hqdefault 등."""
    return f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"


def google_lens(image_url: str, api_key: str | None = None,
                timeout: float = 30.0) -> dict | None:
    """구글 렌즈(SerpAPI) 호출 → 원시 JSON. 키 없음/실패 → None."""
    key = (api_key or os.environ.get("SERPAPI_API_KEY", "")).strip()
    if not key or not image_url:
        return None
    params = {"engine": "google_lens", "url": image_url, "api_key": key}
    url = SERP_ENDPOINT + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def extract_candidates(serp_json: dict | None) -> list[dict]:
    """렌즈 JSON → 후보 목록 [{title, link, source, video_id}]. 유튜브면 video_id 채움.

    SerpAPI google_lens 응답의 visual_matches(및 유사 필드)에서 링크를 뽑는다.
    """
    if not isinstance(serp_json, dict):
        return []
    out, seen = [], set()
    buckets = []
    for key in ("visual_matches", "image_results", "inline_images",
                "related_content", "matches"):
        v = serp_json.get(key)
        if isinstance(v, list):
            buckets += v
    for it in buckets:
        if not isinstance(it, dict):
            continue
        link = it.get("link") or it.get("source_link") or it.get("redirect_link") or ""
        if not link or link in seen:
            continue
        seen.add(link)
        m = _YT_ID.search(link)
        out.append({
            "title": it.get("title", "") or it.get("source", ""),
            "link": link,
            "source": it.get("source", ""),
            "video_id": m.group(1) if m else "",
        })
    return out


def find_candidate_videos(video_id: str, api_key: str | None = None,
                          qualities=("maxresdefault", "hqdefault")) -> dict:
    """쇼츠 video_id → 썸네일 렌즈 → 유튜브 영상 후보(video_id 목록) + 전체 후보.

    여러 화질 썸네일로 시도해 후보를 넓게 확보. 반환:
    {ok, tried, youtube: [video_id...], candidates: [{...}], note}
    """
    key = (api_key or os.environ.get("SERPAPI_API_KEY", "")).strip()
    if not key:
        return {"ok": False, "youtube": [], "candidates": [],
                "note": "SERPAPI_API_KEY 없음 — 설정에서 SerpAPI 키를 넣어주세요(구글 렌즈 후보 발굴)."}
    all_cands, yt = [], []
    tried = []
    seen_links = set()
    for q in qualities:
        j = google_lens(thumbnail_url(video_id, q), api_key=key)
        tried.append(q)
        for c in extract_candidates(j):
            if c["link"] in seen_links:
                continue
            seen_links.add(c["link"])
            all_cands.append(c)
            if c["video_id"] and c["video_id"] != video_id and c["video_id"] not in yt:
                yt.append(c["video_id"])
    return {"ok": True, "tried": tried, "youtube": yt,
            "candidates": all_cands,
            "note": "" if all_cands else "렌즈 결과 없음 — 썸네일 접근 실패나 매칭 없음일 수 있어요."}


# ── 자기검증(네트워크 없이 파서 검증) ──────────────────────────
if __name__ == "__main__":
    assert thumbnail_url("abc12345678").endswith("/abc12345678/hqdefault.jpg")

    # mock SerpAPI 응답 파싱
    mock = {
        "visual_matches": [
            {"title": "원본 롱폼", "link": "https://www.youtube.com/watch?v=ORIGvidABCD", "source": "YouTube"},
            {"title": "다른 쇼츠", "link": "https://www.youtube.com/shorts/SHORTvid123", "source": "YouTube"},
            {"title": "블로그 글", "link": "https://blog.example.com/post", "source": "blog"},
            {"title": "중복", "link": "https://www.youtube.com/watch?v=ORIGvidABCD"},  # 중복 제거
        ]
    }
    cands = extract_candidates(mock)
    assert len(cands) == 3, [c["link"] for c in cands]          # 중복 1건 제거
    yt = [c["video_id"] for c in cands if c["video_id"]]
    assert "ORIGvidABCD" in yt and "SHORTvid123" in yt
    assert any(c["video_id"] == "" for c in cands)               # 블로그는 video_id 없음
    print("렌즈 후보 파싱:", [(c['title'], c['video_id'] or '(non-yt)') for c in cands])

    assert extract_candidates(None) == []
    assert not has_key() or True   # 환경 무관

    # 키 없을 때 graceful
    old = os.environ.pop("SERPAPI_API_KEY", None)
    r = find_candidate_videos("someShort11")
    assert not r["ok"] and "SERPAPI" in r["note"]
    if old:
        os.environ["SERPAPI_API_KEY"] = old
    print("무키 graceful:", r["note"][:40])

    print("\n✅ serp_lens self-test 통과 — 썸네일URL·렌즈파싱·유튜브추출·중복제거·무키폴백")
