"""
5층: Streamlit 검수 UI.
탭 구성:
  1. 📡 채널 수집    — 키워드 검색 + 직접 등록 + 선택 저장
  2. 🖼️  썸네일 수집  — 선택된 채널에서 썸네일 가져오기
  3. 🔎 분석 (예정)
  4. 💡 생성 (예정)
  5. ✅ 검수 (예정)
"""
import logging

import streamlit as st

from core.store import init_db, list_channels, get_stats
from core.utils import setup_logging

setup_logging("WARNING")
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="썸네일 자동화",
    page_icon="🎨",
    layout="wide",
)

# DB 초기화 (최초 1회)
init_db()


# ─────────────────────────────────────────────────────────
# 사이드바 — 현황 요약
# ─────────────────────────────────────────────────────────

def render_sidebar():
    st.sidebar.title("🎨 썸네일 자동화")
    stats = get_stats()
    st.sidebar.markdown("---")
    st.sidebar.metric("등록 채널",  stats["channels"])
    st.sidebar.metric("수집 썸네일", stats["thumbnails"])
    st.sidebar.metric("분석 완료",  stats["analyzed"])
    st.sidebar.metric("생성 후보",  stats["generated"])
    st.sidebar.metric("승인 완료",  stats["approved"])
    st.sidebar.markdown("---")
    st.sidebar.caption("기초→수집→분석→생성→검수 순서로 진행")


# ─────────────────────────────────────────────────────────
# 탭 1: 채널 수집
# ─────────────────────────────────────────────────────────

def tab_channel_collect():
    st.header("📡 채널 수집")

    col_left, col_right = st.columns([1, 1], gap="large")

    # ── 왼쪽: 키워드 자동 검색 ──────────────────────────
    with col_left:
        st.subheader("🔍 키워드로 자동 검색")

        from collect.youtube_collector import SEARCH_KEYWORDS, search_channels, save_selected_channels

        custom_kw = st.text_area(
            "검색 키워드 (한 줄에 하나)",
            value="\n".join(SEARCH_KEYWORDS),
            height=220,
        )
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

        # 검색 결과 테이블 + 선택
        if "candidates" in st.session_state:
            candidates = st.session_state["candidates"]
            st.markdown(f"**{len(candidates)}개 후보** — 저장할 채널을 선택하세요")

            selected_ids = set(st.session_state.get("selected_ids", []))

            for ch in candidates:
                subs = ch.get("subscriber_cnt", 0)
                subs_str = f"{subs:,}명" if subs else "비공개"
                cols = st.columns([0.08, 0.15, 0.55, 0.22])
                checked = cols[0].checkbox("", key=f"chk_{ch['channel_id']}",
                                           value=ch["channel_id"] in selected_ids)
                thumb_url = ch.get("thumbnail_url", "")
                if thumb_url:
                    cols[1].image(thumb_url, width=60)
                cols[2].markdown(f"**{ch['name']}**")
                cols[2].caption(f"구독자 {subs_str} | {ch.get('matched_keyword', '')}")
                cols[3].caption(ch.get("description", "")[:40] if ch.get("description") else "")
                if checked:
                    selected_ids.add(ch["channel_id"])
                else:
                    selected_ids.discard(ch["channel_id"])

            st.session_state["selected_ids"] = list(selected_ids)

            if st.button(f"💾 선택한 채널 저장 ({len(selected_ids)}개)",
                         use_container_width=True, type="primary"):
                chosen = [c for c in candidates if c["channel_id"] in selected_ids]
                save_selected_channels(chosen)
                st.success(f"✅ {len(chosen)}개 채널 저장 완료")
                st.rerun()

    # ── 오른쪽: 직접 등록 ────────────────────────────────
    with col_right:
        st.subheader("✍️ 채널 직접 등록")
        st.caption("URL · @핸들 · 채널ID — 어떤 형식이든 OK")

        direct_input = st.text_area(
            "채널 주소 (한 줄에 하나)",
            placeholder=(
                "https://www.youtube.com/@임영웅\n"
                "https://www.youtube.com/channel/UCxxxxxx\n"
                "@홍진영\n"
                "UCxxxxxx"
            ),
            height=160,
        )
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
                    for ch in results:
                        subs = f"{ch['subscriber_cnt']:,}명" if ch['subscriber_cnt'] else "비공개"
                        st.markdown(f"- **{ch['name']}** | 구독자 {subs}")
                else:
                    st.error("등록된 채널이 없습니다. 주소를 다시 확인하세요.")
                st.rerun()

    # ── 하단: 등록된 채널 목록 ─────────────────────────
    st.markdown("---")
    st.subheader("📋 등록된 채널 목록")
    channels = list_channels()
    if not channels:
        st.info("아직 등록된 채널이 없습니다.")
    else:
        rows = []
        for ch in channels:
            subs = f"{ch['subscriber_cnt']:,}" if ch.get("subscriber_cnt") else "비공개"
            rows.append({
                "채널명": ch["name"],
                "구독자": subs,
                "분류/메모": ch.get("category", ""),
                "국가": ch.get("country", ""),
                "channel_id": ch["channel_id"],
            })
        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df.drop(columns=["channel_id"]), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 탭 2: 썸네일 수집
