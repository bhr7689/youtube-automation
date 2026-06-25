"""WF-1 YouTube Keyword Collector (기획서 MVP).

Notion 'Search Keyword Master' DB의 ACTIVE 키워드를 순회하며 각 키워드별로
YouTube 영상을 수집하고, 'YouTube Reference Videos' DB에 영상별 한 줄씩
upsert(중복 체크)한다. Performance Score 와 Reference Level 자동 계산.

환경변수 (GitHub Secrets):
  YOUTUBE_API_KEY                  (필수)
  NOTION_TOKEN                     (필수)
  NOTION_KEYWORD_MASTER_DB_ID      (필수) — Search Keyword Master DB ID
  NOTION_REFERENCE_VIDEOS_DB_ID    (필수) — YouTube Reference Videos DB ID

선택 환경변수:
  COLLECT_PER_KEYWORD     (기본 15) — 키워드당 영상 개수
  COLLECT_DAYS            (기본 90) — 최근 N일 영상만 (0 = 전체기간)
  COLLECT_PRIORITY_FILTER (예: 'A,B') — 특정 우선순위만
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"


# ============================================================
# Notion 헬퍼
# ============================================================
def _hdr(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _rich(s: str, limit: int = 1900) -> list[dict]:
    s = (s or "")[:limit]
    return [{"type": "text", "text": {"content": s}}] if s else []


def _read_prop(page: dict, name: str, type_: str):
    """페이지에서 속성 값 읽기 (없으면 None)."""
    props = page.get("properties", {})
    p = props.get(name)
    if not p:
        return None
    if type_ == "title":
        arr = p.get("title", [])
        return "".join(x.get("plain_text", "") for x in arr) or None
    if type_ == "rich_text":
        arr = p.get("rich_text", [])
        return "".join(x.get("plain_text", "") for x in arr) or None
    if type_ == "select":
        v = p.get("select")
        return v.get("name") if v else None
    if type_ == "multi_select":
        return [v.get("name") for v in p.get("multi_select", [])]
    if type_ == "number":
        return p.get("number")
    return None


def _find_prop(schema: dict, candidates: list[str], type_: str) -> str | None:
    """DB 스키마에서 컬럼명을 한/영 부분 매칭 + 타입 일치로 찾기."""
    for name, spec in schema.items():
        if spec.get("type") != type_:
            continue
        for c in candidates:
            if c.lower() in name.lower():
                return name
    return None


def query_db(token: str, db_id: str, filter_: dict | None = None) -> list[dict]:
    """DB 전체 페이지 페이지네이션 순회."""
    pages, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        if filter_:
            payload["filter"] = filter_
        r = requests.post(
            f"{NOTION_API}/databases/{db_id}/query",
            headers=_hdr(token), data=json.dumps(payload), timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def get_db_schema(token: str, db_id: str) -> dict:
    r = requests.get(
        f"{NOTION_API}/databases/{db_id}", headers=_hdr(token), timeout=15,
    )
    r.raise_for_status()
    return r.json().get("properties", {})


def create_page(token: str, db_id: str, properties: dict) -> dict:
    r = requests.post(
        f"{NOTION_API}/pages", headers=_hdr(token),
        data=json.dumps({"parent": {"database_id": db_id}, "properties": properties}),
        timeout=20,
    )
    if r.status_code >= 400:
        print(f"[Notion create 오류] {r.status_code}: {r.text[:400]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def update_page(token: str, page_id: str, properties: dict) -> dict:
    r = requests.patch(
        f"{NOTION_API}/pages/{page_id}", headers=_hdr(token),
        data=json.dumps({"properties": properties}), timeout=20,
    )
    if r.status_code >= 400:
        print(f"[Notion update 오류] {r.status_code}: {r.text[:400]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def find_existing_video(
    token: str, db_id: str, video_id_prop: str, video_id: str
) -> str | None:
    """Video ID 기준 기존 페이지 찾기 → page_id 반환."""
    filter_ = {
        "property": video_id_prop,
        "rich_text": {"equals": video_id},
    }
    try:
        results = query_db(token, db_id, filter_)
        return results[0]["id"] if results else None
    except Exception:
        return None


# ============================================================
# YouTube API
# ============================================================
def yt_client(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def parse_duration(s: str) -> int | None:
    if not s:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def collect_videos_for_keyword(
    yt, *, keyword: str, region: str, lang: str,
    per_keyword: int, days: int,
) -> list[dict]:
    """단일 키워드 → 영상 메타 풀세트."""
    published_after = None
    if days > 0:
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

    # 1) 검색 → ID
    ids: list[str] = []
    page_token = None
    while len(ids) < per_keyword:
        params = {
            "part": "id", "q": keyword, "type": "video",
            "order": "viewCount",
            "maxResults": min(50, per_keyword - len(ids)),
            "pageToken": page_token,
        }
        if region:
            params["regionCode"] = region
        if lang:
            params["relevanceLanguage"] = lang
        if published_after:
            params["publishedAfter"] = published_after
        resp = yt.search().list(**params).execute()
        for it in resp.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if not ids:
        return []

    # 2) 영상 메타
    videos: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(ids[i:i + 50]), maxResults=50,
        ).execute()
        for it in resp.get("items", []):
            vid = it["id"]
            sn = it.get("snippet", {})
            stat = it.get("statistics", {})
            cd = it.get("contentDetails", {})
            videos[vid] = {
                "video_id": vid,
                "title": sn.get("title", ""),
                "channel_id": sn.get("channelId"),
                "channel_title": sn.get("channelTitle", ""),
                "published_at": sn.get("publishedAt", "")[:10],
                "thumbnail_url": (
                    sn.get("thumbnails", {}).get("maxres", {}).get("url")
                    or sn.get("thumbnails", {}).get("high", {}).get("url")
                    or sn.get("thumbnails", {}).get("default", {}).get("url")
                    or ""
                ),
                "view_count": int(stat.get("viewCount", 0) or 0),
                "like_count": int(stat.get("likeCount", 0) or 0),
                "comment_count": int(stat.get("commentCount", 0) or 0),
                "duration": cd.get("duration", ""),
                "duration_s": parse_duration(cd.get("duration", "")),
            }

    # 3) 채널 정보
    chan_ids = list({v["channel_id"] for v in videos.values() if v.get("channel_id")})
    chan_info: dict[str, dict] = {}
    for i in range(0, len(chan_ids), 50):
        resp = yt.channels().list(
            part="snippet,statistics",
            id=",".join(chan_ids[i:i + 50]), maxResults=50,
        ).execute()
        for it in resp.get("items", []):
            cid = it["id"]
            sn = it.get("snippet", {})
            stat = it.get("statistics", {})
            chan_info[cid] = {
                "channel_url": f"https://www.youtube.com/channel/{cid}",
                "channel_thumbnail": (
                    sn.get("thumbnails", {}).get("high", {}).get("url")
                    or sn.get("thumbnails", {}).get("default", {}).get("url")
                    or ""
                ),
                "subscriber_count": (
                    None if stat.get("hiddenSubscriberCount")
                    else int(stat.get("subscriberCount", 0) or 0)
                ),
            }
    for v in videos.values():
        v.update(chan_info.get(v.get("channel_id"), {}))

    return list(videos.values())


# ============================================================
# Performance Score (기획서 그대로 100점)
# ============================================================
def calc_performance_score(v: dict, keyword: str) -> int:
    score = 0
    if v.get("view_count", 0) >= 100_000:
        score += 20
    pub = v.get("published_at", "")
    try:
        if pub:
            pub_dt = datetime.strptime(pub, "%Y-%m-%d")
            if (datetime.now() - pub_dt).days <= 30:
                score += 20
    except Exception:
        pass
    if v.get("comment_count", 0) >= 100:
        score += 10
    title_l = (v.get("title", "") or "").lower()
    if keyword and any(w in title_l for w in keyword.lower().split() if len(w) >= 2):
        score += 10
    # 썸네일 점수: maxres URL이 잡힌 경우 +20 (정밀 분석은 다음 단계 Vision)
    if v.get("thumbnail_url", ""):
        score += 20
    # 카테고리 일치: 검색 키워드의 카테고리이므로 항상 +20
    score += 20
    return min(100, score)


def to_reference_level(score: int) -> str:
    if score >= 80:
        return "A급"
    if score >= 50:
        return "B급"
    return "C급"


# ============================================================
# 키워드 마스터 읽기
# ============================================================
def read_keywords(token: str, db_id: str) -> list[dict]:
    """ACTIVE 키워드만 가져오기."""
    schema = get_db_schema(token, db_id)
    title_prop = next((n for n, s in schema.items() if s.get("type") == "title"), None)
    status_prop = _find_prop(schema, ["status"], "select")
    priority_prop = _find_prop(schema, ["priority", "우선"], "select")
    region_prop = _find_prop(schema, ["region", "지역"], "select")
    lang_prop = _find_prop(schema, ["language", "언어"], "select")
    main_prop = _find_prop(schema, ["main category", "main", "대카"], "select")
    middle_prop = _find_prop(schema, ["middle category", "middle", "중카"], "select")
    sub_prop = _find_prop(schema, ["sub category", "sub", "소카"], "select")
    en_prop = _find_prop(schema, ["en keyword", "영어", "english"], "rich_text")
    kr_prop = _find_prop(schema, ["kr keyword", "한국어", "korean"], "rich_text")
    jp_prop = _find_prop(schema, ["jp keyword", "일본어", "japanese"], "rich_text")

    filter_ = None
    if status_prop:
        filter_ = {"property": status_prop, "select": {"equals": "ACTIVE"}}

    priorities_filter = os.environ.get("COLLECT_PRIORITY_FILTER", "").strip()
    pri_allow = {p.strip() for p in priorities_filter.split(",") if p.strip()}

    rows = []
    for page in query_db(token, db_id, filter_):
        title = _read_prop(page, title_prop, "title") if title_prop else None
        if not title:
            continue
        priority = _read_prop(page, priority_prop, "select") if priority_prop else None
        if pri_allow and priority not in pri_allow:
            continue
        rows.append({
            "page_id": page["id"],
            "keyword": title,
            "en": _read_prop(page, en_prop, "rich_text") if en_prop else None,
            "kr": _read_prop(page, kr_prop, "rich_text") if kr_prop else None,
            "jp": _read_prop(page, jp_prop, "rich_text") if jp_prop else None,
            "region": (_read_prop(page, region_prop, "select") if region_prop else None) or "",
            "language": (_read_prop(page, lang_prop, "select") if lang_prop else None) or "",
            "main": _read_prop(page, main_prop, "select") if main_prop else None,
            "middle": _read_prop(page, middle_prop, "select") if middle_prop else None,
            "sub": _read_prop(page, sub_prop, "select") if sub_prop else None,
            "priority": priority,
        })
    return rows


def pick_search_term(row: dict) -> str:
    """검색에 사용할 실제 키워드 결정 (region/language에 맞는 다국어 컬럼 우선)."""
    region = (row.get("region") or "").upper()
    lang = (row.get("language") or "").upper()
    if region == "JP" or lang == "JP":
        return row.get("jp") or row.get("en") or row["keyword"]
    if region == "KR" or lang == "KR":
        return row.get("kr") or row.get("keyword")
    return row.get("en") or row["keyword"]


# ============================================================
# Reference Videos DB에 upsert
# ============================================================
def upsert_videos(
    token: str, db_id: str,
    videos: list[dict], kw_row: dict, search_term: str,
):
    schema = get_db_schema(token, db_id)
    title_prop = next((n for n, s in schema.items() if s.get("type") == "title"), None)

    # 컬럼 자동 매칭
    cols = {
        "video_url":    _find_prop(schema, ["video url"], "url"),
        "video_id":     _find_prop(schema, ["video id"], "rich_text"),
        "channel_name": _find_prop(schema, ["channel name", "채널명"], "rich_text"),
        "channel_id":   _find_prop(schema, ["channel id"], "rich_text"),
        "channel_url":  _find_prop(schema, ["channel url"], "url"),
        "channel_thumb":_find_prop(schema, ["channel thumbnail"], "url"),
        "thumbnail":    _find_prop(schema, ["thumbnail url"], "url"),
        "published":    _find_prop(schema, ["published"], "date"),
        "collected":    _find_prop(schema, ["collected"], "date"),
        "view":         _find_prop(schema, ["view count", "조회수"], "number"),
        "like":         _find_prop(schema, ["like count", "좋아요"], "number"),
        "comment":      _find_prop(schema, ["comment count", "댓글"], "number"),
        "duration":     _find_prop(schema, ["duration", "길이"], "rich_text"),
        "search_kw":    _find_prop(schema, ["search keyword", "검색"], "rich_text"),
        "main":         _find_prop(schema, ["main category"], "select"),
        "middle":       _find_prop(schema, ["middle category"], "select"),
        "sub":          _find_prop(schema, ["sub category"], "select"),
        "score":        _find_prop(schema, ["performance", "점수", "score"], "number"),
        "level":        _find_prop(schema, ["reference level", "레퍼런스"], "select"),
        "status":       _find_prop(schema, ["analysis status"], "select"),
        "subs":         _find_prop(schema, ["subscriber"], "number"),
    }

    if not cols["video_id"]:
        print("⚠️ Reference Videos DB에 'Video ID' (rich_text) 컬럼이 필요해요.")
        return 0, 0

    created, skipped = 0, 0
    today = datetime.now().strftime("%Y-%m-%d")

    for v in videos:
        vid = v["video_id"]
        # 중복 체크
        existing = find_existing_video(token, db_id, cols["video_id"], vid)
        if existing:
            # 통계만 업데이트 (조회수/좋아요/댓글이 늘어남)
            score = calc_performance_score(v, search_term)
            level = to_reference_level(score)
            update_props: dict = {}
            if cols["view"]:    update_props[cols["view"]]    = {"number": v["view_count"]}
            if cols["like"]:    update_props[cols["like"]]    = {"number": v["like_count"]}
            if cols["comment"]: update_props[cols["comment"]] = {"number": v["comment_count"]}
            if cols["score"]:   update_props[cols["score"]]   = {"number": score}
            if cols["level"]:   update_props[cols["level"]]   = {"select": {"name": level}}
            if cols["subs"] and v.get("subscriber_count") is not None:
                update_props[cols["subs"]] = {"number": v["subscriber_count"]}
            if update_props:
                update_page(token, existing, update_props)
            skipped += 1
            continue

        # 신규 생성
        score = calc_performance_score(v, search_term)
        level = to_reference_level(score)
        props: dict = {}
        if title_prop:        props[title_prop]        = {"title": _rich(v["title"])}
        if cols["video_url"]: props[cols["video_url"]] = {"url": f"https://www.youtube.com/watch?v={vid}"}
        if cols["video_id"]:  props[cols["video_id"]]  = {"rich_text": _rich(vid)}
        if cols["channel_name"]: props[cols["channel_name"]] = {"rich_text": _rich(v.get("channel_title", ""))}
        if cols["channel_id"]:   props[cols["channel_id"]]   = {"rich_text": _rich(v.get("channel_id", ""))}
        if cols["channel_url"] and v.get("channel_url"):
            props[cols["channel_url"]] = {"url": v["channel_url"]}
        if cols["channel_thumb"] and v.get("channel_thumbnail"):
            props[cols["channel_thumb"]] = {"url": v["channel_thumbnail"]}
        if cols["thumbnail"] and v.get("thumbnail_url"):
            props[cols["thumbnail"]] = {"url": v["thumbnail_url"]}
        if cols["published"] and v.get("published_at"):
            props[cols["published"]] = {"date": {"start": v["published_at"]}}
        if cols["collected"]: props[cols["collected"]] = {"date": {"start": today}}
        if cols["view"]:      props[cols["view"]]      = {"number": v["view_count"]}
        if cols["like"]:      props[cols["like"]]      = {"number": v["like_count"]}
        if cols["comment"]:   props[cols["comment"]]   = {"number": v["comment_count"]}
        if cols["duration"]:  props[cols["duration"]]  = {"rich_text": _rich(v.get("duration", ""))}
        if cols["search_kw"]: props[cols["search_kw"]] = {"rich_text": _rich(search_term)}
        if cols["main"] and kw_row.get("main"):
            props[cols["main"]] = {"select": {"name": kw_row["main"]}}
        if cols["middle"] and kw_row.get("middle"):
            props[cols["middle"]] = {"select": {"name": kw_row["middle"]}}
        if cols["sub"] and kw_row.get("sub"):
            props[cols["sub"]] = {"select": {"name": kw_row["sub"]}}
        if cols["score"]:     props[cols["score"]]     = {"number": score}
        if cols["level"]:     props[cols["level"]]     = {"select": {"name": level}}
        if cols["status"]:    props[cols["status"]]    = {"select": {"name": "NEW"}}
        if cols["subs"] and v.get("subscriber_count") is not None:
            props[cols["subs"]] = {"number": v["subscriber_count"]}

        try:
            create_page(token, db_id, props)
            created += 1
        except Exception as e:
            print(f"[skip] {vid} 생성 실패: {e}", file=sys.stderr)

    return created, skipped


# ============================================================
# main
# ============================================================
def main():
    yt_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    notion_token = os.environ.get("NOTION_TOKEN", "").strip()
    kw_db = os.environ.get("NOTION_KEYWORD_MASTER_DB_ID", "").strip()
    ref_db = os.environ.get("NOTION_REFERENCE_VIDEOS_DB_ID", "").strip()
    if not (yt_key and notion_token and kw_db and ref_db):
        sys.exit("필수 환경변수 누락: YOUTUBE_API_KEY, NOTION_TOKEN, "
                 "NOTION_KEYWORD_MASTER_DB_ID, NOTION_REFERENCE_VIDEOS_DB_ID")

    per_kw = int(os.environ.get("COLLECT_PER_KEYWORD", "15"))
    days = int(os.environ.get("COLLECT_DAYS", "90"))

    keywords = read_keywords(notion_token, kw_db)
    if not keywords:
        sys.exit("ACTIVE 키워드가 없어요. Search Keyword Master DB에 Status=ACTIVE 인 행을 추가하세요.")

    print(f"📋 ACTIVE 키워드 {len(keywords)}개 처리 시작 (키워드당 영상 {per_kw}개)")
    yt = yt_client(yt_key)
    total_created, total_skipped = 0, 0

    for i, row in enumerate(keywords, 1):
        term = pick_search_term(row)
        region = row.get("region", "")
        lang = (row.get("language") or "").lower()
        if lang in ("kr",): lang = "ko"
        elif lang in ("jp",): lang = "ja"
        elif lang == "en": lang = "en"
        elif lang == "fr": lang = "fr"
        elif lang == "hi": lang = "hi"
        print(f"\n[{i}/{len(keywords)}] '{row['keyword']}' → 검색어 '{term}' "
              f"(region={region or '-'}, lang={lang or '-'})")
        try:
            vids = collect_videos_for_keyword(
                yt, keyword=term, region=region, lang=lang,
                per_keyword=per_kw, days=days,
            )
        except Exception as e:
            print(f"  ⚠️ 수집 실패: {e}", file=sys.stderr)
            continue
        if not vids:
            print("  · 영상 0개")
            continue
        created, skipped = upsert_videos(notion_token, ref_db, vids, row, term)
        total_created += created
        total_skipped += skipped
        print(f"  ✅ 신규 {created} · 기존업데이트 {skipped}")

    print(f"\n🎉 완료 — 신규 {total_created}건 / 기존 업데이트 {total_skipped}건")


if __name__ == "__main__":
    main()
