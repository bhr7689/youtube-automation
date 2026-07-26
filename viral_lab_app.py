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
import viral_folders as F
import viral_channels as VC

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


# ── ✨ 생성 UI (분석 탭 아래에 바로 붙일 수 있게 함수로) ──────
def render_generation(top: list, src: str, kp: str) -> None:
    """분석 표본(top) 기반 톤 선택 + 생성 + 결과. kp=위젯/세션 키 접두사(위치마다 다르게)."""
    if not top:
        return
    if CM is None:
        st.error("생성 엔진을 불러오지 못했습니다.")
        return
    st.caption(f"근거: 1만+ 썸네일 {len([h for h in top if h.get('thumb')])}장 + "
               f"제목 {len([h for h in top if h.get('title')])}개 (출처: {src})")
    tone_keys = list(V.VIBE_TONES.keys())
    tone = st.radio("톤 (레퍼런스 느낌을 어떻게 살릴까)", tone_keys, horizontal=True,
                    format_func=lambda k: V.VIBE_TONES[k][0], key=f"tone_{kp}")
    intensity = st.select_slider("강도", ["약", "중", "강"], value="중", key=f"inten_{kp}")
    st.caption("🪞 레퍼런스 그대로 = 표본이 병맛이면 병맛·감성이면 감성으로 미러링 · "
               "🤪 병맛 살려 = 날것·과장·B급 · 😱 더 자극적 = 충격·반전 · 🌙 감성 유지.")
    rk = f"report_{kp}"
    if st.button("✨ 새 썸네일·제목 10세트 생성", type="primary",
                 use_container_width=True, key=f"go_{kp}"):
        imgs = [h["thumb"] for h in top if h.get("thumb")]
        titles_text = "\n".join(h["title"] for h in top if h.get("title"))
        brief = V.vibe_brief(tone, intensity)
        vibe_notes = CM.build_vibe_notes(brief["tone_line"], brief["intensity_line"])
        nuance_notes = V.nuance_brief_text(st.session_state.get("nuance"))
        spin = f"GPT 가 1만+ 공식 + '{brief['label']}' 톤"
        spin += " + 키워드·뉘앙스" if nuance_notes else ""
        with st.spinner(spin + "으로 짜는 중..."):
            try:
                resp = CM.generate_report(channel_urls=[], song_type="auto", num_songs=1,
                                          images=imgs, titles_text=titles_text,
                                          extra_notes=nuance_notes, vibe_notes=vibe_notes,
                                          punchy_overlay=brief["punchy"])
            except Exception as e:              # noqa: BLE001
                resp = {"error": str(e)}
        if resp.get("error"):
            st.error(resp["error"])
        else:
            st.session_state[rk] = resp

    report = st.session_state.get(rk)
    if report and report.get("engine") == "demo":
        _has = bool(os.environ.get("OPENAI_API_KEY", "").strip()
                    or os.environ.get("GEMINI_API_KEY", "").strip())
        if _has:
            st.error(
                "⚠️ **키는 감지됐는데 생성 응답이 비었습니다.** (키가 없는 게 아니에요.)\n\n"
                "가능한 원인: ① 키에 오타·앞뒤 공백 · ② **OpenAI 계정에 결제/크레딧이 없음**"
                "(가장 흔함) · ③ 네트워크·프록시 문제. → **⚙️ 설정**에서 키를 다시 저장하거나 "
                "OpenAI 결제 상태(platform.openai.com → Billing)를 확인해 주세요.")
        else:
            st.error(
                "⚠️ **이 앱에 OpenAI(또는 Gemini) 키가 없습니다.** ⚙️ 설정 탭에서 넣어주세요.\n\n"
                "키가 없으면 링크와 **무관한 고정 예시(밤·재즈 등)**만 나와요. 다른 앱에서 "
                "저장했어도 같은 PC면 보통 공유되지만, 안 보이면 여기 ⚙️ 설정에서 한 번 더 저장하세요.")
    elif report and isinstance(report.get("result"), dict):
        result = report["result"]
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
                key_img = f"img_{kp}_{idx}"
                if st.session_state.get(key_img):
                    st.image(st.session_state[key_img], use_container_width=True)
                    st.download_button("⬇️ 이미지 저장", _dataurl_bytes(st.session_state[key_img]),
                                       file_name=f"thumb_{idx + 1}.png", mime="image/png",
                                       key=f"dl_{kp}_{idx}")
                prompt = s.get("full_image_prompt") or s.get("image_prompt", "")
                cc1, cc2 = st.columns(2)
                if cc1.button("🎨 이 장면 그리기", key=f"gen_{kp}_{idx}",
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
        all_titles = [s.get("title", "") for s in title_sets if isinstance(s, dict)]
        if all_titles:
            st.markdown("**📋 제목 10개 전체복사**")
            st.code("\n".join(all_titles), language=None)
    elif report and report.get("markdown"):
        st.markdown(report["markdown"])


_alert_n = VC.alert_count()
_alarm_label = f"🔔 알림 ({_alert_n})" if _alert_n else "🔔 알림"
tab_find, tab_cluster, tab_folder, tab_alarm, tab_gen, tab_store, tab_set = st.tabs(
    ["🔎 발굴·분석", "🧩 묶음·갈림", "📁 감성 폴더", _alarm_label,
     "✨ 생성", "📦 수집함", "⚙️ 설정"])


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

        st.caption("같은 풍끼리 묶어 보고 조회수 갈린 이유가 궁금하면 **🧩 묶음·갈림** 탭으로.")

        # ✨ 바로 여기서 생성 — 아래로 스크롤하면 이 분석 기반 썸네일·제목 예시
        st.divider()
        st.markdown("## ✨ 이 분석으로 새 썸네일·제목 만들기")
        st.caption("위 분석(키워드·뉘앙스·1만+ 공식)을 그대로 반영해 만듭니다. 아래로 내려가며 확인하세요.")
        render_generation(ana["top"][:9], st.session_state.get("hits_src", "?"), "find")


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
        if multi and st.button(f"📁 2개 이상 묶인 감성 {len(multi)}개를 폴더로 한 번에 저장",
                               use_container_width=True):
            made = [F.create_folder(c["label"], c["videos"], vibe=c["label"]) for c in multi]
            st.success(f"{len(made)}개 감성 폴더를 만들었습니다. → **📁 감성 폴더** 탭에서 확인·분석하세요.")
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

                if st.button("📁 이 감성 묶음을 폴더로 저장", key=f"savef_{ci}",
                             use_container_width=True):
                    F.create_folder(c["label"], c["videos"], vibe=c["label"])
                    st.success(f"'{c['label']}' 폴더 저장 완료 → 📁 감성 폴더 탭에서 분석하세요.")

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
# 📁 감성 폴더 (비슷한 감성끼리 폴더 저장 → 폴더 안 공통점·유사도 분석)
# ════════════════════════════════════════════════════════════
with tab_folder:
    st.subheader("비슷한 감성끼리 폴더에 모아, 공통점·유사도 보기")

    # (1) 현재 표본을 감성별 폴더로 자동 제안/저장
    hits = st.session_state.get("hits")
    if hits:
        sug = F.suggest_folders(hits)
        with st.expander(f"➕ 지금 표본을 감성별 폴더로 담기 (자동 제안 {len(sug)}개)",
                         expanded=not F.list_folders()):
            if sug:
                for s in sug:
                    st.caption(f"📁 {s['name']} · {s['size']}개 — {s['formula']}")
                if st.button("이 감성 폴더들 전부 만들기", type="primary",
                             use_container_width=True):
                    for s in sug:
                        F.create_folder(s["name"], s["videos"], vibe=s["vibe"])
                    st.success(f"{len(sug)}개 폴더 생성 완료.")
                    st.rerun()
            else:
                st.caption("2개 이상 묶이는 감성이 없어요. 표본을 더 모아 보세요.")
            nm = st.text_input("또는 새 폴더 이름", placeholder="예) 새벽 감성 재즈")
            if st.button("현재 표본 전체를 새 폴더로", use_container_width=True):
                if nm.strip():
                    F.create_folder(nm, V.filter_hits(hits), vibe=nm)
                    st.success(f"'{nm}' 폴더 생성 완료.")
                    st.rerun()
                else:
                    st.warning("폴더 이름을 넣어주세요.")
    else:
        st.caption("🔎 발굴·분석에서 표본을 만들면, 감성별 폴더를 자동으로 제안해 드립니다.")

    # (2) 저장된 폴더 목록 + 폴더 안 공통점 분석
    folders = F.list_folders()
    st.divider()
    if not folders:
        st.info("아직 폴더가 없습니다. 🧩 묶음·갈림 탭의 '📁 폴더로 저장' 또는 위의 자동 제안으로 만드세요.")
    else:
        names = {f"{f['name']} ({f['size']}개)": f["id"] for f in folders}
        pick = st.selectbox("📁 폴더 선택", list(names.keys()))
        fid = names[pick]
        folder = F.get_folder(fid)
        if folder:
            cm = F.folder_common(folder)
            st.markdown(f"### 📁 {folder['name']}")
            a, b, c3 = st.columns(3)
            a.metric("영상 수", f"{cm['n']}개")
            b.metric("제목 유사도", f"{cm['similarity']}%")
            c3.metric("중앙 조회수", f"{cm['median_views']:,}")

            # 공통점 요약
            st.markdown("**🔗 이 폴더의 공통점**")
            st.caption("제목 승리 공식: " + cm["formula"])
            if cm["common_words"]:
                st.caption("공통 단어: " + " · ".join(f"{w}({n})" for w, n in cm["common_words"]))
            for label, val in cm["keywords"]:
                st.caption(f"**{label}** — {val}")

            # 👁 썸네일 공통 시각 패턴 (Vision)
            fvkey = f"fvision_{fid}"
            fthumbs = [v["thumb"] for v in cm["top"] if v.get("thumb")]
            if CM is not None and _openai and fthumbs:
                if st.button("👁 GPT Vision 으로 이 폴더 썸네일 공통점 분석",
                             key=f"fvbtn_{fid}", use_container_width=True):
                    with st.spinner("썸네일들의 공통 시각 패턴을 보는 중..."):
                        st.session_state[fvkey] = CM.analyze_thumbnails_vision(
                            fthumbs[:9], [v["title"] for v in cm["top"][:9]])
                if st.session_state.get(fvkey):
                    with st.container(border=True):
                        st.markdown("**👁 썸네일 공통 시각 패턴**")
                        st.write(st.session_state[fvkey])

            # 📺 이 폴더의 채널 — 링크 + 🔖 북마크(=새 영상 알림 + 새 1만+ 자동수집)
            chs = VC.channels_in_videos(folder["videos"])
            if chs:
                st.markdown("**📺 이 폴더의 채널** — 🔖 북마크하면 새 영상 알림 + 새 1만+ 자동수집")
                for ch in chs:
                    cc1, cc2 = st.columns([3, 1])
                    cc1.markdown(f"[{ch['title']}]({ch['url']}) · 이 폴더에 {ch['count']}개")
                    if ch["bookmarked"]:
                        if cc2.button("🔖 해제", key=f"unbm_{fid}_{ch['channel_id']}",
                                      use_container_width=True):
                            VC.unbookmark(ch["channel_id"])
                            st.rerun()
                    else:
                        if cc2.button("🔖 북마크", key=f"bm_{fid}_{ch['channel_id']}",
                                      use_container_width=True):
                            VC.bookmark(ch["channel_id"], ch["title"], ch["url"])
                            st.rerun()
                st.caption("→ 북마크한 채널은 **🔔 알림** 탭에서 새 영상·새 1만+ 를 확인하세요.")

            # 폴더 안 썸네일 + 제목 한눈에
            st.markdown("**🖼️ 폴더 안 썸네일·제목**")
            fv = cm["top"][:30]
            for i in range(0, len(fv), 3):
                cols = st.columns(3)
                for j, v in enumerate(fv[i:i + 3]):
                    with cols[j]:
                        if v.get("thumb"):
                            st.image(v["thumb"], use_container_width=True)
                        st.markdown(f"**{v['views']:,}회**")
                        st.caption(v["title"])

            c1, c2 = st.columns(2)
            if c1.button("📥 이 폴더를 분석 표본으로 불러오기", use_container_width=True):
                st.session_state["hits"] = V.filter_hits(folder["videos"])
                st.session_state["hits_src"] = f"폴더:{folder['name']}"
                st.success("불러왔습니다. 🔎/✨ 탭에서 이어가세요.")
            if c2.button("🗑️ 이 폴더 삭제", use_container_width=True):
                F.delete_folder(fid)
                st.warning("삭제했습니다.")
                st.rerun()

            # ✨ 이 폴더 분석 기반 생성 — 바로 아래로 스크롤
            st.divider()
            st.markdown("## ✨ 이 폴더 분석으로 새 썸네일·제목 만들기")
            st.caption("이 폴더의 공통점·키워드를 그대로 반영해 만듭니다. 아래로 내려가며 확인하세요.")
            render_generation(cm["top"][:9], f"폴더:{folder['name']}", f"fold_{fid}")


# ════════════════════════════════════════════════════════════
# 🔔 알림 (북마크 채널 새 영상 + 새 1만+ 자동수집)
# ════════════════════════════════════════════════════════════
with tab_alarm:
    st.subheader("북마크한 채널의 새 영상 · 새 1만+")
    bms = VC.list_channels()
    if not bms:
        st.info("아직 북마크한 채널이 없습니다. **📁 감성 폴더** 탭에서 폴더를 열면 "
                "그 안의 채널을 🔖 북마크할 수 있어요. 북마크하면 여기서 새 영상 알림과 "
                "새 1만+ 를 자동으로 챙겨드립니다.")
    else:
        st.caption(f"북마크 채널 {len(bms)}개 — 앱을 열면 자동으로 새 영상을 확인합니다.")
        # 앱 열 때 세션당 1회 자동 확인
        if not st.session_state.get("_checked"):
            with st.spinner("북마크 채널의 새 영상을 확인하는 중(RSS)..."):
                try:
                    st.session_state["_check_res"] = VC.check_new()
                except Exception as e:      # noqa: BLE001
                    st.session_state["_check_res"] = {"error": str(e)}
            st.session_state["_checked"] = True

        if st.button("🔄 지금 새 영상 확인 + 1만+ 수집", use_container_width=True):
            with st.spinner("확인하는 중..."):
                st.session_state["_check_res"] = VC.check_new()
            st.rerun()

        cr = st.session_state.get("_check_res") or {}
        if cr.get("error"):
            st.warning(f"확인 중 문제: {cr['error']}")
        elif cr:
            msg = f"채널 {cr.get('checked', 0)}개 확인 · 새 영상 {cr.get('new_alerts', 0)}건"
            if cr.get("collected"):
                msg += f" · 새 1만+ {cr['collected']}건 수집"
            st.caption(msg)
            if cr.get("need_key"):
                st.caption("⚠️ 조회수 확인(1만+ 자동수집)에는 YouTube 키가 필요합니다(⚙️ 설정). "
                           "키가 없어도 새 영상 알림은 됩니다.")

        # 북마크 채널 목록
        with st.expander(f"📺 북마크 채널 {len(bms)}개"):
            for ch in bms:
                d1, d2 = st.columns([3, 1])
                d1.markdown(f"[{ch.get('title', ch['channel_id'])}]({ch.get('url', '')})")
                if d2.button("🔖 해제", key=f"al_unbm_{ch['channel_id']}",
                             use_container_width=True):
                    VC.unbookmark(ch["channel_id"])
                    st.rerun()

        # 🔔 새 영상 알림
        al = VC.alerts()
        st.markdown(f"### 🔔 새 영상 알림 ({len(al)})")
        if not al:
            st.caption("새로 올라온 영상이 아직 없습니다. (북마크 이후 올라오는 영상부터 떠요.)")
        else:
            if st.button("🔕 알림 모두 끄기(삭제)", use_container_width=True):
                VC.clear_alerts()
                st.rerun()
            for a in al[:40]:
                with st.container(border=True):
                    g1, g2 = st.columns([1, 2])
                    with g1:
                        if a.get("thumb"):
                            st.image(a["thumb"], use_container_width=True)
                    with g2:
                        st.markdown(f"**{a.get('title', '')}**")
                        st.caption(f"{a.get('channel', '')} · {a.get('published', '')}")
                        st.markdown(f"[▶️ 영상 보기]({a.get('url', '')})")
                        if st.button("🔕 이 알림 끄기", key=f"dis_{a['video_id']}"):
                            VC.dismiss_alert(a["video_id"])
                            st.rerun()

        # 🔟 북마크 채널에서 자동수집된 1만+
        col = VC.collected_hits()
        st.markdown(f"### 🔟 북마크 채널 새 1만+ ({len(col)})")
        if not col:
            st.caption("아직 수집된 1만+ 가 없습니다. (키가 있으면 최근 영상 중 1만+ 를 자동 수집해요.)")
        else:
            grid = st.columns(3)
            for i, h in enumerate(col[:30]):
                with grid[i % 3]:
                    if h.get("thumb"):
                        st.image(h["thumb"], use_container_width=True)
                    st.caption(f"**{h.get('views', 0):,}회** · {h.get('channel_title', '')}\n\n"
                               f"{h.get('title', '')[:36]}")
            if st.button("📥 이 1만+ 를 분석 표본으로 불러오기", use_container_width=True):
                st.session_state["hits"] = V.filter_hits(col)
                st.session_state["hits_src"] = "북마크 채널 1만+"
                st.success("불러왔습니다. 🔎/✨ 탭에서 이어가세요.")


# ════════════════════════════════════════════════════════════
# ✨ 생성
# ════════════════════════════════════════════════════════════
with tab_gen:
    st.subheader("검증된 1만+ 공식으로 새 썸네일·제목 만들기")
    hits = st.session_state.get("hits")
    if not hits:
        st.info("먼저 **🔎 발굴·분석** 탭에서 1만+ 표본을 만들어 주세요. "
                "(이제 🔎 발굴·분석 / 📁 감성 폴더 탭에서도 아래로 내려가면 바로 생성됩니다.)")
    else:
        render_generation(V.filter_hits(hits)[:9],
                          st.session_state.get("hits_src", "?"), "gen")


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

    # 🔌 OpenAI 연결 테스트 — "키는 있는데 생성이 안 될 때" 진짜 원인 확인
    st.markdown("**🔌 OpenAI 연결 테스트** — 키는 있는데 생성이 안 되면 눌러 진짜 원인을 확인하세요.")
    if st.button("🔌 지금 OpenAI 연결 테스트", use_container_width=True):
        if CM is None:
            st.error("엔진을 불러오지 못했습니다.")
        else:
            with st.spinner("OpenAI 에 작은 요청을 보내는 중..."):
                res = CM.test_openai()
            if res.get("ok"):
                st.success(res["msg"])
            else:
                st.error(f"❌ {res.get('msg', '실패')}")

    # 🔍 키 진단 — "저장했는데 왜 없다지?" 를 스스로 확인
    with st.expander("🔍 키 진단 (저장했는데 안 먹힐 때 눌러보세요)"):
        _env = os.path.join(_HERE, ".env")
        st.write(f"저장 파일 위치(이 PC): `{_env}`")
        st.write(f"· `.env` 파일 있음: {'✅' if os.path.exists(_env) else '❌ 없음'} · "
                 f"`keys.json` 있음: {'✅' if os.path.exists(KEYS_JSON) else '❌ 없음'}")
        st.write(f"· 지금 감지된 키 — YouTube {'✅' if os.environ.get('YOUTUBE_API_KEY','').strip() else '❌'} · "
                 f"OpenAI {'✅' if os.environ.get('OPENAI_API_KEY','').strip() else '❌'} · "
                 f"Gemini {'✅' if os.environ.get('GEMINI_API_KEY','').strip() else '❌'}")
        st.caption(
            "· 일본쇼츠·썸네일연구소·이 앱은 **같은 PC의 같은 .env** 를 공유합니다. "
            "그래도 여기서 ❌ 면 이 앱이 그 값을 못 읽는 것이니, 위에서 **다시 저장**하세요.\n\n"
            "· OpenAI ✅ 인데도 생성에서 '응답이 비었다'가 나오면 키 문제가 아니라 "
            "**OpenAI 계정 결제/크레딧**(platform.openai.com → Billing) 이나 네트워크 문제입니다.\n\n"
            "· ⚠️ **웹 미리보기(claude.ai)** 에서 저장한 키는 그 세션에만 있고 **사장님 PC 로는 안 넘어갑니다** — "
            "키는 반드시 **사장님 PC에서 실행한 앱**의 ⚙️ 설정에 저장하세요.")
