import json
import logging

import streamlit as st

from core.store import init_db, list_channels, get_stats
from core.utils import setup_logging

setup_logging("WARNING")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="썸네일 자동화", page_icon="🎨", layout="wide")

init_db()


def render_sidebar():
    st.sidebar.title("🎨 썸네일 자동화")
    stats = get_stats()
    st.sidebar.markdown("---")
    st.sidebar.metric("등록 채널", stats["channels"])
    st.sidebar.metric("수집 썸네일", stats["thumbnails"])
    st.sidebar.metric("분석 완료", stats["analyzed"])
    st.sidebar.metric("생성 후보", stats["generated"])
    st.sidebar.metric("승인 완료", stats["approved"])
    st.sidebar.markdown("---")
    st.sidebar.caption("기초→수집→분석→생성→검수 순서로 진행")


def tab_channel_collect():
    st.header("📡 채널 수집")
    col_left, col_right = st.columns([1, 1], gap="large")
    with col_left:
        st.subheader("🔍 키워드로 자동 검색")
        from collect.youtube_collector import SEARCH_KEYWORDS, search_channels, save_selected_channels
        custom_kw = st.text_area("검색 키워드 (한 줄에 하나)", value="\n".join(SEARCH_KEYWORDS), height=220)
        max_per_kw = st.slider("키워드당 최대 채널 수", 3, 20, 5)
        if st.button("🔍 채널 검색 시작", use_container_width=True):
            keywords = [k.strip() for k in custom_kw.strip().splitlines() if k.strip()]
            with st.spinner("YouTube에서 채널 검색 중..."):
                try:
                    candidates = search_channels(keywords, max_per_keyword=max_per_kw)
                    st.session_state["candidates"] = candidates
                    st.success(f"{len(candidates)}개 채널 발견")
                except Exception as e:
                    st.error(f"검색 실패: {e}")
        if "candidates" in st.session_state:
            candidates = st.session_state["candidates"]
            selected_ids = set(st.session_state.get("selected_ids", []))
            for ch in candidates:
                subs = ch.get("subscriber_cnt", 0)
                subs_str = f"{subs:,}명" if subs else "비공개"
                cols = st.columns([0.08, 0.55, 0.22, 0.15])
                checked = cols[0].checkbox("", key=f"chk_{ch['channel_id']}", value=ch["channel_id"] in selected_ids)
                cols[1].markdown(f"**{ch['name']}**")
                cols[2].caption(f"구독자 {subs_str}")
                cols[3].caption(ch.get("matched_keyword", ""))
                if checked:
                    selected_ids.add(ch["channel_id"])
                else:
                    selected_ids.discard(ch["channel_id"])
            st.session_state["selected_ids"] = list(selected_ids)
            if st.button(f"💾 선택한 채널 저장 ({len(selected_ids)}개)", use_container_width=True, type="primary"):
                chosen = [c for c in candidates if c["channel_id"] in selected_ids]
                save_selected_channels(chosen)
                st.success(f"✅ {len(chosen)}개 채널 저장 완료")
                st.rerun()
    with col_right:
        st.subheader("✍️ 채널 직접 등록")
        st.caption("URL · @핸들 · 채널ID — 어떤 형식이든 OK")
        direct_input = st.text_area("채널 주소 (한 줄에 하나)",
            placeholder="https://www.youtube.com/@임영웅\nhttps://www.youtube.com/channel/UCxxxxxx\n@홍진영", height=160)
        note = st.text_input("메모 (선택)", placeholder="예: 벤치마킹 채널, 경쟁사")
        if st.button("➕ 등록하기", use_container_width=True):
            from collect.channel_registry import register_channels_bulk
            lines = [l.strip() for l in direct_input.strip().splitlines() if l.strip()]
            if not lines:
                st.warning("채널 주소를 입력해주세요.")
            else:
                with st.spinner("채널 정보 조회 중..."):
                    results = register_channels_bulk(lines, note=note or "직접등록")
                if results:
                    st.success(f"✅ {len(results)}개 채널 등록 완료")
                else:
                    st.error("등록된 채널이 없습니다.")
                st.rerun()
    st.markdown("---")
    st.subheader("📋 등록된 채널 목록")
    channels = list_channels()
    if not channels:
        st.info("아직 등록된 채널이 없습니다.")
    else:
        import pandas as pd
        rows = [{"채널명": ch["name"], "구독자": f"{ch['subscriber_cnt']:,}" if ch.get("subscriber_cnt") else "비공개",
            "분류/메모": ch.get("category", ""), "국가": ch.get("country", "")} for ch in channels]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)


