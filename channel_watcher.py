"""channel_watcher.py — 🔖 북마크+🔔 알림 채널의 새 영상 감지 (RSS, 쿼터 0).

genre_store.watch_list() 의 채널을 YouTube RSS 로 폴링 → 새 영상 감지 →
제목 자동 분석 → 알림 문구 생성. 상태는 watch_state.json 에 마지막 본 영상 저장.

GitHub Actions cron / 사장님 PC 에서 실행:
    python channel_watcher.py            # 감지만(콘솔)
    python channel_watcher.py --notify   # 감지 + 카톡 발송
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

import genre_store as G
import tier_lab as T

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_state.json")
_NS = {"a": "http://www.w3.org/2005/Atom",
       "yt": "http://www.youtube.com/xml/schemas/2015",
       "media": "http://search.yahoo.com/mrss/"}


def rss_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def parse_feed(xml_text: str) -> list[dict]:
    """RSS XML → [{video_id, title, published, thumb, channel_id, channel}]."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    cname = root.findtext("a:title", default="", namespaces=_NS)
    for e in root.findall("a:entry", _NS):
        vid = e.findtext("yt:videoId", default="", namespaces=_NS)
        if not vid:
            continue
        thumb = ""
        mt = e.find(".//media:thumbnail", _NS)
        if mt is not None:
            thumb = mt.get("url", "")
        out.append({
            "video_id": vid,
            "title": e.findtext("a:title", default="", namespaces=_NS),
            "published": (e.findtext("a:published", default="", namespaces=_NS) or "")[:10],
            "thumb": thumb,
            "channel_id": e.findtext("yt:channelId", default="", namespaces=_NS),
            "channel": cname,
        })
    return out


def _channel_id_from_url(url: str) -> str:
    m = re.search(r"/channel/(UC[\w-]+)", url or "")
    return m.group(1) if m else ""


def resolve_channel_id(url: str) -> str:
    """URL → channelId. /channel/UC.. 는 즉시, 핸들/영상은 YouTube API 로(키 있을 때)."""
    cid = _channel_id_from_url(url)
    if cid:
        return cid
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend"))
        import youtube_client as yc
        if not yc.has_key():
            return ""
        yt = yc._yt()
        # 핸들
        m = re.search(r"/@([^/?#]+)", url)
        if m:
            r = yt.channels().list(part="id", forHandle=m.group(1)).execute()
            items = r.get("items", [])
            if items:
                return items[0]["id"]
        # 영상 → 채널
        m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url)
        if m:
            r = yt.videos().list(part="snippet", id=m.group(1)).execute()
            items = r.get("items", [])
            if items:
                return items[0]["snippet"]["channelId"]
    except Exception:                   # noqa: BLE001
        pass
    return ""


def resolve_channel_info(url: str) -> tuple[str, str]:
    """URL(영상/채널/핸들) → (channel_id, channel_name). 키 있을 때."""
    cid = resolve_channel_id(url)
    if not cid:
        return "", ""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend"))
        import youtube_client as yc
        if not yc.has_key():
            return cid, ""
        r = yc._yt().channels().list(part="snippet", id=cid).execute()
        items = r.get("items", [])
        return cid, (items[0]["snippet"]["title"] if items else "")
    except Exception:                   # noqa: BLE001
        return cid, ""


def resolve_channel_full(url: str) -> tuple[str, str, str]:
    """URL(영상/채널/핸들) → (channel_id, channel_name, thumb_url).

    thumb_url = 채널 대표 이미지(어떤 채널인지 눈으로 구별용). 확보 우선순위:
      1) RSS(쿼터 0·키 불필요): /channel/UC.. 링크는 **키가 없어도** 채널명 +
         최근 영상 썸네일을 얻는다. → 사장님이 키를 안 넣어도 썸네일이 보임.
      2) API 키가 있으면 채널 로고(아바타)로 보강(RSS 로 못 얻었을 때만).
    핸들(@)·영상 링크는 channel_id 해석에 키가 필요할 수 있다(RSS 는 id 필요).
    """
    cid = resolve_channel_id(url)
    name, thumb = "", ""
    # 1) RSS 우선 — 키 없이도 /channel/ 은 채널명 + 대표 썸네일 확보
    if cid:
        try:
            feed = parse_feed(_fetch(rss_url(cid)))
            if feed:
                name = feed[0].get("channel", "") or name
                thumb = feed[0].get("thumb", "") or thumb
        except Exception:               # noqa: BLE001
            pass
    # 2) 키 있으면 정식 채널명 + 로고로 보강(RSS 로 못 얻은 값만 채움)
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend"))
        import youtube_client as yc
        if cid and yc.has_key():
            r = yc._yt().channels().list(part="snippet", id=cid).execute()
            items = r.get("items", [])
            if items:
                sn = items[0]["snippet"]
                name = sn.get("title", "") or name
                if not thumb:           # RSS 썸네일 없을 때만 로고로
                    th = sn.get("thumbnails", {}) or {}
                    thumb = ((th.get("medium") or th.get("high")
                              or th.get("default") or {}).get("url", ""))
    except Exception:                   # noqa: BLE001
        pass
    return cid, name, thumb


