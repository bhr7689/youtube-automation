"""jpshorts 백엔드 — FastAPI.

실행:  uvicorn main:app --port 8787 --app-dir jpshorts/backend
키:    YOUTUBE_API_KEY 없으면 데모 데이터 모드로 동작 (UI 개발·시연용).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import store
import taxonomy
import youtube_client as yc

try:  # .env 자동 로드 (저장소 루트)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
    yc.YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
except ImportError:
    pass

app = FastAPI(title="jpshorts API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _annotate(cards: list[dict]) -> list[dict]:
    """카드에 북마크·레퍼런스 등록 상태 플래그를 붙인다."""
    bm = store.bookmark_ids()
    ch = store.channel_ids()
    for c in cards:
        c["bookmarked"] = c["video_id"] in bm
        c["registered"] = c["channel_id"] in ch
    return cards


@app.get("/api/health")
def health():
    return {"ok": True, "demo": not yc.has_key(), "version": app.version}


@app.get("/api/taxonomy")
def get_taxonomy():
    return taxonomy.load()


class QueryReq(BaseModel):
    category: str = "music_playlist"
    genres: list[str] = Field(default_factory=list)
    situations: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    langs: list[str] = Field(default_factory=lambda: ["ko"])
    limit: int = 10


@app.post("/api/discover/queries")
def discover_queries(req: QueryReq):
    qs = taxonomy.generate_queries(
        category=req.category, genres=req.genres, situations=req.situations,
        emotions=req.emotions, langs=req.langs, limit=req.limit,
    )
    return {"queries": qs}


class DiscoverSearchReq(BaseModel):
    queries: list[str]
    video_type: str = "all"
    max_per_query: int = 15


@app.post("/api/discover/search")
def discover_search(req: DiscoverSearchReq):
    merged: dict[str, dict] = {}
    for q in req.queries[:12]:
        for card in yc.search_videos(q, video_type=req.video_type, max_results=req.max_per_query):
            merged.setdefault(card["video_id"], card)
    cards = sorted(merged.values(), key=lambda c: -(c.get("multiplier") or 0))
    return {"cards": _annotate(cards), "demo": not yc.has_key()}


@app.get("/api/search")
def search(
    q: str,
    video_type: str = "all",
    order: str = "viewCount",
    max_results: int = 100,
    period_days: int = 0,
    lang: str = "",
):
    store.touch_search(q)
    cards = yc.search_videos(
        q, video_type=video_type, order=order,
        max_results=max_results, period_days=period_days, lang=lang,
    )
    return {"cards": _annotate(cards), "demo": not yc.has_key()}


# ── 북마크 (크로스 화면 공유 자산) ──────────────────────

class CardReq(BaseModel):
    card: dict


@app.get("/api/bookmarks")
def get_bookmarks():
    return {"cards": _annotate(store.list_bookmarks())}


@app.post("/api/bookmarks")
def post_bookmark(req: CardReq):
    store.add_bookmark(req.card["video_id"], req.card)
    return {"ok": True}


@app.delete("/api/bookmarks/{video_id}")
def delete_bookmark(video_id: str):
    store.remove_bookmark(video_id)
    return {"ok": True}


# ── 레퍼런스 채널 ───────────────────────────────────────

class ChannelReq(BaseModel):
    channel_id: str
    title: str = ""
    payload: dict = Field(default_factory=dict)


@app.get("/api/channels")
def get_channels():
    return {"channels": store.list_channels()}


@app.post("/api/channels")
def post_channel(req: ChannelReq):
    store.add_channel(req.channel_id, req.title, req.payload)
    return {"ok": True}


@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: str):
    store.remove_channel(channel_id)
    return {"ok": True}


# ── 최근 검색 ──────────────────────────────────────────

@app.get("/api/recent")
def get_recent():
    return {"queries": store.recent_searches()}


@app.delete("/api/recent")
def delete_recent():
    store.clear_searches()
    return {"ok": True}
