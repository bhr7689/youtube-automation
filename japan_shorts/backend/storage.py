"""SQLite 저장소 — 등록 레퍼런스 채널 / 북마크 / 최근 검색.

stdlib sqlite3 만 사용. 멱등적 upsert. 데이터는 japan_shorts/data/app.db.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db")


def _ensure_dir():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)


@contextmanager
def _conn():
    _ensure_dir()
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS ref_channels (
                channel_id   TEXT PRIMARY KEY,
                title        TEXT,
                subscribers  INTEGER,
                avg_views    REAL,
                added_at     REAL
            );
            CREATE TABLE IF NOT EXISTS bookmarks (
                video_id     TEXT PRIMARY KEY,
                title        TEXT,
                channel_title TEXT,
                thumbnail    TEXT,
                views        INTEGER,
                multiplier   REAL,
                url          TEXT,
                added_at     REAL
            );
            CREATE TABLE IF NOT EXISTS recent_searches (
                query        TEXT PRIMARY KEY,
                video_format TEXT,
                period       TEXT,
                searched_at  REAL
            );
            """
        )


# ---- 등록 채널 -----------------------------------------------------------
def list_channels() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM ref_channels ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]


def add_channel(channel_id: str, title: str = "", subscribers: int = 0,
                avg_views: float = 0.0) -> dict:
    with _conn() as con:
        con.execute(
            """INSERT INTO ref_channels(channel_id,title,subscribers,avg_views,added_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(channel_id) DO UPDATE SET
                 title=excluded.title, subscribers=excluded.subscribers,
                 avg_views=excluded.avg_views""",
            (channel_id, title, subscribers, avg_views, time.time()),
        )
    return {"channel_id": channel_id, "title": title, "registered": True}


def remove_channel(channel_id: str):
    with _conn() as con:
        con.execute("DELETE FROM ref_channels WHERE channel_id=?", (channel_id,))


def registered_channel_ids() -> set[str]:
    with _conn() as con:
        rows = con.execute("SELECT channel_id FROM ref_channels").fetchall()
        return {r["channel_id"] for r in rows}


# ---- 북마크 --------------------------------------------------------------
def list_bookmarks() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM bookmarks ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]


def add_bookmark(card: dict) -> dict:
    with _conn() as con:
        con.execute(
            """INSERT INTO bookmarks(video_id,title,channel_title,thumbnail,
                                     views,multiplier,url,added_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id) DO NOTHING""",
            (card.get("video_id"), card.get("title"), card.get("channel_title"),
             card.get("thumbnail"), card.get("views"), card.get("multiplier"),
             card.get("url"), time.time()),
        )
    return {"video_id": card.get("video_id"), "bookmarked": True}


def remove_bookmark(video_id: str):
    with _conn() as con:
        con.execute("DELETE FROM bookmarks WHERE video_id=?", (video_id,))


def bookmarked_ids() -> set[str]:
    with _conn() as con:
        rows = con.execute("SELECT video_id FROM bookmarks").fetchall()
        return {r["video_id"] for r in rows}


# ---- 최근 검색 -----------------------------------------------------------
def list_recent_searches(limit: int = 15) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM recent_searches ORDER BY searched_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]


def add_recent_search(query: str, video_format: str = "any", period: str = "all"):
    if not query.strip():
        return
    with _conn() as con:
        con.execute(
            """INSERT INTO recent_searches(query,video_format,period,searched_at)
               VALUES(?,?,?,?)
               ON CONFLICT(query) DO UPDATE SET
                 video_format=excluded.video_format,
                 period=excluded.period, searched_at=excluded.searched_at""",
            (query.strip(), video_format, period, time.time()),
        )


def remove_recent_search(query: str):
    with _conn() as con:
        con.execute("DELETE FROM recent_searches WHERE query=?", (query,))


def clear_recent_searches():
    with _conn() as con:
        con.execute("DELETE FROM recent_searches")
