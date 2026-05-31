"""
공구 중개업 자동화 대시보드
탭: 📊 대시보드 | 📥 인플루언서 수집 | 👥 인플루언서 DB | 🏭 제조사 DB | 📅 시즌 트래커 | 💰 단가 계산기 | 📧 메일 발송 | 🤝 딜 관리
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import io
import threading

import gonggu_db as db
import gonggu_mailer as mailer
import gonggu_collector as collector

db.init_db()

st.set_page_config(
    page_title="공구 중개업 자동화",
    page_icon="🛍️",
    layout="wide",
)

st.title("🛍️ 공구 중개업 자동화 대시보드")

CATEGORIES = ["뷰티", "식품", "패션", "생활용품", "건강식품", "반려동물", "육아", "가전", "기타"]
SEASONS = ["봄", "여름", "가을", "겨울", "연중"]
STATUS_KO = {
    "negotiating": "협의중",
    "confirmed": "확정",
    "live": "진행중",
    "done": "완료",
    "failed": "실패",
}

tabs = st.tabs(["📊 대시보드", "📥 인플루언서 수집", "👥 인플루언서 DB", "🏭 제조사 DB", "📅 시즌 트래커", "💰 단가 계산기", "📧 메일 발송", "🤝 딜 관리"])

# ─────────────────────────────────────────────────────────
# 탭 1: 대시보드
# ─────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("📊 현황 요약")

    influencers = db.get_influencers()
    manufacturers = db.get_manufacturers()
    deals = db.get_deals()
    mail_logs = db.get_mail_log()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("인플루언서", f"{len(influencers)}명")
    c2.metric("제조사", f"{len(manufacturers)}개")
    active_deals = [d for d in deals if d["status"] in ("negotiating", "confirmed", "live")]
    c3.metric("진행중 딜", f"{len(active_deals)}건")
    total_rev = sum(d["my_revenue"] or 0 for d in deals if d["status"] == "done")
    c4.metric("누적 내 수익", f"{total_rev:,}원")

    st.divider()

    # 이번 달 추천 공구 아이템
    current_month = datetime.now().month
    season_items = db.get_season_items(month=current_month)
    if season_items:
        st.subheader(f"📅 {current_month}월 추천 공구 아이템")
        df = pd.DataFrame(season_items)[["season", "category", "item_name", "demand_level", "note"]]
        df.columns = ["시즌", "카테고리", "아이템", "수요도", "비고"]
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("최근 딜")
        if deals:
            for d in deals[:5]:
                status_label = STATUS_KO.get(d["status"], d["status"])
                inf = d.get("inf_name") or d.get("instagram_id", "")
                st.write(f"**{d['item_name']}** | {inf} × {d.get('mfr_name','')} | {status_label}")
        else:
            st.info("딜 없음")

    with col2:
        st.subheader("최근 메일")
        if mail_logs:
            for m in mail_logs[:5]:
                icon = "✅" if m["status"] == "sent" else "📝"
                st.write(f"{icon} {m['to_email']} — {m['subject'][:30]}...")
        else:
            st.info("발송 이력 없음")


# ─────────────────────────────────────────────────────────
# 탭 2: 인플루언서 수집
# ─────────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("📥 인플루언서 DB 수집")

    method_tab = st.radio(
        "수집 방법 선택",
        ["📂 엑셀/CSV 파일 임포트", "🔍 구글·네이버 검색 자동 수집", "📊 DB 현황 & 정리"],
        horizontal=True,
    )

    # ── 방법 A: 파일 임포트 ──────────────────────────────
    if method_tab == "📂 엑셀/CSV 파일 임포트":
        st.markdown("""
**추천:** 크몽에서 공구 인플루언서 리스트를 구매한 뒤 여기에 업로드하세요.

| 서비스 | 건수 | 가격 | 링크 |
|--------|------|------|------|
| 공동구매 인플루언서·업체 5,700명 | 5,700명 | ~5만원 | kmong.com/gig/638757 |
| 인스타그램 공동구매 인플루언서 리스트 | 3,576명 | ~3만원 | kmong.com/gig/443376 |
| 고효율 인스타 공동구매 3,850명 | 3,850명 | ~4만원 | kmong.com/gig/544304 |
| 공구 인플루언서 2,021명+맘카페 | 2,021명 | ~3만원 | kmong.com/gig/583553 |

