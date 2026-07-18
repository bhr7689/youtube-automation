"""link_classifier.py — 미분류 대량 링크를 장르통으로 자동 분류.

링크 → YouTube 메타(제목·채널) 수집 → 장르 프로젝트로 분류.
분류: (1) GPT 배치(키 있으면, 정확) → (2) 키워드 휴리스틱(항상 동작) 폴백.
Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import re
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

UNSORTED = "미분류"

# 장르별 기본 어휘(프로젝트 이름/메모 토큰에 더해 매칭 강화)
BASE_LEXICON = {
    "파리": ["파리", "paris", "샹송", "chanson", "프렌치", "french", "에펠", "stella", "스텔라",
             "라따뚜이", "ratatouille", "pink martini", "sarah kang"],
    "재즈": ["재즈", "jazz", "카페", "cafe", "café", "bgm", "cozy", "lounge", "라운지", "coffee", "커피"],
    "보사": ["보사", "bossa", "여름", "summer", "夏", "도쿄", "tokyo", "tropical", "beach"],
    "시티": ["시티팝", "citypop", "city pop", "네온", "레트로", "drive", "드라이브"],
    "lofi": ["lofi", "lo-fi", "로파이", "chill", "study", "공부", "sleep", "수면", "감성", "relax"],
    "클래식": ["클래식", "classical", "피아노", "piano", "왈츠", "waltz", "violin", "바이올린", "orchestra"],
    "발라드": ["발라드", "ballad", "슬픈", "이별", "새벽", "밤"],
}


def extract_ref(url: str) -> tuple[str, str]:
    url = (url or "").strip()
    m = re.search(r"/channel/(UC[\w-]+)", url)
    if m:
        return ("channel", m.group(1))
    m = re.search(r"/@([^/?#\s]+)", url)
    if m:
        return ("handle", m.group(1))
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/)([\w-]{11})", url)
    if m:
        return ("video", m.group(1))
    return ("unknown", url)


def split_links(text: str) -> list[str]:
    return [u.strip() for u in re.split(r"[\s]+", text or "") if u.strip().startswith("http")]


def load_inventory_urls(path: str = "ideas/benchmark_links_inventory.md",
                        videos_only: bool = True) -> list[str]:
    """인벤토리 md 에서 유튜브 URL 추출(중복 제거). videos_only=채널 핸들 제외."""
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    out, seen = [], set()
    for u in re.findall(r"https?://[^\s)\]]+", text):
        u = u.rstrip(".,)]")
        if "youtu" not in u:
            continue
        if videos_only and ("/@" in u or "/channel/" in u):
            continue
        kind, key = extract_ref(u)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def fetch_meta(urls: list[str]) -> list[dict]:
    """URL 리스트 → [{url, title, channel, thumb, kind}]. 키 없으면 title 빈칸."""
    import youtube_client as yc
    metas = [{"url": u, "title": "", "channel": "", "thumb": "", "kind": extract_ref(u)[0]} for u in urls]
    if not yc.has_key():
        return metas
    yt = yc._yt()
    by_ref = {i: extract_ref(m["url"]) for i, m in enumerate(metas)}

    # 영상: 50개씩 배치
    vids = [(i, r[1]) for i, r in by_ref.items() if r[0] == "video"]
    for k in range(0, len(vids), 50):
        chunk = vids[k:k + 50]
        try:
            resp = yt.videos().list(part="snippet", id=",".join(v for _, v in chunk)).execute()
            byid = {it["id"]: it["snippet"] for it in resp.get("items", [])}
            for i, vid in chunk:
                sn = byid.get(vid)
                if sn:
                    metas[i]["title"] = sn.get("title", "")
                    metas[i]["channel"] = sn.get("channelTitle", "")
                    th = sn.get("thumbnails", {})
                    for q in ("high", "medium", "default"):
                        if th.get(q, {}).get("url"):
                            metas[i]["thumb"] = th[q]["url"]; break
        except Exception:               # noqa: BLE001
            pass

    # 핸들/채널: 채널명·설명으로
    for i, r in by_ref.items():
        if r[0] in ("handle", "channel") and not metas[i]["title"]:
            try:
                params = {"part": "snippet"}
                if r[0] == "handle":
                    params["forHandle"] = r[1]
                else:
                    params["id"] = r[1]
                resp = yt.channels().list(**params).execute()
                items = resp.get("items", [])
                if items:
                    sn = items[0]["snippet"]
                    metas[i]["channel"] = sn.get("title", "")
                    metas[i]["title"] = sn.get("title", "") + " | " + sn.get("description", "")[:120]
                    th = sn.get("thumbnails", {})
                    for q in ("high", "medium", "default"):
                        if th.get(q, {}).get("url"):
                            metas[i]["thumb"] = th[q]["url"]; break
            except Exception:           # noqa: BLE001
                pass
    return metas


# 장르 신호가 아닌 일반 단어(메모에서 뽑히면 오분류 유발) — 제외
STOPWORDS = {
    "제목", "썸네일", "채널", "우리", "레퍼런스", "후보", "주력", "키워드", "장악",
    "색보정", "정통", "스타일", "무드", "느린", "경쾌", "여자", "남자", "보컬", "비비드",
    "음악", "영상", "이미지", "분위기", "느낌", "감각", "playlist", "플레이리스트",
}


def _project_keywords(projects: dict) -> dict[str, list[str]]:
    """프로젝트 이름/메모 + BASE_LEXICON 으로 장르별 키워드 세트(불용어 제외)."""
    out = {}
    for name, p in projects.items():
        kws = set()
        blob = (name + " " + (p.get("note") or "")).lower()
        for tok in re.findall(r"[^\W\d_]{2,}", blob, re.UNICODE):
            if tok not in STOPWORDS and len(tok) >= 2:
                kws.add(tok)
        for key, words in BASE_LEXICON.items():
            if key in blob or any(w in blob for w in words[:3]):
                kws.update(words)
        out[name] = [w for w in kws if w not in STOPWORDS]
    return out


def classify_heuristic(metas: list[dict], projects: dict) -> list[dict]:
    kwmap = _project_keywords(projects)
    for m in metas:
        text = (m.get("title", "") + " " + m.get("channel", "")).lower()
        best, score = UNSORTED, 0
        for name, kws in kwmap.items():
            s = sum(1 for w in kws if w and w in text)
            if s > score:
                best, score = name, s
        m["genre"] = best if score > 0 else UNSORTED
        m["score"] = score
        m["by"] = "keyword"
    return metas


def classify_llm(metas: list[dict], projects: dict) -> list[dict] | None:
    """GPT 배치 분류. 키 없거나 실패 시 None."""
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        return None
    if not CM.llm_status().get("openai") and not CM.llm_status().get("gemini"):
        return None
    labeled = [m for m in metas if m.get("title")]
    if not labeled:
        return None
    names = list(projects.keys())
    desc = "\n".join(f"- {n}: {projects[n].get('note','')[:60]}" for n in names)
    for k in range(0, len(labeled), 40):
        chunk = labeled[k:k + 40]
        items = "\n".join(f"{j}. {m['title'][:80]} (채널:{m['channel'][:30]})"
                          for j, m in enumerate(chunk))
        prompt = f"""다음 유튜브 영상들을 아래 장르 중 하나로 분류해줘. 애매하면 "{UNSORTED}".
장르:
{desc}
- {UNSORTED}: 위 어디에도 안 맞음

영상:
{items}

JSON만: {{"result":[{{"i":0,"genre":"장르명"}}]}}"""
        raw = CM._llm(prompt, json_mode=True)
        if not raw:
            return None
        try:
            data = json.loads(raw) if raw.strip().startswith("{") else (CM._parse_json(raw) or {})
            for r in data.get("result", []):
                idx = r.get("i")
                if isinstance(idx, int) and 0 <= idx < len(chunk):
                    g = r.get("genre", UNSORTED)
                    chunk[idx]["genre"] = g if g in names else UNSORTED
                    chunk[idx]["by"] = "gpt"
        except Exception:               # noqa: BLE001
            return None
    for m in metas:
        m.setdefault("genre", UNSORTED)
        m.setdefault("by", "gpt")
        m.setdefault("score", 1 if m["genre"] != UNSORTED else 0)
    return metas


def classify(urls: list[str], projects: dict, use_llm: bool = True) -> list[dict]:
    metas = fetch_meta(urls)
    if use_llm:
        res = classify_llm(metas, projects)
        if res is not None:
            return res
    return classify_heuristic(metas, projects)
