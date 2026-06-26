"""
테무(Temu) 식품 카테고리 상품 정보 스크래퍼
- 상품 URL 입력 → 키워드, 태그, 상세 설명, 가격 등 자동 추출
- 개발자 모드 뷰: 원본 JSON 데이터 + 파싱 결과 동시 표시
"""

import streamlit as st
import json
import re
import time
import asyncio
import os
import shutil
from datetime import datetime
from playwright.async_api import async_playwright


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
    # PATH에서 탐색
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

# ── 스타일 ──────────────────────────────────────────────
st.markdown("""
<style>
body { font-family: 'Noto Sans KR', sans-serif; }
.product-card {
    background: #fff;
    border: 1.5px solid #e0e0e0;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
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
.price-big { font-size: 2rem; font-weight: 700; color: #e53935; }
.price-orig { font-size: 1rem; color: #9e9e9e; text-decoration: line-through; }
.section-title {
    font-size: 1rem; font-weight: 700; color: #424242;
    border-left: 4px solid #ff7043;
    padding-left: 10px; margin: 18px 0 8px 0;
}
.dev-badge {
    background: #263238; color: #80cbc4;
    border-radius: 6px; padding: 2px 10px;
    font-size: 12px; font-family: monospace;
}
.stat-box {
    background: #f5f5f5; border-radius: 8px;
    padding: 12px 16px; text-align: center;
}
.stat-num { font-size: 1.4rem; font-weight: 700; color: #e53935; }
.stat-label { font-size: 0.8rem; color: #757575; }
</style>
""", unsafe_allow_html=True)


