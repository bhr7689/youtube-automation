"""데이터 토대 — SQLite 기반 '나만의 자산' 조인 체인.

수집 → 분석 → 프롬프트 → 곡 → 게시 → 성과를 video_id/prompt_id/song_id 로 꿰어
하나의 질의 가능한 자산으로 쌓는다. 핫패스를 로컬 SQLite 로 두어 네트워크 홉 없이
빠르게(버퍼링 최소) 읽고 쓴다. Google Sheets 는 사람이 볼 요약만 별도 동기화한다.

설계 원칙:
- append-only 우선: video_stats·performance·comments·review_log 는 이력 누적.
  videos·video_features·prompts 는 최신 스냅샷 upsert(이력은 video_stats 가 보관).
- 멱등성: 자연키(video_id, comment_id)로 중복 차단 → 재수집해도 낭비 없음.
- 개인정보: 댓글 작성자는 해시로만 저장(원문 텍스트는 감성분석 후 폐기 권장).

stdlib sqlite3 만 사용. Streamlit/외부 의존 없음 → n8n/스케줄러/대시보드 공용.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DB_PATH = Path(__file__).parent / "ktrot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id            TEXT PRIMARY KEY,
    channel_id          TEXT,
    channel_title       TEXT,
    title               TEXT,
    description         TEXT,
    published_at        TEXT,
    duration_sec        INTEGER,
    region              TEXT,
    search_keyword      TEXT,
    subscriber_count    INTEGER,
    view_count          INTEGER,
    like_count          INTEGER,
    comment_count       INTEGER,
    quant_score         REAL,
    first_collected_at  TEXT,
    last_collected_at   TEXT
);

CREATE TABLE IF NOT EXISTS video_stats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    collected_at  TEXT NOT NULL,
    view_count    INTEGER,
    like_count    INTEGER,
    comment_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_video_stats_vid ON video_stats(video_id);

CREATE TABLE IF NOT EXISTS comments (
    comment_id   TEXT PRIMARY KEY,
    video_id     TEXT NOT NULL,
    author_hash  TEXT,
    text         TEXT,
    like_count   INTEGER,
    published_at TEXT,
    collected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_comments_vid ON comments(video_id);

CREATE TABLE IF NOT EXISTS video_features (
    video_id        TEXT PRIMARY KEY,
    mood            TEXT,
    energy          TEXT,
    qual_score      REAL,
    emotion_summary TEXT,
    style_tags      TEXT,
    analyzed_at     TEXT
);

CREATE TABLE IF NOT EXISTS prompts (
    prompt_id       TEXT PRIMARY KEY,
    source_video_id TEXT,
    preset          TEXT,
    picks           TEXT,
    bpm             INTEGER,
    hook            TEXT,
    style_prompt    TEXT,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_prompts_src ON prompts(source_video_id);

CREATE TABLE IF NOT EXISTS songs (
    song_id    TEXT PRIMARY KEY,
    prompt_id  TEXT,
    suno_url   TEXT,
    audio_path TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_songs_prompt ON songs(prompt_id);

CREATE TABLE IF NOT EXISTS publications (
    pub_id       TEXT PRIMARY KEY,
    song_id      TEXT,
    youtube_id   TEXT,
    title        TEXT,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS performance (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_id   TEXT NOT NULL,
    date         TEXT,
    view_count   INTEGER,
    watch_time_sec INTEGER,
    ctr          REAL,
    like_count   INTEGER,
    collected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_perf_yt ON performance(youtube_id);

CREATE TABLE IF NOT EXISTS review_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type   TEXT,
    item_id     TEXT,
    decision    TEXT,
    note        TEXT,
    reviewed_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{int.from_bytes(__import__('os').urandom(2), 'big')}"


def connect(path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(path: str | Path = DB_PATH) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 수집 (videos / video_stats / comments)
# ---------------------------------------------------------------------------

def upsert_videos(rows: Iterable[dict], path: str | Path = DB_PATH) -> int:
    """영상 메타+통계 upsert(최신 스냅샷). 동시에 video_stats 에 시계열 1행 append.

    rows 각 항목 키(있는 것만): video_id(필수), channel_id, channel_title, title,
    description, published_at, duration_sec, region, search_keyword,
    subscriber_count, view_count, like_count, comment_count.
    """
    now = _now()
    conn = connect(path)
    n = 0
    try:
        for r in rows:
            vid = r.get("video_id")
            if not vid:
                continue
            conn.execute(
                """
                INSERT INTO videos (video_id, channel_id, channel_title, title,
                    description, published_at, duration_sec, region, search_keyword,
                    subscriber_count, view_count, like_count, comment_count,
                    first_collected_at, last_collected_at)
                VALUES (:video_id, :channel_id, :channel_title, :title, :description,
                    :published_at, :duration_sec, :region, :search_keyword,
                    :subscriber_count, :view_count, :like_count, :comment_count,
                    :now, :now)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    channel_title=excluded.channel_title,
                    title=excluded.title,
                    description=excluded.description,
                    published_at=excluded.published_at,
                    duration_sec=excluded.duration_sec,
                    region=excluded.region,
                    search_keyword=COALESCE(excluded.search_keyword, videos.search_keyword),
                    subscriber_count=excluded.subscriber_count,
                    view_count=excluded.view_count,
                    like_count=excluded.like_count,
                    comment_count=excluded.comment_count,
                    last_collected_at=excluded.last_collected_at
                """,
                {
                    "video_id": vid,
                    "channel_id": r.get("channel_id"),
                    "channel_title": r.get("channel_title"),
                    "title": r.get("title"),
                    "description": r.get("description"),
                    "published_at": r.get("published_at"),
                    "duration_sec": r.get("duration_sec"),
                    "region": r.get("region"),
                    "search_keyword": r.get("search_keyword"),
                    "subscriber_count": r.get("subscriber_count"),
                    "view_count": r.get("view_count"),
                    "like_count": r.get("like_count"),
                    "comment_count": r.get("comment_count"),
                    "now": now,
                },
            )
            conn.execute(
                """INSERT INTO video_stats (video_id, collected_at, view_count,
                       like_count, comment_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (vid, now, r.get("view_count"), r.get("like_count"),
                 r.get("comment_count")),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def add_comments(video_id: str, comments: Iterable[dict],
                 path: str | Path = DB_PATH) -> int:
    """댓글 append(멱등: comment_id 중복 무시). 작성자는 해시로만 저장.

    comments 각 항목: comment_id(필수), text, author, like_count, published_at.
    """
    now = _now()
    conn = connect(path)
    n = 0
    try:
        for c in comments:
            cid = c.get("comment_id")
            if not cid:
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO comments (comment_id, video_id, author_hash,
                       text, like_count, published_at, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cid, video_id, _hash(c.get("author")), c.get("text"),
                 c.get("like_count"), c.get("published_at"), now),
            )
            n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def set_quant_score(video_id: str, score: float, path: str | Path = DB_PATH) -> None:
    conn = connect(path)
    try:
        conn.execute("UPDATE videos SET quant_score=? WHERE video_id=?",
                     (score, video_id))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 분석 (video_features)
