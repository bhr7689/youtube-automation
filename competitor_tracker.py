"""경쟁 채널 인텔리전스 레이더 — competitor_tracker.py

경쟁 채널 그룹 관리 + 영상 트렌드 분석 + AI 포지셔닝 전략 + 댓글 욕구 분석.
YouTube Data API v3 + Gemini. SQLite 영구 저장 + 24h 캐시로 할당량 절약.

사용:
    from competitor_tracker import CompetitorTracker
    tracker = CompetitorTracker(api_key="...", db_path="ktrot.db")

Streamlit 탭:
    from competitor_tracker import render_tab
    render_tab()
"""

from __future__ import annotations

import json
import sqlite3
import time
import hashlib
import io
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── SQLite 스키마 ───────────────────────────────────────────────────────────

COMPETITOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS competitor_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competitor_channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name      TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    channel_title   TEXT,
    thumbnail_url   TEXT,
    subscriber_count INTEGER DEFAULT 0,
    added_at        TEXT NOT NULL,
    last_fetched_at TEXT,
    UNIQUE(group_name, channel_id)
);

CREATE TABLE IF NOT EXISTS competitor_videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      TEXT NOT NULL,
    video_id        TEXT NOT NULL,
    title           TEXT,
    view_count      INTEGER DEFAULT 0,
    like_count      INTEGER DEFAULT 0,
    comment_count   INTEGER DEFAULT 0,
    published_at    TEXT,
    thumbnail_url   TEXT,
    fetched_at      TEXT NOT NULL,
    UNIQUE(channel_id, video_id)
);

CREATE TABLE IF NOT EXISTS competitor_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    author_hash TEXT,
    text        TEXT,
    like_count  INTEGER DEFAULT 0,
    collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competitor_ai_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT NOT NULL,
    report_type  TEXT NOT NULL,
    content      TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competitor_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    content    TEXT,
    tags       TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competitor_thumbnails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT NOT NULL,
    channel_id      TEXT,
    channel_title   TEXT,
    video_title     TEXT,
    thumbnail_url   TEXT,
    published_at    TEXT,
    view_count      INTEGER DEFAULT 0,
    ai_description  TEXT,
    ai_prompt       TEXT,
    collected_at    TEXT NOT NULL,
    UNIQUE(video_id)
);
"""

DB_PATH = Path(__file__).parent / "ktrot.db"


# ── 핵심 클래스 ──────────────────────────────────────────────────────────────

class CompetitorTracker:
    """경쟁 채널 추적 + 분석 엔진."""

    CACHE_TTL_HOURS = 24  # API 할당량 절약 캐시

    def __init__(self, api_key: str | None = None, gemini_key: str | None = None,
                 db_path: Path | str = DB_PATH):
        self.api_key = api_key
        self.gemini_key = gemini_key
        self.db_path = Path(db_path)
        self._init_db()

    # ── DB 초기화 ─────────────────────────────────────────────────────────

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(COMPETITOR_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 그룹 관리 ─────────────────────────────────────────────────────────

    def list_groups(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT name FROM competitor_groups ORDER BY id").fetchall()
        return [r["name"] for r in rows]

    def add_group(self, name: str) -> bool:
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO competitor_groups(name, created_at) VALUES(?,?)",
                    (name, _now())
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def rename_group(self, old: str, new: str):
        with self._conn() as conn:
            conn.execute("UPDATE competitor_groups SET name=? WHERE name=?", (new, old))
            conn.execute("UPDATE competitor_channels SET group_name=? WHERE group_name=?", (new, old))

    def delete_group(self, name: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM competitor_channels WHERE group_name=?", (name,))
            conn.execute("DELETE FROM competitor_groups WHERE name=?", (name,))

    # ── 채널 관리 ─────────────────────────────────────────────────────────

    def list_channels(self, group_name: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM competitor_channels WHERE group_name=? ORDER BY subscriber_count DESC",
                (group_name,)
            ).fetchall()
        return [dict(r) for r in rows]

    def add_channel_by_id(self, group_name: str, channel_id: str) -> dict:
        """채널 ID로 추가. API로 기본 정보 조회."""
        info = self._fetch_channel_info(channel_id)
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO competitor_channels
                (group_name, channel_id, channel_title, thumbnail_url, subscriber_count, added_at)
                VALUES(?,?,?,?,?,?)
            """, (
                group_name, channel_id,
                info.get("title", channel_id),
                info.get("thumbnail_url", ""),
                info.get("subscriber_count", 0),
                _now()
            ))
        return info

    def add_channel_by_url(self, group_name: str, url_or_handle: str) -> dict:
        """URL/핸들/@handle 형태에서 채널 ID 추출 후 추가."""
        channel_id = self._resolve_channel_id(url_or_handle)
        if not channel_id:
            raise ValueError(f"채널 ID를 찾을 수 없습니다: {url_or_handle}")
        return self.add_channel_by_id(group_name, channel_id)

    def delete_channel(self, group_name: str, channel_id: str):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM competitor_channels WHERE group_name=? AND channel_id=?",
                (group_name, channel_id)
            )

    def refresh_subscriber_counts(self, group_name: str):
        """구독자 수 새로고침 (API 호출)."""
        channels = self.list_channels(group_name)
        ids = [c["channel_id"] for c in channels]
        infos = self._fetch_channels_batch(ids)
        with self._conn() as conn:
            for ch_id, info in infos.items():
                conn.execute("""
                    UPDATE competitor_channels
                    SET subscriber_count=?, channel_title=?, thumbnail_url=?, last_fetched_at=?
                    WHERE channel_id=?
                """, (
                    info.get("subscriber_count", 0),
                    info.get("title", ""),
                    info.get("thumbnail_url", ""),
                    _now(), ch_id
                ))

    # ── 영상 분석 ─────────────────────────────────────────────────────────

    def fetch_videos(self, channel_id: str, max_results: int = 20,
                     force: bool = False) -> list[dict]:
        """채널 최근 영상 수집. 24h 캐시 적용."""
        if not force and self._is_fresh(channel_id):
            return self._cached_videos(channel_id, max_results)

        videos = self._api_fetch_videos(channel_id, max_results)
        with self._conn() as conn:
            for v in videos:
                conn.execute("""
                    INSERT OR REPLACE INTO competitor_videos
                    (channel_id, video_id, title, view_count, like_count,
                     comment_count, published_at, thumbnail_url, fetched_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                """, (
                    channel_id, v["video_id"], v["title"],
                    v.get("view_count", 0), v.get("like_count", 0),
                    v.get("comment_count", 0), v.get("published_at", ""),
                    v.get("thumbnail_url", ""), _now()
                ))
            conn.execute("""
                UPDATE competitor_channels SET last_fetched_at=? WHERE channel_id=?
            """, (_now(), channel_id))
        return videos

    def fetch_group_videos(self, group_name: str, max_per_channel: int = 20,
                           force: bool = False) -> list[dict]:
        """그룹 전체 채널 영상 합산."""
        channels = self.list_channels(group_name)
        all_videos = []
        for ch in channels:
            try:
                vids = self.fetch_videos(ch["channel_id"], max_per_channel, force)
                for v in vids:
                    v["channel_title"] = ch.get("channel_title", ch["channel_id"])
                    v["channel_id"] = ch["channel_id"]
                all_videos.extend(vids)
            except Exception:
                pass
        return all_videos

    def get_top_videos(self, group_name: str, sort_by: str = "view_count",
                       limit: int = 20) -> list[dict]:
        """DB에서 정렬된 영상 목록 반환."""
        sort_col = {
            "조회수순": "view_count",
            "최신순": "published_at",
            "좋아요순": "like_count",
            "댓글순": "comment_count",
        }.get(sort_by, sort_by)

        channels = self.list_channels(group_name)
        ids = [c["channel_id"] for c in channels]
        if not ids:
            return []

        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT cv.*, cc.channel_title, cc.thumbnail_url as ch_thumbnail
                FROM competitor_videos cv
                JOIN competitor_channels cc ON cv.channel_id = cc.channel_id
                WHERE cv.channel_id IN ({placeholders})
                ORDER BY cv.{sort_col} DESC
                LIMIT ?
            """, (*ids, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_top3_report(self, group_name: str) -> list[dict]:
        return self.get_top_videos(group_name, sort_by="view_count", limit=3)

    # ── 댓글 수집 ─────────────────────────────────────────────────────────

    def collect_comments(self, video_id: str, max_comments: int = 100) -> list[dict]:
        comments = self._api_fetch_comments(video_id, max_comments)
        with self._conn() as conn:
            for c in comments:
                author_hash = hashlib.sha256(c.get("author", "").encode()).hexdigest()[:16]
                conn.execute("""
                    INSERT OR IGNORE INTO competitor_comments
                    (video_id, author_hash, text, like_count, collected_at)
                    VALUES(?,?,?,?,?)
                """, (video_id, author_hash, c.get("text", ""),
                      c.get("like_count", 0), _now()))
        return comments

    def get_comments(self, video_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM competitor_comments WHERE video_id=? ORDER BY like_count DESC",
                (video_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── AI 분석 ───────────────────────────────────────────────────────────

    def ai_analyze_channel(self, channel_id: str, channel_title: str = "") -> str:
        """Gemini로 채널 전략 분석."""
        videos = self._cached_videos(channel_id, 20)
        if not videos:
            return "분석할 영상 데이터가 없습니다. 먼저 영상을 수집하세요."

        top5 = sorted(videos, key=lambda x: x.get("view_count", 0), reverse=True)[:5]
        titles = "\n".join(f"- {v['title']} (조회수 {_fmt_num(v.get('view_count',0))})" for v in top5)

        prompt = f"""다음은 유튜브 채널 '{channel_title}' 의 최근 인기 영상 TOP5입니다:

