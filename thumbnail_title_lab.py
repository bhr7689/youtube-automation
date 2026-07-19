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
import img_similar as IMG
import title_digest as TD
import bookmark_tool as BT

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
PAGES = ["🏠 대시보드", "🗂 자동분류", "🔖 북마크 채널", "🔬 구간 분석",
         "🌊 트렌드 레이더", "🔔 감시/알림", "⚙️ 설정"]
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
    st.caption("장르마다 독립 채널 프로젝트. 새 장르 진입엔 **분석이 곧 설계도**입니다. "
               "지금 목표 🇯🇵→🇰🇷 · 🇰🇷→🇯🇵 번안.")

    # ── 전체 요약(한눈에) ──────────────────────────────
    _all = list(state["projects"].values())
    _tb = sum(len(p["benchmarks"]) for p in _all)
    _tbm = sum(1 for p in _all for b in p["benchmarks"] if b.get("bookmark"))
    _tal = sum(1 for p in _all for b in p["benchmarks"] if b.get("alarm"))
    m = st.columns(4)
    m[0].metric("장르(채널)", len(_all))
    m[1].metric("벤치마킹 링크", _tb)
    m[2].metric("🔖 북마크 채널", _tbm)
    m[3].metric("🔔 알림 ON", _tal)
    st.divider()

    cols = st.columns(3)
    for i, (name, p) in enumerate(state["projects"].items()):
        with cols[i % 3]:
            bm = sum(1 for b in p["benchmarks"] if b.get("bookmark"))
            al = sum(1 for b in p["benchmarks"] if b.get("alarm"))
            box = st.container(border=True, height=270)   # 고정 높이 → 열 맞춤
            box.markdown(f"### {'⭐ ' if name == cur else ''}{name}")
            box.caption((p.get("note") or "")[:70])
            box.write(f"벤치 {len(p['benchmarks'])}개 · 🔖{bm} · 🔔{al} · 🧺{len(p['basket'])}")
            g1, g2 = box.columns(2)
            if g1.button("🔬 구간분석", key=f"pick_{i}", use_container_width=True):
                G.set_current(name)
                st.session_state["_goto"] = "🔬 구간 분석"   # 바로 분석 화면으로 이동
                st.rerun()
            if g2.button("🔖 북마크채널", key=f"pickbm_{i}", use_container_width=True):
                G.set_current(name)
                st.session_state["_goto"] = "🔖 북마크 채널"
                st.rerun()

