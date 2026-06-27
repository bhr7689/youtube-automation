"""🎤 가사 자동 생성기 — 모바일 세로 우선 단일 페이지 Streamlit 앱.

장르 + 길이 + (선택) 주제 → Gemini → N개 가사 변주.
엔진은 lyrics_generator.py 재사용.

실행: streamlit run lyrics_app.py
"""

from __future__ import annotations

import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from lyrics_generator import DURATION_PRESETS, generate_lyrics


# ────────────────────────────────────────────────────────────────────────────
# Suno 변환 — 가사를 Suno가 가장 잘 인식하는 표준 포맷으로 정리
# ────────────────────────────────────────────────────────────────────────────
SUNO_SECTION_MAP = {
    "intro": "Intro",
    "verse 1": "Verse 1",
    "verse 2": "Verse 2",
    "verse 3": "Verse 3",
    "verse 4": "Verse 4",
    "verse 5": "Verse 5",
    "verse 6": "Verse 6",
    "verse": "Verse",
    "pre-chorus": "Pre-Chorus",
    "prechorus": "Pre-Chorus",
    "chorus": "Chorus",
    "bridge": "Bridge",
    "outro": "Outro",
    "hook": "Hook",
}


def to_suno_lyrics(sections: list[dict], fallback_text: str = "") -> str:
    """sections → Suno 표준 태그 포맷 텍스트.

    [Verse 1] / [Chorus] / [Bridge] / [Outro] 같이 첫 글자 대문자.
    섹션 태그 한 줄 + 가사 본문 줄 + 빈 줄 패턴.
    """
    if not sections:
        return fallback_text
    blocks: list[str] = []
    for sec in sections:
        raw_label = str(sec.get("section", "")).strip().lower()
        label = SUNO_SECTION_MAP.get(raw_label, raw_label.title() if raw_label else "")
        lines = [str(l).strip() for l in (sec.get("lines") or []) if str(l).strip()]
        if not lines:
            continue
        body = "\n".join(lines)
        blocks.append(f"[{label}]\n{body}" if label else body)
    return "\n\n".join(blocks) if blocks else fallback_text

load_dotenv()

# ────────────────────────────────────────────────────────────────────────────
# 페이지 설정 — 모바일 세로 우선
# ────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="가사 자동 생성기",
    page_icon="🎤",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# 모바일 친화 CSS — 큰 글씨, 큰 버튼, 카드 강조
