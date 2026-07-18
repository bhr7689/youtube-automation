"""thumbnail_title_lab.py — 🎬 썸네일·제목 연구소 (장르별 채널 공장)

여러 장르 채널을 새로 개설하기 위한 도구. 장르마다 독립 프로젝트로:
  🔬 장르 분석(승리 공식) ↔ ✨ 생성(그 공식대로 제작) 두 축.
+ 🎯 일치성 점수 · 🧺 레퍼런스 바구니 · 🔔 북마크 카톡 알림.

실행: streamlit run thumbnail_title_lab.py --server.port 8505
"""
from __future__ import annotations

import os
import sys

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

# ── 사이드바: 프로젝트(장르) 선택 ─────────────────────────────
state = G.load_state()
projects = list(state["projects"].keys())

with st.sidebar:
    st.markdown("## 🎬 썸네일·제목 연구소")
    st.caption("여러 장르 채널 공장 — 분석↔생성")
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


tabs = st.tabs(["🏠 대시보드", "🔬 구간 분석", "🎯 일치성", "✨ 생성",
                "🧺 레퍼런스 바구니", "🔔 감시/알림", "⚙️ 설정"])

# ═══════════════════════════════════════════════════════════════
# 🏠 대시보드
# ═══════════════════════════════════════════════════════════════
with tabs[0]:
    st.subheader("🏠 채널(장르) 대시보드")
    st.caption("장르마다 독립 채널 프로젝트. 새 장르 진입엔 **분석이 곧 설계도**입니다.")
    cols = st.columns(3)
    for i, (name, p) in enumerate(state["projects"].items()):
        with cols[i % 3]:
            bm = sum(1 for b in p["benchmarks"] if b.get("bookmark"))
            al = sum(1 for b in p["benchmarks"] if b.get("alarm"))
            box = st.container(border=True)
            box.markdown(f"### {'⭐ ' if name == cur else ''}{name}")
            box.caption((p.get("note") or "")[:60])
            box.write(f"벤치 {len(p['benchmarks'])}개 · 🔖{bm} · 🔔{al} · 🧺{len(p['basket'])}")
            if box.button("선택", key=f"pick_{i}", use_container_width=True):
                G.set_current(name); st.rerun()

# ═══════════════════════════════════════════════════════════════
# 🔬 구간 분석
# ═══════════════════════════════════════════════════════════════
with tabs[1]:
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
                        allvids.append({**v, "source": data.get("title", url)})
                    prog.progress((i + 1) / len(chans), f"수집 {i+1}/{len(chans)}")
                prog.empty()
                st.session_state["report_" + cur] = T.tier_report(allvids)
                if any(CM.collect_channel(u).get("demo") for u in chans[:1]):
                    st.warning("⚠️ YouTube 키가 없어 데모 데이터로 시연 중입니다. (사장님 PC에선 실데이터)")

        rep = st.session_state.get("report_" + cur)
        if rep:
            st.success(f"6개월 이내 {rep['total']}개 분석 (오래된 영상 {rep['dropped_old']}개 제외)")
            for label in T.TIER_ORDER:
                info = rep["tiers"][label]
                if not info["count"]:
                    continue
                low = " 🌱" if info["is_low"] else ""
                st.markdown(f"#### {label}{low} — {info['count']}개")
                st.caption("승리 공식: " + info["formula"])
                grid = st.columns(4)
                for j, v in enumerate(info["videos"][:8]):
                    with grid[j % 4]:
                        if v.get("thumb"):
                            st.image(v["thumb"], use_container_width=True)
                        st.caption(f"👁 {int(v.get('views',0)):,} · 일{int(v.get('vpd',0)):,}")
                        st.caption((v.get("title", "") or "")[:40])
                        if st.button("🧺 바구니", key=f"bsk_{label}_{j}"):
                            G.add_to_basket(cur, v.get("thumb", ""), v.get("title", ""),
                                            v.get("source", "")); st.toast("바구니에 담음")

