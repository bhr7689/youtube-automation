"""🔎 곡 역설계 단독 툴 — Suno 프롬프트 + 작사가 프롬프트 동시 데이터화.

스코프: 좋은 곡 링크 한 번 입력 → 메타+가사 자동 수집 → Gemini 가
       곡 picks(Suno 프롬프트)와 가사 패턴(작사가 프롬프트)을 동시 추출
       → 두 도서관(곡 프롬프트 / 작사가 프롬프트)에 장르별로 누적.

곡 제작은 Suno 에서 사용자가 직접. 본 툴은 데이터화 전담.

탭 구조:
    🔎 분석                — URL 한 번 → 두 자산 동시 추출 → 저장
    🎚️ 곡 프롬프트 도서관  — Suno 에 붙여넣을 프롬프트 카테고리별 컬렉션
    ✍️ 작사가 프롬프트 도서관 — 장르별 가사 본문 + 작사 패턴 + writer_prompt

실행: streamlit run reverse_app.py
"""

from __future__ import annotations

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
import audio_probe
import lyrics_analyzer
import lyrics_generator
import lyrics_library
import recipes
import suno_studio
import transcript_probe

COPY_HINT = "💡 결과 블록 우상단의 📋 아이콘으로 복사하거나, 텍스트를 드래그해 Ctrl+C 하세요."


DEFAULT_CATEGORIES = [
    "트로트", "발라드", "효도", "5070 댄스",
    "인스트루멘털", "가스펠", "동요", "기타",
]


# ---------------------------------------------------------------------------
# URL 파서
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


def youtube_url(video_id: str | None) -> str:
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""


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
# 카테고리/장르 헬퍼
# ---------------------------------------------------------------------------

def all_categories() -> list[str]:
    found = list(recipes.distinct_categories()) + list(lyrics_library.distinct_genres())
    merged: list[str] = []
    for c in DEFAULT_CATEGORIES + found:
        if c and c not in merged:
            merged.append(c)
    return merged


def _load_vocab_cached() -> dict:
    if "_vocab" not in st.session_state:
        st.session_state["_vocab"] = suno_studio.load_vocab()
    return st.session_state["_vocab"]


# ---------------------------------------------------------------------------
# 탭 1: 분석
# ---------------------------------------------------------------------------