st.markdown(
    """
    <style>
    /* 전체 폰트 키우기 */
    html, body, [class*="css"]  {
        font-size: 17px;
    }
    /* 메인 컨테이너 좁게(모바일 세로) */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 5rem;
        max-width: 720px;
    }
    /* 큰 버튼 */
    .stButton > button {
        width: 100%;
        height: 3.2rem;
        font-size: 1.15rem;
        font-weight: 700;
        border-radius: 14px;
    }
    /* 라디오 옵션 크게 */
    div[role="radiogroup"] label {
        font-size: 1.05rem !important;
        padding: 0.4rem 0;
    }
    /* 결과 카드 */
    .lyric-card {
        background: linear-gradient(135deg, #fff5f0 0%, #fff 100%);
        border: 1px solid #ffd9c4;
        border-radius: 16px;
        padding: 1.2rem 1.2rem 1rem;
        margin: 1rem 0;
        box-shadow: 0 2px 12px rgba(255, 140, 90, 0.08);
    }
    .lyric-title {
        font-size: 1.4rem;
        font-weight: 800;
        color: #c2410c;
        margin-bottom: 0.2rem;
    }
    .lyric-theme {
        font-size: 0.95rem;
        color: #78716c;
        margin-bottom: 0.8rem;
    }
    /* 입력 라벨 키우기 */
    label[data-testid="stWidgetLabel"] p {
        font-size: 1.05rem !important;
        font-weight: 600;
    }
    /* 푸터 */
    .footer-note {
        text-align: center;
        color: #a8a29e;
        font-size: 0.85rem;
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid #f5f5f4;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ────────────────────────────────────────────────────────────────────────────
# 장르 → 페르소나(작사가 화법) 자동 매핑
# ────────────────────────────────────────────────────────────────────────────
GENRE_PERSONAS: dict[str, dict] = {
    "트로트 (5070 감성)": {
        "emoji": "🌾",
        "persona": (
            "당신은 한국 5070 세대를 위한 트로트 작사가입니다. "
            "회상과 그리움을 1인칭으로 잔잔하게 그리고, "
            "어머니·고향·계절·세월의 이미지를 즐겨 씁니다. "
            "어미는 '~네', '~구나', '~던가요'를 자주 사용하고, "
            "한 줄은 짧고 운율이 살아 있게."
        ),
        "suno_style": (
            "Korean trot, nostalgic, mid-tempo 90 BPM, "
            "warm female vocal in her 40s, gentle vibrato, "
            "accordion and slow strings, soft brushed drums, "
            "emotional, melancholic, traditional Korean ballad feel"
        ),
    },
    "트로트 (흥겨운 인생찬가)": {
        "emoji": "🍶",
        "persona": (
            "당신은 흥겨운 트로트 작사가입니다. "
            "인생 한바탕, 한 잔 술, 친구·동무·노래를 신명나게 부릅니다. "
            "어미는 '~세', '~자', '~다네'를 자주 사용하고, "
            "후렴은 누구나 따라 부를 수 있는 짧고 강한 후크."
        ),
        "suno_style": (
            "Korean upbeat trot, festive, 130 BPM, "
            "bright male vocal with cheerful energy, "
            "lively accordion, electric organ, marching drums, "
            "celebratory, sing-along chorus, party mood"
        ),
    },
    "발라드": {
        "emoji": "🌙",
        "persona": (
            "당신은 한국 발라드 작사가입니다. "
            "이별·후회·기다림을 도시의 밤·비·창가의 풍경과 함께 그립니다. "
            "1인칭 시점, 잔잔하지만 후렴에서 정서가 한 번 터지는 구조. "
            "어미는 '~잖아요', '~겠지', '~던 날'을 자주 씁니다."
        ),
        "suno_style": (
            "Korean ballad, slow tempo 70 BPM, "
            "emotional male vocal, soft piano intro, "
            "lush strings building into powerful chorus, "
            "rainy night atmosphere, melancholic, cinematic"
        ),
    },
    "K-POP (청춘 설렘)": {
        "emoji": "💗",
        "persona": (
            "당신은 K-POP 작사가입니다. "
            "청춘의 설렘·첫 만남·계절의 변화를 도시적이고 산뜻하게 씁니다. "
            "리듬감 있는 한국어 + 한두 단어의 영어(Baby, Yeah, Oh 등) 허용. "
            "후렴은 짧고 반복 가능한 후크 라인."
        ),
        "suno_style": (
            "K-pop, modern, 115 BPM, "
            "young female vocal, bright synths, plucky guitar, "
            "punchy drum machine, sparkly pre-chorus, "
            "catchy hook, summery, fresh, polished pop production"
        ),
    },
    "포크/뉴트로 (7080)": {
        "emoji": "📻",
        "persona": (
            "당신은 7080 포크 작사가입니다. "
            "통기타 한 대와 함께 부르는 듯한 자연스러운 어조. "
            "추억의 거리·낡은 의자·노란 가로등 같은 따뜻한 이미지. "
            "어미는 '~었지', '~했었네', '~던 그 시절'."
        ),
        "suno_style": (
            "Korean 70s 80s folk, acoustic guitar driven, 95 BPM, "
            "warm male vocal, simple fingerpicking, harmonica accents, "
            "vintage tape warmth, nostalgic, intimate coffeehouse feel"
        ),
    },
}

# ────────────────────────────────────────────────────────────────────────────
# 헤더
# ────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style="text-align:center; padding: 0.5rem 0 1.5rem;">
        <div style="font-size: 2.2rem; font-weight: 900; color: #1f2937;">
            🎤 가사 자동 생성기
        </div>
        <div style="font-size: 1rem; color: #78716c; margin-top: 0.3rem;">
            장르 고르고 · 길이 정하면 · 가사가 완성돼요
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ────────────────────────────────────────────────────────────────────────────
# API 키 (사이드바)
# ────────────────────────────────────────────────────────────────────────────
default_key = os.getenv("GEMINI_API_KEY", "")
if "gemini_key" not in st.session_state:
    st.session_state["gemini_key"] = default_key

with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.text_input(
        "Gemini API 키",
        type="password",
        key="gemini_key",
        help="Google AI Studio에서 발급. 입력값은 이 세션 메모리에만 보관됩니다.",
        placeholder="AIza... 형식",
    )
    st.caption(
        "키가 없으면 [Google AI Studio](https://aistudio.google.com/app/apikey)에서 무료 발급."
    )
    st.markdown("---")
    st.markdown(
        """
        **이용약관 / 개인정보**

        - 본 앱은 **입력값/결과를 저장하지 않습니다.**
        - API 키는 브라우저 세션 메모리에만 잠시 보관됩니다.
        - 생성된 가사의 저작권은 사용자에게 있으며,
          상업적 활용 시 사용자가 직접 검토해 주세요.
        """
    )

# ────────────────────────────────────────────────────────────────────────────
# 입력 폼 — 장르 + 길이 (메인)
# ────────────────────────────────────────────────────────────────────────────
st.markdown("#### 1️⃣ 장르 고르기")
genre_labels = [f"{v['emoji']}  {k}" for k, v in GENRE_PERSONAS.items()]
genre_keys = list(GENRE_PERSONAS.keys())
genre_label = st.radio(
    label="장르",
    options=genre_labels,
    label_visibility="collapsed",
    index=0,
)
genre = genre_keys[genre_labels.index(genre_label)]

st.markdown("#### 2️⃣ 곡 길이 고르기")
duration_options = list(DURATION_PRESETS.keys())
duration_labels = [DURATION_PRESETS[d]["label"] for d in duration_options]
duration_label = st.radio(
    label="길이",
    options=duration_labels,
    label_visibility="collapsed",
    index=duration_labels.index("4분 (긴 트로트)") if "4분 (긴 트로트)" in duration_labels else 3,
)
duration_sec = duration_options[duration_labels.index(duration_label)]

st.markdown("#### 3️⃣ 주제 (선택)")
theme = st.text_input(
    label="주제",
    placeholder="예) 시골에 두고 온 어머니, 첫사랑의 가을, 한 잔 술…",
    label_visibility="collapsed",
)

st.markdown("#### 4️⃣ 몇 곡 만들까요?")
n_variants = st.radio(
    "개수",
    options=[1, 2, 3],
    horizontal=True,
    label_visibility="collapsed",
    index=1,
)

st.markdown("")  # 여백
go = st.button("✨ 가사 만들기", type="primary", use_container_width=True)

# ────────────────────────────────────────────────────────────────────────────
# 생성
# ────────────────────────────────────────────────────────────────────────────
if go:
    api_key = (st.session_state.get("gemini_key") or "").strip()
    if not api_key:
        st.error(
            "🔑 Gemini API 키를 사이드바(좌측 상단 `>` 클릭)에서 먼저 입력해 주세요.\n\n"
            "[여기서 무료로 발급](https://aistudio.google.com/app/apikey)할 수 있어요."
        )
        st.stop()

    persona = GENRE_PERSONAS[genre]["persona"]

    with st.spinner(f"🎵 {genre} · {duration_label} · {n_variants}곡 만드는 중… (10~30초)"):
        try:
            variants = generate_lyrics(
                persona=persona,
                duration_sec=duration_sec,
                n=int(n_variants),
                theme=theme,
                genre=genre,
                api_key=api_key,
            )
        except Exception as e:  # noqa: BLE001 — 사용자에게 친근한 메시지
            st.error(
                f"가사를 만들지 못했어요. 잠시 후 다시 시도해 주세요.\n\n"
                f"**원인:** `{type(e).__name__}: {e}`"
            )
            st.stop()

    if not variants:
        st.warning("결과가 비어 있어요. 주제를 조금 다르게 적고 다시 시도해 보세요.")
        st.stop()

    st.success(f"🎉 {len(variants)}곡 완성!  아래 3개 박스를 그대로 **수노(Suno)**에 붙여넣으면 끝이에요.")

    with st.expander("📖 수노에 붙여넣는 방법 (펼쳐 보기)", expanded=False):
        st.markdown(
            """
            1. [suno.com](https://suno.com) 접속 → **Create** 클릭
            2. 우측 상단 **Custom** 모드 켜기 (필수!)
            3. 아래 3개 박스를 **각각 복사해서 붙여넣기**:
               - **🎨 Style of Music** ← 스타일 박스
               - **📝 Lyrics** ← 가사 박스
               - **📛 Title** ← 제목 박스
            4. **Create** 버튼 누르면 약 1~2분 뒤 곡이 완성돼요.

            💡 **팁:** 각 박스 우측 상단의 📋 아이콘을 누르면 한 번에 복사돼요.
            """
        )

    suno_style = GENRE_PERSONAS[genre]["suno_style"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, v in enumerate(variants, 1):
        title = v.get("title") or f"가사 {i}"
        v_theme = v.get("theme") or ""
        sections = v.get("sections") or []
        suno_lyrics = to_suno_lyrics(sections, fallback_text=v.get("lyrics_text") or "")

        st.markdown(
            f"""
            <div class="lyric-card">
                <div class="lyric-title">{i}. {title}</div>
                <div class="lyric-theme">🎯 {v_theme}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("**📛 제목 (Suno → Title)**")
        st.code(title, language="text")

        st.markdown("**🎨 스타일 (Suno → Style of Music)**")
        st.code(suno_style, language="text")

        st.markdown("**📝 가사 (Suno → Lyrics)**")
        st.code(suno_lyrics, language="text")

        # 통합 TXT — 한 파일로 백업
        bundle = (
            f"=== TITLE ===\n{title}\n\n"
            f"=== STYLE OF MUSIC ===\n{suno_style}\n\n"
            f"=== LYRICS ===\n{suno_lyrics}\n"
        )
        st.download_button(
            label=f"⬇️ 전체 TXT 백업 다운로드  ({title})",
            data=bundle.encode("utf-8"),
            file_name=f"suno_{i}_{title}_{timestamp}.txt",
            mime="text/plain",
            key=f"dl_{i}",
            use_container_width=True,
        )
        st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# 푸터
# ────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="footer-note">
        🎵 가사 자동 생성기 · 입력값과 결과는 저장되지 않습니다 · Gemini 기반
    </div>
    """,
    unsafe_allow_html=True,
)
