"""YouTube Data API v3 래퍼 — 검색 + 배수(multiplier) 정확 계산.

원칙: 공식 API 만 사용(스크래핑 X). 조회수·구독자·업로드시각은 실제 숫자.
'배수' 는 영상 조회수 ÷ 채널 최근 평균 조회수(중앙값) 로 우리가 직접 계산 → 정확.

키(YOUTUBE_API_KEY)가 없으면 예외 대신 상위(main.py)가 mock 으로 폴백한다.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timezone
from functools import lru_cache

import isodate

MAX_IDS_PER_REQUEST = 50
# 채널 평균 계산 시 표본 (최근 영상 N개). 중앙값이라 이상치(초대박 1편)에 강함.
CHANNEL_SAMPLE = 15


def build_client(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _published_after(period: str) -> str | None:
    """기간 키 → RFC3339 publishedAfter. '전체'면 None."""
    from datetime import timedelta
    days = {
        "1d": 1, "3d": 3, "1w": 7, "1m": 30,
        "3m": 90, "6m": 180, "1y": 365,
    }.get(period)
    if not days:
        return None
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _duration_seconds(iso_dur: str) -> int:
    try:
        return int(isodate.parse_duration(iso_dur).total_seconds())
    except Exception:
        return 0


def _fmt_duration(sec: int) -> str:
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def _hours_since(published: str) -> float:
    try:
        delta = datetime.now(timezone.utc) - _iso_to_dt(published)
        return max(delta.total_seconds() / 3600.0, 1.0)
    except Exception:
        return 1.0


class YouTubeClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.yt = build_client(api_key)
        self._channel_avg_cache: dict[str, float] = {}

    # ---- 검색 -------------------------------------------------------------
    def search(self, query: str, *, period="all", order="viewCount",
               video_format="any", max_results=100, region=None,
               language=None) -> list[dict]:
        """키워드 검색 → 영상 상세 + 배수 계산된 카드 리스트."""
        # 1) search.list 로 video id 수집
        ids = self._search_ids(query, period, order, video_format,
                               max_results, region, language)
        if not ids:
            return []
        # 2) videos.list 로 통계·길이·채널
        details = self._video_details(ids)
        # 3) 채널 평균 조회수(배수 분모) 계산
        channel_ids = list({d["snippet"]["channelId"] for d in details})
        chan_stats = self._channel_stats(channel_ids)
        self._compute_channel_averages(channel_ids, chan_stats)
        # 4) 형식 필터(쇼츠/롱폼) — 길이로 판정
        cards = [self._to_card(d, chan_stats) for d in details]
        if video_format == "shorts":
            cards = [c for c in cards if c["duration_sec"] <= 61]
        elif video_format == "long":
            cards = [c for c in cards if c["duration_sec"] > 61]
        return cards

    def _search_ids(self, query, period, order, video_format,
                    max_results, region, language) -> list[str]:
        published_after = _published_after(period)
        ids, seen = [], set()
        page_token = None
        want = min(max_results, 500)
        # 쇼츠만 원할 땐 넉넉히 받아서 길이로 거른다.
        fetch_target = want * 2 if video_format == "shorts" else want
        while len(ids) < fetch_target:
            page_size = min(50, fetch_target - len(ids))
            params = dict(part="id", q=query, type="video", order=order,
                          maxResults=page_size, pageToken=page_token)
            if published_after:
                params["publishedAfter"] = published_after
            if region:
                params["regionCode"] = region
            if language:
                params["relevanceLanguage"] = language
            if video_format == "shorts":
                params["videoDuration"] = "short"   # <4분 (API 한계, 이후 61초로 재필터)
            elif video_format == "long":
                params["videoDuration"] = "long"    # >20분
            resp = self.yt.search().list(**params).execute()
            items = resp.get("items", [])
            for it in items:
                vid = it.get("id", {}).get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    ids.append(vid)
            page_token = resp.get("nextPageToken")
            if not page_token or not items:
                break
        return ids[: want if video_format != "shorts" else fetch_target]

    def _video_details(self, ids: list[str]) -> list[dict]:
        out = []
        for chunk in _chunks(ids, MAX_IDS_PER_REQUEST):
            resp = self.yt.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(chunk), maxResults=MAX_IDS_PER_REQUEST,
            ).execute()
            out.extend(resp.get("items", []))
        return out

    def _channel_stats(self, channel_ids: list[str]) -> dict[str, dict]:
        out = {}
        for chunk in _chunks(channel_ids, MAX_IDS_PER_REQUEST):
            resp = self.yt.channels().list(
                part="snippet,statistics,contentDetails",
                id=",".join(chunk), maxResults=MAX_IDS_PER_REQUEST,
            ).execute()
            for it in resp.get("items", []):
                out[it["id"]] = it
        return out

    # ---- 배수(정확) -------------------------------------------------------
    def _compute_channel_averages(self, channel_ids, chan_stats):
        """채널별 최근 영상 중앙값 조회수 = 배수 분모. 채널당 1회만 조회(쿼터 절약)."""
        for cid in channel_ids:
            if cid in self._channel_avg_cache:
                continue
            avg = self._recent_median_views(cid, chan_stats.get(cid))
            self._channel_avg_cache[cid] = avg

    def _recent_median_views(self, channel_id, chan_item) -> float:
        """업로드 재생목록에서 최근 N개의 중앙값 조회수. 실패 시 채널 평균으로 폴백."""
        try:
            uploads = (chan_item or {}).get("contentDetails", {}) \
                .get("relatedPlaylists", {}).get("uploads")
            if uploads:
                pl = self.yt.playlistItems().list(
                    part="contentDetails", playlistId=uploads,
                    maxResults=CHANNEL_SAMPLE).execute()
                vids = [i["contentDetails"]["videoId"]
                        for i in pl.get("items", [])]
                if vids:
                    dets = self._video_details(vids)
                    views = [int(d["statistics"].get("viewCount", 0))
                             for d in dets if "statistics" in d]
                    views = [v for v in views if v > 0]
                    if views:
                        return float(statistics.median(views))
        except Exception:
            pass
        # 폴백: 총조회수 / 영상수
        try:
            st = (chan_item or {}).get("statistics", {})
            vc = int(st.get("videoCount", 0))
            tv = int(st.get("viewCount", 0))
            if vc > 0:
                return tv / vc
        except Exception:
            pass
        return 0.0

    # ---- 카드 변환 --------------------------------------------------------
    def _to_card(self, d: dict, chan_stats: dict) -> dict:
        sn, st = d["snippet"], d.get("statistics", {})
        cd = d.get("contentDetails", {})
        views = int(st.get("viewCount", 0))
        cid = sn["channelId"]
        chan = chan_stats.get(cid, {})
        subs = int(chan.get("statistics", {}).get("subscriberCount", 0) or 0)
        avg = self._channel_avg_cache.get(cid, 0.0)
        dur = _duration_seconds(cd.get("duration", ""))
        hours = _hours_since(sn.get("publishedAt", ""))
        mult = round(views / avg, 1) if avg > 0 else None
        sub_mult = round(views / subs, 1) if subs > 0 else None
        return {
            "video_id": d["id"],
            "title": sn.get("title", ""),
            "channel_id": cid,
            "channel_title": sn.get("channelTitle", ""),
            "thumbnail": (sn.get("thumbnails", {}).get("medium")
                          or sn.get("thumbnails", {}).get("default") or {}).get("url", ""),
            "views": views,
            "likes": int(st.get("likeCount", 0) or 0),
            "comments": int(st.get("commentCount", 0) or 0),
            "subscribers": subs,
            "published_at": sn.get("publishedAt", ""),
            "duration_sec": dur,
            "duration": _fmt_duration(dur),
            "is_short": dur <= 61,
            "multiplier": mult,             # 조회수/채널평균 (정확)
            "sub_multiplier": sub_mult,     # 조회수/구독자 (정확)
            "vph": round(views / hours, 1), # 시간당 조회수 (정확)
            "url": f"https://youtube.com/watch?v={d['id']}",
        }

    # ---- 키워드 검색량 추정 (🟠 추정) ------------------------------------
    def keyword_estimate(self, query: str) -> dict:
        """YouTube 검색 결과 총량 + 상위 조회수 합으로 관심도를 '추정'.
        주의: 이건 추정치임(YouTube 는 검색량을 공개 안 함)."""
        try:
            resp = self.yt.search().list(
                part="id", q=query, type="video",
                order="viewCount", maxResults=10).execute()
            total = resp.get("pageInfo", {}).get("totalResults", 0)
            ids = [i["id"]["videoId"] for i in resp.get("items", [])
                   if i.get("id", {}).get("videoId")]
            dets = self._video_details(ids) if ids else []
            top_views = [int(x["statistics"].get("viewCount", 0)) for x in dets]
            demand = int(sum(top_views) / max(len(top_views), 1)) if top_views else 0
            return {
                "query": query,
                "total_results_estimate": total,
                "avg_top_views": demand,
                "note": "추정치 — YouTube는 검색량을 공개하지 않습니다.",
                "is_estimate": True,
            }
        except Exception as e:
            return {"query": query, "error": str(e), "is_estimate": True}


def relative_time_ko(published: str) -> str:
    """'2일 전' 같은 한국어 상대시간."""
    try:
        delta = datetime.now(timezone.utc) - _iso_to_dt(published)
        days = delta.days
        if days >= 365:
            return f"{days // 365}년 전"
        if days >= 30:
            return f"{days // 30}달 전"
        if days >= 7:
            return f"{days // 7}주 전"
        if days >= 1:
            return f"{days}일 전"
        hours = int(delta.total_seconds() // 3600)
        if hours >= 1:
            return f"{hours}시간 전"
        return "방금"
    except Exception:
        return ""
