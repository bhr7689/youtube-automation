"""
쿠팡 상품 자동수집기 — 윈도우 호환 버전
원본 crawl.py(맥 전용)를 윈도우에서도 동작하도록 변환.
Streamlit UI(coupang_app.py)에서 호출하거나, 단독으로도 실행 가능.

사용법(단독):
  python coupang_crawl.py "https://link.coupang.com/a/XXXX"

이 사본은 whiteh2r@gmail.com 전용 · 재배포·재판매 금지 · © 2026 4000
"""
import sys, time, socket, subprocess, re, http.client, json, urllib.request, os
from urllib.parse import urlparse, parse_qs
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright가 없어요. 먼저: pip install playwright && playwright install chromium")
    sys.exit(1)

PORT = 9222
PROFILE = str(Path.home() / ".coupang-crawl-chrome")
OUT_ROOT = Path(__file__).parent / "output"


def find_chrome_windows() -> str | None:
    """윈도우에서 구글 크롬 실행 파일 경로 자동 탐색"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        # macOS (개발 환경)
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # PATH에서 탐색
    import shutil
    for name in ("chrome", "google-chrome", "google-chrome-stable", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_url(url: str) -> str:
    """단축 link.coupang.com → 실제 상품 URL"""
    if "link.coupang.com" in url:
        try:
            p = urlparse(url)
            c = http.client.HTTPSConnection(p.netloc, timeout=10)
            c.request("HEAD", p.path + (("?" + p.query) if p.query else ""),
                      headers={"User-Agent": "Mozilla/5.0"})
            r = c.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                url = r.getheader("Location", url)
        except Exception:
            pass
    m = re.search(r"coupang\.com/vp/products/(\d+)", url)
    if m:
        pid = m.group(1)
        qs = parse_qs(urlparse(url).query)
        u = f"https://www.coupang.com/vp/products/{pid}"
        if "itemId" in qs:
            u += f"?itemId={qs['itemId'][0]}"
        return u
    return url


def kill_zombie():
    """이전 디버그 크롬 정리 (윈도우/맥 모두 지원)"""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/FI", f"COMMANDLINE eq *remote-debugging-port={PORT}*"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        subprocess.run(
            ["pkill", "-f", f"remote-debugging-port={PORT}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    time.sleep(1)


def launch_chrome(chrome_path: str):
    """실제 크롬을 CDP 모드로 실행"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("localhost", PORT)) == 0:
            return  # 이미 실행 중
    if not chrome_path or not os.path.exists(chrome_path):
        return
    cmd = [
        chrome_path,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(0.5)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", PORT)) == 0:
                return


def clean_title(t: str) -> str:
    t = t.replace(" | 쿠팡", "").strip()
    return re.split(r"\s+-\s+", t)[0].strip()


def crawl(url: str, log_fn=print) -> dict:
    """
    상품 URL을 받아 정보를 수집하고 dict로 반환.
    log_fn: 진행 상황을 출력할 함수 (print 또는 st.write 등)
    """
    url = resolve_url(url)
    log_fn(f"[1] 상품 페이지: {url}")

    chrome_path = find_chrome_windows()
    use_cdp = bool(chrome_path)

    if use_cdp:
        log_fn("  실제 크롬으로 접속 중 (봇 차단 우회)...")
        kill_zombie()
        launch_chrome(chrome_path)
    else:
        log_fn("  크롬 미발견 → Playwright 기본 Chromium으로 시도...")

    info = {"url": url, "title": "", "price": "", "original_price": "",
            "discount_rate": "", "rating": "", "review_count": "",
            "reviews": [], "images": [], "error": ""}

    try:
        with sync_playwright() as pw:
            if use_cdp:
                try:
                    browser = pw.chromium.connect_over_cdp(f"http://localhost:{PORT}")
                    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                except Exception:
                    use_cdp = False

            if not use_cdp:
                import shutil as _sh
                candidates = [
                    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                    "/usr/bin/chromium-browser",
                ]
                cp = next((c for c in candidates if os.path.exists(c)), None)
                if not cp:
                    cp = _sh.which("chromium-browser") or _sh.which("chromium")
                opts = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                if cp:
                    opts["executable_path"] = cp
                browser = pw.chromium.launch(**opts)
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
                )
                page = ctx.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            time.sleep(2)

            info["title"] = clean_title(page.title())

            body_text = page.inner_text("body")[:300] if page.query_selector("body") else ""
            if not info["title"] or "Access Denied" in body_text:
                info["error"] = "페이지 차단됨 (캡차/접근 거부). 크롬에서 수동으로 한 번 접속 후 재시도."
                return info

            # 가격 추출 (클래스명 아닌 값의 모양으로)
            prices = page.evaluate("""() => {
              const isP=t=>/^[\\d,]{3,}원?$/.test((t||'').trim()); const o=[];
              for(const e of document.querySelectorAll('span,strong,div,em,b')){
                if(e.children.length)continue; const t=(e.textContent||'').trim();
                if(!isP(t))continue; const cs=getComputedStyle(e),r=e.getBoundingClientRect();
                if(r.top<0||r.top>1600)continue;
                o.push({txt:t,fs:parseFloat(cs.fontSize),
                  strike:(cs.textDecorationLine||'').includes('line-through'),
                  top:Math.round(r.top),num:parseInt(t.replace(/[^0-9]/g,''))});
              } return o;
            }""")
            cur = sorted([p for p in prices if not p["strike"]], key=lambda p: (-p["fs"], p["top"]))
            info["price"] = cur[0]["txt"] if cur else ""
            cnum = cur[0]["num"] if cur else 0
            orig = [p for p in prices if p["strike"]] or [p for p in prices if cnum and p["num"] > cnum]
            orig = sorted(orig, key=lambda p: p["top"])
            info["original_price"] = orig[0]["txt"] if orig else ""
            info["discount_rate"] = (
                f"{round((1 - cnum / orig[0]['num']) * 100)}%"
                if (orig and cnum and orig[0]["num"] > cnum) else ""
            )

            # 평점
            info["rating"] = page.evaluate("""() => {
              for(const e of document.querySelectorAll('[style*="width"]')){
                const cls=(e.className||'')+' '+(e.parentElement?e.parentElement.className:'');
                if(/star|rating|rate/i.test(cls)){
                  const m=(e.getAttribute('style')||'').match(/width:\\s*([\\d.]+)%/);
                  if(m){const pct=parseFloat(m[1]); if(pct>0&&pct<=100) return (pct/20).toFixed(1);}
                }
              } return "";
            }""")

            # 리뷰 수
            info["review_count"] = page.evaluate(
                """() => { const m=(document.body.innerText||'').match(/상품평\\s*\\(?([\\d,]+)\\)?/);
                return m?m[1]:''; }"""
            )

            # 리뷰 탭 클릭 + 스크롤
            log_fn("  리뷰 수집 중...")
            for sel in ('a[href="#sdpReview"]', 'a[href="#review"]', '#sdpReview'):
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.scroll_into_view_if_needed()
                        el.click(timeout=2000)
                        break
                except Exception:
                    pass
            for y in range(0, 10000, 800):
                page.evaluate(f"window.scrollTo(0,{y})")
                time.sleep(0.2)
            time.sleep(1.5)

            reviews = page.evaluate("""(title) => {
              const clean=s=>(s||'').replace(/\\s+/g,' ').trim();
              const hasMeta=t=>
                /\\d{4}\\.\\d{1,2}\\.\\d{1,2}/.test(t)||
                /판매자\\s*:/.test(t)||
                /도움이\\s*됐어요|신고하기/.test(t)||
                (title&&t.includes(title.slice(0,12)));
              const footers=document.querySelectorAll(
                '.sdp-review__article__list__help,[class*="reviewArticleHelpful"]');
              const out=[]; const seen=new Set();
              for(const f of footers){
                let box=f;
                for(let i=0;i<7&&box.parentElement;i++){
                  box=box.parentElement; if(box.tagName==='ARTICLE')break;
                }
                let best='';
                for(const e of box.querySelectorAll('div,span,p')){
                  const t=clean(e.textContent);
                  if(t.length<15||t.length>1200)continue;
                  if(!/[가-힣]/.test(t)||hasMeta(t))continue;
                  if(t.length>best.length)best=t;
                }
                best=best.replace(/^\\d+\\s*:\\s*\\d{2}\\s*/,'');
                if(best&&best.length>=15&&!seen.has(best)){seen.add(best);out.push(best);}
                if(out.length>=8)break;
              } return out;
            }""", info["title"])
            info["reviews"] = reviews

            # 이미지
            imgs = page.evaluate("""() => {
              const u=new Set();
              const og=document.querySelector('meta[property="og:image"]');
              if(og)u.add(og.content);
              for(const im of document.querySelectorAll('img')){
                const s=im.src||'';
                if(/coupangcdn|thumbnail/.test(s)&&/\\.(jpg|jpeg|png)/i.test(s))u.add(s);
                if(u.size>=6)break;
              } return [...u];
            }""")
            info["images"] = imgs
            log_fn(f"  수집 완료: 가격={info['price']}, 리뷰={len(reviews)}개, 이미지={len(imgs)}개")

            page.close()

    except Exception as e:
        info["error"] = str(e)

    return info


