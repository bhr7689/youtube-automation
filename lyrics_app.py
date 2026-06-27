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
import daily_signature as ds
import nation_prompts as np


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


# ────────────────────────────────────────────────────────────────────────────
# 다국어 — 언어별 Suno 스타일 키워드 매핑
# ────────────────────────────────────────────────────────────────────────────
LANGUAGES: dict[str, dict] = {
    "한국어":              {"flag": "🇰🇷", "english": "Korean",                     "style_hint": "Korean"},
    "영어":                {"flag": "🇺🇸", "english": "English",                    "style_hint": "Western pop"},
    "일본어":              {"flag": "🇯🇵", "english": "Japanese",                   "style_hint": "J-pop / Japanese enka"},
    "대만식 중국어 (번체)": {"flag": "🇹🇼", "english": "Traditional Chinese (Taiwan)", "style_hint": "Mandopop"},
    "멕시코식 스페인어":    {"flag": "🇲🇽", "english": "Mexican Spanish",             "style_hint": "Mexican ranchera / Latin"},
    "스페인어 (스페인)":    {"flag": "🇪🇸", "english": "Spanish (Spain)",             "style_hint": "Spanish flamenco-pop"},
    "프랑스어":            {"flag": "🇫🇷", "english": "French",                     "style_hint": "French chanson"},
    "힌디어 (인도)":        {"flag": "🇮🇳", "english": "Hindi",                      "style_hint": "Bollywood"},
    "베트남어":            {"flag": "🇻🇳", "english": "Vietnamese",                 "style_hint": "V-pop / Vietnamese bolero"},
    "인도네시아어":        {"flag": "🇮🇩", "english": "Indonesian",                  "style_hint": "Indonesian dangdut-pop"},
    "태국어":              {"flag": "🇹🇭", "english": "Thai",                       "style_hint": "Thai luk thung-pop"},
    "포르투갈어 (브라질)":  {"flag": "🇧🇷", "english": "Brazilian Portuguese",        "style_hint": "Brazilian MPB / sertanejo"},
}


# 장르의 base Suno 스타일에서 'Korean / K-pop' 같은 한국 식별자를
# 선택한 언어/지역 스타일로 교체. 마지막에 'sung in {english}' 명시.
_GENRE_LOCALIZE_RULES = [
    ("Korean upbeat trot", "{hint} upbeat folk-pop"),
    ("Korean trot",         "{hint} ballad with trot rhythm"),
    ("Korean ballad",       "{hint} ballad"),
    ("Korean 70s 80s folk", "{hint} 70s 80s folk"),
    ("K-pop",               "{hint}-influenced pop"),
    ("traditional Korean ballad feel", "traditional {english} ballad feel"),
]


