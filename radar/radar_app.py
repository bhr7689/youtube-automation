"""
경쟁 채널 인텔리전스 레이더
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실행: streamlit run radar_app.py
의존: requirements.txt 만 필요. 외부 모듈 없음.
DB : radar.db (SQLite, 자동 생성)
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Streamlit Cloud secrets → os.environ ────────────────────────────────────
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# 0. 페이지 설정
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="경쟁 채널 인텔리전스 레이더",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── 전역 다크 스타일 ── */
html, body, [data-testid="stAppViewContainer"] {
    background: #0d1117;
    color: #e6edf3;
}
[data-testid="stSidebar"] {
    background: #161b22;
    border-right: 1px solid #30363d;
    min-width: 260px !important;
    max-width: 260px !important;
}
div[data-testid="stSidebarNav"] { display: none; }

/* ── 탭 ── */
.stTabs [data-baseweb="tab-list"] {
    background: #161b22;
    border-radius: 8px;
    padding: 4px;
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    border-radius: 6px;
    color: #8b949e;
    font-size: 0.85rem;
}
.stTabs [aria-selected="true"] {
    background: #238636 !important;
    color: #fff !important;
}

/* ── 카드 ── */
.top-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.6rem;
    transition: border-color .2s;
}
.top-card:hover { border-color: #238636; }
.top-label { font-size: 0.68rem; color: #3fb950; font-weight: 700; letter-spacing: 1.5px; }
.top-title { font-size: 0.92rem; font-weight: 600; margin: 0.35rem 0 0.2rem 0; line-height: 1.4; }
.top-meta  { font-size: 0.76rem; color: #8b949e; }

/* ── 채널 행 ── */
.ch-row {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 0.6rem 0.9rem;
    margin-bottom: 0.4rem;
    display: flex;
    align-items: center;
    gap: 10px;
}

/* ── 배지 ── */
.badge {
    display: inline-block;
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.72rem;
    color: #8b949e;
    margin-right: 4px;
}

/* ── 버튼 ── */
.stButton > button {
    border-radius: 6px !important;
    font-size: 0.82rem !important;
}

/* ── 입력 ── */
.stTextInput input, .stTextArea textarea {
    background: #0d1117 !important;
    border: 1px solid #30363d !important;
    border-radius: 6px !important;
    color: #e6edf3 !important;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SQLite 엔진
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent / "radar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name       TEXT NOT NULL,
    channel_id       TEXT NOT NULL,
    channel_title    TEXT,
    thumbnail_url    TEXT,
    subscriber_count INTEGER DEFAULT 0,
    added_at         TEXT NOT NULL,
    last_fetched_at  TEXT,
    UNIQUE(group_name, channel_id)
);
CREATE TABLE IF NOT EXISTS videos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id    TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    title         TEXT,
    view_count    INTEGER DEFAULT 0,
    like_count    INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    published_at  TEXT,
    thumbnail_url TEXT,
    fetched_at    TEXT NOT NULL,
    UNIQUE(channel_id, video_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     TEXT NOT NULL,
    author_hash  TEXT,
    text         TEXT,
    like_count   INTEGER DEFAULT 0,
    collected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thumbnails (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       TEXT NOT NULL,
    channel_id     TEXT,
    channel_title  TEXT,
    video_title    TEXT,
    thumbnail_url  TEXT,
    published_at   TEXT,
    view_count     INTEGER DEFAULT 0,
    ai_analysis    TEXT,
    mj_prompt      TEXT,
    dalle_prompt   TEXT,
    collected_at   TEXT NOT NULL,
    UNIQUE(video_id)
);
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    content    TEXT,
    tags       TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fmt_num(n) -> str:
    n = int(n or 0)
    if n >= 100_000_000: return f"{n/100_000_000:.1f}억"
    if n >= 10_000:      return f"{n/10_000:.1f}만"
    if n >= 1_000:       return f"{n/1_000:.1f}천"
    return str(n)


def fmt_date(iso: str) -> str:
    if not iso: return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y.%m.%d")
    except Exception:
        return iso[:10]


init_db()


# ─────────────────────────────────────────────────────────────────────────────
# 2. YouTube API 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _yt(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key)


def resolve_channel_id(api_key: str, url_or_handle: str) -> str | None:
    s = url_or_handle.strip()
    if s.startswith("UC") and len(s) == 24:
        return s
    if "youtube.com/channel/" in s:
        return s.split("youtube.com/channel/")[-1].split("/")[0].split("?")[0]
    handle = s.split("youtube.com/@")[-1].split("/")[0].lstrip("@")
    try:
        yt = _yt(api_key)
        r = yt.channels().list(part="id", forHandle=f"@{handle}").execute()
        if r.get("items"):
            return r["items"][0]["id"]
        r2 = yt.search().list(part="snippet", q=handle, type="channel", maxResults=1).execute()
        if r2.get("items"):
            return r2["items"][0]["snippet"]["channelId"]
    except Exception:
        pass
    return None


def fetch_channel_info(api_key: str, channel_id: str) -> dict:
    try:
        r = _yt(api_key).channels().list(part="snippet,statistics", id=channel_id).execute()
        if not r.get("items"):
            return {"channel_id": channel_id, "title": channel_id}
        it = r["items"][0]
        return {
            "channel_id": channel_id,
            "title": it["snippet"]["title"],
            "thumbnail_url": it["snippet"]["thumbnails"].get("default", {}).get("url", ""),
            "subscriber_count": int(it["statistics"].get("subscriberCount", 0)),
        }
    except Exception:
        return {"channel_id": channel_id, "title": channel_id}


def fetch_channel_videos(api_key: str, channel_id: str, max_results: int = 20) -> list[dict]:
    try:
        yt = _yt(api_key)
        sr = yt.search().list(
            part="snippet", channelId=channel_id,
            order="date", type="video",
            maxResults=min(max_results, 50)
        ).execute()
        ids = [i["id"]["videoId"] for i in sr.get("items", [])]
        if not ids:
            return []
        vr = yt.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
        out = []
        for it in vr.get("items", []):
            s = it.get("statistics", {})
            out.append({
                "video_id": it["id"],
                "title": it["snippet"]["title"],
                "view_count": int(s.get("viewCount", 0)),
                "like_count": int(s.get("likeCount", 0)),
                "comment_count": int(s.get("commentCount", 0)),
                "published_at": it["snippet"]["publishedAt"],
                "thumbnail_url": it["snippet"]["thumbnails"].get("medium", {}).get("url", ""),
            })
        return out
    except Exception:
        return []


def fetch_video_comments(api_key: str, video_id: str, max_results: int = 100) -> list[dict]:
    try:
        r = _yt(api_key).commentThreads().list(
            part="snippet", videoId=video_id,
            order="relevance", maxResults=min(max_results, 100)
        ).execute()
        out = []
        for it in r.get("items", []):
            top = it["snippet"]["topLevelComment"]["snippet"]
            out.append({
                "text": top.get("textDisplay", ""),
                "author": top.get("authorDisplayName", ""),
                "like_count": int(top.get("likeCount", 0)),
            })
        return out
    except Exception:
        return []


def is_cache_fresh(channel_id: str, ttl_hours: int = 24) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT last_fetched_at FROM channels WHERE channel_id=?", (channel_id,)
        ).fetchone()
    if not row or not row["last_fetched_at"]:
        return False
    try:
        last = datetime.fromisoformat(row["last_fetched_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last) < timedelta(hours=ttl_hours)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. DB CRUD
# ─────────────────────────────────────────────────────────────────────────────

# ── 그룹 ──
def list_groups() -> list[str]:
    with _conn() as c:
        return [r["name"] for r in c.execute("SELECT name FROM groups ORDER BY id").fetchall()]

def add_group(name: str) -> bool:
    try:
        with _conn() as c:
            c.execute("INSERT INTO groups(name,created_at) VALUES(?,?)", (name, _now()))
        return True
    except sqlite3.IntegrityError:
        return False

def rename_group(old: str, new: str):
    with _conn() as c:
        c.execute("UPDATE groups SET name=? WHERE name=?", (new, old))
        c.execute("UPDATE channels SET group_name=? WHERE group_name=?", (new, old))

def delete_group(name: str):
    with _conn() as c:
        c.execute("DELETE FROM channels WHERE group_name=?", (name,))
        c.execute("DELETE FROM groups WHERE name=?", (name,))

# ── 채널 ──
def list_channels(group: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM channels WHERE group_name=? ORDER BY subscriber_count DESC", (group,)
        ).fetchall()
    return [dict(r) for r in rows]

def upsert_channel(group: str, info: dict):
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO channels
            (group_name,channel_id,channel_title,thumbnail_url,subscriber_count,added_at)
            VALUES(?,?,?,?,?,?)
        """, (group, info["channel_id"], info.get("title",""), info.get("thumbnail_url",""),
              info.get("subscriber_count",0), _now()))

