"""
공구 중개업 SQLite DB
- 인플루언서 DB (팔로워, 카테고리, 공구 이력)
- 제조사/공급사 DB
- 공구 아이템 DB (시즌별 트래킹)
- 메일 발송 이력
"""
import sqlite3, json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("gonggu.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    instagram_id TEXT UNIQUE NOT NULL,
    name        TEXT,
    followers   INTEGER,
    category    TEXT,       -- 뷰티/식품/패션/생활/건강/반려동물/육아
    sub_category TEXT,
    email       TEXT,
    dm_link     TEXT,
    commission_rate REAL,   -- 수수료율 %
    note        TEXT,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS gonggu_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id   INTEGER REFERENCES influencers(id),
    item_name       TEXT,
    category        TEXT,
    season          TEXT,   -- 봄/여름/가을/겨울/연중
    month           INTEGER,
    sale_price      INTEGER,
    estimated_qty   INTEGER,
    actual_revenue  INTEGER,
    sold_out        INTEGER DEFAULT 0,  -- 완판 여부
    start_date      TEXT,
    end_date        TEXT,
    note            TEXT,
    created_at      TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS manufacturers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT NOT NULL,
    contact_name TEXT,
    email       TEXT,
    phone       TEXT,
    category    TEXT,
    product_line TEXT,
    supply_price_range TEXT,  -- 공급가 범위
    min_order   TEXT,         -- 최소 주문량
    can_dropship INTEGER DEFAULT 1,  -- 직배송 가능
    note        TEXT,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS season_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    season      TEXT,       -- 봄/여름/가을/겨울
    month_start INTEGER,
    month_end   INTEGER,
    category    TEXT,
    item_name   TEXT,
    keyword     TEXT,
    demand_level TEXT,      -- 높음/중간/낮음
    note        TEXT
);