def build_suno_style(genre_key: str, language: str) -> str:
    """장르 base style + 언어 → 언어/지역에 맞춰진 Suno 스타일 프롬프트."""
    base = GENRE_PERSONAS[genre_key]["suno_style"]
    if language == "한국어" or language not in LANGUAGES:
        return base
    hint = LANGUAGES[language]["style_hint"]
    english = LANGUAGES[language]["english"]
    adapted = base
    for needle, repl in _GENRE_LOCALIZE_RULES:
        adapted = adapted.replace(needle, repl.format(hint=hint, english=english))
    return f"{adapted}, sung in {english}, {english} lyrics"


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
    # ── 🎭 시리즈 전환 (여러 시그니처 보관 + 시즌 운영) ───────────────
    st.markdown("### 🎭 시리즈")
    sig_data = ds.load_signatures()
    series_list = ds.list_series()  # [(id, name, day_count), ...]
    series_ids = [s[0] for s in series_list]
    series_labels = [f"{s[1]}  ·  Day {s[2]}" for s in series_list]
    current_id = sig_data.get("current", series_ids[0])
    current_idx = series_ids.index(current_id) if current_id in series_ids else 0

    selected_label = st.selectbox(
        "현재 시리즈",
        options=series_labels,
        index=current_idx,
        key="series_select",
    )
    selected_id = series_ids[series_labels.index(selected_label)]
    if selected_id != current_id:
        ds.set_current(selected_id)
        st.rerun()

    with st.expander("➕ 새 시리즈 / 🗑️ 삭제", expanded=False):
        new_name = st.text_input(
            "새 시리즈 이름",
            placeholder="예: Autumn Train, Bollywood Monsoon",
            key="new_series_name",
        )
        copy_from_current = st.checkbox(
            "현재 시그니처 복제해서 시작",
            value=True,
            help="체크하면 현재 시그니처의 모든 설정을 가져와서 시작 (이름·날짜·카운트만 새로).",
        )
        if st.button("➕ 시리즈 만들기", use_container_width=True):
            if not new_name.strip():
                st.warning("시리즈 이름을 입력해 주세요.")
            else:
                try:
                    new_id = ds.create_series(
                        new_name.strip(),
                        base_series_id=selected_id if copy_from_current else None,
                    )
                    st.success(f"'{new_name}' 생성 + 현재 시리즈로 전환됨!")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"실패: {e}")

        st.markdown("---")
        if len(series_list) > 1:
            if st.button(f"🗑️ '{sig_data.get('current')}' 삭제", use_container_width=True):
                if ds.delete_series(selected_id):
                    st.success("삭제됨!")
                    st.rerun()
                else:
                    st.error("삭제 실패 (마지막 시리즈는 보호됩니다).")
        else:
            st.caption("🛡️ 마지막 시리즈는 삭제할 수 없어요.")

    st.markdown("---")

    # ── ☀️ 오늘의 시그니처 (사운드 정체성) ───────────────────────────
    sig_data = ds.load_signatures()  # 변경 반영
    sig = ds.get_current(sig_data)
    st.markdown("### ☀️ 오늘의 시그니처")
    st.markdown(
        f"**{sig.get('name','(없음)')}** · Day {sig.get('day_count', 1)}\n\n"
        f"🎹 {', '.join((sig.get('core_instruments') or [])[:2])}…  \n"
        f"🎤 {sig.get('vocal','')[:50]}…  \n"
        f"💭 {sig.get('mood','')[:50]}…"
    )
    excluded = sig.get("excluded_instruments") or []
    if excluded:
        st.caption("🚫 **금지 악기:** " + ", ".join(excluded))

    with st.expander("✏️ 시그니처 편집", expanded=False):
        new_name = st.text_input("시리즈명", value=sig.get("name", ""))
        new_core = st.text_area(
            "핵심 악기 (한 줄에 하나)",
            value="\n".join(sig.get("core_instruments") or []),
            height=120,
        )
        new_excluded = st.text_input(
            "절대 금지 악기 (쉼표 구분)",
            value=", ".join(sig.get("excluded_instruments") or []),
        )
        new_vocal = st.text_area("보컬", value=sig.get("vocal", ""), height=70)
        new_mood = st.text_area("분위기", value=sig.get("mood", ""), height=70)
        new_tempo = st.text_input("템포 라벨", value=sig.get("tempo_label", ""))
        new_ref = st.text_input("레퍼런스 아티스트", value=sig.get("reference_artist", ""))
        new_accents = st.text_area(
            "액센트 팔레트 (한 줄에 하나, 매 곡 1개 자동 선택)",
            value="\n".join(sig.get("accent_palette") or []),
            height=120,
        )
        if st.button("💾 시그니처 저장", use_container_width=True):
            sig["name"] = new_name.strip()
            sig["core_instruments"] = [x.strip() for x in new_core.splitlines() if x.strip()]
            sig["excluded_instruments"] = [x.strip() for x in new_excluded.split(",") if x.strip()]
            sig["vocal"] = new_vocal.strip()
            sig["mood"] = new_mood.strip()
            sig["tempo_label"] = new_tempo.strip()
            sig["reference_artist"] = new_ref.strip()
            sig["accent_palette"] = [x.strip() for x in new_accents.splitlines() if x.strip()]
            ds.upsert_series(sig_data.get("current"), sig)
            st.success("저장됨!")
            st.rerun()

    st.markdown("---")

    # ── 📚 나라별 작사 도서관 ──────────────────────────────────────
    st.markdown("### 📚 나라별 작사 도서관")
    st.caption(
        "각 언어 선택 시 그 나라의 작사 DNA(모티프·운율·대표 작사가)가 "
        "자동으로 페르소나에 합쳐져요."
    )
    np_data = np.load_prompts()
    np_keys = list(np_data.keys())
    edit_lang = st.selectbox(
        "편집할 나라 고르기",
        options=np_keys,
        index=0,
        key="nation_edit_lang",
    )
    cur_nation = np_data.get(edit_lang, {})
    with st.expander(f"✏️ {edit_lang} 작사 DNA 편집", expanded=False):
        new_writer = st.text_area(
            "작사가 페르소나(한 문단)",
            value=cur_nation.get("writer_persona", ""),
            height=100,
            key=f"np_writer_{edit_lang}",
        )
        new_motifs = st.text_area(
            "자주 쓰는 모티프 (쉼표 구분)",
            value=", ".join(cur_nation.get("motifs") or []),
            height=70,
            key=f"np_motifs_{edit_lang}",
        )
        new_rhyme = st.text_area(
            "운율/형식 규칙",
            value=cur_nation.get("rhyme_rules", ""),
            height=70,
            key=f"np_rhyme_{edit_lang}",
        )
        new_famous = st.text_input(
            "대표 작사가/아티스트 (쉼표 구분)",
            value=cur_nation.get("famous_writers", ""),
            key=f"np_famous_{edit_lang}",
        )
        new_avoid = st.text_area(
            "피해야 할 것",
            value=cur_nation.get("avoid", ""),
            height=70,
            key=f"np_avoid_{edit_lang}",
        )
        new_sample = st.text_input(
            "한 줄 샘플 (톤 참고용)",
            value=cur_nation.get("sample_line", ""),
            key=f"np_sample_{edit_lang}",
        )
        if st.button(f"💾 {edit_lang} 저장", use_container_width=True, key=f"np_save_{edit_lang}"):
            np.upsert_nation(edit_lang, {
                "writer_persona": new_writer.strip(),
                "motifs": [x.strip() for x in new_motifs.split(",") if x.strip()],
                "rhyme_rules": new_rhyme.strip(),
                "famous_writers": new_famous.strip(),
                "avoid": new_avoid.strip(),
                "sample_line": new_sample.strip(),
            })
            st.success(f"{edit_lang} 작사 DNA 저장됨!")
            st.rerun()

    st.markdown("---")
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

        - 본 앱은 **입력값/결과를 저장하지 않습니다** (시그니처만 로컬 저장).
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