{titles}

다음을 분석해 주세요:
1. **제목 패턴 공식** — 자주 쓰는 구조, 키워드
2. **콘텐츠 전략** — 어떤 주제/포맷이 터지는지
3. **시청자 니즈** — 이 채널 시청자가 원하는 것
4. **빈틈 (나의 기회)** — 이 채널이 다루지 않는 영역
5. **벤치마킹 포인트** — 내 채널에 바로 적용할 수 있는 것

간결하고 실전적으로 답하세요."""

        return self._call_gemini(prompt)

    def ai_analyze_group_trend(self, group_name: str) -> str:
        """그룹 전체 트렌드 요약 분석."""
        videos = self.get_top_videos(group_name, sort_by="view_count", limit=30)
        if not videos:
            return "영상 데이터가 없습니다."

        titles = "\n".join(
            f"- [{v.get('channel_title','')}] {v['title']} (조회수 {_fmt_num(v.get('view_count',0))})"
            for v in videos[:15]
        )

        prompt = f"""다음은 경쟁 채널 그룹 '{group_name}'의 최근 인기 영상 목록입니다:

{titles}

분석해 주세요:
1. **공통 트렌드 키워드** — 자주 등장하는 단어/주제
2. **터지는 제목 구조** — 숫자, 질문, 감정어 패턴
3. **콘텐츠 흐름** — 요즘 이 분야에서 뭐가 뜨는지
4. **즉시 기획 가능한 영상 아이디어 3가지**

실전 적용 가능하게 간결히."""

        return self._call_gemini(prompt)

    # ── 썸네일 분석 ───────────────────────────────────────────────────────

    def collect_thumbnails(self, group_name: str, limit: int = 30) -> list[dict]:
        """그룹의 상위 영상 썸네일 수집 (DB 저장)."""
        videos = self.get_top_videos(group_name, sort_by="view_count", limit=limit)
        channels = {c["channel_id"]: c for c in self.list_channels(group_name)}
        saved = []
        with self._conn() as conn:
            for v in videos:
                if not v.get("thumbnail_url"):
                    continue
                ch = channels.get(v.get("channel_id", ""), {})
                conn.execute("""
                    INSERT OR REPLACE INTO competitor_thumbnails
                    (video_id, channel_id, channel_title, video_title, thumbnail_url,
                     published_at, view_count, collected_at)
                    VALUES(?,?,?,?,?,?,?,?)
                """, (
                    v["video_id"], v.get("channel_id", ""),
                    v.get("channel_title", ch.get("channel_title", "")),
                    v["title"], v["thumbnail_url"],
                    v.get("published_at", ""),
                    v.get("view_count", 0), _now()
                ))
                saved.append(v)
        return saved

    def get_thumbnails(self, group_name: str = None, channel_id: str = None,
                       limit: int = 30) -> list[dict]:
        """저장된 썸네일 목록 반환."""
        with self._conn() as conn:
            if channel_id:
                rows = conn.execute("""
                    SELECT * FROM competitor_thumbnails WHERE channel_id=?
                    ORDER BY view_count DESC LIMIT ?
                """, (channel_id, limit)).fetchall()
            elif group_name:
                channels = self.list_channels(group_name)
                ids = [c["channel_id"] for c in channels]
                if not ids:
                    return []
                ph = ",".join("?" * len(ids))
                rows = conn.execute(f"""
                    SELECT * FROM competitor_thumbnails WHERE channel_id IN ({ph})
                    ORDER BY view_count DESC LIMIT ?
                """, (*ids, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM competitor_thumbnails ORDER BY view_count DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def ai_analyze_thumbnail(self, thumbnail_url: str, video_title: str = "",
                              channel_title: str = "") -> dict:
        """썸네일 1장 분석 → 설명 + Midjourney/DALL-E 스타일 복제 프롬프트 반환."""
        prompt = f"""당신은 유튜브 썸네일 전문 디자이너입니다.
