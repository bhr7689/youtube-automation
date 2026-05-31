import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from core.config import PINTEREST_TOKEN, THUMB_DIR, VOCAB_DIR
from core.store import get_conn
from core.utils import url_hash, new_id, download_image

logger = logging.getLogger(__name__)

PINTEREST_KEYWORDS = {
    "트로트_그리움": ["Korean retro nostalgia", "vintage korean aesthetic", "trot singer poster"],
    "트로트_흥": ["colorful kpop thumbnail", "vibrant korean music", "energetic stage performance"],
    "트로트_효도": ["korean grandmother aesthetic", "warm family korea", "emotional korean poster"],
    "먹방_욕망": ["food photography desire", "mukbang thumbnail", "delicious food close up"],
    "반전_호기심": ["shocking reveal thumbnail", "clickbait curiosity", "before after dramatic"],
    "공포_불안": ["dark horror thumbnail", "scary face expression", "mystery dark aesthetic"],
    "일반_트렌드": ["youtube thumbnail design 2024", "viral thumbnail layout", "eye catching banner"],
    "색상_트렌드": ["trending color palette 2024", "vivid color combination", "high contrast design"],
    "타이포_트렌드": ["bold typography design", "korean font poster", "text overlay thumbnail"],
}


def init_pinterest_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS pinterest_pins (
            pin_id TEXT PRIMARY KEY, keyword TEXT, category TEXT, title TEXT,
            description TEXT, image_url TEXT, local_path TEXT, source_url TEXT,
            dominant_color TEXT, palette TEXT, collected_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pin_keyword ON pinterest_pins(keyword);
        CREATE INDEX IF NOT EXISTS idx_pin_category ON pinterest_pins(category);
        """)


def _save_pin(pin):
    with get_conn() as conn:
        conn.execute("""
        INSERT OR IGNORE INTO pinterest_pins
            (pin_id, keyword, category, title, description, image_url, local_path,
             source_url, dominant_color, palette, collected_at)
        VALUES
            (:pin_id,:keyword,:category,:title,:description,:image_url,:local_path,
             :source_url,:dominant_color,:palette,:collected_at)
        """, pin)


_API_BASE = "https://api.pinterest.com/v5"

def _api_headers():
    return {"Authorization": f"Bearer {PINTEREST_TOKEN}", "Content-Type": "application/json"}


def _api_search_pins(keyword, limit=20):
    url = f"{_API_BASE}/pins/search"
    try:
        resp = httpx.get(url, headers=_api_headers(), params={"query": keyword, "page_size": min(limit, 25)}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        logger.warning("Pinterest API 실패 [%s]: %s", keyword, e)
        return []


def _api_pin_to_dict(item, keyword, category):
    images = item.get("media", {}).get("images", {})
    img_url = ""
    for size in ("originals", "1200x", "600x", "400x300", "150x150"):
        if size in images:
            img_url = images[size].get("url", "")
            break
    if not img_url:
        return None
    pin_id = "pi_" + url_hash(item.get("id", "") + keyword)
    return {"pin_id": pin_id, "keyword": keyword, "category": category,
        "title": item.get("title", "")[:200], "description": item.get("description", "")[:500],
        "image_url": img_url, "local_path": None,
        "source_url": f"https://pinterest.com/pin/{item.get('id','')}",
        "dominant_color": None, "palette": None, "collected_at": datetime.utcnow().isoformat()}


_SCRAPE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}


def _scrape_pinterest(keyword, limit=20):
    q = keyword.replace(" ", "+")
    url = f"https://www.pinterest.com/search/pins/?q={q}&rs=typed"
    pins = []
    try:
        resp = httpx.get(url, headers=_SCRAPE_HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        match = re.search(r'__PWS_DATA__\s*=\s*(\{.*?\});</script>', resp.text, re.DOTALL)
        if not match:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup.find_all("img", src=True):
                src = tag.get("src", "")
                if "pinimg.com" in src and "236x" not in src:
                    pins.append({"pin_id": "pi_" + url_hash(src + keyword), "keyword": keyword,
                        "image_url": src, "title": tag.get("alt", ""), "description": "", "source_url": url})
                    if len(pins) >= limit:
                        break
            return pins
        data = json.loads(match.group(1))
        pins = _extract_pins_from_pws(data, keyword, limit)
    except Exception as e:
        logger.warning("Pinterest 스크래핑 실패 [%s]: %s", keyword, e)
    return pins[:limit]


def _extract_pins_from_pws(data, keyword, limit):
    pins = []
    stack = [data]
    seen = set()
    while stack and len(pins) < limit:
        node = stack.pop()
        if isinstance(node, dict):
            images = node.get("images")
            if isinstance(images, dict):
                for size_key in ("orig", "736x", "474x", "236x"):
                    img = images.get(size_key, {})
                    url = img.get("url", "")
                    if url and url not in seen and "pinimg.com" in url:
                        seen.add(url)
                        pins.append({"pin_id": "pi_" + url_hash(url + keyword), "keyword": keyword,
                            "image_url": url, "title": node.get("title", node.get("grid_title", ""))[:200],
                            "description": node.get("description", "")[:500],
                            "source_url": f"https://pinterest.com/pin/{node.get('id','')"})
                        break
            for v in node.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return pins


def _analyze_colors(local_path):
    try:
        from analyze.color_extractor import extract_palette
        result = extract_palette(local_path)
        return result.get("dominant"), json.dumps(result.get("palette", []))
    except Exception:
        return None, None


def collect_pinterest_trends(categories=None, max_per_keyword=15, download=True):
    init_pinterest_db()
    categories = categories or list(PINTEREST_KEYWORDS.keys())
    use_api = bool(PINTEREST_TOKEN)
    total = 0
    for cat in categories:
        for kw in PINTEREST_KEYWORDS.get(cat, [cat]):
            if use_api:
                raw_pins = _api_search_pins(kw, limit=max_per_keyword)
                pins = [p for item in raw_pins if (p := _api_pin_to_dict(item, kw, cat))]
            else:
                raw = _scrape_pinterest(kw, limit=max_per_keyword)
                pins = [{**p, "category": cat, "local_path": None, "dominant_color": None,
                    "palette": None, "collected_at": datetime.utcnow().isoformat()} for p in raw]
            for pin in pins:
                if download and pin.get("image_url"):
                    dest = THUMB_DIR / "pinterest"
                    dest.mkdir(exist_ok=True)
                    path = download_image(pin["image_url"], dest, pin["pin_id"] + ".jpg")
                    if path:
                        pin["local_path"] = str(path)
                        dom, pal = _analyze_colors(str(path))
                        pin["dominant_color"] = dom
                        pin["palette"] = pal
                _save_pin(pin)
                total += 1
            time.sleep(0.5)
    return total


def get_trend_colors(category, limit=20):
    with get_conn() as conn:
        rows = conn.execute("SELECT dominant_color FROM pinterest_pins WHERE category=? AND dominant_color IS NOT NULL LIMIT ?", (category, limit)).fetchall()
    return [r["dominant_color"] for r in rows if r["dominant_color"]]


def get_trend_images(category=None, keyword=None, limit=20):
    sql = "SELECT * FROM pinterest_pins WHERE 1=1"
    params = []
    if category:
        sql += " AND category=?"; params.append(category)
    if keyword:
        sql += " AND keyword LIKE ?"; params.append(f"%{keyword}%")
    sql += " ORDER BY collected_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_pinterest_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM pinterest_pins").fetchone()[0]
        cats = conn.execute("SELECT category, COUNT(*) as cnt FROM pinterest_pins GROUP BY category ORDER BY cnt DESC").fetchall()
    return {"total": total, "by_category": [dict(r) for r in cats]}