CREATE TABLE IF NOT EXISTS mail_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type     TEXT,   -- influencer / manufacturer
    target_id       INTEGER,
    to_email        TEXT,
    subject         TEXT,
    body            TEXT,
    template_name   TEXT,
    status          TEXT DEFAULT 'draft',  -- draft/sent/bounced
    sent_at         TEXT,
    reply_received  INTEGER DEFAULT 0,
    reply_note      TEXT,
    created_at      TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id   INTEGER REFERENCES influencers(id),
    manufacturer_id INTEGER REFERENCES manufacturers(id),
    item_name       TEXT,
    status          TEXT DEFAULT 'negotiating',  -- negotiating/confirmed/live/done/failed
    commission_rate REAL,
    revenue_total   INTEGER,
    my_revenue      INTEGER,
    start_date      TEXT,
    note            TEXT,
    created_at      TEXT DEFAULT (datetime('now','localtime'))
);
"""

SEED_SEASON_ITEMS = [
    ("겨울→봄 전환", 2, 3, "뷰티", "자외선차단제", "선크림 공구", "높음", "봄 필수템"),
    ("겨울→봄 전환", 2, 3, "다이어트", "다이어트 보조제", "다이어트 공구", "높음", "봄 다이어트 시즌"),
    ("봄", 4, 5, "패션", "봄 의류", "봄코디 공구", "높음", "계절 전환기"),
    ("봄", 4, 5, "건강식품", "건강기능식품", "비타민 공구", "중간", ""),
    ("봄", 4, 5, "반려동물", "펫 용품", "펫 공구", "중간", ""),
    ("초여름", 6, 6, "생활가전", "무선 선풍기", "여름 가전 공구", "높음", "6월 폭발적 수요"),
    ("초여름", 6, 6, "패션", "냉감 의류", "냉감 공구", "높음", ""),
    ("여름", 7, 8, "신선식품", "복숭아·납작복숭아", "제철과일 공구", "높음", "완판률 최고"),
    ("여름", 7, 8, "신선식품", "초당 옥수수", "제철 옥수수 공구", "높음", "한시적 판매"),
    ("여름", 7, 8, "신선식품", "참외", "참외 공구", "높음", "2~3주 한정"),
    ("여름", 7, 8, "식품", "밀키트", "밀키트 공구", "중간", ""),
    ("가을", 9, 10, "건강식품", "홍삼·콜라겐", "건강식품 공구", "높음", "가을 보양 시즌"),
    ("가을", 9, 10, "뷰티", "이너뷰티", "이너뷰티 공구", "중간", ""),
    ("가을", 9, 10, "패션", "가을 의류", "가을코디 공구", "높음", ""),
    ("가을", 9, 10, "생활", "핫팩", "핫팩 공구", "중간", ""),
    ("연말", 11, 12, "뷰티", "뷰티 선물세트", "선물세트 공구", "높음", "크리스마스·연말 선물"),
    ("연말", 11, 12, "식품", "홈파티 식품", "홈파티 공구", "중간", ""),
    ("연말", 11, 12, "생활", "보온 홈웨어", "홈웨어 공구", "중간", ""),
    ("연중", 1, 12, "식품", "다이어트 식품", "다이어트 공구", "높음", "연중 수요 있음"),
    ("연중", 1, 12, "생활", "주방용품", "주방 공구", "중간", ""),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # 시즌 아이템 시드 (없으면 삽입)
    cur = conn.execute("SELECT COUNT(*) FROM season_items")
    if cur.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO season_items (season,month_start,month_end,category,item_name,keyword,demand_level,note) VALUES (?,?,?,?,?,?,?,?)",
            SEED_SEASON_ITEMS,
        )
    conn.commit()
    conn.close()


# ── 인플루언서 ──────────────────────────────────────────
def upsert_influencer(data: dict) -> int:
    conn = get_conn()
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id FROM influencers WHERE instagram_id=?", (data["instagram_id"],)
    ).fetchone()
    if existing:
        fields = ", ".join(f"{k}=?" for k in data if k != "instagram_id")
        vals = [v for k, v in data.items() if k != "instagram_id"] + [data["instagram_id"]]
        conn.execute(f"UPDATE influencers SET {fields} WHERE instagram_id=?", vals)
        row_id = existing["id"]
    else:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        conn.execute(f"INSERT INTO influencers ({cols}) VALUES ({placeholders})", list(data.values()))
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return row_id


def get_influencers(category=None, min_followers=0):
    conn = get_conn()
    q = "SELECT * FROM influencers WHERE followers >= ?"
    params = [min_followers]
    if category and category != "전체":
        q += " AND category=?"
        params.append(category)
    q += " ORDER BY followers DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    return rows


def delete_influencer(iid: int):
    conn = get_conn()
    conn.execute("DELETE FROM influencers WHERE id=?", (iid,))
    conn.commit(); conn.close()


# ── 공구 이력 ───────────────────────────────────────────
def add_gonggu_history(data: dict):
    conn = get_conn()
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" * len(data))
    conn.execute(f"INSERT INTO gonggu_history ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit(); conn.close()


def get_gonggu_history(influencer_id=None):
    conn = get_conn()
    if influencer_id:
        rows = conn.execute(
            "SELECT gh.*, i.name, i.instagram_id FROM gonggu_history gh JOIN influencers i ON gh.influencer_id=i.id WHERE gh.influencer_id=? ORDER BY gh.created_at DESC",
            (influencer_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT gh.*, i.name, i.instagram_id FROM gonggu_history gh LEFT JOIN influencers i ON gh.influencer_id=i.id ORDER BY gh.created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 제조사 ──────────────────────────────────────────────
def upsert_manufacturer(data: dict) -> int:
    conn = get_conn()
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id FROM manufacturers WHERE company=? AND email=?",
        (data.get("company"), data.get("email", "")),
    ).fetchone()
    if existing:
        mid = existing["id"]
        fields = ", ".join(f"{k}=?" for k in data)
        conn.execute(f"UPDATE manufacturers SET {fields} WHERE id=?", list(data.values()) + [mid])
    else:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        conn.execute(f"INSERT INTO manufacturers ({cols}) VALUES ({placeholders})", list(data.values()))
        mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return mid


def get_manufacturers(category=None):
    conn = get_conn()
    if category and category != "전체":
        rows = conn.execute("SELECT * FROM manufacturers WHERE category=? ORDER BY company", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM manufacturers ORDER BY company").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_manufacturer(mid: int):
    conn = get_conn()
    conn.execute("DELETE FROM manufacturers WHERE id=?", (mid,))
    conn.commit(); conn.close()


# ── 시즌 아이템 ─────────────────────────────────────────
def get_season_items(month=None, season=None):
    conn = get_conn()
    if month:
        rows = conn.execute(
            "SELECT * FROM season_items WHERE month_start<=? AND month_end>=? ORDER BY demand_level DESC",
            (month, month),
        ).fetchall()
    elif season:
        rows = conn.execute(
            "SELECT * FROM season_items WHERE season=? ORDER BY demand_level DESC", (season,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM season_items ORDER BY month_start").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 메일 로그 ───────────────────────────────────────────
def save_mail_log(data: dict) -> int:
    conn = get_conn()
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" * len(data))
    conn.execute(f"INSERT INTO mail_log ({cols}) VALUES ({placeholders})", list(data.values()))
    mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return mid


def get_mail_log(target_type=None, status=None):
    conn = get_conn()
    q = "SELECT * FROM mail_log WHERE 1=1"
    params = []
    if target_type:
        q += " AND target_type=?"
        params.append(target_type)
    if status:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_mail_status(log_id: int, status: str, reply_note: str = ""):
    conn = get_conn()
    conn.execute(
        "UPDATE mail_log SET status=?, sent_at=?, reply_note=? WHERE id=?",
        (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), reply_note, log_id),
    )
    conn.commit(); conn.close()


# ── 딜 관리 ─────────────────────────────────────────────
def add_deal(data: dict) -> int:
    conn = get_conn()
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" * len(data))
    conn.execute(f"INSERT INTO deals ({cols}) VALUES ({placeholders})", list(data.values()))
    did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return did


def get_deals():
    conn = get_conn()
    rows = conn.execute(
        """SELECT d.*, i.name as inf_name, i.instagram_id, m.company as mfr_name
           FROM deals d
           LEFT JOIN influencers i ON d.influencer_id=i.id
           LEFT JOIN manufacturers m ON d.manufacturer_id=m.id
           ORDER BY d.created_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_deal_status(did: int, status: str, my_revenue: int = None):
    conn = get_conn()
    if my_revenue is not None:
        conn.execute("UPDATE deals SET status=?, my_revenue=? WHERE id=?", (status, my_revenue, did))
    else:
        conn.execute("UPDATE deals SET status=? WHERE id=?", (status, did))
    conn.commit(); conn.close()


if __name__ == "__main__":
    init_db()
    print("✅ gonggu.db 초기화 완료")