# ═══════════════════════════════════════════════════════════════
# 🗂 자동분류
# ═══════════════════════════════════════════════════════════════
if page == "🗂 자동분류":
    st.subheader("🗂 미분류 대량 링크 자동분류")
    st.caption("링크 뭉치 붙여넣기 → 유튜브에서 제목 읽어 장르통으로 자동 정렬 → "
               "**드롭다운으로 직접 옮긴 뒤** 각 장르에 추가.")

    with st.container(border=True):
        st.markdown("**🔧 데이터 복구** — 인벤토리의 모든 링크를 '📦 복구함'으로 되살리기 (분류·API 불필요)")
        _invn = len(LC.load_inventory_urls(videos_only=False))
        if st.button(f"🔧 인벤토리 전체 복구 ({_invn}개 링크)", type="primary"):
            _urls = LC.load_inventory_urls(videos_only=False)
            if _urls:
                G.add_project("📦 복구함", "인벤토리에서 되살린 링크 — 여기서 자동분류로 정리하세요.")
                G.add_benchmarks("📦 복구함", _urls)
                st.success(f"{len(_urls)}개 링크를 '📦 복구함'에 복구했어요! "
                           "이제 아래 '📂 미분류함 다시 분류' 대신 이 장르를 선택해 자동분류하거나, "
                           "구간분석에서 바로 보세요.")
                st.rerun()
            else:
                st.warning("인벤토리 파일을 못 찾았어요.")
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
# 🔖 북마크 채널
# ═══════════════════════════════════════════════════════════════
if page == "🔖 북마크 채널":
    st.subheader(f"🔖 북마크 채널 — {cur}")
    st.caption("🔖 북마크한 채널을 조회수순으로: 채널명·로고·구독자·개설일 + 인기 영상(썸네일·제목·조회수). "
               "🔔 알림 켜면 새 영상+72h 성과 카톡.")

    with st.expander("➕ 이 장르에 북마크 채널 직접 추가 (채널/영상 URL, 여러 줄)", expanded=False):
        st.caption(f"여기에 넣으면 **'{cur}' 장르**에 바로 🔖 북마크로 등록돼요. 영상 링크는 원채널로 추적돼요.")
        _bt = st.text_area("채널/영상 URL", height=90, key="bmadd_" + cur,
                           placeholder="https://www.youtube.com/@channel\nhttps://youtu.be/xxxx")
        _bal = st.checkbox("🔔 새 영상·72h 성과 알림도 함께 켜기", value=True, key="bmadd_al_" + cur)
        if st.button("🔖 북마크로 추가", type="primary", disabled=not _bt.strip()):
            _urls = [u.strip() for u in _bt.replace(",", "\n").splitlines() if u.strip()]
            _added = 0
            for u in _urls:
                if "youtu" not in u.lower():      # 유튜브 URL 아니면 건너뜀
                    continue
                G.add_benchmarks(cur, [u])
                G.toggle_flag(cur, u, "bookmark", True)
                if _bal:
                    G.toggle_flag(cur, u, "alarm", True)
                _added += 1
            if _added:
                _ss_del("bm_" + cur)              # 다시 불러오기 유도
                st.toast(f"🔖 {_added}개 북마크 추가 (알림 {'ON' if _bal else 'OFF'})"); st.rerun()
            else:
                st.warning("유튜브 URL을 찾지 못했어요. (채널/@핸들/영상 링크를 넣어주세요)")

    _bm = [b for b in proj["benchmarks"] if b.get("bookmark")]
    b1, b2 = st.columns(2)
    if b1.button(f"🔖 북마크 채널 불러오기 ({len(_bm)}개)", type="primary"):
        with st.spinner("채널 정보·구독자·개설일·인기영상 수집 중…"):
            _ss_set("bm_" + cur, BT.collect(proj["benchmarks"]))
    if b2.button("🇰🇷🇯🇵 제목 번안 보기 (일↔한)"):
        _d = st.session_state.get("bm_" + cur)
        if _d:
            _allt = [(v["video_id"], v["title"]) for ch in _d["channels"]
                     for v in ch["videos"] if v.get("video_id")]
            _ja = [(vid, t) for vid, t in _allt if LC.is_japanese({"title": t})]
            _ko = [(vid, t) for vid, t in _allt if not LC.is_japanese({"title": t})]
            _tr = {}
            if _ja:
                _m = LZ.localize_batch([t for _, t in _ja], "KR")
                for _i, (vid, _) in enumerate(_ja):
                    _tr[vid] = ("🇰🇷", _m.get(_i, ""))
            if _ko:
                _m = LZ.localize_batch([t for _, t in _ko], "JP")
                for _i, (vid, _) in enumerate(_ko):
                    _tr[vid] = ("🇯🇵", _m.get(_i, ""))
            _ss_set("bmtr_" + cur, _tr)

    data = st.session_state.get("bm_" + cur)
    tr = st.session_state.get("bmtr_" + cur, {})
    if data:
        if data.get("demo"):
            st.warning("⚠️ YouTube 키가 없어 데모입니다. (사장님 PC에선 실데이터)")
        if not data["channels"]:
            st.info("북마크된 채널이 없어요. 구간분석/레이더 카드에서 🔖·⭐로 북마크하세요.")
        for ci, ch in enumerate(data["channels"]):
            box = st.container(border=True)
            hd = box.columns([1, 5, 2])
            if ch.get("logo"):
                hd[0].image(ch["logo"], width=64)
            hd[1].markdown(f"### {ch['channel']}")
            hd[1].caption(f"👥 구독 {ch['subscribers']:,} · 📅 개설 {ch.get('created','?')} "
                          f"({BT.channel_age(ch.get('created',''))} 됨)")
            if ch.get("url"):
                _bref = next((b for b in proj["benchmarks"] if b["url"] == ch["url"]), None)
                _al = _bref.get("alarm") if _bref else False
                if hd[2].checkbox("🔔 알림", value=_al, key=f"bmal_{ci}") != _al:
                    G.toggle_flag(cur, ch["url"], "alarm"); st.rerun()
            grid = box.columns(4)
            for j, v in enumerate(ch["videos"][:8]):
                with grid[j % 4]:
                    _vid = v.get("video_id", "")
                    if v.get("thumb"):
                        _lk = f"https://youtu.be/{_vid}"
                        st.markdown(f'<a href="{_lk}" target="_blank">'
                                    f'<img src="{v["thumb"]}" style="width:100%;border-radius:8px"></a>',
                                    unsafe_allow_html=True)
                    st.caption(f"👁 {v['views']:,} · {v['published']}")
                    st.caption((v.get("title", "") or "")[:30])
                    _t = tr.get(_vid)
                    if _t:
                        st.caption(_t[0] + " " + (_t[1] or "")[:28])
    elif not _bm:
        st.info("아직 북마크한 채널이 없어요. 🔬 구간분석/🌊 레이더 카드에서 🔖·⭐로 북마크한 뒤 여기서 모아보세요.")

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

        with st.expander("🔀 장르 이동 / 삭제 (여러 개 한 번에)", expanded=False):
            st.caption("이 장르의 링크를 골라 **다른 장르로 옮기거나** 삭제해요. 필요 없는 데이터 정리에 쓰세요.")
            _opts = {(f"{b['channel']} · " if b.get("channel") else "") + b["url"]: b["url"]
                     for b in proj["benchmarks"]}
            _sel_lbls = st.multiselect("링크 선택", list(_opts), key="mv_sel_" + cur)
            _sel = [_opts[l] for l in _sel_lbls]
            _others = [g for g in projects if g != cur]
            m1, m2 = st.columns([2, 1])
            _tgt = m1.selectbox("이동할 장르", _others, key="mv_tgt_" + cur) if _others else None
            if m1.button("➡️ 선택 이동", disabled=not (_sel and _tgt), use_container_width=True):
                for u in _sel:
                    G.move_benchmark(cur, u, _tgt)
                st.toast(f"{len(_sel)}개 → '{_tgt}'로 이동"); st.rerun()
            if m2.button("🗑 선택 삭제", disabled=not _sel, use_container_width=True):
                for u in _sel:
                    G.remove_benchmark(cur, u)
                st.toast(f"{len(_sel)}개 삭제"); st.rerun()

        expand = st.checkbox("🔗 영상 링크를 **원채널로 확장** (그 채널 새 영상까지 분석 — 시간 지나도 갱신)",
                             value=True, key="expand_ch")
        if st.button("📊 분석 실행 (수집 → 구간별 공식)", type="primary"):
            if CM is None:
                st.error("concept_maker 로드 실패 — jpshorts/backend 확인.")
            else:
                allvids, seen = [], set()
                chans = [b["url"] for b in proj["benchmarks"]]
                ch_urls = [u for u in chans if LC.extract_ref(u)[0] in ("channel", "handle")]
                vid_urls = [u for u in chans if LC.extract_ref(u)[0] == "video"]
                targets = list(ch_urls)                    # 수집할 '채널' 목록
                prog = st.progress(0.0, "수집 준비…")
                if vid_urls and expand:                    # 영상 → 원채널 해석 후 채널로 편입
                    for vc in LC.resolve_videos_to_channels(vid_urls):
                        if vc.get("channel_id"):
                            G.set_benchmark_channel(cur, vc["url"], vc["channel_id"], vc["channel_title"])
                            turl = "https://www.youtube.com/channel/" + vc["channel_id"]
                            if turl not in targets:
                                targets.append(turl)
                for i, url in enumerate(targets):          # 채널들 → 그 채널 최근 영상들(갱신됨)
                    data = CM.collect_channel(url)
                    for v in data.get("videos", []):
                        vid = v.get("video_id", "")
                        if vid and vid in seen:
                            continue
                        seen.add(vid)
                        allvids.append({**v, "source": data.get("title", url), "bench_url": url})
                    prog.progress((i + 1) / max(1, len(targets) + 1), f"채널 {i+1}/{len(targets)}")
                if vid_urls and not expand:                # 확장 OFF → 그 영상만 직접 조회
                    prog.progress(0.95, f"영상 {len(vid_urls)}개 조회…")
                    allvids += [v for v in LC.fetch_video_stats(vid_urls)
                                if v.get("video_id") not in seen]
                prog.empty()
                _ss_set("report_" + cur, T.tier_report(allvids))
                if not os.environ.get("YOUTUBE_API_KEY", "").strip():
                    st.warning("⚠️ YouTube 키가 없어 데모/빈 데이터입니다. (설정 탭에서 키 저장)")
                elif not allvids:
                    st.warning("수집 0건 — 벤치마킹 링크를 확인해주세요.")

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
                        # 카드에서 바로 🔖북마크 · 🔔알림 · ⭐집중 · 🗑삭제
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
                        if a3.button("⭐", key=f"fc_{label}_{j}", help="집중 벤치마킹에 추가 + 알림 ON",
                                     disabled=(not burl or cur == G.FOCUS_BUCKET)):
                            G.add_benchmarks(G.FOCUS_BUCKET, [burl])
                            G.toggle_flag(G.FOCUS_BUCKET, burl, "alarm", True)
                            st.toast("⭐ 집중 벤치마킹에 추가 + 🔔알림 ON")
                        if a4.button("🗑", key=f"del_{label}_{j}", help="잘못 수집된 링크 삭제 (이 소스 링크 + 카드 즉시 제거)",
                                     disabled=not burl):
                            G.remove_benchmark(cur, burl)                 # 원본 소스 링크 제거
                            info["videos"] = [x for x in info["videos"]  # 이 소스의 카드 즉시 제거
                                              if x.get("bench_url") != burl]
                            info["count"] = len(info["videos"])
                            rep["total"] = sum(t["count"] for t in rep["tiers"].values())
                            _ss_set("report_" + cur, rep)
                            st.toast("🗑 잘못 수집 링크 삭제됨"); st.rerun()
                        card.caption(f"👁 {int(v.get('views',0)):,} · 📅 {v.get('published','')}")
                        card.caption(f"📺 {(v.get('source','') or '')[:22]}")
                        card.caption((v.get("title", "") or "")[:38])