# ─────────────────────────────────────────────────────────

def tab_thumbnail_collect():
    st.header("🖼️ 썸네일 수집")

    channels = list_channels()
    if not channels:
        st.warning("먼저 '채널 수집' 탭에서 채널을 등록하세요.")
        return

    ch_options = {f"{ch['name']} ({ch['channel_id']})": ch["channel_id"] for ch in channels}
    selected = st.multiselect(
        "썸네일을 수집할 채널 선택",
        options=list(ch_options.keys()),
        default=list(ch_options.keys()),
    )
    max_videos   = st.slider("채널당 최대 영상 수", 10, 200, 50)
    dl_images    = st.checkbox("이미지 파일도 로컬에 저장", value=True)

    if st.button("🖼️ 썸네일 수집 시작", type="primary", use_container_width=True):
        if not selected:
            st.warning("채널을 하나 이상 선택하세요.")
            return
        channel_ids = [ch_options[s] for s in selected]
        from collect.youtube_collector import collect_thumbnails
        with st.spinner("썸네일 수집 중... (채널 수에 따라 수 분 소요)"):
            try:
                total = collect_thumbnails(channel_ids, max_videos=max_videos,
                                           download_images=dl_images)
                st.success(f"✅ {total}개 썸네일 수집 완료")
            except Exception as e:
                st.error(f"수집 실패: {e}")
        st.rerun()

    # 수집된 썸네일 미리보기
    from core.store import get_conn
    import pandas as pd

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.thumb_id, t.title, t.image_url, t.local_path,
                   t.view_count, t.like_count, t.comment_count,
                   t.published_at, c.name as channel_name
            FROM thumbnails t
            JOIN channels c ON c.channel_id = t.channel_id
            ORDER BY t.view_count DESC
            LIMIT 100
        """).fetchall()

    if rows:
        st.markdown("---")

        # 수치 테이블
        st.subheader("📊 수집 현황 (조회수 순)")
        table_data = []
        for row in rows:
            pub = (row["published_at"] or "")[:10]
            table_data.append({
                "채널":      row["channel_name"],
                "제목":      (row["title"] or "")[:30],
                "업로드":    pub,
                "조회수":    f"{row['view_count']:,}" if row['view_count'] else "-",
                "좋아요":    f"{row['like_count']:,}" if row['like_count'] else "-",
                "댓글수":    f"{row['comment_count']:,}" if row['comment_count'] else "-",
            })
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, height=280)

        # 썸네일 그리드
        st.subheader("🖼️ 썸네일 미리보기 (상위 30개)")
        cols = st.columns(5)
        for i, row in enumerate(rows[:30]):
            with cols[i % 5]:
                url = row["local_path"] or row["image_url"]
                try:
                    st.image(url, use_container_width=True)
                except Exception:
                    st.caption("이미지 없음")
                views    = f"👁 {row['view_count']:,}" if row['view_count'] else "👁 -"
                comments = f"💬 {row['comment_count']:,}" if row['comment_count'] else "💬 -"
                pub      = (row["published_at"] or "")[:10]
                st.caption(f"{views}  {comments}\n📅 {pub}\n{row['channel_name'][:14]}")


# ─────────────────────────────────────────────────────────
# 탭 3~5: 예정
# ─────────────────────────────────────────────────────────

def tab_analyze():
    st.header("🔎 12레이어 분석")

    from core.store import list_unanalyzed_thumbnails, get_stats
    from analyze.vision_analyzer import analyze_batch, list_analyses, get_analysis_with_thumbnail

    stats = get_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("수집된 썸네일", stats["thumbnails"])
    col2.metric("분석 완료", stats["analyzed"])
    col3.metric("미분석", stats["thumbnails"] - stats["analyzed"])

    st.markdown("---")

    # ── 분석 실행 ──────────────────────────────────────────
    st.subheader("⚙️ 분석 실행")
    limit = st.slider("한 번에 분석할 썸네일 수", 1, 50, 10)

    if st.button("🔎 분석 시작", type="primary", use_container_width=True):
        if not __import__("core.config", fromlist=["GEMINI_API_KEY"]).GEMINI_API_KEY:
            st.error("GEMINI_API_KEY가 .env에 없습니다.")
        else:
            progress = st.progress(0, text="분석 중...")
            unanalyzed = list_unanalyzed_thumbnails(limit=limit)
            total = len(unanalyzed)
            if total == 0:
                st.info("분석할 썸네일이 없습니다.")
            else:
                from analyze.vision_analyzer import analyze_thumbnail
                done = 0
                for i, thumb in enumerate(unanalyzed):
                    result = analyze_thumbnail(thumb)
                    if result:
                        done += 1
                    progress.progress((i+1)/total, text=f"분석 중 {i+1}/{total}...")
                st.success(f"✅ {done}/{total}개 분석 완료")
                st.rerun()

    # ── 분석 결과 목록 ─────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 분석 완료 목록")

    analyses = list_analyses(limit=50)
    if not analyses:
        st.info("분석된 썸네일이 없습니다.")
        return

    # 선택해서 상세 보기
    options = {
        f"{a['channel_name']} — {(a['title'] or '')[:30]}": a["analysis_id"]
        for a in analyses
    }
    selected_label = st.selectbox("썸네일 선택 (상세 보기)", list(options.keys()))
    selected_id    = options[selected_label]

    detail = get_analysis_with_thumbnail(selected_id)
    if not detail:
        return

    # 상세 카드
    img_col, info_col = st.columns([1, 2], gap="large")

    with img_col:
        url = detail.get("local_path") or detail.get("image_url")
        if url:
            st.image(url, use_container_width=True)
        views    = f"{detail.get('view_count',0):,}"
        comments = f"{detail.get('comment_count',0):,}"
        pub      = (detail.get("published_at") or "")[:10]
        st.markdown(f"""