아래 유튜브 영상의 썸네일을 분석해 주세요.

영상 제목: {video_title}
채널명: {channel_title}
썸네일 URL: {thumbnail_url}

다음 항목을 분석하세요:

## 1. 썸네일 구성 분석
- 배경색/배경 이미지
- 텍스트 (폰트 스타일, 크기, 색상, 위치)
- 인물/캐릭터 유무 및 표정
- 그래픽 요소 (아이콘, 화살표, 테두리 등)
- 전체 레이아웃 구조

## 2. 심리적 후킹 전략
- 어떤 감정을 자극하는가 (호기심/공포/희망/충격)
- 클릭을 유도하는 핵심 요소

## 3. 복제 가능한 Midjourney 프롬프트
아래 형식으로 작성:
```
[MIDJOURNEY PROMPT]
YouTube thumbnail, [배경 설명], [인물/요소 설명], [텍스트 스타일],
[색감/분위기], bold Korean text "[제목 예시]", high contrast,
eye-catching, professional thumbnail design --ar 16:9 --v 6
```

## 4. DALL-E 3 프롬프트
```
[DALL-E PROMPT]
A YouTube thumbnail image: [전체 구성을 영어로 상세 설명],
bold Korean text overlay "[제목]", high contrast colors,
sharp focus, thumbnail composition --ratio 16:9
```

## 5. 디자인 핵심 공식 (1줄 요약)
이 썸네일의 성공 공식을 한 줄로."""

        result = self._call_gemini(prompt)

        # 프롬프트 파트 추출
        mid_prompt = ""
        dalle_prompt = ""
        if "[MIDJOURNEY PROMPT]" in result:
            try:
                mid_prompt = result.split("[MIDJOURNEY PROMPT]")[1].split("```")[0].strip()
            except Exception:
                pass
        if "[DALL-E PROMPT]" in result:
            try:
                dalle_prompt = result.split("[DALL-E PROMPT]")[1].split("```")[0].strip()
            except Exception:
                pass

        # DB 저장
        with self._conn() as conn:
            conn.execute("""
                UPDATE competitor_thumbnails
                SET ai_description=?, ai_prompt=?
                WHERE thumbnail_url=?
            """, (result, mid_prompt, thumbnail_url))

        return {
            "analysis": result,
            "midjourney_prompt": mid_prompt,
            "dalle_prompt": dalle_prompt,
        }

    def ai_analyze_thumbnail_trend(self, group_name: str) -> str:
        """채널 그룹의 썸네일 변화 추이 + 패턴 분석."""
        thumbnails = self.get_thumbnails(group_name=group_name, limit=30)
        if not thumbnails:
            return "썸네일 데이터가 없습니다. 먼저 썸네일을 수집하세요."

        # 날짜순 정렬
        sorted_ths = sorted(thumbnails, key=lambda x: x.get("published_at", ""))

        # AI에게 제목+날짜 정보로 추세 분석
        entries = "\n".join(
            f"- [{_fmt_date(t.get('published_at',''))}] [{t.get('channel_title','')}] "
            f"{t.get('video_title','')} (조회수: {_fmt_num(t.get('view_count',0))})"
            for t in sorted_ths[:25]
        )

        prompt = f"""다음은 경쟁 채널 그룹 '{group_name}'의 영상 목록입니다 (날짜순):

{entries}

썸네일 트렌드를 분석해 주세요:

## 1. 시간에 따른 썸네일 전략 변화
- 최근으로 올수록 어떤 요소가 변했는가
- 제목 구조 변화 트렌드

## 2. 조회수 높은 영상의 제목/썸네일 공통점
- 어떤 키워드, 패턴이 조회수와 상관관계가 있는가

## 3. 지금 이 시장에서 통하는 썸네일 공식
- 즉시 적용 가능한 템플릿 3가지

