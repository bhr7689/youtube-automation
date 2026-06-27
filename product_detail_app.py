"""제품 상세페이지 자동 생성 (식품 특화) — Streamlit 메인.

흐름:
  ① 사진 + 간단 정보 입력
  ② [생성] → Gemini 카피 + 디테일 이미지
  ③ 미리보기(HTML) + PNG/HTML 다운로드

설계 철학(=식품의 본질):
  맛있겠다 → 먹고 싶다 → 사고 싶다 → 사야겠다
"""
from __future__ import annotations

import io
import os
import time
from datetime import datetime

import streamlit as st
from PIL import Image

from product_detail.generator import generate_copy, CopyResult
from product_detail.image_gen import generate_detail_images
from product_detail.templates import render_page
from product_detail.exporter import html_to_png


# ───────────────────────────────────────────────────────────────────────────
# 페이지 기본 설정 (모바일 세로 우선)
st.set_page_config(
    page_title="제품 상세페이지 자동 생성",
    page_icon="🍱",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { max-width: 720px; padding-top: 1.2rem; padding-bottom: 4rem; }
      .stButton>button { width: 100%; font-weight: 700; }
      h1, h2, h3 { letter-spacing: -0.5px; }
      div[data-testid="stFileUploader"] section { padding: 1rem; }
      .small-note { color: #6b7280; font-size: 13px; }
      .funnel {
        display: flex; gap: 6px; margin: 4px 0 12px; flex-wrap: wrap;
      }
      .funnel span {
        background: #fff7ed; color: #9a3412; border: 1px solid #fdba74;
        border-radius: 999px; padding: 4px 10px; font-size: 13px; font-weight: 600;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ───────────────────────────────────────────────────────────────────────────
# 약관 / 개인정보처리방침 (URL 파라미터로 분리 페이지)
def _render_policy_terms() -> None:
    st.title("이용약관")
    st.markdown(
        """
**제1조 (목적)**
본 약관은 이용자가 본 서비스(AI 제품 상세페이지 자동 생성 도구)를 사용함에 있어
필요한 사항을 정합니다.

**제2조 (서비스 내용)**
이용자가 입력한 제품 정보·이미지를 바탕으로 AI가 상세페이지 카피와 이미지를
생성합니다. 생성 결과의 사용·게시·판매 책임은 이용자에게 있습니다.

**제3조 (금지 행위)**
① 타인의 저작권·초상권·상표권을 침해하는 입력
② 의학적 효능 단정, 허위·과장 광고
③ 식약처/표시광고법 등 관련 법령을 위반하는 카피 게시

**제4조 (면책)**
서비스는 입력에 기반한 자동 생성 결과를 제공하며, 최종 게시 전 이용자가
법령·플랫폼 정책 부합 여부를 직접 확인해야 합니다.
        """
    )
    st.link_button("← 돌아가기", url="?")


def _render_policy_privacy() -> None:
    st.title("개인정보처리방침")
    st.markdown(
        """
**1. 수집 항목**
- 입력한 제품명·메모·업로드한 이미지(처리 후 저장하지 않음)

**2. 수집 목적**
- 상세페이지 카피·이미지 생성

**3. 보관 기간**
- 생성 요청이 끝나면 즉시 메모리에서 폐기. 별도 서버 저장 없음.

**4. 제3자 제공**
- 카피·이미지 생성 시 Google Gemini API 로 입력값이 전송됩니다.

**5. 문의**
- 본 도구 운영자에게 직접 문의해 주세요.
        """
    )
    st.link_button("← 돌아가기", url="?")


_qp = st.query_params
_policy = (_qp.get("policy") or "").lower() if hasattr(_qp, "get") else ""
if _policy == "terms":
    _render_policy_terms()
    st.stop()
if _policy == "privacy":
    _render_policy_privacy()
    st.stop()


# ───────────────────────────────────────────────────────────────────────────
st.title("🍱 제품 상세페이지 자동 생성")
st.caption("사진 + 간단 정보만 넣으면 — AI가 식품 상세페이지를 만들어드려요.")
st.markdown(
    '<div class="funnel">'
    '<span>① 맛있겠다</span><span>② 먹고 싶다</span>'
    '<span>③ 사고 싶다</span><span>④ 사야겠다</span>'
    "</div>",
    unsafe_allow_html=True,
)

# 입력 UI ───────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("1. 제품 정보")

    cat_options = ["수산물", "농산물·과일", "정육·가공", "반찬·간식", "건강식품", "기타 식품"]
    category = st.selectbox("카테고리", cat_options, index=0)

    raw_name = st.text_input(
        "제품 이름/키워드",
        placeholder="예: 통영 손질 갈치, 제주 한라봉, 청정 한우 등심",
        help="대충 적어도 OK. AI가 다듬어줍니다.",
    )
    note = st.text_area(
        "메모 (원산지·중량·특징 등 — 자유롭게)",
        placeholder="예: 통영 욕지도산, 1kg 2~3마리, 비늘제거·내장손질, 진공포장",
        height=90,
    )

with st.container(border=True):
    st.subheader("2. 제품 사진")
    uploads = st.file_uploader(
        "사진 1장 이상 (JPG/PNG) — AI가 이걸 베이스로 디테일 컷도 만들어요",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

with st.expander("⚙️ 고급 옵션", expanded=False):
    api_key = st.text_input(
        "GEMINI_API_KEY (비우면 환경변수 사용 · 비었으면 안전 폴백 카피로 동작)",
        value="",
        type="password",
    )
    enable_image_gen = st.checkbox(
        "AI 이미지 생성 사용 (Gemini 이미지)",
        value=True,
        help="끄면 업로드 사진만 사용합니다.",
    )

go = st.button("✨ 상세페이지 만들기", type="primary")


# ───────────────────────────────────────────────────────────────────────────
def _load_first_image(files) -> Image.Image | None:
    if not files:
        return None
    try:
        return Image.open(files[0]).convert("RGB")
    except Exception:
        return None


if go:
    if not raw_name and not uploads:
        st.warning("제품 이름이나 사진 중 하나는 꼭 넣어주세요.")
        st.stop()

    key = api_key.strip() or os.getenv("GEMINI_API_KEY", "")
    if not key:
        st.info(
            "GEMINI_API_KEY 가 없어 **안전 폴백 카피**로 보여드려요. "
            "키를 넣으면 더 제품에 맞춘 카피·이미지를 생성합니다."
        )

    base_img = _load_first_image(uploads)

    with st.spinner("AI가 카피를 다듬는 중…"):
        copy: CopyResult = generate_copy(
            raw_name=raw_name, category=category, note=note, api_key=key or None
        )

    images: dict = {}
    if base_img is not None:
        if enable_image_gen and key:
            with st.spinner("AI가 디테일 이미지를 그리는 중…"):
                gens = generate_detail_images(
                    base_img,
                    prompts=copy.image_prompts or {},
                    api_key=key,
                    max_count=3,
                )
            for g in gens:
                images[g.label] = g.image
            ai_count = sum(1 for g in gens if g.is_generated)
            if ai_count == 0:
                st.warning(
                    "이미지 생성 결과가 없어 업로드 사진을 그대로 사용했어요. "
                    "(모델 권한/리전 문제일 수 있어요)"
                )
        else:
            # 업로드 사진을 모든 슬롯에
            for label in ("hero", "close_up", "cook_example"):
                images[label] = base_img

    html = render_page(copy, images, include_ad_slot=True)

    st.session_state["last_html"] = html
    st.session_state["last_copy"] = copy.to_dict()
    st.session_state["last_ts"] = datetime.now().strftime("%Y%m%d_%H%M%S")


# ───────────────────────────────────────────────────────────────────────────
# 결과 표시
if st.session_state.get("last_html"):
    html = st.session_state["last_html"]
    ts = st.session_state.get("last_ts", "")
    st.markdown("---")
    st.subheader("3. 미리보기")
    st.caption("실제 모바일 화면에서 보이는 모습이에요. 마음에 안 드는 문구는 다시 만들 수 있어요.")
    st.components.v1.html(html, height=1600, scrolling=True)

    st.markdown("---")
    st.subheader("4. 다운로드")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📄 HTML 다운로드",
            data=html.encode("utf-8"),
            file_name=f"product_detail_{ts}.html",
            mime="text/html",
            use_container_width=True,
        )
    with col2:
        if st.button("🖼️ PNG로 저장", use_container_width=True):
            with st.spinner("페이지를 한 장 PNG로 캡처 중…"):
                png = html_to_png(html)
            if png:
                st.session_state["last_png"] = png
            else:
                st.error(
                    "PNG 저장에 실패했어요. (Playwright/Chromium 환경 문제) "
                    "HTML 다운로드 후 브라우저에서 캡처해 주세요."
                )

    if st.session_state.get("last_png"):
        st.download_button(
            "⬇️ PNG 다운로드",
            data=st.session_state["last_png"],
            file_name=f"product_detail_{ts}.png",
            mime="image/png",
            use_container_width=True,
        )

    with st.expander("🪄 생성된 카피 JSON (참고용)"):
        st.json(st.session_state.get("last_copy", {}))


# 푸터 (앱인토스 정책: 약관·개인정보처리방침 링크 필수)
st.markdown("---")
st.markdown(
    '<div class="small-note" style="text-align:center;">'
    '<a href="?policy=terms">이용약관</a> · '
    '<a href="?policy=privacy">개인정보처리방침</a>'
    "</div>",
    unsafe_allow_html=True,
)