def save_result(info: dict) -> Path:
    """결과를 output 폴더에 저장"""
    safe = re.sub(r'[^\w가-힣]+', '_', info["title"])[:40].strip('_') or "product"
    d = OUT_ROOT / safe
    (d / "images").mkdir(parents=True, exist_ok=True)

    saved = 0
    for i, u in enumerate(info.get("images", [])[:6]):
        try:
            req = urllib.request.Request(
                u if u.startswith('http') else 'https:' + u,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.coupang.com/"}
            )
            (d / "images" / f"img_{i+1}.jpg").write_bytes(
                urllib.request.urlopen(req, timeout=10).read()
            )
            saved += 1
        except Exception:
            pass

    (d / "result.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (d / "summary.md").write_text(
        f"# {info['title']}\n\n"
        f"- 현재가: {info['price']}\n"
        f"- 원가: {info['original_price']}\n"
        f"- 할인율: {info['discount_rate']}\n"
        f"- 평점: {info['rating'] or '(수집 못함)'}\n"
        f"- 리뷰수: {info['review_count']}\n"
        f"- URL: {info['url']}\n",
        encoding="utf-8"
    )
    reviews = info.get("reviews", [])
    (d / "review.md").write_text(
        "# 구매자 리뷰 (원문)\n\n" + (
            "\n\n".join(f"- {r}" for r in reviews) if reviews
            else "(자동 수집 못함 — 후기 2~3개를 직접 복사해서 붙여넣어주세요)"
        ),
        encoding="utf-8"
    )
    return d


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    json_mode = "--json" in sys.argv

    if not args:
        print('사용법: python coupang_crawl.py "<쿠팡 링크>"')
        sys.exit(1)

    info = crawl(args[0], log_fn=(lambda *_: None) if json_mode else print)

    if json_mode:
        print(json.dumps(info, ensure_ascii=False))
    elif info.get("error"):
        print(f"오류: {info['error']}")
    else:
        d = save_result(info)
        print(f"\n결과 저장: {d}")
