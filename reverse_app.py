"""🔎 곡 역설계 단독 툴 — 카테고리별 "내 프롬프트 도서관" 구축기.

스코프: **좋은 곡 링크 → 프롬프트 역설계 → 카테고리별 저장**. 곡 제작은 Suno 에서
사용자가 직접 하므로, 이 툴은 데이터화(컬렉션 구축)에만 집중한다.

별도 Streamlit 앱이다. app.py(메인 대시보드)와 독립적으로 켤 수 있다.

실행:
    streamlit run reverse_app.py

흐름:
    🔎 분석 탭        ── 카테고리 선택 → URL 붙여넣기 → 메타 자동 수집 → Gemini 역설계
                       → Suno 프롬프트 카드 → 마음에 들면 도서관에 저장
    📚 도서관 탭     ── 카테고리별로 저장된 프롬프트 카드 열람·복사·삭제·메모

키: YOUTUBE_API_KEY(필수), GEMINI_API_KEY(필수). .env 자동 로드.
저장소: recipes.json (app.py 의 스튜디오와 공유. category/source_url 필드 추가).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import analyzer
import recipes
import suno_studio


# 기본 카테고리(사용자가 새로 추가하면 도서관에 자동 누적됨).
DEFAULT_CATEGORIES = [
    "트로트", "발라드", "효도", "5070 댄스",
    "인스트루멘털", "가스펠", "동요", "기타",
]


# ---------------------------------------------------------------------------
# 유튜브 URL → video_id 추출
# ---------------------------------------------------------------------------

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_PATTERNS = [
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:[?&]v=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})"),
]


def extract_video_id(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if _VIDEO_ID_RE.match(s):
        return s
    for pat in _URL_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# YouTube Data API
# ---------------------------------------------------------------------------

def fetch_video_metadata(api_key: str, video_id: str, *, max_comments: int = 20) -> dict:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)

    v_resp = youtube.videos().list(
        part="snippet,statistics,contentDetails", id=video_id, maxResults=1,
    ).execute()
    items = v_resp.get("items", [])
    if not items:
        raise ValueError(f"영상을 찾을 수 없습니다: {video_id}")
    v = items[0]
    sn = v.get("snippet", {}) or {}
    stats = v.get("statistics", {}) or {}

    comments: list[str] = []
    if max_comments > 0:
        try:
            c_resp = youtube.commentThreads().list(
                part="snippet", videoId=video_id,
                maxResults=min(100, max_comments), order="relevance",
                textFormat="plainText",
            ).execute()
            for it in c_resp.get("items", []):
                text = (
                    it.get("snippet", {})
                    .get("topLevelComment", {})
                    .get("snippet", {})
                    .get("textDisplay")
                )
                if text:
                    comments.append(text)
        except Exception:
            pass

    return {
        "video_id": video_id,
        "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""),
        "channel_id": sn.get("channelId", ""),
        "published_at": sn.get("publishedAt", ""),
        "tags": list(sn.get("tags") or []),
        "description": sn.get("description", ""),
        "comments": comments[:max_comments],
        "view_count": int(stats.get("viewCount", 0) or 0),
        "like_count": int(stats.get("likeCount", 0) or 0),
        "comment_count": int(stats.get("commentCount", 0) or 0),
        "thumbnail": (sn.get("thumbnails", {}).get("high") or {}).get("url", ""),
    }


# ---------------------------------------------------------------------------
# 카테고리 헬퍼
# ---------------------------------------------------------------------------

def all_categories() -> list[str]:
    """기본 카테고리 + 저장된 레시피에서 발견된 카테고리(중복 제거, 순서 유지)."""
    found = recipes.distinct_categories()
    merged: list[str] = []
    for c in DEFAULT_CATEGORIES + found:
        if c and c not in merged:
            merged.append(c)
    return merged


def youtube_url(video_id: str | None) -> str:
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _load_vocab_cached() -> dict:
    if "_vocab" not in st.session_state:
        st.session_state["_vocab"] = suno_studio.load_vocab()
    return st.session_state["_vocab"]


def render_analyze_tab(vocab: dict, yt_key: str, gem_key: str, model: str,
                      preset_key: str, max_comments: int) -> None:
    st.subheader("🔎 좋은 곡을 프롬프트로 역설계")
    st.caption(
        "마음에 든 유튜브 곡을 카테고리에 담아 분석합니다. "
        "오디오는 받지 않고(ToS 안전) 제목·태그·설명·댓글만으로 추정합니다."
    )

    cats = all_categories()

    # --- 카테고리: 기존에서 고르거나 직접 입력 (직접 입력값 우선) ---
    st.markdown("**카테고리 / 장르**  · 기존에서 고르거나 오른쪽에 직접 입력하세요 (직접 입력이 우선)")
    cat_cols = st.columns([2, 2])
    with cat_cols[0]:
        picked = st.selectbox(
            "기존 카테고리에서 선택",
            options=["(선택 안 함)"] + cats,
            key="rv_cat_select",
            label_visibility="collapsed",
        )
    with cat_cols[1]:
        typed = st.text_input(
            "직접 입력",
            key="rv_cat_typed",
            placeholder="예: 시티팝 / 90년대 발라드 / 보사노바",
            label_visibility="collapsed",
        )
    typed_clean = (typed or "").strip()
    if typed_clean:
        category = typed_clean
    elif picked and picked != "(선택 안 함)":
        category = picked
    else:
        category = ""
    if category:
        st.caption(f"→ 저장 카테고리: **{category}**")

    url = st.text_input(
        "유튜브 URL 또는 video_id",
        placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX",
        key="rv_url",
    )

    cols = st.columns([1, 1, 4])
    fetch_btn = cols[0].button("① 메타 가져오기", use_container_width=True)
    analyze_btn = cols[1].button("② 역설계 분석", type="primary", use_container_width=True)

    # --- 1단계: 메타 수집 ---
    if fetch_btn:
        vid = extract_video_id(url)
        if not vid:
            st.error("유효한 유튜브 URL 또는 11자 video_id 를 입력하세요.")
        elif not yt_key.strip():
            st.error("YouTube API 키가 필요합니다. (사이드바)")
        else:
            try:
                with st.spinner(f"메타데이터 수집 중… ({vid})"):
                    meta = fetch_video_metadata(
                        yt_key.strip(), vid, max_comments=max_comments,
                    )
                st.session_state["rv_meta"] = meta
                st.session_state.pop("rv_result", None)
                st.success(f"수집 완료: {meta['title']}")
            except Exception as e:
                st.error(f"수집 실패: {type(e).__name__}: {e}")

    meta: dict[str, Any] | None = st.session_state.get("rv_meta")

    if meta:
        with st.container(border=True):
            top = st.columns([1, 3])
            if meta.get("thumbnail"):
                top[0].image(meta["thumbnail"], use_container_width=True)
            top[1].markdown(f"### {meta['title']}")
            top[1].caption(
                f"채널: {meta['channel']}  ·  조회수 {meta['view_count']:,}  ·  "
                f"좋아요 {meta['like_count']:,}  ·  댓글 {meta['comment_count']:,}"
            )
            if meta.get("tags"):
                top[1].markdown("**태그:** " + ", ".join(meta["tags"][:20]))
            with st.expander("설명 / 댓글 보기"):
                st.text_area("설명", value=meta.get("description", ""),
                             height=120, disabled=True, key="rv_meta_desc")
                if meta.get("comments"):
                    st.markdown(f"**상위 댓글 {len(meta['comments'])}개**")
                    for c in meta["comments"][:10]:
                        st.markdown(f"- {c}")

    # --- 2단계: 역설계 ---
    if analyze_btn:
        if not meta:
            st.warning("먼저 ① 메타 가져오기를 누르세요.")
        elif not gem_key.strip():
            st.error("Gemini API 키가 필요합니다. (사이드바)")
        else:
            try:
                with st.spinner("Gemini 역설계 분석 중…"):
                    result = analyzer.analyze_metadata(
                        meta, vocab,
                        preset_hint=preset_key,
                        api_key=gem_key.strip(),
                        model=model.strip() or analyzer.DEFAULT_MODEL,
                    )
                st.session_state["rv_result"] = result
            except Exception as e:
                st.error(f"분석 실패: {type(e).__name__}: {e}")

    result = st.session_state.get("rv_result")

    # --- 결과 카드 + 저장 ---
    if result and meta:
        st.divider()
        st.subheader("🎚️ Suno 프롬프트 카드")
        prompt_text = suno_studio.picks_to_prompt(
            vocab, result["preset"], result["picks"]
        )

        mcols = st.columns(3)
        mcols[0].metric("무드", result.get("mood") or "-")
        mcols[1].metric("BPM", result.get("bpm") or "-")
        mcols[2].metric("프리셋", result["preset"])
        if result.get("rationale"):
            st.caption(f"💡 근거: {result['rationale']}")

        st.markdown("**Suno 에 그대로 붙여넣을 프롬프트:**")
        st.code(prompt_text, language=None)

        with st.expander("picks (차원별 원본)"):
            st.json(result["picks"])

        new_terms = result.get("new_terms") or {}
        if new_terms:
            with st.expander("🧩 새 어휘 후보 (vocab.json 보완용)"):
                st.json(new_terms)

        st.divider()
        st.subheader("📥 도서관에 저장")
        if not category:
            st.warning("저장하려면 위에서 카테고리를 선택하거나 새로 만드세요.")
        else:
            st.caption(f"카테고리: **{category}**")
            rname = st.text_input(
                "프롬프트 이름 (기억하기 쉬운 라벨)",
                value=meta["title"][:50] or "역설계 프롬프트",
                key="rv_save_name",
            )
            note = st.text_area(
                "메모 (선택) — 이 곡이 좋은 이유, Suno 에서 시도한 변형 등",
                key="rv_save_note", height=70,
            )
            if st.button("💾 도서관에 저장", type="primary", use_container_width=True):
                try:
                    rec = recipes.save_recipe(
                        rname or meta["title"] or "역설계 프롬프트",
                        result["preset"], result["picks"],
                        bpm=result.get("bpm"),
                        source_video_id=meta.get("video_id"),
                        source_url=youtube_url(meta.get("video_id")),
                        category=category,
                        notes=(note.strip() or result.get("rationale", "")),
                    )
                    st.success(f"저장됨: **{rec['name']}**  ({category})")
                    st.session_state.pop("rv_result", None)
                    st.session_state.pop("rv_meta", None)
                except Exception as e:
                    st.error(f"저장 실패: {type(e).__name__}: {e}")

    elif not meta:
        st.info(
            "👆 카테고리 선택 → URL 붙여넣기 → **① 메타 가져오기** → **② 역설계 분석** 순서로 진행하세요."
        )


def render_library_tab(vocab: dict) -> None:
    st.subheader("📚 내 프롬프트 도서관")
    st.caption("카테고리별로 모은 역설계 프롬프트. Suno 에 붙여넣을 텍스트가 카드마다 들어있습니다.")

    all_recipes = recipes.list_recipes()
    if not all_recipes:
        st.info("아직 모은 프롬프트가 없습니다. 🔎 분석 탭에서 첫 곡을 역설계하세요.")
        return

    # 카테고리별 그룹화 (빈 카테고리는 '미분류' 로)
    grouped: dict[str, list[dict]] = {}
    for r in all_recipes:
        c = (r.get("category") or "").strip() or "미분류"
        grouped.setdefault(c, []).append(r)

    # 필터
    filt_cols = st.columns([2, 1, 1])
    cats_in_lib = sorted(grouped.keys())
    selected = filt_cols[0].multiselect(
        "카테고리 필터 (비우면 전체)", options=cats_in_lib, default=[],
        key="rv_lib_cat_filter",
    )
    sort_mode = filt_cols[1].selectbox(
        "정렬", ["최신순", "이름순"], key="rv_lib_sort",
    )
    filt_cols[2].metric("총 개수", len(all_recipes))

    shown_cats = selected if selected else cats_in_lib

    for cat in shown_cats:
        items = list(grouped.get(cat, []))
        if not items:
            continue
        if sort_mode == "최신순":
            items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        else:
            items.sort(key=lambda r: r.get("name", ""))

        st.markdown(f"## {cat}  ·  {len(items)}개")
        for r in items:
            render_recipe_card(r, vocab)


def render_recipe_card(r: dict, vocab: dict) -> None:
    rid = r["id"]
    confirm_key = f"rv_del_confirm_{rid}"
    edit_key = f"rv_edit_open_{rid}"

    with st.container(border=True):
        head = st.columns([5, 1])
        head[0].markdown(f"### {r.get('name', '(이름없음)')}")
        head[0].caption(
            f"카테고리: **{r.get('category') or '미분류'}**  ·  "
            f"프리셋: {r.get('preset', '')}  ·  "
            f"BPM: {r.get('bpm') or '-'}  ·  "
            f"저장: {(r.get('created_at') or '')[:10]}"
        )
        if r.get("source_url"):
            head[1].link_button("🔗 원본", r["source_url"], use_container_width=True)

        try:
            prompt = suno_studio.picks_to_prompt(
                vocab, r.get("preset") or "kr_trot", r.get("picks") or {}
            )
        except Exception:
            prompt = "(프롬프트 재구성 실패)"
        st.code(prompt, language=None)

        if r.get("notes"):
            st.caption(f"📝 {r['notes']}")

        with st.expander("picks / 메타 보기"):
            st.json({k: v for k, v in r.items() if k not in {"picks"}})
            st.json(r.get("picks") or {})

        action_cols = st.columns([1, 1, 1, 3])
        if action_cols[0].button("✏️ 카테고리 수정", key=f"rv_edit_{rid}"):
            st.session_state[edit_key] = not st.session_state.get(edit_key, False)

        if action_cols[1].button("🗑 삭제", key=f"rv_del_{rid}"):
            st.session_state[confirm_key] = True

        if st.session_state.get(confirm_key):
            st.warning(f"정말 '{r.get('name')}' 을(를) 삭제할까요? 되돌릴 수 없습니다.")
            yn = st.columns([1, 1, 4])
            if yn[0].button("✅ 예, 삭제", key=f"rv_del_yes_{rid}", type="primary"):
                recipes.delete_recipe(rid)
                st.session_state.pop(confirm_key, None)
                st.success("삭제되었습니다.")
                st.rerun()
            if yn[1].button("취소", key=f"rv_del_no_{rid}"):
                st.session_state.pop(confirm_key, None)
                st.rerun()

        if st.session_state.get(edit_key):
            cats = all_categories() + ["미분류"]
            cur = r.get("category") or "미분류"
            new_cat = st.selectbox(
                "카테고리 변경", options=cats,
                index=cats.index(cur) if cur in cats else 0,
                key=f"rv_edit_sel_{rid}",
            )
            if st.button("저장", key=f"rv_edit_save_{rid}"):
                recipes.update_recipe(
                    rid, category=("" if new_cat == "미분류" else new_cat),
                )
                st.session_state.pop(edit_key, None)
                st.success("수정되었습니다.")
                st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="곡 역설계 — 내 프롬프트 도서관",
        page_icon="🔎", layout="wide",
    )
    st.title("🔎 곡 역설계 → 📚 내 프롬프트 도서관")
    st.caption(
        "좋은 곡 링크 → Suno 프롬프트 역설계 → 카테고리별 저장. "
        "곡 제작은 Suno 에서 직접 하시고, 여기는 데이터화에 집중합니다."
    )

    vocab = _load_vocab_cached()
    presets = suno_studio.list_presets(vocab)

    with st.sidebar:
        st.header("🔑 키 / 설정")
        yt_key = st.text_input(
            "YouTube API Key", type="password",
            value=os.getenv("YOUTUBE_API_KEY", ""),
            help="영상 메타데이터/댓글 수집에 필요합니다.",
        )
        gem_key = st.text_input(
            "Gemini API Key", type="password",
            value=os.getenv("GEMINI_API_KEY", ""),
            help="역설계(스타일 추정)에 필요합니다.",
        )
        model = st.text_input("Gemini 모델", value=analyzer.DEFAULT_MODEL)
        preset_key = st.selectbox(
            "프리셋(나라/장르 힌트)",
            options=[k for k, _ in presets],
            format_func=lambda k: dict(presets)[k],
        )
        max_comments = st.slider("수집 댓글 수", 0, 50, 20)
        st.divider()
        st.caption(
            f"저장소: `recipes.json` ({len(recipes.list_recipes())}개 보관 중)"
        )

    tab_analyze, tab_library = st.tabs(["🔎 분석", "📚 도서관"])
    with tab_analyze:
        render_analyze_tab(
            vocab, yt_key, gem_key, model, preset_key, max_comments,
        )
    with tab_library:
        render_library_tab(vocab)


if __name__ == "__main__":
    main()