# ── 스크래핑 함수 ────────────────────────────────────────
async def scrape_temu_product(url: str, dev_mode: bool = False, proxy: str | None = None):
    """Playwright로 테무 상품 페이지 스크래핑"""
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
        "brand": None,
        "category_path": [],
        "tags": [],
        "keywords": [],
        "description": None,
        "description_bullets": [],
        "attributes": {},
        "images": [],
        "seller": None,
        "shipping_info": None,
        "raw_json": {},
        "raw_html_snippet": "",
        "error": None,
    }

    try:
        chromium_path = _find_chromium()
        launch_opts = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        }
        if chromium_path:
            launch_opts["executable_path"] = chromium_path
        if proxy:
            launch_opts["proxy"] = {"server": proxy}

        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_opts)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="ko-KR",
            )
            page = await ctx.new_page()

            # 불필요한 리소스 차단해 속도 향상
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}",
                lambda r: r.abort(),
            )

            # 페이지 이동
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)  # JS 렌더 대기

            # ── 1) __NEXT_DATA__ / window.__STORE__ JSON 추출 ──
            raw_json = await page.evaluate("""() => {
                // Next.js SSR 데이터
                const nd = document.getElementById('__NEXT_DATA__');
                if (nd) {
                    try { return { source: '__NEXT_DATA__', data: JSON.parse(nd.textContent) }; }
                    catch(e) {}
                }
                // 인라인 스크립트에서 window.__INITIAL_STATE__ 등 탐색
                const scripts = [...document.querySelectorAll('script:not([src])')];
                for (const s of scripts) {
                    const txt = s.textContent || '';
                    if (txt.includes('goodsId') || txt.includes('goodsPrice') || txt.includes('price')) {
                        const m = txt.match(/window\.__[A-Z_]+__\s*=\s*(\{[\s\S]*?\});/);
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

            # ── 2) DOM 파싱 ──
            html = await page.content()
            result["raw_html_snippet"] = html[:5000] if dev_mode else ""

            # 제목
            title = await page.evaluate("""() => {
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
            result["title"] = title

            # 가격
            prices = await page.evaluate("""() => {
                const out = { current: null, original: null, discount: null };
                // 현재가
                const priceSelectors = [
                    '[class*="price-current"]', '[class*="sale-price"]',
                    '[class*="final-price"]', '[class*="goods-price"]',
                    '[data-testid="goods-price"]',
                ];
                for (const s of priceSelectors) {
                    const el = document.querySelector(s);
                    if (el) { out.current = el.innerText.trim(); break; }
                }
                // 원가
                const origSelectors = [
                    '[class*="price-original"]', '[class*="origin-price"]',
                    '[class*="market-price"]', 'del', 's',
                ];
                for (const s of origSelectors) {
                    const el = document.querySelector(s);
                    if (el) { out.original = el.innerText.trim(); break; }
                }
                // 할인율
                const discSelectors = [
                    '[class*="discount"]', '[class*="off"]',
                    '[class*="percent"]',
                ];
                for (const s of discSelectors) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.includes('%')) { out.discount = el.innerText.trim(); break; }
                }
                // 숫자 없으면 meta 시도
                if (!out.current) {
                    const meta = document.querySelector('meta[property="product:price:amount"]');
                    if (meta) out.current = meta.content;
                }
                return out;
            }""")
            result["price_current"] = prices.get("current")
            result["price_original"] = prices.get("original")
            result["discount_rate"] = prices.get("discount")

            # 평점 / 리뷰 수 / 판매량
            stats = await page.evaluate("""() => {
                const out = { rating: null, reviews: null, sold: null };
                const ratingEl = document.querySelector(
                    '[class*="rating-score"], [class*="star-score"], [aria-label*="rating"]'
                );
                if (ratingEl) out.rating = ratingEl.innerText.trim();

                const reviewEl = document.querySelector(
                    '[class*="review-count"], [class*="rating-count"]'
                );
                if (reviewEl) out.reviews = reviewEl.innerText.trim();

                // 판매량 - 텍스트 기반 탐색
                const allText = document.body.innerText;
                const soldM = allText.match(/(\d[\d,]+)\s*(sold|판매|개 판매|개 팔린)/i);
                if (soldM) out.sold = soldM[0];
                return out;
            }""")
            result["rating"] = stats.get("rating")
            result["review_count"] = stats.get("reviews")
            result["sold_count"] = stats.get("sold")

            # 카테고리 경로(브레드크럼)
            cats = await page.evaluate("""() => {
                const breadcrumb = document.querySelector(
                    '[class*="breadcrumb"], [aria-label="breadcrumb"], nav[class*="crumb"]'
                );
                if (breadcrumb) {
                    return [...breadcrumb.querySelectorAll('a, span')]
                        .map(el => el.innerText.trim())
                        .filter(t => t && t !== '>' && t !== '/' && t.length < 60);
                }
                return [];
            }""")
            result["category_path"] = cats

            # 태그
            tags = await page.evaluate("""() => {
                const tagSelectors = [
                    '[class*="tag"]', '[class*="badge"]', '[class*="label"]',
                    '[class*="chip"]',
                ];
                const tags = new Set();
                for (const s of tagSelectors) {
                    document.querySelectorAll(s).forEach(el => {
                        const t = el.innerText.trim();
                        if (t && t.length < 40 && t.length > 1) tags.add(t);
                    });
                }
                return [...tags].slice(0, 30);
            }""")
            result["tags"] = tags

            # 상세 설명
            desc = await page.evaluate("""() => {
                const selectors = [
                    '[class*="description"]', '[class*="detail-desc"]',
                    '[class*="product-desc"]', '[class*="goods-desc"]',
                    '[data-testid="product-description"]',
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 20) {
                        return el.innerText.trim().slice(0, 2000);
                    }
                }
                return null;
            }""")
            result["description"] = desc

            # 상품 속성(스펙표)
            attrs = await page.evaluate("""() => {
                const rows = {};
                const attrSelectors = [
                    '[class*="attribute"]', '[class*="spec"]',
                    '[class*="property"]', '[class*="detail-attr"]',
                ];
                for (const s of attrSelectors) {
                    document.querySelectorAll(s).forEach(el => {
                        const key = el.querySelector('[class*="label"], [class*="key"], th, dt');
                        const val = el.querySelector('[class*="value"], [class*="content"], td, dd');
                        if (key && val) {
                            rows[key.innerText.trim()] = val.innerText.trim();
                        }
                    });
                }
                // 테이블 방식
                document.querySelectorAll('table tr').forEach(tr => {
                    const cells = tr.querySelectorAll('td, th');
                    if (cells.length === 2) {
                        rows[cells[0].innerText.trim()] = cells[1].innerText.trim();
                    }
                });
                return rows;
            }""")
            result["attributes"] = attrs

            # 셀러/브랜드
            seller = await page.evaluate("""() => {
                const selectors = [
                    '[class*="seller"]', '[class*="shop-name"]',
                    '[class*="brand"]', '[class*="store"]',
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim().length > 0) return el.innerText.trim();
                }
                return null;
            }""")
            result["seller"] = seller

            # ── 3) 키워드 자동 추출 ──
            result["keywords"] = _extract_keywords(result)

            # ── 4) meta keywords/description도 확인 ──
            meta_kw = await page.evaluate("""() => {
                const m = document.querySelector('meta[name="keywords"]');
                return m ? m.content : null;
            }""")
            if meta_kw:
                extra = [k.strip() for k in re.split(r'[,，]', meta_kw) if k.strip()]
                result["keywords"] = list(dict.fromkeys(result["keywords"] + extra))

            await browser.close()

    except Exception as e:
        result["error"] = str(e)

    return result


def _extract_keywords(result: dict) -> list[str]:
    """제목 + 카테고리 + 속성에서 키워드 자동 추출"""
    text_parts = []
    if result["title"]:
        text_parts.append(result["title"])
    text_parts.extend(result.get("category_path", []))
    for v in (result.get("attributes") or {}).values():
        text_parts.append(str(v))
    if result.get("description"):
        text_parts.append(result["description"][:500])

    combined = " ".join(text_parts)

    # 한국어 단어 (2글자 이상)
    ko_words = re.findall(r'[가-힣]{2,}', combined)
    # 영어 단어 (3글자 이상, 숫자 포함)
    en_words = re.findall(r'[A-Za-z][A-Za-z0-9\-]{2,}', combined)

    # 불용어
    stopwords = {
        '이다', '있다', '없다', '하다', '되다', '그리고', '또는', '또한',
        '에서', '으로', '에게', '부터', '까지', '상품', '제품', '판매',
        'the', 'and', 'for', 'with', 'this', 'that', 'from',
    }

    freq: dict[str, int] = {}
    for w in ko_words + en_words:
        w_lower = w.lower()
        if w_lower not in stopwords and len(w) > 1:
            freq[w] = freq.get(w, 0) + 1

    sorted_kw = sorted(freq.items(), key=lambda x: -x[1])
    return [k for k, _ in sorted_kw[:30]]


def run_scrape(url: str, dev_mode: bool, proxy: str | None = None) -> dict:
    """asyncio 이벤트 루프 실행 래퍼"""
    return asyncio.run(scrape_temu_product(url, dev_mode, proxy))


# ── UI ──────────────────────────────────────────────────
def main():
    # 사이드바
    with st.sidebar:
        st.markdown("## 🛒 테무 식품 스크래퍼")
        st.markdown("---")
        st.markdown("**사용법**")
        st.markdown("""
1. 테무 상품 URL 붙여넣기
2. 여러 URL은 한 줄에 하나씩
3. **스크래핑 시작** 클릭
        """)
        st.markdown("---")
        dev_mode = st.toggle("🔧 개발자 모드 (원본 JSON·HTML 표시)", value=True)
        st.markdown("---")
        st.markdown("**카테고리 필터 (수동)**")
        filter_price_max = st.number_input("최대 가격 (₩, 0=제한없음)", min_value=0, value=0, step=1000)
        st.markdown("---")
        st.markdown("---")
        proxy_input = st.text_input("🔒 프록시 (선택)", placeholder="http://127.0.0.1:7890", help="VPN/프록시 사용 시 입력")
        chromium_found = _find_chromium()
        if chromium_found:
            st.success(f"✅ Chromium 감지됨")
            st.caption(chromium_found)
        else:
            st.warning("⚠️ Chromium 미감지\n`playwright install chromium` 실행 필요")
        st.caption("Playwright + Chromium 기반\n정보 수집 목적 전용")

    # 메인
    st.markdown("# 🛒 테무 식품 카테고리 상품 분석기")
    st.markdown("테무 상품 링크를 넣으면 키워드·태그·가격·상세설명 등을 자동으로 추출해요.")

    # URL 입력
    url_input = st.text_area(
        "📎 테무 상품 URL (여러 개면 한 줄에 하나씩)",
        height=120,
        placeholder="https://www.temu.com/...\nhttps://www.temu.com/...",
    )

    col_btn, col_info = st.columns([2, 8])
    with col_btn:
        start = st.button("🚀 스크래핑 시작", type="primary", use_container_width=True)

    if start and url_input.strip():
        urls = [u.strip() for u in url_input.strip().splitlines() if u.strip().startswith("http")]
        if not urls:
            st.error("올바른 URL을 입력해주세요 (http로 시작)")
            return

        results = []
        prog = st.progress(0, text="준비 중...")
        for i, url in enumerate(urls):
            prog.progress((i) / len(urls), text=f"스크래핑 중... ({i+1}/{len(urls)}) {url[:60]}...")
            data = run_scrape(url, dev_mode, proxy_input.strip() or None)
            results.append(data)
            if i < len(urls) - 1:
                time.sleep(2)  # 서버 부하 방지

        prog.progress(1.0, text="완료!")
        time.sleep(0.5)
        prog.empty()

        # ── 결과 표시 ──
        for idx, r in enumerate(results):
            st.markdown(f"---")
            st.markdown(f"### 상품 {idx+1}")

            if r.get("error"):
                st.error(f"오류 발생: {r['error']}")
                if dev_mode:
                    st.code(r["error"])
                continue

            # 상단 요약
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                price_txt = r.get("price_current") or "정보없음"
                st.markdown(f'<div class="stat-box"><div class="stat-num">{price_txt}</div><div class="stat-label">현재가</div></div>', unsafe_allow_html=True)
            with c2:
                disc = r.get("discount_rate") or "-"
                st.markdown(f'<div class="stat-box"><div class="stat-num">{disc}</div><div class="stat-label">할인율</div></div>', unsafe_allow_html=True)
            with c3:
                rating = r.get("rating") or "-"
                st.markdown(f'<div class="stat-box"><div class="stat-num">{rating}</div><div class="stat-label">평점</div></div>', unsafe_allow_html=True)
            with c4:
                reviews = r.get("review_count") or "-"
                st.markdown(f'<div class="stat-box"><div class="stat-num">{reviews}</div><div class="stat-label">리뷰수</div></div>', unsafe_allow_html=True)

            st.markdown("")

            # 제목
            st.markdown(f'<div class="section-title">📌 상품명</div>', unsafe_allow_html=True)
            st.markdown(f"**{r.get('title') or '(제목 없음)'}**")

            # 카테고리
            if r.get("category_path"):
                st.markdown(f'<div class="section-title">📂 카테고리 경로</div>', unsafe_allow_html=True)
                st.markdown(" > ".join(r["category_path"]))

            # 키워드
            if r.get("keywords"):
                st.markdown(f'<div class="section-title">🔑 자동 추출 키워드</div>', unsafe_allow_html=True)
                chips = "".join([f'<span class="keyword-chip">{k}</span>' for k in r["keywords"]])
                st.markdown(chips, unsafe_allow_html=True)
                # 복사용 텍스트
                with st.expander("📋 키워드 복사 (쉼표 구분)"):
                    st.code(", ".join(r["keywords"]))

            # 태그
            if r.get("tags"):
                st.markdown(f'<div class="section-title">🏷️ 태그/뱃지</div>', unsafe_allow_html=True)
                chips = "".join([f'<span class="tag-chip">{t}</span>' for t in r["tags"]])
                st.markdown(chips, unsafe_allow_html=True)

            # 상세 설명
            if r.get("description"):
                st.markdown(f'<div class="section-title">📄 상세 설명</div>', unsafe_allow_html=True)
                st.text_area("", value=r["description"], height=200, key=f"desc_{idx}", label_visibility="collapsed")

            # 속성/스펙
            if r.get("attributes"):
                st.markdown(f'<div class="section-title">📊 상품 속성/스펙</div>', unsafe_allow_html=True)
                import pandas as pd
                df = pd.DataFrame(list(r["attributes"].items()), columns=["항목", "값"])
                st.dataframe(df, use_container_width=True, hide_index=True)

            # 셀러
            if r.get("seller"):
                st.markdown(f'<div class="section-title">🏪 셀러/브랜드</div>', unsafe_allow_html=True)
                st.info(r["seller"])

            # 가격 상세
            st.markdown(f'<div class="section-title">💰 가격 정보</div>', unsafe_allow_html=True)
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("현재가", r.get("price_current") or "-")
            pc2.metric("원가", r.get("price_original") or "-")
            pc3.metric("할인율", r.get("discount_rate") or "-")

            # URL & 수집 시각
            st.caption(f"🔗 URL: {r['url']}  |  🕐 수집: {r['scraped_at']}")

            # ── 개발자 모드 ──
            if dev_mode:
                st.markdown(f'<div class="section-title"><span class="dev-badge">DEV</span> 개발자 모드 — 원본 데이터</div>', unsafe_allow_html=True)

                tab_json, tab_html, tab_full = st.tabs(["📦 JSON 데이터", "🌐 HTML 스니펫", "📋 전체 파싱 결과"])

                with tab_json:
                    if r.get("raw_json"):
                        st.json(r["raw_json"])
                    else:
                        st.warning("페이지에서 JSON 데이터를 찾지 못했어요 (SPA 렌더링 완료 전일 수 있어요).")

                with tab_html:
                    if r.get("raw_html_snippet"):
                        st.code(r["raw_html_snippet"], language="html")
                    else:
                        st.info("개발자 모드에서만 HTML 스니펫이 표시됩니다.")

                with tab_full:
                    display_r = {k: v for k, v in r.items() if k not in ("raw_json", "raw_html_snippet")}
                    st.json(display_r)

            # JSON 다운로드
            st.download_button(
                label="⬇️ JSON으로 저장",
                data=json.dumps(r, ensure_ascii=False, indent=2),
                file_name=f"temu_product_{idx+1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                key=f"dl_{idx}",
            )

    elif start:
        st.warning("URL을 입력해주세요.")

    # ── 사용 가이드 (처음 화면) ──
    if not start:
        st.markdown("---")
        st.markdown("## 📖 사용 가이드")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
**추출 정보 목록**
- 📌 상품명
- 💰 현재가 / 원가 / 할인율
- ⭐ 평점 / 리뷰 수 / 판매량
- 📂 카테고리 경로 (브레드크럼)
- 🔑 자동 키워드 추출 (빈도 기반)
- 🏷️ 태그 / 뱃지
- 📄 상세 설명
- 📊 상품 속성 / 스펙
- 🏪 셀러 / 브랜드
""")
        with col2:
            st.markdown("""
**개발자 모드 활성화 시 추가**
- 📦 `__NEXT_DATA__` / `window.__*__` JSON 원본
- 🌐 HTML 소스 스니펫 (첫 5000자)
- 📋 전체 파싱 결과 JSON

**팁**
- 여러 상품 비교: URL을 여러 줄 입력
- JSON 저장 후 Excel에서 열어 분석 가능
- 테무 앱 → 공유 → 링크 복사로 URL 획득
""")
        st.info("💡 테무 상품 URL 예시: https://www.temu.com/goods.html?goods_id=601099512820537")


if __name__ == "__main__":
    main()
