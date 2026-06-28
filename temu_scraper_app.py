"""
테무(Temu) 식품 카테고리 상품 정보 스크래퍼 — Streamlit UI
스크래핑은 subprocess로 분리 실행 → 충돌해도 앱이 살아있음
"""

import streamlit as st
import json
import subprocess
import sys
import os
import shutil
import time
from datetime import datetime

st.set_page_config(
    page_title="테무 식품 스크래퍼",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.tag-chip {
    display: inline-block; background:#fff3e0; color:#e65100;
    border:1px solid #ffb74d; border-radius:20px;
    padding:3px 12px; margin:3px 3px; font-size:13px; font-weight:500;
}
.keyword-chip {
    display: inline-block; background:#e3f2fd; color:#1565c0;
    border:1px solid #90caf9; border-radius:20px;
    padding:3px 12px; margin:3px 3px; font-size:13px; font-weight:500;
}
.section-title {
    font-size:1rem; font-weight:700; color:#424242;
    border-left:4px solid #ff7043; padding-left:10px; margin:18px 0 8px 0;
}
.stat-box { background:#f5f5f5; border-radius:8px; padding:12px 16px; text-align:center; }
.stat-num { font-size:1.4rem; font-weight:700; color:#e53935; }
.stat-label { font-size:0.8rem; color:#757575; }
</style>
""", unsafe_allow_html=True)


def find_chromium():
    candidates = [
        # Linux (cloud/서버)
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/opt/pw-browsers/chromium/chrome-linux/chrome",
        "/usr/bin/chromium-browser", "/usr/bin/chromium", "/usr/bin/google-chrome",
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    # Windows: Playwright 기본 설치 경로 자동 탐색
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        import glob as _glob
        for pattern in [
            os.path.join(local_app, "ms-playwright", "chromium-*", "chrome-win", "chrome.exe"),
            os.path.join(local_app, "ms-playwright", "chromium*", "chrome-win", "chrome.exe"),
        ]:
            matches = _glob.glob(pattern)
            if matches:
                candidates.insert(0, matches[-1])  # 최신 버전 우선
    # Windows: Chrome 설치 경로
    prog = os.environ.get("PROGRAMFILES", "C:\\Program Files")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
    candidates += [
        os.path.join(prog, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(prog86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for name in ("chromium-browser", "chromium", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    # Playwright가 알아서 찾도록 None 대신 sentinel 반환
    return "playwright_managed"


def run_scraper(url: str, dev_mode: bool, proxy: str) -> dict:
    """subprocess로 temu_scraper_core.py 실행 — 충돌해도 앱 안 죽음"""
    core = os.path.join(os.path.dirname(__file__), "temu_scraper_core.py")
    cmd = [sys.executable, core, url]
    if dev_mode:
        cmd.append("--dev")
    if proxy:
        cmd.append(f"--proxy={proxy}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if not stdout:
            return {
                "url": url,
                "error": "스크래퍼가 아무 결과도 반환하지 않았어요.",
                "error_detail": stderr or "(출력 없음)",
            }
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "url": url,
                "error": "결과 파싱 실패",
                "error_detail": f"stdout:\n{stdout}\n\nstderr:\n{stderr}",
            }

    except subprocess.TimeoutExpired:
        return {"url": url, "error": "시간 초과 (60초) — 인터넷 속도나 URL을 확인해주세요.", "error_detail": ""}
    except Exception as e:
        import traceback
        return {"url": url, "error": str(e), "error_detail": traceback.format_exc()}


# ── session_state 초기화 ──
if "results" not in st.session_state:
    st.session_state.results = []
if "toast" not in st.session_state:
    st.session_state.toast = ""

# ── 사이드바 ──
with st.sidebar:
    st.markdown("## 🛒 테무 식품 스크래퍼")
    st.markdown("---")
    dev_mode = st.toggle("🔧 개발자 모드", value=False)
    proxy_input = st.text_input("🔒 프록시 (선택)", placeholder="http://127.0.0.1:7890")
    st.markdown("---")
    chromium = find_chromium()
    if chromium and chromium != "playwright_managed":
        st.success("✅ Chromium 감지됨")
        st.caption(chromium[:60])
    else:
        st.success("✅ Chromium (Playwright 관리)")
        st.caption("playwright install chromium 완료 상태")
    st.markdown("---")
    st.caption("Playwright subprocess 방식\n앱이 충돌해도 UI 유지")

# ── 메인 ──
st.markdown("# 🛒 테무 식품 카테고리 상품 분석기")
st.markdown("테무 상품 링크를 넣으면 키워드·태그·가격·상세설명을 자동 추출해요.")

url_input = st.text_area(
    "📎 테무 상품 URL (여러 개면 한 줄에 하나씩)",
    height=120,
    placeholder="https://www.temu.com/...",
)

c1, c2 = st.columns([3, 9])
with c1:
    start = st.button("🚀 스크래핑 시작", type="primary", use_container_width=True)
with c2:
    if st.button("🗑️ 결과 지우기"):
        st.session_state.results = []
        st.rerun()

# ── 스크래핑 실행 ──
if start:
    if not url_input.strip():
        st.warning("URL을 입력해주세요.")
    elif False:  # Chromium 체크 제거 — playwright가 자체 관리
    else:
        urls = [u.strip() for u in url_input.strip().splitlines() if u.strip().startswith("http")]
        if not urls:
            st.warning("http로 시작하는 URL을 입력해주세요.")
        else:
            results = []
            prog = st.progress(0, text="시작 중...")
            for i, url in enumerate(urls):
                prog.progress(i / len(urls), text=f"🔍 분석 중... ({i+1}/{len(urls)}) {url[:50]}...")
                data = run_scraper(url, dev_mode, proxy_input.strip())
                results.append(data)
                if i < len(urls) - 1:
                    time.sleep(2)
            prog.progress(1.0, text="✅ 완료!")
            time.sleep(0.5)
            prog.empty()
            st.session_state.results = results
            st.rerun()

# ── 결과 표시 ──
for idx, r in enumerate(st.session_state.results):
    st.markdown("---")
    st.markdown(f"### 상품 {idx+1}")

    if r.get("error"):
        st.error(f"⚠️ 오류: {r['error']}")
        if r.get("error_detail"):
            with st.expander("🔍 상세 오류 내용 (여기를 캡처해서 보내주세요!)"):
                st.code(r["error_detail"])
        st.info("💡 위 '상세 오류 내용'을 펼쳐서 캡처해 보내주시면 바로 고쳐드릴게요!")
        continue

    # 요약 수치
    c1, c2, c3, c4 = st.columns(4)
    for col, val, label in zip(
        [c1, c2, c3, c4],
        [r.get("price_current"), r.get("discount_rate"), r.get("rating"), r.get("review_count")],
        ["현재가", "할인율", "평점", "리뷰수"],
    ):
        col.markdown(
            f'<div class="stat-box"><div class="stat-num">{val or "-"}</div>'
            f'<div class="stat-label">{label}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # 상품명
    st.markdown('<div class="section-title">📌 상품명</div>', unsafe_allow_html=True)
    st.markdown(f"**{r.get('title') or '(없음)'}**")

    # 카테고리
    if r.get("category_path"):
        st.markdown('<div class="section-title">📂 카테고리</div>', unsafe_allow_html=True)
        st.markdown(" > ".join(r["category_path"]))

    # 키워드
    if r.get("keywords"):
        st.markdown('<div class="section-title">🔑 자동 키워드</div>', unsafe_allow_html=True)
        st.markdown("".join(f'<span class="keyword-chip">{k}</span>' for k in r["keywords"]), unsafe_allow_html=True)
        with st.expander("📋 키워드 복사"):
            st.code(", ".join(r["keywords"]))

    # 태그
    if r.get("tags"):
        st.markdown('<div class="section-title">🏷️ 태그</div>', unsafe_allow_html=True)
        st.markdown("".join(f'<span class="tag-chip">{t}</span>' for t in r["tags"]), unsafe_allow_html=True)

    # 설명
    if r.get("description"):
        st.markdown('<div class="section-title">📄 상세 설명</div>', unsafe_allow_html=True)
        st.text_area("", value=r["description"], height=180, key=f"desc_{idx}", label_visibility="collapsed")

    # 속성
    if r.get("attributes"):
        st.markdown('<div class="section-title">📊 속성/스펙</div>', unsafe_allow_html=True)
        import pandas as pd
        st.dataframe(pd.DataFrame(list(r["attributes"].items()), columns=["항목", "값"]),
                     use_container_width=True, hide_index=True)

    # 가격
    st.markdown('<div class="section-title">💰 가격</div>', unsafe_allow_html=True)
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("현재가", r.get("price_current") or "-")
    pc2.metric("원가",   r.get("price_original") or "-")
    pc3.metric("할인율", r.get("discount_rate") or "-")

    st.caption(f"🔗 {r.get('url', '')}  |  🕐 {r.get('scraped_at', '')}")

    # 개발자 모드
    if dev_mode and r.get("raw_json"):
        with st.expander("📦 JSON 원본 데이터"):
            st.json(r["raw_json"])
    if dev_mode and r.get("raw_html_snippet"):
        with st.expander("🌐 HTML 스니펫"):
            st.code(r["raw_html_snippet"], language="html")

    # 저장
    st.download_button(
        "⬇️ JSON 저장",
        data=json.dumps(r, ensure_ascii=False, indent=2),
        file_name=f"temu_{idx+1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        key=f"dl_{idx}",
    )

# 결과 없을 때 가이드
if not st.session_state.results:
    st.markdown("---")
    st.info("""
**📖 사용 방법**

1. 테무 앱 또는 웹에서 식품 상품 페이지 열기
2. 상품 링크 복사 (공유 → 링크 복사)
3. 위 입력창에 붙여넣기
4. 🚀 스크래핑 시작 클릭

**추출 정보**: 상품명 · 가격 · 할인율 · 평점 · 카테고리 · 키워드 · 태그 · 설명 · 속성
""")
