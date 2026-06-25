"""자동 시드 발굴 → Notion DB 저장.

GitHub Actions cron 으로 매일/N일 트리거. 각 실행마다:
  1) 설정한 국가들의 히든 젬(또는 인기 급상승) 발굴
  2) 영상 제목에서 시드 키워드 추출 (단일/국가별 + 다국가 공통)
  3) Notion DB에 한 줄(페이지) 추가, 본문에 영상 리스트 포함

환경변수 (전부 GitHub Secrets로 관리):
  YOUTUBE_API_KEY      (필수)
  NOTION_TOKEN         (필수) — Notion integration internal token
  NOTION_DATABASE_ID   (필수) — 32자 hex

선택 환경변수 (없으면 기본값):
  REPORT_MODE          'hidden_gems' (기본) | 'trending'
  REPORT_COUNTRIES     'KR,US,JP'  콤마 구분 ISO 코드
  REPORT_LANGS         'ko,en,ja'  콤마 구분 (없으면 국가 기본 매핑)
  REPORT_DAYS          '7'
  REPORT_MIN_RATIO     '5'
  REPORT_MIN_VIEWS     '5000'
  REPORT_TOP_N         '30'
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

# ---- 토큰 추출 (다국어 호환) ----
WORD_RE = re.compile(r"[^\W\d_]+", flags=re.UNICODE)
STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "are", "was", "were",
    "this", "that", "but", "from", "have", "has", "not", "all", "new",
    "그", "이", "저", "것", "수", "들", "더", "또", "및", "위", "왜",
    "el", "la", "los", "las", "de", "en", "del", "que", "por", "para",
    "con", "una", "uno", "se", "lo", "su", "mi", "te", "do", "da", "no",
    "の", "は", "を", "に", "が", "と", "で", "へ", "や", "も",
    "ft", "feat", "official", "audio", "video", "mv", "live", "lyrics",
    "shorts", "short", "youtube", "vlog", "ep", "full", "ver",
}


def extract_seeds(titles: list[str], top_n: int = 15) -> list[tuple[str, int]]:
    """단어 + 인접 2-gram 빈도 기반 시드 추출."""
    word_c: Counter[str] = Counter()
    bigram_c: Counter[str] = Counter()
    for t in titles:
        toks: list[str] = []
        for m in WORD_RE.findall(t):
            ml = m.lower()
            if len(ml) < 2 or ml in STOPWORDS:
                continue
            is_cjk = any(
                0xAC00 <= ord(c) <= 0xD7A3 or 0x3040 <= ord(c) <= 0x9FFF
                for c in m
            )
            toks.append(m if is_cjk else ml)
        for tok in toks:
            word_c[tok] += 1
        for a, b in zip(toks, toks[1:]):
            bigram_c[f"{a} {b}"] += 1
    seeds: list[tuple[str, int]] = []
    seen: set[str] = set()
    for term, c in bigram_c.most_common():
        if c < 2:
            break
        seeds.append((term, c))
        for w in term.split():
            seen.add(w)
    for term, c in word_c.most_common():
        if c < 2:
            continue
        if term in seen:
            continue
        seeds.append((term, c))
        seen.add(term)
    seeds.sort(key=lambda x: x[1], reverse=True)
    return seeds[:top_n]


def parse_iso_duration_to_seconds(s: str) -> int | None:
    if not s:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


# ---- YouTube API ----
def yt_client(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def fetch_hidden_gems(
    api_key: str, *, region: str, lang: str, days: int,
    pool_size: int, top_n: int, min_ratio: float, min_views: int,
) -> list[dict]:
    yt = yt_client(api_key)
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    ids: list[str] = []
    page_token = None
    while len(ids) < pool_size:
        resp = yt.search().list(
            part="id", q="", type="video", order="viewCount",
            publishedAfter=published_after,
            maxResults=min(50, pool_size - len(ids)),
            regionCode=region, relevanceLanguage=lang, pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

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
            videos[vid] = {
                "video_id": vid,
                "title": sn.get("title", ""),
                "channel_id": sn.get("channelId"),
                "channel_title": sn.get("channelTitle", ""),
                "view_count": int(stat.get("viewCount", 0) or 0),
                "duration_s": parse_iso_duration_to_seconds(
                    it.get("contentDetails", {}).get("duration", "")
                ),
            }

    chan_ids = list({v["channel_id"] for v in videos.values() if v.get("channel_id")})
    subs: dict[str, int] = {}
    hidden: set[str] = set()
    for i in range(0, len(chan_ids), 50):
        resp = yt.channels().list(
            part="statistics", id=",".join(chan_ids[i:i + 50]), maxResults=50,
        ).execute()
        for it in resp.get("items", []):
            cid = it["id"]
            stat = it.get("statistics", {})
            if stat.get("hiddenSubscriberCount"):
                hidden.add(cid)
                continue
            subs[cid] = int(stat.get("subscriberCount", 0) or 0)

    results = []
    for v in videos.values():
        cid = v.get("channel_id")
        if not cid or cid in hidden:
            continue
        s = subs.get(cid, 0)
        views = v["view_count"]
        if views < min_views:
            continue
        ratio = views / max(s, 100)
        if ratio < min_ratio:
            continue
        v["subscriber_count"] = s
        v["viral_ratio"] = ratio
        results.append(v)
    results.sort(key=lambda x: x["viral_ratio"], reverse=True)
    return results[:top_n]


def fetch_trending(api_key: str, *, region: str, top_n: int) -> list[dict]:
    yt = yt_client(api_key)
    out: list[dict] = []
    page_token = None
    while len(out) < top_n:
        resp = yt.videos().list(
            part="snippet,contentDetails,statistics",
            chart="mostPopular", regionCode=region,
            maxResults=min(50, top_n - len(out)), pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            sn = it.get("snippet", {})
            stat = it.get("statistics", {})
            out.append({
                "video_id": it.get("id"),
                "title": sn.get("title", ""),
                "channel_title": sn.get("channelTitle", ""),
                "view_count": int(stat.get("viewCount", 0) or 0),
                "duration_s": parse_iso_duration_to_seconds(
                    it.get("contentDetails", {}).get("duration", "")
                ),
                "viral_ratio": None, "subscriber_count": None,
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


# ---- Notion API ----
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"


def _notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _txt(s: str, *, limit: int = 1900) -> list[dict]:
    s = (s or "")[:limit]
    return [{"type": "text", "text": {"content": s}}] if s else []


def _block_h2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": _txt(text)}}


def _block_h3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": _txt(text)}}


def _block_p(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _txt(text)}}


def _block_bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _txt(text)}}


def fmt_count(n: int | None) -> str:
    if n is None:
        return "-"
    if n >= 10_000_000:
        return f"{n/10_000_000:.1f}천만"
    if n >= 10_000:
        return f"{n/10_000:.1f}만"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def push_to_notion(
    *, token: str, db_id: str,
    title: str, date_iso: str, mode_label: str,
    countries: list[str], seeds_csv: str, common_csv: str,
    video_count: int, by_country: dict[str, list[dict]],
):
    # 1) DB 스키마 확인 — 사용자가 어떤 컬럼명을 썼는지 파악해서 그것만 채움
    db_resp = requests.get(
        f"{NOTION_API}/databases/{db_id}", headers=_notion_headers(token), timeout=15,
    )
    db_resp.raise_for_status()
    db = db_resp.json()
    props_schema = db.get("properties", {})

    # 컬럼명 매칭 (한국어/영어 양쪽 시도, 타입 일치 시만 채움)
    def find_prop(candidates: list[str], type_: str) -> str | None:
        for name, spec in props_schema.items():
            if spec.get("type") != type_:
                continue
            for c in candidates:
                if c.lower() in name.lower():
                    return name
        return None

    properties: dict = {}
    title_prop = next(
        (n for n, s in props_schema.items() if s.get("type") == "title"), None
    )
    if title_prop:
        properties[title_prop] = {"title": _txt(title)}

    if p := find_prop(["날짜", "date"], "date"):
        properties[p] = {"date": {"start": date_iso}}
    if p := find_prop(["모드", "mode"], "select"):
        properties[p] = {"select": {"name": mode_label}}
    if p := find_prop(["국가", "country"], "multi_select"):
        properties[p] = {"multi_select": [{"name": c[:90]} for c in countries]}
    if p := find_prop(["공통", "common"], "rich_text"):
        properties[p] = {"rich_text": _txt(common_csv)}
    if p := find_prop(["시드", "seed", "키워드", "keyword"], "rich_text"):
        properties[p] = {"rich_text": _txt(seeds_csv)}
    if p := find_prop(["영상 수", "영상수", "count", "video"], "number"):
        properties[p] = {"number": video_count}

    # 2) 본문 블록
    children: list[dict] = []
    children.append(_block_p(f"📅 {date_iso} · {mode_label} · {video_count}개 영상"))
    if common_csv:
        children.append(_block_h2("🌍 글로벌 공통 시드"))
        children.append(_block_p(common_csv))
    for country, vids in by_country.items():
        if not vids:
            continue
        children.append(_block_h2(f"{country} · 영상 {len(vids)}개"))
        seeds = extract_seeds([v["title"] for v in vids], top_n=12)
        if seeds:
            children.append(_block_h3("🎯 시드 키워드"))
            children.append(_block_p(", ".join(f"{t}({c})" for t, c in seeds)))
        children.append(_block_h3("💎 상위 영상"))
        for v in vids[:15]:
            ratio = v.get("viral_ratio")
            ratio_txt = f"⚡{ratio:.0f}배 · " if ratio else ""
            subs = fmt_count(v.get("subscriber_count"))
            views = fmt_count(v.get("view_count"))
            ch = v.get("channel_title", "")
            children.append(_block_bullet(
                f"{ratio_txt}{v['title']}  ({ch} · 구독 {subs} → 조회 {views})"
            ))

    # 3) 페이지 생성
    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
        "children": children[:100],  # Notion 100블록 제한
    }
    resp = requests.post(
        f"{NOTION_API}/pages", headers=_notion_headers(token),
        data=json.dumps(payload), timeout=30,
    )
    if resp.status_code >= 400:
        print(f"[Notion 오류] {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json().get("url", "")


# ---- 국가/언어 매핑 ----
COUNTRY_LANG = {
    "KR": ("🇰🇷 한국", "ko"),
    "US": ("🇺🇸 미국", "en"),
    "GB": ("🇬🇧 영국", "en"),
    "JP": ("🇯🇵 일본", "ja"),
    "IN": ("🇮🇳 인도", "hi"),
    "MX": ("🇲🇽 멕시코", "es"),
    "ES": ("🇪🇸 스페인", "es"),
    "BR": ("🇧🇷 브라질", "pt"),
    "DE": ("🇩🇪 독일", "de"),
    "FR": ("🇫🇷 프랑스", "fr"),
    "ID": ("🇮🇩 인도네시아", "id"),
    "VN": ("🇻🇳 베트남", "vi"),
    "TH": ("🇹🇭 태국", "th"),
    "PH": ("🇵🇭 필리핀", "en"),
}


def main():
    yt_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    notion_token = os.environ.get("NOTION_TOKEN", "").strip()
    notion_db = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not yt_key:
        sys.exit("YOUTUBE_API_KEY 환경변수가 필요해요.")
    if not notion_token or not notion_db:
        sys.exit("NOTION_TOKEN, NOTION_DATABASE_ID 환경변수가 필요해요.")

    mode = os.environ.get("REPORT_MODE", "hidden_gems").strip()
    countries_csv = os.environ.get("REPORT_COUNTRIES", "KR,US,JP").strip()
    langs_csv = os.environ.get("REPORT_LANGS", "").strip()
    days = int(os.environ.get("REPORT_DAYS", "7"))
    min_ratio = float(os.environ.get("REPORT_MIN_RATIO", "5"))
    min_views = int(os.environ.get("REPORT_MIN_VIEWS", "5000"))
    top_n = int(os.environ.get("REPORT_TOP_N", "30"))

    codes = [c.strip().upper() for c in countries_csv.split(",") if c.strip()]
    langs = (
        [l.strip() for l in langs_csv.split(",") if l.strip()]
        if langs_csv else [None] * len(codes)
    )
    # 길이 맞추기
    while len(langs) < len(codes):
        langs.append(None)

    by_country: dict[str, list[dict]] = {}
    for code, lang in zip(codes, langs):
        if code not in COUNTRY_LANG:
            print(f"[skip] 미지원 국가 코드: {code}")
            continue
        label, default_lang = COUNTRY_LANG[code]
        eff_lang = lang or default_lang
        try:
            if mode == "trending":
                vids = fetch_trending(yt_key, region=code, top_n=top_n)
            else:
                vids = fetch_hidden_gems(
                    yt_key, region=code, lang=eff_lang, days=days,
                    pool_size=min(200, top_n * 6), top_n=top_n,
                    min_ratio=min_ratio, min_views=min_views,
                )
            print(f"[{label}] 영상 {len(vids)}개 수집")
            by_country[label] = vids
        except Exception as e:
            print(f"[{label}] 수집 실패: {e}", file=sys.stderr)

    if not any(by_country.values()):
        sys.exit("모든 국가에서 결과가 없어요. 임계값을 낮추거나 국가를 바꿔보세요.")

    # 시드 추출
    seeds_by_country = {
        c: extract_seeds([v["title"] for v in vs], top_n=20)
        for c, vs in by_country.items()
    }
    # 다국가 공통 시드
    appear_in: dict[str, set[str]] = {}
    for c, seeds in seeds_by_country.items():
        for t, _ in seeds:
            appear_in.setdefault(t, set()).add(c)
    common = sorted(
        [(t, cs) for t, cs in appear_in.items() if len(cs) >= 2],
        key=lambda x: (-len(x[1]), x[0]),
    )

    today = datetime.now().strftime("%Y-%m-%d")
    mode_label = "💎 히든젬" if mode == "hidden_gems" else "📺 인기급상승"
    title = f"{today} · {mode_label} · {','.join(codes)}"
    all_seeds = sorted(
        {(t, c) for seeds in seeds_by_country.values() for t, c in seeds},
        key=lambda x: -x[1],
    )[:25]
    seeds_csv = ", ".join(f"{t}({c})" for t, c in all_seeds)
    common_csv = ", ".join(
        f"{t}[{len(cs)}개국]" for t, cs in common[:20]
    )
    total = sum(len(v) for v in by_country.values())

    url = push_to_notion(
        token=notion_token, db_id=notion_db,
        title=title, date_iso=today, mode_label=mode_label,
        countries=list(by_country.keys()),
        seeds_csv=seeds_csv, common_csv=common_csv,
        video_count=total, by_country=by_country,
    )
    print(f"\n✅ Notion 페이지 생성: {url}")


if __name__ == "__main__":
    main()