def delete_channel(group: str, channel_id: str):
    with _conn() as c:
        c.execute("DELETE FROM channels WHERE group_name=? AND channel_id=?", (group, channel_id))

def refresh_all_subscribers(api_key: str, group: str):
    chs = list_channels(group)
    if not chs: return
    ids = [c["channel_id"] for c in chs]
    try:
        yt = _yt(api_key)
        for i in range(0, len(ids), 50):
            chunk = ids[i:i+50]
            r = yt.channels().list(part="snippet,statistics", id=",".join(chunk)).execute()
            with _conn() as c:
                for it in r.get("items", []):
                    c.execute("""
                        UPDATE channels SET subscriber_count=?,channel_title=?,
                        thumbnail_url=?,last_fetched_at=? WHERE channel_id=?
                    """, (
                        int(it["statistics"].get("subscriberCount",0)),
                        it["snippet"]["title"],
                        it["snippet"]["thumbnails"].get("default",{}).get("url",""),
                        _now(), it["id"]
                    ))
    except Exception:
        pass

# ── 영상 ──
def save_videos(channel_id: str, videos: list[dict]):
    with _conn() as c:
        for v in videos:
            c.execute("""
                INSERT OR REPLACE INTO videos
                (channel_id,video_id,title,view_count,like_count,comment_count,
                 published_at,thumbnail_url,fetched_at)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (channel_id, v["video_id"], v["title"],
                  v.get("view_count",0), v.get("like_count",0), v.get("comment_count",0),
                  v.get("published_at",""), v.get("thumbnail_url",""), _now()))
        c.execute("UPDATE channels SET last_fetched_at=? WHERE channel_id=?", (_now(), channel_id))

def get_group_videos(group: str, sort: str = "view_count", limit: int = 50) -> list[dict]:
    sort_col = {"조회수순":"view_count","최신순":"published_at",
                "좋아요순":"like_count","댓글순":"comment_count"}.get(sort, "view_count")
    chs = list_channels(group)
    ids = [c["channel_id"] for c in chs]
    if not ids: return []
    ph = ",".join("?"*len(ids))
    with _conn() as c:
        rows = c.execute(f"""
            SELECT v.*, ch.channel_title, ch.thumbnail_url AS ch_thumb
            FROM videos v JOIN channels ch ON v.channel_id=ch.channel_id
            WHERE v.channel_id IN ({ph})
            ORDER BY v.{sort_col} DESC LIMIT ?
        """, (*ids, limit)).fetchall()
    return [dict(r) for r in rows]

# ── 댓글 ──
def save_comments(video_id: str, comments: list[dict]):
    with _conn() as c:
        for cm in comments:
            h = hashlib.sha256(cm.get("author","").encode()).hexdigest()[:16]
            c.execute("""
                INSERT OR IGNORE INTO comments(video_id,author_hash,text,like_count,collected_at)
                VALUES(?,?,?,?,?)
            """, (video_id, h, cm.get("text",""), cm.get("like_count",0), _now()))

def get_comments(video_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM comments WHERE video_id=? ORDER BY like_count DESC", (video_id,)
        ).fetchall()
    return [dict(r) for r in rows]

# ── 썸네일 ──
def save_thumbnails(group: str, limit: int = 30):
    videos = get_group_videos(group, sort="view_count", limit=limit)
    chs = {c["channel_id"]: c for c in list_channels(group)}
    with _conn() as c:
        for v in videos:
            if not v.get("thumbnail_url"): continue
            ch = chs.get(v.get("channel_id",""), {})
            c.execute("""
                INSERT OR REPLACE INTO thumbnails
                (video_id,channel_id,channel_title,video_title,thumbnail_url,
                 published_at,view_count,collected_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (v["video_id"], v.get("channel_id",""),
                  v.get("channel_title", ch.get("channel_title","")),
                  v["title"], v["thumbnail_url"],
                  v.get("published_at",""), v.get("view_count",0), _now()))
    return len(videos)

def get_thumbnails(group: str, limit: int = 40) -> list[dict]:
    chs = list_channels(group)
    ids = [c["channel_id"] for c in chs]
    if not ids: return []
    ph = ",".join("?"*len(ids))
    with _conn() as c:
        rows = c.execute(f"""
            SELECT * FROM thumbnails WHERE channel_id IN ({ph})
            ORDER BY view_count DESC LIMIT ?
        """, (*ids, limit)).fetchall()
    return [dict(r) for r in rows]

def save_thumbnail_analysis(video_id: str, analysis: str, mj: str, dalle: str):
    with _conn() as c:
        c.execute("""
            UPDATE thumbnails SET ai_analysis=?,mj_prompt=?,dalle_prompt=?
            WHERE video_id=?
        """, (analysis, mj, dalle, video_id))

# ── 메모 ──
def list_notes() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM notes ORDER BY updated_at DESC").fetchall()]

def save_note(title: str, content: str, tags: str = "") -> int:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO notes(title,content,tags,created_at,updated_at) VALUES(?,?,?,?,?)",
            (title, content, tags, now, now))
    return cur.lastrowid

