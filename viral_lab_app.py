"""viral_lab_app.py — 🔟 조회수 1만+ 썸네일·제목 연구소 (단독 앱)

단 하나의 원칙: **조회수 1만 이상 영상만** 학습해 새 썸네일·제목을 만든다.
1만 미만은 발굴·분석·생성 어디에도 끼지 못한다("검증된 성공"만 학습).

4 탭:
  🔎 발굴·분석  — YouTube 검색 or 캡처 붙여넣기 → 1만+ 만 남겨 승리공식 + 👁Vision 실측
  ✨ 생성       — 그 1만+ 근거로 새 제목 10세트 + 썸네일 이미지(무드 이식·최고화질)
  📦 수집함     — 무인 cron(daily_viral_collect)이 매일 쌓은 1만+ 아카이브
  ⚙️ 설정       — 이 PC 에 API 키 저장(.env + keys.json)

실행: streamlit run viral_lab_app.py --server.port 8506
"""
from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_JSON = os.path.join(_HERE, "keys.json")

# .env + keys.json 를 환경변수로 (youtube_client/concept_maker import 전에)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_HERE, ".env"))
except Exception:                       # noqa: BLE001
    pass
try:
    if os.path.exists(KEYS_JSON):
        for _k, _v in json.load(open(KEYS_JSON, encoding="utf-8")).items():
            if _v:
                os.environ[_k] = _v
except Exception:                       # noqa: BLE001
    pass

import streamlit as st

import viral_lab as V

