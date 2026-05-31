import logging
import re
from datetime import datetime

from googleapiclient.discovery import build

from core.config import YOUTUBE_API_KEY, MAX_CHANNELS_PER_CATEGORY, MAX_VIDEOS_PER_CHANNEL
from core.store import init_db, upsert_channel, upsert_thumbnail, list_channels
from core.utils import new_id, url_hash, download_image
from core.config import THUMB_DIR

logger = logging.getLogger(__name__)

SEARCH_KEYWORDS = [
    "트로트 메들리",
    "트로트 플레이리스트",
    "트로트 모음",
    "효도 트로트 메들리",
    "트로트 인기곡 모음",
    "trot medley",
    "trot playlist",
    "Korean trot playlist",
    "Korean trot best songs",
    "K-trot medley",
    "suno trot",
    "AI trot music",
    "AI 트로트",
]


def _build_yt():
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY 가 .env에 없습니다.")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def search_channels(keywords=None, max_per_keyword=10):
    yt = _build_yt()
    keywords = keywords or SEARCH_KEYWORDS
    seen = set()
    results = []
    for kw in keywords:
        try:
            resp = yt.search().list(q=kw, type="channel", part="snippet",
                maxResults=max_per_keyword, relevanceLanguage="ko", regionCode="KR").execute()
        except Exception as e:
            logger.warning("검색 실패 [%s]: %s", kw, e)
            continue
        for item in resp.get("items", []):
            ch_id = item["snippet"]["channelId"]
            if ch_id in seen:
                continue
            seen.add(ch_id)
            results.append({"channel_id": ch_id, "name": item["snippet"]["channelTitle"],
                "description": item["snippet"].get("description", ""),
                "thumbnail_url": item["snippet"]["thumbnails"].get("default", {}).get("url", ""),
                "matched_keyword": kw})
    results = _enrich_channel_stats(yt, results)
    return results


def _enrich_channel_stats(yt, channels):
    ids = [c["channel_id"] for c in channels]
    enriched = {c["channel_id"]: c for c in channels}
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        try:
            resp = yt.channels().list(id=",".join(batch), part="statistics,snippet").execute()
        except Exception as e:
            continue
        for item in resp.get("items", []):
            cid = item["id"]
            stats = item.get("statistics", {})
            if cid in enriched:
                enriched[cid]["subscriber_cnt"] = int(stats.get("subscriberCount", 0))
                enriched[cid]["video_cnt"] = int(stats.get("videoCount", 0))
                enriched[cid]["total_views"] = int(stats.get("viewCount", 0))
                enriched[cid]["country"] = item["snippet"].get("country", "")
    return list(enriched.values())


def save_selected_channels(channels):
    now = datetime.utcnow().isoformat()
    for ch in channels:
        upsert_channel({"channel_id": ch["channel_id"], "name": ch["name"],
            "category": ch.get("matched_keyword", ""),
            "subscriber_cnt": ch.get("subscriber_cnt", 0),
            "avg_view_cnt": ch.get("total_views", 0),
            "avg_ctr_est": 0.0, "country": ch.get("country", ""), "collected_at": now})


def collect_thumbnails(channel_ids, max_videos=MAX_VIDEOS_PER_CHANNEL, download_images=True):
    yt = _build_yt()
    total = 0
    for ch_id in channel_ids:
        videos = _fetch_videos(yt, ch_id, max_videos)
        for v in videos:
            thumb_id = "th_" + url_hash(v["video_id"])
            local_path = None
            if download_images and v["thumbnail_url"]:
                path = download_image(v["thumbnail_url"], THUMB_DIR, thumb_id + ".jpg")
                local_path = str(path) if path else None
            upsert_thumbnail({"thumb_id": thumb_id, "channel_id": ch_id,
                "video_id": v["video_id"], "title": v["title"],
                "image_url": v["thumbnail_url"], "local_path": local_path,
                "view_count": v.get("view_count", 0), "like_count": v.get("like_count", 0),
                "comment_count": v.get("comment_count", 0),
                "is_viral": 1 if v.get("view_count", 0) >= 100_000 else 0,
                "published_at": v.get("published_at", ""),
                "collected_at": datetime.utcnow().isoformat()})
            total += 1
    return total


def _fetch_videos(yt, channel_id, max_videos):
    videos = []
    page_token = None
    while len(videos) < max_videos:
        limit = min(50, max_videos - len(videos))
        try:
            resp = yt.search().list(channelId=channel_id, type="video", part="snippet",
                maxResults=limit, order="viewCount", pageToken=page_token).execute()
        except Exception as e:
            break
        items = resp.get("items", [])
        if not items:
            break
        vid_ids = [i["id"]["videoId"] for i in items]
        stats = _fetch_video_stats(yt, vid_ids)
        for item in items:
            vid_id = item["id"]["videoId"]
            snip = item["snippet"]
            thumbs = snip.get("thumbnails", {})
            url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
            st = stats.get(vid_id, {})
            videos.append({"video_id": vid_id, "title": snip.get("title", ""),
                "thumbnail_url": url, "published_at": snip.get("publishedAt", ""),
                "view_count": st.get("viewCount", 0), "like_count": st.get("likeCount", 0),
                "comment_count": st.get("commentCount", 0)})
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return videos


def _fetch_video_stats(yt, video_ids):
    if not video_ids:
        return {}
    try:
        resp = yt.videos().list(id=",".join(video_ids), part="statistics").execute()
    except Exception:
        return {}
    out = {}
    for item in resp.get("items", []):
        s = item.get("statistics", {})
        out[item["id"]] = {"viewCount": int(s.get("viewCount", 0)),
            "likeCount": int(s.get("likeCount", 0)), "commentCount": int(s.get("commentCount", 0))}
    return out
