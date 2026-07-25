"""viral_channels.py — 🔖 폴더 채널 북마크 + 🔔 새 영상 알림 + 새 1만+ 자동수집.

폴더 안 영상들의 채널을 북마크하면:
  · 그 채널의 **새 영상**을 RSS(쿼터 0)로 감지해 🔔 알림으로 쌓고
  · 그 채널의 최근 영상 중 **1만+** 를 자동으로 수집(로컬)한다.
알림은 사장님이 보고 끄면(dismiss) 삭제된다.

저장소: viral_channels.json (gitignore — 이 PC 로컬. 앱을 열 때 자동 확인하므로
GitHub Actions·git 충돌 없이 '자동'으로 동작).

채널 해석·RSS·조회수는 channel_watcher(W) 를 재활용. Streamlit 비의존.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

import channel_watcher as W
import viral_lab as V

_HERE = os.path.dirname(os.path.abspath(__file__))
CH_PATH = os.path.join(_HERE, "viral_channels.json")


def channel_url(cid: str) -> str:
    return f"https://www.youtube.com/channel/{cid}" if cid else ""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# ── 저장소 ───────────────────────────────────────────────────
def _load() -> dict:
    if os.path.exists(CH_PATH):
        try:
            with open(CH_PATH, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("channels", [])
                d.setdefault("alerts", [])
                d.setdefault("collected", [])
                return d
        except Exception:  # noqa: BLE001
            pass
    return {"channels": [], "alerts": [], "collected": [], "updated": ""}


def _save(store: dict) -> None:
    store["updated"] = _now()
    with open(CH_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


# ── 북마크 ───────────────────────────────────────────────────
def list_channels() -> list[dict]:
    return _load()["channels"]


def get_channel(cid: str) -> dict | None:
    return next((c for c in _load()["channels"] if c.get("channel_id") == cid), None)


def is_bookmarked(cid: str) -> bool:
    return get_channel(cid) is not None


def bookmark(cid: str, title: str = "", url: str = "") -> dict:
    """채널 북마크(중복 방지). 첫 확인 때 기존 영상은 알림 안 뜨도록 baseline 미설정."""
    store = _load()
    ch = next((c for c in store["channels"] if c.get("channel_id") == cid), None)
    if ch:
        if title:
            ch["title"] = title
        _save(store)
        return ch
    ch = {"channel_id": cid, "title": title or cid, "url": url or channel_url(cid),
          "added": _now(), "last_video": "", "last_checked": ""}
    store["channels"].append(ch)
    _save(store)
    return ch


def unbookmark(cid: str) -> bool:
    store = _load()
    before = len(store["channels"])
    store["channels"] = [c for c in store["channels"] if c.get("channel_id") != cid]
    _save(store)
    return len(store["channels"]) < before


# ── 폴더/표본 안 채널 목록 ───────────────────────────────────
def channels_in_videos(videos: list[dict]) -> list[dict]:
    """영상 리스트 → 고유 채널 [{channel_id, title, url, count, bookmarked}] (영상 많은 순)."""
    marked = {c["channel_id"] for c in list_channels()}
    by: dict[str, dict] = {}
    for v in videos or []:
        cid = v.get("channel_id") or ""
        if not cid:
            continue
        row = by.setdefault(cid, {"channel_id": cid,
                                  "title": v.get("channel_title") or cid,
                                  "url": channel_url(cid), "count": 0})
        row["count"] += 1
        if v.get("channel_title"):
            row["title"] = v["channel_title"]
    out = list(by.values())
    for r in out:
        r["bookmarked"] = r["channel_id"] in marked
    return sorted(out, key=lambda r: r["count"], reverse=True)


# ── 🔔 새 영상 감지 + 🔟 새 1만+ 자동수집 ────────────────────
def check_new(min_views: int = V.MIN_VIEWS, per_channel: int = 15) -> dict:
    """북마크 채널을 RSS 로 폴링 → 새 영상 알림 + 최근 영상 중 1만+ 자동수집.

    반환: {checked, new_alerts, collected, need_key}
      new_alerts = 새로 뜬 알림 수
      collected  = 새로 수집된 1만+ 수
      need_key   = 조회수 확인(1만+ 필터)에 키가 없어 수집 못 한 경우 True
    """
    store = _load()
    checked = new_alerts = collected = 0
    need_key = False
    have_key = V.has_youtube_key()

    for ch in store["channels"]:
        cid = ch.get("channel_id")
        if not cid:
            continue
        try:
            feed = W.parse_feed(W._fetch(W.rss_url(cid)))
        except Exception:  # noqa: BLE001
            continue
        if not feed:
            continue
        checked += 1
        newest = feed[0]["video_id"]
        last = ch.get("last_video", "")

        # 최근 영상 조회수 → 1만+ 자동수집 (키 필요)
        recent = feed[:per_channel]
        if have_key:
            views = W._video_views([e["video_id"] for e in recent])
            have_ids = {c["video_id"] for c in store["collected"]}
            for e in recent:
                v = views.get(e["video_id"])
                if v is not None and v >= min_views and e["video_id"] not in have_ids:
                    store["collected"].insert(0, V.normalize({
                        **e, "views": v, "channel_id": cid,
                        "channel_title": ch.get("title", "")}))
                    collected += 1
        else:
            need_key = True

        # 새 영상 알림 (baseline 이후 올라온 것만)
        if not last:                     # 첫 확인 = 기준선만, 알림 X (기존 영상 홍수 방지)
            ch["last_video"] = newest
            ch["last_checked"] = _now()
            continue
        alert_ids = {a["video_id"] for a in store["alerts"]}
        for e in feed:
            if e["video_id"] == last:
                break
            if e["video_id"] in alert_ids:
                continue
            store["alerts"].insert(0, {
                "video_id": e["video_id"], "channel_id": cid,
                "channel": ch.get("title", "") or e.get("channel", ""),
                "title": e.get("title", ""), "thumb": e.get("thumb", ""),
                "published": e.get("published", ""),
                "url": f"https://www.youtube.com/watch?v={e['video_id']}",
                "added_at": _now()})
            new_alerts += 1
        ch["last_video"] = newest
        ch["last_checked"] = _now()

    store["collected"] = store["collected"][:1000]
    _save(store)
    return {"checked": checked, "new_alerts": new_alerts,
            "collected": collected, "need_key": need_key}


# ── 알림 ─────────────────────────────────────────────────────
def alerts() -> list[dict]:
    return _load()["alerts"]


def alert_count() -> int:
    return len(_load()["alerts"])


def dismiss_alert(video_id: str) -> bool:
    store = _load()
    before = len(store["alerts"])
    store["alerts"] = [a for a in store["alerts"] if a.get("video_id") != video_id]
    _save(store)
    return len(store["alerts"]) < before


def clear_alerts() -> int:
    store = _load()
    n = len(store["alerts"])
    store["alerts"] = []
    _save(store)
    return n


def collected_hits() -> list[dict]:
    """북마크 채널에서 자동수집된 1만+ (조회수순)."""
    return sorted(_load()["collected"], key=lambda v: v.get("views", 0), reverse=True)


if __name__ == "__main__":  # 자기검증 (임시 파일, 네트워크 없이 로직만)
    import tempfile
    CH_PATH = os.path.join(tempfile.gettempdir(), "vc_selftest.json")
    if os.path.exists(CH_PATH):
        os.remove(CH_PATH)
    vids = [{"channel_id": "UC_a", "channel_title": "새벽재즈", "title": "t1"},
            {"channel_id": "UC_a", "channel_title": "새벽재즈", "title": "t2"},
            {"channel_id": "UC_b", "channel_title": "카페BGM", "title": "t3"}]
    rows = channels_in_videos(vids)
    assert rows[0]["channel_id"] == "UC_a" and rows[0]["count"] == 2, rows
    assert all(not r["bookmarked"] for r in rows)
    bookmark("UC_a", "새벽재즈")
    assert is_bookmarked("UC_a") and not is_bookmarked("UC_b")
    assert channels_in_videos(vids)[0]["bookmarked"] is True
    # 알림 dismiss
    st = _load(); st["alerts"] = [{"video_id": "v1", "title": "새 영상"}]; _save(st)
    assert alert_count() == 1
    assert dismiss_alert("v1") and alert_count() == 0
    assert unbookmark("UC_a") and not is_bookmarked("UC_a")
    print("채널:", [(r["title"], r["count"]) for r in rows])
    print("self-test OK")
