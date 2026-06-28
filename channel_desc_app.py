"""🎬 채널 설명·해시태그 자동 생성기 — 모바일 세로 우선 단일 페이지.

흐름:
  1) 유튜브 링크(채널/영상) 입력
  2) 채널 메타 + 최근 영상 설명 N개 수집(YouTube Data API)
  3) Gemini 가 채널 브리프 + 의식의 흐름 4단 전략으로
     "구독 누르고 싶은" 설명 + 해시태그 생성
  4) 결과 카드는 모두 `st.code()` 로 → 우상단 📋 한 번에 복사

실행: streamlit run channel_desc_app.py
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

import streamlit as st
from dotenv import load_dotenv

import channel_brief as cb
import channel_desc_generator as gen


load_dotenv()

# ────────────────────────────────────────────────────────────────────────────
# 페이지 설정 — 모바일 세로 우선
# ────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="채널 설명·해시태그 생성기",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    html, body, [class*="css"] { font-size: 17px; }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 5rem;
        max-width: 720px;
    }
    .stButton > button {
        width: 100%;
        height: 3.2rem;
        font-size: 1.15rem;
        font-weight: 700;
        border-radius: 14px;
    }
    div[role="radiogroup"] label {
        font-size: 1.05rem !important;
        padding: 0.4rem 0;
    }
    label[data-testid="stWidgetLabel"] p {
        font-size: 1.05rem !important;
        font-weight: 600;
    }
    .result-card {
        background: linear-gradient(135deg, #f0f7ff 0%, #fff 100%);
        border: 1px solid #c4d9ff;
        border-radius: 16px;
        padding: 1rem 1.2rem;
        margin: 1rem 0;
        box-shadow: 0 2px 12px rgba(80, 130, 255, 0.08);
    }
    .result-title {
        font-size: 1.3rem;
        font-weight: 800;
        color: #1d4ed8;
        margin-bottom: 0.4rem;
    }
    .hook-quote {
        font-size: 1.05rem;
        color: #525252;
        font-style: italic;
        border-left: 3px solid #93c5fd;
        padding-left: 0.7rem;
        margin: 0.5rem 0 0.8rem;
    }
    .channel-meta {
        background: #f8fafc;
        border-radius: 12px;
        padding: 0.8rem 1rem;
        margin-bottom: 1rem;
        font-size: 0.95rem;
        color: #475569;
    }
    .footer-note {
        text-align: center;
        color: #a8a29e;
        font-size: 0.85rem;
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid #f5f5f4;
    }
    .brief-pill {
        display: inline-block;
        background: #fef3c7;
        color: #92400e;
        font-size: 0.85rem;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        margin-bottom: 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ────────────────────────────────────────────────────────────────────────────
# 사이드바 — 채널 브리프 편집(모든 앱이 공유하는 메모리)
# ────────────────────────────────────────────────────────────────────────────
def sidebar_brief():
    with st.sidebar:
        st.markdown("### 🎭 채널 브랜드 브리프")
        st.caption("이 메모는 가사·역설계·채널설명 등 **모든 앱이 함께 참조**합니다.")

        state = cb.load_state()
        keys = list(state["briefs"].keys())
        names = [state["briefs"][k].get("channel_name", k) for k in keys]
        labels = [f"{n} ({k})" for n, k in zip(names, keys)]

        cur_idx = keys.index(state["current"]) if state["current"] in keys else 0
        choice = st.selectbox("현재 사용 중인 브리프", labels, index=cur_idx)
        chosen_key = keys[labels.index(choice)]
        if chosen_key != state["current"]:
            cb.set_current(chosen_key)
            st.rerun()

        brief = cb.load_brief(chosen_key)

        with st.expander("✏️ 이 브리프 편집", expanded=False):
            new = deepcopy(brief)
            new["channel_name"]      = st.text_input("채널명", new.get("channel_name", ""))
            new["one_line_identity"] = st.text_area("정체성 한 줄", new.get("one_line_identity", ""), height=80)
            new["target_audience"]   = st.text_area("타깃 (누가 듣는가)", new.get("target_audience", ""), height=80)
            new["promise"]           = st.text_area("약속 (무엇을 얻는가)", new.get("promise", ""), height=80)
            new["emotional_keywords"] = [
                k.strip() for k in
                st.text_area("감정 키워드 (쉼표로 구분)",
                             ", ".join(new.get("emotional_keywords", [])),
                             height=70).split(",") if k.strip()
            ]
            new["music_keywords"] = [
                k.strip() for k in
                st.text_area("음악 키워드 (쉼표로 구분)",
                             ", ".join(new.get("music_keywords", [])),
                             height=70).split(",") if k.strip()
            ]
            new["tone_and_manner"]   = st.text_area("톤 앤 매너", new.get("tone_and_manner", ""), height=80)
            new["avoid"] = [
                k.strip() for k in
                st.text_area("절대 쓰지 말 것 (쉼표로 구분)",
                             ", ".join(new.get("avoid", [])),
                             height=60).split(",") if k.strip()
            ]
            new["signature_lines"] = [
                k.strip() for k in
                st.text_area("시그니처 문구 (쉼표로 구분)",
                             ", ".join(new.get("signature_lines", [])),
                             height=60).split(",") if k.strip()
            ]
            new["cta_style"]      = st.text_area("CTA 스타일", new.get("cta_style", ""), height=70)
            new["upload_rhythm"]  = st.text_input("발행 리듬", new.get("upload_rhythm", ""))

            if st.button("💾 이 브리프 저장", use_container_width=True):
                cb.save_brief(chosen_key, new)
                st.success("저장 완료!")
                st.rerun()

        with st.expander("➕ 새 채널 브리프 추가 / 삭제"):
            new_name = st.text_input("새 채널명")
            base_choice = st.selectbox("어떤 브리프를 복제해서 시작할까요?", ["(빈 템플릿)"] + labels)
            if st.button("➕ 새 브리프 만들기"):
                if not new_name.strip():
                    st.warning("채널명을 입력해주세요.")
                else:
                    base_key = None if base_choice == "(빈 템플릿)" else keys[labels.index(base_choice) - 1] if base_choice != "(빈 템플릿)" else None
                    if base_choice != "(빈 템플릿)":
                        base_key = keys[labels.index(base_choice)]
                    slug = "".join(c.lower() if c.isalnum() else "_" for c in new_name.strip())[:40] or "brief"
                    cb.create_brief(slug, new_name.strip(), base_key=base_key)
                    st.success(f"'{new_name}' 추가됨!")
                    st.rerun()

            if len(keys) > 1:
                del_choice = st.selectbox("삭제할 브리프", labels, key="del_brief")
                if st.button("🗑️ 삭제"):
                    del_key = keys[labels.index(del_choice)]
                    cb.delete_brief(del_key)
                    st.success("삭제 완료")
                    st.rerun()

        with st.expander("📜 LLM 이 받는 프롬프트 블록 (미리보기)"):
            st.code(cb.as_prompt_block(brief), language="markdown")

        return brief


# ────────────────────────────────────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────────────────────────────────────
def main():
    brief = sidebar_brief()

    st.title("🎬 채널 설명·해시태그 생성기")
    st.markdown(
        f"<span class='brief-pill'>현재 브리프: {brief.get('channel_name','')}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        "유튜브 링크를 주면 채널 설명을 모두 모아 분석한 후, "
        "**알고리즘 + 의식의 흐름** 으로 끌어당기는 채널 설명과 해시태그를 만들어 드려요."
    )

    # 입력
    url = st.text_input(
        "유튜브 링크 (채널 또는 영상)",
        placeholder="https://www.youtube.com/@... 또는 https://youtu.be/...",
    )

    col1, col2 = st.columns(2)
    with col1:
        n_variants = st.radio(
            "변주 개수",
            [1, 2, 3],
            index=1,
            horizontal=True,
        )
    with col2:
        length = st.radio(
            "설명 길이",
            ["짧게", "중간", "길게"],
            index=1,
            horizontal=True,
        )
    length_map = {"짧게": "short", "중간": "medium", "길게": "long"}

    max_videos = st.slider(
        "분석할 최근 영상 수 (많을수록 키워드 정확도 ↑, API 쿼터 ↑)",
        min_value=5, max_value=50, value=20, step=5,
    )

    # API 키
    yt_key = os.environ.get("YOUTUBE_API_KEY", "")
    gem_key = os.environ.get("GEMINI_API_KEY", "")
    with st.expander("🔑 API 키 (없으면 직접 입력)", expanded=not (yt_key and gem_key)):
        yt_key = st.text_input("YOUTUBE_API_KEY (필수)", value=yt_key, type="password")
        gem_key = st.text_input("GEMINI_API_KEY (필수)", value=gem_key, type="password")

    go = st.button("✨ 채널 설명·해시태그 만들기")

    if not go:
        st.markdown(
            """
            <div class='footer-note'>
            💡 결과는 모두 코드 블록으로 나와요 — 우상단 📋 아이콘을 누르면 한 번에 복사됩니다.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # 검증
    if not url.strip():
        st.error("유튜브 링크를 입력해주세요.")
        return
    if not yt_key.strip():
        st.error("YouTube API 키가 필요해요.")
        return
    if not gem_key.strip():
        st.error("Gemini API 키가 필요해요.")
        return

    # 1) 수집
    with st.spinner("유튜브 채널 정보·영상 설명을 모으는 중…"):
        try:
            payload = gen.fetch_channel_payload(yt_key.strip(), url.strip(), max_videos=max_videos)
        except Exception as e:
            st.error(f"수집 실패: {e}")
            return

    st.markdown(
        f"""
        <div class='channel-meta'>
        <b>📺 {payload.title}</b><br/>
        구독자 {payload.subscriber_count:,} · 영상 {payload.video_count} · 누적 조회 {payload.view_count:,}<br/>
        분석에 사용한 최근 영상: {len(payload.videos)}개
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2) 생성
    with st.spinner("Gemini 가 채널 설명과 해시태그를 쓰는 중…"):
        try:
            result = gen.generate(
                payload=payload,
                brief=brief,
                n_variants=int(n_variants),
                description_length=length_map[length],
                api_key=gem_key.strip(),
            )
        except Exception as e:
            st.error(f"생성 실패: {e}")
            return

    if not result["variants"]:
        st.warning("생성된 변주가 없어요. 다시 시도해주세요.")
        return

    # 3) 결과
    st.success(f"{len(result['variants'])}개 변주 생성 완료! 마음에 드는 걸 복사해서 쓰세요.")

    for i, v in enumerate(result["variants"], 1):
        st.markdown(
            f"""
            <div class='result-card'>
              <div class='result-title'>변주 {i} — {v.get('title','')}</div>
              <div class='hook-quote'>"{v.get('hook','')}"</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("📋 아래 코드 블록 우상단 아이콘으로 복사하세요.")

        st.markdown("**📝 채널 설명 본문**")
        st.code(v.get("description", ""), language="markdown")

        st.markdown("**#️⃣ 해시태그 (콤마 구분 — 그대로 복사)**")
        st.code(v.get("hashtags", ""), language="text")

        if v.get("channel_keywords"):
            st.markdown("**🔑 채널 설정 → 키워드 (YouTube Studio 검색 메타)**")
            st.code(v.get("channel_keywords", ""), language="text")

        st.markdown("---")

    if result.get("seo_summary"):
        with st.expander("🧠 왜 이 설명이 알고리즘에 강한가?", expanded=False):
            st.write(result["seo_summary"])

    # 보조 정보 — 분석 키워드/태그 빈도
    with st.expander("📊 영상 설명·태그에서 뽑힌 SEO 키워드 빈도"):
        st.markdown("**설명 키워드 상위**")
        st.code("\n".join(f"{w}\t{c}" for w, c in result["top_keywords"][:25]), language="text")
        st.markdown("**기존 영상 태그 상위**")
        st.code("\n".join(f"{t}\t{c}" for t, c in result["top_tags"][:25]), language="text")

    # 전체 백업
    backup = {
        "channel": {
            "title": payload.title,
            "subscriber_count": payload.subscriber_count,
            "video_count": payload.video_count,
            "url": url.strip(),
        },
        "brief": brief.get("channel_name"),
        "variants": result["variants"],
        "seo_summary": result.get("seo_summary"),
    }
    st.download_button(
        "💾 전체 결과 JSON 백업",
        data=json.dumps(backup, ensure_ascii=False, indent=2),
        file_name=f"channel_desc_{payload.title or 'result'}.json",
        mime="application/json",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
