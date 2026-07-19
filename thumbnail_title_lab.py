"""thumbnail_title_lab.py — 🎬 썸네일·제목 연구소 (장르별 채널 공장)

여러 장르 채널을 새로 개설하기 위한 도구. 장르마다 독립 프로젝트로:
  🔬 장르 분석(승리 공식) ↔ ✨ 생성(그 공식대로 제작) 두 축.
+ 🎯 일치성 점수 · 🧺 레퍼런스 바구니 · 🔔 북마크 카톡 알림.

실행: streamlit run thumbnail_title_lab.py --server.port 8505
"""
from __future__ import annotations

import os
import sys

# .env 를 환경변수로 로드 (concept_maker/youtube_client import 전에 해야 키가 잡힘)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:                       # noqa: BLE001
    pass

import streamlit as st

# concept_maker (Vision·이미지생성·수집) 재사용 — jpshorts/backend 경로 주입
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
try:
    import concept_maker as CM
except Exception:                       # noqa: BLE001
    CM = None

import tier_lab as T
import genre_store as G
import thumb_overlay as OV
import link_classifier as LC
import pattern_analyzer as PA

st.set_page_config(page_title="🎬 썸네일·제목 연구소", page_icon="🎬", layout="wide")


# ── 헬퍼 (탭보다 먼저 정의) ────────────────────────────────────
def _generate_sets(genre, content, n, formula, ref_titles):
    """장르 공식 + 레퍼런스 제목 → 제목·문구·장면 세트 N개."""
    import json
    prompt = f"""너는 유튜브 음악 플레이리스트 채널 '{genre}'의 썸네일·제목 기획자다.
소재: {content or '(자유)'}
이 장르 승리 공식: {formula or '(분석 전 — 장르 감각으로)'}
참고 제목들: {' / '.join(ref_titles) or '(없음)'}

아래 JSON만 출력. {n}개 세트. 각 세트:
- title: 제목(감각어+구체적 상황+분위기, 이 장르 톤). 이모지 1개까지.
- thumb_text: 썸네일 이미지 위에 얹을 한글 문구 1~2줄(제목과 겹치지 말고 새 감정 한마디).
- scene: 썸네일 장면 묘사(글자 없는 배경 — 장소·시간대·색·조명). 영어로.
{{"sets":[{{"title":"...","thumb_text":"...","scene":"..."}}]}}"""
    if CM is not None:
        raw = CM._llm(prompt, json_mode=True)
        if raw:
            try:
                data = json.loads(raw) if raw.strip().startswith("{") else (CM._parse_json(raw) or {})
                sets = data.get("sets") or []
                if sets:
                    return sets[:n]
            except Exception:       # noqa: BLE001
                pass
    return [{"title": f"{content or '고요한 밤'} · 그날의 감성 {'☕' if i % 2 else '🌙'}",
             "thumb_text": "오늘도 수고했어요",
             "scene": f"cozy cafe window, warm light, {content}, cinematic"}
            for i in range(n)]


