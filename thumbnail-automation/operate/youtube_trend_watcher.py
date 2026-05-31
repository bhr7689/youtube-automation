import json
import logging
from datetime import datetime, timedelta

from googleapiclient.discovery import build

from core.config import YOUTUBE_API_KEY
from core.store import upsert_channel, upsert_thumbnail, get_conn
from core.utils import url_hash, download_image
from core.config import THUMB_DIR

logger = logging.getLogger(__name__)

CATEGORY_IDS = {"음악": "10", "엔터테인먼트": "24", "사람과블로그": "22", "음식": "26", "교육": "27"}
PEAK_HOURS = {"평일": [(19, 22)], "주말": [(10, 13), (19, 23)]}


def _build_yt():
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY 없음")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def fetch_trending(region="KR", max_results=50):
    yt = _build_yt()
    all_videos = []
    for cat_name, cat_id in CATEGORY_IDS.items():
        try:
            resp = yt.videos().list(part="snippet,statistics,contentDetails",
                chart="mostPopular", regionCode=region, videoCategoryId=cat_id,
                maxResults=max_results, hl="ko").execute()
        except Exception as e:
            continue
        for item in resp.get("items", []):
            snip = item["snippet"]
            stats = item.get("statistics", {})
            thumbs = snip.get("thumbnails", {})
            url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {}).get("url", "")
            all_videos.append({"video_id": item["id"], "category": cat_name,
                "title": snip.get("title", ""), "channel_id": snip.get("channelId", ""),
                "channel_name": snip.get("channelTitle", ""), "thumbnail_url": url,
                "view_count": int(stats.get("viewCount", 0)), "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "published_at": snip.get("publishedAt", ""), "is_trending": 1})
    return all_videos


def save_trending_thumbnails(videos, download=True):
    now = datetime.utcnow().isoformat()
    saved = 0
    for v in videos:
        upsert_channel({"channel_id": v["channel_id"], "name": v["channel_name"],
            "category": f"급상승_{v['category']}", "subscriber_cnt": 0,
            "avg_view_cnt": v["view_count"], "avg_ctr_est": 0.0, "country": "KR", "collected_at": now})
        thumb_id = "th_" + url_hash(v["video_id"])
        local_path = None
        if download and v["thumbnail_url"]:
            dest = THUMB_DIR / "trending"
            dest.mkdir(exist_ok=True)
            p = download_image(v["thumbnail_url"], dest, thumb_id + ".jpg")
            local_path = str(p) if p else None
        upsert_thumbnail({"thumb_id": thumb_id, "channel_id": v["channel_id"],
            "video_id": v["video_id"], "title": v["title"], "image_url": v["thumbnail_url"],
            "local_path": local_path, "view_count": v["view_count"], "like_count": v["like_count"],
            "comment_count": v["comment_count"], "is_viral": 1,
            "published_at": v["published_at"], "collected_at": now})
        saved += 1
    return saved


def detect_new_uploads(channel_ids, since_hours=24):
    yt = _build_yt()
    cutoff = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat() + "Z"
    new_vids = []
    for ch_id in channel_ids:
        try:
            resp = yt.search().list(channelId=ch_id, type="video", part="snippet",
                maxResults=10, order="date", publishedAfter=cutoff).execute()
        except Exception as e:
            continue
        for item in resp.get("items", []):
            snip = item["snippet"]
            thumbs = snip.get("thumbnails", {})
            url = (thumbs.get("maxres") or thumbs.get("high") or {}).get("url", "")
            new_vids.append({"video_id": item["id"]["videoId"], "channel_id": ch_id,
                "channel_name": snip.get("channelTitle", ""), "title": snip.get("title", ""),
                "thumbnail_url": url, "published_at": snip.get("publishedAt", ""),
                "view_count": 0, "like_count": 0, "comment_count": 0, "is_trending": 0})
    return new_vids


def get_upload_timing_advice():
    now_kst = datetime.utcnow().replace(tzinfo=None)
    hour = (now_kst.hour + 9) % 24
    weekday = now_kst.weekday()
    is_weekend = weekday >= 5
    peaks = PEAK_HOURS["주말"] if is_weekend else PEAK_HOURS["평일"]
    in_peak = any(start <= hour < end for start, end in peaks)
    next_peak = None
    for start, end in peaks:
        if hour < start:
            next_peak = start
            break
    if next_peak is None:
        next_day_peaks = PEAK_HOURS["주말"] if (weekday + 1) >= 5 else PEAK_HOURS["평일"]
        next_peak = next_day_peaks[0][0]
    return {"current_hour_kst": hour, "is_peak": in_peak, "is_weekend": is_weekend,
        "next_peak_hour": next_peak,
        "advice": "🟢 지금이 피크 타임! 바로 업로드하세요." if in_peak
            else f"🟡 피크 타임은 {next_peak}시입니다. 업로드를 예약하세요.",
        "peak_hours": peaks}


def extract_trend_keywords(limit=50):
    import re
    from collections import Counter
    with get_conn() as conn:
        rows = conn.execute("SELECT title FROM thumbnails WHERE is_viral=1 ORDER BY view_count DESC LIMIT ?", (limit,)).fetchall()
    words = Counter()
    stop = {"the","a","an","이","그","저","은","는","이","가","을","를","의","와","과","도"}
    for row in rows:
        for w in re.split(r'[\s\|\-\[\]()#]+', row["title"] or ""):
            w = w.strip().lower()
            if len(w) >= 2 and w not in stop:
                words[w] += 1
    return [{"keyword": k, "count": v} for k, v in words.most_common(20)]
