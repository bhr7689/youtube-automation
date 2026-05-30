"""
매일 GitHub Actions에서 자동 실행되는 레퍼런스 채널 수집 스크립트.

수집 결과:
  ref_data/latest.json   — 가장 최근 전체 데이터 (앱에서 표시)
  ref_data/history.json  — 최근 30일 요약 (조회수 추이용)
"""

import json
import os
import pathlib
import sys
from datetime import datetime

API_KEY   = os.environ.get("YOUTUBE_API_KEY", "")
REF_FILE  = pathlib.Path("reference_channels.json")
DATA_DIR  = pathlib.Path("ref_data")
DATA_DIR.mkdir(exist_ok=True)


def fetch_channel_latest(youtube, channel_id: str, max_videos: int = 10) -> list[dict]:
    try:
        s = youtube.search().list(
            part="id", channelId=channel_id,
            order="date", type="video", maxResults=max_videos,
        ).execute()
        vid_ids = [it["id"]["videoId"] for it in s.get("items", [])]
        if not vid_ids:
            return []
        v = youtube.videos().list(
            part="snippet,statistics",
            id=",".join(vid_ids),
        ).execute()
        rows = []
        for item in v.get("items", []):
            snip  = item.get("snippet", {})
            stats = item.get("statistics", {})
            rows.append({
                "video_id":      item["id"],
                "title":         snip.get("title", ""),
                "thumbnail":     (snip.get("thumbnails") or {}).get("medium", {}).get("url", ""),
                "published_at":  snip.get("publishedAt", "")[:16].replace("T", " "),
                "view_count":    int(stats.get("viewCount")    or 0),
                "like_count":    int(stats.get("likeCount")    or 0),
                "comment_count": int(stats.get("commentCount") or 0),
                "video_url":     f"https://www.youtube.com/watch?v={item['id']}",
            })
        return rows
    except Exception as e:
        print(f"  ⚠️  {channel_id} 수집 실패: {e}")
        return []


def main() -> None:
    if not API_KEY:
        print("❌ YOUTUBE_API_KEY 환경변수 없음. GitHub Secrets에 등록했는지 확인하세요.")
        sys.exit(1)

    if not REF_FILE.exists():
        print("reference_channels.json 없음 — 아직 저장된 채널이 없습니다.")
        return

    channels: list[dict] = json.loads(REF_FILE.read_text(encoding="utf-8"))
    if not channels:
        print("저장된 채널 없음.")
        return

    from googleapiclient.discovery import build  # type: ignore
    youtube = build("youtube", "v3", developerKey=API_KEY)

    today   = datetime.utcnow().strftime("%Y-%m-%d")
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # ── 전체 채널 수집 ──────────────────────────────────────
    result: dict = {"collected_at": now_str, "channels": {}}
    for ch in channels:
        cid = ch["channel_id"]
        print(f"  → {ch['channel_title']} ({ch['category']})")
        videos = fetch_channel_latest(youtube, cid)
        result["channels"][cid] = {
            "channel_title": ch["channel_title"],
            "category":      ch["category"],
            "added_at":      ch.get("added_at", ""),
            "videos":        videos,
        }
        print(f"     영상 {len(videos)}개 수집 완료")

    # ── latest.json 저장 ────────────────────────────────────
    latest_file = DATA_DIR / "latest.json"
    latest_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ latest.json 저장 완료")

    # ── history.json 업데이트 (최근 30일) ──────────────────
    hist_file = DATA_DIR / "history.json"
    history: list[dict] = []
    if hist_file.exists():
        try:
            history = json.loads(hist_file.read_text(encoding="utf-8"))
        except Exception:
            history = []

    # 오늘 데이터 교체
    today_summary = {
        cid: {
            "channel_title": data["channel_title"],
            "category":      data["category"],
            "latest_views":  data["videos"][0]["view_count"] if data["videos"] else 0,
            "latest_title":  data["videos"][0]["title"]      if data["videos"] else "",
            "video_count":   len(data["videos"]),
        }
        for cid, data in result["channels"].items()
    }
    history = [h for h in history if h.get("date") != today]
    history.append({"date": today, "summary": today_summary})
    history = sorted(history, key=lambda x: x["date"])[-30:]  # 최근 30일만 유지

    hist_file.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ history.json 업데이트 완료 (보관 {len(history)}일치)")
    print(f"\n🎉 전체 완료: {len(channels)}개 채널 수집 ({now_str})")


if __name__ == "__main__":
    main()