엑셀/CSV 컬럼명은 자동 인식합니다. (인스타ID, 팔로워수, 카테고리, 이메일 등)
""")
        st.divider()

        uploaded = st.file_uploader("엑셀(.xlsx) 또는 CSV 파일 업로드", type=["xlsx", "xls", "csv"])
        default_cat = st.selectbox("카테고리 자동 분류 실패 시 기본값",
                                   ["기타"] + ["뷰티", "식품", "패션", "건강식품", "생활용품", "육아", "반려동물", "가전"])

        if uploaded:
            try:
                if uploaded.name.endswith(".csv"):
                    for enc in ("utf-8-sig", "cp949", "utf-8"):
                        try:
                            df_preview = pd.read_csv(uploaded, dtype=str, encoding=enc, nrows=5)
                            uploaded.seek(0)
                            df_full = pd.read_csv(uploaded, dtype=str, encoding=enc)
                            break
                        except UnicodeDecodeError:
                            uploaded.seek(0)
                else:
                    df_preview = pd.read_excel(uploaded, dtype=str, nrows=5)
                    uploaded.seek(0)
                    df_full = pd.read_excel(uploaded, dtype=str)

                st.write(f"**파일 미리보기** ({len(df_full)}행 감지)")
                st.dataframe(df_preview, use_container_width=True)

                # 컬럼 매핑 자동 감지 후 표시
                mapping = collector.detect_column_mapping(list(df_full.columns))
                if mapping:
                    st.success(f"자동 감지된 컬럼: {mapping}")
                else:
                    st.warning("컬럼 자동 인식 실패. 아래에서 직접 지정하세요.")
                    col_options = ["(없음)"] + list(df_full.columns)
                    c1, c2, c3 = st.columns(3)
                    id_col    = c1.selectbox("인스타그램 ID 컬럼", col_options)
                    name_col  = c2.selectbox("이름/닉네임 컬럼", col_options)
                    fol_col   = c3.selectbox("팔로워 수 컬럼", col_options)
                    if id_col != "(없음)":
                        df_full = df_full.rename(columns={id_col: "instagram_id"})
                    if name_col != "(없음)":
                        df_full = df_full.rename(columns={name_col: "name"})
                    if fol_col != "(없음)":
                        df_full = df_full.rename(columns={fol_col: "followers"})

                if st.button("🚀 DB에 전체 임포트", type="primary"):
                    result = collector.import_from_dataframe(df_full, default_category=default_cat)
                    st.success(f"✅ 임포트 완료: {result['imported']}명 저장 / {result['skipped']}개 스킵")
                    if result["errors"]:
                        with st.expander("오류 내역"):
                            for e in result["errors"][:10]:
                                st.write(e)
                    st.rerun()
            except Exception as e:
                st.error(f"파일 읽기 오류: {e}")

    # ── 방법 B: 검색 자동 수집 ───────────────────────────
    elif method_tab == "🔍 구글·네이버 검색 자동 수집":
        st.markdown("""
구글·네이버 검색결과에서 공개된 인스타그램 공구 계정을 자동으로 수집합니다.
팔로워 수·이메일은 수집되지 않으며, 계정명만 저장됩니다. (나중에 수동 보완)

