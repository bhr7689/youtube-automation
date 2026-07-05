"""일본쇼츠 자동 프로그램 — FastAPI 백엔드 + 정적 프론트 서빙.

실행:
  cd japan_shorts
  uvicorn backend.main:app --port 8600 --reload
  또는 python -m backend.main

키(YOUTUBE_API_KEY)가 있으면 실데이터, 없으면 mock 으로 자동 폴백(시현 가능).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 프로젝트 루트(.env)와 백엔드 모듈 경로 세팅
_ROOT = Path(__file__).resolve().parent.parent          # japan_shorts/
_FRONTEND = _ROOT / "frontend"
sys.path.insert(0, str(_ROOT / "backend"))

# .env 로드 (있으면). 상위 저장소 .env 도 시도.
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    load_dotenv(_ROOT.parent / ".env")
except Exception:
    pass

import mock_data           # noqa: E402
import storage             # noqa: E402

API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

app = FastAPI(title="일본쇼츠 자동 프로그램", version="0.3.0")
storage.init_db()

# 실 클라이언트는 지연 생성(키 있을 때만)
_yt_client = None


def get_client():
    global _yt_client
    if not API_KEY:
        return None
    if _yt_client is None:
        try:
            from youtube_api import YouTubeClient
            _yt_client = YouTubeClient(API_KEY)
        except Exception as e:
            print("[warn] YouTube 클라이언트 생성 실패:", e)
            return None
    return _yt_client


# ---- API ----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "has_api_key": bool(API_KEY),
        "mode": "live" if API_KEY else "demo",
        "version": app.version,
    }


@app.get("/api/search")
def search(
    q: str = Query("", description="검색 키워드"),
    period: str = Query("all"),
    order: str = Query("viewCount"),   # viewCount | date
    format: str = Query("any"),        # shorts | long | any
    count: int = Query(100, ge=10, le=500),
    scope: str = Query("all"),         # all | registered
    region: str = Query(""),
    language: str = Query(""),
):
    client = get_client()
    if client is None:
        cards = mock_data.mock_search(q, format, count)
        mode = "demo"
    else:
        try:
            cards = client.search(
                q, period=period, order=order, video_format=format,
                max_results=count, region=region or None,
                language=language or None)
            mode = "live"
        except Exception as e:
            return JSONResponse(
                {"error": str(e), "hint": "API 키/쿼터를 확인하세요.",
                 "results": [], "mode": "error"}, status_code=200)

    # 등록/북마크 상태 주입
    reg = storage.registered_channel_ids()
    bm = storage.bookmarked_ids()
    for c in cards:
        c.setdefault("registered", c.get("channel_id") in reg)
        c["bookmarked"] = c.get("video_id") in bm
    if scope == "registered":
        cards = [c for c in cards if c.get("registered")]

    if q.strip():
        storage.add_recent_search(q, format, period)
    return {"results": cards, "mode": mode, "count": len(cards)}


@app.get("/api/keyword-estimate")
def keyword_estimate(q: str):
    client = get_client()
    if client is None:
        return mock_data.mock_keyword_estimate(q)
    return client.keyword_estimate(q)


# ---- 등록 채널 -----------------------------------------------------------
@app.get("/api/channels")
def get_channels():
    return {"channels": storage.list_channels()}


@app.post("/api/channels")
def post_channel(payload: dict):
    return storage.add_channel(
        payload.get("channel_id", ""), payload.get("title", ""),
        int(payload.get("subscribers", 0) or 0),
        float(payload.get("avg_views", 0) or 0))


@app.delete("/api/channels/{channel_id}")
def del_channel(channel_id: str):
    storage.remove_channel(channel_id)
    return {"removed": channel_id}


# ---- 북마크 --------------------------------------------------------------
@app.get("/api/bookmarks")
def get_bookmarks():
    return {"bookmarks": storage.list_bookmarks()}


@app.post("/api/bookmarks")
def post_bookmark(card: dict):
    return storage.add_bookmark(card)


@app.delete("/api/bookmarks/{video_id}")
def del_bookmark(video_id: str):
    storage.remove_bookmark(video_id)
    return {"removed": video_id}


# ---- 최근 검색 -----------------------------------------------------------
@app.get("/api/recent-searches")
def get_recent():
    return {"recent": storage.list_recent_searches()}


@app.delete("/api/recent-searches")
def clear_recent():
    storage.clear_recent_searches()
    return {"cleared": True}


@app.delete("/api/recent-searches/{query}")
def del_recent(query: str):
    storage.remove_recent_search(query)
    return {"removed": query}


# ---- 정적 프론트 (맨 마지막에 마운트) -----------------------------------
@app.get("/")
def index():
    return FileResponse(str(_FRONTEND / "index.html"))


if _FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")


def main():
    import uvicorn
    port = int(os.getenv("PORT", "8600"))
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
