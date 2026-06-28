"""
테무(Temu) 식품 카테고리 상품 정보 스크래퍼
- 상품 URL 입력 → 키워드, 태그, 상세 설명, 가격 등 자동 추출
- 개발자 모드 뷰: 원본 JSON 데이터 + 파싱 결과 동시 표시
"""

import streamlit as st
import json
import re
import time
import os
import shutil
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright


def _find_chromium() -> str | None:
    """PC 환경에 따라 Chromium 실행 파일 자동 탐색"""
    candidates = [
        # 클라우드 환경(Claude Code Web)
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/opt/pw-browsers/chromium/chrome-linux/chrome",
        # Linux 일반
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        # macOS
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


st.set_page_config(
    page_title="테무 식품 스크래퍼",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.tag-chip {
    display: inline-block;
    background: #fff3e0;
    color: #e65100;
    border: 1px solid #ffb74d;
    border-radius: 20px;
    padding: 3px 12px;
    margin: 3px 3px;
    font-size: 13px;
    font-weight: 500;
}
.keyword-chip {
    display: inline-block;
    background: #e3f2fd;
    color: #1565c0;
    border: 1px solid #90caf9;
    border-radius: 20px;
    padding: 3px 12px;
    margin: 3px 3px;
    font-size: 13px;
    font-weight: 500;
}
.section-title {
    font-size: 1rem; font-weight: 700; color: #424242;
    border-left: 4px solid #ff7043;
    padding-left: 10px; margin: 18px 0 8px 0;
}
.stat-box {
    background: #f5f5f5; border-radius: 8px;
    padding: 12px 16px; text-align: center;
}
.stat-num { font-size: 1.4rem; font-weight: 700; color: #e53935; }
.stat-label { font-size: 0.8rem; color: #757575; }
.dev-badge {
    background: #263238; color: #80cbc4;
    border-radius: 6px; padding: 2px 10px;
    font-size: 12px; font-family: monospace;
}
</style>
""", unsafe_allow_html=True)


# ── 스크래핑 (sync 방식 — Streamlit 호환) ─────────────────
def scrape_temu_product(url: str, dev_mode: bool = False, proxy: str | None = None) -> dict:
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
        chromium_path = _find_chromium()

        launch_opts: dict = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        }
        if chromium_path:
            launch_opts["executable_path"] = chromium_path
        if proxy:
            launch_opts["proxy"] = {"server": proxy}

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_opts)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="ko-KR",
            )
            page = ctx.new_page()

            # 이미지·폰트 차단해 속도 향상
            page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}",
                lambda r: r.abort(),
            )

            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(4000)

            # ── JSON 원본 추출 ──
            raw_json = page.evaluate("""() => {
                const nd = document.getElementById('__NEXT_DATA__');
                if (nd) {
                    try { return { source: '__NEXT_DATA__', data: JSON.parse(nd.textContent) }; }
                    catch(e) {}
                }
                const scripts = [...document.querySelectorAll('script:not([src])')];
                for (const s of scripts) {
                    const txt = s.textContent || '';
                    if (txt.includes('goodsId') || txt.includes('goodsPrice')) {
                        const m = txt.match(/window\\.__[A-Z_]+__\\s*=\\s*(\\{[\\s\\S]*?\\});/);
                        if (m) {
                            try { return { source: 'window_var', data: JSON.parse(m[1]) }; }
                            catch(e) {}
                        }
                    }
                }
                return null;
            }""")
            if raw_json:
                result["raw_json"] = raw_json

            html = page.content()
            if dev_mode:
                result["raw_html_snippet"] = html[:5000]

            # ── 제목 ──
            result["title"] = page.evaluate("""() => {
                const selectors = [
                    'h1[class*="title"]', 'h1[class*="name"]',
                    '[class*="goods-name"]', '[class*="product-title"]',
                    '[data-testid="goods-title"]', 'h1',
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 5) return el.innerText.trim();
                }
                return document.title.split('|')[0].trim();
            }""")

            # ── 가격 ──
            prices = page.evaluate("""() => {
                const out = { current: null, original: null, discount: null };
                for (const s of ['[class*="price-current"]','[class*="sale-price"]',
                                  '[class*="final-price"]','[class*="goods-price"]',
                                  '[data-testid="goods-price"]']) {
                    const el = document.querySelector(s);
                    if (el) { out.current = el.innerText.trim(); break; }
                }
                for (const s of ['[class*="price-original"]','[class*="origin-price"]',
                                  '[class*="market-price"]','del','s']) {
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
            result["price_current"]  = prices.get("current")
            result["price_original"] = prices.get("original")
            result["discount_rate"]  = prices.get("discount")

            # ── 평점·리뷰·판매량 ──
            stats = page.evaluate("""() => {
                const out = { rating: null, reviews: null, sold: null };
                const re = document.querySelector('[class*="rating-score"],[class*="star-score"],[aria-label*="rating"]');
                if (re) out.rating = re.innerText.trim();
                const rv = document.querySelector('[class*="review-count"],[class*="rating-count"]');
                if (rv) out.reviews = rv.innerText.trim();
                const m = document.body.innerText.match(/(\\d[\\d,]+)\\s*(sold|판매|개 판매|개 팔린)/i);
                if (m) out.sold = m[0];
                return out;
            }""")
            result["rating"]       = stats.get("rating")
            result["review_count"] = stats.get("reviews")
            result["sold_count"]   = stats.get("sold")

            # ── 카테고리 경로 ──
            result["category_path"] = page.evaluate("""() => {
                const bc = document.querySelector('[class*="breadcrumb"],[aria-label="breadcrumb"],nav[class*="crumb"]');
                if (!bc) return [];
                return [...bc.querySelectorAll('a,span')]
                    .map(el => el.innerText.trim())
                    .filter(t => t && t !== '>' && t !== '/' && t.length < 60);
            }""")

            # ── 태그 ──
            result["tags"] = page.evaluate("""() => {
                const tags = new Set();
                for (const s of ['[class*="tag"]','[class*="badge"]','[class*="label"]','[class*="chip"]']) {
                    document.querySelectorAll(s).forEach(el => {
                        const t = el.innerText.trim();
                        if (t && t.length > 1 && t.length < 40) tags.add(t);
                    });
                }
                return [...tags].slice(0, 30);
            }""")

            # ── 상세 설명 ──
            result["description"] = page.evaluate("""() => {
                for (const s of ['[class*="description"]','[class*="detail-desc"]',
                                  '[class*="product-desc"]','[class*="goods-desc"]',
                                  '[data-testid="product-description"]']) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 20) return el.innerText.trim().slice(0,2000);
                }
                return null;
            }""")

            # ── 속성/스펙 ──
            result["attributes"] = page.evaluate("""() => {
                const rows = {};
                for (const s of ['[class*="attribute"]','[class*="spec"]',
                                  '[class*="property"]','[class*="detail-attr"]']) {
                    document.querySelectorAll(s).forEach(el => {
                        const k = el.querySelector('[class*="label"],[class*="key"],th,dt');
                        const v = el.querySelector('[class*="value"],[class*="content"],td,dd');
                        if (k && v) rows[k.innerText.trim()] = v.innerText.trim();
                    });
                }
                document.querySelectorAll('table tr').forEach(tr => {
                    const cells = tr.querySelectorAll('td,th');
                    if (cells.length === 2) rows[cells[0].innerText.trim()] = cells[1].innerText.trim();
                });
                return rows;
            }""")

            # ── 셀러 ──
            result["seller"] = page.evaluate("""() => {
                for (const s of ['[class*="seller"]','[class*="shop-name"]',
                                  '[class*="brand"]','[class*="store"]']) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim()) return el.innerText.trim();
                }
                return null;
            }""")

            # ── 키워드 자동 추출 ──
            result["keywords"] = _extract_keywords(result)

            meta_kw = page.evaluate("""() => {
                const m = document.querySelector('meta[name="keywords"]');
                return m ? m.content : null;
            }""")
            if meta_kw:
                extra = [k.strip() for k in re.split(r'[,，]', meta_kw) if k.strip()]
                result["keywords"] = list(dict.fromkeys(result["keywords"] + extra))

            browser.close()

    except Exception as e:
        result["error"] = str(e)
        result["error_detail"] = traceback.format_exc()

    return result


def _extract_keywords(result: dict) -> list[str]:
    text_parts = []
    if result["title"]:
        text_parts.append(result["title"])
    text_parts.extend(result.get("category_path", []))
    for v in (result.get("attributes") or {}).values():
        text_parts.append(str(v))
    if result.get("description"):
        text_parts.append(result["description"][:500])

    combined = " ".join(text_parts)
    ko_words = re.findall(r'[가-힣]{2,}', combined)
    en_words = re.findall(r'[A-Za-z][A-Za-z0-9\-]{2,}', combined)
    stopwords = {
        '이다', '있다', '없다', '하다', '되다', '그리고', '또는', '또한',
        '에서', '으로', '에게', '부터', '까지', '상품', '제품', '판매',
        'the', 'and', 'for', 'with', 'this', 'that', 'from',
    }
    freq: dict[str, int] = {}
    for w in ko_words + en_words:
        wl = w.lower()
        if wl not in stopwords and len(w) > 1:
            freq[w] = freq.get(w, 0) + 1
    return [k for k, _ in sorted(freq.items(), key=lambda x: -x[1])[:30]]


# ── UI ──────────────────────────────────────────────────
def main():
    # ── session_state 초기화 (결과가 사라지지 않게) ──
    if "results" not in st.session_state:
        st.session_state.results = []
    if "last_error" not in st.session_state:
        st.session_state.last_error = ""

    with st.sidebar:
        st.markdown("## 🛒 테무 식품 스크래퍼")
        st.markdown("---")
        st.markdown("**사용법**")
        st.markdown("1. 테무 상품 URL 붙여넣기\n2. 여러 URL은 한 줄에 하나씩\n3. **스크래핑 시작** 클릭")
        st.markdown("---")
        dev_mode = st.toggle("🔧 개발자 모드 (원본 JSON·HTML 표시)", value=True)
        st.markdown("---")
        proxy_input = st.text_input("🔒 프록시 (선택)", placeholder="http://127.0.0.1:7890")

        chromium_path = _find_chromium()
        st.markdown("---")
        if chromium_path:
            st.success("✅ Chromium 감지됨")
            st.caption(chromium_path)
        else:
            st.error("❌ Chromium 없음")
            st.code("playwright install chromium")

    st.markdown("# 🛒 테무 식품 카테고리 상품 분석기")
    st.markdown("테무 상품 링크를 넣으면 키워드·태그·가격·상세설명을 자동 추출해요.")

    url_input = st.text_area(
        "📎 테무 상품 URL (여러 개면 한 줄에 하나씩)",
        height=120,
        placeholder="https://www.temu.com/...\nhttps://www.temu.com/...",
    )

    col1, col2 = st.columns([2, 8])
    with col1:
        start = st.button("🚀 스크래핑 시작", type="primary", use_container_width=True)
    with col2:
        if st.button("🗑️ 결과 지우기", use_container_width=False):
            st.session_state.results = []
            st.session_state.last_error = ""
            st.rerun()

    # ── 이전 오류가 있으면 항상 표시 ──
    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    if start and url_input.strip():
        urls = [u.strip() for u in url_input.strip().splitlines() if u.strip().startswith("http")]
        if not urls:
            st.session_state.last_error = "올바른 URL을 입력해주세요 (http로 시작)"
            st.rerun()
            return

        if not _find_chromium():
            st.session_state.last_error = (
                "❌ Chromium 브라우저가 없어요!\n\n"
                "검은 창(터미널)에 아래를 붙여넣고 엔터:\n\n"
                "playwright install chromium"
            )
            st.rerun()
            return

        st.session_state.last_error = ""
        results = []
        prog = st.progress(0, text="준비 중...")
        for i, url in enumerate(urls):
            prog.progress(i / len(urls), text=f"스크래핑 중... ({i+1}/{len(urls)})")
            try:
                data = scrape_temu_product(url, dev_mode, proxy_input.strip() or None)
            except Exception as e:
                data = {
                    "url": url,
                    "scraped_at": datetime.now().isoformat(),
                    "error": str(e),
                    "error_detail": traceback.format_exc(),
                }
            results.append(data)
            if i < len(urls) - 1:
                time.sleep(2)
        prog.progress(1.0, text="완료!")
        time.sleep(0.3)
        prog.empty()
        st.session_state.results = results
        st.rerun()
        return

    results = st.session_state.results

    for idx, r in enumerate(results):
            st.markdown(f"---")
            st.markdown(f"### 상품 {idx+1}")

            # ── 오류 표시 (사라지지 않게 고정) ──
            if r.get("error"):
                st.error(f"⚠️ 오류가 발생했어요:\n\n`{r['error']}`")
                with st.expander("🔍 상세 오류 보기 (개발자용)"):
                    st.code(r.get("error_detail", ""))
                st.info("💡 **해결 방법**\n- URL이 올바른지 확인해주세요\n- 인터넷 연결을 확인해주세요\n- 테무가 접속을 막은 경우 잠시 후 다시 시도해주세요")
                continue

            # ── 요약 ──
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(f'<div class="stat-box"><div class="stat-num">{r.get("price_current") or "-"}</div><div class="stat-label">현재가</div></div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="stat-box"><div class="stat-num">{r.get("discount_rate") or "-"}</div><div class="stat-label">할인율</div></div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div class="stat-box"><div class="stat-num">{r.get("rating") or "-"}</div><div class="stat-label">평점</div></div>', unsafe_allow_html=True)
            with c4:
                st.markdown(f'<div class="stat-box"><div class="stat-num">{r.get("review_count") or "-"}</div><div class="stat-label">리뷰수</div></div>', unsafe_allow_html=True)

            st.markdown("")

            st.markdown('<div class="section-title">📌 상품명</div>', unsafe_allow_html=True)
            st.markdown(f"**{r.get('title') or '(제목 없음)'}**")

            if r.get("category_path"):
                st.markdown('<div class="section-title">📂 카테고리 경로</div>', unsafe_allow_html=True)
                st.markdown(" > ".join(r["category_path"]))

            if r.get("keywords"):
                st.markdown('<div class="section-title">🔑 자동 추출 키워드</div>', unsafe_allow_html=True)
                st.markdown("".join([f'<span class="keyword-chip">{k}</span>' for k in r["keywords"]]), unsafe_allow_html=True)
                with st.expander("📋 키워드 복사 (쉼표 구분)"):
                    st.code(", ".join(r["keywords"]))

            if r.get("tags"):
                st.markdown('<div class="section-title">🏷️ 태그/뱃지</div>', unsafe_allow_html=True)
                st.markdown("".join([f'<span class="tag-chip">{t}</span>' for t in r["tags"]]), unsafe_allow_html=True)

            if r.get("description"):
                st.markdown('<div class="section-title">📄 상세 설명</div>', unsafe_allow_html=True)
                st.text_area("", value=r["description"], height=200, key=f"desc_{idx}", label_visibility="collapsed")

            if r.get("attributes"):
                st.markdown('<div class="section-title">📊 상품 속성/스펙</div>', unsafe_allow_html=True)
                import pandas as pd
                st.dataframe(
                    pd.DataFrame(list(r["attributes"].items()), columns=["항목", "값"]),
                    use_container_width=True, hide_index=True,
                )

            if r.get("seller"):
                st.markdown('<div class="section-title">🏪 셀러/브랜드</div>', unsafe_allow_html=True)
                st.info(r["seller"])

            st.markdown('<div class="section-title">💰 가격 정보</div>', unsafe_allow_html=True)
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("현재가", r.get("price_current") or "-")
            pc2.metric("원가",   r.get("price_original") or "-")
            pc3.metric("할인율", r.get("discount_rate") or "-")

            st.caption(f"🔗 {r['url']}  |  🕐 {r['scraped_at']}")

            if dev_mode:
                st.markdown('<div class="section-title"><span class="dev-badge">DEV</span> 원본 데이터</div>', unsafe_allow_html=True)
                tab_json, tab_html, tab_full = st.tabs(["📦 JSON", "🌐 HTML", "📋 전체 결과"])
                with tab_json:
                    if r.get("raw_json"):
                        st.json(r["raw_json"])
                    else:
                        st.warning("JSON 데이터 없음")
                with tab_html:
                    st.code(r.get("raw_html_snippet") or "(없음)", language="html")
                with tab_full:
                    st.json({k: v for k, v in r.items() if k not in ("raw_json", "raw_html_snippet")})

            st.download_button(
                label="⬇️ JSON으로 저장",
                data=json.dumps(r, ensure_ascii=False, indent=2),
                file_name=f"temu_{idx+1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                key=f"dl_{idx}",
            )

    if start and not url_input.strip():
        st.warning("URL을 입력해주세요.")

    if not results:
        st.markdown("---")
        st.markdown("## 📖 사용 가이드")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
**추출 정보 목록**
- 📌 상품명
- 💰 현재가 / 원가 / 할인율
- ⭐ 평점 / 리뷰 수 / 판매량
- 📂 카테고리 경로
- 🔑 자동 키워드 추출
- 🏷️ 태그 / 뱃지
- 📄 상세 설명
- 📊 상품 속성 / 스펙
- 🏪 셀러 / 브랜드
""")
        with col2:
            st.markdown("""
**개발자 모드 추가 정보**
- 📦 JSON 원본 데이터
- 🌐 HTML 소스 스니펫
- 📋 전체 파싱 결과

**팁**
- 여러 상품 비교: URL 여러 줄 입력
- JSON 저장 후 Excel에서 분석 가능
- 테무 앱 → 공유 → 링크 복사로 URL 획득
""")


if __name__ == "__main__":
    main()
