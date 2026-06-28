"""
쇼핑 숏폼 대본 자동화
- 레퍼런스 영상 구조 분석 + 상품 소구점 분석 → 새 대본 자동 생성
- 입력: 1 레퍼런스(MP4/URL)  2 상품URL
"""

import streamlit as st
import os
import re
import json
import tempfile
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="쇼핑 숏폼 대본 자동화",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.section-card {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
.badge {
    display: inline-block;
    background: #89b4fa;
    color: #1e1e2e;
    border-radius: 20px;
    padding: 2px 12px;
    font-size: 13px;
    font-weight: 700;
    margin-right: 6px;
}
.badge-green { background: #a6e3a1; }
.badge-yellow { background: #f9e2af; }
.badge-red { background: #f38ba8; }
.step-title {
    font-size: 1.1rem; font-weight: 700;
    border-left: 4px solid #89b4fa;
    padding-left: 10px; margin: 20px 0 10px 0;
}
</style>
""", unsafe_allow_html=True)


# ── Gemini 호출 ────────────────────────────────────────────
def call_gemini(prompt: str, api_key: str) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        return f"[Gemini 오류] {e}"


# ── Playwright로 URL 콘텐츠 수집 ──────────────────────────
def fetch_url_content(url: str) -> dict:
    """URL 페이지 텍스트, 제목, 설명 추출"""
    core = Path(__file__).parent / "url_fetcher.py"
    # 인라인 스크립트로 실행
    script = f"""
import sys, json
from playwright.sync_api import sync_playwright
import os, shutil

def find_chromium():
    candidates = [
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/usr/bin/chromium-browser", "/usr/bin/chromium",
    ]
    for c in candidates:
        if os.path.exists(c): return c
    for name in ("chromium-browser","chromium","google-chrome","chrome"):
        import shutil
        f = shutil.which(name)
        if f: return f
    return None

url = {json.dumps(url)}
result = {{"title":"","description":"","text":"","error":""}}
try:
    with sync_playwright() as p:
        opts = {{"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"]}}
        cp = find_chromium()
        if cp: opts["executable_path"] = cp
        b = p.chromium.launch(**opts)
        ctx = b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            locale="ko-KR"
        )
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(3000)
        result["title"] = pg.title()
        result["description"] = pg.evaluate("()=>{{const m=document.querySelector('meta[name=description]');return m?m.content:''}}")
        result["text"] = pg.evaluate("()=>document.body.innerText.slice(0,5000)")
        b.close()
except Exception as e:
    result["error"] = str(e)
print(json.dumps(result, ensure_ascii=False))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=45, encoding="utf-8"
        )
        if proc.stdout.strip():
            return json.loads(proc.stdout.strip())
        return {"error": proc.stderr.strip() or "출력 없음", "title": "", "description": "", "text": ""}
    except Exception as e:
        return {"error": str(e), "title": "", "description": "", "text": ""}


# ── MP4 분석 ──────────────────────────────────────────────
def analyze_mp4(file_path: str, api_key: str) -> str:
    """ffprobe로 메타데이터 추출 후 Gemini로 분석"""
    meta = {}
    try:
        import subprocess as sp
        r = sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
            capture_output=True, text=True, timeout=15
        )
        meta = json.loads(r.stdout) if r.stdout else {}
    except Exception:
        pass

    duration = "알 수 없음"
    try:
        duration = f"{float(meta.get('format', {}).get('duration', 0)):.1f}초"
    except Exception:
        pass

    prompt = f"""
아래는 쇼핑 숏폼 영상 파일의 메타데이터입니다.
파일: {file_path}
재생 시간: {duration}
메타: {json.dumps(meta, ensure_ascii=False)[:1000]}

이 정보를 바탕으로 아래 항목을 추정해 분석해주세요.
(실제 영상을 볼 수 없으므로, 파일명과 메타에서 파악 가능한 것만 서술하고 나머지는 "직접 확인 필요"로 표시)

1. 예상 플랫폼 및 영상 유형
2. 영상 길이 기반 예상 구조 (초반 훅 / 중반 정보 / 후반 CTA)
3. 쇼핑 숏폼으로서 분석해야 할 핵심 포인트
4. 사용자가 직접 확인해야 할 항목 목록
"""
    return call_gemini(prompt, api_key)


