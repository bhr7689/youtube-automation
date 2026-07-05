"""데모 데이터 — YOUTUBE_API_KEY 가 없을 때 화면을 시현하기 위한 가짜 데이터.

실제 키를 넣으면 youtube_api.py 의 실데이터로 자동 교체된다.
카드 구조는 youtube_api._to_card() 와 동일해야 프론트가 동일하게 렌더한다.
시안(Gordon Ramsay / Shark Tank 계열)과 톤을 맞춤. is_estimate 로 데모임을 표시.
"""
from __future__ import annotations

import hashlib
import random

# 시안에 나온 느낌의 소스들 (해외 예능/리얼리티 쇼츠)
_SEED = [
    ("Smartest hair invention on Shark Tank !?", "Pitch Reality", 140_000_000, 53, 3, True, 38.1),
    ("The Future of Panties | Shark Tank US", "painfulset", 120_000_000, 55, 400, False, 12.4),
    ("They Trashed Him on Shark Tank, But This...", "TuxMotivation", 96_380_000, 48, 400, False, 9.2),
    ("Gordon Ramsay's Eggs", "Nick DiGiovanni", 43_067_000, 59, 2, False, 6.1),
    ("Gordon Ramsay Was Not Ready for This", "FoundOnDash", 160_000_000, 31, 2, True, 41.0),
    ("Gordon Gave The Owner A BRUTAL Review", "Blaze", 43_724_000, 59, 1, False, 7.8),
    ("Gordon Ramsay's Son Hates His Scrambled Eggs", "UNFAZED", 26_329_000, 28, 14, False, 4.3),
    ("Gordon Ramsay Fooled Everyone Here", "MoneyMoves", 21_316_000, 18, 2, False, 3.9),
    ("This Is Why I Love Gordon Ramsay", "ZESTY", 14_203_000, 55, 2, False, 3.1),
    ("How Much Gordon Ramsay Makes!", "Mark Tilbury", 13_956_000, 22, 2, False, 2.8),
    ("Young Chef Shocks Gordon Ramsay With Skill", "Bimbo", 11_328_000, 45, 2, False, 2.5),
    ("Gordon Ramsay Rizzes up contestant in Hell's", "Chefs Vault", 11_084_000, 53, 2, False, 2.2),
    ("Gordon Ramsay Joins Squid Game", "Team Maguire", 10_242_000, 42, 7, False, 5.4),
    ("Most Addictive Chiller EVER Seen on Shark Tank", "Wealth Opti", 86_930_000, 41, 8, True, 18.7),
    ("This Product Is ADDICTIVE | Shark Tank", "Wealth Opti", 86_486_000, 44, 7, True, 15.3),
    ("Little Girl's Lemonade Melts the Sharks' Hearts", "Long Lost Family", 52_100_000, 58, 12, False, 22.0),
    ("A Son Reunites With His Mother After 40 Years", "Humans of NY", 33_400_000, 60, 5, False, 8.9),
    ("The Dodo: A Dog Waits Every Day at the Station", "The Dodo", 47_800_000, 39, 3, False, 11.2),
    ("Undercover Boss Cries With His Employee", "CBS", 19_200_000, 50, 6, False, 3.4),
    ("Elderly Man Sings and the Judges Cry", "Got Talent Global", 78_500_000, 57, 9, False, 27.5),
]

_CHANNELS = {
    "Pitch Reality": 3_670_000,
    "The Dodo": 12_400_000,
    "Got Talent Global": 30_100_000,
    "Long Lost Family": 2_360_000,
    "Humans of NY": 4_010_000,
}


def _vid_id(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()[:11]


def _thumb(idx: int) -> str:
    # 색 블록 SVG data URI — 외부 이미지 없이 카드가 채워지게.
    palette = ["#7c3aed", "#db2777", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444"]
    c = palette[idx % len(palette)]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180'>"
           f"<rect width='320' height='180' fill='{c}'/>"
           f"<circle cx='160' cy='90' r='34' fill='white' opacity='0.25'/>"
           f"<polygon points='150,72 150,108 182,90' fill='white' opacity='0.9'/></svg>")
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def mock_search(query: str = "", video_format: str = "any",
                max_results: int = 100) -> list[dict]:
    rng = random.Random(query or "seed")
    cards = []
    for idx, (title, chan, views, dur, days, registered, mult) in enumerate(_SEED):
        subs = _CHANNELS.get(chan, rng.randint(200_000, 6_000_000))
        published = _days_ago_iso(days)
        card = {
            "video_id": _vid_id(title),
            "title": title,
            "channel_id": "UC" + _vid_id(chan),
            "channel_title": chan,
            "thumbnail": _thumb(idx),
            "views": views,
            "likes": int(views * rng.uniform(0.02, 0.06)),
            "comments": int(views * rng.uniform(0.001, 0.004)),
            "subscribers": subs,
            "published_at": published,
            "duration_sec": dur,
            "duration": f"{dur // 60}:{dur % 60:02d}",
            "is_short": dur <= 61,
            "multiplier": mult,
            "sub_multiplier": round(views / subs, 1) if subs else None,
            "vph": round(views / max(days * 24, 1), 1),
            "url": "https://youtube.com/watch?v=" + _vid_id(title),
            "registered": registered,
        }
        cards.append(card)
    if video_format == "shorts":
        cards = [c for c in cards if c["duration_sec"] <= 61]
    elif video_format == "long":
        cards = [c for c in cards if c["duration_sec"] > 61]
    return cards[:max_results]


def _days_ago_iso(days: int) -> str:
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def mock_keyword_estimate(query: str) -> dict:
    rng = random.Random(query)
    return {
        "query": query,
        "total_results_estimate": rng.randint(50_000, 2_000_000),
        "avg_top_views": rng.randint(1_000_000, 80_000_000),
        "note": "추정치 (데모 데이터) — 실제 키를 넣으면 실측 근사치로 바뀝니다.",
        "is_estimate": True,
    }
