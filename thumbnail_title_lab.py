"""thumbnail_title_lab.py — 🎬 썸네일·제목 연구소 (장르별 채널 공장)

여러 장르 채널을 새로 개설하기 위한 도구. 장르마다 독립 프로젝트로:
  🔬 장르 분석(승리 공식) ↔ ✨ 생성(그 공식대로 제작) 두 축.
+ 🎯 일치성 점수 · 🧺 레퍼런스 바구니 · 🔔 북마크 카톡 알림.

실행: streamlit run thumbnail_title_lab.py --server.port 8505
"""
from __future__ import annotations

import os
import sys

# .env + keys.json 를 환경변수로 로드 (concept_maker/youtube_client import 전에)
_HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_JSON = os.path.join(_HERE, "keys.json")
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_HERE, ".env"))
except Exception:                       # noqa: BLE001
    pass
try:                                    # keys.json 이 최우선(다른 툴이 .env 건드려도 안 풀림)
    import json as _json
    if os.path.exists(KEYS_JSON):
        for _k, _v in _json.load(open(KEYS_JSON, encoding="utf-8")).items():
            if _v:
                os.environ[_k] = _v
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
import analysis_cache as AC
import ctr_scorer as CS
import thumb_scorer as TS
import channel_watcher as W
import trend_radar as TR
import chat_editor as CE
import localize as LZ

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
    # keys.json 에도 저장 (영구·견고 — .env 가 지워져도 여기서 복원)
    try:
        import json
        cur = {}
        if os.path.exists(KEYS_JSON):
            cur = json.load(open(KEYS_JSON, encoding="utf-8"))
        for k, v in keys.items():
            if v.strip():
                cur[k] = v.strip()
        json.dump(cur, open(KEYS_JSON, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:                   # noqa: BLE001
        pass
    # 유튜브 모듈이 시작 시 캐시한 키를 즉시 갱신 (재시작 없이 반영)
    try:
        if CM and keys.get("YOUTUBE_API_KEY", "").strip():
            CM.yc.YOUTUBE_API_KEY = keys["YOUTUBE_API_KEY"].strip()
    except Exception:                   # noqa: BLE001
        pass


def _dataurl_bytes(durl: str) -> bytes:
    """data:image URL → 다운로드용 bytes."""
    import base64
    if isinstance(durl, str) and durl.startswith("data:"):
        return base64.b64decode(durl.split(",", 1)[1])
    return b""


def _mj_prompt(scene: str) -> str:
    """씬 → 미드저니 프롬프트."""
    if CM is not None:
        try:
            return CM._midjourney(scene)
        except Exception:               # noqa: BLE001
            pass
    return (scene or "").split(" --")[0].strip() + " --ar 16:9 --style raw --v 6"


def _ss_set(key: str, value) -> None:
    """세션 + 디스크 캐시에 동시 저장(새로고침해도 복원)."""
    st.session_state[key] = value
    AC.set(key, value)


def _ss_del(key: str) -> None:
    st.session_state.pop(key, None)
    AC.delete(key)

# ── 페이지 네비게이션 ─────────────────────────────────────────
PAGES = ["🏠 대시보드", "🗂 자동분류", "🔬 구간 분석", "🎯 일치성", "✨ 생성",
         "🤖 AI 편집", "🌊 트렌드 레이더", "🧺 레퍼런스 바구니", "🔔 감시/알림", "⚙️ 설정"]
if "_goto" in st.session_state:          # 다른 화면에서 넘어온 이동 요청(위젯 생성 전 반영)
    st.session_state["nav"] = st.session_state.pop("_goto")

# 디스크 캐시 → 세션 복원 (새로고침해도 분석/생성 결과 유지)
if "_hydrated" not in st.session_state:
    for _k, _v in AC.load_all().items():
        st.session_state.setdefault(_k, _v)
    st.session_state["_hydrated"] = True

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
                _ss_set("cls_res", LC.classify(urls, state["projects"], use_llm=use_llm))

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
            _ss_del("cls_res")
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
        with st.expander("🔖 북마크 · 🔔 알림 관리 · 🔗 채널정보", expanded=False):
            if st.button("🔗 채널 정보 채우기 (영상링크 → 채널명 파악)"):
                filled = 0
                with st.spinner("채널 정보 파악 중…"):
                    for b in proj["benchmarks"]:
                        if not b.get("channel"):
                            cid, cname = W.resolve_channel_info(b["url"])
                            if cid or cname:
                                G.set_benchmark_channel(cur, b["url"], cid, cname); filled += 1
                st.success(f"{filled}개 채널 정보 채움"); st.rerun()
            for b in proj["benchmarks"]:
                c1, c2, c3, c4 = st.columns([6, 1, 1, 1])
                c1.write((f"📺 **{b['channel']}** · " if b.get("channel") else "") + b["url"])
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
                _ss_set("report_" + cur, T.tier_report(allvids))
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
                        # 카드에서 바로 🔖북마크 · 🔔알림 · 🧺바구니 · ⭐집중
                        burl = v.get("bench_url", "")
                        b = bench_by_url.get(burl)
                        a1, a2, a3, a4 = card.columns(4)
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
                        if a4.button("⭐", key=f"fc_{label}_{j}", help="집중 벤치마킹에 추가 + 알림 ON",
                                     disabled=(not burl or cur == G.FOCUS_BUCKET)):
                            G.add_benchmarks(G.FOCUS_BUCKET, [burl])
                            G.toggle_flag(G.FOCUS_BUCKET, burl, "alarm", True)
                            st.toast("⭐ 집중 벤치마킹에 추가 + 🔔알림 ON")
                        card.caption(f"👁 {int(v.get('views',0)):,} · 📅 {v.get('published','')}")
                        card.caption(f"📺 {(v.get('source','') or '')[:22]}")
                        card.caption((v.get("title", "") or "")[:38])

# ═══════════════════════════════════════════════════════════════
# 🎯 일치성 검사
# ═══════════════════════════════════════════════════════════════
if page == "🎯 일치성":
    st.subheader("🎯 일치성 + 패턴 분석 → 자동 프롬프트")
    st.caption("링크 여러 개 → GPT가 실제 썸네일 보고 제목 읽어 → 일치성 채점 + 썸네일·제목 패턴 → 재사용 프롬프트.")

    with st.expander("🎨 채널 전체 '결' 분석 (로고·배너·태그·설명·썸네일 통합)", expanded=False):
        ch_url = st.text_input("유튜브 채널 URL", key="brand_url",
                               placeholder="https://www.youtube.com/@channel")
        if st.button("🎨 채널 결 분석") and ch_url.strip():
            with st.spinner("채널 브랜드(로고·배너·태그·설명·썸네일) 수집 + GPT Vision…"):
                _ss_set("brand_" + cur, PA.channel_brand(ch_url, cur))
        bd = st.session_state.get("brand_" + cur)
        if bd:
            if bd.get("error"):
                st.warning(bd["error"])
            else:
                st.markdown(f"**{bd['title']}** · 구독자 {bd.get('subscribers',0):,}")
                bc = st.columns(2)
                if bd.get("logo"):
                    bc[0].caption("로고"); bc[0].image(bd["logo"], width=120)
                if bd.get("banner"):
                    bc[1].caption("배너"); bc[1].image(bd["banner"], use_container_width=True)
                if bd.get("thumbs"):
                    st.caption("최근 썸네일")
                    tcols = st.columns(min(6, len(bd["thumbs"])))
                    for _i, _t in enumerate(bd["thumbs"][:6]):
                        tcols[_i].image(_t, use_container_width=True)
                st.caption("📝 설명글: " + (bd.get("description", "") or "")[:200])
                st.caption("🏷 채널 키워드: " + (bd.get("keywords", "") or "-"))
                vz = bd.get("vision") or {}
                if vz:
                    st.markdown("**🎨 채널 '결' (Vision 종합)**")
                    st.write(f"- 팔레트: {'  '.join(vz.get('palette',[]))} · 무드: {vz.get('mood','')}")
                    st.write(f"- 비주얼: {vz.get('visual_style','')} · 톤: {vz.get('tone','')}")
                    st.write(f"- 로고: {vz.get('logo_style','')} · 배너: {vz.get('banner_style','')}")
                    st.write(f"- 썸네일 일관성: {vz.get('thumbnail_consistency','')}")
                    st.info("🧬 " + vz.get("signature_summary", ""))
                    if st.button("💾 이 결을 참고해 우리 시그니처로 저장"):
                        G.set_signature(cur, vz.get("signature_summary", ""))
                        st.success("우리 시그니처로 저장! ✨ 생성에 반영됩니다."); st.rerun()

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
                    _ss_set("pa_" + cur, PA.analyze_videos(allv, cur))
                else:
                    st.warning("수집된 영상이 없어요. 🔬 구간분석에서 [분석 실행]을 먼저.")
            elif pa_urls:
                _ss_set("pa_" + cur, PA.analyze(pa_urls[:n_limit], cur))
            else:
                st.warning("분석할 링크가 없어요.")

    res = st.session_state.get("pa_" + cur)
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

        ts = res.get("title_stats", {})
        if ts.get("top_tokens"):
            st.markdown("#### 🔑 키워드 트렌드 (분석 영상 누적)")
            st.write("· ".join(f"**{w}**({c})" for w, c in ts["top_tokens"][:12]))
            st.caption(f"평균 제목길이 {ts.get('avg_length','-')}자 · 감각어 {ts.get('sensory_pct',0)}% · "
                       f"상황어 {ts.get('situation_pct',0)}% · 이모지 {ts.get('emoji_pct',0)}%. "
                       "링크를 더 모아 다시 분석하면 이 키워드·패턴이 갱신됩니다.")

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
    gc1, gc2, gc3 = st.columns(3)
    n = gc1.slider("만들 세트 수", 1, 5, 3)
    thumb_style = gc2.selectbox("🎨 썸네일 공격 스타일", list(TS.STYLES),
                                help="폰에서 스크롤 멈추는 한 방. 강대비/병맛/감성/미니멀 중 선택")
    _tgt_names = {LZ.REGION_NAME[k]: k for k in LZ.REGION_NAME}
    gen_target = _tgt_names[gc3.selectbox("🌐 타깃 언어(현지 정서)", list(_tgt_names),
                                          help="그 나라 현지인이 실제 검색·사용하는 말투로 '번안'. 직역 아님")]
    st.caption("💡 폰 기준 — 핵심 포인트 하나 + 강한 대비. 🌐 타깃 언어면 현지 정서로 번안(제목+한국어 병기).")
    basket = G.get_basket(cur)
    refs = [b["thumb"] for b in basket if b.get("thumb")]
    st.caption(f"🧺 바구니 레퍼런스 {len(refs)}장 무드 반영 예정")
    ident = G.get_identity(cur) or {}
    igp = ident.get("generation_prompt", {})
    if igp.get("title_template") or igp.get("thumbnail_prompt"):
        st.info("💡 일치성 탭에서 저장한 **장르 공식(원리)** 이 적용됩니다. + 아래 우리 시그니처로 원본화.")

    with st.expander("🎨 우리 채널 시그니처 (우리만의 '결' — 복제 아닌 원본 만들기)", expanded=False):
        st.caption("벤치마크에선 '원리'만 배우고, 여기 우리 고유 스타일을 입혀 복제가 아닌 원본으로.")
        _sigv = ident.get("signature", "")
        new_sig = st.text_area("색 · 아트스타일 · 모티프 · 톤 · 차별점", value=_sigv, key="sig_" + cur,
                               placeholder="예: 파스텔 수채 일러스트 + 손글씨 로고 '별밤', 고양이 마스코트, "
                                           "따뜻한 필름톤, 왼쪽 하단 브랜드 마크, 유럽 빈티지 무드")
        if st.button("💾 시그니처 저장", key="save_sig"):
            G.set_signature(cur, new_sig)
            st.success("저장! 생성에 '우리만의 결'로 반영됩니다."); st.rerun()

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
        with st.spinner("세트 생성 + 🏆 CTR 예측 채점 중…"):
            sets = _generate_sets(cur, content, n, formula, ref_titles)
            sets = CS.score_sets(sets, cur, ident)     # 후보 채점 → 베스트 정렬
            if gen_target != "KR":                     # 타깃 언어면 현지 정서로 번안(+한국어 병기)
                _tl = LZ.localize_batch([s["title"] for s in sets], gen_target)
                _xl = LZ.localize_batch([s.get("thumb_text", "") for s in sets], gen_target)
                for _i, _s in enumerate(sets):
                    if _tl.get(_i):
                        _s["title_ko"] = _s["title"]; _s["title"] = _tl[_i]
                    if _xl.get(_i):
                        _s["thumb_text_ko"] = _s.get("thumb_text", ""); _s["thumb_text"] = _xl[_i]
        _ss_set("gen_" + cur, sets)

    gens = st.session_state.get("gen_" + cur, [])
    if gens:
        st.caption("💾 생성 이미지는 저장돼 탭을 옮겨도 남아요. 프롬프트는 📋로 복사해 ChatGPT·Gemini·미드저니에서도 쓸 수 있어요.")
    for i, s in enumerate(gens):
        box = st.container(border=True)
        sc = s.get("score", {})
        if sc:
            tot = sc.get("total", 0)
            badge = "🏆 베스트 " if s.get("winner") else ""
            dot = "🟢" if tot >= 75 else ("🟠" if tot >= 55 else "🔴")
            box.markdown(f"### {badge}{dot} CTR 예측 {tot} / 100")
            box.caption(" · ".join(f"{CS.LABELS[c]} {sc.get(c,0)}" for c in CS.CRITERIA))
            if sc.get("reason"):
                box.caption("💬 " + sc["reason"])
        else:
            box.markdown(f"**세트 {i+1}**")
        box.caption("📋 제목" + ("  ·  🌐 현지 정서 번안" if s.get("title_ko") else ""))
        box.code(s["title"], language=None)
        if s.get("title_ko"):
            box.caption("🇰🇷 " + s["title_ko"])
        _tx = s.get("thumb_text", "")
        box.caption("🖼 썸네일 문구(이미지 위 글자): " + _tx
                    + (f"  (🇰🇷 {s['thumb_text_ko']})" if s.get("thumb_text_ko") else ""))

        # 외부 도구용 프롬프트 (복붙) — 공식(원리) + 우리 시그니처 + 복제 금지
        base_scene = s.get("scene", content)
        _p = [TS.STYLES[thumb_style]]
        if igp.get("thumbnail_prompt"):        # 저장된 장르 공식 = 원리만 참고
            _p.append("Winning pattern (principles only, do not copy): " + igp["thumbnail_prompt"])
        _sig = ident.get("signature", "")
        if _sig:
            _p.append("OUR channel signature style (make it distinctly ours): " + _sig)
        _p.append("Create an ORIGINAL scene in our own style — it must NOT look like a copy of any "
                  "reference. Scene: " + base_scene)
        scene = " . ".join(_p)
        box.caption("📋 이미지 프롬프트 (ChatGPT · Gemini · DALL·E) — 우리 결 + 복제 방지 포함")
        box.code(scene, language=None)
        box.caption("📋 미드저니 프롬프트")
        box.code(_mj_prompt(scene), language=None)

        img_key = f"img_{cur}_{i}"
        imgval = st.session_state.get(img_key)
        b1, b2 = box.columns(2)
        do_draw = bool(CM) and b1.button("🎨 그리기(최고화질)" if not imgval else "🔄 다시 그리기",
                                         key=f"draw_{i}", use_container_width=True)
        if b2.button("🗑 이미지 삭제", key=f"del_{i}", disabled=not imgval, use_container_width=True):
            _ss_del(img_key); st.rerun()
        if do_draw:
            with st.spinner("생성 중… (씬 이미지 → 글자 얹기)"):
                # scene 에 이미 공격스타일+공식+시그니처+복제금지 포함
                out = CM.generate_thumbnail_image(scene, size="1536x1024", refs=refs[:6])
            if out.get("data_url"):
                final = OV.overlay_title(out["data_url"], s.get("thumb_text", ""))
                _ss_set(img_key, OV.to_data_url(final))
                st.rerun()
            else:
                box.error(out.get("error", "생성 실패 — OpenAI 키 필요(설정)."))
        if imgval:
            box.image(imgval, use_container_width=True)
            box.download_button("⬇️ 이미지 다운로드 (PNG)", data=_dataurl_bytes(imgval),
                                file_name=f"{cur}_{i+1}.png", mime="image/png",
                                key=f"dl_{i}", use_container_width=True)
            # 📱 폰 피드 미리보기 (작게 봐도 읽히나 확인)
            fp = box.columns([1, 2])
            fp[0].image(imgval, width=180)
            fp[1].caption("📱 폰 피드에서 이렇게 보여요")
            fp[1].markdown(f"**{s['title'][:45]}**")
            fp[1].caption("📺 내 채널 · 조회수 1.2만 · 방금")
            # 👁 이미지 Vision 채점
            sc_key = f"imgscore_{cur}_{i}"
            imgsc = st.session_state.get(sc_key)
            if box.button("👁 이 썸네일 이미지 채점 (Vision)", key=f"vs_{i}"):
                with st.spinner("GPT Vision 이미지 채점 중…"):
                    _r = TS.score(imgval, s.get("title", ""), cur, ident)
                if _r:
                    _ss_set(sc_key, _r); st.rerun()
                else:
                    box.warning("이미지 채점은 OpenAI 키가 필요해요(설정 탭).")
            if imgsc:
                _t = imgsc.get("total", 0)
                _d = "🟢" if _t >= 75 else ("🟠" if _t >= 55 else "🔴")
                box.markdown(f"**👁 {_d} 이미지 CTR {_t} / 100**")
                box.caption(" · ".join(f"{TS.LAB[c]} {imgsc.get(c,0)}" for c in TS.CRIT))
                if imgsc.get("verdict"):
                    box.caption("💬 " + imgsc["verdict"])
                for _tip in imgsc.get("tips", []):
                    box.write("• " + _tip)

# ═══════════════════════════════════════════════════════════════
# 🤖 AI 편집 대화
# ═══════════════════════════════════════════════════════════════
if page == "🤖 AI 편집":
    st.subheader(f"🤖 AI 편집 대화 — {cur}")
    st.caption("나랑 대화하듯 고쳐요. 예: '제목 더 궁금하게', '대비 강하게 고양이 추가', '문구를 한 줄로'.")
    wk_key, hk_key, imgk = f"chat_work_{cur}", f"chat_hist_{cur}", f"chatimg_{cur}"
    work = st.session_state.get(wk_key, {"title": "", "thumb_text": "", "scene": ""})
    hist = st.session_state.get(hk_key, [])
    ci_ident = G.get_identity(cur) or {}
    ci_igp = ci_ident.get("generation_prompt", {})
    brief = " | ".join(filter(None, [ci_ident.get("signature", ""), ci_igp.get("title_template", "")]))

    with st.expander("✏️ 편집 시작 (소재 입력 또는 생성 세트 불러오기)", expanded=not work.get("title")):
        seed = st.text_input("소재/초안 제목", key="chat_seed")
        cgens = st.session_state.get("gen_" + cur, [])
        copts = [f"세트 {i+1}: {g.get('title','')[:28]}" for i, g in enumerate(cgens)]
        cA, cB = st.columns(2)
        if cA.button("이 소재로 시작", use_container_width=True) and seed.strip():
            _ss_set(wk_key, {"title": seed, "thumb_text": "", "scene": seed})
            _ss_set(hk_key, []); st.session_state.pop(imgk, None); st.rerun()
        pick = cB.selectbox("생성 세트 불러오기", ["(선택)"] + copts, label_visibility="collapsed") if copts else "(선택)"
        if copts and pick != "(선택)":
            g = cgens[copts.index(pick)]
            if cB.button("불러오기", use_container_width=True):
                _ss_set(wk_key, {"title": g.get("title", ""), "thumb_text": g.get("thumb_text", ""),
                                 "scene": g.get("scene", "")})
                _ss_set(hk_key, []); st.session_state.pop(imgk, None); st.rerun()

    st.markdown("**현재 작업물**")
    st.code(work.get("title", ""), language=None)
    st.caption("🖼 문구: " + (work.get("thumb_text", "") or "-"))
    st.caption("🎬 장면: " + (work.get("scene", "") or "-")[:80])

    for m in hist:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.write(m["content"])
    if prompt := st.chat_input("어떻게 고칠까요?"):
        hist2 = hist + [{"role": "user", "content": prompt}]
        with st.spinner("AI 편집 중…"):
            r = CE.chat(hist2, work, cur, brief)
        _ss_set(wk_key, {"title": r["title"], "thumb_text": r["thumb_text"], "scene": r["scene"]})
        _ss_set(hk_key, hist2 + [{"role": "assistant", "content": r["reply"]}])
        st.rerun()

    cst = st.selectbox("🎨 썸네일 스타일", list(TS.STYLES), key="chat_style")
    if CM and work.get("scene") and st.button("🎨 현재 작업물로 썸네일 그리기", type="primary"):
        _p = [TS.STYLES[cst]]
        if ci_igp.get("thumbnail_prompt"):
            _p.append("Winning pattern (principles only): " + ci_igp["thumbnail_prompt"])
        if ci_ident.get("signature"):
            _p.append("OUR signature (distinctly ours): " + ci_ident["signature"])
        _p.append("Original scene, not a copy. Scene: " + work["scene"])
        with st.spinner("생성 중…"):
            out = CM.generate_thumbnail_image(" . ".join(_p), size="1536x1024",
                                              refs=[b["thumb"] for b in G.get_basket(cur) if b.get("thumb")][:6])
        if out.get("data_url"):
            _ss_set(imgk, OV.to_data_url(OV.overlay_title(out["data_url"], work.get("thumb_text", ""))))
            st.rerun()
        else:
            st.error(out.get("error", "생성 실패 — OpenAI 키 필요."))
    ci = st.session_state.get(imgk)
    if ci:
        st.image(ci, use_container_width=True)
        st.download_button("⬇️ 다운로드 (PNG)", data=_dataurl_bytes(ci),
                           file_name=f"{cur}_chat.png", mime="image/png")

# ═══════════════════════════════════════════════════════════════
# 🌊 트렌드 레이더
# ═══════════════════════════════════════════════════════════════
if page == "🌊 트렌드 레이더":
    st.subheader("🌊 트렌드 레이더 — 장르 불문 '지금 터지는 제목'")
    st.caption("터지는 제목 = [상황]+[장르]. 상황 구조는 장르를 초월해요. 다른 장르 급상승 제목을 "
               "가져와 **장르만 우리 걸로** 바꿔 쓰면 됩니다.")
    rc1, rc2 = st.columns([1, 2])
    region_name = rc1.selectbox("🌍 나라", list(TR.REGIONS), key="radar_region")
    region = TR.REGIONS[region_name]
    kws = rc2.text_input("상황 키워드 (쉼표, 비우면 그 나라 언어 기본 세트로 검색)", key="radar_kw")
    kw_list = [k.strip() for k in kws.split(",") if k.strip()] or None
    days = st.slider("최근 며칠 이내", 3, 30, 14)
    if st.button("🔍 지금 터지는 제목 찾기", type="primary"):
        with st.spinner(f"{region_name} 최근 급상승 검색 중…"):
            _ss_set("radar_res", TR.find_surging(kw_list, days=days, region=region))

    rr = st.session_state.get("radar_res")
    if rr:
        if rr.get("engine") == "demo":
            st.warning("⚠️ YouTube 키가 없어 데모입니다. (사장님 PC에선 실검색)")
        elif not rr["videos"]:
            st.info("결과가 0개예요. 최근 일수를 늘리거나(예: 30일), 상황 키워드를 직접 넣거나, "
                    "다른 나라를 선택해보세요. (쿼터 소진 시에도 0이 날 수 있어요)")
        st.caption(f"🌍 {region} · 급상승 {len(rr['videos'])}개 (일평균 조회수 높은 순)")
        for i, v in enumerate(rr["videos"]):
            box = st.container(border=True)
            cc = box.columns([1, 3])
            if v.get("thumb"):
                cc[0].image(v["thumb"], use_container_width=True)
            cc[1].markdown(f"**{v['title']}**")
            if v.get("title_ko"):
                cc[1].markdown(f"🇰🇷 {v['title_ko']}")
            cc[1].caption(f"🔥 일평균 {int(v.get('vpd',0)):,}회 · 👁 {v.get('views',0):,} · "
                          f"[{v.get('keyword','')}] · 📺 {(v.get('channel','') or '')[:18]}")
            src_title = v.get("title_ko") or v["title"]     # 번역본 있으면 그걸로 템플릿
            tmpl = TR.strip_genre_template(src_title)
            cc[1].caption("💡 전이 템플릿 (한국어 · 장르만 우리 걸로 바꾸면 됨)")
            cc[1].code(tmpl, language=None)
            if cc[1].button(f"➡️ '{cur}' 참고 제목으로 저장", key=f"radar_apply_{i}"):
                G.add_example_title(cur, tmpl)
                st.toast("저장! ✨ 생성에서 참고 제목으로 쓰여요")

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
    st.caption("🔖 북마크 + 🔔 알림 ON 채널만 → ① 새 영상 즉시 알림 ② 72시간 후 성과 알림.")
    st.caption("📊 새 영상이 뜨면 카톡, 그 영상이 72시간 뒤 얼마나 떴는지(조회수·일평균·판정) 다시 카톡으로 와요.")
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
    st.caption("이 PC의 .env + keys.json 에 영구 저장. 둘 다 gitignore — 절대 업로드 안 됨. "
               "다른 툴이 .env 를 지워도 keys.json 에서 복원돼요.")

    def _mask(k):
        v = os.environ.get(k, "")
        return f"저장됨 ••••{v[-4:]}" if v else "미설정"
    st.write(f"현재 상태 — 🎬 YouTube: **{_mask('YOUTUBE_API_KEY')}** · "
             f"🤖 OpenAI: **{_mask('OPENAI_API_KEY')}** · ✨ Gemini: **{_mask('GEMINI_API_KEY')}**")

    yk = st.text_input("YOUTUBE_API_KEY", type="password", placeholder="바꿀 때만 입력(빈칸=유지)")
    ok = st.text_input("OPENAI_API_KEY (GPT·이미지생성)", type="password", placeholder="바꿀 때만 입력(빈칸=유지)")
    gk = st.text_input("GEMINI_API_KEY (선택)", type="password", placeholder="바꿀 때만 입력(빈칸=유지)")
    if st.button("💾 저장"):
        _save_keys({"YOUTUBE_API_KEY": yk, "OPENAI_API_KEY": ok, "GEMINI_API_KEY": gk})
        st.success("저장 완료 — 즉시 적용. (일부는 앱 재시작 후 반영)")