| | |
|---|---|
| 📅 업로드 | {pub} |
| 👁 조회수 | {views} |
| 💬 댓글수 | {comments} |
| 📌 트리거 | **{detail.get('layer11_trigger','')}** |
""")

    with info_col:
        emo = detail.get("layer10_emotion") or {}
        if isinstance(emo, dict):
            st.markdown(f"**감정:** {emo.get('primary','')} / {emo.get('secondary','')}")
            st.caption(emo.get("overall_mood", ""))

        hook = detail.get("layer12_hook", "")
        if hook:
            st.info(f"💡 **한 끗 제안:** {hook}")

        # 12레이어 펼치기
        with st.expander("🔬 12레이어 전체 보기"):
            layer_labels = {
                "layer1_composition": "Layer 1 — 구도",
                "layer2_colors":      "Layer 2 — 색상",
                "layer3_face":        "Layer 3 — 인물/표정",
                "layer4_hair":        "Layer 4 — 헤어",
                "layer5_feature":     "Layer 5 — 특징점",
                "layer6_objects":     "Layer 6 — 오브젝트",
                "layer7_layout":      "Layer 7 — 배치",
                "layer8_background":  "Layer 8 — 배경",
                "layer9_text":        "Layer 9 — 텍스트",
                "layer10_emotion":    "Layer 10 — 감정톤",
                "layer11_trigger":    "Layer 11 — 클릭 트리거",
                "layer12_hook":       "Layer 12 — 한 끗 제안",
            }
            for key, label in layer_labels.items():
                val = detail.get(key)
                if val:
                    st.markdown(f"**{label}**")
                    if isinstance(val, dict):
                        st.json(val)
                    else:
                        st.write(val)
                    st.markdown("---")

def tab_generate():
    st.header("💡 한 끗 생성")

    from analyze.vision_analyzer import list_analyses, get_analysis_with_thumbnail
    from generate.hook_generator import generate_hook, list_all_hook_types
    from generate.prompt_builder import build_prompt
    from generate.ctr_predictor  import score_ctr, format_score_report
    from core.store import insert_generated
    from core.utils import new_id

    analyses = list_analyses(limit=100)
    if not analyses:
        st.warning("먼저 '분석' 탭에서 썸네일을 분석하세요.")
        return

    # 썸네일 선택
    options = {
        f"{a['channel_name']} — {(a['title'] or '')[:30]}  [👁{a.get('view_count',0):,}]": a["analysis_id"]
        for a in analyses
    }
    selected_label = st.selectbox("분석된 썸네일 선택", list(options.keys()))
    selected_id    = options[selected_label]
    detail         = get_analysis_with_thumbnail(selected_id)

    if not detail:
        st.error("분석 데이터를 불러올 수 없습니다.")
        return

    # 썸네일 미리보기
    col_img, col_meta = st.columns([1, 2])
    with col_img:
        url = detail.get("local_path") or detail.get("image_url")
        if url:
            st.image(url, use_container_width=True)
    with col_meta:
        emo = detail.get("layer10_emotion") or {}
        if isinstance(emo, dict):
            st.markdown(f"**감정:** {emo.get('primary','')} / {emo.get('secondary','')}")
            st.caption(emo.get("overall_mood", ""))
        trigger = detail.get("layer11_trigger", "")
        st.markdown(f"**현재 트리거:** `{trigger}`")
        current_hook = detail.get("layer12_hook", "")
        if current_hook:
            st.caption(f"기존 제안: {current_hook}")

    st.markdown("---")

    # 한 끗 설정
    col_set1, col_set2 = st.columns(2)
    with col_set1:
        hook_types   = ["자동 선택"] + [h["id"] for h in list_all_hook_types()]
        chosen_type  = st.selectbox("한 끗 유형 선택", hook_types)
        hook_type_val = None if chosen_type == "자동 선택" else chosen_type
    with col_set2:
        use_ai  = st.toggle("AI 생성 (Gemini)", value=bool(__import__("core.config", fromlist=["GEMINI_API_KEY"]).GEMINI_API_KEY))
        use_ai2 = st.toggle("AI 프롬프트 (Gemini)", value=bool(__import__("core.config", fromlist=["GEMINI_API_KEY"]).GEMINI_API_KEY))

    if st.button("💡 한 끗 + 프롬프트 생성", type="primary", use_container_width=True):
        with st.spinner("한 끗 아이디어 생성 중..."):
            hook   = generate_hook(detail, hook_type=hook_type_val, use_ai=use_ai)
        with st.spinner("이미지 프롬프트 조립 중..."):
            prompt = build_prompt(detail, hook, use_ai=use_ai2)
        score  = score_ctr(detail, hook, prompt)

        st.session_state["last_hook"]   = hook
        st.session_state["last_prompt"] = prompt
        st.session_state["last_score"]  = score
        st.session_state["last_analysis_id"] = selected_id

    # 결과 표시
    if "last_hook" in st.session_state and st.session_state.get("last_analysis_id") == selected_id:
        hook   = st.session_state["last_hook"]
        prompt = st.session_state["last_prompt"]
        score  = st.session_state["last_score"]

        st.markdown("---")
        col_hook, col_score = st.columns([3, 2])

        with col_hook:
            st.subheader(f"💡 한 끗: {hook['hook_type']}")
            st.info(hook.get("idea", ""))
            if hook.get("expected_effect"):
                st.success(f"📈 기대 효과: {hook['expected_effect']}")
            st.caption(f"생성 방식: {'AI' if hook.get('source')=='ai' else '규칙 기반'}")

        with col_score:
            st.subheader("📊 CTR 예측")
            total = score["total"]
            st.metric("예측 점수", f"{total} / 100")
            st.progress(total / 100)
            st.caption(score["grade"])
            if score["advice"]:
                with st.expander("💬 개선 조언"):
                    for a in score["advice"]:
                        st.write(f"• {a}")

        # 프롬프트 박스
        st.markdown("---")
        st.subheader("📝 이미지 생성 프롬프트")

        tab_dalle, tab_sd = st.tabs(["DALL-E 3", "Stable Diffusion"])
        with tab_dalle:
            edited_dalle = st.text_area("DALL-E 프롬프트 (수정 가능)", value=prompt["dalle"], height=160)
            st.caption("→ 4층 렌더 탭에서 이 프롬프트로 이미지를 생성합니다")
        with tab_sd:
            st.text_area("SD 프롬프트", value=prompt["sd"], height=100)
            st.text_area("네거티브 프롬프트", value=prompt["negative"], height=70)

        # 저장
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("💾 프롬프트 저장 (이미지 생성 대기)", use_container_width=True):
                gen_id = new_id("gen")
                insert_generated({
                    "gen_id":      gen_id,
                    "analysis_id": selected_id,
                    "hook_type":   hook["hook_type"],
                    "prompt_text": edited_dalle,
                    "image_path":  None,
                    "ctr_score":   score["total"],
                    "status":      "pending",
                    "feedback":    "",
                })
                st.success(f"✅ 저장 완료 (gen_id: {gen_id[:12]})")
                st.session_state["saved_gen_id"]    = gen_id
                st.session_state["saved_prompt"]    = edited_dalle
                st.rerun()
        with col_s2:
            if "saved_gen_id" in st.session_state:
                st.info(f"저장됨: {st.session_state['saved_gen_id'][:12]}")

def tab_render():
    st.header("🎨 이미지 생성")

    from render.image_generator import available_engines, generate_images, ENGINES
    from core.store import list_generated
    from core.config import GEN_DIR

    # ── 엔진 현황 ─────────────────────────────────────────
    st.subheader("⚙️ 사용 가능한 생성 엔진")
    cols = st.columns(3)
    engine_ids = list(ENGINES.keys())
    for i, (eid, ecfg) in enumerate(ENGINES.items()):
        with cols[i]:
            status = "✅ 활성" if ecfg["available"] else "❌ 키 없음"
            color  = "green" if ecfg["available"] else "red"
            st.markdown(f"**{ecfg['name']}**")
            st.markdown(f":{color}[{status}]")
            st.caption(ecfg["best_for"])
            if not ecfg["available"]:
                st.caption(f"→ .env에 `{ecfg['key']}` 추가")

    avail = available_engines()
    if not avail:
        st.error("사용 가능한 이미지 생성 API가 없습니다. .env에 API 키를 하나 이상 추가하세요.")
        return

    st.markdown("---")

    # ── 저장된 프롬프트 불러오기 ──────────────────────────
    st.subheader("📝 생성할 프롬프트")
    from core.store import get_conn
    with get_conn() as conn:
        pending = conn.execute("""
            SELECT g.gen_id, g.prompt_text, g.hook_type, g.ctr_score,
                   g.analysis_id, a.layer10_emotion,
                   t.title, c.name as channel_name
            FROM generated_thumbnails g
            JOIN analysis a ON a.analysis_id = g.analysis_id
            JOIN thumbnails t ON t.thumb_id = a.thumb_id
            JOIN channels c ON c.channel_id = t.channel_id
            WHERE g.image_path IS NULL AND g.status = 'pending'
            ORDER BY g.created_at DESC LIMIT 20
        """).fetchall()

    if pending:
        opts = {
            f"[{p['hook_type']}] {p['channel_name']} — {(p['title'] or '')[:25]}  CTR:{p['ctr_score']:.0f}점": p
            for p in pending
        }
        sel_label = st.selectbox("저장된 프롬프트 선택", list(opts.keys()))
        sel_row   = opts[sel_label]
        prompt_val    = sel_row["prompt_text"]
        analysis_id   = sel_row["analysis_id"]
        hook_type_val = sel_row["hook_type"]
        ctr_val       = sel_row["ctr_score"]
    else:
        st.info("저장된 프롬프트가 없습니다. '💡 한 끗 생성' 탭에서 먼저 프롬프트를 저장하세요.")
        prompt_val    = ""
        analysis_id   = ""
        hook_type_val = ""
        ctr_val       = 0.0

    # 프롬프트 직접 입력도 가능
    with st.expander("✏️ 프롬프트 직접 입력 또는 수정"):
        prompt_val  = st.text_area("프롬프트 (영어)", value=prompt_val, height=130)
        negative_val = st.text_input("네거티브 프롬프트 (SD용)",
                                      value="blurry, low quality, watermark, ugly, deformed")
        analysis_id  = st.text_input("analysis_id (선택)", value=analysis_id)

    # ── 엔진 + 장수 선택 ──────────────────────────────────
    col_eng, col_cnt, col_par = st.columns([3, 1, 1])
    with col_eng:
        chosen_engines = st.multiselect(
            "생성 엔진 선택",
            options=[e["id"] for e in avail],
            default=[e["id"] for e in avail],
            format_func=lambda x: ENGINES[x]["name"],
        )
    with col_cnt:
        count_per = st.number_input("엔진당 장수", 1, 4, 2)
    with col_par:
        parallel = st.toggle("동시 실행", value=True)

    if st.button("🎨 이미지 생성 시작", type="primary", use_container_width=True,
                 disabled=not (prompt_val and chosen_engines)):
        total_expected = len(chosen_engines) * count_per
        prog = st.progress(0, text=f"0 / {total_expected}장 생성 중...")

        results = []
        errors  = []

        for idx, eid in enumerate(chosen_engines):
            prog.progress((idx) / len(chosen_engines),
                          text=f"{ENGINES[eid]['name']} 생성 중...")
            try:
                partial = generate_images(
                    analysis_id   = analysis_id or "direct",
                    prompt        = prompt_val,
                    negative      = negative_val,
                    hook_type     = hook_type_val,
                    ctr_score     = ctr_val,
                    engines       = [eid],
                    count_per_engine = count_per,
                    parallel      = False,
                )
                results.extend(partial)
            except Exception as e:
                errors.append(f"{ENGINES[eid]['name']}: {e}")

        prog.progress(1.0, text="완료!")

        ok = [r for r in results if r.get("image_path")]
        st.success(f"✅ {len(ok)}장 생성 완료")
        if errors:
            for err in errors:
                st.warning(f"⚠️ {err}")
        st.session_state["last_generated"] = ok
        st.rerun()

    # ── 생성 결과 그리드 ──────────────────────────────────
    if "last_generated" in st.session_state:
        imgs = st.session_state["last_generated"]
        if imgs:
            st.markdown("---")
            st.subheader(f"🖼️ 생성 결과 — {len(imgs)}장")
            cols = st.columns(min(len(imgs), 4))
            for i, r in enumerate(imgs):
                with cols[i % 4]:
                    try:
                        st.image(r["image_path"], use_container_width=True)
                    except Exception:
                        st.caption("이미지 로드 실패")
                    eng_name = ENGINES.get(r["engine"], {}).get("name", r["engine"])
                    st.caption(f"🤖 {eng_name}")
                    st.caption(f"gen_id: {(r.get('gen_id') or '')[:10]}")


def tab_review():
    st.header("✅ 검수 · 컨펌")

    from core.store import list_generated, update_generated_status
    import pandas as pd
    from core.config import GEN_DIR

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_status = st.selectbox("상태 필터", ["pending", "approved", "rejected", "전체"])
    with col_f2:
        limit = st.slider("표시 개수", 10, 100, 30)

    status_filter = None if filter_status == "전체" else filter_status
    items = list_generated(status=status_filter)[:limit]

    if not items:
        st.info("검수할 이미지가 없습니다. '🎨 이미지 생성' 탭에서 이미지를 먼저 생성하세요.")
        return

    st.markdown(f"**{len(items)}개** 항목")
    st.markdown("---")

    # 이미지 그리드 + 버튼
    cols = st.columns(4)
    for i, item in enumerate(items):
        with cols[i % 4]:
            path = item.get("image_path")
            if path:
                try:
                    st.image(path, use_container_width=True)
                except Exception:
                    st.caption("🖼️ 이미지 없음")
            else:
                st.caption("🖼️ 이미지 없음")

            score  = item.get("ctr_score", 0)
            status = item.get("status", "pending")
            hook   = item.get("hook_type", "")
            st.caption(f"📊 CTR: {score:.0f}점  |  {hook}")

            status_color = {"approved": "🟢", "rejected": "🔴", "pending": "🟡"}.get(status, "⚪")
            st.caption(f"{status_color} {status}")

            gen_id = item["gen_id"]
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅", key=f"approve_{gen_id}", help="승인",
                             disabled=(status == "approved")):
                    update_generated_status(gen_id, "approved")
                    st.rerun()
            with col_b:
                if st.button("❌", key=f"reject_{gen_id}", help="반려",
                             disabled=(status == "rejected")):
                    update_generated_status(gen_id, "rejected")
                    st.rerun()

            # 피드백 메모
            if status == "rejected":
                feedback = st.text_input("반려 사유", key=f"fb_{gen_id}",
                                          placeholder="수정 요청 내용...")
                if feedback and st.button("저장", key=f"fbsave_{gen_id}"):
                    update_generated_status(gen_id, "rejected", feedback)
                    st.rerun()


# ─────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────

def tab_pinterest():
    st.header("🌸 Pinterest 트렌드")

    from collect.pinterest_collector import (
        collect_pinterest_trends, get_pinterest_stats,
        get_trend_images, PINTEREST_KEYWORDS,
    )
    from core.config import PINTEREST_TOKEN

    # 현황
    try:
        stats = get_pinterest_stats()
        col1, col2 = st.columns(2)
        col1.metric("수집된 핀 수", stats["total"])
        col2.metric("카테고리 수", len(stats["by_category"]))
    except Exception:
        st.info("아직 수집된 핀이 없습니다.")

    st.markdown("---")

    # 수집 설정
    st.subheader("📥 트렌드 수집")

    mode = "API" if PINTEREST_TOKEN else "스크래핑"
    st.caption(f"현재 모드: **{mode}** {'(PINTEREST_TOKEN 설정됨)' if PINTEREST_TOKEN else '(토큰 없음 — 웹 스크래핑)'}")

    all_cats = list(PINTEREST_KEYWORDS.keys())
    chosen_cats = st.multiselect("수집할 카테고리", all_cats, default=all_cats[:4])
    max_per_kw  = st.slider("키워드당 최대 핀 수", 5, 30, 10)
    dl_images   = st.checkbox("이미지 로컬 저장 (색상 분석 포함)", value=True)

    if st.button("🌸 Pinterest 수집 시작", type="primary", use_container_width=True):
        with st.spinner("Pinterest 트렌드 수집 중..."):
            try:
                n = collect_pinterest_trends(
                    categories=chosen_cats,
                    max_per_keyword=max_per_kw,
                    download=dl_images,
                )
                st.success(f"✅ {n}개 핀 수집 완료")
            except Exception as e:
                st.error(f"수집 실패: {e}")
        st.rerun()

    # 수집된 핀 미리보기
    st.markdown("---")
    st.subheader("🖼️ 수집된 트렌드 이미지")

    filter_cat = st.selectbox("카테고리 필터", ["전체"] + all_cats)
    cat_val    = None if filter_cat == "전체" else filter_cat
    pins = get_trend_images(category=cat_val, limit=40)

    if not pins:
        st.info("수집된 핀이 없습니다.")
    else:
        cols = st.columns(5)
        for i, pin in enumerate(pins):
            with cols[i % 5]:
                url = pin.get("local_path") or pin.get("image_url")
                try:
                    st.image(url, use_container_width=True)
                except Exception:
                    st.caption("🖼️")
                if pin.get("dominant_color"):
                    st.markdown(
                        f"<div style='background:{pin['dominant_color']};height:8px;border-radius:4px'></div>",
                        unsafe_allow_html=True,
                    )
                st.caption(f"{pin.get('keyword','')[:20]}")


def tab_hook_manager():
    st.header("🧠 한 끗 관리")

    from generate.custom_hooks    import list_custom_hooks, add_custom_hook, delete_custom_hook
    from generate.pattern_miner   import mine_patterns, pattern_to_hook_hint
    from generate.feedback_learner import learn_from_approved
    from core.config import CATEGORIES

    inner_tab1, inner_tab2, inner_tab3 = st.tabs([
        "✍️ 나만의 공식 등록",
        "📊 DB 패턴 인사이트",
        "🏆 피드백 학습 결과",
    ])

    # ── 커스텀 한 끗 등록 ────────────────────────────────
    with inner_tab1:
        st.subheader("등록된 나만의 공식")
        customs = list_custom_hooks()
        if customs:
            for h in customs:
                col_a, col_b = st.columns([5, 1])
                with col_a:
                    st.markdown(f"**[{h['id']}]** {h['description']}")
                    st.caption(f"적용 카테고리: {', '.join(h.get('best_for',[]))}")
                    if h.get("examples"):
                        st.caption(f"예시: {h['examples'][0]}")
                with col_b:
                    if st.button("삭제", key=f"del_{h['id']}"):
                        delete_custom_hook(h["id"])
                        st.rerun()
                st.markdown("---")
        else:
            st.info("아직 등록된 나만의 공식이 없습니다.")

        st.subheader("➕ 새 공식 등록")
        with st.form("add_hook_form"):
            h_id   = st.text_input("공식 ID (영문, 공백없이)", placeholder="my_trot_formula_1")
            h_desc = st.text_area("설명 (한 줄로)", placeholder="태극기를 배경에 넣으면 애국심 클릭 유발")
            h_cats = st.multiselect("효과 있는 카테고리", list(CATEGORIES.keys()))
            h_kws  = st.text_input("프롬프트 키워드 (콤마 구분, 영어)",
                                    placeholder="Korean flag, patriotic, emotional crowd")
            h_exs  = st.text_input("예시 (콤마 구분)", placeholder="인물 뒤 태극기, 태극기 물결")
            submitted = st.form_submit_button("등록", type="primary")
            if submitted:
                if not h_id or not h_desc:
                    st.warning("ID와 설명은 필수입니다.")
                else:
                    kws = [k.strip() for k in h_kws.split(",") if k.strip()]
                    exs = [e.strip() for e in h_exs.split(",") if e.strip()]
                    add_custom_hook(h_id, h_desc, h_cats, kws, exs)
                    st.success(f"✅ '{h_id}' 등록 완료!")
                    st.rerun()

    # ── DB 패턴 인사이트 ─────────────────────────────────
    with inner_tab2:
        st.subheader("고조회수 썸네일 공통 패턴")
        min_views = st.number_input("최소 조회수 기준", value=50000, step=10000)
        if st.button("🔍 패턴 분석", use_container_width=True):
            with st.spinner("분석 중..."):
                patterns = mine_patterns(min_view_count=int(min_views))
            if not patterns or patterns.get("sample_count", 0) == 0:
                st.warning("분석 데이터가 부족합니다. 더 많은 썸네일을 수집·분석하세요.")
            else:
                st.caption(f"분석 샘플: {patterns['sample_count']}개")

                def show_pattern(label, items):
                    if not items: return
                    st.markdown(f"**{label}**")
                    for item in items:
                        val = item.get("value") or item.get("trigger") or item.get("temp", "")
                        pct = item.get("pct", 0)
                        st.progress(pct / 100, text=f"{val} — {pct}%")

                col1, col2 = st.columns(2)
                with col1:
                    show_pattern("📐 구도", patterns.get("composition", []))
                    show_pattern("👁 시선", patterns.get("gaze", []))
                    show_pattern("😊 감정", patterns.get("emotion", []))
                with col2:
                    show_pattern("🎨 배경", patterns.get("background", []))
                    show_pattern("📌 트리거", patterns.get("triggers", []))
                    show_pattern("🌡 색온도", patterns.get("color_temp", []))

    # ── 피드백 학습 결과 ─────────────────────────────────
    with inner_tab3:
        st.subheader("승인된 썸네일에서 학습한 패턴")
        fb = learn_from_approved()

        if fb.get("sample_count", 0) == 0:
            st.info("아직 승인된 썸네일이 없습니다. '✅ 검수' 탭에서 마음에 드는 이미지를 승인하세요.")
        else:
            st.info(fb.get("insight", ""))
            st.markdown("---")

            col1, col2, col3 = st.columns(3)
            col1.metric("학습 샘플", fb["sample_count"])
            col2.metric("평균 CTR 점수", f"{fb['avg_ctr']}점")
            col3.metric("최적 한 끗", fb["top_hooks"][0]["hook"] if fb.get("top_hooks") else "-")

            if fb.get("top_hooks"):
                st.subheader("🏆 승인율 높은 한 끗 유형")
                for h in fb["top_hooks"]:
                    st.progress(h["pct"] / 100, text=f"{h['hook']} — {h['pct']}%")


def tab_operate():
    st.header("🚀 운영 · 알고리즘 전략")

    from operate.youtube_trend_watcher import get_upload_timing_advice, extract_trend_keywords
    from operate.reporter              import generate_daily_report, format_report_text
    from operate.scheduler             import TASKS

    # ── 업로드 타이밍 ─────────────────────────────────────
    timing = get_upload_timing_advice()
    col1, col2, col3 = st.columns(3)

    status_color = "🟢" if timing["is_peak"] else "🟡"
    col1.metric("현재 시각 (KST)", f"{timing['current_hour_kst']}시")
    col2.metric("피크 타임", "지금!" if timing["is_peak"] else f"{timing['next_peak_hour']}시부터")
    col3.metric("요일", "주말" if timing["is_weekend"] else "평일")

    st.info(f"{status_color} {timing['advice']}")

    st.markdown("""
    > **알고리즘 상위노출 원칙**
    > - 피크 시간 업로드 → 초반 CTR 극대화 → 알고리즘 노출 확대
    > - 썸네일 CTR **3% 이상** 유지가 목표
    > - 업로드 후 **48시간** 이 성패를 가름
    > - 같은 영상 썸네일 **A/B 테스트** → 클릭율 높은 것으로 교체
    """)

    st.markdown("---")

    # ── 트렌드 키워드 ─────────────────────────────────────
    st.subheader("🔥 지금 뜨는 키워드 (급상승 영상 기준)")
    keywords = extract_trend_keywords(limit=200)
    if keywords:
        # 워드클라우드 대신 바 형태로 표시
        cols = st.columns(2)
        for i, kw in enumerate(keywords[:14]):
            with cols[i % 2]:
                st.progress(
                    min(kw["count"] / max(keywords[0]["count"], 1), 1.0),
                    text=f"#{kw['keyword']}  ({kw['count']}회)"
                )
    else:
        st.info("급상승 영상을 먼저 수집하세요 (아래 버튼).")

    st.markdown("---")

    # ── 수동 태스크 실행 ──────────────────────────────────
    st.subheader("⚙️ 수동 실행")
    task_labels = {
        "detect":    "🔍 경쟁 채널 새 업로드 감지",
        "pinterest": "🌸 Pinterest 트렌드 수집",
        "trend":     "📈 유튜브 급상승 수집·분석",
        "pattern":   "🧠 DB 패턴 마이닝",
        "peak":      "⏰ 피크 알림 저장",
        "report":    "📄 일일 리포트 생성",
    }
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

    if st.button("🚀 전체 태스크 1회 실행 (수집→분석→패턴→리포트)",
                 type="primary", use_container_width=True):
        from operate.scheduler import run_all
        with st.spinner("전체 실행 중... (수 분 소요)"):
            run_all()
        st.success("✅ 전체 완료")
        st.rerun()

    st.markdown("---")

    # ── 일일 리포트 ───────────────────────────────────────
    st.subheader("📄 일일 리포트")
    if st.button("리포트 생성", use_container_width=True):
        with st.spinner("리포트 생성 중..."):
            report = generate_daily_report()
        st.text(format_report_text(report))

    # 최근 스케줄 로그
    from core.config import ROOT_DIR
    import json
    log_path = ROOT_DIR / "data" / "scheduler_log.jsonl"
    if log_path.exists():
        st.markdown("---")
        st.subheader("📋 최근 실행 로그")
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines[-20:]):
            try:
                entry = json.loads(line)
                icon  = "✅" if entry["status"] == "ok" else ("⏭️" if entry["status"] == "skip" else "❌")
                st.caption(f"{icon} `{entry['ts'][:16]}` [{entry['task']}] {entry['detail']}")
            except Exception:
                pass


def main():
    render_sidebar()

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
        "📡 채널 수집",
        "🖼️ 썸네일 수집",
        "🌸 Pinterest",
        "🔎 분석",
        "💡 한 끗 생성",
        "🧠 한 끗 관리",
        "🎨 이미지 생성",
        "✅ 검수",
        "🚀 운영·전략",
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