def update_note(nid: int, title: str, content: str, tags: str = ""):
    with _conn() as c:
        c.execute("UPDATE notes SET title=?,content=?,tags=?,updated_at=? WHERE id=?",
                  (title, content, tags, _now(), nid))

def delete_note(nid: int):
    with _conn() as c:
        c.execute("DELETE FROM notes WHERE id=?", (nid,))


# ─────────────────────────────────────────────────────────────────────────────
# 4. AI (Gemini)
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini(gemini_key: str, prompt: str) -> str:
    if not gemini_key:
        return "⚠️ Gemini API 키가 없습니다. 사이드바에서 설정하세요."
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        return model.generate_content(prompt).text
    except Exception as e:
        return f"AI 오류: {e}"


def ai_channel_deep(gemini_key: str, channel_title: str, channel_id: str) -> str:
    videos = get_group_videos.__wrapped__(channel_id) if False else []
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM videos WHERE channel_id=? ORDER BY view_count DESC LIMIT 10",
            (channel_id,)
        ).fetchall()
    videos = [dict(r) for r in rows]
    if not videos:
        return "영상 데이터가 없습니다. 먼저 영상을 수집하세요."
    titles = "\n".join(f"- {v['title']} (조회수 {fmt_num(v.get('view_count',0))})" for v in videos[:8])
    return call_gemini(gemini_key, f"""유튜브 채널 '{channel_title}'의 인기 영상 TOP:

{titles}

분석해 주세요:
## 1. 제목 패턴 공식
## 2. 콘텐츠 전략 (어떤 주제/포맷이 터지는지)
## 3. 시청자 니즈
## 4. 빈틈 — 내 채널의 기회
## 5. 즉시 적용할 벤치마킹 포인트""")


def ai_group_trend(gemini_key: str, group: str) -> str:
    videos = get_group_videos(group, sort="view_count", limit=20)
    if not videos:
        return "영상 데이터가 없습니다."
    lines = "\n".join(
        f"- [{v.get('channel_title','')}] {v['title']} (조회수 {fmt_num(v.get('view_count',0))})"
        for v in videos[:15])
    return call_gemini(gemini_key, f"""경쟁 채널 그룹 '{group}' 인기 영상:

{lines}

분석:
## 1. 공통 트렌드 키워드
## 2. 터지는 제목 구조 패턴
## 3. 지금 이 분야 콘텐츠 흐름
## 4. 즉시 기획 가능한 영상 아이디어 3가지""")


def ai_comments_sentiment(gemini_key: str, video_id: str) -> str:
    coms = get_comments(video_id)
    if not coms:
        return "수집된 댓글이 없습니다."
    texts = "\n".join(f"- {c['text']}" for c in coms[:50] if c.get("text"))
    return call_gemini(gemini_key, f"""유튜브 영상 시청자 댓글:

{texts}

분석:
## 1. 주요 감정 반응 (긍/부/중 비율)
## 2. 시청자가 원하는 것 (욕구·질문·요청)
## 3. 바이럴 요소
## 4. 후속 영상 아이디어""")