# concept_maker (Vision·이미지생성·리포트) 재사용
_BACKEND = os.path.join(_HERE, "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
try:
    import concept_maker as CM
except Exception as _e:                 # noqa: BLE001
    CM = None
    _CM_ERR = str(_e)

st.set_page_config(page_title="조회수 1만+ 연구소", page_icon="🔟", layout="centered")


# ── 키 저장(이 PC 의 .env + keys.json) ───────────────────────
def _save_keys(keys: dict) -> None:
    path = os.path.join(_HERE, ".env")
    lines: dict[str, str] = {}
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
    try:
        cur = json.load(open(KEYS_JSON, encoding="utf-8")) if os.path.exists(KEYS_JSON) else {}
        for k, v in keys.items():
            if v.strip():
                cur[k] = v.strip()
        json.dump(cur, open(KEYS_JSON, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:                   # noqa: BLE001
        pass
    try:                                # 유튜브 모듈 캐시 키 즉시 갱신(재시작 불필요)
        if CM and keys.get("YOUTUBE_API_KEY", "").strip():
            CM.yc.YOUTUBE_API_KEY = keys["YOUTUBE_API_KEY"].strip()
    except Exception:                   # noqa: BLE001
        pass


def _mask(name: str) -> str:
    v = os.environ.get(name, "").strip()
    return f"••••{v[-4:]}" if len(v) >= 4 else ("미설정" if not v else "설정됨")


def _dataurl_bytes(durl: str) -> bytes:
    if isinstance(durl, str) and durl.startswith("data:"):
        return base64.b64decode(durl.split(",", 1)[1])
    return b""


# ── 헤더 ─────────────────────────────────────────────────────
st.title("🔟 조회수 1만+ 연구소")
st.caption(f"**조회수 {V.MIN_VIEWS:,}회 이상** 썸네일·제목만 분석해서, 그 검증된 "
           "성공 공식대로 새 썸네일·제목을 만듭니다. 1만 미만은 아예 버립니다.")

_yt = bool(os.environ.get("YOUTUBE_API_KEY", "").strip())
_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
_badge = ("🎬 YouTube " + ("✅" if _yt else "⚠️미설정") + " · "
          "🎨 이미지생성(OpenAI) " + ("✅" if _openai else "⚠️미설정"))
st.caption(_badge + "  — 미설정 키는 **⚙️ 설정** 탭에서 넣으세요.")

if CM is None:
    st.error(f"생성 엔진(concept_maker) 로드 실패: {_CM_ERR}. 저장소 구조를 확인하세요.")

tab_find, tab_cluster, tab_gen, tab_store, tab_set = st.tabs(
    ["🔎 발굴·분석", "🧩 묶음·갈림", "✨ 생성", "📦 수집함", "⚙️ 설정"])


# ════════════════════════════════════════════════════════════
# 🔎 발굴·분석
# ════════════════════════════════════════════════════════════
with tab_find:
    st.subheader("1만+ 만 골라 승리 공식 뽑기")
    mode = st.radio("방법", ["🌐 YouTube 검색", "🔗 링크 직접 추가", "📎 캡처 붙여넣기"],
                    horizontal=True, label_visibility="collapsed")

    if mode == "🌐 YouTube 검색":
        kw = st.text_input("키워드", placeholder="예) 재즈 플레이리스트 / 새벽 감성 / 시티팝")
        c1, c2, c3 = st.columns(3)
        vtype = c1.selectbox("유형", ["all", "long", "shorts"],
                             format_func=lambda x: {"all": "전체", "long": "롱폼",
                                                    "shorts": "쇼츠"}[x])
        period = c2.selectbox("기간", [0, 30, 90, 180, 365],
                              index=3, format_func=lambda d: "전체" if d == 0 else f"{d}일")
        maxr = c3.slider("검색 수", 10, 50, 50, step=10)
        if st.button("🔎 1만+ 발굴", type="primary", use_container_width=True):
            if not kw.strip():
                st.warning("키워드를 넣어주세요.")
            else:
                with st.spinner("YouTube 조회수순 검색 중..."):
                    try:
                        res = V.search_hits(kw, video_type=vtype, period_days=period,
                                            max_results=maxr)
                    except Exception as e:      # noqa: BLE001
                        res = None
                        st.error(f"검색 실패: {e}")
                if res:
                    if res["demo"]:
                        st.info("⚠️ YouTube 키가 없어 **데모 데이터**로 보여줍니다. "
                                "실제 검색은 ⚙️ 설정에서 키를 넣으세요.")
                    st.success(f"검색 {res['raw']}개 중 **1만+ {len(res['hits'])}개** "
                               f"통과 · {res['dropped']}개는 1만 미만이라 버림")
                    st.session_state["hits"] = res["hits"]
                    st.session_state["hits_src"] = kw

    elif mode == "🔗 링크 직접 추가":
        st.caption("분석할 영상/채널 링크를 한 줄에 하나씩 붙여넣으세요. **영상 링크**는 그 영상만, "
                   "**채널 링크(@핸들 등)**는 그 채널 인기영상을 가져옵니다. (1만+ 만 남깁니다)")
        links = st.text_area(
            "유튜브 링크 (한 줄에 하나)", height=150,
            placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX\n"
                        "https://youtu.be/XXXXXXXXXXX\n"
                        "https://www.youtube.com/@채널핸들")
        if st.button("🔗 링크에서 1만+ 가져오기", type="primary", use_container_width=True):
            if not links.strip():
                st.warning("링크를 하나 이상 넣어주세요.")
            else:
                with st.spinner("링크에서 영상 정보를 가져오는 중..."):
                    try:
                        res = V.add_from_links(links)
                    except Exception as e:      # noqa: BLE001
                        res = None
                        st.error(f"불러오기 실패: {e}")
                if res is not None:
                    if res["raw"] == 0:
                        st.warning("링크에서 영상을 못 찾았습니다. 유튜브 영상/채널 주소가 맞는지 확인해 주세요.")
                    else:
                        if res["demo"]:
                            st.info("⚠️ YouTube 키가 없어 **데모**로 보여줍니다(썸네일은 실제, 조회수는 임의). "
                                    "실제 수치는 ⚙️ 설정에서 키를 넣으세요.")
                        st.success(f"영상링크 {res['video_ids']}개 + 채널 {res['channels']}개 → "
                                   f"**1만+ {len(res['hits'])}개** 통과 · {res['dropped']}개는 1만 미만이라 제외")
                        if res["hits"]:
                            st.session_state["hits"] = res["hits"]
                            st.session_state["hits_src"] = "링크 직접 추가"
                        else:
                            st.warning("가져온 영상 중 1만+ 가 없습니다.")

    else:  # 캡처 붙여넣기
        st.caption("이미 1만+ 로 확인한 인기 썸네일 캡처와 제목을 직접 넣으면, 그 이미지를 "
                   "GPT 가 직접 보고(👁Vision) 분석합니다. (선별=정밀)")
        ups = st.file_uploader("썸네일 이미지(여러 장)", type=["png", "jpg", "jpeg", "webp"],
                               accept_multiple_files=True)
        titles_txt = st.text_area("제목(한 줄에 하나, 이미지 순서와 맞추면 좋음)", height=140,
                                  placeholder="새벽 감성 재즈 플레이리스트 🌙\n비 오는 날 카페 보사노바\n...")
        if st.button("📎 이 캡처로 분석", type="primary", use_container_width=True):
            titles = [t.strip() for t in titles_txt.splitlines() if t.strip()]
            hits = []
            for i, f in enumerate(ups or []):
                mime = f.type or "image/png"
                b64 = base64.b64encode(f.read()).decode()
                hits.append({
                    "video_id": f"upload-{i}",
                    "title": titles[i] if i < len(titles) else "",
                    "thumb": f"data:{mime};base64,{b64}",
                    "views": V.MIN_VIEWS,   # 사용자가 1만+ 로 선별한 것으로 간주
                    "published_at": "",
                })
            # 이미지 없이 제목만 넣은 경우도 허용
            for j, t in enumerate(titles[len(hits):], start=len(hits)):
                hits.append({"video_id": f"title-{j}", "title": t, "thumb": "",
                             "views": V.MIN_VIEWS, "published_at": ""})
            if not hits:
                st.warning("썸네일 캡처 또는 제목을 하나 이상 넣어주세요.")
            else:
                st.session_state["hits"] = [V.normalize(h) for h in hits]
                st.session_state["hits_src"] = "내 캡처"
                st.success(f"{len(hits)}개를 1만+ 표본으로 등록했습니다.")

    # ── 분석 결과 ──
    hits = st.session_state.get("hits")
    if hits:
        st.divider()
        ana = V.analyze_hits(hits)
        m1, m2, m3 = st.columns(3)
        m1.metric("1만+ 표본", f"{ana['n']}개")
        m2.metric("중앙 조회수", f"{ana['median_views']:,}")
        m3.metric("평균 제목길이", f"{int(ana['agg'].get('avg_length', 0))}자")
        st.markdown(f"**🏆 제목 승리 공식** — {ana['formula']}")

        # 🖼️ 한눈에 보기 — 썸네일 + 제목(전체) + 조회수·배수·순위 (제일 먼저 크게)
        st.markdown(f"**🖼️ 한눈에 보기 — 1만+ 썸네일·제목 ({ana['n']}개, 조회수순)**")
        _show = ana["top"][:30]
        for _i in range(0, len(_show), 3):
            _cols = st.columns(3)
            for _j, _h in enumerate(_show[_i:_i + 3]):
                with _cols[_j]:
                    if _h.get("thumb"):
                        st.image(_h["thumb"], use_container_width=True)
                    _mult = f" · {_h['multiplier']}배" if _h.get("multiplier") else ""
                    st.markdown(f"**#{_i + _j + 1} · {_h['views']:,}회**{_mult}")
                    st.caption(_h["title"])
        if ana["n"] > len(_show):
            st.caption(f"…외 {ana['n'] - len(_show)}개 더 (조회수 상위 {len(_show)}개만 표시)")
        with st.expander("📋 제목만 모아보기 (복사용)"):
            st.code("\n".join(f"{h['views']:,}\t{h['title']}" for h in ana["top"]),
                    language=None)

        agg = ana["agg"]
        # 📊 정량 키워드 분석 (무료·항상)
        st.markdown("**📊 키워드 분석 (빈도)**")
        for label, val in V.keyword_summary(agg):
            st.caption(f"**{label}** — {val}")

        # 🔬 키워드·뉘앙스 심층 분석 (GPT/Gemini) — 정성·뉘앙스
        st.markdown("**🔬 키워드·뉘앙스 심층 분석**")
        can_llm = CM is not None and (_openai or bool(os.environ.get("GEMINI_API_KEY", "").strip()))
        if can_llm:
            if st.button("🔬 GPT 로 키워드·뉘앙스 뽑기", use_container_width=True):
                with st.spinner("제목들의 톤·말투·암시·감정 트리거를 분석하는 중..."):
                    st.session_state["nuance"] = CM.analyze_titles_nuance(
                        [h["title"] for h in ana["top"] if h.get("title")],
                        vision_text=st.session_state.get("vision", ""))
        else:
            st.caption("뉘앙스 분석은 OpenAI 또는 Gemini 키가 필요합니다(⚙️ 설정).")

        nz = st.session_state.get("nuance")
        if nz and isinstance(nz.get("result"), dict):
            r = nz["result"]
            with st.container(border=True):
                if r.get("overall_nuance"):
                    st.markdown("**🎭 전체 뉘앙스** — " + str(r["overall_nuance"]))
                if r.get("tone_words"):
                    st.caption("톤: " + " · ".join(map(str, r["tone_words"])))
                if r.get("power_words"):
                    st.caption("💥 파워워드: " + " · ".join(map(str, r["power_words"])))
                if r.get("emotional_triggers"):
                    st.caption("❤️ 감정 트리거: " + " · ".join(map(str, r["emotional_triggers"])))
                for g in (r.get("keyword_groups") or [])[:6]:
                    if isinstance(g, dict):
                        st.markdown(f"- **{g.get('label', '')}**: "
                                    f"{' · '.join(map(str, g.get('words', [])))}  \n"
                                    f"  ↳ {g.get('why', '')}")
                if r.get("nuance_notes"):
                    st.markdown("**미묘한 뉘앙스 포인트**")
                    for n in r["nuance_notes"][:6]:
                        st.markdown("- " + str(n))
                if r.get("title_structure"):
                    st.caption("🧱 제목 구조: " + str(r["title_structure"]))
                cda, cdb = st.columns(2)
                if r.get("dos"):
                    cda.markdown("**✅ 살릴 것**\n\n" + "\n".join("- " + str(x) for x in r["dos"][:5]))
                if r.get("donts"):
                    cdb.markdown("**🚫 피할 것**\n\n" + "\n".join("- " + str(x) for x in r["donts"][:4]))
            st.caption("→ 이 뉘앙스·파워워드는 **✨ 생성** 시 자동으로 반영됩니다.")
        elif nz and nz.get("markdown"):
            st.write(nz["markdown"])

        # 👁 GPT Vision 실측(썸네일 이미지 존재 시)
        if CM is not None and _openai:
            thumbs = [h["thumb"] for h in ana["top"] if h.get("thumb")]
            if thumbs and st.button("👁 GPT Vision 으로 썸네일 실측 분석", use_container_width=True):
                with st.spinner("GPT-4o Vision 이 썸네일을 직접 보는 중..."):
                    vis = CM.analyze_thumbnails_vision(
                        thumbs[:9], [h["title"] for h in ana["top"][:9]])
                if vis:
                    st.session_state["vision"] = vis
        if st.session_state.get("vision"):
            with st.container(border=True):
                st.markdown("**👁 GPT Vision 실측 — 1만+ 썸네일 공통 패턴**")
                st.write(st.session_state["vision"])

        st.info("→ 이 표본을 근거로 **✨ 생성** 탭에서 새 썸네일·제목을 만듭니다. "
                "같은 풍끼리 묶어 보고 조회수 갈린 이유가 궁금하면 **🧩 묶음·갈림** 탭으로.")


# ════════════════════════════════════════════════════════════
# 🧩 묶음·갈림 (같은 풍끼리 분류 + 조회수 갈린 이유 유추)
# ════════════════════════════════════════════════════════════
with tab_cluster:
    st.subheader("같은 풍끼리 묶고, 조회수 갈린 이유 찾기")
    hits = st.session_state.get("hits")
    if not hits:
        st.info("먼저 **🔎 발굴·분석** 탭에서 1만+ 표본을 만들어 주세요. "
                "(📦 수집함에서 불러와도 됩니다.)")
    else:
        clusters = V.cluster_by_style(hits)
        multi = [c for c in clusters if c["size"] >= 2]
        st.caption(f"{len(hits)}개를 **{len(clusters)}개 풍**으로 분류 "
                   f"(2개 이상 묶인 풍 {len(multi)}개 — 이런 묶음에서 갈림 원인이 보입니다).")
        for ci, c in enumerate(clusters):
            spread = f" · 최고/최저 **{c['spread']}배**" if c.get("spread") and c["size"] >= 2 else ""
            with st.expander(f"🧩 {c['label']}  ·  {c['size']}개{spread}",
                             expanded=(ci == 0 and c["size"] >= 2)):
                st.caption("승리 공식: " + c["formula"])
                grid = st.columns(3)
                for i, v in enumerate(c["videos"][:6]):
                    with grid[i % 3]:
                        if v.get("thumb"):
                            st.image(v["thumb"], use_container_width=True)
                        tag = "🥇최고" if i == 0 and c["size"] >= 2 else (
                            "🥉최저" if v is c["bottom"] and c["size"] >= 2 else "")
                        st.caption(f"**{v['views']:,}회** {tag}\n\n{v['title'][:36]}")

                if c["size"] >= 2:
                    st.markdown("**🔬 왜 갈렸나 — 정량 유추**")
                    for line in V.diff_hypotheses(c):
                        st.markdown("- " + line)

                    # 👁 시각 원인(색상·헤어·배경·표정) — GPT Vision
                    hi = [{"thumb": v.get("thumb"), "title": v.get("title"),
                           "views": v.get("views")} for v in c["videos"][:3] if v.get("thumb")]
                    lo = [{"thumb": v.get("thumb"), "title": v.get("title"),
                           "views": v.get("views")} for v in c["videos"][-3:] if v.get("thumb")]
                    vkey = f"vgap_{ci}"
                    if CM is not None and _openai and hi and lo:
                        if st.button("👁 GPT 로 시각 원인 유추 (색상·헤어·배경·표정)",
                                     key=f"vgapbtn_{ci}", use_container_width=True):
                            with st.spinner("GPT Vision 이 상·하위 썸네일을 비교하는 중..."):
                                st.session_state[vkey] = (
                                    CM.explain_view_gap_vision(hi, lo)
                                    or "이미지 비교로는 뚜렷한 차이를 못 찾았습니다.")
                        if st.session_state.get(vkey):
                            with st.container(border=True):
                                st.markdown("**👁 GPT Vision 시각 원인**")
                                st.write(st.session_state[vkey])
                    elif hi and lo and not _openai:
                        st.caption("👁 시각 원인 유추는 OpenAI 키가 필요합니다(⚙️ 설정).")


# ════════════════════════════════════════════════════════════
# ✨ 생성
# ════════════════════════════════════════════════════════════
with tab_gen:
    st.subheader("검증된 1만+ 공식으로 새 썸네일·제목 만들기")
    hits = st.session_state.get("hits")
    if not hits:
        st.info("먼저 **🔎 발굴·분석** 탭에서 1만+ 표본을 만들어 주세요.")
    elif CM is None:
        st.error("생성 엔진을 불러오지 못했습니다.")
    else:
        top = V.filter_hits(hits)[:9]
        st.caption(f"근거: 1만+ 썸네일 {len(top)}장 + 제목 {len(top)}개 "
                   f"(출처: {st.session_state.get('hits_src', '?')})")

        # 🎯 톤 선택 — 레퍼런스가 병맛이면 병맛까지 살려서, 클릭 심리 자극
        tone_keys = list(V.VIBE_TONES.keys())
        tone = st.radio(
            "톤 (레퍼런스 느낌을 어떻게 살릴까)", tone_keys, horizontal=True,
            format_func=lambda k: V.VIBE_TONES[k][0])
        intensity = st.select_slider("강도", ["약", "중", "강"], value="중")
        st.caption("🪞 레퍼런스 그대로 = 표본이 병맛이면 병맛·감성이면 감성으로 미러링 · "
                   "🤪 병맛 살려 = 날것·과장·B급 감성 밀어붙임 · 😱 더 자극적 = 충격·반전 극대화 · "
                   "🌙 감성 유지 = 무드는 지키되 클릭 심리는 확실히.")

        if st.button("✨ 새 썸네일·제목 10세트 생성", type="primary",
                     use_container_width=True):
            imgs = [h["thumb"] for h in top if h.get("thumb")]
            titles_text = "\n".join(h["title"] for h in top if h.get("title"))
            brief = V.vibe_brief(tone, intensity)
            vibe_notes = CM.build_vibe_notes(brief["tone_line"], brief["intensity_line"])
            nuance_notes = V.nuance_brief_text(st.session_state.get("nuance"))
            st.session_state["punchy"] = brief["punchy"]
            spin = f"GPT 가 1만+ 공식 + '{brief['label']}' 톤"
            spin += " + 키워드·뉘앙스" if nuance_notes else ""
            with st.spinner(spin + "으로 짜는 중..."):
                try:
                    resp = CM.generate_report(channel_urls=[], song_type="auto",
                                              num_songs=1, images=imgs,
                                              titles_text=titles_text,
                                              extra_notes=nuance_notes,
                                              vibe_notes=vibe_notes,
                                              punchy_overlay=brief["punchy"])
                except Exception as e:          # noqa: BLE001
                    resp = {"error": str(e)}
            if resp.get("error"):
                st.error(resp["error"])
            else:
                st.session_state["report"] = resp

        report = st.session_state.get("report")
        if report and isinstance(report.get("result"), dict):
            result = report["result"]
            if report.get("engine") == "demo":
                st.info("⚠️ LLM 키가 없어 **데모 결과**입니다. ⚙️ 설정에서 OpenAI 키를 넣으면 "
                        "실제 GPT 가 1만+ 공식으로 생성합니다.")
            # 컨셉 한 줄
            concept = result.get("concept") or {}
            if isinstance(concept, dict) and concept.get("headline"):
                st.markdown(f"**🎯 컨셉** — {concept.get('headline')}")
                if concept.get("keep"):
                    st.caption("유지 85%: " + str(concept.get("keep")))

            title_sets = result.get("title_sets") or []
            refs = [h["thumb"] for h in top if h.get("thumb")]
            st.markdown(f"### 🎬 썸네일·제목 {len(title_sets)}세트")
            for idx, s in enumerate(title_sets):
                if not isinstance(s, dict):
                    continue
                with st.container(border=True):
                    st.markdown(f"**{idx + 1}. {s.get('title', '')}**")
                    if s.get("thumb_text"):
                        st.caption("썸네일 문구: " + s["thumb_text"])
                    key_img = f"img_{idx}"
                    if st.session_state.get(key_img):
                        st.image(st.session_state[key_img], use_container_width=True)
                        st.download_button("⬇️ 이미지 저장", _dataurl_bytes(st.session_state[key_img]),
                                           file_name=f"thumb_{idx + 1}.png", mime="image/png",
                                           key=f"dl_{idx}")
                    prompt = s.get("full_image_prompt") or s.get("image_prompt", "")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("🎨 이 장면 그리기", key=f"gen_{idx}",
                                  use_container_width=True):
                        if not _openai:
                            st.warning("이미지 생성엔 OpenAI 키가 필요합니다(⚙️ 설정).")
                        else:
                            with st.spinner("최고화질 썸네일 생성 중(무드 이식)..."):
                                r = CM.generate_thumbnail_image(prompt, refs=refs)
                            if r.get("ok"):
                                st.session_state[key_img] = r["data_url"]
                                st.rerun()
                            else:
                                st.error(r.get("error", "생성 실패"))
                    with cc2.popover("📋 프롬프트", use_container_width=True):
                        st.code(prompt, language=None)
                        if s.get("midjourney_prompt"):
                            st.caption("미드저니용:")
                            st.code(s["midjourney_prompt"], language=None)

            # 제목 전체 복사
            all_titles = [s.get("title", "") for s in title_sets if isinstance(s, dict)]
            if all_titles:
                st.markdown("**📋 제목 10개 전체복사**")
                st.code("\n".join(all_titles), language=None)
        elif report and report.get("markdown"):
            st.markdown(report["markdown"])


# ════════════════════════════════════════════════════════════
# 📦 수집함 (무인 자동 수집)
# ════════════════════════════════════════════════════════════
with tab_store:
    st.subheader("📦 무인 자동 수집함")
    st.caption("GitHub Actions cron(`daily_viral_collect`)이 매일 자동으로 1만+ 를 쌓습니다. "
               "PC 를 켜고 `git pull` 하면 최신 수집분이 여기 보입니다.")
    store = V.load_store()
    stored = store.get("hits", [])
    if not stored:
        st.info("아직 수집된 1만+ 가 없습니다. GitHub Actions 워크플로가 돌면 채워집니다. "
                "(로컬 즉시 수집: `python daily_viral_collect.py`)")
    else:
        st.success(f"총 **{len(stored):,}개** · 마지막 갱신 {store.get('updated', '?')}")
        kws = sorted({h.get("keyword", "") for h in stored if h.get("keyword")})
        pick = st.selectbox("키워드 필터", ["(전체)"] + kws)
        rows = [h for h in stored if pick == "(전체)" or h.get("keyword") == pick]
        rows = sorted(rows, key=lambda h: h.get("views", 0), reverse=True)[:60]
        grid = st.columns(3)
        for i, h in enumerate(rows):
            with grid[i % 3]:
                if h.get("thumb"):
                    st.image(h["thumb"], use_container_width=True)
                st.caption(f"**{h.get('views', 0):,}회** · {h.get('keyword', '')}\n\n"
                           f"{h.get('title', '')[:40]}")
        if st.button("📥 이 수집함을 분석 표본으로 불러오기", use_container_width=True):
            st.session_state["hits"] = V.filter_hits(rows)
            st.session_state["hits_src"] = f"수집함:{pick}"
            st.success("불러왔습니다. 🔎/✨ 탭에서 분석·생성하세요.")


# ════════════════════════════════════════════════════════════
# ⚙️ 설정
# ════════════════════════════════════════════════════════════
with tab_set:
    st.subheader("⚙️ 연결키 저장")
    st.caption("이 PC 의 .env + keys.json 에 영구 저장. 둘 다 gitignore — 절대 업로드 안 됨.")
    st.write(f"현재 — 🎬 YouTube: **{_mask('YOUTUBE_API_KEY')}** · "
             f"🎨 OpenAI: **{_mask('OPENAI_API_KEY')}** · ✨ Gemini: **{_mask('GEMINI_API_KEY')}**")
    yk = st.text_input("YOUTUBE_API_KEY (검색·수집)", type="password",
                       placeholder="바꿀 때만 입력(빈칸=유지)")
    ok = st.text_input("OPENAI_API_KEY (GPT·Vision·이미지생성)", type="password",
                       placeholder="바꿀 때만 입력(빈칸=유지)")
    gk = st.text_input("GEMINI_API_KEY (선택)", type="password",
                       placeholder="바꿀 때만 입력(빈칸=유지)")
    if st.button("💾 저장", type="primary"):
        if not (yk.strip() or ok.strip() or gk.strip()):
            st.warning("최소 하나는 입력하세요.")
        else:
            _save_keys({"YOUTUBE_API_KEY": yk, "OPENAI_API_KEY": ok, "GEMINI_API_KEY": gk})
            st.success("저장 완료 — 재시작 없이 바로 적용됩니다.")
            st.rerun()