st.markdown("#### 3️⃣ 어떤 언어로? (여러 개 동시 선택 가능)")
language_labels = [f"{v['flag']} {k}" for k, v in LANGUAGES.items()]
language_keys = list(LANGUAGES.keys())
selected_language_labels = st.multiselect(
    label="언어",
    options=language_labels,
    default=[language_labels[0]],  # 한국어 기본
    label_visibility="collapsed",
    help="여러 언어를 고르면 같은 정서·구조로 각 언어 가사를 모두 만들어 드려요. "
         "수노 스타일도 그 언어/지역(샹송·랜체라·볼리우드·만도팝 등)에 맞춰 자동 변환됩니다.",
)
selected_languages = [
    language_keys[language_labels.index(lbl)] for lbl in selected_language_labels
] or ["한국어"]

st.markdown("#### 4️⃣ 주제 (선택)")
theme = st.text_input(
    label="주제",
    placeholder="예) 시골에 두고 온 어머니, 첫사랑의 가을, 한 잔 술…",
    label_visibility="collapsed",
)

st.markdown("#### 5️⃣ 언어당 몇 곡씩 만들까요?")
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

    base_persona = GENRE_PERSONAS[genre]["persona"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 오늘의 시그니처 + 곡별 액센트 (각 언어마다 다른 액센트 — seed = timestamp+lang)
    current_sig = ds.get_current()

    # 언어별로 한 번씩 호출 — 각 언어의 자연스러운 가요 운율 확보
    results_by_lang: dict[str, list[dict]] = {}
    accent_by_lang: dict[str, str] = {}
    total_jobs = len(selected_languages)
    progress = st.progress(0.0, text=f"🎵 0 / {total_jobs} 언어 작업 중…")

    for idx, lang in enumerate(selected_languages, 1):
        progress.progress(
            (idx - 1) / total_jobs,
            text=f"🎵 [{idx}/{total_jobs}] {LANGUAGES[lang]['flag']} {lang} 가사 만드는 중…",
        )
        accent = ds.pick_accent(current_sig, seed=hash((timestamp, lang)) & 0xFFFFFFFF)
        accent_by_lang[lang] = accent
        sig_brief = ds.signature_brief_for_prompt(current_sig, accent=accent)
        # 🌍 나라별 작사 DNA 자동 합치기 — 장르 페르소나 + 그 나라 모티프/운율/대표 작사가
        combined_persona = np.build_combined_persona(
            genre_persona=base_persona,
            language=lang,
            extra_genre_label=genre,
        )
        try:
            variants = generate_lyrics(
                persona=combined_persona,
                duration_sec=duration_sec,
                n=int(n_variants),
                theme=theme,
                genre=genre,
                language=lang,
                signature_brief=sig_brief,
                api_key=api_key,
            )
        except Exception as e:  # noqa: BLE001
            st.error(
                f"**{LANGUAGES[lang]['flag']} {lang}** 가사를 만들지 못했어요.\n\n"
                f"원인: `{type(e).__name__}: {e}`"
            )
            continue
        results_by_lang[lang] = variants or []

    progress.progress(1.0, text="✅ 완료!")
    progress.empty()

    total_songs = sum(len(v) for v in results_by_lang.values())
    if total_songs == 0:
        st.warning("결과가 비어 있어요. 주제를 조금 다르게 적고 다시 시도해 보세요.")
        st.stop()

    st.success(
        f"🎉 **{len(results_by_lang)}개 언어 × {n_variants}곡 = 총 {total_songs}곡** 완성!  "
        f"☀️ **{current_sig.get('name','')} (Day {current_sig.get('day_count',1)})** 사운드 위에서 만들어졌어요.  "
        f"각 카드 3개 박스를 그대로 **수노(Suno) Custom 모드**에 붙여넣으면 끝이에요."
    )

    with st.expander("📖 수노에 붙여넣는 방법 (펼쳐 보기)", expanded=False):
        st.markdown(
            """
            1. [suno.com](https://suno.com) 접속 → **Create** 클릭
            2. 우측 상단 **Custom** 모드 켜기 (필수!)
            3. 아래 3개 박스를 **각각 복사해서 붙여넣기**:
               - **🎨 Style of Music** ← 스타일 박스 (언어/지역 스타일 자동 반영됨)
               - **📝 Lyrics** ← 가사 박스 (Suno 표준 섹션 태그 자동 변환됨)
               - **📛 Title** ← 제목 박스
            4. **Create** 누르면 약 1~2분 뒤 곡 완성!

            💡 **팁:** 각 박스 우측 상단의 📋 아이콘을 누르면 한 번에 복사돼요.
            💡 **다국어 팁:** 스타일에 "sung in French" 처럼 명시되어 수노가 그 언어로 부릅니다.
            """
        )

    # 언어별 섹션 — Suno Style 은 시그니처 + 곡별 액센트 기반
    card_no = 0
    for lang, variants in results_by_lang.items():
        if not variants:
            continue
        flag = LANGUAGES[lang]["flag"]
        accent = accent_by_lang.get(lang, "")
        suno_style = ds.build_suno_style(
            current_sig,
            accent=accent,
            language_english=LANGUAGES[lang]["english"],
        )
        st.markdown(f"## {flag} {lang}  ({len(variants)}곡)")
        if accent:
            st.caption(f"🎵 오늘의 액센트(이 언어): **{accent}**")
        nation = np.get_nation(lang)
        if nation.get("famous_writers"):
            st.caption(
                f"📚 작사 DNA 적용: **{nation.get('famous_writers','')[:60]}…** 톤 / "
                f"모티프 {len(nation.get('motifs') or [])}개"
            )

        for v in variants:
            card_no += 1
            title = v.get("title") or f"가사 {card_no}"
            v_theme = v.get("theme") or ""
            sections = v.get("sections") or []
            suno_lyrics = to_suno_lyrics(sections, fallback_text=v.get("lyrics_text") or "")

            st.markdown(
                f"""
                <div class="lyric-card">
                    <div class="lyric-title">{card_no}. {title}</div>
                    <div class="lyric-theme">{flag} {lang} · 🎯 {v_theme}</div>
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

            bundle = (
                f"=== SIGNATURE ===\n{current_sig.get('name','')} (Day {current_sig.get('day_count',1)})\n\n"
                f"=== LANGUAGE ===\n{lang} ({LANGUAGES[lang]['english']})\n\n"
                f"=== TITLE ===\n{title}\n\n"
                f"=== STYLE OF MUSIC ===\n{suno_style}\n\n"
                f"=== LYRICS ===\n{suno_lyrics}\n"
            )
            st.download_button(
                label=f"⬇️ 전체 TXT 백업 다운로드  ({flag} {title})",
                data=bundle.encode("utf-8"),
                file_name=f"suno_{card_no}_{lang}_{title}_{timestamp}.txt",
                mime="text/plain",
                key=f"dl_{card_no}",
                use_container_width=True,
            )
            st.markdown("---")

    # 곡 생성 완료 → 시리즈 day_count + 총 곡수만큼 증가
    for _ in range(total_songs):
        ds.increment_day(sig_data.get("current"))

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
