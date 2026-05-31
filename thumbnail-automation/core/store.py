"""
SQLite DB 토대.
테이블: channels / thumbnails / analysis / generated_thumbnails
append-only 이력 + upsert 멱등성. stdlib sqlite3만 사용.
"""
import json
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.config import DB_PATH

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 연결
# ─────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────
# 초기화
# ─────────────────────────────────────────────────────────

def init_db():
    """DB 및 전체 테이블 생성 (멱등)."""
    with get_conn() as conn:
        conn.executescript("""
        -- 수집된 채널
        CREATE TABLE IF NOT EXISTS channels (
            channel_id      TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            category        TEXT,
            subscriber_cnt  INTEGER DEFAULT 0,
            avg_view_cnt    INTEGER DEFAULT 0,
            avg_ctr_est     REAL    DEFAULT 0.0,
            country         TEXT,
            collected_at    TEXT    NOT NULL
        );

        -- 수집된 썸네일
        CREATE TABLE IF NOT EXISTS thumbnails (
            thumb_id        TEXT PRIMARY KEY,
            channel_id      TEXT NOT NULL REFERENCES channels(channel_id),
            video_id        TEXT NOT NULL UNIQUE,
            title           TEXT,
            image_url       TEXT NOT NULL,
            local_path      TEXT,
            view_count      INTEGER DEFAULT 0,
            like_count      INTEGER DEFAULT 0,
            comment_count   INTEGER DEFAULT 0,
            published_at    TEXT,
            is_viral        INTEGER DEFAULT 0,
            collected_at    TEXT NOT NULL
        );

        -- 12레이어 분석 결과
        CREATE TABLE IF NOT EXISTS analysis (
            analysis_id         TEXT PRIMARY KEY,
            thumb_id            TEXT NOT NULL REFERENCES thumbnails(thumb_id),
            layer1_composition  TEXT,   -- JSON: rule_of_thirds, golden_ratio, type
            layer2_colors       TEXT,   -- JSON: primary_hex, secondary_hex, accent_hex, contrast, temp
            layer3_face         TEXT,   -- JSON: gaze_dir, emotion, mouth_open, eye_scale
            layer4_hair         TEXT,   -- JSON: style, color, volume, face_cover_pct
            layer5_feature      TEXT,   -- JSON: items (점/안경/문신 등)
            layer6_objects      TEXT,   -- JSON: has_animal, items[]
            layer7_layout       TEXT,   -- JSON: elements[{name, x_pct, y_pct, area_pct}]
            layer8_background   TEXT,   -- JSON: type, brightness, contrast_with_subject
            layer9_text         TEXT,   -- JSON: font_family, size_pct, position, color, has_stroke, char_count
            layer10_emotion     TEXT,   -- JSON: primary, secondary
            layer11_trigger     TEXT,   -- 클릭욕구 트리거 (단일 텍스트)
            layer12_hook        TEXT,   -- 한 끗 제안 (단일 텍스트)
            analyzed_at         TEXT    NOT NULL
        );

        -- 생성된 썸네일 후보
        CREATE TABLE IF NOT EXISTS generated_thumbnails (
            gen_id          TEXT PRIMARY KEY,
            analysis_id     TEXT NOT NULL REFERENCES analysis(analysis_id),
            hook_type       TEXT,
            prompt_text     TEXT,
            image_path      TEXT,
            ctr_score       REAL DEFAULT 0.0,
            status          TEXT DEFAULT 'pending',  -- pending/approved/rejected
            feedback        TEXT,
            created_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_thumb_channel  ON thumbnails(channel_id);
        CREATE INDEX IF NOT EXISTS idx_analysis_thumb ON analysis(thumb_id);
        CREATE INDEX IF NOT EXISTS idx_gen_analysis   ON generated_thumbnails(analysis_id);
        CREATE INDEX IF NOT EXISTS idx_gen_status     ON generated_thumbnails(status);
        """)
    logger.info("DB 초기화 완료: %s", DB_PATH)

    # 기존 DB 마이그레이션 — 블록 밖에서 별도 커넥션으로 실행
    _migrate()


def _migrate():
    with get_conn() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(thumbnails)").fetchall()}
        if "comment_count" not in existing:
            conn.execute("ALTER TABLE thumbnails ADD COLUMN comment_count INTEGER DEFAULT 0")
            logger.info("마이그레이션: thumbnails.comment_count 추가")


# ─────────────────────────────────────────────────────────
# channels
# ─────────────────────────────────────────────────────────

def upsert_channel(ch: dict):
    sql = """
    INSERT INTO channels (channel_id, name, category, subscriber_cnt,
                          avg_view_cnt, avg_ctr_est, country, collected_at)
    VALUES (:channel_id,:name,:category,:subscriber_cnt,
            :avg_view_cnt,:avg_ctr_est,:country,:collected_at)
    ON CONFLICT(channel_id) DO UPDATE SET
        name           = excluded.name,
        subscriber_cnt = excluded.subscriber_cnt,
        avg_view_cnt   = excluded.avg_view_cnt,
        avg_ctr_est    = excluded.avg_ctr_est,
        collected_at   = excluded.collected_at
    """
    ch.setdefault("collected_at", datetime.utcnow().isoformat())
    with get_conn() as conn:
        conn.execute(sql, ch)