## 4. 내 채널에 추천하는 다음 썸네일 전략"""

        return self._call_gemini(prompt)

    def ai_create_thumbnail_prompt_batch(self, channel_id: str,
                                          channel_title: str = "") -> str:
        """채널의 인기 영상들을 분석해 해당 채널 스타일의 썸네일 프롬프트 공식 생성."""
        videos = self._cached_videos(channel_id, 10)
        if not videos:
            return "영상 데이터가 없습니다."

        titles = "\n".join(f"- {v['title']} (조회수 {_fmt_num(v.get('view_count',0))})"
                           for v in videos[:8])

        prompt = f"""유튜브 채널 '{channel_title}'의 인기 영상 제목들:

{titles}

이 채널의 썸네일 스타일을 추론하여 **범용 썸네일 제작 프롬프트 키트**를 만들어 주세요:

## 채널 스타일 프로파일
(제목 패턴으로 추론한 채널 특성, 타겟 시청자, 콘텐츠 분위기)

## 썸네일 마스터 템플릿 (Midjourney)
```
[TEMPLATE 1 - 충격/호기심 유발형]
YouTube thumbnail, [구체적 배경], shocked/surprised Korean person,
bold Korean text "[제목 공식]", bright contrast, high impact --ar 16:9

[TEMPLATE 2 - 정보/신뢰형]
YouTube thumbnail, clean background, professional Korean presenter,
data visualization elements, bold Korean title "[제목 공식]", --ar 16:9

[TEMPLATE 3 - 감성/공감형]
YouTube thumbnail, emotional Korean scene, warm tones,
relatable situation, large bold Korean text --ar 16:9
```

## 이 채널 특화 색상 팔레트
(추천 배경색, 텍스트색, 포인트색)

## 즉시 사용 가능한 제목+썸네일 세트 3개
각 세트: 제목 / 썸네일 구성 / Midjourney 프롬프트"""

        return self._call_gemini(prompt)

    def ai_analyze_comments_sentiment(self, video_id: str) -> str:
        """댓글 감성 + 시청자 욕구 분석."""
        comments = self.get_comments(video_id)
        if not comments:
            return "수집된 댓글이 없습니다."

        sample = comments[:50]
        texts = "\n".join(f"- {c['text']}" for c in sample if c.get("text"))

        prompt = f"""다음은 유튜브 영상의 시청자 댓글입니다:

{texts}

분석해 주세요:
1. **주요 감정 반응** (긍정/부정/중립 비율 + 대표 감정)
2. **시청자가 원하는 것** (댓글에서 드러나는 욕구, 질문, 요청)
3. **바이럴 요소** (왜 이 댓글들이 공감을 받았는가)
4. **후속 영상 아이디어** (댓글 반응 기반)"""

        return self._call_gemini(prompt)

    # ── 메모 ─────────────────────────────────────────────────────────────

    def save_note(self, title: str, content: str, tags: str = "") -> int:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO competitor_notes(title, content, tags, created_at, updated_at) VALUES(?,?,?,?,?)",
                (title, content, tags, now, now)
            )
        return cur.lastrowid

    def update_note(self, note_id: int, title: str, content: str, tags: str = ""):
        with self._conn() as conn:
            conn.execute(
                "UPDATE competitor_notes SET title=?, content=?, tags=?, updated_at=? WHERE id=?",
                (title, content, tags, _now(), note_id)
            )

    def delete_note(self, note_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM competitor_notes WHERE id=?", (note_id,))

    def list_notes(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM competitor_notes ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 통계 헬퍼 ────────────────────────────────────────────────────────

    def get_channel_stats(self, group_name: str) -> dict:
        """그룹 채널들의 요약 통계."""
        videos = self.get_top_videos(group_name, sort_by="view_count", limit=100)
        if not videos:
            return {}
        total = len(videos)
        avg_views = sum(v.get("view_count", 0) for v in videos) / total if total else 0
        avg_likes = sum(v.get("like_count", 0) for v in videos) / total if total else 0
        avg_comments = sum(v.get("comment_count", 0) for v in videos) / total if total else 0
        return {
            "total_videos": total,
            "avg_views": avg_views,
            "avg_likes": avg_likes,
            "avg_comments": avg_comments,
            "top_channel": max(videos, key=lambda x: x.get("view_count", 0)).get("channel_title", ""),
        }

    def export_urls(self, group_name: str, limit: int = 20, sort_by: str = "view_count") -> str:
        """영상 URL 목록 반환 (복사용)."""
        videos = self.get_top_videos(group_name, sort_by=sort_by, limit=limit)
        urls = [f"https://www.youtube.com/watch?v={v['video_id']}" for v in videos]
        return "\n".join(urls)

    # ── 내부 API 호출 ─────────────────────────────────────────────────────

    def _build_youtube(self):
        if not self.api_key:
            raise ValueError("YouTube API 키가 없습니다.")
        try:
            from googleapiclient.discovery import build
            return build("youtube", "v3", developerKey=self.api_key)
        except ImportError:
            raise ImportError("google-api-python-client 가 설치되어 있지 않습니다.")

    def _fetch_channel_info(self, channel_id: str) -> dict:
        try:
            yt = self._build_youtube()
            resp = yt.channels().list(
                part="snippet,statistics",
                id=channel_id
            ).execute()
            items = resp.get("items", [])
            if not items:
                return {"title": channel_id}
            item = items[0]
            return {
                "title": item["snippet"]["title"],
                "thumbnail_url": item["snippet"]["thumbnails"].get("default", {}).get("url", ""),
                "subscriber_count": int(item["statistics"].get("subscriberCount", 0)),
                "channel_id": channel_id,
            }
        except Exception:
            return {"title": channel_id, "channel_id": channel_id}

    def _fetch_channels_batch(self, channel_ids: list[str]) -> dict[str, dict]:
        if not channel_ids:
            return {}
        result = {}
        try:
            yt = self._build_youtube()
            for i in range(0, len(channel_ids), 50):
                chunk = channel_ids[i:i+50]
                resp = yt.channels().list(
                    part="snippet,statistics",
                    id=",".join(chunk)
                ).execute()
                for item in resp.get("items", []):
                    cid = item["id"]
                    result[cid] = {
                        "title": item["snippet"]["title"],
                        "thumbnail_url": item["snippet"]["thumbnails"].get("default", {}).get("url", ""),
                        "subscriber_count": int(item["statistics"].get("subscriberCount", 0)),
                    }
        except Exception:
            pass
        return result

    def _resolve_channel_id(self, url_or_handle: str) -> str | None:
        """URL/@handle/채널명 → channel_id"""
        s = url_or_handle.strip()
        # 이미 channel_id 형태
        if s.startswith("UC") and len(s) == 24:
            return s
        # URL에서 channel_id 추출
        if "youtube.com/channel/" in s:
            part = s.split("youtube.com/channel/")[-1].split("/")[0].split("?")[0]
            return part
        # @handle 검색
        handle = s.lstrip("@").split("/")[0]
        try:
            yt = self._build_youtube()
            resp = yt.channels().list(part="id", forHandle=f"@{handle}").execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]
            # 이름 검색 폴백
            resp2 = yt.search().list(part="snippet", q=handle, type="channel", maxResults=1).execute()
            items2 = resp2.get("items", [])
            if items2:
                return items2[0]["snippet"]["channelId"]
        except Exception:
            pass
        return None

    def _api_fetch_videos(self, channel_id: str, max_results: int = 20) -> list[dict]:
        try:
            yt = self._build_youtube()
            # 최근 영상 검색
            resp = yt.search().list(
                part="snippet",
                channelId=channel_id,
                order="date",
                type="video",
                maxResults=min(max_results, 50)
            ).execute()
            video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]
            if not video_ids:
                return []
            # 통계 조회
            stats_resp = yt.videos().list(
                part="snippet,statistics",
                id=",".join(video_ids)
            ).execute()
            videos = []
            for item in stats_resp.get("items", []):
                stats = item.get("statistics", {})
                videos.append({
                    "video_id": item["id"],
                    "title": item["snippet"]["title"],
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "published_at": item["snippet"]["publishedAt"],
                    "thumbnail_url": item["snippet"]["thumbnails"].get("medium", {}).get("url", ""),
                })
            return videos
        except Exception:
            return []

    def _api_fetch_comments(self, video_id: str, max_comments: int = 100) -> list[dict]:
        try:
            yt = self._build_youtube()
            resp = yt.commentThreads().list(
                part="snippet",
                videoId=video_id,
                order="relevance",
                maxResults=min(max_comments, 100)
            ).execute()
            comments = []
            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "text": top.get("textDisplay", ""),
                    "author": top.get("authorDisplayName", ""),
                    "like_count": int(top.get("likeCount", 0)),
                    "published_at": top.get("publishedAt", ""),
                })
            return comments
        except Exception:
            return []

    def _call_gemini(self, prompt: str) -> str:
        if not self.gemini_key:
            return "Gemini API 키가 없습니다. .env 파일에 GEMINI_API_KEY를 설정하세요."
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            return f"AI 분석 오류: {e}"

    def _is_fresh(self, channel_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_fetched_at FROM competitor_channels WHERE channel_id=?",
                (channel_id,)
            ).fetchone()
        if not row or not row["last_fetched_at"]:
            return False
        try:
            last = datetime.fromisoformat(row["last_fetched_at"].replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - last) < timedelta(hours=self.CACHE_TTL_HOURS)
        except Exception:
            return False

    def _cached_videos(self, channel_id: str, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM competitor_videos WHERE channel_id=? ORDER BY view_count DESC LIMIT ?",
                (channel_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]


# ── 유틸리티 ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _fmt_num(n: int) -> str:
    if n >= 100_000_000:
        return f"{n/100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n/10_000:.1f}만"
    if n >= 1_000:
        return f"{n/1_000:.1f}천"
    return str(n)

def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y. %m. %d.")
    except Exception:
        return iso[:10]


# ── Streamlit 탭 렌더링 ───────────────────────────────────────────────────────

def render_tab():
    """app.py에서 import해서 호출."""
    import streamlit as st
    import os

    st.markdown("""
    <style>
    .radar-header { font-size:1.4rem; font-weight:700; margin-bottom:0.2rem; }
    .radar-sub    { font-size:0.85rem; color:#888; margin-bottom:1rem; }
    .top-card {
        background:#1e2130; border-radius:10px; padding:1rem 1.2rem;
        border:1px solid #2a2f45; margin-bottom:0.6rem;
    }
    .top-label { font-size:0.7rem; color:#6ee7b7; font-weight:700; letter-spacing:1px; }
    .top-title { font-size:0.95rem; font-weight:600; margin:0.3rem 0; }
    .top-meta  { font-size:0.78rem; color:#aaa; }
    .stat-pill {
        display:inline-block; background:#2a3050; border-radius:20px;
        padding:0.15rem 0.6rem; font-size:0.75rem; margin-right:0.3rem; color:#c9d1f0;
    }
    .ch-card {
        background:#181c2e; border-radius:8px; padding:0.7rem 1rem;
        border:1px solid #252a40; margin-bottom:0.4rem; cursor:pointer;
    }
    .ch-card:hover { border-color:#6ee7b7; }
    .ch-title { font-weight:600; font-size:0.9rem; }
    .ch-sub   { font-size:0.75rem; color:#888; }
    </style>
    """, unsafe_allow_html=True)

    # API 키 로드
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    # 세션 상태 초기화
    if "ct_selected_group" not in st.session_state:
        st.session_state.ct_selected_group = None
    if "ct_selected_channel" not in st.session_state:
        st.session_state.ct_selected_channel = None
    if "ct_sort" not in st.session_state:
        st.session_state.ct_sort = "조회수순"

    tracker = CompetitorTracker(api_key=api_key, gemini_key=gemini_key)

    # ── 헤더 ─────────────────────────────────────────────────────────────
    col_title, col_status = st.columns([3, 1])
    with col_title:
        st.markdown('<div class="radar-header">🛰️ 경쟁 채널 인텔리전스 레이더</div>', unsafe_allow_html=True)
        st.markdown('<div class="radar-sub">경쟁 채널을 추적하고, 터지는 패턴을 역설계하는 Pro 분석 시스템</div>', unsafe_allow_html=True)
    with col_status:
        cache_status = "✅ API 연결됨" if api_key else "⚠️ API 키 없음"
        st.caption(cache_status)
        st.caption(f"캐시: {CompetitorTracker.CACHE_TTL_HOURS}h 유지")

    # ── 탭 ───────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📡 경쟁 레이더",          # 채널 관리 → 경쟁 지형도
        "⚡ 트렌드 포착",           # 분석 실행 → 급상승 알림
        "💬 시청자 욕구 분석",      # 댓글 수집 → 감성+니즈 클러스터링
        "🎯 포지셔닝 전략",        # AI 채널 분석 → 빈틈 분석
        "💡 아이디어 캔버스",       # 메모장 → 분석→기획 연결
        "🖼️ 썸네일 분석",          # 썸네일 수집+변화추이+복제 프롬프트
    ])

    # ════════════════════════════════════════════════════════════
    # 탭 1: 채널 관리
    # ════════════════════════════════════════════════════════════
    with tab1:
        col_left, col_right = st.columns([1, 2])

        with col_left:
            st.subheader("그룹 / 채널 관리")
            groups = tracker.list_groups()

            # 그룹 선택
            group_options = groups if groups else ["(그룹 없음)"]
            selected = st.selectbox("그룹 선택", group_options, key="ct_group_select")
            if groups:
                st.session_state.ct_selected_group = selected

            new_group = st.text_input("새 그룹 이름", key="ct_new_group", placeholder="예: 경제채널")

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("＋ 그룹", use_container_width=True):
                    if new_group:
                        if tracker.add_group(new_group):
                            st.success(f"'{new_group}' 생성됨")
                            st.rerun()
                        else:
                            st.error("이미 있는 이름")
            with c2:
                if st.button("이름변경", use_container_width=True):
                    if groups and new_group:
                        tracker.rename_group(st.session_state.ct_selected_group, new_group)
                        st.rerun()
            with c3:
                if st.button("🗑 삭제", use_container_width=True):
                    if groups and st.session_state.ct_selected_group:
                        tracker.delete_group(st.session_state.ct_selected_group)
                        st.session_state.ct_selected_group = None
                        st.rerun()

            st.divider()

            # 채널 추가
            if st.session_state.ct_selected_group:
                st.markdown(f"**[{st.session_state.ct_selected_group}] 채널 추가**")
                ch_input = st.text_input(
                    "채널 링크 / @핸들 / URL 붙여넣기",
                    key="ct_ch_input",
                    placeholder="https://www.youtube.com/@channel  또는  @handle  또는  UCxxxxxx"
                )
                if st.button("채널 추가", use_container_width=True):
                    if ch_input:
                        with st.spinner("채널 정보 조회 중..."):
                            try:
                                info = tracker.add_channel_by_url(
                                    st.session_state.ct_selected_group, ch_input
                                )
                                st.success(f"✅ {info.get('title', ch_input)} 추가됨")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

                if st.button("🔄 구독자 새로고침", use_container_width=True):
                    with st.spinner("API 조회 중..."):
                        tracker.refresh_subscriber_counts(st.session_state.ct_selected_group)
                    st.success("완료")
                    st.rerun()

            # 채널 목록
            if st.session_state.ct_selected_group:
                channels = tracker.list_channels(st.session_state.ct_selected_group)
                st.markdown(f"**[{st.session_state.ct_selected_group}] 채널 {len(channels)}개**")
                for ch in channels:
                    with st.container():
                        c_col, d_col = st.columns([4, 1])
                        with c_col:
                            thumb = f"<img src='{ch.get('thumbnail_url','')}' width='28' style='border-radius:50%;vertical-align:middle;margin-right:6px;'>" if ch.get("thumbnail_url") else "📺 "
                            st.markdown(
                                f"{thumb}<b>{ch.get('channel_title', ch['channel_id'])}</b> "
                                f"<span style='color:#888;font-size:0.78rem;'>구독자 {_fmt_num(ch.get('subscriber_count',0))}</span>",
                                unsafe_allow_html=True
                            )
                            st.caption(f"추가일: {_fmt_date(ch.get('added_at',''))}")
                        with d_col:
                            if st.button("삭제", key=f"del_{ch['channel_id']}"):
                                tracker.delete_channel(st.session_state.ct_selected_group, ch["channel_id"])
                                st.rerun()

        with col_right:
            st.subheader("경쟁 지형도")
            if st.session_state.ct_selected_group:
                channels = tracker.list_channels(st.session_state.ct_selected_group)
                # 구독자 규모 바 차트
                if channels:
                    try:
                        import pandas as pd
                        df_map = pd.DataFrame([{
                            "채널": ch.get("channel_title", ch["channel_id"])[:12],
                            "구독자": ch.get("subscriber_count", 0),
                        } for ch in channels]).sort_values("구독자", ascending=True)
                        st.bar_chart(df_map.set_index("채널")["구독자"], height=180)
                    except Exception:
                        pass

                for ch in channels:
                    is_selected = st.session_state.ct_selected_channel == ch["channel_id"]
                    border = "#6ee7b7" if is_selected else "#252a40"
                    st.markdown(f"""
                    <div style='background:#181c2e;border-radius:8px;padding:0.7rem 1rem;
                    border:2px solid {border};margin-bottom:0.4rem;'>
                        <span style='font-weight:600;'>{ch.get('channel_title','')}</span>
                        <span style='color:#888;font-size:0.78rem;margin-left:8px;'>구독자 {_fmt_num(ch.get('subscriber_count',0))}</span>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("선택", key=f"sel_{ch['channel_id']}"):
                        st.session_state.ct_selected_channel = ch["channel_id"]
                        st.rerun()

    # ════════════════════════════════════════════════════════════
    # 탭 2: 분석 실행
    # ════════════════════════════════════════════════════════════
    with tab2:
        group = st.session_state.ct_selected_group
        if not group:
            st.info("채널 관리 탭에서 그룹을 선택하세요.")
        else:
            st.subheader(f"📊 {group} — 분석 리포트")

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("🚀 전체 수집 + 분석", type="primary", use_container_width=True):
                    with st.spinner("YouTube API로 영상 수집 중..."):
                        tracker.fetch_group_videos(group, max_per_channel=20, force=True)
                    st.success("✅ 수집 완료!")
                    st.rerun()
            with c2:
                if st.button("캐시 사용 (빠름)", use_container_width=True):
                    tracker.fetch_group_videos(group, force=False)
                    st.rerun()

            st.divider()

            # TOP3 카드
            top3 = tracker.get_top3_report(group)
            if top3:
                st.markdown("**🔥 TOP3 인기 영상**")
                cols = st.columns(3)
                labels = ["TOP 1", "TOP 2", "TOP 3"]
                for i, (v, col) in enumerate(zip(top3, cols)):
                    with col:
                        st.markdown(f"""
                        <div class="top-card">
                            <div class="top-label">{labels[i]}</div>
                            <div class="top-title">{v['title']}</div>
                            <div class="top-meta">
                                {v.get('channel_title','')} ·
                                조회수 {_fmt_num(v.get('view_count',0))} ·
                                댓글 {v.get('comment_count',0)}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

            # 자동 모니터링 요약
            stats = tracker.get_channel_stats(group)
            if stats:
                st.markdown("""
                <div style='background:#1a2035;border-radius:10px;padding:1rem 1.2rem;border:1px solid #2a3050;margin:1rem 0;'>
                    <b>✨ 자동 모니터링 관점 요약</b>
                </div>
                """, unsafe_allow_html=True)
                st.markdown(f"- 수집된 영상 **{stats['total_videos']}개** 분석 완료")
                st.markdown(f"- 평균 조회수 **{_fmt_num(int(stats['avg_views']))}** / 평균 댓글 **{int(stats['avg_comments'])}개**")
                st.markdown(f"- 최다 조회 채널: **{stats.get('top_channel','-')}**")

            st.divider()

            # 정렬 + 테이블
            sort_cols = st.columns([1, 1, 1, 1, 2])
            sort_options = ["조회수순", "최신순", "좋아요순", "댓글순"]
            for i, opt in enumerate(sort_options):
                with sort_cols[i]:
                    if st.button(
                        f"{'▶ ' if st.session_state.ct_sort == opt else ''}{opt}",
                        key=f"sort_{opt}",
                        use_container_width=True
                    ):
                        st.session_state.ct_sort = opt
                        st.rerun()

            with sort_cols[4]:
                if st.button("📋 20개 URL 복사용 출력", use_container_width=True):
                    urls = tracker.export_urls(group, limit=20, sort_by=st.session_state.ct_sort)
                    st.code(urls, language="text")

            videos = tracker.get_top_videos(group, sort_by=st.session_state.ct_sort, limit=50)
            if videos:
                import pandas as pd
                df = pd.DataFrame([{
                    "채널": v.get("channel_title", ""),
                    "영상 제목": v["title"],
                    "조회수": v.get("view_count", 0),
                    "좋아요": v.get("like_count", 0),
                    "댓글": v.get("comment_count", 0),
                    "게시일": _fmt_date(v.get("published_at", "")),
                    "video_id": v["video_id"],
                } for v in videos])

                st.dataframe(
                    df.drop(columns=["video_id"]),
                    use_container_width=True,
                    height=400,
                    column_config={
                        "조회수": st.column_config.NumberColumn(format="%d"),
                        "좋아요": st.column_config.NumberColumn(format="%d"),
                        "댓글": st.column_config.NumberColumn(format="%d"),
                    }
                )

                # 선택한 영상의 댓글 수집 버튼
                sel_title = st.selectbox(
                    "댓글 수집할 영상 선택",
                    options=df["영상 제목"].tolist(),
                    key="ct_video_select"
                )
                sel_row = df[df["영상 제목"] == sel_title].iloc[0] if sel_title else None
                if sel_row is not None:
                    st.session_state["ct_sel_video_id"] = sel_row["video_id"]
                    st.session_state["ct_sel_video_title"] = sel_title
            else:
                st.info("수집된 영상이 없습니다. 위 버튼으로 수집하세요.")

    # ════════════════════════════════════════════════════════════
    # 탭 3: 댓글 수집
    # ════════════════════════════════════════════════════════════
    with tab3:
        st.subheader("💬 댓글 수집 & 시청자 욕구 분석")

        vid_id = st.session_state.get("ct_sel_video_id", "")
        vid_title = st.session_state.get("ct_sel_video_title", "영상을 선택하지 않았습니다")

        st.info(f"선택된 영상: **{vid_title}**")

        manual_vid = st.text_input("또는 직접 video_id 입력", placeholder="dQw4w9WgXcQ")
        target_vid = manual_vid if manual_vid else vid_id

        c1, c2 = st.columns(2)
        with c1:
            max_c = st.slider("수집할 댓글 수", 20, 100, 50)
        with c2:
            if st.button("💬 댓글 수집", type="primary", use_container_width=True):
                if target_vid:
                    with st.spinner("댓글 수집 중..."):
                        comments = tracker.collect_comments(target_vid, max_c)
                    st.success(f"✅ {len(comments)}개 댓글 수집 완료")
                    st.rerun()
                else:
                    st.error("video_id를 입력하세요")

        if target_vid:
            comments = tracker.get_comments(target_vid)
            if comments:
                st.markdown(f"**수집된 댓글 {len(comments)}개**")

                if st.button("🤖 AI 댓글 감성 분석", use_container_width=True):
                    with st.spinner("Gemini 분석 중..."):
                        result = tracker.ai_analyze_comments_sentiment(target_vid)
                    st.markdown("### 분석 결과")
                    st.markdown(result)

                import pandas as pd
                df_c = pd.DataFrame([{
                    "댓글": c["text"],
                    "좋아요": c.get("like_count", 0),
                } for c in comments])
                st.dataframe(df_c, use_container_width=True, height=350)
            else:
                st.info("수집된 댓글이 없습니다.")

    # ════════════════════════════════════════════════════════════
    # 탭 4: AI 채널 분석
    # ════════════════════════════════════════════════════════════
    with tab4:
        st.subheader("🤖 AI 채널 분석 — 성공 공식 역설계")

        group = st.session_state.ct_selected_group
        if not group:
            st.info("채널 관리 탭에서 그룹을 선택하세요.")
        else:
            analysis_type = st.radio(
                "분석 유형",
                ["그룹 전체 트렌드 분석", "개별 채널 심층 분석"],
                horizontal=True
            )

            if analysis_type == "그룹 전체 트렌드 분석":
                st.markdown(f"**{group}** 그룹의 터지는 콘텐츠 패턴을 AI가 역설계합니다.")
                if st.button("🚀 그룹 트렌드 AI 분석 시작", type="primary", use_container_width=True):
                    with st.spinner("Gemini가 경쟁 채널 패턴을 분석 중..."):
                        result = tracker.ai_analyze_group_trend(group)
                    st.markdown("---")
                    st.markdown("### 📊 그룹 트렌드 분석 결과")
                    st.markdown(result)
                    # 자동 저장
                    tracker.save_note(
                        title=f"[자동저장] {group} 그룹 트렌드 분석",
                        content=result,
                        tags="AI분석,트렌드"
                    )
                    st.caption("💾 아이디어 캔버스에 자동 저장됨")

            else:
                channels = tracker.list_channels(group)
                if not channels:
                    st.info("채널이 없습니다.")
                else:
                    ch_names = {ch.get("channel_title", ch["channel_id"]): ch["channel_id"] for ch in channels}
                    sel_name = st.selectbox("분석할 채널", list(ch_names.keys()))
                    sel_id = ch_names[sel_name]

                    if st.button(f"🔬 '{sel_name}' 심층 분석", type="primary", use_container_width=True):
                        with st.spinner("채널 분석 중..."):
                            result = tracker.ai_analyze_channel(sel_id, sel_name)
                        st.markdown("---")
                        st.markdown(f"### 🔬 {sel_name} 채널 분석 결과")
                        st.markdown(result)
                        tracker.save_note(
                            title=f"[자동저장] {sel_name} 채널 분석",
                            content=result,
                            tags="AI분석,채널분석"
                        )
                        st.caption("💾 아이디어 캔버스에 자동 저장됨")

    # ════════════════════════════════════════════════════════════
    # 탭 6: 썸네일 분석
    # ════════════════════════════════════════════════════════════
    with tab6:
        st.subheader("🖼️ 썸네일 분석 — 보고 복붙하는 썸네일 공식")
        st.caption("경쟁 채널 썸네일을 수집·분석해 복제 프롬프트(Midjourney/DALL-E)를 자동 생성합니다.")

        group = st.session_state.ct_selected_group

        col_a, col_b = st.columns([2, 1])
        with col_a:
            st.markdown("**Step 1: 썸네일 수집**")
            if group:
                c1, c2 = st.columns(2)
                with c1:
                    th_limit = st.slider("수집 개수", 10, 50, 30, key="th_limit")
                with c2:
                    if st.button("🖼️ 썸네일 수집", type="primary", use_container_width=True):
                        with st.spinner("썸네일 URL 수집 중..."):
                            saved = tracker.collect_thumbnails(group, limit=th_limit)
                        st.success(f"✅ {len(saved)}개 썸네일 수집 완료")
                        st.rerun()
            else:
                st.info("채널 관리 탭에서 그룹을 선택하세요.")

        with col_b:
            st.markdown("**변화 추이 분석**")
            if group and st.button("📈 썸네일 트렌드 AI 분석", use_container_width=True):
                with st.spinner("트렌드 분석 중..."):
                    trend_result = tracker.ai_analyze_thumbnail_trend(group)
                st.session_state["th_trend_result"] = trend_result

        if st.session_state.get("th_trend_result"):
            with st.expander("📈 썸네일 트렌드 분석 결과", expanded=True):
                st.markdown(st.session_state["th_trend_result"])
                if st.button("💾 아이디어 캔버스에 저장", key="save_trend"):
                    tracker.save_note(
                        title=f"[썸네일 트렌드] {group}",
                        content=st.session_state["th_trend_result"],
                        tags="썸네일,트렌드"
                    )
                    st.success("저장됨")

        st.divider()
        st.markdown("**Step 2: 썸네일 갤러리 + 개별 분석**")

        thumbnails = tracker.get_thumbnails(group_name=group, limit=30) if group else []

        if thumbnails:
            # 채널별 필터
            ch_titles = list(set(t.get("channel_title", "") for t in thumbnails if t.get("channel_title")))
            ch_filter = st.selectbox("채널 필터", ["전체"] + ch_titles, key="th_ch_filter")
            filtered = thumbnails if ch_filter == "전체" else [
                t for t in thumbnails if t.get("channel_title") == ch_filter
            ]

            # 썸네일 그리드 (4열)
            cols_per_row = 4
            for i in range(0, len(filtered), cols_per_row):
                row_ths = filtered[i:i+cols_per_row]
                cols = st.columns(cols_per_row)
                for th, col in zip(row_ths, cols):
                    with col:
                        if th.get("thumbnail_url"):
                            st.image(th["thumbnail_url"], use_container_width=True)
                        st.caption(f"**{th.get('video_title','')[:35]}{'...' if len(th.get('video_title',''))>35 else ''}**")
                        st.caption(
                            f"👁 {_fmt_num(th.get('view_count',0))} · "
                            f"{th.get('channel_title','')} · "
                            f"{_fmt_date(th.get('published_at',''))}"
                        )
                        if th.get("ai_prompt"):
                            with st.expander("📋 프롬프트"):
                                st.code(th["ai_prompt"], language="text")
                        elif st.button("🤖 AI 분석", key=f"th_ai_{th['video_id']}", use_container_width=True):
                            with st.spinner("썸네일 분석 중..."):
                                result = tracker.ai_analyze_thumbnail(
                                    th["thumbnail_url"],
                                    th.get("video_title", ""),
                                    th.get("channel_title", "")
                                )
                            st.session_state[f"th_result_{th['video_id']}"] = result
                            st.rerun()

                        res = st.session_state.get(f"th_result_{th['video_id']}")
                        if res:
                            with st.expander("분석 결과 보기"):
                                st.markdown(res["analysis"])
                                st.markdown("**🎨 Midjourney 프롬프트:**")
                                st.code(res["midjourney_prompt"], language="text")
                                st.markdown("**🖼️ DALL-E 3 프롬프트:**")
                                st.code(res["dalle_prompt"], language="text")
                                if st.button("💾 저장", key=f"save_th_{th['video_id']}"):
                                    tracker.save_note(
                                        title=f"[썸네일 프롬프트] {th.get('video_title','')[:30]}",
                                        content=f"**Midjourney:**\n```\n{res['midjourney_prompt']}\n```\n\n**DALL-E 3:**\n```\n{res['dalle_prompt']}\n```\n\n---\n{res['analysis']}",
                                        tags="썸네일,프롬프트"
                                    )
                                    st.success("저장됨")

            st.divider()
            st.markdown("**Step 3: 채널 전체 썸네일 공식 일괄 생성**")
            if group:
                channels_th = tracker.list_channels(group)
                if channels_th:
                    ch_names_th = {c.get("channel_title", c["channel_id"]): c["channel_id"] for c in channels_th}
                    sel_ch = st.selectbox("채널 선택", list(ch_names_th.keys()), key="th_batch_ch")
                    sel_ch_id = ch_names_th[sel_ch]
                    if st.button(f"🎨 '{sel_ch}' 썸네일 공식 키트 생성", type="primary", use_container_width=True):
                        with st.spinner("채널 스타일 분석 + 프롬프트 생성 중..."):
                            kit = tracker.ai_create_thumbnail_prompt_batch(sel_ch_id, sel_ch)
                        st.markdown("### 🎨 썸네일 공식 키트")
                        st.markdown(kit)
                        tracker.save_note(
                            title=f"[썸네일 키트] {sel_ch}",
                            content=kit,
                            tags="썸네일,키트,프롬프트"
                        )
                        st.caption("💾 아이디어 캔버스에 저장됨")
        else:
            st.info("수집된 썸네일이 없습니다. Step 1에서 먼저 수집하세요.")

    # ════════════════════════════════════════════════════════════
    # 탭 5: 아이디어 캔버스 (메모장)
    # ════════════════════════════════════════════════════════════
    with tab5:
        st.subheader("📝 아이디어 캔버스")
        st.caption("분석 결과, 기획 아이디어, 제목 공식을 저장합니다. AI 분석 결과는 자동 저장됩니다.")

        with st.expander("＋ 새 메모 작성", expanded=False):
            note_title = st.text_input("제목", key="new_note_title")
            note_content = st.text_area("내용", key="new_note_content", height=150)
            note_tags = st.text_input("태그 (쉼표 구분)", key="new_note_tags", placeholder="트렌드,제목공식")
            if st.button("💾 저장", key="save_new_note"):
                if note_title:
                    tracker.save_note(note_title, note_content, note_tags)
                    st.success("저장됨")
                    st.rerun()

        notes = tracker.list_notes()
        if not notes:
            st.info("저장된 메모가 없습니다.")
        else:
            for note in notes:
                with st.expander(f"📌 {note['title']}  —  {_fmt_date(note['updated_at'])}", expanded=False):
                    st.markdown(note["content"])
                    if note.get("tags"):
                        for tag in note["tags"].split(","):
                            st.markdown(f"`{tag.strip()}`", unsafe_allow_html=False)
                    col1, col2 = st.columns(2)
                    with col1:
                        new_c = st.text_area("편집", value=note["content"], key=f"edit_{note['id']}", height=100)
                        if st.button("업데이트", key=f"upd_{note['id']}"):
                            tracker.update_note(note["id"], note["title"], new_c, note.get("tags",""))
                            st.rerun()
                    with col2:
                        if st.button("🗑 삭제", key=f"del_note_{note['id']}"):
                            tracker.delete_note(note["id"])
                            st.rerun()