def ai_thumbnail_analysis(gemini_key: str, thumbnail_url: str,
                           video_title: str, channel_title: str) -> dict:
    result = call_gemini(gemini_key, f"""유튜브 썸네일 전문 분석가로서 분석해주세요.

영상 제목: {video_title}
채널명: {channel_title}
썸네일 URL: {thumbnail_url}

## 1. 썸네일 구성 분석
배경색/이미지, 텍스트 스타일, 인물 표정, 그래픽 요소, 레이아웃

## 2. 심리적 후킹 전략
어떤 감정 자극, 클릭 유도 요소

## 3. Midjourney 복제 프롬프트
```
[MIDJOURNEY PROMPT]
YouTube thumbnail, [배경], [인물/요소], [텍스트 스타일], [색감], bold Korean text "[제목]", high contrast, eye-catching --ar 16:9 --v 6
```

## 4. DALL-E 3 프롬프트
```
[DALLE PROMPT]
YouTube thumbnail: [구성 영어 설명], bold Korean text "[제목]", high contrast, sharp focus --ratio 16:9
```

## 5. 성공 공식 1줄 요약""")

    mj, dalle = "", ""
    if "[MIDJOURNEY PROMPT]" in result:
        try: mj = result.split("[MIDJOURNEY PROMPT]")[1].split("```")[0].strip()
        except Exception: pass
    if "[DALLE PROMPT]" in result:
        try: dalle = result.split("[DALLE PROMPT]")[1].split("```")[0].strip()
        except Exception: pass

    save_thumbnail_analysis(
        next((t["video_id"] for t in get_thumbnails.__wrapped__() if False), ""),
        result, mj, dalle
    ) if False else None

    with _conn() as c:
        c.execute("UPDATE thumbnails SET ai_analysis=?,mj_prompt=?,dalle_prompt=? WHERE thumbnail_url=?",
                  (result, mj, dalle, thumbnail_url))

    return {"analysis": result, "mj_prompt": mj, "dalle_prompt": dalle}


def ai_thumbnail_trend(gemini_key: str, group: str) -> str:
    ths = get_thumbnails(group, limit=30)
    if not ths:
        return "썸네일 데이터가 없습니다."
    ths_sorted = sorted(ths, key=lambda x: x.get("published_at",""))
    lines = "\n".join(
        f"- [{fmt_date(t.get('published_at',''))}] [{t.get('channel_title','')}] "
        f"{t.get('video_title','')} (조회수 {fmt_num(t.get('view_count',0))})"
        for t in ths_sorted[:25])
    return call_gemini(gemini_key, f"""경쟁 채널 그룹 '{group}' 영상 목록 (날짜순):

{lines}

썸네일/제목 트렌드 분석:
## 1. 시간에 따른 전략 변화
## 2. 조회수 높은 영상의 공통점
## 3. 지금 통하는 썸네일 공식 템플릿 3가지
## 4. 내 채널 추천 썸네일 전략""")


def ai_thumbnail_kit(gemini_key: str, channel_id: str, channel_title: str) -> str:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM videos WHERE channel_id=? ORDER BY view_count DESC LIMIT 10",
            (channel_id,)
        ).fetchall()
    videos = [dict(r) for r in rows]
    if not videos:
        return "영상 데이터가 없습니다."
    titles = "\n".join(f"- {v['title']} (조회수 {fmt_num(v.get('view_count',0))})"
                       for v in videos[:8])
    return call_gemini(gemini_key, f"""채널 '{channel_title}' 인기 영상:

{titles}

이 채널 스타일의 썸네일 제작 키트를 만들어 주세요:

## 채널 스타일 프로파일

## Midjourney 마스터 템플릿 3종
```
[TEMPLATE 1 - 충격/호기심형]
...--ar 16:9 --v 6

[TEMPLATE 2 - 정보/신뢰형]
...--ar 16:9

[TEMPLATE 3 - 감성/공감형]
...--ar 16:9
```

## 이 채널 특화 색상 팔레트

## 즉시 사용 가능한 제목+썸네일 세트 3개
(제목 / 썸네일 구성 / Midjourney 프롬프트)""")


# ─────────────────────────────────────────────────────────────────────────────
# 5. 사이드바
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style='font-size:1.25rem;font-weight:800;color:#e6edf3;margin-bottom:2px;'>
        🛰️ 경쟁 채널 레이더
    </div>
    <div style='font-size:0.78rem;color:#8b949e;margin-bottom:16px;'>
        경쟁 채널 인텔리전스 시스템
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.markdown("**🔑 API 키 설정**")
    st.caption(".env 파일에 저장하거나 아래에서 직접 입력")

    # API 키: env → session state → 입력값 순서
    if "yt_key" not in st.session_state:
        st.session_state.yt_key = os.getenv("YOUTUBE_API_KEY", "")
    if "gem_key" not in st.session_state:
        st.session_state.gem_key = os.getenv("GEMINI_API_KEY", "")

    yt_input = st.text_input(
        "YouTube API Key",
        value=st.session_state.yt_key,
        type="password",
        key="sb_yt",
        placeholder="AIza..."
    )
    gem_input = st.text_input(
        "Gemini API Key",
        value=st.session_state.gem_key,
        type="password",
        key="sb_gem",
        placeholder="AIza..."
    )
    if st.button("💾 키 저장", use_container_width=True):
        st.session_state.yt_key = yt_input
        st.session_state.gem_key = gem_input
        st.success("저장됨")

    st.divider()

    # API 상태
    yt_ok  = bool(st.session_state.yt_key)
    gem_ok = bool(st.session_state.gem_key)

    def dot(on): return "🟢" if on else "🔴"
    st.markdown(f"{dot(yt_ok)} YouTube API  \n{dot(gem_ok)} Gemini API")

    st.divider()
    st.markdown("**📂 DB 위치**")
    st.code(str(DB_PATH), language="text")
    st.caption("radar.db — SQLite, 자동 생성")

    # 전체 통계
    with _conn() as c:
        n_ch = c.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        n_v  = c.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        n_cm = c.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    st.divider()
    st.markdown(f"채널 **{n_ch}**개 · 영상 **{n_v}**개 · 댓글 **{n_cm}**개")


# 키 편의 변수
YT_KEY  = st.session_state.yt_key
GEM_KEY = st.session_state.gem_key