def render_analyze_tab(
    vocab: dict, yt_key: str, gem_key: str, oai_key: str, model: str,
    preset_key: str, max_comments: int, allow_whisper: bool,
    allow_audio_probe: bool = False,
) -> None:
    st.subheader("🔎 좋은 곡 → 곡 프롬프트 + 작사가 프롬프트 동시 추출")
    st.caption(
        "URL 한 번에 메타데이터 + 가사를 가져와 Gemini 가 두 자산을 동시에 만듭니다. "
        "곡은 Suno 에서 직접 만드시고, 여기에는 데이터만 누적됩니다."
    )
    st.caption(COPY_HINT)

    cats = all_categories()

    st.markdown("**카테고리 / 장르**  · 기존에서 고르거나 오른쪽에 직접 입력 (직접 입력이 우선)")
    cat_cols = st.columns([2, 2])
    with cat_cols[0]:
        picked = st.selectbox(
            "기존 카테고리에서 선택",
            options=["(선택 안 함)"] + cats,
            key="rv_cat_select", label_visibility="collapsed",
        )
    with cat_cols[1]:
        typed = st.text_input(
            "직접 입력", key="rv_cat_typed",
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
        st.caption(f"→ 저장 카테고리/장르: **{category}**")

    url = st.text_input(
        "유튜브 URL 또는 video_id",
        placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX",
        key="rv_url",
    )

    cols = st.columns([1, 1, 4])
    fetch_btn = cols[0].button("① 메타 + 가사 가져오기", use_container_width=True)
    analyze_btn = cols[1].button("② 분석", type="primary", use_container_width=True)

    # --- 1단계: 메타 + 가사 수집 ---
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

                with st.spinner("자막에서 가사 추출 중…"):
                    tr = transcript_probe.get_lyrics(
                        vid,
                        openai_key=oai_key.strip() or None,
                        allow_whisper=allow_whisper,
                    )
                st.session_state["rv_transcript"] = tr.as_dict()
                st.session_state.pop("rv_song_result", None)
                st.session_state.pop("rv_lyrics_result", None)
                st.session_state.pop("rv_audio", None)

                if tr.ok:
                    src_label = {
                        "manual": "수동 자막", "auto": "자동 자막",
                        "translated": "번역 자막", "whisper": "Whisper 받아쓰기",
                    }.get(tr.source, tr.source)
                    st.success(f"수집 완료: {meta['title']}  ·  가사 소스: {src_label}")
                else:
                    st.warning(
                        f"메타 수집은 완료. 가사는 못 가져왔습니다 → {tr.error or '사용 가능한 자막 없음'}. "
                        "사이드바에서 Whisper fallback 을 켜면 다시 시도할 수 있습니다."
                    )

                if allow_audio_probe:
                    with st.spinner("오디오 다운로드 + librosa 실측 분석 중… (30초~2분 소요)"):
                        feats = audio_probe.probe_video(vid)
                    st.session_state["rv_audio"] = feats.as_dict()
                    if feats.ok:
                        st.success(f"오디오 실측 완료: {feats.summary()}")
                    else:
                        st.warning(
                            f"오디오 실측 실패 → {feats.error or '알 수 없음'}. "
                            "메타·가사만으로 분석을 진행합니다."
                        )
            except Exception as e:
                st.error(f"수집 실패: {type(e).__name__}: {e}")

    meta: dict[str, Any] | None = st.session_state.get("rv_meta")
    tr_dict: dict[str, Any] | None = st.session_state.get("rv_transcript")

    # --- 메타 미리보기 ---
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

    # --- 오디오 실측 결과 카드 ---
    audio_dict: dict[str, Any] | None = st.session_state.get("rv_audio")
    if audio_dict and not audio_dict.get("error"):
        with st.container(border=True):
            st.markdown("**🎧 오디오 실측 (librosa)**")
            metrics = st.columns(4)
            metrics[0].metric("BPM", f"{audio_dict.get('tempo_bpm') or 0:.0f}")
            metrics[1].metric("키", audio_dict.get("key_label") or "-")
            dur = audio_dict.get("duration_sec") or 0
            metrics[2].metric("길이", f"{int(dur)//60}:{int(dur)%60:02d}" if dur else "-")
            metrics[3].metric("평균 에너지",
                              f"{audio_dict.get('rms_mean') or 0:.3f}")
            with st.expander("스펙트럼/리듬 세부 지표"):
                st.json({
                    k: audio_dict.get(k) for k in [
                        "spectral_centroid_mean", "zero_crossing_rate_mean",
                        "onset_rate", "rms_peak", "key_confidence", "sample_rate",
                    ]
                })

    # --- 가사 미리보기 + 편집 ---
    if tr_dict:
        with st.container(border=True):
            src_label = {
                "manual": "수동 자막 (정확)", "auto": "자동 자막 (오인식 가능)",
                "translated": "번역된 자막", "whisper": "Whisper 받아쓰기",
            }.get(tr_dict.get("source"), "없음")
            st.markdown(f"**📝 가사 / 자막**  ·  소스: {src_label}")
            if tr_dict.get("error"):
                st.caption(tr_dict["error"])
            edited = st.text_area(
                "가사 본문 (오타·중복은 직접 수정 후 분석하세요)",
                value=tr_dict.get("text", ""),
                height=200, key="rv_lyrics_edited",
            )
            # 편집 결과를 다시 세션에 반영
            st.session_state["rv_transcript"]["text"] = edited
            if edited.strip() != (tr_dict.get("text") or "").strip():
                st.session_state["rv_transcript"]["source"] = (
                    (tr_dict.get("source") or "") + "+edit"
                ).strip("+")

    # --- 2단계: 분석 ---
    if analyze_btn:
        if not meta:
            st.warning("먼저 ① 메타 + 가사 가져오기를 누르세요.")
        elif not gem_key.strip():
            st.error("Gemini API 키가 필요합니다. (사이드바)")
        else:
            # 곡 picks: 메타 + (있으면) 오디오 실측 + 가사 일부를 모두 주입
            enriched_meta = dict(meta)
            audio = st.session_state.get("rv_audio") or {}
            if audio and not audio.get("error"):
                enriched_meta["audio_features"] = {
                    k: audio.get(k) for k in [
                        "tempo_bpm", "key_label", "duration_sec", "rms_mean",
                        "spectral_centroid_mean", "onset_rate",
                    ]
                }
            lyrics_text = (st.session_state.get("rv_transcript") or {}).get("text") or ""
            if lyrics_text.strip():
                enriched_meta["lyrics_excerpt"] = lyrics_text[:600]
            try:
                with st.spinner("Gemini 역설계 분석 중 (곡 picks)…"):
                    song_result = analyzer.analyze_metadata(
                        enriched_meta, vocab,
                        preset_hint=preset_key,
                        api_key=gem_key.strip(),
                        model=model.strip() or analyzer.DEFAULT_MODEL,
                    )
                st.session_state["rv_song_result"] = song_result
            except Exception as e:
                st.error(f"곡 분석 실패: {type(e).__name__}: {e}")
                st.session_state.pop("rv_song_result", None)

            # 가사 패턴 (가사가 있을 때만)
            lyrics_text = (st.session_state.get("rv_transcript") or {}).get("text") or ""
            if lyrics_text.strip():
                try:
                    with st.spinner("Gemini 작사 패턴 분석 중…"):
                        lyr_result = lyrics_analyzer.analyze_lyrics(
                            lyrics_text, title=meta.get("title", ""), genre=category,
                            api_key=gem_key.strip(),
                            model=model.strip() or lyrics_analyzer.DEFAULT_MODEL,
                        )
                    st.session_state["rv_lyrics_result"] = lyr_result
                except Exception as e:
                    st.error(f"작사 분석 실패: {type(e).__name__}: {e}")
                    st.session_state.pop("rv_lyrics_result", None)
            else:
                st.info("가사가 없어 작사 분석은 건너뛰었습니다. 곡 분석만 진행합니다.")
                st.session_state.pop("rv_lyrics_result", None)

    song_result = st.session_state.get("rv_song_result")
    lyr_result = st.session_state.get("rv_lyrics_result")

    # --- 결과: 곡 카드 ---
    if song_result and meta:
        st.divider()
        st.subheader("🎚️ 곡 프롬프트 카드 (Suno 용)")
        prompt_text = suno_studio.picks_to_prompt(
            vocab, song_result["preset"], song_result["picks"]
        )
        mcols = st.columns(3)
        mcols[0].metric("무드", song_result.get("mood") or "-")
        mcols[1].metric("BPM", song_result.get("bpm") or "-")
        mcols[2].metric("프리셋", song_result["preset"])
        if song_result.get("rationale"):
            st.caption(f"💡 {song_result['rationale']}")
        st.code(prompt_text, language=None)

        with st.expander("picks (차원별 원본)"):
            st.json(song_result["picks"])

        new_terms = song_result.get("new_terms") or {}
        if new_terms:
            with st.expander("🧩 새 어휘 후보 (vocab.json 보완용)"):
                st.json(new_terms)

        # 저장
        with st.container(border=True):
            st.markdown("**📥 곡 프롬프트 도서관에 저장**")
            if not category:
                st.warning("저장하려면 위에서 카테고리를 선택하거나 직접 입력하세요.")
            else:
                rname = st.text_input(
                    "프롬프트 이름",
                    value=meta["title"][:50] or "역설계 프롬프트",
                    key="rv_song_save_name",
                )
                note = st.text_area(
                    "메모 (선택)", key="rv_song_save_note", height=60,
                )
                if st.button("💾 곡 도서관에 저장", type="primary",
                             key="rv_song_save", use_container_width=True):
                    try:
                        rec = recipes.save_recipe(
                            rname or meta["title"] or "역설계 프롬프트",
                            song_result["preset"], song_result["picks"],
                            bpm=song_result.get("bpm"),
                            source_video_id=meta.get("video_id"),
                            source_url=youtube_url(meta.get("video_id")),
                            category=category,
                            notes=(note.strip() or song_result.get("rationale", "")),
                        )
                        st.success(f"저장: **{rec['name']}** ({category})")
                    except Exception as e:
                        st.error(f"저장 실패: {type(e).__name__}: {e}")

    # --- 결과: 작사가 카드 ---
    if lyr_result and meta:
        st.divider()
        st.subheader("✍️ 작사가 프롬프트 카드")
        st.caption(f"한 줄 요약: {lyr_result.get('summary', '')}")
        if lyr_result.get("rationale"):
            st.caption(f"💡 {lyr_result['rationale']}")

        st.markdown("**AI 작사가에게 줄 페르소나·지시문 (이대로 복사해서 사용):**")
        st.code(lyr_result.get("writer_prompt", ""), language=None)

        with st.expander("작사 패턴 (차원별)"):
            st.json(lyr_result.get("patterns") or {})

        with st.container(border=True):
            st.markdown("**📥 작사가 도서관에 저장**")
            if not category:
                st.warning("저장하려면 카테고리/장르를 지정하세요.")
            else:
                lname = st.text_input(
                    "이름 (이 가사를 부르는 라벨)",
                    value=meta["title"][:50] or "작사 패턴",
                    key="rv_lyr_save_name",
                )
                lnote = st.text_area(
                    "메모 (선택)", key="rv_lyr_save_note", height=60,
                )
                if st.button("💾 작사가 도서관에 저장", type="primary",
                             key="rv_lyr_save", use_container_width=True):
                    try:
                        lyrics_full = (st.session_state.get("rv_transcript") or {}).get("text") or ""
                        src = (st.session_state.get("rv_transcript") or {}).get("source") or ""
                        ent = lyrics_library.save_entry(
                            name=lname or meta["title"] or "작사 패턴",
                            genre=category,
                            lyrics_text=lyrics_full,
                            patterns=lyr_result.get("patterns") or {},
                            writer_prompt=lyr_result.get("writer_prompt", ""),
                            summary=lyr_result.get("summary", ""),
                            rationale=lyr_result.get("rationale", ""),
                            transcript_source=src,
                            source_video_id=meta.get("video_id"),
                            source_url=youtube_url(meta.get("video_id")),
                            notes=lnote,
                        )
                        st.success(f"저장: **{ent['name']}** ({category})")
                    except Exception as e:
                        st.error(f"저장 실패: {type(e).__name__}: {e}")

    if not meta and not song_result:
        st.info(
            "👆 카테고리/장르 지정 → URL 붙여넣기 → **① 메타 + 가사 가져오기** → "
            "**② 분석** 순서로 진행하세요."
        )


# ---------------------------------------------------------------------------
# 탭 2: 곡 프롬프트 도서관
# ---------------------------------------------------------------------------

def render_song_library_tab(vocab: dict) -> None:
    st.subheader("🎚️ 곡 프롬프트 도서관")
    st.caption("카테고리별 Suno 프롬프트 컬렉션. 카드의 텍스트를 Suno 에 붙여넣으세요.")
    st.caption(COPY_HINT)

    all_recipes = recipes.list_recipes()
    if not all_recipes:
        st.info("아직 모은 곡 프롬프트가 없습니다. 🔎 분석 탭에서 첫 곡을 역설계하세요.")
        return

    grouped: dict[str, list[dict]] = {}
    for r in all_recipes:
        c = (r.get("category") or "").strip() or "미분류"
        grouped.setdefault(c, []).append(r)

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
            render_song_card(r, vocab)


def render_song_card(r: dict, vocab: dict) -> None:
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

        action_cols = st.columns([1, 1, 1, 3])
        if action_cols[0].button("✏️ 카테고리", key=f"rv_edit_{rid}"):
            st.session_state[edit_key] = not st.session_state.get(edit_key, False)
        if action_cols[1].button("🗑 삭제", key=f"rv_del_{rid}"):
            st.session_state[confirm_key] = True

        if st.session_state.get(confirm_key):
            st.warning(f"정말 '{r.get('name')}' 을(를) 삭제할까요?")
            yn = st.columns([1, 1, 4])
            if yn[0].button("✅ 예", key=f"rv_del_yes_{rid}", type="primary"):
                recipes.delete_recipe(rid)
                st.session_state.pop(confirm_key, None)
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
                st.rerun()


# ---------------------------------------------------------------------------
# 탭 3: 작사가 프롬프트 도서관
# ---------------------------------------------------------------------------

def render_lyrics_library_tab() -> None:
    st.subheader("✍️ 작사가 프롬프트 도서관")
    st.caption(
        "장르별 가사 본문 + 작사 패턴 + writer_prompt. 같은 장르의 곡들을 합쳐서 "
        "'그 장르 작사가 통합 페르소나'도 자동 생성합니다."
    )
    st.caption(COPY_HINT)

    entries = lyrics_library.list_entries()
    if not entries:
        st.info("아직 모은 작사 데이터가 없습니다. 🔎 분석 탭에서 가사 있는 곡을 분석하세요.")
        return

    grouped: dict[str, list[dict]] = {}
    for e in entries:
        g = (e.get("genre") or "").strip() or "미분류"
        grouped.setdefault(g, []).append(e)

    filt_cols = st.columns([2, 1, 1])
    genres = sorted(grouped.keys())
    selected = filt_cols[0].multiselect(
        "장르 필터 (비우면 전체)", options=genres, default=[],
        key="rv_lyr_filter",
    )
    sort_mode = filt_cols[1].selectbox(
        "정렬", ["최신순", "이름순"], key="rv_lyr_sort",
    )
    filt_cols[2].metric("총 개수", len(entries))

    shown = selected if selected else genres

    for g in shown:
        items = list(grouped.get(g, []))
        if not items:
            continue
        if sort_mode == "최신순":
            items.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        else:
            items.sort(key=lambda e: e.get("name", ""))

        head_cols = st.columns([4, 1])
        head_cols[0].markdown(f"## {g}  ·  {len(items)}개")
        if head_cols[1].button(f"🧬 {g} 통합 페르소나", key=f"rv_merge_{g}",
                               use_container_width=True):
            st.session_state[f"rv_merge_show_{g}"] = True

        if st.session_state.get(f"rv_merge_show_{g}"):
            merged = lyrics_library.merged_writer_prompt(g)
            with st.container(border=True):
                st.markdown(f"### 🧬 {g} 작사가 통합 페르소나 (곡 {len(items)}개 합성)")
                st.caption("💡 블록 우상단의 📋 아이콘으로 클립보드 복사, 또는 ⬇ .txt 다운로드.")
                st.code(merged, language="markdown")
                dl_cols = st.columns([1, 1, 4])
                dl_cols[0].download_button(
                    "⬇ .txt 다운로드", data=merged.encode("utf-8"),
                    file_name=f"persona_{g}.txt", mime="text/plain",
                    key=f"rv_merge_dl_{g}", use_container_width=True,
                )
                if dl_cols[1].button("닫기", key=f"rv_merge_close_{g}",
                                     use_container_width=True):
                    st.session_state.pop(f"rv_merge_show_{g}", None)
                    st.rerun()

        for e in items:
            render_lyrics_card(e)


def render_lyrics_card(e: dict) -> None:
    eid = e["id"]
    confirm_key = f"rv_lyr_del_confirm_{eid}"
    edit_key = f"rv_lyr_edit_open_{eid}"

    with st.container(border=True):
        head = st.columns([5, 1])
        head[0].markdown(f"### {e.get('name', '(이름없음)')}")
        src = e.get("transcript_source") or ""
        head[0].caption(
            f"장르: **{e.get('genre') or '미분류'}**  ·  "
            f"가사 소스: {src or '-'}  ·  "
            f"저장: {(e.get('created_at') or '')[:10]}"
        )
        if e.get("source_url"):
            head[1].link_button("🔗 원본", e["source_url"], use_container_width=True)

        if e.get("summary"):
            st.markdown(f"**요약:** {e['summary']}")

        st.markdown("**작사가 프롬프트 (그대로 AI 에 붙여넣기):**")
        st.code(e.get("writer_prompt", ""), language=None)

        with st.expander("📝 가사 본문 보기 (복사 가능)"):
            st.code(e.get("lyrics_text", "") or "(없음)", language=None)
        with st.expander("작사 패턴 (차원별)"):
            st.json(e.get("patterns") or {})

        action_cols = st.columns([1, 1, 1, 3])
        if action_cols[0].button("✏️ 장르 변경", key=f"rv_lyr_edit_{eid}"):
            st.session_state[edit_key] = not st.session_state.get(edit_key, False)
        if action_cols[1].button("🗑 삭제", key=f"rv_lyr_del_{eid}"):
            st.session_state[confirm_key] = True

        if st.session_state.get(confirm_key):
            st.warning(f"정말 '{e.get('name')}' 을(를) 삭제할까요?")
            yn = st.columns([1, 1, 4])
            if yn[0].button("✅ 예", key=f"rv_lyr_del_yes_{eid}", type="primary"):
                lyrics_library.delete_entry(eid)
                st.session_state.pop(confirm_key, None)
                st.rerun()
            if yn[1].button("취소", key=f"rv_lyr_del_no_{eid}"):
                st.session_state.pop(confirm_key, None)
                st.rerun()

        if st.session_state.get(edit_key):
            gs = all_categories() + ["미분류"]
            cur = e.get("genre") or "미분류"
            new_g = st.selectbox(
                "장르 변경", options=gs,
                index=gs.index(cur) if cur in gs else 0,
                key=f"rv_lyr_edit_sel_{eid}",
            )
            if st.button("저장", key=f"rv_lyr_edit_save_{eid}"):
                lyrics_library.update_entry(
                    eid, genre=("" if new_g == "미분류" else new_g),
                )
                st.session_state.pop(edit_key, None)
                st.rerun()


# ---------------------------------------------------------------------------
# 탭 4: 곡 프롬프트 변주 (도서관 항목 → 같은 듯 다른 N개)
# ---------------------------------------------------------------------------

_STRENGTH_LOCKS = {
    "약 (정체성 최대 보존)": {"mood", "vocal_gender", "vocal_register", "vocal_ensemble", "production"},
    "중 (권장)": {"mood", "vocal_gender"},
    "강 (대담한 변주)": set(),
}


def render_song_variation_tab(vocab: dict) -> None:
    st.subheader("✨ 곡 프롬프트 변주")
    st.caption(
        "도서관에서 베이스 곡을 골라 같은 무드·정체성으로 변주된 Suno 프롬프트를 N개 생성합니다. "
        "여러 곡을 고르면 블렌딩되어 더 풍부한 베이스로 시작합니다."
    )
    st.caption(COPY_HINT)

    all_recipes = recipes.list_recipes()
    if not all_recipes:
        st.info("아직 곡 도서관이 비어 있습니다. 🔎 분석 탭에서 먼저 곡을 모으세요.")
        return

    by_label: dict[str, dict] = {}
    for r in all_recipes:
        label = f"[{r.get('category') or '미분류'}] {r.get('name','')} ({(r.get('created_at') or '')[:10]})"
        by_label[label] = r

    cols = st.columns([3, 1, 1])
    selected_labels = cols[0].multiselect(
        "베이스 곡 선택 (여러 개 고르면 블렌딩)",
        options=list(by_label.keys()),
        key="rv_var_select",
    )
    strength = cols[1].selectbox(
        "변주 강도",
        options=list(_STRENGTH_LOCKS.keys()), index=1,
        key="rv_var_strength",
    )
    n = cols[2].number_input("개수", min_value=1, max_value=20, value=5, key="rv_var_n")

    seed_cols = st.columns([1, 3])
    seed_str = seed_cols[0].text_input("랜덤 시드 (선택)", key="rv_var_seed",
                                       placeholder="비우면 매번 다른 결과")

    if st.button("✨ 변주 생성", type="primary", key="rv_var_run"):
        if not selected_labels:
            st.warning("최소 1개 이상의 베이스 곡을 선택하세요.")
        else:
            chosen = [by_label[l] for l in selected_labels]
            preset_key = chosen[0].get("preset") or "kr_trot"
            try:
                if len(chosen) == 1:
                    base_picks = dict(chosen[0].get("picks") or {})
                else:
                    preset_key, base_picks = recipes.blend_recipes(chosen, preset=preset_key)
                seed = int(seed_str) if seed_str.strip().isdigit() else None
                variants = suno_studio.generate_variations(
                    vocab, preset_key, base_picks,
                    n=int(n), lock=_STRENGTH_LOCKS[strength], seed=seed,
                )
                st.session_state["rv_var_results"] = {
                    "variants": variants, "preset": preset_key,
                    "base_names": [c.get("name","") for c in chosen],
                }
            except Exception as e:
                st.error(f"변주 실패: {type(e).__name__}: {e}")

    res = st.session_state.get("rv_var_results")
    if res:
        st.divider()
        st.markdown(
            f"### 결과 {len(res['variants'])}개  ·  베이스: {', '.join(res['base_names'])}"
        )
        for i, var in enumerate(res["variants"], 1):
            with st.container(border=True):
                prompt = suno_studio.picks_to_prompt(vocab, res["preset"], var)
                bpm = (var.get("_bpm") or ["-"])[0]
                mood = (var.get("mood") or ["-"])[0]
                st.markdown(f"**변주 #{i}**  ·  무드 {mood}  ·  BPM {bpm}")
                st.code(prompt, language=None)
                with st.expander("picks (차원별)"):
                    st.json(var)
                save_cols = st.columns([2, 1, 3])
                name_input = save_cols[0].text_input(
                    "저장할 이름",
                    value=f"변주 #{i} ({res['base_names'][0] if res['base_names'] else '베이스'})",
                    key=f"rv_var_name_{i}",
                )
                cat_input = save_cols[1].text_input(
                    "카테고리",
                    value=(recipes.get_recipe(
                        next(iter([r['id'] for r in all_recipes
                                   if r.get('name') == res['base_names'][0]]), ""),
                    ) or {}).get("category") or "",
                    key=f"rv_var_cat_{i}",
                )
                if save_cols[2].button(f"💾 도서관에 저장 #{i}",
                                       key=f"rv_var_save_{i}",
                                       use_container_width=True):
                    try:
                        clean_picks = {k: list(v) for k, v in var.items()
                                       if not k.startswith("_") and v}
                        bpm_int = int(bpm) if str(bpm).isdigit() else None
                        recipes.save_recipe(
                            name_input or f"변주 #{i}",
                            res["preset"], clean_picks,
                            bpm=bpm_int,
                            category=cat_input,
                            notes=f"변주(강도: {strength}) — 베이스: {', '.join(res['base_names'])}",
                        )
                        st.success(f"저장됨: {name_input}")
                    except Exception as e:
                        st.error(f"저장 실패: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 탭 5: 가사 생성 (작사가 페르소나 → N개 가사 변주)
# ---------------------------------------------------------------------------

_DURATION_OPTIONS = list(lyrics_generator.DURATION_PRESETS.items())


def render_lyrics_generation_tab(gem_key: str, model: str) -> None:
    st.subheader("✨ 가사 생성")
    st.caption(
        "작사가 도서관의 페르소나(단일/장르 통합/직접 입력)를 기반으로 새 가사를 N개 생성합니다. "
        "곡 길이를 늘리면 절·후렴 구조가 자동 확장됩니다."
    )
    st.caption(COPY_HINT)

    entries = lyrics_library.list_entries()
    genres = lyrics_library.distinct_genres()

    persona_mode = st.radio(
        "페르소나 소스",
        options=["단일 항목 선택", "장르 통합 페르소나", "직접 입력"],
        horizontal=True, key="rv_gen_mode",
    )

    persona_text = ""
    used_genre = ""

    if persona_mode == "단일 항목 선택":
        if not entries:
            st.info("작사가 도서관이 비어 있습니다. 🔎 분석 탭에서 가사 있는 곡을 분석하세요.")
            return
        by_label = {f"[{e.get('genre') or '미분류'}] {e.get('name','')}": e for e in entries}
        picked_label = st.selectbox("페르소나 항목", options=list(by_label.keys()),
                                    key="rv_gen_entry")
        if picked_label:
            e = by_label[picked_label]
            persona_text = e.get("writer_prompt", "") or ""
            used_genre = e.get("genre") or ""
            with st.expander("선택된 페르소나 미리보기"):
                st.code(persona_text, language=None)
    elif persona_mode == "장르 통합 페르소나":
        if not genres:
            st.info("등록된 장르가 없습니다. 먼저 가사 데이터를 누적하세요.")
            return
        used_genre = st.selectbox("장르", options=genres, key="rv_gen_genre")
        if used_genre:
            persona_text = lyrics_library.merged_writer_prompt(used_genre)
            with st.expander(f"{used_genre} 통합 페르소나 미리보기"):
                st.code(persona_text, language="markdown")
    else:
        used_genre = st.text_input("장르 라벨(선택)", key="rv_gen_genre_free")
        persona_text = st.text_area(
            "페르소나 직접 입력",
            placeholder="예: 당신은 회상·그리움 톤의 트로트 작사가입니다…",
            height=150, key="rv_gen_persona_free",
        )

    st.divider()
    p = st.columns([2, 2, 1, 1])
    duration_label = p[0].selectbox(
        "곡 길이 / 구조",
        options=[v["label"] for _, v in _DURATION_OPTIONS],
        index=3, key="rv_gen_dur",  # 기본: 4분
    )
    duration_sec = next(k for k, v in _DURATION_OPTIONS if v["label"] == duration_label)
    n = p[1].number_input("가사 변주 개수", min_value=1, max_value=10, value=3,
                          key="rv_gen_n")
    structure = lyrics_generator.pick_structure(duration_sec)
    p[2].metric("벌스", structure["verses"])
    p[3].metric("후렴 반복", structure["chorus_reps"])

    theme = st.text_input(
        "주제 힌트 (선택) — 비우면 페르소나가 자유롭게",
        placeholder="예: 늦가을 어머니 산소 가는 길",
        key="rv_gen_theme",
    )

    if st.button("✨ 가사 생성", type="primary", key="rv_gen_run"):
        if not persona_text.strip():
            st.warning("페르소나가 비어 있습니다.")
        elif not gem_key.strip():
            st.error("Gemini API 키가 필요합니다. (사이드바)")
        else:
            try:
                with st.spinner(f"Gemini 가사 생성 중… ({n}개)"):
                    results = lyrics_generator.generate_lyrics(
                        persona=persona_text,
                        duration_sec=duration_sec,
                        n=int(n), theme=theme, genre=used_genre,
                        api_key=gem_key.strip(),
                        model=model.strip() or lyrics_generator.DEFAULT_MODEL,
                    )
                st.session_state["rv_gen_results"] = {
                    "variants": results, "genre": used_genre,
                    "duration_sec": duration_sec,
                }
                if not results:
                    st.warning("결과가 비어 있습니다. 다시 시도해 주세요.")
            except Exception as e:
                st.error(f"가사 생성 실패: {type(e).__name__}: {e}")

    res = st.session_state.get("rv_gen_results")
    if res and res.get("variants"):
        st.divider()
        st.markdown(f"### 결과 {len(res['variants'])}개")
        for i, v in enumerate(res["variants"], 1):
            with st.container(border=True):
                st.markdown(f"### 변주 #{i} — {v.get('title','(제목없음)')}")
                if v.get("theme"):
                    st.caption(f"주제: {v['theme']}")
                st.code(v["lyrics_text"], language=None)

                act = st.columns([2, 1, 1, 2])
                act[0].download_button(
                    "⬇ .txt 다운로드",
                    data=v["lyrics_text"].encode("utf-8"),
                    file_name=f"lyrics_{i}_{v.get('title','untitled')}.txt",
                    mime="text/plain",
                    key=f"rv_gen_dl_{i}", use_container_width=True,
                )
                if act[1].button(f"💾 도서관에 저장", key=f"rv_gen_save_{i}",
                                 use_container_width=True):
                    try:
                        lyrics_library.save_entry(
                            name=v.get("title") or f"생성 변주 #{i}",
                            genre=res.get("genre") or "",
                            lyrics_text=v["lyrics_text"],
                            patterns={},  # 생성물은 패턴 재추출 안 함
                            writer_prompt="",
                            summary=v.get("theme", ""),
                            transcript_source="generated",
                            notes=f"가사 생성기 변주 (목표 {res['duration_sec']}초)",
                        )
                        st.success(f"저장됨: {v.get('title')}")
                    except Exception as e:
                        st.error(f"저장 실패: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="곡 역설계 — 곡·작사가 프롬프트 도서관",
        page_icon="🔎", layout="wide",
    )
    st.title("🔎 곡 역설계 → 🎚️ 곡 + ✍️ 작사가 프롬프트 도서관")
    st.caption(
        "URL 한 번에 메타데이터·가사를 모아 두 자산을 동시에 만들고, 장르별로 누적합니다. "
        "곡 제작은 Suno 에서 직접 하시면 됩니다."
    )

    vocab = _load_vocab_cached()
    presets = suno_studio.list_presets(vocab)

    with st.sidebar:
        st.header("🔑 키 / 설정")
        yt_key = st.text_input(
            "YouTube API Key", type="password",
            value=os.getenv("YOUTUBE_API_KEY", ""),
        )
        gem_key = st.text_input(
            "Gemini API Key", type="password",
            value=os.getenv("GEMINI_API_KEY", ""),
            help="곡 역설계 + 작사 분석에 사용됩니다.",
        )
        model = st.text_input("Gemini 모델", value=analyzer.DEFAULT_MODEL)
        preset_key = st.selectbox(
            "프리셋(나라/장르 힌트, 곡 picks 용)",
            options=[k for k, _ in presets],
            format_func=lambda k: dict(presets)[k],
        )
        max_comments = st.slider("수집 댓글 수", 0, 50, 20)
        st.divider()
        st.markdown("**가사 추출 설정**")
        st.caption("1차로 유튜브 자막을 시도합니다(무료). 실패 시 Whisper fallback 옵션.")
        oai_key = st.text_input(
            "OpenAI API Key (Whisper용, 선택)", type="password",
            value=os.getenv("OPENAI_API_KEY", ""),
        )
        allow_whisper = st.checkbox(
            "🎙 자막 없을 때 Whisper API 로 받아쓰기",
            value=False,
            help="yt-dlp 로 오디오를 추출해 OpenAI Whisper 에 전송합니다. "
                 "본인 권리·CC 라이선스 영상에만 사용하세요.",
        )
        st.divider()
        st.markdown("**오디오 실측 (librosa)**")
        st.caption(
            "yt-dlp 로 오디오를 받아 BPM·키·에너지·리듬 밀도를 직접 측정합니다. "
            "곡당 30초~2분 소요. 추출된 실측치는 Gemini 분석에 단서로 주입됩니다."
        )
        allow_audio_probe = st.checkbox(
            "🎧 오디오 실측 분석 활성화 (BPM/키/에너지)",
            value=False,
            help="본인 권리·CC 라이선스 영상에만 사용하세요.",
        )
        st.divider()
        st.caption(
            f"저장소: `recipes.json` ({len(recipes.list_recipes())}개)  ·  "
            f"`lyrics_library.json` ({len(lyrics_library.list_entries())}개)"
        )

    tab_analyze, tab_song, tab_var, tab_lyrics, tab_gen = st.tabs([
        "🔎 분석",
        "🎚️ 곡 프롬프트 도서관",
        "✨ 곡 프롬프트 변주",
        "✍️ 작사가 프롬프트 도서관",
        "✨ 가사 생성",
    ])
    with tab_analyze:
        render_analyze_tab(
            vocab, yt_key, gem_key, oai_key, model, preset_key,
            max_comments, allow_whisper, allow_audio_probe,
        )
    with tab_song:
        render_song_library_tab(vocab)
    with tab_var:
        render_song_variation_tab(vocab)
    with tab_lyrics:
        render_lyrics_library_tab()
    with tab_gen:
        render_lyrics_generation_tab(gem_key, model)


if __name__ == "__main__":
    main()
