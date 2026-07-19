"""jpshorts 저장소 — SQLite (stdlib sqlite3만 사용).

테이블
  bookmarks        ⭐ 북마크 (video_id 자연키, payload = 카드 JSON 스냅샷)
  ref_channels     ➕ 레퍼런스 채널 (channel_id 자연키)
  recent_searches  최근 검색어 (중복 시 최신으로 갱신)
  channel_cache    채널 통계 캐시 (평균조회수·개설일 — API 쿼터 절약)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "jpshorts.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
  video_id TEXT PRIMARY KEY,
  payload  TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_channels (
  channel_id TEXT PRIMARY KEY,
  title      TEXT NOT NULL DEFAULT '',
  payload    TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recent_searches (
  query TEXT PRIMARY KEY,
  used_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_cache (
  channel_id TEXT PRIMARY KEY,
  payload    TEXT NOT NULL,
  fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collections (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_members (
  collection_id TEXT NOT NULL,
  channel_id    TEXT NOT NULL,
  title         TEXT NOT NULL DEFAULT '',
  payload       TEXT NOT NULL DEFAULT '{}',
  added_at      REAL NOT NULL,
  PRIMARY KEY (collection_id, channel_id)
);
CREATE TABLE IF NOT EXISTS script_corpus (
  video_id    TEXT PRIMARY KEY,
  genre       TEXT NOT NULL DEFAULT '',
  title       TEXT NOT NULL DEFAULT '',
  channel_title TEXT NOT NULL DEFAULT '',
  views       INTEGER NOT NULL DEFAULT 0,
  multiplier  REAL,
  duration_sec INTEGER NOT NULL DEFAULT 0,
  lang        TEXT NOT NULL DEFAULT '',
  transcript  TEXT NOT NULL DEFAULT '[]',
  comments    TEXT NOT NULL DEFAULT '[]',
  features    TEXT NOT NULL DEFAULT '{}',
  collected_at REAL NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


# ── 북마크 ─────────────────────────────────────────────

def add_bookmark(video_id: str, payload: dict) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO bookmarks(video_id, payload, created_at) VALUES(?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET payload=excluded.payload",
            (video_id, json.dumps(payload, ensure_ascii=False), time.time()),
        )


def remove_bookmark(video_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM bookmarks WHERE video_id=?", (video_id,))


def list_bookmarks() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT payload FROM bookmarks ORDER BY created_at DESC"
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def bookmark_ids() -> set[str]:
    with _conn() as c:
        rows = c.execute("SELECT video_id FROM bookmarks").fetchall()
    return {r["video_id"] for r in rows}


# ── 레퍼런스 채널 ───────────────────────────────────────

def add_channel(channel_id: str, title: str, payload: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO ref_channels(channel_id, title, payload, created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title, payload=excluded.payload",
            (channel_id, title, json.dumps(payload or {}, ensure_ascii=False), time.time()),
        )


def remove_channel(channel_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM ref_channels WHERE channel_id=?", (channel_id,))


def list_channels() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT channel_id, title, payload, created_at FROM ref_channels "
            "ORDER BY created_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        item = json.loads(r["payload"])
        item.update({"channel_id": r["channel_id"], "title": r["title"]})
        out.append(item)
    return out


def channel_ids() -> set[str]:
    with _conn() as c:
        rows = c.execute("SELECT channel_id FROM ref_channels").fetchall()
    return {r["channel_id"] for r in rows}


# ── 최근 검색 ──────────────────────────────────────────

def touch_search(query: str) -> None:
    q = query.strip()
    if not q:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO recent_searches(query, used_at) VALUES(?,?) "
            "ON CONFLICT(query) DO UPDATE SET used_at=excluded.used_at",
            (q, time.time()),
        )


def recent_searches(limit: int = 15) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT query FROM recent_searches ORDER BY used_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["query"] for r in rows]


def clear_searches() -> None:
    with _conn() as c:
        c.execute("DELETE FROM recent_searches")


# ── 📁 컬렉션 (채널 폴더 — 플랫 v1) ────────────────────

def _slug(name: str) -> str:
    import hashlib as _h
    return "col_" + _h.md5(f"{name}{time.time()}".encode()).hexdigest()[:8]


def create_collection(name: str) -> dict:
    cid = _slug(name)
    with _conn() as c:
        c.execute(
            "INSERT INTO collections(id, name, created_at) VALUES(?,?,?)",
            (cid, name.strip() or "새 폴더", time.time()),
        )
    return {"id": cid, "name": name.strip() or "새 폴더"}


def rename_collection(cid: str, name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE collections SET name=? WHERE id=?", (name.strip(), cid))


def delete_collection(cid: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM collection_members WHERE collection_id=?", (cid,))
        c.execute("DELETE FROM collections WHERE id=?", (cid,))


def list_collections() -> list[dict]:
    with _conn() as c:
        cols = c.execute(
            "SELECT id, name, created_at FROM collections ORDER BY created_at DESC"
        ).fetchall()
        out = []
        for col in cols:
            members = c.execute(
                "SELECT channel_id, title, payload FROM collection_members "
                "WHERE collection_id=? ORDER BY added_at DESC",
                (col["id"],),
            ).fetchall()
            chans = []
            for m in members:
                item = json.loads(m["payload"] or "{}")
                item.update({"channel_id": m["channel_id"], "title": m["title"]})
                chans.append(item)
            out.append({
                "id": col["id"], "name": col["name"],
                "channel_count": len(chans), "channels": chans,
            })
    return out


def get_collection(cid: str) -> dict | None:
    for col in list_collections():
        if col["id"] == cid:
            return col
    return None


def add_to_collection(cid: str, channel_id: str, title: str = "",
                      payload: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO collection_members(collection_id, channel_id, title, payload, added_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(collection_id, channel_id) DO UPDATE SET "
            "title=excluded.title, payload=excluded.payload",
            (cid, channel_id, title, json.dumps(payload or {}, ensure_ascii=False), time.time()),
        )


def remove_from_collection(cid: str, channel_id: str) -> None:
    with _conn() as c:
        c.execute(
            "DELETE FROM collection_members WHERE collection_id=? AND channel_id=?",
            (cid, channel_id),
        )


# ── 채널 캐시 (24h TTL) ────────────────────────────────

def cache_get_channels(ids: list[str], ttl: float = 86400.0) -> dict[str, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with _conn() as c:
        rows = c.execute(
            f"SELECT channel_id, payload, fetched_at FROM channel_cache WHERE channel_id IN ({marks})",
            ids,
        ).fetchall()
    now = time.time()
    return {
        r["channel_id"]: json.loads(r["payload"])
        for r in rows
        if now - r["fetched_at"] < ttl
    }


def cache_put_channels(items: dict[str, dict]) -> None:
    now = time.time()
    with _conn() as c:
        for cid, payload in items.items():
            c.execute(
                "INSERT INTO channel_cache(channel_id, payload, fetched_at) VALUES(?,?,?) "
                "ON CONFLICT(channel_id) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at",
                (cid, json.dumps(payload, ensure_ascii=False), now),
            )


# ── 📚 대본 코퍼스 (터진 숏폼 대본 수집 → 훅 규칙 학습) ─

def corpus_add(item: dict) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO script_corpus(video_id, genre, title, channel_title, views, "
            "multiplier, duration_sec, lang, transcript, comments, features, collected_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET views=excluded.views, "
            "multiplier=excluded.multiplier, transcript=excluded.transcript, "
            "comments=excluded.comments, features=excluded.features",
            (item["video_id"], item.get("genre", ""), item.get("title", ""),
             item.get("channel_title", ""), item.get("views", 0), item.get("multiplier"),
             item.get("duration_sec", 0), item.get("lang", ""),
             json.dumps(item.get("transcript", []), ensure_ascii=False),
             json.dumps(item.get("comments", []), ensure_ascii=False),
             json.dumps(item.get("features", {}), ensure_ascii=False), time.time()),
        )


def corpus_list(genre: str = "", limit: int = 1000) -> list[dict]:
    with _conn() as c:
        if genre:
            rows = c.execute(
                "SELECT * FROM script_corpus WHERE genre=? ORDER BY multiplier DESC LIMIT ?",
                (genre, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM script_corpus ORDER BY multiplier DESC LIMIT ?",
                (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("transcript", "comments", "features"):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = [] if k != "features" else {}
        out.append(d)
    return out


def corpus_count(genre: str = "") -> int:
    with _conn() as c:
        if genre:
            r = c.execute("SELECT COUNT(*) n FROM script_corpus WHERE genre=?", (genre,)).fetchone()
        else:
            r = c.execute("SELECT COUNT(*) n FROM script_corpus").fetchone()
    return r["n"]