> **합법 범위**: 공개 검색결과 파싱. 인스타그램 직접 크롤링 아님.
""")
        st.warning("⚠️ 검색 자동화는 구글 캡차로 차단될 수 있습니다. 소량(1~2개 카테고리)씩 진행하세요.")

        cats_to_search = st.multiselect(
            "수집할 카테고리 선택",
            ["뷰티", "식품", "패션", "건강식품", "생활용품", "육아", "반려동물", "가전"],
            default=["뷰티", "식품"],
        )
        delay_sec = st.slider("검색 간격 (초, 너무 짧으면 차단됨)", 1.5, 8.0, 3.0, 0.5)

        if "search_log" not in st.session_state:
            st.session_state["search_log"] = []

        if st.button("🔍 검색 수집 시작", disabled=not cats_to_search, type="primary"):
            log_container = st.empty()
            total_new = 0

            for cat in cats_to_search:
                log_container.info(f"🔍 [{cat}] 검색 중...")
                candidates = collector.collect_by_category(cat, delay=delay_sec)
                for c in candidates:
                    db.upsert_influencer({
                        "instagram_id": c["instagram_id"],
                        "name": c["instagram_id"],
                        "category": c["category"],
                        "followers": 0,
                        "note": f"[검색수집] {c['source']}",
                    })
                total_new += len(candidates)
                st.session_state["search_log"].append(
                    f"[{cat}] {len(candidates)}개 수집"
                )
                log_container.success(f"✅ [{cat}] {len(candidates)}개 수집 완료")

            st.success(f"전체 {total_new}개 계정 수집 → DB 저장 완료")
            st.rerun()

        if st.session_state["search_log"]:
            st.write("**최근 수집 로그:**")
            for log in st.session_state["search_log"][-10:]:
                st.write(f"  • {log}")

        st.divider()
        st.markdown("#### 직접 검색어 입력 (단건)")
        custom_query = st.text_input("검색어", placeholder="예: 인스타 홍삼 공구 진행중")
        custom_cat = st.selectbox("카테고리 지정", ["뷰티", "식품", "패션", "건강식품", "생활용품", "육아", "반려동물", "기타"], key="custom_cat_sel")
        if st.button("검색 실행") and custom_query:
            ids_g = collector.search_google(custom_query)
            ids_n = collector.search_naver(custom_query)
            all_ids = set(ids_g + ids_n)
            for iid in all_ids:
                db.upsert_influencer({
                    "instagram_id": iid,
                    "name": iid,
                    "category": custom_cat,
                    "followers": 0,
                    "note": f"[직접검색] {custom_query[:30]}",
                })
            st.success(f"구글 {len(ids_g)}개 + 네이버 {len(ids_n)}개 → {len(all_ids)}개 저장 완료")
            st.rerun()

    # ── 방법 C: DB 현황 & 정리 ──────────────────────────
    else:
        stats = collector.get_import_stats()
        st.markdown(f"### DB 현황: 총 **{stats['total']:,}명**")

        if stats["by_category"]:
            df_stats = pd.DataFrame(stats["by_category"])
            df_stats.columns = ["카테고리", "인원수"]
            df_stats["비율(%)"] = (df_stats["인원수"] / stats["total"] * 100).round(1)
            st.dataframe(df_stats, use_container_width=True, hide_index=True)

        st.info(f"팔로워 수 미확인 계정: {stats['unknown_followers']:,}명 (검색 수집 계정, 수동 보완 필요)")

        st.divider()
        st.markdown("### 🧹 중복 제거")
        st.write("인스타그램 ID 기준으로 중복 레코드를 제거합니다.")
        if st.button("중복 제거 실행"):
            deleted = collector.deduplicate_db()
            st.success(f"중복 {deleted}건 제거 완료")
            st.rerun()

        st.divider()
        st.markdown("### 📤 전체 DB 내보내기 (엑셀)")
        infs = db.get_influencers()
        if infs:
            df_export = pd.DataFrame(infs)
            buf = io.BytesIO()
            df_export.to_excel(buf, index=False)
            buf.seek(0)
            st.download_button(
                "⬇️ 전체 인플루언서 DB 다운로드",
                data=buf,
                file_name=f"influencer_db_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ─────────────────────────────────────────────────────────
# 탭 3: 인플루언서 DB
# ─────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("👥 인플루언서 DB")

    with st.expander("➕ 인플루언서 추가/수정", expanded=False):
        with st.form("inf_form"):
            c1, c2 = st.columns(2)
            instagram_id = c1.text_input("인스타그램 ID (@없이)", placeholder="example_id")
            name = c2.text_input("이름/닉네임")
            c1, c2, c3 = st.columns(3)
            followers = c1.number_input("팔로워 수", min_value=0, value=10000)
            category = c2.selectbox("주 카테고리", CATEGORIES)
            commission_rate = c3.number_input("협의 수수료율(%)", min_value=0.0, max_value=100.0, value=30.0, step=0.5)
            c1, c2 = st.columns(2)
            email = c1.text_input("이메일")
            dm_link = c2.text_input("DM/링크")
            note = st.text_area("메모", height=80)
            if st.form_submit_button("저장"):
                if not instagram_id:
                    st.error("인스타그램 ID 필수")
                else:
                    db.upsert_influencer({
                        "instagram_id": instagram_id, "name": name,
                        "followers": followers, "category": category,
                        "commission_rate": commission_rate,
                        "email": email, "dm_link": dm_link, "note": note,
                    })
                    st.success("저장 완료!")
                    st.rerun()

    col1, col2, col3 = st.columns([2, 1, 1])
    cat_filter = col1.selectbox("카테고리 필터", ["전체"] + CATEGORIES, key="inf_cat")
    min_fol = col2.number_input("최소 팔로워", value=0, step=1000, key="inf_min")
    st.write("")

    rows = db.get_influencers(category=cat_filter if cat_filter != "전체" else None, min_followers=min_fol)
    if rows:
        df = pd.DataFrame(rows)
        display_cols = ["id", "instagram_id", "name", "followers", "category", "commission_rate", "email", "note"]
        display_cols = [c for c in display_cols if c in df.columns]
        df_show = df[display_cols].copy()
        df_show.columns = ["ID", "인스타ID", "이름", "팔로워", "카테고리", "수수료%", "이메일", "메모"]
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        # 공구 이력 추가
        with st.expander("📋 공구 이력 추가"):
            with st.form("history_form"):
                inf_options = {f"{r['name']} (@{r['instagram_id']})": r["id"] for r in rows}
                selected_inf = st.selectbox("인플루언서", list(inf_options.keys()))
                c1, c2 = st.columns(2)
                item_name = c1.text_input("아이템명")
                h_category = c2.selectbox("카테고리", CATEGORIES, key="h_cat")
                c1, c2, c3 = st.columns(3)
                h_season = c1.selectbox("시즌", SEASONS, key="h_season")
                h_month = c2.number_input("진행 월", 1, 12, datetime.now().month)
                sold_out = c3.checkbox("완판")
                c1, c2, c3 = st.columns(3)
                sale_price = c1.number_input("판매가(원)", value=0)
                actual_revenue = c2.number_input("실매출(원)", value=0)
                h_note = st.text_input("메모")
                if st.form_submit_button("이력 추가"):
                    db.add_gonggu_history({
                        "influencer_id": inf_options[selected_inf],
                        "item_name": item_name, "category": h_category,
                        "season": h_season, "month": h_month,
                        "sale_price": sale_price, "actual_revenue": actual_revenue,
                        "sold_out": 1 if sold_out else 0, "note": h_note,
                    })
                    st.success("이력 추가 완료!")

        # 삭제
        with st.expander("🗑️ 삭제"):
            del_id = st.number_input("삭제할 인플루언서 ID", min_value=1, step=1, key="inf_del_id")
            if st.button("삭제", key="inf_del_btn"):
                db.delete_influencer(del_id)
                st.success("삭제 완료")
                st.rerun()
    else:
        st.info("등록된 인플루언서 없음")

    st.divider()
    st.subheader("📋 공구 이력 전체")
    hist = db.get_gonggu_history()
    if hist:
        df_h = pd.DataFrame(hist)
        cols = ["id", "instagram_id", "name", "item_name", "category", "season", "month", "actual_revenue", "sold_out"]
        cols = [c for c in cols if c in df_h.columns]
        df_h = df_h[cols]
        df_h.columns = ["ID", "인스타ID", "이름", "아이템", "카테고리", "시즌", "월", "실매출", "완판"][:len(cols)]
        st.dataframe(df_h, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────
# 탭 3: 제조사 DB
# ─────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("🏭 제조사/공급사 DB")

    with st.expander("➕ 제조사 추가", expanded=False):
        with st.form("mfr_form"):
            c1, c2 = st.columns(2)
            company = c1.text_input("회사명 *")
            contact_name = c2.text_input("담당자명")
            c1, c2, c3 = st.columns(3)
            email = c1.text_input("이메일")
            phone = c2.text_input("전화번호")
            m_category = c3.selectbox("카테고리", CATEGORIES, key="mfr_cat")
            c1, c2 = st.columns(2)
            product_line = c1.text_input("주요 제품군", placeholder="예: 홍삼 건강식품")
            supply_price_range = c2.text_input("공급가 범위", placeholder="예: 소비자가의 30~40%")
            c1, c2 = st.columns(2)
            min_order = c1.text_input("최소 주문량", placeholder="예: 100개 이상")
            can_dropship = c2.checkbox("직배송 가능", value=True)
            note = st.text_area("메모", height=60)
            if st.form_submit_button("저장"):
                if not company:
                    st.error("회사명 필수")
                else:
                    db.upsert_manufacturer({
                        "company": company, "contact_name": contact_name,
                        "email": email, "phone": phone, "category": m_category,
                        "product_line": product_line,
                        "supply_price_range": supply_price_range,
                        "min_order": min_order,
                        "can_dropship": 1 if can_dropship else 0,
                        "note": note,
                    })
                    st.success("저장 완료!")
                    st.rerun()

    cat_filter_m = st.selectbox("카테고리 필터", ["전체"] + CATEGORIES, key="mfr_cat_filter")
    rows_m = db.get_manufacturers(category=cat_filter_m if cat_filter_m != "전체" else None)
    if rows_m:
        df_m = pd.DataFrame(rows_m)
        display_m = ["id", "company", "contact_name", "email", "phone", "category", "product_line", "supply_price_range", "min_order", "can_dropship"]
        display_m = [c for c in display_m if c in df_m.columns]
        df_show_m = df_m[display_m].copy()
        df_show_m.columns = ["ID", "회사명", "담당자", "이메일", "전화", "카테고리", "제품군", "공급가범위", "최소주문", "직배송"][:len(display_m)]
        st.dataframe(df_show_m, use_container_width=True, hide_index=True)

        with st.expander("🗑️ 삭제"):
            del_mid = st.number_input("삭제할 제조사 ID", min_value=1, step=1, key="mfr_del_id")
            if st.button("삭제", key="mfr_del_btn"):
                db.delete_manufacturer(del_mid)
                st.success("삭제 완료")
                st.rerun()
    else:
        st.info("등록된 제조사 없음")


# ─────────────────────────────────────────────────────────
# 탭 4: 시즌 트래커
# ─────────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("📅 시즌별 공구 아이템 트래커")

    view_mode = st.radio("보기 방식", ["이번 달 추천", "시즌별 전체", "월 선택"], horizontal=True)

    if view_mode == "이번 달 추천":
        month = datetime.now().month
        items = db.get_season_items(month=month)
        st.write(f"**{month}월** 추천 공구 아이템")
    elif view_mode == "시즌별 전체":
        sel_season = st.selectbox("시즌", SEASONS)
        items = db.get_season_items(season=sel_season)
    else:
        sel_month = st.slider("월 선택", 1, 12, datetime.now().month)
        items = db.get_season_items(month=sel_month)

    if items:
        df_s = pd.DataFrame(items)
        demand_icon = {"높음": "🔥", "중간": "⭐", "낮음": "💤"}
        df_s["수요도"] = df_s["demand_level"].map(lambda x: f"{demand_icon.get(x, '')} {x}")
        show_cols = ["season", "category", "item_name", "수요도", "keyword", "note"]
        show_cols = [c for c in show_cols if c in df_s.columns]
        df_out = df_s[show_cols].copy()
        df_out.columns = ["시즌", "카테고리", "아이템", "수요도", "키워드", "비고"][:len(show_cols)]
        st.dataframe(df_out, use_container_width=True, hide_index=True)
    else:
        st.info("해당 시즌 데이터 없음")

    st.divider()

    # 연간 캘린더 뷰
    st.subheader("📆 연간 공구 캘린더")
    all_items = db.get_season_items()
    months_label = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
    cal_data = {m: [] for m in range(1, 13)}
    for item in all_items:
        for m in range(item["month_start"], item["month_end"] + 1):
            icon = "🔥" if item["demand_level"] == "높음" else "⭐"
            cal_data[m].append(f"{icon} {item['item_name']}")

    cols = st.columns(4)
    for i, (month, items_list) in enumerate(cal_data.items()):
        with cols[i % 4]:
            st.markdown(f"**{months_label[i]}**")
            if items_list:
                for it in items_list[:4]:
                    st.write(f"  {it}")
                if len(items_list) > 4:
                    st.write(f"  +{len(items_list)-4}개 더")
            else:
                st.write("  —")


# ─────────────────────────────────────────────────────────
# 탭 5: 단가 계산기
# ─────────────────────────────────────────────────────────
with tabs[5]:
    st.subheader("💰 공구 단가 자동 계산기")
    st.caption("공급가·택배비·반품비·수수료를 입력하면 판매가·수익 구조를 자동 계산합니다.")

    # ── 기본 입력 ──────────────────────────────────────────
    st.markdown("### 1️⃣ 제조사 조건")
    c1, c2, c3 = st.columns(3)
    supply_price = c1.number_input("제조사 공급가 (원/개)", min_value=0, value=5000, step=100,
                                   help="제조사가 중개자에게 제공하는 원가")
    has_delivery = c2.checkbox("택배비 포함 여부", value=False,
                               help="체크=공급가에 배송비 포함 / 미체크=별도 청구")
    delivery_fee = c3.number_input("택배비 (원/건)", min_value=0, value=3000, step=100,
                                   disabled=has_delivery,
                                   help="공급가에 미포함 시 건당 추가 택배비")

    c1, c2, c3 = st.columns(3)
    has_return = c1.checkbox("반품비 발생 여부", value=True)
    return_fee = c2.number_input("반품비 (원/건)", min_value=0, value=5000, step=500,
                                  disabled=not has_return,
                                  help="소비자 반품 시 발생 비용 (왕복 택배비 등)")
    return_rate = c3.number_input("예상 반품율 (%)", min_value=0.0, max_value=100.0,
                                   value=3.0, step=0.5,
                                   help="판매 수량 대비 평균 반품 비율")

    st.markdown("### 2️⃣ 판매 조건")
    c1, c2, c3 = st.columns(3)
    sale_price = c1.number_input("공구 판매가 제안 (원/개)", min_value=0, value=12000, step=500,
                                  help="소비자에게 제시할 공구가")
    expected_qty = c2.number_input("예상 판매 수량 (개)", min_value=1, value=100, step=10)
    platform_fee_rate = c3.number_input("플랫폼 수수료 (%)", min_value=0.0, max_value=20.0,
                                         value=3.5, step=0.5,
                                         help="스마트스토어 3.5% / 자사몰 0% 등")

    st.markdown("### 3️⃣ 수수료 배분")
    c1, c2 = st.columns(2)
    inf_rate = c1.slider("인플루언서 수수료 (%)", min_value=0, max_value=60,
                          value=30, step=1,
                          help="판매액 기준 인플루언서에게 지급하는 비율")
    my_rate = c2.slider("중개사(나) 수수료 (%)", min_value=0, max_value=30,
                         value=10, step=1,
                         help="판매액 기준 중개사가 가져가는 비율")

    # ── 자동 계산 ──────────────────────────────────────────
    st.markdown("---")

    # 개당 실제 원가 (택배비 + 반품 충당금 포함)
    actual_delivery = 0 if has_delivery else delivery_fee
    return_allowance = (return_fee * return_rate / 100) if has_return else 0
    cost_per_unit = supply_price + actual_delivery + return_allowance

    # 판매액 기준 각 항목
    platform_fee_per = sale_price * platform_fee_rate / 100
    inf_fee_per = sale_price * inf_rate / 100
    my_fee_per = sale_price * my_rate / 100
    mfr_revenue_per = sale_price - platform_fee_per - inf_fee_per - my_fee_per  # 제조사 정산액
    gross_profit_per = sale_price - cost_per_unit  # 판매가 - 원가
    net_margin_per = my_fee_per  # 중개사 순수익(개당)

    margin_rate = (my_fee_per / sale_price * 100) if sale_price > 0 else 0
    total_revenue = sale_price * expected_qty
    total_my_revenue = my_fee_per * expected_qty
    total_inf_revenue = inf_fee_per * expected_qty
    total_mfr = mfr_revenue_per * expected_qty
    total_platform = platform_fee_per * expected_qty

    # 수익성 경고
    if cost_per_unit > mfr_revenue_per:
        st.error(f"⚠️ 원가({cost_per_unit:,.0f}원) > 제조사 정산액({mfr_revenue_per:,.0f}원) — 제조사 손실 구조입니다. 판매가를 올리거나 수수료율을 낮추세요.")
    elif margin_rate < 5:
        st.warning(f"⚠️ 중개사 마진이 {margin_rate:.1f}%로 낮습니다. 수수료율 조정을 검토하세요.")
    else:
        st.success(f"✅ 수익 구조 정상 — 중개사 마진 {margin_rate:.1f}%")

    # ── 개당 단가 표 ────────────────────────────────────────
    st.markdown("### 📊 개당 단가 분석표")

    unit_table = pd.DataFrame([
        {"항목": "소비자 공구 판매가",     "금액(원)": sale_price,             "비율(%)": 100.0,              "비고": "기준"},
        {"항목": "├ 제조사 공급가",        "금액(원)": supply_price,           "비율(%)": round(supply_price/sale_price*100,1) if sale_price else 0, "비고": "원가"},
        {"항목": "├ 택배비",               "금액(원)": actual_delivery,        "비율(%)": round(actual_delivery/sale_price*100,1) if sale_price else 0, "비고": "포함" if has_delivery else "별도"},
        {"항목": "├ 반품 충당금",          "금액(원)": round(return_allowance), "비율(%)": round(return_allowance/sale_price*100,1) if sale_price else 0, "비고": f"반품율 {return_rate}%" if has_return else "없음"},
        {"항목": "├ 플랫폼 수수료",        "금액(원)": round(platform_fee_per),"비율(%)": platform_fee_rate,  "비고": "스마트스토어 등"},
        {"항목": "├ 인플루언서 수수료",    "금액(원)": round(inf_fee_per),     "비율(%)": float(inf_rate),    "비고": "판매액 기준"},
        {"항목": "├ 중개사(나) 수수료",    "금액(원)": round(my_fee_per),      "비율(%)": float(my_rate),     "비고": "판매액 기준"},
        {"항목": "└ 제조사 정산액",        "금액(원)": round(mfr_revenue_per), "비율(%)": round(mfr_revenue_per/sale_price*100,1) if sale_price else 0, "비고": "제조사 실수령"},
        {"항목": "▶ 중개사 순이익(개당)",  "금액(원)": round(net_margin_per),  "비율(%)": round(margin_rate,1),"비고": "★ 핵심 지표"},
    ])

    def highlight_row(row):
        if "중개사 순이익" in row["항목"]:
            return ["background-color: #d4edda; font-weight: bold"] * len(row)
        elif "제조사 정산액" in row["항목"]:
            return ["background-color: #fff3cd"] * len(row)
        elif "인플루언서" in row["항목"]:
            return ["background-color: #cce5ff"] * len(row)
        return [""] * len(row)

    st.dataframe(
        unit_table.style.apply(highlight_row, axis=1).format({"금액(원)": "{:,.0f}", "비율(%)": "{:.1f}"}),
        use_container_width=True, hide_index=True,
    )

    # ── 전체 수익 시뮬레이션 표 ────────────────────────────
    st.markdown(f"### 📦 총 {expected_qty:,}개 판매 시 수익 시뮬레이션")

    sim_table = pd.DataFrame([
        {"구분": "총 매출",              "금액(원)": total_revenue,           "비고": f"{sale_price:,}원 × {expected_qty:,}개"},
        {"구분": "인플루언서 지급액",    "금액(원)": round(total_inf_revenue), "비고": f"{inf_rate}% × 총매출"},
        {"구분": "플랫폼 수수료",        "금액(원)": round(total_platform),    "비고": f"{platform_fee_rate}% × 총매출"},
        {"구분": "제조사 정산액",        "금액(원)": round(total_mfr),         "비고": "공급가·배송비 회수분"},
        {"구분": "★ 중개사 수익",        "금액(원)": round(total_my_revenue),  "비고": f"{my_rate}% × 총매출"},
    ])

    st.dataframe(
        sim_table.style.apply(
            lambda row: ["background-color: #d4edda; font-weight: bold"] * len(row) if "★" in row["구분"] else [""] * len(row),
            axis=1
        ).format({"금액(원)": "{:,.0f}"}),
        use_container_width=True, hide_index=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 매출", f"{total_revenue:,.0f}원")
    col2.metric("내 수익", f"{round(total_my_revenue):,}원", f"{margin_rate:.1f}%")
    col3.metric("인플루언서 지급", f"{round(total_inf_revenue):,}원")
    col4.metric("제조사 정산", f"{round(total_mfr):,}원")

    # ── 손익분기 & 민감도 ──────────────────────────────────
    st.markdown("### 🔢 손익분기 & 민감도 분석")

    # 중개사 기준 손익분기 수량 (내 수익이 0이 되는 시점은 없지만 최소 수익 목표 기준)
    target_my_revenue = st.number_input("목표 중개사 수익 (원)", value=500000, step=100000)
    bep_qty = (target_my_revenue / my_fee_per) if my_fee_per > 0 else float("inf")
    st.info(f"목표 수익 **{target_my_revenue:,}원** 달성을 위한 최소 판매 수량: **{bep_qty:,.0f}개**")

    # 판매가 변동 시나리오
    st.markdown("**판매가 변동 시나리오**")
    scenarios = []
    for delta in [-2000, -1000, 0, 1000, 2000]:
        sp = sale_price + delta
        if sp <= 0:
            continue
        my = sp * my_rate / 100
        inf_f = sp * inf_rate / 100
        mfr_r = sp - sp * platform_fee_rate / 100 - inf_f - my
        scenarios.append({
            "판매가(원)": sp,
            "중개사 수익/개(원)": round(my),
            "인플루언서 수익/개(원)": round(inf_f),
            "제조사 정산/개(원)": round(mfr_r),
            "중개사 마진(%)": round(my / sp * 100, 1),
            "현재가 대비": "◀ 현재" if delta == 0 else f"{'▲' if delta > 0 else '▼'} {abs(delta):,}원",
        })

    df_sc = pd.DataFrame(scenarios)
    st.dataframe(
        df_sc.style.apply(
            lambda row: ["background-color: #fff3cd; font-weight: bold"] * len(row) if row["현재가 대비"] == "◀ 현재" else [""] * len(row),
            axis=1,
        ).format({
            "판매가(원)": "{:,}",
            "중개사 수익/개(원)": "{:,}",
            "인플루언서 수익/개(원)": "{:,}",
            "제조사 정산/개(원)": "{:,}",
            "중개사 마진(%)": "{:.1f}",
        }),
        use_container_width=True, hide_index=True,
    )

    # ── 저장 ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 💾 이 조건으로 딜 저장")
    inf_list_calc = db.get_influencers()
    mfr_list_calc = db.get_manufacturers()
    if inf_list_calc and mfr_list_calc:
        with st.form("calc_deal_form"):
            c1, c2, c3 = st.columns(3)
            inf_opts_c = {f"{r['name']} (@{r['instagram_id']})": r["id"] for r in inf_list_calc}
            mfr_opts_c = {r["company"]: r["id"] for r in mfr_list_calc}
            sel_inf_c = c1.selectbox("인플루언서", list(inf_opts_c.keys()))
            sel_mfr_c = c2.selectbox("제조사", list(mfr_opts_c.keys()))
            d_item_c = c3.text_input("아이템명")
            note_c = st.text_area("메모 (자동 요약 포함)", height=60,
                value=f"공급가:{supply_price:,}원 / 판매가:{sale_price:,}원 / 인플루언서:{inf_rate}% / 중개사:{my_rate}% / 예상수량:{expected_qty:,}개 / 중개사예상수익:{round(total_my_revenue):,}원")
            if st.form_submit_button("딜로 저장"):
                if d_item_c:
                    db.add_deal({
                        "influencer_id": inf_opts_c[sel_inf_c],
                        "manufacturer_id": mfr_opts_c[sel_mfr_c],
                        "item_name": d_item_c,
                        "commission_rate": my_rate,
                        "note": note_c,
                    })
                    st.success("딜 탭에 저장 완료!")
                else:
                    st.error("아이템명 입력 필요")
    else:
        st.info("인플루언서/제조사를 먼저 DB에 등록하세요")

# ─────────────────────────────────────────────────────────
# 탭 6: 메일 발송
# ─────────────────────────────────────────────────────────
with tabs[6]:
    st.subheader("📧 메일 발송")

    # SMTP 설정 확인
    smtp_configured = bool(os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))
    if not smtp_configured:
        st.warning("⚠️ SMTP 설정 필요: .env에 SMTP_USER, SMTP_PASSWORD 설정 후 재시작하세요")

    with st.expander("⚙️ SMTP 설정 (세션 임시)", expanded=not smtp_configured):
        c1, c2 = st.columns(2)
        smtp_user_input = c1.text_input("SMTP 이메일 (Gmail 권장)", value=os.getenv("SMTP_USER", ""))
        smtp_pw_input = c2.text_input("SMTP 앱 비밀번호", type="password", value=os.getenv("SMTP_PASSWORD", ""))
        sender_name_input = st.text_input("발송자 이름", value=os.getenv("SENDER_NAME", "공구 중개"))
        if st.button("임시 저장"):
            os.environ["SMTP_USER"] = smtp_user_input
            os.environ["SMTP_PASSWORD"] = smtp_pw_input
            os.environ["SENDER_NAME"] = sender_name_input
            st.success("세션에 저장됨 (앱 재시작 시 초기화)")
            st.rerun()

    st.divider()

    target_type = st.radio("발송 대상", ["인플루언서", "제조사"], horizontal=True)
    template_names = mailer.get_template_names()

    if target_type == "인플루언서":
        template_options = [t for t in template_names if "인플루언서" in t]
        inf_list = db.get_influencers()
        if not inf_list:
            st.info("등록된 인플루언서 없음")
            st.stop()
        inf_options = {f"{r['name']} (@{r['instagram_id']}) — {r.get('email','')}": r for r in inf_list if r.get("email")}
        selected_inf_key = st.selectbox("인플루언서 선택 (이메일 있는 경우만 표시)", list(inf_options.keys()))
        selected_inf_data = inf_options.get(selected_inf_key, {})
    else:
        template_options = [t for t in template_names if "제조사" in t]
        mfr_list = db.get_manufacturers()
        if not mfr_list:
            st.info("등록된 제조사 없음")
            st.stop()
        mfr_options = {f"{r['company']} — {r.get('contact_name','')} ({r.get('email','')})": r for r in mfr_list if r.get("email")}
        selected_mfr_key = st.selectbox("제조사 선택 (이메일 있는 경우만 표시)", list(mfr_options.keys()))
        selected_inf_data = mfr_options.get(selected_mfr_key, {})

    selected_template = st.selectbox("템플릿 선택", template_options)

    # 변수 자동 채우기
    required_vars = mailer.get_template_variables(selected_template)

    sender_name = os.getenv("SENDER_NAME", "공구 중개")
    sender_email = os.getenv("SMTP_USER", "")
    auto_vars = {
        "sender_name": sender_name,
        "sender_email": sender_email,
        "sender_phone": "",
        "influencer_name": selected_inf_data.get("name", ""),
        "company": selected_inf_data.get("company", ""),
        "contact_name": selected_inf_data.get("contact_name", ""),
        "product_line": selected_inf_data.get("product_line", ""),
        "commission_rate": str(selected_inf_data.get("commission_rate", 30)),
    }

    st.write("**템플릿 변수 입력**")
    var_inputs = {}
    col_pairs = st.columns(2)
    for i, var in enumerate(required_vars):
        with col_pairs[i % 2]:
            if var == "season_items":
                month = datetime.now().month
                items_now = db.get_season_items(month=month)
                default_items = "\n".join(
                    f"• {it['item_name']} ({it['category']}) — 수요: {it['demand_level']}"
                    for it in items_now[:5]
                )
                var_inputs[var] = st.text_area(f"{var}", value=default_items, height=120)
            else:
                var_inputs[var] = st.text_input(f"{var}", value=auto_vars.get(var, ""))

    if st.button("📋 미리보기"):
        try:
            rendered = mailer.render_template(selected_template, var_inputs)
            st.markdown("---")
            st.markdown(f"**제목:** {rendered['subject']}")
            st.text_area("본문", rendered["body"], height=300)
            st.session_state["mail_preview"] = rendered
            to_email = selected_inf_data.get("email", "")
            st.session_state["mail_to"] = to_email
            st.session_state["mail_target_type"] = "influencer" if target_type == "인플루언서" else "manufacturer"
            st.session_state["mail_target_id"] = selected_inf_data.get("id", 0)
            st.session_state["mail_template"] = selected_template
        except Exception as e:
            st.error(f"렌더링 오류: {e}")

    if "mail_preview" in st.session_state:
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📧 실제 발송", disabled=not smtp_configured):
                rendered = st.session_state["mail_preview"]
                ok, msg = mailer.send_email(
                    to_email=st.session_state["mail_to"],
                    subject=rendered["subject"],
                    body=rendered["body"],
                )
                if ok:
                    db.save_mail_log({
                        "target_type": st.session_state["mail_target_type"],
                        "target_id": st.session_state["mail_target_id"],
                        "to_email": st.session_state["mail_to"],
                        "subject": rendered["subject"],
                        "body": rendered["body"],
                        "template_name": st.session_state["mail_template"],
                        "status": "sent",
                        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ {msg}")
                    del st.session_state["mail_preview"]
                    st.rerun()
                else:
                    st.error(f"발송 실패: {msg}")
        with col2:
            if st.button("📝 임시저장(Draft)"):
                rendered = st.session_state["mail_preview"]
                db.save_mail_log({
                    "target_type": st.session_state["mail_target_type"],
                    "target_id": st.session_state["mail_target_id"],
                    "to_email": st.session_state["mail_to"],
                    "subject": rendered["subject"],
                    "body": rendered["body"],
                    "template_name": st.session_state["mail_template"],
                    "status": "draft",
                })
                st.success("임시저장 완료")
                del st.session_state["mail_preview"]
                st.rerun()

    st.divider()
    st.subheader("📬 발송 이력")
    logs = db.get_mail_log()
    if logs:
        df_l = pd.DataFrame(logs)
        show_l = ["id", "target_type", "to_email", "subject", "template_name", "status", "sent_at", "reply_received"]
        show_l = [c for c in show_l if c in df_l.columns]
        df_l_show = df_l[show_l].copy()
        df_l_show.columns = ["ID", "대상", "수신자", "제목", "템플릿", "상태", "발송일", "답장"][:len(show_l)]
        st.dataframe(df_l_show, use_container_width=True, hide_index=True)

        with st.expander("답장 수신 업데이트"):
            log_id = st.number_input("이력 ID", min_value=1, step=1)
            reply_note = st.text_input("답장 내용 메모")
            if st.button("답장 수신 처리"):
                db.update_mail_status(log_id, "sent", reply_note)
                conn = __import__("sqlite3").connect("gonggu.db")
                conn.execute("UPDATE mail_log SET reply_received=1 WHERE id=?", (log_id,))
                conn.commit(); conn.close()
                st.success("업데이트 완료")
                st.rerun()
    else:
        st.info("발송 이력 없음")


# ─────────────────────────────────────────────────────────
# 탭 7: 딜 관리
# ─────────────────────────────────────────────────────────
with tabs[7]:
    st.subheader("🤝 딜 관리 (인플루언서 × 제조사)")

    inf_list_d = db.get_influencers()
    mfr_list_d = db.get_manufacturers()

    with st.expander("➕ 새 딜 추가", expanded=False):
        with st.form("deal_form"):
            c1, c2 = st.columns(2)
            inf_opts = {f"{r['name']} (@{r['instagram_id']})": r["id"] for r in inf_list_d}
            mfr_opts = {r["company"]: r["id"] for r in mfr_list_d}
            sel_inf = c1.selectbox("인플루언서", list(inf_opts.keys()) or ["없음"])
            sel_mfr = c2.selectbox("제조사", list(mfr_opts.keys()) or ["없음"])
            c1, c2, c3 = st.columns(3)
            d_item = c1.text_input("아이템명")
            d_commission = c2.number_input("내 수수료율(%)", value=10.0, step=0.5)
            d_start = c3.date_input("시작 예정일", value=date.today())
            d_note = st.text_area("메모", height=60)
            if st.form_submit_button("딜 추가"):
                if inf_opts and mfr_opts and d_item:
                    db.add_deal({
                        "influencer_id": inf_opts[sel_inf],
                        "manufacturer_id": mfr_opts[sel_mfr],
                        "item_name": d_item,
                        "commission_rate": d_commission,
                        "start_date": str(d_start),
                        "note": d_note,
                    })
                    st.success("딜 추가 완료!")
                    st.rerun()
                else:
                    st.error("인플루언서/제조사/아이템명 필수")

    deals_all = db.get_deals()
    if deals_all:
        for deal in deals_all:
            status_ko = STATUS_KO.get(deal["status"], deal["status"])
            status_color = {"negotiating": "🟡", "confirmed": "🔵", "live": "🟢", "done": "✅", "failed": "❌"}.get(deal["status"], "⚪")
            with st.expander(f"{status_color} [{status_ko}] {deal['item_name']} | {deal.get('inf_name','')} × {deal.get('mfr_name','')}"):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**내 수수료율:** {deal['commission_rate']}%")
                c2.write(f"**시작일:** {deal.get('start_date','')}")
                c3.write(f"**내 수익:** {(deal['my_revenue'] or 0):,}원")
                st.write(f"**메모:** {deal.get('note','')}")

                col1, col2 = st.columns(2)
                new_status = col1.selectbox(
                    "상태 변경",
                    list(STATUS_KO.keys()),
                    index=list(STATUS_KO.keys()).index(deal["status"]),
                    key=f"status_{deal['id']}",
                )
                my_rev = col2.number_input("내 수익(원)", value=deal["my_revenue"] or 0, step=10000, key=f"rev_{deal['id']}")
                if st.button("업데이트", key=f"upd_{deal['id']}"):
                    db.update_deal_status(deal["id"], new_status, my_rev)
                    st.success("업데이트 완료")
                    st.rerun()
    else:
        st.info("등록된 딜 없음")
