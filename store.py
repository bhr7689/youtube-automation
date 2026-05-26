"""SQLite 영속 계층 — 자동 수집(cron)과 Streamlit UI 사이의 비동기 경계.

cron 으로 도는 ``automation.py`` 가 수집·정량필터 결과를 여기에 적재하고,
``app.py`` 의 UI 는 라이브 API 대신 이 DB 를 즉시 읽어 버퍼링 없이 검수만 한다.

설계 원칙:
- API 키 등 비밀값은 절대 저장하지 않는다(설정 메타만 보관).
- 외부 의존성 없음(stdlib sqlite3 + pandas). 어떤 프로세스에서도 import 가능.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_DB = "ktrot.db"

# build_dataframe() 가 생성하는 컬럼과 1:1 로 매핑된다.
VIDEO_COLUMNS: tuple[str, ...] = (
    "video_id",
    "video_title",
    "channel_title",
    "published_at",
    "duration_sec",
    "view_count",
    "like_count",
    "comment_count",
    "subscriber_count",
    "view_sub_ratio",
    "channel_video_count",
    "channel_country",
    "video_url",
    "channel_url",
    "thumbnail_url",
    "channel_id",
)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = DEFAULT_DB) -> None:
    """테이블이 없으면 생성한다(idempotent)."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                keywords    TEXT NOT NULL,
                region      TEXT,
                language    TEXT,
                days        INTEGER,
                max_results INTEGER,
                order_by    TEXT,
                max_subscribers INTEGER,
                min_views   INTEGER,
                min_ratio   REAL,
                video_count INTEGER,
                filtered_count INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                run_id      INTEGER NOT NULL,
                video_id    TEXT,
                video_title TEXT,
                channel_title TEXT,
                published_at TEXT,
                duration_sec INTEGER,
                view_count  INTEGER,
                like_count  INTEGER,
                comment_count INTEGER,
                subscriber_count INTEGER,
                view_sub_ratio REAL,
                channel_video_count INTEGER,
                channel_country TEXT,
                video_url   TEXT,
                channel_url TEXT,
                thumbnail_url TEXT,
                channel_id  TEXT,
                is_breakout INTEGER DEFAULT 0,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_run ON videos(run_id)")
        conn.commit()


def save_run(
    df: pd.DataFrame,
    config: dict,
    *,
    filtered_ids: set[str] | None = None,
    db_path: str | Path = DEFAULT_DB,
) -> int:
    """한 번의 수집 결과를 저장하고 run_id 를 돌려준다.

    config 는 SearchConfig 를 dict 로 변환한 것(단, api_key 는 포함하지 말 것).
    filtered_ids 는 정량필터를 통과한 video_id 집합(검수 우선순위 표시용).
    """
    init_db(db_path)
    filtered_ids = filtered_ids or set()
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (created_at, keywords, region, language, days,
                              max_results, order_by, max_subscribers, min_views,
                              min_ratio, video_count, filtered_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                json.dumps(list(config.get("keywords", [])), ensure_ascii=False),
                config.get("region_code"),
                config.get("language"),
                config.get("days"),
                config.get("max_results_per_keyword"),
                config.get("order"),
                config.get("max_subscribers"),
                config.get("min_views"),
                config.get("min_view_sub_ratio"),
                int(len(df)),
                int(len(filtered_ids)),
            ),
        )
        run_id = int(cur.lastrowid)

        if not df.empty:
            rows = []
            for rec in df.to_dict("records"):
                published = rec.get("published_at")
                if isinstance(published, (pd.Timestamp, datetime)):
                    published = published.isoformat()
                vid = rec.get("video_id")
                rows.append(
                    (
                        run_id,
                        vid,
                        rec.get("video_title"),
                        rec.get("channel_title"),
                        published,
                        _int(rec.get("duration_sec")),
                        _int(rec.get("view_count")),
                        _int(rec.get("like_count")),
                        _int(rec.get("comment_count")),
                        _int(rec.get("subscriber_count")),
                        _float(rec.get("view_sub_ratio")),
                        _int(rec.get("channel_video_count")),
                        rec.get("channel_country"),
                        rec.get("video_url"),
                        rec.get("channel_url"),
                        rec.get("thumbnail_url"),
                        rec.get("channel_id"),
                        1 if vid in filtered_ids else 0,
                    )
                )
            conn.executemany(
                """
                INSERT INTO videos (run_id, video_id, video_title, channel_title,
                    published_at, duration_sec, view_count, like_count, comment_count,
                    subscriber_count, view_sub_ratio, channel_video_count,
                    channel_country, video_url, channel_url, thumbnail_url,
                    channel_id, is_breakout)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()
    return run_id


def list_runs(db_path: str | Path = DEFAULT_DB, limit: int = 50) -> list[dict]:
    """최근 수집 실행 메타 목록(최신순)."""
    if not Path(db_path).exists():
        return []
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [_run_to_meta(r) for r in cur.fetchall()]


def load_run(run_id: int, db_path: str | Path = DEFAULT_DB) -> tuple[dict, pd.DataFrame] | None:
    """특정 run 의 (메타, DataFrame) 을 돌려준다."""
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return None
        df = _load_videos(conn, run_id)
    return _run_to_meta(run), df


def load_latest(db_path: str | Path = DEFAULT_DB) -> tuple[dict, pd.DataFrame] | None:
    """가장 최근 run 의 (메타, DataFrame)."""
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if run is None:
            return None
        df = _load_videos(conn, run["id"])
    return _run_to_meta(run), df


def _load_videos(conn: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    cur = conn.execute(
        f"SELECT {', '.join(VIDEO_COLUMNS)}, is_breakout FROM videos WHERE run_id = ? "
        "ORDER BY view_sub_ratio DESC",
        (run_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    df = pd.DataFrame(rows, columns=list(VIDEO_COLUMNS) + ["is_breakout"])
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    return df


def _run_to_meta(row: sqlite3.Row) -> dict:
    meta = dict(row)
    try:
        meta["keywords"] = json.loads(meta.get("keywords") or "[]")
    except (json.JSONDecodeError, TypeError):
        meta["keywords"] = []
    return meta


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