# ═══════════════════════════════════════════════════════════════
# 🌊 트렌드 레이더
# ═══════════════════════════════════════════════════════════════
if page == "🌊 트렌드 레이더":
    st.subheader("🌊 트렌드 레이더 — 장르 불문 '지금 터지는 제목'")
    st.caption("터지는 제목 = [상황]+[장르]. 상황 구조는 장르를 초월해요. 다른 장르 급상승 제목을 "
               "가져와 **장르만 우리 걸로** 바꿔 쓰면 됩니다.")
    if "_radar_kw" in st.session_state:        # 키워드 칩 클릭 → 검색어 반영(위젯 생성 전)
        st.session_state["radar_kw"] = st.session_state.pop("_radar_kw")
    rc1, rc2 = st.columns([1, 2])
    region_name = rc1.selectbox("🌍 나라", list(TR.REGIONS), key="radar_region")
    region = TR.REGIONS[region_name]
    kws = rc2.text_input("상황 키워드 (쉼표, 비우면 그 나라 언어 기본 세트로 검색)", key="radar_kw")
    kw_list = [k.strip() for k in kws.split(",") if k.strip()] or None
    st.caption("💡 키워드를 한국어로 넣어도, 선택한 나라 언어로 **자동 번역해 검색**해요 (플레이리스트→プレイリスト).")
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
        _usedkw = rr.get("keywords", [])
        st.caption(f"🌍 {region} · 급상승 {len(rr['videos'])}개 (일평균 조회수 높은 순)"
                   + (f" · 검색어: {', '.join(_usedkw[:6])}" if _usedkw else ""))
        _plist = list(state["projects"].keys())
        _tc1, _tc2 = st.columns([3, 1])
        rtarget = _tc1.selectbox("📁 담을 장르 (아래 버튼이 이 장르로 저장돼요)", _plist,
                                 index=_plist.index(cur) if cur in _plist else 0, key="radar_target")
        if _tc2.button("🗑 전체 삭제", help="분류 다 끝냈으면 결과 목록 비우기"):
            _ss_del("radar_res"); st.rerun()

        # 🔑 떠오르는 키워드 (결과 제목에서 추출 → 데이터화)
        _rtitles = [v.get("title_ko") or v.get("title", "") for v in rr["videos"]]
        _rdg = TD.digest(_rtitles)
        if _rdg.get("top_tokens"):
            st.markdown("**🔑 떠오르는 키워드** (급상승 제목에서 추출 — 클릭하면 그 키워드로 재검색)")
            kcols = st.columns(6)
            for _ki, (w, c) in enumerate(_rdg["top_tokens"][:6]):
                if kcols[_ki].button(f"{w} ({c})", key=f"radar_kwchip_{_ki}"):
                    st.session_state["_radar_kw"] = w; st.rerun()
        # 📺 급상승 채널 (새로 뜨는 채널 발굴 → 담기)
        import collections as _col
        _chc = _col.Counter(v.get("channel", "") for v in rr["videos"] if v.get("channel"))
        if _chc:
            st.markdown("**📺 급상승 채널** (담으면 원채널로 추적)")
            for _ci, (chname, ccnt) in enumerate(_chc.most_common(5)):
                _cc = st.columns([3, 1])
                _cc[0].caption(f"📺 {chname} · 급상승 {ccnt}개")
                _vu = next((f"https://youtu.be/{v['video_id']}" for v in rr["videos"]
                            if v.get("channel") == chname and not str(v.get("video_id", "")).startswith("demo")), "")
                if _vu and _cc[1].button("📌 담기", key=f"radar_chadd_{_ci}"):
                    G.add_benchmarks(rtarget, [_vu]); st.toast(f"'{rtarget}'에 채널 담음(원채널 확장)")
        st.divider()

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
            _vurl = f"https://youtu.be/{v.get('video_id','')}"
            _demo = str(v.get("video_id", "")).startswith("demo")
            b1, b2, b3 = cc[1].columns(3)
            if b1.button("📌 벤치마크 담기", key=f"radar_bench_{i}", disabled=_demo,
                         help=f"'{rtarget}' 벤치마크에 담고 목록에서 제거"):
                G.add_benchmarks(rtarget, [_vurl])
                rr["videos"].pop(i); _ss_set("radar_res", rr)
                st.toast(f"'{rtarget}'에 담고 목록서 제거"); st.rerun()
            if b2.button("⭐ 집중+알림", key=f"radar_focus_{i}", disabled=_demo,
                         help="집중 벤치마킹에 추가 + 알림 ON, 목록서 제거"):
                G.add_benchmarks(G.FOCUS_BUCKET, [_vurl])
                G.toggle_flag(G.FOCUS_BUCKET, _vurl, "alarm", True)
                rr["videos"].pop(i); _ss_set("radar_res", rr)
                st.toast("⭐ 집중+알림, 목록서 제거"); st.rerun()
            if b3.button("🗑 삭제", key=f"radar_del_{i}", help="이 결과만 제거"):
                rr["videos"].pop(i); _ss_set("radar_res", rr); st.rerun()

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