def list_channels(category: str | None = None) -> list[dict]:
    sql = "SELECT * FROM channels"
    params: list = []
    if category:
        sql += " WHERE category = ?"
        params.append(category)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ─────────────────────────────────────────────────────────
# thumbnails
# ─────────────────────────────────────────────────────────

def upsert_thumbnail(th: dict):
    sql = """
    INSERT INTO thumbnails (thumb_id, channel_id, video_id, title,
                            image_url, local_path, view_count, like_count,
                            comment_count, is_viral, published_at, collected_at)
    VALUES (:thumb_id,:channel_id,:video_id,:title,
            :image_url,:local_path,:view_count,:like_count,
            :comment_count,:is_viral,:published_at,:collected_at)
    ON CONFLICT(video_id) DO UPDATE SET
        title         = excluded.title,
        view_count    = excluded.view_count,
        like_count    = excluded.like_count,
        comment_count = excluded.comment_count,
        is_viral      = excluded.is_viral,
        collected_at  = excluded.collected_at
    """
    th.setdefault("collected_at", datetime.utcnow().isoformat())
    th.setdefault("local_path", None)
    th.setdefault("comment_count", 0)
    th.setdefault("is_viral", 0)
    with get_conn() as conn:
        conn.execute(sql, th)


def list_unanalyzed_thumbnails(limit: int = 50) -> list[dict]:
    """분석 기록이 없는 썸네일 목록."""
    sql = """
    SELECT t.* FROM thumbnails t
    LEFT JOIN analysis a ON a.thumb_id = t.thumb_id
    WHERE a.analysis_id IS NULL
    ORDER BY t.view_count DESC
    LIMIT ?
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]


def update_thumbnail_local_path(thumb_id: str, local_path: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE thumbnails SET local_path=? WHERE thumb_id=?",
            (local_path, thumb_id)
        )


# ─────────────────────────────────────────────────────────
# analysis
# ─────────────────────────────────────────────────────────

def _json(v) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def insert_analysis(a: dict):
    """12레이어 분석 결과 저장. JSON 필드는 dict로 넘겨도 자동 직렬화."""
    json_fields = [f"layer{i}" for i in range(1, 13)]
    layer_keys  = [
        "layer1_composition","layer2_colors","layer3_face","layer4_hair",
        "layer5_feature","layer6_objects","layer7_layout","layer8_background",
        "layer9_text","layer10_emotion","layer11_trigger","layer12_hook",
    ]
    row = dict(a)
    for k in layer_keys:
        if isinstance(row.get(k), dict) or isinstance(row.get(k), list):
            row[k] = _json(row[k])
    row.setdefault("analyzed_at", datetime.utcnow().isoformat())

    sql = """
    INSERT OR IGNORE INTO analysis
        (analysis_id, thumb_id,
         layer1_composition, layer2_colors, layer3_face, layer4_hair,
         layer5_feature, layer6_objects, layer7_layout, layer8_background,
         layer9_text, layer10_emotion, layer11_trigger, layer12_hook,
         analyzed_at)
    VALUES
        (:analysis_id, :thumb_id,
         :layer1_composition, :layer2_colors, :layer3_face, :layer4_hair,
         :layer5_feature, :layer6_objects, :layer7_layout, :layer8_background,
         :layer9_text, :layer10_emotion, :layer11_trigger, :layer12_hook,
         :analyzed_at)
    """
    with get_conn() as conn:
        conn.execute(sql, row)


def get_analysis(thumb_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM analysis WHERE thumb_id=?", (thumb_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    for k in result:
        if k.startswith("layer") and isinstance(result[k], str):
            try:
                result[k] = json.loads(result[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


# ─────────────────────────────────────────────────────────
# generated_thumbnails
# ─────────────────────────────────────────────────────────

def insert_generated(g: dict):
    g.setdefault("created_at", datetime.utcnow().isoformat())
    g.setdefault("status", "pending")
    sql = """
    INSERT OR IGNORE INTO generated_thumbnails
        (gen_id, analysis_id, hook_type, prompt_text,
         image_path, ctr_score, status, feedback, created_at)
    VALUES
        (:gen_id,:analysis_id,:hook_type,:prompt_text,
         :image_path,:ctr_score,:status,:feedback,:created_at)
    """
    with get_conn() as conn:
        conn.execute(sql, g)


def update_generated_status(gen_id: str, status: str, feedback: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE generated_thumbnails SET status=?, feedback=? WHERE gen_id=?",
            (status, feedback, gen_id)
        )


def list_generated(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM generated_thumbnails"
    params: list = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ─────────────────────────────────────────────────────────
# 통계
# ─────────────────────────────────────────────────────────

def get_stats() -> dict:
    with get_conn() as conn:
        def cnt(table, where=""):
            return conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
        return {
            "channels":   cnt("channels"),
            "thumbnails": cnt("thumbnails"),
            "analyzed":   cnt("analysis"),
            "generated":  cnt("generated_thumbnails"),
            "approved":   cnt("generated_thumbnails", "WHERE status='approved'"),
            "pending":    cnt("generated_thumbnails", "WHERE status='pending'"),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("✅ DB 초기화 완료:", DB_PATH)
    print("📊 현재 통계:", get_stats())
