"""trend_radar.py — 장르 불문 '지금 터지는 제목' 레이더 + 전이 가능 템플릿.

인사이트: 터지는 제목 = [상황(비/눈/여름/초여름/녹음/새벽/드라이브…)] + [장르].
상황 구조는 장르를 초월하므로, 다른 장르에서 터진 제목의 '장르 단어만' 우리 걸로
바꾸면 그대로 쓸 수 있다. → 상황 키워드로 최근 급상승 영상을 찾아 템플릿화.

키 없으면 데모. Streamlit 비의존.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import tier_lab as T

# 장르를 초월하는 '상황' 시드 (계절·날씨·시간·순간)
DEFAULT_SITUATIONS = [
    "비 오는 날", "눈 오는 날", "새벽", "밤", "퇴근길", "드라이브", "카페",
    "초여름", "여름", "가을", "겨울", "봄", "녹음", "장마", "첫눈", "노을", "산책",
]


def _vpd(views: int, published: str) -> float:
    return T.views_per_day(views, published)


def strip_genre_template(title: str, my_genre_word: str = "우리 장르") -> str:
    """제목에서 장르 단어를 {내 장르} 로 치환 → 전이 가능한 템플릿."""
    t = title or ""
    hit = False
    for g in sorted(T.GENRE_WORDS, key=len, reverse=True):
        if g.lower() in t.lower():
            t = re.sub(re.escape(g), f"[{my_genre_word}]", t, flags=re.IGNORECASE)
            hit = True
            break
    if not hit:
        t = t + f" | [{my_genre_word}]"
    return t


def _demo(keywords: list[str]) -> list[dict]:
    base = [
        ("비 오는 날 새벽, 창밖을 보며 듣는 재즈", 420000, "2026-07-10"),
        ("초여름 드라이브에 어울리는 시티팝", 310000, "2026-07-12"),
        ("첫눈 오는 밤, 포근한 로파이", 280000, "2026-07-08"),
        ("퇴근길에 듣는 감성 발라드", 260000, "2026-07-14"),
    ]
    today = _dt.date(2026, 7, 19)
    out = []
    for i, (t, v, d) in enumerate(base):
        out.append({"title": t, "views": v, "published": d, "video_id": f"demo{i}",
                    "channel": "데모 채널", "thumb": "", "keyword": keywords[i % len(keywords)],
                    "vpd": T.views_per_day(v, d, today)})
    return out


def find_surging(keywords: list[str] | None = None, days: int = 14,
                 region: str = "KR", per_kw: int = 6, top: int = 20) -> dict:
    """상황 키워드별 최근 급상승(음악) 영상 → vpd 정렬. 반환 {engine, videos}."""
    keywords = keywords or DEFAULT_SITUATIONS
    try:
        import youtube_client as yc
        if not yc.has_key():
            return {"engine": "demo", "videos": _demo(keywords)}
        yt = yc._yt()
        after = (_dt.datetime.utcnow() - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        seen, vids = set(), []
        for kw in keywords:
            try:
                s = yt.search().list(part="id", q=kw, type="video", order="viewCount",
                                     publishedAfter=after, maxResults=per_kw,
                                     regionCode=region, videoCategoryId="10").execute()
                ids = [it["id"]["videoId"] for it in s.get("items", []) if it["id"].get("videoId")]
                if not ids:
                    continue
                vr = yt.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
                for v in vr.get("items", []):
                    if v["id"] in seen:
                        continue
                    seen.add(v["id"])
                    sn, stt = v["snippet"], v.get("statistics", {})
                    views = int(stt.get("viewCount", 0) or 0)
                    pub = sn["publishedAt"][:10]
                    th = sn.get("thumbnails", {})
                    thumb = next((th[q]["url"] for q in ("high", "medium", "default")
                                  if th.get(q, {}).get("url")), "")
                    vids.append({"title": sn["title"], "views": views, "published": pub,
                                 "video_id": v["id"], "channel": sn.get("channelTitle", ""),
                                 "thumb": thumb, "keyword": kw, "vpd": _vpd(views, pub)})
            except Exception:           # noqa: BLE001
                continue
        vids.sort(key=lambda x: x["vpd"], reverse=True)
        return {"engine": "youtube", "videos": vids[:top]}
    except Exception:                   # noqa: BLE001
        return {"engine": "demo", "videos": _demo(keywords)}


def alert(keywords: list[str] | None = None, notify: bool = False, min_vpd: int = 20000) -> list[dict]:
    """급상승 top 을 카톡 알림(cron 용). min_vpd 이상만."""
    res = find_surging(keywords)
    hot = [v for v in res["videos"] if v.get("vpd", 0) >= min_vpd][:5]
    if notify and hot:
        try:
            import kakao_notify
            for v in hot:
                kakao_notify.send_to_me(
                    f"🌊 지금 터지는 제목 [{v['keyword']}]\n{v['title']}\n"
                    f"👁 {v['views']:,} · 일평균 {int(v['vpd']):,}회\n"
                    f"💡 템플릿: {strip_genre_template(v['title'])}\n"
                    f"▶ https://youtu.be/{v['video_id']}", link=f"https://youtu.be/{v['video_id']}")
        except Exception as e:           # noqa: BLE001
            print("카톡 스킵:", e)
    return hot


if __name__ == "__main__":
    a = alert(notify="--notify" in sys.argv)
    for v in a:
        print(v["vpd"], v["title"], "→", strip_genre_template(v["title"]))