def tab_thumbnail_collect():
    st.header("🖼️ 썸네일 수집")
    channels = list_channels()
    if not channels:
        st.warning("먼저 '채널 수집' 탭에서 채널을 등록하세요.")
        return
    ch_options = {f"{ch['name']} ({ch['channel_id']})": ch["channel_id"] for ch in channels}
    selected = st.multiselect("썸네일을 수집할 채널 선택", options=list(ch_options.keys()), default=list(ch_options.keys()))
    max_videos = st.slider("채널당 최대 영상 수", 10, 200, 50)
    dl_images = st.checkbox("이미지 파일도 로컈에 저장", value=True)
    if st.button("🖼️ 썸네일 수집 시작", type="primary", use_container_width=True):
        if not selected:
            st.warning("채널을 하나 이상 선택하세요.")
            return
        channel_ids = [ch_options[s] for s in selected]
        from collect.youtube_collector import collect_thumbnails
        with st.spinner("썸네일 수집 중..."):
            try:
                total = collect_thumbnails(channel_ids, max_videos=max_videos, download_images=dl_images)
                st.success(f"✅ {total}개 썸네일 수집 완료")
            except Exception as e:
                st.error(f"수집 실패: {e}")
        st.rerun()
    from core.store import get_conn
    import pandas as pd
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.thumb_id, t.title, t.image_url, t.local_path, t.view_count,
                   t.like_count, t.comment_count, t.published_at, c.name as channel_name
            FROM thumbnails t JOIN channels c ON c.channel_id = t.channel_id
            ORDER BY t.view_count DESC LIMIT 100
        """).fetchall()
    if rows:
        st.markdown("---")
        st.subheader("📊 수집 현황 (조회수 순)")
        table_data = []
        for row in rows:
            pub = (row["published_at"] or "")[:10]
            table_data.append({"채널": row["channel_name"], "제목": (row["title"] or "")[:30],
                "업로드": pub, "조회수": f"{row['view_count']:,}" if row['view_count'] else "-",
                "좋아요": f"{row['like_count']:,}" if row['like_count'] else "-",
                "댓글수": f"{row['comment_count']:,}" if row['comment_count'] else "-"})
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, height=280)
        st.subheader("🖼️ 썸네일 미리보기 (상위 30개)")
        cols = st.columns(5)
        for i, row in enumerate(rows[:30]):
            with cols[i % 5]:
                url = row["local_path"] or row["image_url"]
                try:
                    st.image(url, use_container_width=True)
                except Exception:
                    st.caption("이미지 없음")
                st.caption(f"👁 {row['view_count']:,}  💬 {row['comment_count']:,}\n{row['channel_name'][:14]}")


def tab_analyze():
    st.header("🔎 12레이어 분석")
    from core.store import list_unanalyzed_thumbnails
    from analyze.vision_analyzer import analyze_batch, list_analyses, get_analysis_with_thumbnail
    stats = get_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("수집된 썸네일", stats["thumbnails"])
    col2.metric("분석 완료", stats["analyzed"])
    col3.metric("미분석", stats["thumbnails"] - stats["analyzed"])
    st.markdown("---")
    limit = st.slider("한 번에 분석할 썸네일 수", 1, 50, 10)
    if st.button("🔎 분석 시작", type="primary", use_container_width=True):
        from core.config import GEMINI_API_KEY
        if not GEMINI_API_KEY:
            st.error("GEMINI_API_KEY가 .env에 없습니다.")
        else:
            unanalyzed = list_unanalyzed_thumbnails(limit=limit)
            if not unanalyzed:
                st.info("분석할 썸네일이 없습니다.")
            else:
                from analyze.vision_analyzer import analyze_thumbnail
                prog = st.progress(0)
                done = 0
                for i, thumb in enumerate(unanalyzed):
                    if analyze_thumbnail(thumb): done += 1
                    prog.progress((i+1)/len(unanalyzed))
                st.success(f"✅ {done}/{len(unanalyzed)}개 분석 완료")
                st.rerun()
    st.markdown("---")
    st.subheader("📋 분석 완료 목록")
    analyses = list_analyses(limit=50)
    if not analyses:
        st.info("분석된 썸네일이 없습니다.")
        return
    options = {f"{a['channel_name']} — {(a['title'] or '')[:30]}": a["analysis_id"] for a in analyses}
    selected_id = options[st.selectbox("썸네일 선택 (상세 보기)", list(options.keys()))]
    detail = get_analysis_with_thumbnail(selected_id)
    if not detail: return
    img_col, info_col = st.columns([1, 2], gap="large")
    with img_col:
        url = detail.get("local_path") or detail.get("image_url")
        if url: st.image(url, use_container_width=True)
        st.markdown(f"| | |\n|---|---|\n| 📌 트리거 | **{detail.get('layer11_trigger','')}** |\n| 👁 조회수 | {detail.get('view_count',0):,} |")
    with info_col:
        emo = detail.get("layer10_emotion") or {}
        if isinstance(emo, dict):
            st.markdown(f"**감정:** {emo.get('primary','')} / {emo.get('secondary','')}")
        hook = detail.get("layer12_hook", "")
        if hook: st.info(f"💡 **한 끗 제안:** {hook}")
        with st.expander("🔬 12레이어 전체 보기"):
            for k in ["layer1_composition","layer2_colors","layer3_face","layer4_hair",
                      "layer5_feature","layer6_objects","layer7_layout","layer8_background",
                      "layer9_text","layer10_emotion","layer11_trigger","layer12_hook"]:
                val = detail.get(k)
                if val:
                    st.markdown(f"**{k}**")
                    if isinstance(val, dict): st.json(val)
                    else: st.write(val)
                    st.markdown("---")


def tab_generate():
    st.header("💡 한 끗 생성")
    from analyze.vision_analyzer import list_analyses, get_analysis_with_thumbnail
    from generate.hook_generator import generate_hook, list_all_hook_types
    from generate.prompt_builder import build_prompt
    from generate.ctr_predictor import score_ctr, format_score_report
    from core.store import insert_generated
    from core.utils import new_id
    analyses = list_analyses(limit=100)
    if not analyses:
        st.warning("먼저 '분석' 탭에서 썸네일을 분석하세요.")
        return
    options = {f"{a['channel_name']} — {(a['title'] or '')[:30]}  [👁{a.get('view_count',0):,}]": a["analysis_id"] for a in analyses}
    selected_id = options[st.selectbox("분석된 썸네일 선택", list(options.keys()))]
    detail = get_analysis_with_thumbnail(selected_id)
    if not detail: st.error("분석 데이터를 불러올 수 없습니다."); return
    col_img, col_meta = st.columns([1, 2])
    with col_img:
        url = detail.get("local_path") or detail.get("image_url")
        if url: st.image(url, use_container_width=True)
    with col_meta:
        emo = detail.get("layer10_emotion") or {}
        if isinstance(emo, dict): st.markdown(f"**감정:** {emo.get('primary','')} / {emo.get('secondary','')}")
        st.markdown(f"**현재 트리거:** `{detail.get('layer11_trigger', '')}`")
    st.markdown("---")
    from core.config import GEMINI_API_KEY
    col_set1, col_set2 = st.columns(2)
    with col_set1:
        hook_types = ["자동 선택"] + [h["id"] for h in list_all_hook_types()]
        chosen_type = st.selectbox("한 끗 유형 선택", hook_types)
        hook_type_val = None if chosen_type == "자동 선택" else chosen_type
    with col_set2:
        use_ai = st.toggle("AI 생성 (Gemini)", value=bool(GEMINI_API_KEY))
        use_ai2 = st.toggle("AI 프롬프트 (Gemini)", value=bool(GEMINI_API_KEY))
    if st.button("💡 한 끗 + 프롬프트 생성", type="primary", use_container_width=True):
        with st.spinner("한 끗 아이디어 생성 중..."):
            hook = generate_hook(detail, hook_type=hook_type_val, use_ai=use_ai)
        with st.spinner("이미지 프롬프트 조립 중..."):
            prompt = build_prompt(detail, hook, use_ai=use_ai2)
        score = score_ctr(detail, hook, prompt)
        st.session_state.update({"last_hook": hook, "last_prompt": prompt, "last_score": score, "last_analysis_id": selected_id})
    if "last_hook" in st.session_state and st.session_state.get("last_analysis_id") == selected_id:
        hook = st.session_state["last_hook"]
        prompt = st.session_state["last_prompt"]
        score = st.session_state["last_score"]
        st.markdown("---")
        col_hook, col_score = st.columns([3, 2])
        with col_hook:
            st.subheader(f"💡 한 끗: {hook['hook_type']}")
            st.info(hook.get("idea", ""))
            if hook.get("expected_effect"): st.success(f"📈 기대 효과: {hook['expected_effect']}")
        with col_score:
            st.subheader("📊 CTR 예측")
            total = score["total"]
            st.metric("예측 점수", f"{total} / 100")
            st.progress(total / 100)
            st.caption(score["grade"])
        st.markdown("---")
        st.subheader("📝 이미지 생성 프롬프트")
        tab_dalle, tab_sd = st.tabs(["DALL-E 3", "Stable Diffusion"])
        with tab_dalle:
            edited_dalle = st.text_area("DALL-E 프롬프트 (수정 가능)", value=prompt["dalle"], height=160)
        with tab_sd:
            st.text_area("SD 프롬프트", value=prompt["sd"], height=100)
            st.text_area("네거티브 프롬프트", value=prompt["negative"], height=70)
        if st.button("💾 프롬프트 저장 (이미지 생성 대기)", use_container_width=True):
            gen_id = new_id("gen")
            insert_generated({"gen_id": gen_id, "analysis_id": selected_id,
                "hook_type": hook["hook_type"], "prompt_text": edited_dalle,
                "image_path": None, "ctr_score": score["total"], "status": "pending", "feedback": ""})
            st.success(f"✅ 저장 완료 (gen_id: {gen_id[:12]})")
            st.rerun()


def tab_render():
    st.header("🎨 이미지 생성")
    from render.image_generator import available_engines, generate_images, ENGINES
    from core.store import list_generated
    st.subheader("⚙️ 사용 가능한 생성 엔진")
    cols = st.columns(3)
    for i, (eid, ecfg) in enumerate(ENGINES.items()):
        with cols[i]:
            status = "✅ 활성" if ecfg["available"] else "❌ 키 없음"
            st.markdown(f"**{ecfg['name']}**\n{status}\n{ecfg['best_for']}")
    avail = available_engines()
    if not avail:
        st.error("사용 가능한 이미지 생성 API가 없습니다.")
        return
    st.markdown("---")
    from core.store import get_conn
    with get_conn() as conn:
        pending = conn.execute("""
            SELECT g.gen_id, g.prompt_text, g.hook_type, g.ctr_score, g.analysis_id,
                   t.title, c.name as channel_name
            FROM generated_thumbnails g
            JOIN analysis a ON a.analysis_id = g.analysis_id
            JOIN thumbnails t ON t.thumb_id = a.thumb_id
            JOIN channels c ON c.channel_id = t.channel_id
            WHERE g.image_path IS NULL AND g.status = 'pending'
            ORDER BY g.created_at DESC LIMIT 20
        """).fetchall()
    prompt_val = analysis_id = hook_type_val = ""
    ctr_val = 0.0
    if pending:
        opts = {f"[{p['hook_type']}] {p['channel_name']} — {(p['title'] or '')[:25]}  CTR:{p['ctr_score']:.0f}점": p for p in pending}
        sel_row = opts[st.selectbox("저장된 프롬프트 선택", list(opts.keys()))]
        prompt_val = sel_row["prompt_text"]
        analysis_id = sel_row["analysis_id"]
        hook_type_val = sel_row["hook_type"]
        ctr_val = sel_row["ctr_score"]
    else:
        st.info("저장된 프롬프트가 없습니다. '한 끗 생성' 탭에서 먼저 프롬프트를 저장하세요.")
    with st.expander("✏️ 프롬프트 직접 입력 또는 수정"):
        prompt_val = st.text_area("프롬프트 (영어)", value=prompt_val, height=130)
        negative_val = st.text_input("네거티브 프롬프트", value="blurry, low quality, watermark, ugly, deformed")
        analysis_id = st.text_input("analysis_id (선택)", value=analysis_id)
    col_eng, col_cnt = st.columns([3, 1])
    with col_eng:
        chosen_engines = st.multiselect("생성 엔진 선택", [e["id"] for e in avail],
            default=[e["id"] for e in avail], format_func=lambda x: ENGINES[x]["name"])
    with col_cnt:
        count_per = st.number_input("엔진당 장수", 1, 4, 2)
    if st.button("🎨 이미지 생성 시작", type="primary", use_container_width=True, disabled=not (prompt_val and chosen_engines)):
        results = []
        for eid in chosen_engines:
            try:
                partial = generate_images(analysis_id=analysis_id or "direct", prompt=prompt_val,
                    negative=negative_val, hook_type=hook_type_val, ctr_score=ctr_val,
                    engines=[eid], count_per_engine=count_per, parallel=False)
                results.extend(partial)
            except Exception as e:
                st.warning(f"⚠️ {ENGINES[eid]['name']}: {e}")
        ok = [r for r in results if r.get("image_path")]
        st.success(f"✅ {len(ok)}장 생성 완료")
        st.session_state["last_generated"] = ok
        st.rerun()
    if st.session_state.get("last_generated"):
        imgs = st.session_state["last_generated"]
        st.subheader(f"🖼️ 생성 결과 — {len(imgs)}장")
        cols = st.columns(min(len(imgs), 4))
        for i, r in enumerate(imgs):
            with cols[i % 4]:
                try: st.image(r["image_path"], use_container_width=True)
                except Exception: st.caption("이미지 로드 실패")
                st.caption(f"🤖 {ENGINES.get(r['engine'],{}).get('name', r['engine'])}")


def tab_review():
    st.header("✅ 검수 · 컨펀")
    from core.store import list_generated, update_generated_status
    filter_status = st.selectbox("상태 필터", ["pending", "approved", "rejected", "전체"])
    limit = st.slider("표시 개수", 10, 100, 30)
    items = list_generated(status=None if filter_status == "전체" else filter_status)[:limit]
    if not items:
        st.info("검수할 이미지가 없습니다. '이미지 생성' 탭에서 도로 영상을 생성하세요.")
        return
    st.markdown(f"**{len(items)}개** 항목")
    cols = st.columns(4)
    for i, item in enumerate(items):
        with cols[i % 4]:
            path = item.get("image_path")
            if path:
                try: st.image(path, use_container_width=True)
                except Exception: st.caption("🖼️ 이미지 없음")
            else:
                st.caption("🖼️ 이미지 없음")
            status = item.get("status", "pending")
            status_color = {"확인": "🟢", "rejected": "🔴", "pending": "🟡"}.get(status, "⚪")
            st.caption(f"📊 CTR: {item.get('ctr_score', 0):.0f}점  |  {item.get('hook_type', '')}\n{status_color} {status}")
            gen_id = item["gen_id"]
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅", key=f"approve_{gen_id}", disabled=(status == "approved")):
                    update_generated_status(gen_id, "approved"); st.rerun()
            with col_b:
                if st.button("❌", key=f"reject_{gen_id}", disabled=(status == "rejected")):
                    update_generated_status(gen_id, "rejected"); st.rerun()


def tab_pinterest():
    st.header("🌸 Pinterest 트렌드")
    from collect.pinterest_collector import collect_pinterest_trends, get_pinterest_stats, get_trend_images, PINTEREST_KEYWORDS
    from core.config import PINTEREST_TOKEN
    try:
        stats = get_pinterest_stats()
        col1, col2 = st.columns(2)
        col1.metric("수집된 핀 수", stats["total"])
        col2.metric("카테고리 수", len(stats["by_category"]))
    except Exception:
        st.info("아직 수집된 핀이 없습니다.")
    st.markdown("---")
    mode = "API" if PINTEREST_TOKEN else "스크래핑"
    st.caption(f"현재 모드: **{mode}**")
    all_cats = list(PINTEREST_KEYWORDS.keys())
    chosen_cats = st.multiselect("수집할 카테고리", all_cats, default=all_cats[:4])
    max_per_kw = st.slider("키워드당 최대 핀 수", 5, 30, 10)
    dl_images = st.checkbox("이미지 로컈 저장 (색상 분석 포함)", value=True)
    if st.button("🌸 Pinterest 수집 시작", type="primary", use_container_width=True):
        with st.spinner("Pinterest 트렌드 수집 중..."):
            try:
                n = collect_pinterest_trends(categories=chosen_cats, max_per_keyword=max_per_kw, download=dl_images)
                st.success(f"✅ {n}개 핀 수집 완료")
            except Exception as e:
                st.error(f"수집 실패: {e}")
        st.rerun()
    st.markdown("---")
    filter_cat = st.selectbox("카테고리 필터", ["전체"] + all_cats)
    pins = get_trend_images(category=None if filter_cat == "전체" else filter_cat, limit=40)
    if pins:
        cols = st.columns(5)
        for i, pin in enumerate(pins):
            with cols[i % 5]:
                url = pin.get("local_path") or pin.get("image_url")
                try: st.image(url, use_container_width=True)
                except Exception: st.caption("🖼️")
                if pin.get("dominant_color"):
                    st.markdown(f"<div style='background:{pin['dominant_color']};height:8px;border-radius:4px'></div>", unsafe_allow_html=True)
                st.caption(f"{pin.get('keyword','')[:20]}")
    else:
        st.info("수집된 핀이 없습니다.")


def tab_hook_manager():
    st.header("🧠 한 끗 관리")
    from generate.custom_hooks import list_custom_hooks, add_custom_hook, delete_custom_hook
    from generate.pattern_miner import mine_patterns, pattern_to_hook_hint
    from generate.feedback_learner import learn_from_approved
    from core.config import CATEGORIES
    inner_tab1, inner_tab2, inner_tab3 = st.tabs(["✍️ 나만의 공식 등록", "📊 DB 패턴 인사이트", "🏆 피드백 학습 결과"])
    with inner_tab1:
        customs = list_custom_hooks()
        if customs:
            for h in customs:
                col_a, col_b = st.columns([5, 1])
                col_a.markdown(f"**[{h['id']}]** {h['description']}")
                col_a.caption(f"적용 카테고리: {', '.join(h.get('best_for',[]))}")
                if col_b.button("삭제", key=f"del_{h['id']}"):
                    delete_custom_hook(h["id"]); st.rerun()
        else:
            st.info("아직 등록된 나만의 공식이 없습니다.")
        with st.form("add_hook_form"):
            h_id = st.text_input("공식 ID (영문, 공백없이)")
            h_desc = st.text_area("설명")
            h_cats = st.multiselect("효과 있는 카테고리", list(CATEGORIES.keys()))
            h_kws = st.text_input("프롬프트 키워드 (콤마 구분, 영어)")
            h_exs = st.text_input("예시 (콤마 구분)")
            if st.form_submit_button("등록", type="primary"):
                if h_id and h_desc:
                    add_custom_hook(h_id, h_desc, h_cats, [k.strip() for k in h_kws.split(",") if k.strip()], [e.strip() for e in h_exs.split(",") if e.strip()])
                    st.success(f"✅ '{h_id}' 등록 완료!")
                    st.rerun()
    with inner_tab2:
        min_views = st.number_input("최소 조회수 기준", value=50000, step=10000)
        if st.button("🔍 패턴 분석"):
            patterns = mine_patterns(min_view_count=int(min_views))
            if not patterns or patterns.get("sample_count", 0) == 0:
                st.warning("분석 데이터가 부족합니다.")
            else:
                st.caption(f"분석 샘플: {patterns['sample_count']}개")
                def show_pattern(label, items):
                    if not items: return
                    st.markdown(f"**{label}**")
                    for item in items:
                        val = item.get("value") or item.get("trigger") or item.get("temp", "")
                        st.progress(item.get("pct", 0)/100, text=f"{val} — {item.get('pct',0)}%")
                col1, col2 = st.columns(2)
                with col1:
                    show_pattern("파도", patterns.get("composition", []))
                    show_pattern("시선", patterns.get("gaze", []))
                with col2:
                    show_pattern("트리거", patterns.get("triggers", []))
                    show_pattern("색온도", patterns.get("color_temp", []))
    with inner_tab3:
        fb = learn_from_approved()
        if fb.get("sample_count", 0) == 0:
            st.info("아직 승인된 썸네일이 없습니다.")
        else:
            st.info(fb.get("insight", ""))
            col1, col2, col3 = st.columns(3)
            col1.metric("학습 샘플", fb["sample_count"])
            col2.metric("평균 CTR 점수", f"{fb['avg_ctr']}점")
            col3.metric("최적 한 끗", fb["top_hooks"][0]["hook"] if fb.get("top_hooks") else "-")


def tab_operate():
    st.header("🚀 운영 · 알고리즘 전략")
    from operate.youtube_trend_watcher import get_upload_timing_advice, extract_trend_keywords
    from operate.reporter import generate_daily_report, format_report_text
    from operate.scheduler import TASKS
    timing = get_upload_timing_advice()
    col1, col2, col3 = st.columns(3)
    col1.metric("현재 시각 (KST)", f"{timing['current_hour_kst']}시")
    col2.metric("피크 타임", "지금!" if timing["is_peak"] else f"{timing['next_peak_hour']}시부터")
    col3.metric("요일", "주말" if timing["is_weekend"] else "평일")
    st.info(f"{'\U0001f7e2' if timing['is_peak'] else '\U0001f7e1'} {timing['advice']}")
    st.markdown("---")
    st.subheader("🔥 지금 뜨는 키워드")
    keywords = extract_trend_keywords(limit=200)
    if keywords:
        cols = st.columns(2)
        for i, kw in enumerate(keywords[:14]):
            with cols[i % 2]:
                st.progress(min(kw["count"]/max(keywords[0]["count"], 1), 1.0), text=f"#{kw['keyword']}  ({kw['count']}회)")
    else:
        st.info("급상승 영상을 먼저 수집하세요.")
    st.markdown("---")
    st.subheader("⚙️ 수동 실행")
    task_labels = {"detect": "🔍 경쟁 채널 새 업로드 감지", "pinterest": "🌸 Pinterest 트렌드 수집",
        "trend": "📈 유튜브 급상승 수집·분석", "pattern": "🧠 DB 패턴 마이닝",
        "peak": "⏰ 피크 알림 저장", "report": "📄 일일 리포트 생성"}
    cols = st.columns(3)
    for i, (task_id, label) in enumerate(task_labels.items()):
        with cols[i % 3]:
            if st.button(label, use_container_width=True):
                with st.spinner(f"{label} 실행 중..."):
                    try:
                        TASKS[task_id]()
                        st.success("✅ 완료")
                    except Exception as e:
                        st.error(f"실패: {e}")
                st.rerun()
    if st.button("🚀 전체 태스크 1회 실행", type="primary", use_container_width=True):
        from operate.scheduler import run_all
        with st.spinner("전체 실행 중..."):
            run_all()
        st.success("✅ 전체 완료")
        st.rerun()
    st.markdown("---")
    st.subheader("📄 일일 리포트")
    if st.button("리포트 생성"):
        with st.spinner("리포트 생성 중..."):
            report = generate_daily_report()
        st.text(format_report_text(report))
    from core.config import ROOT_DIR
    log_path = ROOT_DIR / "data" / "scheduler_log.jsonl"
    if log_path.exists():
        st.subheader("📋 최근 실행 로그")
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines[-20:]):
            try:
                entry = json.loads(line)
                icon = "✅" if entry["status"] == "ok" else ("⏭️" if entry["status"] == "skip" else "❌")
                st.caption(f"{icon} `{entry['ts'][:16]}` [{entry['task']}] {entry['detail']}")
            except Exception:
                pass


def main():
    render_sidebar()
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
        "📡 채널 수집", "🖼️ 썸네일 수집", "🌸 Pinterest",
        "🔎 분석", "💡 한 끗 생성", "🧠 한 끗 관리",
        "🎨 이미지 생성", "✅ 검수", "🚀 운영·전략"
    ])
    with tab1: tab_channel_collect()
    with tab2: tab_thumbnail_collect()
    with tab3: tab_pinterest()
    with tab4: tab_analyze()
    with tab5: tab_generate()
    with tab6: tab_hook_manager()
    with tab7: tab_render()
    with tab8: tab_review()
    with tab9: tab_operate()


if __name__ == "__main__":
    main()