def _save_keys(keys: dict):
    """빈칸은 기존 유지, 입력한 것만 .env 갱신 + 환경변수 즉시 반영."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = {}
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.partition("=")
                lines[k.strip()] = v.rstrip("\n")
    for k, v in keys.items():
        if v.strip():
            lines[k] = v.strip()
            os.environ[k] = v.strip()
    with open(path, "w", encoding="utf-8") as f:
        for k, v in lines.items():
            f.write(f"{k}={v}\n")
    # 유튜브 모듈이 시작 시 캐시한 키를 즉시 갱신 (재시작 없이 반영)
    try:
        if CM and keys.get("YOUTUBE_API_KEY", "").strip():
            CM.yc.YOUTUBE_API_KEY = keys["YOUTUBE_API_KEY"].strip()
    except Exception:                   # noqa: BLE001
        pass

# ── 페이지 네비게이션 ─────────────────────────────────────────
PAGES = ["🏠 대시보드", "🗂 자동분류", "🔬 구간 분석", "🎯 일치성", "✨ 생성",
         "🧺 레퍼런스 바구니", "🔔 감시/알림", "⚙️ 설정"]
if "_goto" in st.session_state:          # 다른 화면에서 넘어온 이동 요청(위젯 생성 전 반영)
    st.session_state["nav"] = st.session_state.pop("_goto")

# ── 사이드바: 프로젝트(장르) 선택 ─────────────────────────────
state = G.load_state()
projects = list(state["projects"].keys())

with st.sidebar:
    st.markdown("## 🎬 썸네일·제목 연구소")
    st.caption("여러 장르 채널 공장 — 분석↔생성")
    page = st.radio("메뉴", PAGES, key="nav", label_visibility="collapsed")
    st.divider()
    cur = st.selectbox("📺 채널(장르) 선택", projects,
                       index=projects.index(state["current"]) if state["current"] in projects else 0)
    if cur != state["current"]:
        G.set_current(cur); st.rerun()
    proj = state["projects"][cur]
    if proj.get("note"):
        st.caption("📝 " + proj["note"])

    with st.expander("➕ 채널(장르) 추가 / 삭제"):
        new = st.text_input("새 장르 이름", key="new_proj")
        newnote = st.text_input("메모(선택)", key="new_note")
        if st.button("추가", use_container_width=True) and new.strip():
            G.add_project(new, newnote); st.rerun()
        if len(projects) > 1:
            if st.button(f"🗑 '{cur}' 삭제", use_container_width=True):
                G.delete_project(cur); st.rerun()

    st.divider()
    # 키 상태
    if CM:
        s = CM.llm_status()
        yt = bool(os.environ.get("YOUTUBE_API_KEY", "").strip())
        st.caption("🔑 " + " · ".join([
            ("🟢" if yt else "⚪") + "YouTube",
            ("🟢" if s.get("openai") else "⚪") + "GPT",
            ("🟢" if s.get("gemini") else "⚪") + "Gemini"]))
        if not yt:
            st.caption("↳ 키 없으면 데모 데이터로 시연됩니다.")
    st.caption("발행 6개월 이내 · 구간 1천~30만+")


# (탭 → 사이드바 메뉴 전환: page 값으로 각 화면 표시)

# ═══════════════════════════════════════════════════════════════
# 🏠 대시보드
# ═══════════════════════════════════════════════════════════════
if page == "🏠 대시보드":
    st.subheader("🏠 채널(장르) 대시보드")
    st.caption("장르마다 독립 채널 프로젝트. 새 장르 진입엔 **분석이 곧 설계도**입니다.")
    cols = st.columns(3)
    for i, (name, p) in enumerate(state["projects"].items()):
        with cols[i % 3]:
            bm = sum(1 for b in p["benchmarks"] if b.get("bookmark"))
            al = sum(1 for b in p["benchmarks"] if b.get("alarm"))
            box = st.container(border=True, height=250)   # 고정 높이 → 열 맞춤
            box.markdown(f"### {'⭐ ' if name == cur else ''}{name}")
            box.caption((p.get("note") or "")[:70])
            box.write(f"벤치 {len(p['benchmarks'])}개 · 🔖{bm} · 🔔{al} · 🧺{len(p['basket'])}")
            if box.button("🔬 선택 → 구간분석 보기", key=f"pick_{i}", use_container_width=True):
                G.set_current(name)
                st.session_state["_goto"] = "🔬 구간 분석"   # 바로 분석 화면으로 이동
                st.rerun()

# ═══════════════════════════════════════════════════════════════
# 🗂 자동분류
# ═══════════════════════════════════════════════════════════════
if page == "🗂 자동분류":
    st.subheader("🗂 미분류 대량 링크 자동분류")
    st.caption("링크 뭉치 붙여넣기 → 유튜브에서 제목 읽어 장르통으로 자동 정렬 → "
               "**드롭다운으로 직접 옮긴 뒤** 각 장르에 추가.")
    cls_txt = st.text_area("링크 붙여넣기 (여러 줄, 섞여 있어도 OK)", height=130, key="cls_input",
                           placeholder="https://youtu.be/xxxx\nhttps://youtu.be/yyyy ...")
    use_llm = st.checkbox("🤖 GPT 정밀분류", value=True, help="OpenAI/Gemini 키 있을 때 더 정확. 없으면 키워드 분류.")
    cc1, cc2, cc3 = st.columns(3)
    run_paste = cc1.button("🔎 붙여넣기 분류", type="primary")
    run_inv = cc2.button("📥 인벤토리 링크 분류")
    _uns_cnt = len(state["projects"].get(LC.UNSORTED, {}).get("benchmarks", []))
    run_uns = cc3.button(f"📂 미분류함 다시 분류 ({_uns_cnt})", disabled=_uns_cnt == 0)

    urls = None
    if run_paste:
        urls = LC.split_links(cls_txt)
    elif run_inv:
        urls = LC.load_inventory_urls()
        if urls:
            st.info(f"인벤토리에서 영상 링크 {len(urls)}개 불러옴.")
    elif run_uns:
        urls = [b["url"] for b in state["projects"].get(LC.UNSORTED, {}).get("benchmarks", [])]
        if urls:
            st.info(f"미분류함 {len(urls)}개 다시 분류합니다.")
    if urls is not None:
        if not urls:
            st.warning("링크를 찾지 못했어요. (붙여넣기 또는 인벤토리 확인)")
        else:
            with st.spinner(f"{len(urls)}개 수집·분류 중… (유튜브 제목 읽는 중)"):
                st.session_state["cls_res"] = LC.classify(urls, state["projects"], use_llm=use_llm)

    res = st.session_state.get("cls_res")
    if res:
        import collections
        names = list(state["projects"].keys()) + [LC.UNSORTED]
        n_sorted = sum(1 for m in res if m.get("genre") != LC.UNSORTED)
        st.success(f"분류 결과 {len(res)}개 · 장르 배정 {n_sorted}개 · 미분류 {len(res)-n_sorted}개")
        if not any(m.get("title") for m in res):
            st.warning("⚠️ 제목을 못 읽었어요. YouTube 키가 없거나(설정 탭) 링크가 비공개일 수 있어요.")
        # 장르별 배정 개수 미리보기
        cnt = collections.Counter(m["genre"] for m in res)
        st.caption("📦 배정 미리보기 — " + " · ".join(f"{g} {c}" for g, c in cnt.most_common()))

        CONFIRM = "✅ 확정 — 분류는 각 장르로, 미분류는 미분류함에 저장"
        do_confirm = st.button(CONFIRM, type="primary", key="confirm_top")
        st.caption("↑ 위 버튼으로 바로 확정하거나, 아래에서 드롭다운으로 장르를 고친 뒤 확정하세요.")

        # 장르별로 묶어 표시(같은 장르끼리 모임)
        order = {g: i for i, g in enumerate(names)}
        for idx, m in enumerate(sorted(range(len(res)), key=lambda k: order.get(res[k]["genre"], 99))):
            mm = res[m]
            col = st.columns([1, 4, 3])
            if mm.get("thumb"):
                col[0].image(mm["thumb"], use_container_width=True)
            tag = ("🇯🇵 " if mm.get("jp") else "") + ("🤖" if mm.get("by") == "gpt" else "🔤")
            col[1].caption(f"{tag} " + (mm.get("title") or mm["url"])[:70])
            sel = col[2].selectbox("장르", names,
                                   index=names.index(mm["genre"]) if mm["genre"] in names else len(names) - 1,
                                   key=f"cls_sel_{m}", label_visibility="collapsed")
            res[m]["genre"] = sel
        if st.button(CONFIRM, type="primary", key="confirm_bottom"):
            do_confirm = True

        if do_confirm:
            # 미분류함 · 일본채널함이 없으면 생성 (현재 선택 장르는 그대로)
            stt = G.load_state()
            if LC.UNSORTED not in stt["projects"]:
                stt["projects"][LC.UNSORTED] = {
                    "note": "자동분류가 장르를 못 정한 링크 모음 — 나중에 재분류.",
                    "benchmarks": [], "basket": [], "identity": {}}
            if any(m.get("jp") for m in res) and LC.JP_BUCKET not in stt["projects"]:
                stt["projects"][LC.JP_BUCKET] = {
                    "note": "일본어(가나) 채널 모음 — 장르와 별개로 언어 기준. 장르통에도 함께 들어감.",
                    "benchmarks": [], "basket": [], "identity": {}}
            G.save_state(stt)
            added = un = jp = 0
            for mm in res:
                g = mm["genre"]
                if g in state["projects"] and g != LC.UNSORTED:
                    G.add_benchmarks(g, [mm["url"]]); added += 1
                    G.remove_benchmark(LC.UNSORTED, mm["url"])   # 미분류함에서 이동
                else:
                    G.add_benchmarks(LC.UNSORTED, [mm["url"]]); un += 1
                if mm.get("jp"):                                  # 일본어면 일본채널함에도
                    G.add_benchmarks(LC.JP_BUCKET, [mm["url"]]); jp += 1
            st.session_state.pop("cls_res", None)
            st.success(f"장르 배정 {added} · 미분류함 {un} · 🇯🇵 일본채널 {jp} 저장 완료! "
                       "일본 채널은 장르통과 🇯🇵일본채널함 양쪽에 들어갔어요.")
            st.rerun()

# ═══════════════════════════════════════════════════════════════
# 🔬 구간 분석
# ═══════════════════════════════════════════════════════════════
if page == "🔬 구간 분석":
    st.subheader(f"🔬 구간 분석 — {cur}")
    st.caption("벤치마킹 채널의 6개월 이내 영상 → 구간별(1천~30만+) 승리 공식.")

    with st.expander("➕ 벤치마킹 링크 추가 (채널/영상 URL, 여러 줄)"):
        txt = st.text_area("링크 붙여넣기", height=100, key="bm_add",
                           placeholder="https://www.youtube.com/@channel\nhttps://youtu.be/xxxx")
        if st.button("추가하기") and txt.strip():
            G.add_benchmarks(cur, txt); st.rerun()

    st.write(f"**등록된 벤치마킹: {len(proj['benchmarks'])}개**")
    if not proj["benchmarks"]:
        st.info("위에서 이 장르의 벤치마킹 채널/영상 링크를 넣어주세요.")
    else:
        with st.expander("🔖 북마크 · 🔔 알림 관리", expanded=False):
            for b in proj["benchmarks"]:
                c1, c2, c3, c4 = st.columns([6, 1, 1, 1])
                c1.write(b["url"])
                if c2.checkbox("🔖", value=b.get("bookmark"), key="bk_" + b["url"]) != b.get("bookmark"):
                    G.toggle_flag(cur, b["url"], "bookmark"); st.rerun()
                if c3.checkbox("🔔", value=b.get("alarm"), key="al_" + b["url"]) != b.get("alarm"):
                    G.toggle_flag(cur, b["url"], "alarm"); st.rerun()
                if c4.button("🗑", key="rm_" + b["url"]):
                    G.remove_benchmark(cur, b["url"]); st.rerun()

        if st.button("📊 분석 실행 (수집 → 구간별 공식)", type="primary"):
            if CM is None:
                st.error("concept_maker 로드 실패 — jpshorts/backend 확인.")
            else:
                allvids = []
                prog = st.progress(0.0, "수집 중…")
                chans = [b["url"] for b in proj["benchmarks"]]
                for i, url in enumerate(chans):
                    data = CM.collect_channel(url)
                    for v in data.get("videos", []):
                        allvids.append({**v, "source": data.get("title", url), "bench_url": url})
                    prog.progress((i + 1) / len(chans), f"수집 {i+1}/{len(chans)}")
                prog.empty()
                st.session_state["report_" + cur] = T.tier_report(allvids)
                if any(CM.collect_channel(u).get("demo") for u in chans[:1]):
                    st.warning("⚠️ YouTube 키가 없어 데모 데이터로 시연 중입니다. (사장님 PC에선 실데이터)")

        rep = st.session_state.get("report_" + cur)
        if rep:
            top = st.columns([3, 2])
            top[0].success(f"6개월 이내 {rep['total']}개 분석 (오래된 영상 {rep['dropped_old']}개 제외)")
            sort_key = top[1].radio("정렬", ["조회수순", "📅 날짜순"], horizontal=True,
                                    key="sort_" + cur, label_visibility="collapsed")
            bench_by_url = {b["url"]: b for b in proj["benchmarks"]}
            for label in T.TIER_ORDER:
                info = rep["tiers"][label]
                if not info["count"]:
                    continue
                low = " 🌱" if info["is_low"] else ""
                st.markdown(f"#### {label}{low} — {info['count']}개")
                st.caption("승리 공식: " + info["formula"])
                if sort_key == "📅 날짜순":
                    vids = sorted(info["videos"], key=lambda v: v.get("published", ""), reverse=True)
                else:
                    vids = sorted(info["videos"], key=lambda v: v.get("views", 0), reverse=True)
                grid = st.columns(4)
                for j, v in enumerate(vids):        # 구간 내 전체 표시
                    with grid[j % 4]:
                        card = st.container(border=True, height=360)  # 고정 높이 → 열 맞춤
                        vid = v.get("video_id", "")
                        link = f"https://youtu.be/{vid}" if vid else ""
                        if v.get("thumb"):
                            if link:   # 썸네일 클릭 → 유튜브 새 탭
                                card.markdown(
                                    f'<a href="{link}" target="_blank" title="유튜브에서 보기">'
                                    f'<img src="{v["thumb"]}" style="width:100%;border-radius:8px"></a>',
                                    unsafe_allow_html=True)
                            else:
                                card.image(v["thumb"], use_container_width=True)
                        # 카드에서 바로 🔖북마크 · 🔔알림 · 🧺바구니
                        burl = v.get("bench_url", "")
                        b = bench_by_url.get(burl)
                        a1, a2, a3 = card.columns(3)
                        if b is not None:
                            if a1.checkbox("🔖", value=b.get("bookmark"), key=f"bk_{label}_{j}",
                                           help="채널 북마크") != b.get("bookmark"):
                                G.toggle_flag(cur, burl, "bookmark"); st.rerun()
                            if a2.checkbox("🔔", value=b.get("alarm"), key=f"al_{label}_{j}",
                                           help="새 영상 카톡 알림") != b.get("alarm"):
                                G.toggle_flag(cur, burl, "alarm"); st.rerun()
                        if a3.button("🧺", key=f"bsk_{label}_{j}", help="레퍼런스 바구니에 담기"):
                            G.add_to_basket(cur, v.get("thumb", ""), v.get("title", ""),
                                            v.get("source", "")); st.toast("바구니에 담음")
                        card.caption(f"👁 {int(v.get('views',0)):,} · 📅 {v.get('published','')}")
                        card.caption(f"📺 {(v.get('source','') or '')[:22]}")
                        card.caption((v.get("title", "") or "")[:38])

# ═══════════════════════════════════════════════════════════════
# 🎯 일치성 검사
# ═══════════════════════════════════════════════════════════════
if page == "🎯 일치성":
    st.subheader("🎯 일치성 + 패턴 분석 → 자동 프롬프트")
    st.caption("링크 여러 개 → GPT가 실제 썸네일 보고 제목 읽어 → 일치성 채점 + 썸네일·제목 패턴 → 재사용 프롬프트.")

    src = st.radio("분석 대상", ["📺 현재 장르 벤치마크", "🔗 링크 직접 입력"],
                   horizontal=True, key="pa_src")
    pa_urls = []
    if src == "📺 현재 장르 벤치마크":
        pa_urls = [b["url"] for b in proj["benchmarks"]]
        st.caption(f"'{cur}' 벤치마크 {len(pa_urls)}개. 💡 구간분석을 먼저 돌리면 **실제 영상 썸네일**로 분석돼요(로고 아님).")
    else:
        _t = st.text_area("영상 링크 (여러 줄)", height=110, key="pa_links",
                          placeholder="https://youtu.be/xxxx\nhttps://youtu.be/yyyy")
        pa_urls = LC.split_links(_t)
    n_limit = st.slider("Vision 분석 개수(비용·속도)", 3, 9, 6)

    if st.button("🔍 패턴 분석 실행", type="primary"):
        with st.spinner("수집 + GPT Vision 분석 중… (실제 썸네일)"):
            rep = st.session_state.get("report_" + cur)
            if src == "📺 현재 장르 벤치마크" and rep:
                allv = []
                for label in T.TIER_ORDER:
                    allv += rep["tiers"][label]["videos"]
                allv = sorted(allv, key=lambda v: v.get("views", 0), reverse=True)[:n_limit]
                if allv:
                    st.session_state["pa_res"] = PA.analyze_videos(allv, cur)
                else:
                    st.warning("수집된 영상이 없어요. 🔬 구간분석에서 [분석 실행]을 먼저.")
            elif pa_urls:
                st.session_state["pa_res"] = PA.analyze(pa_urls[:n_limit], cur)
            else:
                st.warning("분석할 링크가 없어요.")

    res = st.session_state.get("pa_res")
    if res:
        st.caption(f"엔진: {res['engine']} · {res['n']}개 분석")
        cons = res.get("consistency", {})
        score = int(cons.get("avg_score", 0) or 0)
        color = "🟢" if score >= 75 else ("🟠" if score >= 55 else "🔴")
        st.markdown(f"### {color} 일치성 {score} / 100")
        if cons.get("note"):
            st.write(cons["note"])

        pv = {p.get("i"): p for p in res.get("per_video", [])}
        metas = res.get("metas", [])
        if metas:
            cols = st.columns(min(len(metas), n_limit) if metas else 1)
            for i, m in enumerate(metas[:n_limit]):
                with cols[i % len(cols)]:
                    if m.get("thumb"):
                        st.image(m["thumb"], use_container_width=True)
                    p = pv.get(i + 1, {})
                    if p:
                        st.caption(f"일치 {p.get('score','-')} · {p.get('note','')[:30]}")
                    st.caption((m.get("title", "") or "")[:32])

        tp = res.get("thumbnail_pattern", {})
        st.markdown("#### 🖼 썸네일 패턴")
        st.write(f"- **구도**: {tp.get('composition','')} / **각도**: {tp.get('angle','')}")
        st.write(f"- **인물·오브젝트**: {tp.get('subject','')}")
        st.write(f"- **색상**: {'  '.join(tp.get('colors',[]))}  · **무드**: {tp.get('mood','')}")
        st.write(f"- **문구 스타일**: {tp.get('text_overlay','')} · **배경**: {tp.get('background','')}")

        tt = res.get("title_pattern", {})
        st.markdown("#### ✍️ 제목 패턴")
        st.write(f"- **고정문구**: {', '.join(tt.get('fixed_phrases',[])) or '-'} · **이모지**: {tt.get('emoji','')}")
        st.write(f"- **상황**: {tt.get('situation','')} · **감각어**: {', '.join(tt.get('sensory',[]))}")
        st.write(f"- **구조/톤**: {tt.get('structure','')} / {tt.get('tone','')}")

        gp = res.get("generation_prompt", {})
        st.markdown("#### ✨ 자동 생성 프롬프트 (복붙 가능)")
        st.caption("🖼 썸네일 이미지 프롬프트")
        st.code(gp.get("thumbnail_prompt", ""), language=None)
        st.caption("✍️ 제목 공식")
        st.code(gp.get("title_template", ""), language=None)
        if gp.get("example_titles"):
            st.caption("예시 제목")
            st.code("\n".join(gp["example_titles"]), language=None)

        if st.button(f"💾 이 프롬프트를 '{cur}' 장르 공식으로 저장", type="primary"):
            G.set_identity(cur, {"thumbnail_pattern": tp, "title_pattern": tt,
                                 "generation_prompt": gp})
            st.success("저장 완료! ✨ 생성 탭에서 이 공식이 자동 적용됩니다.")

    with st.expander("✍️ 수동 채점 (제목·문구 직접 입력)"):
        title = st.text_input("제목", placeholder="비 오는 새벽, 창가에서 듣는 재즈 ☔", key="man_title")
        thumb_text = st.text_input("썸네일 문구", placeholder="눈물이 나요", key="man_thumb")
        tags = st.text_input("썸네일 태그(쉼표)", placeholder="새벽, 재즈, 창가", key="man_tags")
        if st.button("일치성 채점") and title.strip():
            r = T.consistency_heuristic(title, thumb_text, [t.strip() for t in tags.split(",") if t.strip()])
            c = st.columns(4)
            c[0].metric("감정", r["emotion"]); c[1].metric("주제", r["topic"])
            c[2].metric("상보", r["complement"]); c[3].metric("타깃", r["target"])
            st.markdown(f"**합계 {r['total']}/100**")
            for nn in r["notes"]:
                st.write("• " + nn)

# ═══════════════════════════════════════════════════════════════
# ✨ 생성
# ═══════════════════════════════════════════════════════════════
if page == "✨ 생성":
    st.subheader(f"✨ 생성 — {cur}")
    st.caption("장르 공식 + 🧺 바구니 무드 + 내 콘텐츠 → 썸네일·제목 세트. 씬은 이미지, 글자는 코드로.")
    content = st.text_input("이번 영상 소재", placeholder="파리 카페의 비 오는 아침, 스텔라장 스타일 피아노")
    n = st.slider("만들 세트 수", 1, 5, 3)
    basket = G.get_basket(cur)
    refs = [b["thumb"] for b in basket if b.get("thumb")]
    st.caption(f"🧺 바구니 레퍼런스 {len(refs)}장 무드 반영 예정")
    ident = G.get_identity(cur) or {}
    igp = ident.get("generation_prompt", {})
    if igp.get("title_template") or igp.get("thumbnail_prompt"):
        st.info("💡 일치성 탭에서 저장한 **장르 공식**이 적용됩니다 (썸네일 프롬프트 + 제목 공식).")

    if st.button("✨ 제목·썸네일 세트 생성", type="primary"):
        formula = ""
        if igp.get("title_template"):          # 저장된 장르 공식 우선
            formula = "[저장된 장르 공식] " + igp["title_template"]
        if not formula:
            rep = st.session_state.get("report_" + cur)
            if rep:
                for label in ("10만+", "5만+", "3만+", "1만+", "5천+"):
                    if rep["tiers"][label]["count"]:
                        formula = f"[{label} 공식] " + rep["tiers"][label]["formula"]; break
        ref_titles = (igp.get("example_titles", []) +
                      [b["title"] for b in basket if b.get("title")])[:6]
        sets = _generate_sets(cur, content, n, formula, ref_titles)
        st.session_state["gen_" + cur] = sets

    for i, s in enumerate(st.session_state.get("gen_" + cur, [])):
        box = st.container(border=True)
        box.markdown(f"**세트 {i+1}**")
        box.code(s["title"], language=None)
        box.caption("🖼 썸네일 문구: " + s.get("thumb_text", ""))
        box.caption("🎬 장면: " + s.get("scene", ""))
        if CM and box.button("🎨 썸네일 그리기(최고화질)", key=f"draw_{i}"):
            with st.spinner("생성 중… (씬 이미지 → 글자 얹기)"):
                scene = s.get("scene", content)
                if igp.get("thumbnail_prompt"):    # 저장된 장르 이미지 패턴 반영
                    scene = igp["thumbnail_prompt"] + " — " + scene
                out = CM.generate_thumbnail_image(scene, size="1536x1024", refs=refs[:6])
                if out.get("data_url"):
                    final = OV.overlay_title(out["data_url"], s.get("thumb_text", ""))
                    box.image(final, use_container_width=True)
                    box.caption("✅ 씬 이미지 + 코드로 얹은 또렷한 문구")
                else:
                    box.error(out.get("error", "생성 실패 — OpenAI 키 필요(설정)."))

# ═══════════════════════════════════════════════════════════════
# 🧺 레퍼런스 바구니
# ═══════════════════════════════════════════════════════════════
if page == "🧺 레퍼런스 바구니":
    st.subheader(f"🧺 레퍼런스 바구니 — {cur}")
    st.caption("체크해 담은 썸네일(이미지+제목). 생성 시 무드·제목 공식으로 자동 반영.")
    up = st.file_uploader("내 캡처 이미지 추가(바구니에 합류)", type=["png", "jpg", "jpeg", "webp"],
                          accept_multiple_files=True)
    if up:
        import base64
        for f in up:
            b64 = base64.b64encode(f.read()).decode()
            G.add_to_basket(cur, f"data:image/png;base64,{b64}", "", "내 캡처")
        st.toast(f"{len(up)}장 담음"); st.rerun()
    basket = G.get_basket(cur)
    if not basket:
        st.info("아직 비었습니다. 구간 분석에서 🧺 버튼으로 담거나, 위에서 캡처를 올리세요.")
    grid = st.columns(4)
    for i, b in enumerate(basket):
        with grid[i % 4]:
            if b.get("thumb"):
                st.image(b["thumb"], use_container_width=True)
            if b.get("title"):
                st.caption(b["title"][:40])
            st.caption("출처: " + (b.get("source", "") or "-"))
            if st.button("🗑 빼기", key=f"unbsk_{i}"):
                G.remove_from_basket(cur, i); st.rerun()

# ═══════════════════════════════════════════════════════════════
# 🔔 감시/알림
# ═══════════════════════════════════════════════════════════════
if page == "🔔 감시/알림":
    st.subheader("🔔 감시 / 카톡 알림")
    st.caption("🔖 북마크 + 🔔 알림 ON 채널만 새 영상 감지 → 자동 분석 → 카톡(나에게 보내기).")
    wl = G.watch_list()
    if not wl:
        st.info("구간 분석 탭에서 채널에 🔔 알림을 켜면 여기에 표시됩니다.")
    else:
        st.write(f"**알림 대상 {len(wl)}개 채널**")
        for w in wl:
            st.write(f"- [{w['project']}] {w['url']}")
        if st.button("📤 알림목록 내보내기 (GitHub Actions용 커밋 파일)"):
            n = G.export_watch_channels()
            st.success(f"watch_channels.json 저장 ({n}개). git commit·push 하면 클라우드 감시가 이 목록을 씁니다.")
    st.divider()
    st.markdown("**카톡 설정** — GitHub Secrets 또는 설정 탭에 `KAKAO_REST_API_KEY`·`KAKAO_REFRESH_TOKEN` 저장 시 "
                "GitHub Actions cron 이 2~4시간마다 감지·발송합니다. (PC 꺼져도 작동)")
    st.caption("최초 1회 토큰 발급: `python get_kakao_token.py` 로 브라우저 로그인.")

# ═══════════════════════════════════════════════════════════════
# ⚙️ 설정
# ═══════════════════════════════════════════════════════════════
if page == "⚙️ 설정":
    st.subheader("⚙️ 설정 — 연결 키")
    st.caption("이 PC의 .env 에 저장됩니다. .env 는 gitignore — 절대 업로드 안 됨.")
    yk = st.text_input("YOUTUBE_API_KEY", type="password")
    ok = st.text_input("OPENAI_API_KEY (GPT·이미지생성)", type="password")
    gk = st.text_input("GEMINI_API_KEY (선택)", type="password")
    if st.button("💾 저장"):
        _save_keys({"YOUTUBE_API_KEY": yk, "OPENAI_API_KEY": ok, "GEMINI_API_KEY": gk})
        st.success("저장 완료 — 즉시 적용. (일부는 앱 재시작 후 반영)")