# ── 레퍼런스 영상 구조 분석 ───────────────────────────────
def analyze_reference(source: str, source_type: str, api_key: str, url_data: dict = None) -> str:
    if source_type == "mp4":
        raw = analyze_mp4(source, api_key)
    else:
        raw = f"""
제목: {url_data.get('title', '')}
설명: {url_data.get('description', '')}
페이지 텍스트: {url_data.get('text', '')[:2000]}
"""

    prompt = f"""
당신은 쇼핑 숏폼 대본 전문가입니다.
아래는 레퍼런스(떡상한) 영상에서 수집한 정보입니다.

{raw}

다음 항목을 분석해주세요. 확인되지 않은 내용은 "추정" 또는 "직접 확인 필요"로 명시하세요.

## 한눈에 보기
- 핵심 소재:
- 예상 타깃:
- 첫 3초 훅:
- 핵심 감정:
- 영상의 약속:
- 최종 보상:
- 구매/행동 유도 방식:

## 구간별 구조 분석
| 구간 | 역할 | 사용 장치 | 시청자에게 주는 효과 |
|---|---|---|---|
| 도입 | | | |
| 문제 제기 | | | |
| 상품/해결책 등장 | | | |
| 사용 장면/근거 | | | |
| 반전/강화 | | | |
| CTA | | | |

## 흥행 요인 (추정)
1.
2.
3.

## 새 대본에 가져올 원리
- 훅 원리:
- 문제 제기 방식:
- 정보 공개 순서:
- 감정선:
- 상품 등장 타이밍:
- CTA 구조:

## 복제하면 안 되는 요소
- 고유 문장:
- 고유 비유:
- 고유 장면 배열:
"""
    return call_gemini(prompt, api_key)


# ── 상품 소구점 분석 ──────────────────────────────────────
def analyze_product(url_data: dict, api_key: str) -> str:
    raw = f"""
제목: {url_data.get('title', '')}
설명: {url_data.get('description', '')}
페이지 텍스트: {url_data.get('text', '')[:3000]}
"""
    prompt = f"""
당신은 쇼핑 숏폼 마케팅 전문가입니다.
아래는 판매할 상품 페이지에서 수집한 정보입니다.

{raw}

다음 항목으로 소구점을 분석해주세요. 확인되지 않은 수치/효능/후기는 절대 사실처럼 쓰지 마세요.

## 상품 기본 정보
- 상품명:
- 가격대 (확인된 경우):
- 타깃:

## 소구점 분석
- 기능적 소구 (실제 확인된 기능):
- 감정적 소구 (어떤 감정을 건드리는가):
- 상황적 소구 (어떤 상황에서 필요한가):
- 비교 소구 (경쟁 대비 차별점, 확인된 것만):
- 구매 전환 포인트:

## 숏폼 대본에 쓸 핵심 메시지 (3가지)
1.
2.
3.

## 주의할 표현
- 사실 확인 필요한 내용:
- 과장 위험 표현:
- 쓰면 안 되는 표현:
"""
    return call_gemini(prompt, api_key)