# ─────────────────────────────────────────────────────────────────────────────
# 6. 메인 헤더
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<div style='margin-bottom:1.2rem;'>
    <h1 style='font-size:1.7rem;font-weight:800;margin:0;'>
        🛰️ 경쟁 채널 인텔리전스 레이더
    </h1>
    <p style='font-size:0.88rem;color:#8b949e;margin:4px 0 0 0;'>
        경쟁 채널을 추적하고, 터지는 패턴을 역설계하는 Pro 분석 시스템
    </p>
</div>
""", unsafe_allow_html=True)

# 세션 상태 초기화
for k, v in [("sel_group", None), ("sel_channel", None),
             ("sort", "조회수순"), ("sel_vid_id", ""), ("sel_vid_title", "")]:
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# 7. 탭
# ─────────────────────────────────────────────────────────────────────────────

TAB_RADAR, TAB_TREND, TAB_COMMENT, TAB_AI, TAB_THUMB, TAB_CANVAS = st.tabs([
    "📡 경쟁 레이더",
    "⚡ 트렌드 포착",
    "💬 시청자 욕구 분석",
    "🎯 포지셔닝 전략",
    "🖼️ 썸네일 분석",
    "💡 아이디어 캔버스",
])


# ════════════════════════════════════════════════════════════════════════════
# 탭 1: 경쟁 레이더 (그룹·채널 관리 + 지형도)
# ════════════════════════════════════════════════════════════════════════════
with TAB_RADAR:
    left, right = st.columns([1, 2], gap="large")

    # ── 왼쪽: 관리 패널 ──────────────────────────────────────────────────────
    with left:
        st.subheader("그룹 / 채널 관리")
        groups = list_groups()
        g_opts = groups if groups else ["(그룹 없음)"]
        sel_g = st.selectbox("그룹 선택", g_opts, key="g_select")
        if groups:
            st.session_state.sel_group = sel_g

        new_g = st.text_input("새 그룹 이름", placeholder="예: 경제채널, 먹방채널 …", key="new_g")

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("＋ 추가", use_container_width=True):
                if new_g:
                    if add_group(new_g):
                        st.success(f"'{new_g}' 생성")
                        st.rerun()
                    else:
                        st.error("이미 있는 이름")
        with c2:
            if st.button("✏️ 이름변경", use_container_width=True):
                if groups and new_g:
                    rename_group(st.session_state.sel_group, new_g)
                    st.rerun()
        with c3:
            if st.button("🗑 삭제", use_container_width=True):
                if groups and st.session_state.sel_group:
                    delete_group(st.session_state.sel_group)
                    st.session_state.sel_group = None
                    st.rerun()

        st.divider()

        if st.session_state.sel_group:
            st.markdown(f"**채널 추가 → [{st.session_state.sel_group}]**")
            ch_url = st.text_input(
                "채널 링크 / @핸들 / UCxxxxxx",
                placeholder="https://youtube.com/@channel  또는  @handle",
                key="ch_url_input"
            )
            if st.button("＋ 채널 추가", type="primary", use_container_width=True):
                if not YT_KEY:
                    st.error("YouTube API 키가 필요합니다.")
                elif ch_url:
                    with st.spinner("채널 정보 조회 중…"):
                        cid = resolve_channel_id(YT_KEY, ch_url)
                        if cid:
                            info = fetch_channel_info(YT_KEY, cid)
                            upsert_channel(st.session_state.sel_group, info)
                            st.success(f"✅ {info.get('title', cid)} 추가됨")
                            st.rerun()
                        else:
                            st.error("채널을 찾을 수 없습니다.")

            if st.button("🔄 구독자 수 새로고침", use_container_width=True):
                if YT_KEY:
                    with st.spinner("API 조회 중…"):
                        refresh_all_subscribers(YT_KEY, st.session_state.sel_group)
                    st.success("완료")
                    st.rerun()
                else:
                    st.error("YouTube API 키가 필요합니다.")

            # 채널 목록
            chs = list_channels(st.session_state.sel_group)
            st.markdown(f"**채널 {len(chs)}개**")
            for ch in chs:
                cc1, cc2 = st.columns([5, 1])
                with cc1:
                    img_html = (f"<img src='{ch['thumbnail_url']}' width='26' "
                                f"style='border-radius:50%;vertical-align:middle;margin-right:6px;'>"
                                if ch.get("thumbnail_url") else "📺 ")
                    st.markdown(
                        f"{img_html}<b>{ch.get('channel_title', ch['channel_id'])}</b> "
                        f"<span style='color:#8b949e;font-size:0.76rem;'>구독자 {fmt_num(ch.get('subscriber_count',0))}</span>",
                        unsafe_allow_html=True
                    )
                with cc2:
                    if st.button("삭제", key=f"delch_{ch['channel_id']}"):
                        delete_channel(st.session_state.sel_group, ch["channel_id"])
                        st.rerun()

    # ── 오른쪽: 경쟁 지형도 ──────────────────────────────────────────────────
    with right:
        st.subheader("경쟁 지형도")
        if st.session_state.sel_group:
            chs = list_channels(st.session_state.sel_group)
            if chs:
                df_map = pd.DataFrame([{
                    "채널": ch.get("channel_title","")[:14],
                    "구독자": ch.get("subscriber_count", 0),
                } for ch in chs]).sort_values("구독자", ascending=True)
                st.bar_chart(df_map.set_index("채널")["구독자"], height=200)

                # 채널 카드
                for ch in chs:
                    is_sel = st.session_state.sel_channel == ch["channel_id"]
                    border = "#238636" if is_sel else "#30363d"
                    img_html = (f"<img src='{ch['thumbnail_url']}' width='36' "
                                f"style='border-radius:50%;flex-shrink:0;'>"
                                if ch.get("thumbnail_url") else "")
                    st.markdown(f"""
                    <div style='background:#161b22;border:2px solid {border};border-radius:9px;
                         padding:0.65rem 1rem;margin-bottom:0.4rem;
                         display:flex;align-items:center;gap:10px;'>
                        {img_html}
                        <div>
                            <div style='font-weight:600;font-size:0.92rem;'>{ch.get('channel_title','')}</div>
                            <div style='font-size:0.75rem;color:#8b949e;'>
                                구독자 {fmt_num(ch.get('subscriber_count',0))} &nbsp;·&nbsp;
                                추가 {fmt_date(ch.get('added_at',''))}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("▶ 선택", key=f"selch_{ch['channel_id']}"):
                        st.session_state.sel_channel = ch["channel_id"]
                        st.rerun()
            else:
                st.info("채널을 추가하면 지형도가 표시됩니다.")
        else:
            st.info("왼쪽에서 그룹을 선택하세요.")