def _video_views(video_ids: list[str]) -> dict[str, int]:
    """영상 ID들 → 현재 조회수 (72시간 결과용)."""
    out: dict[str, int] = {}
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend"))
        import youtube_client as yc
        if not yc.has_key() or not video_ids:
            return out
        yt = yc._yt()
        for k in range(0, len(video_ids), 50):
            r = yt.videos().list(part="statistics", id=",".join(video_ids[k:k + 50])).execute()
            for it in r.get("items", []):
                out[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0) or 0)
    except Exception:                   # noqa: BLE001
        pass
    return out


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"seen": {}}


def _save_state(s: dict) -> None:
    json.dump(s, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def analyze_new_video(v: dict) -> str:
    """새 영상 제목 → 한 줄 자동 분석(공식·구간 추정)."""
    a = T.analyze_title(v.get("title", ""))
    tier = T.tier_of(int(v.get("views", 0) or 0)) if v.get("views") else "신규"
    bits = []
    if a["situation"]:
        bits.append("상황[" + "·".join(a["situation"][:2]) + "]")
    if a["sensory"]:
        bits.append("감각[" + "·".join(a["sensory"][:2]) + "]")
    if a["emojis"]:
        bits.append("이모지" + "".join(a["emojis"][:2]))
    return f"🔍 {' + '.join(bits) or '패턴 약함'} · 길이 {a['length']}자 · 구간 {tier}"


def run_once(notify: bool = False) -> list[dict]:
    """알림 대상 채널을 폴링 → 새 영상 목록 반환(+옵션 카톡 발송)."""
    state = _load_state()
    seen = state.setdefault("seen", {})
    news = []
    targets = G.watch_list() or G.load_exported_watch()   # Actions 는 커밋된 목록 사용
    for w in targets:
        cid = w.get("channel_id") or resolve_channel_id(w["url"])
        if not cid:
            continue
        try:
            entries = parse_feed(_fetch(rss_url(cid)))
        except Exception:               # noqa: BLE001
            continue
        known = set(seen.get(cid, []))
        fresh = [e for e in entries if e["video_id"] not in known]
        # 최초 관측이면 기준선만 저장(폭탄 방지)
        if cid not in seen:
            seen[cid] = [e["video_id"] for e in entries][:15]
            continue
        pend = state.setdefault("pending72", [])
        now_iso = _dt.datetime.utcnow().isoformat()
        for e in fresh:
            e["project"] = w["project"]
            e["analysis"] = analyze_new_video(e)
            news.append(e)
            pend.append({"video_id": e["video_id"], "title": e["title"],
                         "project": e["project"], "detected_at": now_iso, "reported": False})
        seen[cid] = ([e["video_id"] for e in fresh] + seen.get(cid, []))[:15]

    followups = _process_followups(state)   # 72시간 지난 것 성과 집계
    _save_state(state)

    if notify:
        try:
            import kakao_notify
            for e in news:
                kakao_notify.send_to_me(
                    f"📺 [{e['project']}] 새 영상\n{e['title']}\n{e['analysis']}\n"
                    f"▶ https://youtu.be/{e['video_id']}", link=f"https://youtu.be/{e['video_id']}")
            for f in followups:
                kakao_notify.send_to_me(
                    f"📊 72시간 결과 [{f['project']}]\n{f['title']}\n"
                    f"👁 {f['views']:,}회 · 일평균 {f['vpd']:,}회 · {f['verdict']}\n"
                    f"▶ https://youtu.be/{f['video_id']}", link=f"https://youtu.be/{f['video_id']}")
        except Exception as ex:          # noqa: BLE001
            print("카톡 발송 스킵:", ex)
    return news + followups


def _process_followups(state: dict, hours: int = 72) -> list[dict]:
    """감지 후 hours 지난 영상의 현재 조회수 집계 → 결과 목록(중복 방지)."""
    pend = state.setdefault("pending72", [])
    now = _dt.datetime.utcnow()
    due = []
    for p in pend:
        if p.get("reported"):
            continue
        try:
            det = _dt.datetime.fromisoformat(p["detected_at"])
        except (ValueError, KeyError):
            p["reported"] = True
            continue
        if (now - det).total_seconds() >= hours * 3600:
            due.append(p)
    out = []
    if due:
        views_map = _video_views([p["video_id"] for p in due])
        for p in due:
            v = views_map.get(p["video_id"], 0)
            vpd = round(v / max(1, hours / 24))
            verdict = "🔥 잘 먹힘" if vpd >= 5000 else ("👍 무난" if vpd >= 1000 else "😐 반응 약함")
            out.append({**p, "views": v, "vpd": vpd, "verdict": verdict})
            p["reported"] = True
    # 오래된 reported 정리(30일)
    cut = now - _dt.timedelta(days=30)
    state["pending72"] = [p for p in pend if not (
        p.get("reported") and _safe_before(p.get("detected_at"), cut))]
    return out


def _safe_before(iso: str, cut) -> bool:
    try:
        return _dt.datetime.fromisoformat(iso) < cut
    except (ValueError, TypeError):
        return True


if __name__ == "__main__":
    notify = "--notify" in sys.argv
    found = run_once(notify=notify)
    if not found:
        print("새 영상 없음 (또는 기준선 최초 저장).")
    for e in found:
        print(f"[{e['project']}] {e['title']}\n  {e['analysis']}\n  https://youtu.be/{e['video_id']}")
