"""제품 상세페이지 자동 생성 (식품 특화) — Streamlit 메인.

흐름:
  ① 사진 + (선택) 움짤 + 간단 정보 입력
  ② [생성] → Gemini / GPT / 둘 다 비교
  ③ 카피 선택 → 디테일 이미지 생성 → HTML 미리보기 → PNG/HTML 다운로드

설계(=식품의 본질): 맛있겠다 → 먹고 싶다 → 사고 싶다 → 사야겠다
"""
from __future__ import annotations

import os
from datetime import datetime

import streamlit as st
from PIL import Image

from product_detail.generator import (
    generate_copy,
    generate_copy_compare,
    CopyResult,
)
from product_detail.image_gen import generate_detail_images
from product_detail.templates import render_page, _video_to_data_uri
from product_detail.exporter import html_to_png


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
      .funnel { display: flex; gap: 6px; margin: 4px 0 12px; flex-wrap: wrap; }
      .funnel span {
        background: #fff7ed; color: #9a3412; border: 1px solid #fdba74;
        border-radius: 999px; padding: 4px 10px; font-size: 13px; font-weight: 600;
      }
      .compare-card {
        border: 2px solid #e5e7eb; border-radius: 14px;
        padding: 14px 16px; margin-bottom: 10px; background: #fff;
      }
      .compare-card h4 { margin: 0 0 6px; font-size: 16px; }
      .compare-card .meta { font-size: 12px; color: #9ca3af; }
      .compare-card .body { font-size: 14px; color: #1f2937; line-height: 1.5; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ───────────────────────────────────────────────────────────────────────────
# 약관 / 개인정보처리방침
def _render_policy_terms() -> None:
    st.title("이용약관")
    st.markdown(
        """
**제1조 (목적)** 본 약관은 이용자가 본 서비스(AI 제품 상세페이지 자동 생성 도구)를
사용함에 있어 필요한 사항을 정합니다.

**제2조 (서비스 내용)** 이용자가 입력한 제품 정보·이미지·영상을 바탕으로 AI가
상세페이지 카피와 이미지를 생성합니다. 생성 결과의 사용·게시·판매 책임은
이용자에게 있습니다.

**제3조 (금지 행위)**
① 타인의 저작권·초상권·상표권을 침해하는 입력
② 의학적 효능 단정, 허위·과장 광고
③ 식약처/표시광고법 등 관련 법령을 위반하는 카피 게시

**제4조 (면책)** 서비스는 자동 생성 결과를 제공하며, 최종 게시 전 이용자가
법령·플랫폼 정책 부합 여부를 직접 확인해야 합니다.
        """
    )
    st.link_button("← 돌아가기", url="?")


def _render_policy_privacy() -> None:
    st.title("개인정보처리방침")
    st.markdown(
        """
**1. 수집 항목** 입력한 제품명·메모·업로드한 이미지/영상(처리 후 저장하지 않음)

**2. 수집 목적** 상세페이지 카피·이미지 생성

**3. 보관 기간** 생성 요청이 끝나면 즉시 메모리에서 폐기. 별도 서버 저장 없음.

**4. 제3자 제공** 카피·이미지 생성 시 Google Gemini / OpenAI API 로 입력값이
전송됩니다. (이용자가 선택한 모델에 한함)

**5. 문의** 본 도구 운영자에게 직접 문의해 주세요.
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
st.caption("사진 + 움짤 + 간단 정보만 넣으면 — AI가 식품 상세페이지를 만들어드려요.")
st.markdown(
    '<div class="funnel">'
    '<span>① 맛있겠다</span><span>② 먹고 싶다</span>'
    '<span>③ 사고 싶다</span><span>④ 사야겠다</span>'
    "</div>",
    unsafe_allow_html=True,
)


# 입력 ──────────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("1. 제품 정보")

    cat_options = ["수산물", "농산물·과일", "정육·가공", "반찬·간식", "건강식품", "기타 식품"]
    category = st.selectbox("카테고리", cat_options, index=0)

    raw_name = st.text_input(
        "제품 이름/키워드",
        placeholder="예: 해남 꿀고구마, 통영 손질 갈치, 제주 한라봉",
    )
    note = st.text_area(
        "메모 (원산지·중량·특징 자유롭게)",
        placeholder="예: 해남산, 1박스 3kg(약 10~14개), 진공포장",
        height=90,
    )

# 페이지 이미지 자리 6곳 — 업로드 사진을 순서대로 자동 배정
SLOT_DEFS = [
    ("hero", "① 메인(히어로)"),
    ("close_up", "② 맛 클로즈업"),
    ("size_compare", "③ 크기/실측"),
    ("farm", "④ 산지/생산자"),
    ("package", "⑤ 포장/박스"),
    ("cook_example", "⑥ 조리/활용"),
]

with st.container(border=True):
    st.subheader("2. 제품 사진 (여러 장 올리세요)")
    uploads = st.file_uploader(
        "사진 여러 장 (JPG/PNG/WEBP) — 올린 순서대로 페이지 자리에 자동 배치돼요",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )
    if uploads:
        st.caption(
            "자리 배정 (기본: 올린 순서). 남는 사진은 페이지 중간 **'생생한 현장 컷'** 띠로 전부 들어가요."
        )
        _names = [f.name for f in uploads]
        _cols = st.columns(3)
        for _i, (_key, _label) in enumerate(SLOT_DEFS):
            with _cols[_i % 3]:
                _default = _names[_i] if _i < len(_names) else "(없음)"
                _options = ["(없음)"] + _names
                _idx = _options.index(_default) if _default in _options else 0
                st.selectbox(_label, _options, index=_idx, key=f"slot_{_key}")

with st.container(border=True):
    st.subheader("3. 움짤 영상 (선택, 2개까지)")
    st.caption(
        "MP4 / WebM / GIF · 5~10초 짧은 영상이 좋아요. "
        "1번 영상은 **'먹고 싶다' 자리(맛 섹션)**, 2번 영상은 **'조리' 자리**에 자동 배치돼요."
    )
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        video1 = st.file_uploader(
            "1️⃣ 맛 섹션 영상 (한 입 베어무는·꿀 흐르는·자르는 순간 등)",
            type=["mp4", "webm", "gif", "mov"],
            key="video1",
        )
    with col_v2:
        video2 = st.file_uploader(
            "2️⃣ 조리 섹션 영상 (조리 완성·김 모락·스푼으로 푸는 순간 등)",
            type=["mp4", "webm", "gif", "mov"],
            key="video2",
        )

with st.expander("⚙️ AI 모델 설정", expanded=True):
    provider = st.radio(
        "어떤 AI로 카피를 만들까요?",
        ["Gemini만", "GPT만", "둘 다 비교하기 (추천)"],
        index=2,
        horizontal=True,
        help="둘 다 비교하면 두 결과를 보고 마음에 드는 쪽을 골라서 페이지가 만들어져요.",
    )
    gemini_key = st.text_input(
        "GEMINI_API_KEY (비우면 환경변수)", value="", type="password",
        help="Gemini 카피 + 이미지 생성에 사용",
    )
    openai_key = st.text_input(
        "OPENAI_API_KEY (비우면 환경변수)", value="", type="password",
        help="GPT 카피에 사용 (gpt-4o-mini)",
    )
    enable_image_gen = st.checkbox(
        "빈 자리를 AI 이미지로 채우기 (Gemini)", value=True,
        help="사진을 배정하고 남은 빈 자리만 AI가 그려요. 올린 사진이 항상 우선이에요.",
    )

go = st.button("✨ 카피 생성하기", type="primary")


# ───────────────────────────────────────────────────────────────────────────
def _load_first_image(files) -> Image.Image | None:
    if not files:
        return None
    try:
        return Image.open(files[0]).convert("RGB")
    except Exception:
        return None


def _resolve_keys():
    gk = (gemini_key.strip() if gemini_key else "") or os.getenv("GEMINI_API_KEY", "")
    ok = (openai_key.strip() if openai_key else "") or os.getenv("OPENAI_API_KEY", "")
    return gk, ok


if go:
    if not raw_name and not uploads:
        st.warning("제품 이름이나 사진 중 하나는 꼭 넣어주세요.")
        st.stop()

    gk, ok = _resolve_keys()

    if provider == "Gemini만":
        with st.spinner("Gemini 카피 생성 중…"):
            copy_g = generate_copy(
                raw_name=raw_name, category=category, note=note,
                api_key=gk or None, provider="gemini",
            )
        st.session_state["candidates"] = {"gemini": copy_g, "openai": None}
        st.session_state["auto_choice"] = "gemini"
    elif provider == "GPT만":
        with st.spinner("GPT 카피 생성 중…"):
            copy_o = generate_copy(
                raw_name=raw_name, category=category, note=note,
                api_key=ok or None, provider="openai",
            )
        st.session_state["candidates"] = {"gemini": None, "openai": copy_o}
        st.session_state["auto_choice"] = "openai"
    else:
        with st.spinner("Gemini와 GPT를 동시에 호출 중…"):
            cands = generate_copy_compare(
                raw_name=raw_name, category=category, note=note,
                gemini_key=gk or None, openai_key=ok or None,
            )
        # 키 없는 쪽은 fallback CopyResult 라도 표시
        st.session_state["candidates"] = {
            "gemini": cands["gemini"] or generate_copy(
                raw_name, category, note, api_key=None, provider="gemini"
            ),
            "openai": cands["openai"] or generate_copy(
                raw_name, category, note, api_key=None, provider="openai"
            ),
        }
        st.session_state["auto_choice"] = None

    # 입력 사진/영상 메타 보존(이미지/영상은 데이터로 보관)
    base_img = _load_first_image(uploads)
    st.session_state["base_img"] = base_img
    v1 = video1.read() if video1 else b""
    v1n = video1.name if video1 else ""
    v2 = video2.read() if video2 else b""
    v2n = video2.name if video2 else ""
    st.session_state["video1"] = (v1, v1n)
    st.session_state["video2"] = (v2, v2n)
    st.session_state["meta"] = {
        "category": category, "raw_name": raw_name, "note": note,
        "enable_image_gen": enable_image_gen,
        "gemini_key": gk, "openai_key": ok,
    }


# ───────────────────────────────────────────────────────────────────────────
# 카피 비교 / 선택
def _summary_card(label: str, copy: CopyResult | None) -> str:
    if copy is None:
        return f'<div class="compare-card"><h4>{label}</h4><div class="meta">키 없음 또는 호출 실패</div></div>'
    name = copy.product_name or "(이름 없음)"
    head = copy.hero_headline or ""
    sub = copy.hero_sub or ""
    appeals = " · ".join((copy.appeals or [])[:3])
    hook_title = (copy.hook_section or {}).get("title", "")
    return (
        f'<div class="compare-card">'
        f'<h4>{label} <span class="meta">({copy.provider})</span></h4>'
        f'<div class="body"><b>{name}</b> — {head}<br>'
        f'<span class="meta">{sub}</span><br>'
        f'🔥 후크: <b>{hook_title}</b><br>'
        f'⭐ 소구점: {appeals}</div>'
        f'</div>'
    )


cands = st.session_state.get("candidates")
if cands:
    st.markdown("---")
    st.subheader("2. 카피 결과 비교")
    if cands.get("gemini") and cands.get("openai") and st.session_state.get("auto_choice") is None:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(_summary_card("Gemini", cands["gemini"]), unsafe_allow_html=True)
        with c2:
            st.markdown(_summary_card("GPT", cands["openai"]), unsafe_allow_html=True)
        choice = st.radio(
            "어느 카피로 페이지를 만들까요?",
            ["Gemini", "GPT"],
            horizontal=True,
            key="choice_radio",
        )
        chosen_key = "gemini" if choice == "Gemini" else "openai"
    else:
        chosen_key = st.session_state.get("auto_choice") or ("gemini" if cands.get("gemini") else "openai")
        st.markdown(
            _summary_card("Gemini" if chosen_key == "gemini" else "GPT", cands.get(chosen_key)),
            unsafe_allow_html=True,
        )

    if st.button("🎨 이 카피로 상세페이지 만들기", type="primary"):
        copy_obj: CopyResult = cands[chosen_key]
        meta = st.session_state.get("meta", {})

        def _open(f):
            try:
                return Image.open(f).convert("RGB")
            except Exception:
                return None

        # ① 업로드 사진 → 슬롯 배정표대로 배치
        file_by_name = {}
        for f in (uploads or []):
            file_by_name.setdefault(f.name, f)
        images: dict = {}
        used_names: set = set()
        for slot_key, _label in SLOT_DEFS:
            sel = st.session_state.get(f"slot_{slot_key}", "(없음)")
            if sel and sel != "(없음)" and sel in file_by_name:
                im = _open(file_by_name[sel])
                if im is not None:
                    images[slot_key] = im
                    used_names.add(sel)

        # ② 슬롯에 안 쓰인 나머지 사진 → '생생한 현장 컷' 띠
        extra_images = []
        for f in (uploads or []):
            if f.name not in used_names:
                im = _open(f)
                if im is not None:
                    extra_images.append(im)

        # ③ 빈 슬롯만 AI 이미지로 보충 (옵션)
        if meta.get("enable_image_gen") and meta.get("gemini_key"):
            empty_slots = [k for k, _ in SLOT_DEFS if k not in images]
            base_for_gen = images.get("hero") or (
                extra_images[0] if extra_images else next(iter(images.values()), None)
            )
            gen_prompts = {
                k: (copy_obj.image_prompts or {}).get(k, "")
                for k in empty_slots
                if (copy_obj.image_prompts or {}).get(k)
            }
            if gen_prompts and base_for_gen is not None:
                with st.spinner(f"빈 자리 {len(gen_prompts)}곳을 AI 이미지로 채우는 중…"):
                    gens = generate_detail_images(
                        base_for_gen,
                        prompts=gen_prompts,
                        api_key=meta["gemini_key"],
                        max_count=len(gen_prompts),
                    )
                for g in gens:
                    if g.is_generated:
                        images[g.label] = g.image

        v1, v1n = st.session_state.get("video1", (b"", ""))
        v2, v2n = st.session_state.get("video2", (b"", ""))
        html = render_page(
            copy_obj,
            images,
            include_ad_slot=True,
            video_taste=_video_to_data_uri(v1, v1n) if v1 else "",
            video_taste_mime="image/gif" if v1n.lower().endswith(".gif") else "",
            video_cook=_video_to_data_uri(v2, v2n) if v2 else "",
            video_cook_mime="image/gif" if v2n.lower().endswith(".gif") else "",
            extra_images=extra_images,
        )
        st.session_state["last_html"] = html
        st.session_state["last_copy"] = copy_obj.to_dict()
        st.session_state["last_ts"] = datetime.now().strftime("%Y%m%d_%H%M%S")


# ───────────────────────────────────────────────────────────────────────────
# 결과 표시
if st.session_state.get("last_html"):
    html = st.session_state["last_html"]
    ts = st.session_state.get("last_ts", "")
    st.markdown("---")
    st.subheader("3. 미리보기")
    st.caption("실제 모바일 화면입니다. 마음에 안 들면 카피를 다시 만들 수 있어요.")
    st.components.v1.html(html, height=1800, scrolling=True)

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


# 푸터
st.markdown("---")
st.markdown(
    '<div class="small-note" style="text-align:center;">'
    '<a href="?policy=terms">이용약관</a> · '
    '<a href="?policy=privacy">개인정보처리방침</a>'
    "</div>",
    unsafe_allow_html=True,
)