# ── 대본 생성 ─────────────────────────────────────────────
def generate_script(ref_analysis: str, product_analysis: str, product_name: str,
                    platform: str, duration: str, tone: str, api_key: str) -> str:
    prompt = f"""
당신은 쇼핑 숏폼 대본 전문가입니다.

## 레퍼런스 영상 구조 분석
{ref_analysis}

## 상품 소구점 분석
{product_analysis}

## 대본 조건
- 상품명: {product_name}
- 플랫폼: {platform}
- 목표 길이: {duration}
- 말투: {tone}

## 작성 규칙
1. 첫 1~3초: 상품명보다 시청자의 문제/욕망/상황을 먼저 제시
2. 상품 설명: "누가, 언제, 왜 필요한지" 중심으로 풀기
3. 사용 장면, 전후 차이, 선택 이유를 보여주기
4. 레퍼런스의 고유 문장·장면 배열·비유·결론은 절대 복제 금지
5. 확인되지 않은 효능·수치·후기·의학 표현 금지
6. CTA는 플랫폼에 맞게 자연스럽게

## 출력 형식

### 선택한 구조
(레퍼런스에서 가져온 구조 원리)

### 핵심 소구점
(이 대본에서 강조할 핵심 3가지)

### 최종 대본
```
[0~3초] 훅
[3~8초] 문제 제기
[8~18초] 해결책 / 상품 소개
[18~25초] 사용 장면 / 근거
[25~30초] CTA
```

### 주의할 표현
(이 대본에서 확인·수정이 필요한 부분)
"""
    return call_gemini(prompt, api_key)


