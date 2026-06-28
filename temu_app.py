"""테무 한국 셀러센터 제품 등록 자동화 — Streamlit 메인.

가이드(2026 한국 셀러 PDF) 기반 흐름:
  ① 카테고리 선택
  ② 제품 정보 입력 (브랜드/이름/메모)
  ③ AI 카피 생성 (Gemini/GPT 선택·비교) — 제목 5단 구조, 설명, 세부 정보, 옵션 자동
  ④ 옵션·SKU 편집 (가격/수량/치수)
  ⑤ 이미지 업로드 + 자동 정사각형 1340 패키징
  ⑥ 동영상/규정 첨부
  ⑦ 출력 — 셀러센터 복붙 카드 / 보조 엑셀 / 이미지 ZIP / (옵션) 자동 업로드
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image

from temu.schema import (
    TemuListing, TitleParts, SkuRow, AttributeRow,
    ITC_OPTIONS, CATEGORY_PRESETS, TITLE_PARTS,
)
from temu.generator import generate_listing, generate_listing_compare
from temu.image_pack import build_image_pack, to_temu_square
from temu.excel_export import build_excel
from temu.uploader import open_seller_center_guided, auto_upload_listing


st.set_page_config(
    page_title="테무 제품 등록 자동화",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      /* 이 앱만 라이트 톤 강제 (식품 등 다른 다크 앱과 무관) */
      html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #f7f9fc !important; color: #1f2937 !important;
      }
      [data-testid="stSidebar"] { background-color: #ffffff !important; }
      h1, h2, h3, h4, label, p, span, div { color: #1f2937 !important; }
      [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
      [data-testid="stNumberInput"] input, [data-baseweb="select"] div {
        background-color:#ffffff !important; color:#1f2937 !important;
      }
      [data-testid="stExpander"] { background:#fff; border:1px solid #e5e7eb; border-radius:10px; }

      .block-container { max-width: 1100px; padding-top: 1.0rem; padding-bottom: 4rem; }
      .stButton>button { font-weight: 700; }
      .card { background:#fff; border:1px solid #e5e7eb; border-radius:12px;
              padding:16px 18px; margin-bottom:10px; }
      .copybox { background:#f8fafc !important; border:1px dashed #cbd5e1; border-radius:10px;
                 padding:12px 14px; font-size:14px; color:#1f2937 !important; white-space:pre-wrap; }
      .label { font-size:12px; color:#6b7280 !important; }
      .funnel span { background:#fff7ed; color:#9a3412 !important;
                     border:1px solid #fdba74; border-radius:999px;
                     padding:4px 10px; font-size:13px; font-weight:600; margin-right:6px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ────────────────────────────────────────────────────────────────────────────
st.title("🛒 테무 제품 등록 자동화 (한국 셀러)")
st.caption("가이드 5단계(제품 설명·세부정보·옵션·배송·규정)에 맞춰 AI가 양식을 만들어줍니다.")
st.markdown(
    '<div class="funnel">'
    '<span>① 카테고리</span><span>② 정보 입력</span>'
    '<span>③ AI 카피</span><span>④ 옵션/이미지</span>'
    '<span>⑤ 다운로드/업로드</span></div>',
    unsafe_allow_html=True,
)

# ─── 1단계: 입력 ─────────────────────────────────────────────────────────────
col_in1, col_in2 = st.columns([1, 1])
with col_in1:
    with st.container(border=True):
        st.subheader("1. 제품 정보")
        category = st.selectbox("카테고리", CATEGORY_PRESETS, index=0)
        brand = st.text_input("브랜드 (없으면 비워두세요)", placeholder="예: ABC")
        raw_name = st.text_input(
            "제품 이름/키워드",
            placeholder="예: 듀얼 존 와인 쿨러 24인치 78캔",
        )
        note = st.text_area(
            "메모 (특징·스펙·소재·사이즈 등 자유롭게)",
            placeholder="예: 독립형/카운터탑, 유리문 LED, 스테인리스, 78캔+20병",
            height=110,
        )
with col_in2:
    with st.container(border=True):
        st.subheader("2. AI 모델")
        provider = st.radio(
            "어떤 AI 로 카피를 만들까요?",
            ["Gemini만", "GPT만", "둘 다 비교"],
            index=2, horizontal=True,
        )
        gemini_key = st.text_input("GEMINI_API_KEY", value="", type="password")
        openai_key = st.text_input("OPENAI_API_KEY", value="", type="password")

go = st.button("✨ AI 카피 생성", type="primary")


def _resolve_keys():
    gk = (gemini_key.strip() if gemini_key else "") or os.getenv("GEMINI_API_KEY", "")
    ok = (openai_key.strip() if openai_key else "") or os.getenv("OPENAI_API_KEY", "")
    return gk, ok


if go:
    gk, ok = _resolve_keys()
    if provider == "Gemini만":
        with st.spinner("Gemini 카피 생성 중…"):
            res = {"gemini": generate_listing(
                raw_name, category, brand, note,
                provider="gemini", gemini_key=gk or None, openai_key=ok or None,
            ), "openai": None}
        st.session_state["auto_choice"] = "gemini"
    elif provider == "GPT만":
        with st.spinner("GPT 카피 생성 중…"):
            res = {"gemini": None, "openai": generate_listing(
                raw_name, category, brand, note,
                provider="openai", gemini_key=gk or None, openai_key=ok or None,
            )}
        st.session_state["auto_choice"] = "openai"
    else:
        with st.spinner("Gemini + GPT 동시 호출 중…"):
            res = generate_listing_compare(
                raw_name, category, brand, note,
                gemini_key=gk or None, openai_key=ok or None,
            )
        st.session_state["auto_choice"] = None
    st.session_state["cands"] = res


# ─── 비교 / 선택 ─────────────────────────────────────────────────────────────
def _preview_card(label: str, lst: TemuListing | None) -> str:
    if lst is None:
        return f'<div class="card"><b>{label}</b><div class="label">(생성 안 됨)</div></div>'
    title = lst.final_title()
    attrs = " · ".join(f"{a.label}={a.value}" for a in lst.attributes[:4])
    n_sku = len(lst.skus)
    return (
        f'<div class="card">'
        f'<b>{label}</b>'
        f'<div class="label">제목 {len(title)}자 · SKU {n_sku}건</div>'
        f'<div style="margin-top:8px;font-weight:700;">{title[:120]}{"…" if len(title)>120 else ""}</div>'
        f'<div style="margin-top:6px;font-size:13px;color:#374151;">{lst.description[:160]}…</div>'
        f'<div style="margin-top:6px;font-size:12px;color:#6b7280;">속성: {attrs}</div>'
        f'</div>'
    )


cands = st.session_state.get("cands")
chosen: TemuListing | None = None
if cands:
    st.markdown("---")
    st.subheader("3. AI 결과 비교/선택")
    if cands.get("gemini") and cands.get("openai") and st.session_state.get("auto_choice") is None:
        c1, c2 = st.columns(2)
        with c1: st.markdown(_preview_card("Gemini", cands["gemini"]), unsafe_allow_html=True)
        with c2: st.markdown(_preview_card("GPT", cands["openai"]), unsafe_allow_html=True)
        pick = st.radio("어느 카피로 작업할까요?", ["Gemini", "GPT"], horizontal=True)
        chosen = cands["gemini" if pick == "Gemini" else "openai"]
    else:
        which = st.session_state.get("auto_choice") or ("gemini" if cands.get("gemini") else "openai")
        chosen = cands.get(which)
        st.markdown(_preview_card("Gemini" if which == "gemini" else "GPT", chosen),
                    unsafe_allow_html=True)
    st.session_state["chosen"] = chosen.to_dict() if chosen else None


# ─── 4. 편집 (제목/설명/속성/SKU/이미지) ─────────────────────────────────────
if st.session_state.get("chosen"):
    st.markdown("---")
    st.subheader("4. 편집 (필요한 부분만 손보세요)")
    d = st.session_state["chosen"]

    with st.expander("📝 제목 (5단 구조)", expanded=True):
        tp = d.get("title_parts", {})
        cols = st.columns(5)
        labels = ["브랜드", "세부정보", "적용범위", "제품유형", "주요특징/기능/장점"]
        for i, key in enumerate(TITLE_PARTS):
            with cols[i]:
                tp[key] = st.text_area(labels[i], value=tp.get(key, ""), height=110, key=f"tp_{key}")
        d["title_parts"] = tp
        joined = " ".join(v for v in (tp.get(k, "").strip() for k in TITLE_PARTS) if v)
        if len(joined) > 500:
            st.warning(f"제목 길이 {len(joined)}자 — 500자 초과! 줄여주세요.")
        else:
            st.caption(f"최종 제목 미리보기 ({len(joined)}/500자):")
            st.markdown(f'<div class="copybox">{joined}</div>', unsafe_allow_html=True)
        d["title_override"] = st.text_input(
            "(선택) 제목 직접 작성", value=d.get("title_override", ""),
            help="비워두면 위 5단을 이어붙여 사용",
        )

    with st.expander("📄 상세 설명", expanded=False):
        d["description"] = st.text_area("상세 설명", value=d.get("description", ""), height=220)

    with st.expander("🏷️ ITC 코드 & 브랜드", expanded=False):
        itc_labels = [f"{c} — {desc}" for c, desc in ITC_OPTIONS]
        idx = 0 if d.get("itc_code") != "Gen Exempt" else 1
        pick = st.radio("ITC 코드", itc_labels, index=idx, horizontal=True)
        d["itc_code"] = "Gen Standard" if pick.startswith("Gen Standard") else "Gen Exempt"
        d["brand_name"] = st.text_input("브랜드명", value=d.get("brand_name", ""))

    with st.expander("🔬 제품 세부 정보 (속성 키-값)", expanded=False):
        attrs_df = pd.DataFrame(d.get("attributes", []) or [], columns=["label", "value"])
        edited = st.data_editor(
            attrs_df, num_rows="dynamic", use_container_width=True,
            column_config={"label": "속성명", "value": "값"},
            key="attrs_editor",
        )
        d["attributes"] = edited.dropna(how="all").to_dict("records")

    with st.expander("🎨 옵션 & SKU (색상·사이즈·가격·수량·치수)", expanded=True):
        cax1, cax2 = st.columns(2)
        with cax1:
            d["option_axis_1"] = st.text_input("옵션축 1", value=d.get("option_axis_1", "색상"))
        with cax2:
            d["option_axis_2"] = st.text_input("옵션축 2 (없으면 비움)", value=d.get("option_axis_2", "사이즈"))
        sku_df = pd.DataFrame(d.get("skus", []) or [])
        if sku_df.empty:
            sku_df = pd.DataFrame([{
                "color":"", "size":"", "sku_code":"", "qty":0, "price_krw":0.0,
                "weight_g":0.0, "length_cm":0.0, "width_cm":0.0, "height_cm":0.0,
                "image_filename":"",
            }])
        edited_sku = st.data_editor(
            sku_df, num_rows="dynamic", use_container_width=True,
            column_config={
                "color": d.get("option_axis_1", "옵션1"),
                "size": d.get("option_axis_2", "옵션2"),
                "sku_code": "SKU 코드",
                "qty": st.column_config.NumberColumn("수량", min_value=0, step=1),
                "price_krw": st.column_config.NumberColumn("기본가격(KRW)", min_value=0.0, step=100.0),
                "weight_g": st.column_config.NumberColumn("무게(g)", min_value=0.0),
                "length_cm": st.column_config.NumberColumn("가로(cm)", min_value=0.0),
                "width_cm": st.column_config.NumberColumn("세로(cm)", min_value=0.0),
                "height_cm": st.column_config.NumberColumn("높이(cm)", min_value=0.0),
                "image_filename": "SKU 이미지 파일명(자동)",
            },
            key="sku_editor",
        )
        d["skus"] = edited_sku.dropna(how="all", subset=["color", "size"]).to_dict("records")

    with st.expander("🚚 배송 정보", expanded=False):
        sh = d.get("shipping", {})
        c1, c2, c3 = st.columns(3)
        with c1:
            sh["processing_days"] = st.number_input("처리 시간(일)", min_value=1, max_value=30,
                                                    value=int(sh.get("processing_days", 2)))
        with c2:
            sh["template_name"] = st.text_input("배송 템플릿명", value=sh.get("template_name", "기본 배송 템플릿"))
        with c3:
            sh["method"] = st.text_input("배송 방법", value=sh.get("method", "표준 배송"))
        d["shipping"] = sh

    with st.expander("🖼️ 이미지 (메인 + 갤러리 + SKU별)", expanded=True):
        main_up = st.file_uploader("메인 이미지 (1장)", type=["jpg", "jpeg", "png", "webp"],
                                   key="main_up")
        gal_ups = st.file_uploader("갤러리 이미지 (여러 장)", type=["jpg", "jpeg", "png", "webp"],
                                   accept_multiple_files=True, key="gal_up")
        sku_files = {}
        if d.get("skus"):
            st.caption("SKU별 이미지 (옵션) — 각 옵션 변형마다 1장씩")
            for i, sku in enumerate(d["skus"]):
                key = f"{sku.get('color','')}_{sku.get('size','')}".strip("_") or f"sku{i+1}"
                f = st.file_uploader(f"SKU: {key}", type=["jpg","jpeg","png","webp"],
                                     key=f"sku_img_{i}")
                if f is not None:
                    sku_files[key] = f
        st.session_state["main_up"] = main_up
        st.session_state["gal_ups"] = gal_ups
        st.session_state["sku_files"] = sku_files

    with st.expander("🎬 동영상 & 📜 규정 첨부", expanded=False):
        video_up = st.file_uploader("동영상 1개 (상세페이지 상단에 표시)",
                                    type=["mp4","mov","webm"], key="video_up")
        comp_ups = st.file_uploader("규정/인증 서류 (PDF/이미지, 여러 장)",
                                    type=["pdf","jpg","jpeg","png"],
                                    accept_multiple_files=True, key="comp_ups")
        d["compliance_notes"] = st.text_area(
            "규정 메모 (어떤 인증/서류가 들어가는지)",
            value=d.get("compliance_notes", ""), height=80,
        )
        st.session_state["video_up"] = video_up
        st.session_state["comp_ups"] = comp_ups

    st.session_state["chosen"] = d


# ─── 5. 출력: 복붙 카드 + 엑셀 + 이미지 ZIP ──────────────────────────────────
if st.session_state.get("chosen"):
    st.markdown("---")
    st.subheader("5. 다운로드 / 셀러센터로")
    d = st.session_state["chosen"]

    # listing 객체 재조립
    listing = TemuListing(
        category=d.get("category") or category,
        title_parts=TitleParts(**(d.get("title_parts") or {})),
        title_override=d.get("title_override", ""),
        brand_name=d.get("brand_name", ""),
        description=d.get("description", ""),
        itc_code=d.get("itc_code", "Gen Standard"),
        attributes=[AttributeRow(**a) for a in (d.get("attributes") or [])],
        option_axis_1=d.get("option_axis_1", "색상"),
        option_axis_2=d.get("option_axis_2", "사이즈"),
        skus=[SkuRow(**{k: v for k, v in s.items() if k in SkuRow.__dataclass_fields__})
              for s in (d.get("skus") or [])],
        compliance_notes=d.get("compliance_notes", ""),
    )

    main_up = st.session_state.get("main_up")
    gal_ups = st.session_state.get("gal_ups") or []
    sku_files = st.session_state.get("sku_files") or {}

    def _img(f):
        try: return Image.open(f).convert("RGB")
        except Exception: return None

    main_img = _img(main_up) if main_up else None
    gallery_imgs = [im for im in (_img(g) for g in gal_ups) if im is not None]
    sku_imgs = {k: im for k, im in ((kk, _img(ff)) for kk, ff in sku_files.items()) if im is not None}

    # 복붙 카드
    st.markdown("### 📋 셀러센터 복붙 카드")
    st.caption("각 박스를 그대로 셀러센터에 붙여넣으면 돼요.")
    st.markdown('<div class="label">제목 (1단계)</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="copybox">{listing.final_title()}</div>', unsafe_allow_html=True)
    st.markdown('<div class="label">상세 설명 (1단계)</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="copybox">{listing.description}</div>', unsafe_allow_html=True)
    st.markdown('<div class="label">ITC / 브랜드</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="copybox">ITC: {listing.itc_code}\n브랜드: {listing.brand_name or "(없음)"}</div>',
        unsafe_allow_html=True,
    )

    # 다운로드 버튼
    col_d1, col_d2, col_d3 = st.columns(3)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    with col_d1:
        if main_img is not None or gallery_imgs or sku_imgs:
            zip_bytes, manifest = build_image_pack(
                main_image=main_img, gallery=gallery_imgs, sku_images=sku_imgs,
            )
            st.download_button(
                "🖼️ 이미지 ZIP (1340 정사각형)",
                data=zip_bytes,
                file_name=f"temu_images_{ts}.zip",
                mime="application/zip",
                use_container_width=True,
            )
            st.session_state["image_manifest"] = manifest
        else:
            st.button("🖼️ 이미지 ZIP", disabled=True, use_container_width=True,
                      help="이미지를 1장 이상 업로드하면 활성화돼요.")

    with col_d2:
        excel_bytes = build_excel(listing, image_manifest=st.session_state.get("image_manifest"))
        st.download_button(
            "📊 보조 엑셀 (대량 등록용)",
            data=excel_bytes,
            file_name=f"temu_listing_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with col_d3:
        import json
        st.download_button(
            "📥 JSON (원본)",
            data=json.dumps(listing.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"temu_listing_{ts}.json",
            mime="application/json",
            use_container_width=True,
        )

    # 자동 업로드 (옵션, 위험 명시)
    st.markdown("---")
    st.markdown("### 🚀 셀러센터로 보내기 (옵션)")
    st.warning(
        "⚠️ 자동 로그인·업로드는 캡차/2FA/봇 탐지로 실패할 수 있고, "
        "잘못 쓰면 계정 정지 위험이 있어요. 처음엔 **가이드 모드** 추천!"
    )
    seller_url = st.text_input(
        "셀러센터 URL",
        value=os.getenv("TEMU_SELLER_URL", "https://seller.kuajingmaihuo.com"),
        help="가이드에 적힌 셀러센터 주소가 있으면 그걸 입력하세요.",
    )
    mode = st.radio("모드", ["가이드 모드(추천)", "자동 모드(실험적)"], horizontal=True)
    if mode == "가이드 모드(추천)":
        if st.button("🌐 셀러센터 열기 (가이드 모드)", use_container_width=True):
            with st.spinner("브라우저를 여는 중…"):
                r = open_seller_center_guided(seller_url)
            (st.success if r.ok else st.error)(r.message)
    else:
        c1, c2 = st.columns(2)
        with c1: email = st.text_input("셀러 이메일", value=os.getenv("TEMU_EMAIL", ""))
        with c2: pw = st.text_input("셀러 비밀번호", value=os.getenv("TEMU_PASSWORD", ""), type="password")
        if st.button("⚡ 자동 업로드 시도", use_container_width=True):
            with st.spinner("자동 업로드 시도 중…"):
                r = auto_upload_listing(
                    seller_url=seller_url, email=email, password=pw,
                    title=listing.final_title(), description=listing.description,
                )
            (st.success if r.ok else st.error)(r.message)


# 푸터
st.markdown("---")
st.caption("© AI 테무 제품 등록 자동화 · 가이드 v2026 한국 셀러 기준")