# ---------------------------------------------------------------------------

def set_video_features(
    video_id: str,
    *,
    mood: str | None = None,
    energy: str | None = None,
    qual_score: float | None = None,
    emotion_summary: str | None = None,
    style_tags: dict | list | None = None,
    path: str | Path = DB_PATH,
) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """INSERT INTO video_features (video_id, mood, energy, qual_score,
                   emotion_summary, style_tags, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET
                   mood=excluded.mood, energy=excluded.energy,
                   qual_score=excluded.qual_score,
                   emotion_summary=excluded.emotion_summary,
                   style_tags=excluded.style_tags, analyzed_at=excluded.analyzed_at""",
            (video_id, mood, energy, qual_score, emotion_summary,
             json.dumps(style_tags, ensure_ascii=False) if style_tags is not None else None,
             _now()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 생성 체인 (prompts / songs / publications / performance / review)
# ---------------------------------------------------------------------------

def add_prompt(
    *,
    source_video_id: str | None,
    preset: str,
    picks: dict,
    bpm: int | None = None,
    hook: str = "",
    style_prompt: str = "",
    prompt_id: str | None = None,
    path: str | Path = DB_PATH,
) -> str:
    pid = prompt_id or _new_id("prompt")
    conn = connect(path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO prompts (prompt_id, source_video_id, preset,
                   picks, bpm, hook, style_prompt, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, source_video_id, preset,
             json.dumps(picks, ensure_ascii=False), bpm, hook, style_prompt, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return pid


def add_song(*, prompt_id: str, suno_url: str = "", audio_path: str = "",
             song_id: str | None = None, path: str | Path = DB_PATH) -> str:
    sid = song_id or _new_id("song")
    conn = connect(path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO songs (song_id, prompt_id, suno_url, audio_path,
                   created_at) VALUES (?, ?, ?, ?, ?)""",
            (sid, prompt_id, suno_url, audio_path, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def add_publication(*, song_id: str, youtube_id: str, title: str = "",
                    published_at: str | None = None,
                    pub_id: str | None = None, path: str | Path = DB_PATH) -> str:
    pid = pub_id or _new_id("pub")
    conn = connect(path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO publications (pub_id, song_id, youtube_id, title,
                   published_at) VALUES (?, ?, ?, ?, ?)""",
            (pid, song_id, youtube_id, title, published_at or _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return pid


def add_performance(*, youtube_id: str, view_count: int | None = None,
                    watch_time_sec: int | None = None, ctr: float | None = None,
                    like_count: int | None = None, date: str | None = None,
                    path: str | Path = DB_PATH) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """INSERT INTO performance (youtube_id, date, view_count, watch_time_sec,
                   ctr, like_count, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (youtube_id, date or _now()[:10], view_count, watch_time_sec, ctr,
             like_count, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def add_review(*, item_type: str, item_id: str, decision: str, note: str = "",
               path: str | Path = DB_PATH) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """INSERT INTO review_log (item_type, item_id, decision, note, reviewed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (item_type, item_id, decision, note, _now()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def get_video(video_id: str, path: str | Path = DB_PATH) -> dict | None:
    conn = connect(path)
    try:
        row = conn.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_videos(*, order_by: str = "quant_score", desc: bool = True,
                limit: int = 50, path: str | Path = DB_PATH) -> list[dict]:
    allowed = {"quant_score", "view_count", "last_collected_at", "published_at"}
    col = order_by if order_by in allowed else "quant_score"
    direction = "DESC" if desc else "ASC"
    conn = connect(path)
    try:
        rows = conn.execute(
            f"SELECT * FROM videos ORDER BY {col} {direction} NULLS LAST LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def videos_missing(table: str, *, limit: int = 50,
                   path: str | Path = DB_PATH) -> list[dict]:
    """아직 분석(features)/댓글(comments)이 없는 영상 — 다음 단계 작업 큐."""
    if table == "features":
        sub = "SELECT video_id FROM video_features"
    elif table == "comments":
        sub = "SELECT DISTINCT video_id FROM comments"
    else:
        raise ValueError("table 은 'features' 또는 'comments'")
    conn = connect(path)
    try:
        rows = conn.execute(
            f"SELECT * FROM videos WHERE video_id NOT IN ({sub}) "
            f"ORDER BY quant_score DESC NULLS LAST LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_comments(video_id: str, path: str | Path = DB_PATH) -> list[dict]:
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM comments WHERE video_id=? ORDER BY like_count DESC", (video_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def counts(path: str | Path = DB_PATH) -> dict[str, int]:
    """테이블별 행 수 — 자산이 얼마나 쌓였는지 한눈에."""
    tables = ["videos", "video_stats", "comments", "video_features", "prompts",
              "songs", "publications", "performance", "review_log"]
    conn = connect(path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "demo.db"
    init_db(tmp)

    upsert_videos([{
        "video_id": "abc123", "channel_title": "추억의 트로트", "title": "비 오는 밤 트로트",
        "published_at": "2026-05-20T00:00:00Z", "subscriber_count": 800,
        "view_count": 50000, "like_count": 1200, "comment_count": 300,
        "search_keyword": "트로트 발라드",
    }], path=tmp)
    # 재수집(통계 갱신) → videos 는 1행, video_stats 는 2행이 되어야 함
    upsert_videos([{"video_id": "abc123", "view_count": 62000, "like_count": 1500,
                    "comment_count": 340}], path=tmp)
    set_quant_score("abc123", 47.5, path=tmp)
    add_comments("abc123", [
        {"comment_id": "c1", "author": "할머니팬", "text": "눈물나요", "like_count": 50},
        {"comment_id": "c2", "author": "트로트사랑", "text": "어머니 생각", "like_count": 30},
        {"comment_id": "c1", "author": "할머니팬", "text": "중복", "like_count": 0},  # 무시돼야
    ], path=tmp)
    set_video_features("abc123", mood="tearful, emotional, heartfelt", energy="low",
                       qual_score=38.0, emotion_summary="눈물·고향·어머니",
                       style_tags={"instruments": ["saxophone solo"]}, path=tmp)
    pid = add_prompt(source_video_id="abc123", preset="kr_trot",
                     picks={"mood": ["tearful, emotional, heartfelt"]}, bpm=70,
                     style_prompt="Korean trot, tearful, 70 BPM", path=tmp)
    sid = add_song(prompt_id=pid, audio_path="/out/song.mp3", path=tmp)
    add_publication(song_id=sid, youtube_id="yt_xyz", title="비오는밤", path=tmp)
    add_performance(youtube_id="yt_xyz", view_count=1200, watch_time_sec=300, ctr=0.06,
                    like_count=80, path=tmp)
    add_review(item_type="prompt", item_id=pid, decision="approved", note="좋음", path=tmp)

    print("테이블별 행 수:", json.dumps(counts(tmp), ensure_ascii=False))
    v = get_video("abc123", tmp)
    print(f"영상 abc123: 조회수={v['view_count']} (재수집 반영), quant_score={v['quant_score']}")
    print("분석 대기(features 없는 영상):", len(videos_missing("features", path=tmp)))
    print("프롬프트 source_video_id 연결:", add_prompt.__name__, "→", pid[:12], "...")