# ── UI ────────────────────────────────────────────────────
def main():
    if "ref_analysis" not in st.session_state:
        st.session_state.ref_analysis = ""
    if "product_analysis" not in st.session_state:
        st.session_state.product_analysis = ""
    if "final_script" not in st.session_state:
        st.session_state.final_script = ""
    if "product_name" not in st.session_state:
        st.session_state.product_name = "상품"

    # ── 사이드바 ──
    with st.sidebar:
        st.markdown("## 🎬 숏폼 대본 자동화")
        st.markdown("---")
        api_key = st.text_input(
            "🔑 Gemini API 키",
            value=os.getenv("GEMINI_API_KEY", ""),
            type="password",
            help="https://aistudio.google.com/app/apikey 에서 발급",
        )
        st.markdown("---")
        platform = st.selectbox("📱 플랫폼", ["Instagram 릴스", "TikTok", "YouTube 쇼츠", "네이버 클립"])
        duration = st.selectbox("⏱️ 목표 길이", ["20~30초", "30~45초", "45~60초", "60초 이상"])
        tone = st.selectbox("💬 말투", ["구어체 (친근하게)", "공식체 (신뢰감)", "MZ 말투 (재미있게)", "전문가 말투"])
        st.markdown("---")
        st.markdown("**사용법**")
        st.markdown("""
1. Gemini API 키 입력
2. 레퍼런스 영상 입력 (MP4 또는 URL)
3. 상품 URL 입력
4. 분석 시작 클릭
5. 대본 자동 생성!
""")

    st.markdown("# 🎬 쇼핑 숏폼 대본 자동화")
    st.markdown("떡상한 영상 구조 + 내 상품 소구점 → 새 대본 자동 생성")

    if not api_key:
        st.warning("⚠️ 사이드바에서 Gemini API 키를 입력해주세요.")
        st.info("발급: https://aistudio.google.com/app/apikey (무료)")
        return

    st.markdown("---")

    # ── 입력 영역 ──
    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="step-title"><span class="badge">1</span> 레퍼런스 영상 (떡상한 영상)</div>', unsafe_allow_html=True)
        ref_type = st.radio("입력 방식", ["URL", "MP4 파일 업로드"], horizontal=True, key="ref_type")

        if ref_type == "URL":
            ref_url = st.text_input("레퍼런스 영상 URL", placeholder="https://www.instagram.com/reel/...")
            ref_file = None
        else:
            ref_file = st.file_uploader("MP4 파일", type=["mp4", "mov", "avi"])
            ref_url = None

    with col2:
        st.markdown('<div class="step-title"><span class="badge badge-green">2</span> 상품 영상/페이지 URL</div>', unsafe_allow_html=True)
        product_url = st.text_input("상품 URL", placeholder="https://www.temu.com/... 또는 인스타 상품 영상 URL")
        product_name_input = st.text_input("상품명 (모르면 비워두세요)", placeholder="예: 국산 김 세트")

    st.markdown("")
    start_btn = st.button("🚀 분석 시작 → 대본 생성", type="primary", use_container_width=True)

    if start_btn:
        # 입력 확인
        has_ref = (ref_url and ref_url.strip()) or ref_file
        has_product = product_url and product_url.strip()

        if not has_ref:
            st.error("레퍼런스 영상을 입력해주세요.")
            return
        if not has_product:
            st.error("상품 URL을 입력해주세요.")
            return

        prog = st.progress(0, text="시작 중...")

        # ── 1단계: 레퍼런스 분석 ──
        prog.progress(0.1, text="🔍 레퍼런스 영상 분석 중...")
        url_data_ref = {}
        if ref_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                tmp.write(ref_file.read())
                tmp_path = tmp.name
            ref_analysis = analyze_reference(tmp_path, "mp4", api_key)
            os.unlink(tmp_path)
        else:
            url_data_ref = fetch_url_content(ref_url.strip())
            ref_analysis = analyze_reference(ref_url.strip(), "url", api_key, url_data_ref)

        st.session_state.ref_analysis = ref_analysis
        prog.progress(0.4, text="✅ 레퍼런스 분석 완료! 상품 소구점 분석 중...")

        # ── 2단계: 상품 소구점 분석 ──
        url_data_product = fetch_url_content(product_url.strip())
        product_analysis = analyze_product(url_data_product, api_key)
        st.session_state.product_analysis = product_analysis

        # 상품명 추출
        if product_name_input.strip():
            pname = product_name_input.strip()
        else:
            title = url_data_product.get("title", "상품")
            pname = title.split("|")[0].split("-")[0].strip()[:20] or "상품"
        st.session_state.product_name = pname

        prog.progress(0.7, text="✅ 소구점 분석 완료! 대본 생성 중...")

        # ── 3단계: 대본 생성 ──
        final_script = generate_script(
            ref_analysis, product_analysis, pname,
            platform, duration, tone, api_key
        )
        st.session_state.final_script = final_script

        prog.progress(1.0, text="🎉 완료!")
        import time; time.sleep(0.5)
        prog.empty()
        st.rerun()

    # ── 결과 표시 ──
    if st.session_state.final_script:
        st.markdown("---")
        tab1, tab2, tab3 = st.tabs(["✍️ 최종 대본", "🔍 레퍼런스 분석", "🛒 소구점 분석"])

        with tab1:
            st.markdown(f"### ✍️ [{st.session_state.product_name}] 쇼핑 숏폼 대본")
            st.markdown(st.session_state.final_script)

            # 저장 버튼
            fname = f"{st.session_state.product_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            content = f"# {st.session_state.product_name} 쇼핑 숏폼 대본\n\n생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            content += st.session_state.final_script
            st.download_button("⬇️ 대본 저장 (.md)", data=content, file_name=fname, mime="text/markdown")

        with tab2:
            st.markdown("### 🔍 레퍼런스 영상 구조 분석")
            st.markdown(st.session_state.ref_analysis)
            st.download_button(
                "⬇️ 레퍼런스 분석 저장",
                data=st.session_state.ref_analysis,
                file_name=f"레퍼런스분석_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                key="dl_ref",
            )

        with tab3:
            st.markdown("### 🛒 상품 소구점 분석")
            st.markdown(st.session_state.product_analysis)
            st.download_button(
                "⬇️ 소구점 분석 저장",
                data=st.session_state.product_analysis,
                file_name=f"소구점분석_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                key="dl_product",
            )

    elif not start_btn:
        st.markdown("---")
        st.info("""
**📖 사용 예시**

```
레퍼런스: https://www.instagram.com/reel/떡상영상/
상품: https://www.temu.com/상품페이지
```

또는

```
레퍼런스: 참고영상.mp4 (파일 업로드)
상품: https://smartstore.naver.com/상품
```

**결과물**
- ✍️ 최종 대본 (구조 + 소구점 + 대본 + 주의 표현)
- 🔍 레퍼런스 분석 (흥행 원리)
- 🛒 소구점 분석 (구매 이유)
""")


if __name__ == "__main__":
    main()
