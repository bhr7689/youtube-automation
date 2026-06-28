"""
별도 프로세스로 실행되는 스크래핑 엔진.
결과를 JSON으로 stdout에 출력.
"""
import sys
import json
import re
import os
import shutil
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright


def find_chromium():
    candidates = [
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/opt/pw-browsers/chromium/chrome-linux/chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for name in ("chromium-browser", "chromium", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def scrape(url, dev_mode=False, proxy=None):
    result = {
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "title": None,
        "price_current": None,
        "price_original": None,
        "discount_rate": None,
        "rating": None,
        "review_count": None,
        "sold_count": None,
        "category_path": [],
        "tags": [],
        "keywords": [],
        "description": None,
        "attributes": {},
        "seller": None,
        "raw_json": {},
        "raw_html_snippet": "",
        "error": None,
        "error_detail": "",
    }
    try:
        chromium_path = find_chromium()
        launch_opts = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled",
                     "--disable-dev-shm-usage", "--disable-gpu"],
        }
        if chromium_path:
            launch_opts["executable_path"] = chromium_path
        if proxy:
            launch_opts["proxy"] = {"server": proxy}

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_opts)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="ko-KR",
            )
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda r: r.abort())
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(4000)

            raw_json = page.evaluate("""() => {
                const nd = document.getElementById('__NEXT_DATA__');
                if (nd) { try { return { source: '__NEXT_DATA__', data: JSON.parse(nd.textContent) }; } catch(e) {} }
                return null;
            }""")
            if raw_json:
                result["raw_json"] = raw_json
            if dev_mode:
                result["raw_html_snippet"] = page.content()[:5000]

            result["title"] = page.evaluate("""() => {
                for (const s of ['h1[class*="title"]','h1[class*="name"]','[class*="goods-name"]','[class*="product-title"]','h1']) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 5) return el.innerText.trim();
                }
                return document.title.split('|')[0].trim();
            }""")

            prices = page.evaluate("""() => {
                const out = {current:null,original:null,discount:null};
                for (const s of ['[class*="price-current"]','[class*="sale-price"]','[class*="final-price"]','[class*="goods-price"]']) {
                    const el = document.querySelector(s);
                    if (el) { out.current = el.innerText.trim(); break; }
                }
                for (const s of ['[class*="price-original"]','[class*="origin-price"]','del','s']) {
                    const el = document.querySelector(s);
                    if (el) { out.original = el.innerText.trim(); break; }
                }
                for (const s of ['[class*="discount"]','[class*="off"]','[class*="percent"]']) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.includes('%')) { out.discount = el.innerText.trim(); break; }
                }
                if (!out.current) {
                    const meta = document.querySelector('meta[property="product:price:amount"]');
                    if (meta) out.current = meta.content;
                }
                return out;
            }""")
            result["price_current"] = prices.get("current")
            result["price_original"] = prices.get("original")
            result["discount_rate"] = prices.get("discount")

            stats = page.evaluate("""() => {
                const out = {rating:null,reviews:null,sold:null};
                const re = document.querySelector('[class*="rating-score"],[class*="star-score"]');
                if (re) out.rating = re.innerText.trim();
                const rv = document.querySelector('[class*="review-count"],[class*="rating-count"]');
                if (rv) out.reviews = rv.innerText.trim();
                const m = document.body.innerText.match(/(\\d[\\d,]+)\\s*(sold|판매|개 판매)/i);
                if (m) out.sold = m[0];
                return out;
            }""")
            result["rating"] = stats.get("rating")
            result["review_count"] = stats.get("reviews")
            result["sold_count"] = stats.get("sold")

            result["category_path"] = page.evaluate("""() => {
                const bc = document.querySelector('[class*="breadcrumb"],[aria-label="breadcrumb"]');
                if (!bc) return [];
                return [...bc.querySelectorAll('a,span')].map(el=>el.innerText.trim()).filter(t=>t&&t!='>'&&t!='/'&&t.length<60);
            }""")

            result["tags"] = page.evaluate("""() => {
                const tags = new Set();
                for (const s of ['[class*="tag"]','[class*="badge"]','[class*="label"]','[class*="chip"]']) {
                    document.querySelectorAll(s).forEach(el=>{const t=el.innerText.trim();if(t&&t.length>1&&t.length<40)tags.add(t);});
                }
                return [...tags].slice(0,30);
            }""")

            result["description"] = page.evaluate("""() => {
                for (const s of ['[class*="description"]','[class*="detail-desc"]','[class*="product-desc"]']) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 20) return el.innerText.trim().slice(0,2000);
                }
                return null;
            }""")

            result["attributes"] = page.evaluate("""() => {
                const rows={};
                for (const s of ['[class*="attribute"]','[class*="spec"]','[class*="property"]']) {
                    document.querySelectorAll(s).forEach(el=>{
                        const k=el.querySelector('[class*="label"],[class*="key"],th,dt');
                        const v=el.querySelector('[class*="value"],[class*="content"],td,dd');
                        if(k&&v)rows[k.innerText.trim()]=v.innerText.trim();
                    });
                }
                return rows;
            }""")

            result["seller"] = page.evaluate("""() => {
                for (const s of ['[class*="seller"]','[class*="shop-name"]','[class*="brand"]']) {
                    const el=document.querySelector(s);
                    if(el&&el.innerText.trim())return el.innerText.trim();
                }
                return null;
            }""")

            # 키워드 추출
            text = " ".join(filter(None, [
                result["title"],
                *result["category_path"],
                *result["attributes"].values(),
                (result["description"] or "")[:500],
            ]))
            ko = re.findall(r'[가-힣]{2,}', text)
            en = re.findall(r'[A-Za-z][A-Za-z0-9\-]{2,}', text)
            stop = {'이다','있다','없다','하다','되다','그리고','상품','제품','판매','the','and','for','with'}
            freq = {}
            for w in ko + en:
                if w.lower() not in stop:
                    freq[w] = freq.get(w, 0) + 1
            result["keywords"] = [k for k, _ in sorted(freq.items(), key=lambda x: -x[1])[:30]]

            meta_kw = page.evaluate("""() => { const m=document.querySelector('meta[name="keywords"]'); return m?m.content:null; }""")
            if meta_kw:
                extra = [k.strip() for k in re.split(r'[,，]', meta_kw) if k.strip()]
                result["keywords"] = list(dict.fromkeys(result["keywords"] + extra))

            browser.close()

    except Exception as e:
        result["error"] = str(e)
        result["error_detail"] = traceback.format_exc()

    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "URL이 없어요"}))
        sys.exit(1)

    url = args[0]
    dev_mode = "--dev" in args
    proxy = None
    for a in args:
        if a.startswith("--proxy="):
            proxy = a.split("=", 1)[1]

    result = scrape(url, dev_mode, proxy)
    print(json.dumps(result, ensure_ascii=False))