# ═══════════════════════════════════════════════════════════════
# 🎯 일치성 검사
# ═══════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("🎯 썸네일 ↔ 제목 일치성 검사")
    st.caption("감정·주제는 맞고, 문구는 새 정보를 줄 때 최고점. 실전에서 '불일치=노출저하'.")
    title = st.text_input("제목", placeholder="비 오는 새벽, 창가에서 듣는 재즈 ☔")
    thumb_text = st.text_input("썸네일 문구(이미지 위 글자)", placeholder="눈물이 나요")
    tags = st.text_input("썸네일 태그(쉼표, 선택)", placeholder="새벽, 재즈, 창가, 딥블루")
    if st.button("일치성 채점") and title.strip():
        r = T.consistency_heuristic(title, thumb_text, [t.strip() for t in tags.split(",") if t.strip()])
        color = "🟢" if r["total"] >= 75 else ("🟠" if r["total"] >= 55 else "🔴")
        st.markdown(f"## {color} {r['total']} / 100")
        c = st.columns(4)
        c[0].metric("감정 일치", r["emotion"]); c[1].metric("주제 일치", r["topic"])
        c[2].metric("정보 상보", r["complement"]); c[3].metric("타깃 일치", r["target"])
        for n in r["notes"]:
            st.write("• " + n)

# ═══════════════════════════════════════════════════════════════
# ✨ 생성
# ═══════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader(f"✨ 생성 — {cur}")
    st.caption("장르 공식 + 🧺 바구니 무드 + 내 콘텐츠 → 썸네일·제목 세트. 씬은 이미지, 글자는 코드로.")
    content = st.text_input("이번 영상 소재", placeholder="파리 카페의 비 오는 아침, 스텔라장 스타일 피아노")
    n = st.slider("만들 세트 수", 1, 5, 3)
    basket = G.get_basket(cur)
    refs = [b["thumb"] for b in basket if b.get("thumb")]
    st.caption(f"🧺 바구니 레퍼런스 {len(refs)}장 무드 반영 예정")

    if st.button("✨ 제목·썸네일 세트 생성", type="primary"):
        rep = st.session_state.get("report_" + cur)
        formula = ""
        if rep:
            for label in ("10만+", "5만+", "3만+", "1만+", "5천+"):
                if rep["tiers"][label]["count"]:
                    formula = f"[{label} 공식] " + rep["tiers"][label]["formula"]; break
        ref_titles = [b["title"] for b in basket if b.get("title")][:6]
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
                out = CM.generate_thumbnail_image(s.get("scene", content), size="1536x1024", refs=refs[:6])
                if out.get("data_url"):
                    final = OV.overlay_title(out["data_url"], s.get("thumb_text", ""))
                    box.image(final, use_container_width=True)
                    box.caption("✅ 씬 이미지 + 코드로 얹은 또렷한 문구")
                else:
                    box.error(out.get("error", "생성 실패 — OpenAI 키 필요(설정)."))

# ═══════════════════════════════════════════════════════════════
# 🧺 레퍼런스 바구니
# ═══════════════════════════════════════════════════════════════
with tabs[4]:
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
with tabs[5]:
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
with tabs[6]:
    st.subheader("⚙️ 설정 — 연결 키")
    st.caption("이 PC의 .env 에 저장됩니다. .env 는 gitignore — 절대 업로드 안 됨.")
    yk = st.text_input("YOUTUBE_API_KEY", type="password")
    ok = st.text_input("OPENAI_API_KEY (GPT·이미지생성)", type="password")
    gk = st.text_input("GEMINI_API_KEY (선택)", type="password")
    if st.button("💾 저장"):
        _save_keys({"YOUTUBE_API_KEY": yk, "OPENAI_API_KEY": ok, "GEMINI_API_KEY": gk})
        st.success("저장 완료 — 즉시 적용. (일부는 앱 재시작 후 반영)")