# ════════════════════════════════════════════════════════════════════════════
# 탭 2: 트렌드 포착
# ════════════════════════════════════════════════════════════════════════════
with TAB_TREND:
    group = st.session_state.sel_group
    if not group:
        st.info("📡 경쟁 레이더 탭에서 그룹을 선택하세요.")
    else:
        st.subheader(f"⚡ {group} — 트렌드 포착")

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            if st.button("🚀 전체 채널 영상 수집 (API)", type="primary", use_container_width=True):
                if not YT_KEY:
                    st.error("YouTube API 키가 필요합니다.")
                else:
                    chs = list_channels(group)
                    prog = st.progress(0)
                    for i, ch in enumerate(chs):
                        with st.spinner(f"수집 중: {ch.get('channel_title','')}…"):
                            videos = fetch_channel_videos(YT_KEY, ch["channel_id"], 20)
                            save_videos(ch["channel_id"], videos)
                        prog.progress((i+1)/len(chs))
                    st.success(f"✅ {len(chs)}개 채널 수집 완료")
                    st.rerun()
        with col2:
            if st.button("⚡ 캐시 로드 (빠름)", use_container_width=True):
                st.rerun()
        with col3:
            max_v = st.selectbox("최대 영상 수", [20, 30, 50, 100], key="max_v_sel")

        st.divider()

        # TOP3
        top3 = get_group_videos(group, sort="view_count", limit=3)
        if top3:
            st.markdown("**🔥 TOP 3 인기 영상**")
            cols = st.columns(3)
            for i, (v, col) in enumerate(zip(top3, cols)):
                with col:
                    if v.get("thumbnail_url"):
                        st.image(v["thumbnail_url"], use_container_width=True)
                    st.markdown(f"""
                    <div class="top-card">
                        <div class="top-label">TOP {i+1}</div>
                        <div class="top-title">{v['title']}</div>
                        <div class="top-meta">
                            {v.get('channel_title','')} &nbsp;·&nbsp;
                            👁 {fmt_num(v.get('view_count',0))} &nbsp;·&nbsp;
                            💬 {v.get('comment_count',0)}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

        # 요약 통계
        all_v = get_group_videos(group, limit=100)
        if all_v:
            avg_views = sum(v.get("view_count",0) for v in all_v) / len(all_v)
            avg_coms  = sum(v.get("comment_count",0) for v in all_v) / len(all_v)
            top_ch = max(all_v, key=lambda x: x.get("view_count",0)).get("channel_title","")
            st.markdown(f"""
            <div style='background:#161b22;border:1px solid #30363d;border-radius:10px;
                 padding:1rem 1.4rem;margin:1rem 0;'>
                ✨ <b>수집 요약</b>  &nbsp;—&nbsp;
                영상 <b>{len(all_v)}</b>개 &nbsp;|&nbsp;
                평균 조회수 <b>{fmt_num(int(avg_views))}</b> &nbsp;|&nbsp;
                평균 댓글 <b>{int(avg_coms)}</b>개 &nbsp;|&nbsp;
                최다조회 채널 <b>{top_ch}</b>
            </div>
            """, unsafe_allow_html=True)

        st.divider()

        # 정렬 + 테이블
        sort_c = st.columns([1,1,1,1,3])
        for i, opt in enumerate(["조회수순","최신순","좋아요순","댓글순"]):
            with sort_c[i]:
                active = st.session_state.sort == opt
                if st.button(
                    ("▶ " if active else "") + opt,
                    key=f"sort_{opt}",
                    use_container_width=True,
                    type="primary" if active else "secondary"
                ):
                    st.session_state.sort = opt
                    st.rerun()

        with sort_c[4]:
            if st.button("📋 URL 복사용 출력", use_container_width=True):
                vids = get_group_videos(group, sort=st.session_state.sort, limit=int(max_v))
                urls = "\n".join(f"https://www.youtube.com/watch?v={v['video_id']}" for v in vids)
                st.code(urls, language="text")

        videos = get_group_videos(group, sort=st.session_state.sort, limit=int(max_v))
        if videos:
            df = pd.DataFrame([{
                "채널": v.get("channel_title",""),
                "영상 제목": v["title"],
                "조회수": v.get("view_count",0),
                "좋아요": v.get("like_count",0),
                "댓글": v.get("comment_count",0),
                "게시일": fmt_date(v.get("published_at","")),
                "_vid": v["video_id"],
            } for v in videos])

            st.dataframe(
                df.drop(columns=["_vid"]),
                use_container_width=True,
                height=420,
                column_config={
                    "조회수": st.column_config.NumberColumn(format="%d"),
                    "좋아요": st.column_config.NumberColumn(format="%d"),
                    "댓글":   st.column_config.NumberColumn(format="%d"),
                }
            )
            # 영상 선택 → 댓글 탭 연동
            sel_t = st.selectbox("댓글 수집할 영상 선택", df["영상 제목"].tolist(), key="trend_sel_v")
            if sel_t:
                row = df[df["영상 제목"]==sel_t].iloc[0]
                st.session_state.sel_vid_id    = row["_vid"]
                st.session_state.sel_vid_title = sel_t
        else:
            st.info("수집된 영상이 없습니다. '전체 채널 영상 수집' 버튼을 누르세요.")


# ════════════════════════════════════════════════════════════════════════════
# 탭 3: 시청자 욕구 분석
# ════════════════════════════════════════════════════════════════════════════
with TAB_COMMENT:
    st.subheader("💬 시청자 욕구 분석")
    st.caption("댓글 수집 → Gemini 감성·니즈 클러스터링")

    vid_id    = st.session_state.sel_vid_id
    vid_title = st.session_state.sel_vid_title or "선택된 영상 없음"
    st.info(f"선택된 영상: **{vid_title}**")

    manual_id = st.text_input("또는 video_id 직접 입력", placeholder="dQw4w9WgXcQ")
    target_id = manual_id if manual_id else vid_id

    col_a, col_b = st.columns([1, 1])
    with col_a:
        max_c = st.slider("수집할 댓글 수", 20, 100, 50)
    with col_b:
        if st.button("💬 댓글 수집", type="primary", use_container_width=True):
            if not YT_KEY:
                st.error("YouTube API 키가 필요합니다.")
            elif target_id:
                with st.spinner("댓글 수집 중…"):
                    coms = fetch_video_comments(YT_KEY, target_id, max_c)
                    save_comments(target_id, coms)
                st.success(f"✅ {len(coms)}개 수집")
                st.rerun()
            else:
                st.error("video_id를 입력하세요.")

    if target_id:
        coms = get_comments(target_id)
        if coms:
            st.markdown(f"**수집된 댓글 {len(coms)}개**")
            if st.button("🤖 AI 감성·욕구 분석", type="primary", use_container_width=True):
                with st.spinner("Gemini 분석 중…"):
                    res = ai_comments_sentiment(GEM_KEY, target_id)
                st.markdown("---")
                st.markdown(res)
                save_note(f"[댓글 분석] {vid_title[:30]}", res, "댓글,욕구분석")
                st.caption("💾 아이디어 캔버스에 저장됨")

            df_c = pd.DataFrame([{"댓글": c["text"], "좋아요": c.get("like_count",0)} for c in coms])
            st.dataframe(df_c, use_container_width=True, height=350)
        else:
            st.info("수집된 댓글이 없습니다.")


# ════════════════════════════════════════════════════════════════════════════
# 탭 4: 포지셔닝 전략
# ════════════════════════════════════════════════════════════════════════════
with TAB_AI:
    st.subheader("🎯 포지셔닝 전략")
    st.caption("경쟁 채널 패턴 역설계 → 내 채널의 빈틈과 기회 도출")

    group = st.session_state.sel_group
    if not group:
        st.info("📡 경쟁 레이더 탭에서 그룹을 선택하세요.")
    else:
        mode = st.radio("분석 유형", ["그룹 전체 트렌드", "개별 채널 심층 분석"], horizontal=True)

        if mode == "그룹 전체 트렌드":
            st.markdown(f"**{group}** 그룹 전체의 터지는 패턴을 AI가 역설계합니다.")
            if st.button("🚀 그룹 트렌드 분석 시작", type="primary", use_container_width=True):
                with st.spinner("Gemini 분석 중…"):
                    result = ai_group_trend(GEM_KEY, group)
                st.markdown("---")
                st.markdown(result)
                save_note(f"[트렌드] {group}", result, "AI분석,트렌드")
                st.caption("💾 아이디어 캔버스에 저장됨")
        else:
            chs = list_channels(group)
            if not chs:
                st.info("채널이 없습니다.")
            else:
                ch_map = {c.get("channel_title", c["channel_id"]): c["channel_id"] for c in chs}
                sel_name = st.selectbox("채널 선택", list(ch_map.keys()))
                sel_id   = ch_map[sel_name]
                if st.button(f"🔬 '{sel_name}' 심층 분석", type="primary", use_container_width=True):
                    with st.spinner("분석 중…"):
                        result = ai_channel_deep(GEM_KEY, sel_name, sel_id)
                    st.markdown("---")
                    st.markdown(result)
                    save_note(f"[채널분석] {sel_name}", result, "AI분석,채널")
                    st.caption("💾 아이디어 캔버스에 저장됨")


# ════════════════════════════════════════════════════════════════════════════
# 탭 5: 썸네일 분석
# ════════════════════════════════════════════════════════════════════════════
with TAB_THUMB:
    st.subheader("🖼️ 썸네일 분석")
    st.caption("썸네일 갤러리 · 변화 추이 AI 분석 · Midjourney/DALL-E 복제 프롬프트 자동 생성")

    group = st.session_state.sel_group
    if not group:
        st.info("📡 경쟁 레이더 탭에서 그룹을 선택하세요.")
    else:
        # ── 수집 & 추이 분석 ──
        ca, cb = st.columns([2, 1])
        with ca:
            st.markdown("**Step 1. 썸네일 수집**")
            th_n = st.slider("수집 개수", 10, 50, 30, key="th_n")
            if st.button("🖼️ 썸네일 수집", type="primary", use_container_width=True):
                n = save_thumbnails(group, th_n)
                st.success(f"✅ {n}개 수집")
                st.rerun()
        with cb:
            st.markdown("**추이 분석**")
            if st.button("📈 트렌드 AI 분석", use_container_width=True):
                with st.spinner("분석 중…"):
                    trend = ai_thumbnail_trend(GEM_KEY, group)
                st.session_state["th_trend"] = trend

        if st.session_state.get("th_trend"):
            with st.expander("📈 썸네일 트렌드 분석", expanded=True):
                st.markdown(st.session_state["th_trend"])
                if st.button("💾 저장", key="save_th_trend"):
                    save_note(f"[썸네일 트렌드] {group}",
                              st.session_state["th_trend"], "썸네일,트렌드")
                    st.success("저장됨")

        st.divider()

        # ── 썸네일 갤러리 ──
        st.markdown("**Step 2. 썸네일 갤러리 + 개별 AI 분석**")
        ths = get_thumbnails(group, limit=40)

        if ths:
            # 채널 필터
            ch_set = sorted(set(t.get("channel_title","") for t in ths if t.get("channel_title")))
            ch_f = st.selectbox("채널 필터", ["전체"] + ch_set, key="th_filter")
            filtered = ths if ch_f == "전체" else [t for t in ths if t.get("channel_title")==ch_f]

            # 4열 그리드
            COLS = 4
            for i in range(0, len(filtered), COLS):
                row = filtered[i:i+COLS]
                cols = st.columns(COLS)
                for th, col in zip(row, cols):
                    with col:
                        if th.get("thumbnail_url"):
                            st.image(th["thumbnail_url"], use_container_width=True)

                        title_disp = th.get("video_title","")
                        st.caption(f"**{title_disp[:32]}{'…' if len(title_disp)>32 else ''}**")
                        st.caption(
                            f"👁 {fmt_num(th.get('view_count',0))} · "
                            f"{th.get('channel_title','')} · "
                            f"{fmt_date(th.get('published_at',''))}"
                        )

                        # 이미 분석됐으면 프롬프트 표시
                        if th.get("mj_prompt"):
                            with st.expander("📋 MJ 프롬프트"):
                                st.code(th["mj_prompt"], language="text")
                            if th.get("dalle_prompt"):
                                with st.expander("🖼️ DALL-E 프롬프트"):
                                    st.code(th["dalle_prompt"], language="text")
                        else:
                            if st.button("🤖 AI 분석", key=f"th_ai_{th['video_id']}",
                                         use_container_width=True):
                                with st.spinner("분석 중…"):
                                    r = ai_thumbnail_analysis(
                                        GEM_KEY,
                                        th["thumbnail_url"],
                                        th.get("video_title",""),
                                        th.get("channel_title","")
                                    )
                                st.session_state[f"th_r_{th['video_id']}"] = r
                                st.rerun()

                        # 분석 결과 표시
                        r = st.session_state.get(f"th_r_{th['video_id']}")
                        if r:
                            with st.expander("분석 결과"):
                                st.markdown(r["analysis"])
                            st.code(r["mj_prompt"] or "(없음)", language="text")
                            if st.button("💾 저장", key=f"save_th_r_{th['video_id']}"):
                                save_note(
                                    f"[썸네일] {th.get('video_title','')[:30]}",
                                    f"**MJ:**\n```\n{r['mj_prompt']}\n```\n\n**DALL-E:**\n```\n{r['dalle_prompt']}\n```\n\n---\n{r['analysis']}",
                                    "썸네일,프롬프트"
                                )
                                st.success("저장됨")

            st.divider()

            # ── 채널 전체 키트 ──
            st.markdown("**Step 3. 채널 썸네일 공식 키트 (일괄 생성)**")
            chs_kit = list_channels(group)
            if chs_kit:
                kit_map = {c.get("channel_title",c["channel_id"]): c["channel_id"] for c in chs_kit}
                kit_sel = st.selectbox("채널 선택", list(kit_map.keys()), key="kit_sel")
                kit_id  = kit_map[kit_sel]
                if st.button(f"🎨 '{kit_sel}' 썸네일 키트 생성", type="primary", use_container_width=True):
                    with st.spinner("분석 중…"):
                        kit = ai_thumbnail_kit(GEM_KEY, kit_id, kit_sel)
                    st.markdown("### 🎨 썸네일 공식 키트")
                    st.markdown(kit)
                    save_note(f"[썸네일 키트] {kit_sel}", kit, "썸네일,키트")
                    st.caption("💾 아이디어 캔버스에 저장됨")
        else:
            st.info("수집된 썸네일이 없습니다. Step 1에서 먼저 수집하세요.")


# ════════════════════════════════════════════════════════════════════════════
# 탭 6: 아이디어 캔버스
# ════════════════════════════════════════════════════════════════════════════
with TAB_CANVAS:
    st.subheader("💡 아이디어 캔버스")
    st.caption("분석 결과·기획 아이디어·제목 공식 저장소. AI 분석 결과는 자동 저장됩니다.")

    with st.expander("＋ 새 메모 작성", expanded=False):
        nt = st.text_input("제목", key="new_nt")
        nc = st.text_area("내용", key="new_nc", height=140)
        ntg = st.text_input("태그", placeholder="트렌드,썸네일,아이디어", key="new_ntg")
        if st.button("💾 저장", key="save_nt"):
            if nt:
                save_note(nt, nc, ntg)
                st.success("저장됨")
                st.rerun()

    notes = list_notes()
    if not notes:
        st.info("저장된 메모가 없습니다.")
    else:
        # 태그 필터
        all_tags = sorted(set(
            t.strip()
            for n in notes if n.get("tags")
            for t in n["tags"].split(",") if t.strip()
        ))
        tag_f = st.multiselect("태그 필터", all_tags, key="tag_filter")
        shown = [n for n in notes
                 if not tag_f or any(t in (n.get("tags","").split(",")) for t in tag_f)]

        for note in shown:
            with st.expander(
                f"📌 {note['title']}  —  {fmt_date(note['updated_at'])}",
                expanded=False
            ):
                st.markdown(note["content"])
                if note.get("tags"):
                    tags_html = " ".join(
                        f"<span class='badge'>{t.strip()}</span>"
                        for t in note["tags"].split(",") if t.strip()
                    )
                    st.markdown(tags_html, unsafe_allow_html=True)

                nc_edit = st.text_area("편집", value=note["content"],
                                        key=f"edit_{note['id']}", height=100)
                ec1, ec2 = st.columns(2)
                with ec1:
                    if st.button("💾 업데이트", key=f"upd_{note['id']}"):
                        update_note(note["id"], note["title"], nc_edit, note.get("tags",""))
                        st.rerun()
                with ec2:
                    if st.button("🗑 삭제", key=f"del_{note['id']}"):
                        delete_note(note["id"])
                        st.rerun()
