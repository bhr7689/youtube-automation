"""🔎 곡 역설계 단독 툴 — URL 한 줄로 Suno 프롬프트 카드까지.

별도 Streamlit 앱이다. app.py(메인 대시보드)와 독립적으로 켤 수 있다.

실행:
    streamlit run reverse_app.py

흐름:
    유튜브 URL/ID 입력
        ↓ YouTube Data API (snippet+statistics+commentThreads)
    제목/채널/태그/설명/상위 댓글 자동 수집
        ↓ analyzer.analyze_metadata (Gemini, vocab.json 통제어휘 안)
    Suno picks + mood + bpm + 새 어휘 후보
        ↓ suno_studio.picks_to_prompt
    완성된 Suno 프롬프트 문자열
        ↓ (옵션) 레시피 저장 / 파이프라인 inbox 투입

키: YOUTUBE_API_KEY(필수), GEMINI_API_KEY(필수). 둘 다 .env 로드 우선.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
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
# YouTube Data API 호출 (collect.py 와 같은 방식)
# ---------------------------------------------------------------------------

def fetch_video_metadata(api_key: str, video_id: str, *, max_comments: int = 20) -> dict:
    """단일 영상의 snippet/statistics + 상위 댓글을 한 번에 가져온다."""
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
# 파이프라인 inbox 잡 생성 (mp3 없이 메타만 — 사람이 mp3 떨굴 자리)
# ---------------------------------------------------------------------------

def write_pipeline_stub(
    *, root: str | os.PathLike, title: str, prompt: str,
    picks: dict, meta: dict,
) -> Path:
    """inbox/<job_id>/ 폴더와 job.json + style.txt 만 만들어둔다.

    오디오·배경은 사람이 Suno 결과를 떨굴 자리. pipeline.py 가 자동 합성한다.
    """
    job_id = f"reverse_{int(time.time())}_{(meta.get('video_id') or 'x')[:8]}"
    inbox = Path(root) / "inbox" / job_id
    inbox.mkdir(parents=True, exist_ok=True)

    job = {
        "title": title or meta.get("title") or "역설계 자동 잡",
        "background_color": "0x101418",
        "resolution": "1920x1080",
        "audio_bitrate": "192k",
        "crf": 22,
        "_source": {
            "kind": "reverse_engineering",
            "video_id": meta.get("video_id"),
            "url": f"https://www.youtube.com/watch?v={meta.get('video_id')}",
            "channel": meta.get("channel"),
            "picks": picks,
            "suno_prompt": prompt,
        },
    }
    (inbox / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (inbox / "style.txt").write_text(prompt, encoding="utf-8")
    (inbox / "README.txt").write_text(
        "이 폴더에 Suno mp3 를 떨구면 pipeline.py 가 자동으로 MP4 를 만듭니다.\n"
        "배경 이미지(png/jpg)를 함께 두면 그걸 배경으로 씁니다(없으면 단색).\n",
        encoding="utf-8",
    )
    return inbox


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def _load_vocab_cached() -> dict:
    if "_vocab" not in st.session_state:
        st.session_state["_vocab"] = suno_studio.load_vocab()
    return st.session_state["_vocab"]


def main() -> None:
    st.set_page_config(page_title="곡 역설계 — Suno 프롬프트 추출", page_icon="🔎", layout="wide")
    st.title("🔎 곡 역설계 단독 툴")
    st.caption(
        "유튜브 링크 한 줄 → 메타데이터 자동 수집 → Gemini 역설계 → Suno 프롬프트 카드. "
        "오디오는 받지 않음(ToS 안전). vocab.json 통제 어휘로 정렬됨."
    )

    vocab = _load_vocab_cached()
    presets = suno_studio.list_presets(vocab)

    # --- 사이드바: 키 / 설정 ---
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
        pipe_root = st.text_input(
            "파이프라인 루트",
            value=os.getenv("PIPELINE_ROOT", "./pipeline_data"),
            help="inbox 투입 시 사용할 폴더. pipeline.py 와 동일 경로여야 합니다.",
        )

    # --- 입력 ---
    url = st.text_input(
        "유튜브 URL 또는 video_id",
        placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX  또는  XXXXXXXXXXX",
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
                    meta = fetch_video_metadata(yt_key.strip(), vid, max_comments=max_comments)
                st.session_state["rv_meta"] = meta
                st.session_state.pop("rv_result", None)
                st.success(f"수집 완료: {meta['title']}")
            except Exception as e:
                st.error(f"수집 실패: {type(e).__name__}: {e}")

    meta: dict[str, Any] | None = st.session_state.get("rv_meta")

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
                st.text_area("설명", value=meta.get("description", ""), height=120, disabled=True)
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

    # --- 결과 카드 ---
    if result and meta:
        st.divider()
        st.subheader("🎚️ Suno 프롬프트 카드")
        prompt_text = suno_studio.picks_to_prompt(vocab, result["preset"], result["picks"])

        mcols = st.columns(3)
        mcols[0].metric("무드", result.get("mood") or "-")
        mcols[1].metric("BPM", result.get("bpm") or "-")
        mcols[2].metric("프리셋", result["preset"])
        if result.get("rationale"):
            st.caption(f"💡 근거: {result['rationale']}")

        st.code(prompt_text, language=None)

        with st.expander("picks (차원별 원본)"):
            st.json(result["picks"])

        new_terms = result.get("new_terms") or {}
        if new_terms:
            st.markdown("**🧩 새 어휘 후보 (vocab.json 보완용)**")
            st.json(new_terms)

        st.divider()
        st.subheader("📦 다음 단계")
        save_col, send_col = st.columns(2)

        with save_col:
            st.markdown("**레시피로 저장**")
            rname = st.text_input(
                "레시피 이름",
                value=meta["title"][:40] or "역설계 레시피",
                key="rv_rname",
            )
            if st.button("💾 recipes.json 에 저장", use_container_width=True):
                try:
                    rec = recipes.save_recipe(
                        rname or meta["title"] or "역설계 레시피",
                        result["preset"], result["picks"],
                        bpm=result.get("bpm"),
                        source_video_id=meta.get("video_id"),
                        notes=result.get("rationale", ""),
                    )
                    st.success(f"저장됨: {rec['name']}")
                except Exception as e:
                    st.error(f"저장 실패: {type(e).__name__}: {e}")

        with send_col:
            st.markdown("**파이프라인 inbox 로 보내기 (mp3 자리 만들기)**")
            st.caption(
                "프롬프트와 메타가 담긴 잡 폴더를 만들어둡니다. "
                "Suno 에서 받은 mp3 를 그 폴더에 떨구면 pipeline.py 가 MP4 로 합성합니다."
            )
            if st.button("📥 inbox 폴더 만들기", use_container_width=True):
                try:
                    job_dir = write_pipeline_stub(
                        root=pipe_root,
                        title=meta["title"],
                        prompt=prompt_text,
                        picks=result["picks"],
                        meta=meta,
                    )
                    st.success(f"생성: `{job_dir}`")
                    st.caption("이 폴더에 mp3 (그리고 선택 배경 이미지) 를 넣고 "
                               "`python pipeline.py --once` 실행.")
                except Exception as e:
                    st.error(f"폴더 생성 실패: {type(e).__name__}: {e}")

    elif not meta:
        st.info(
            "👆 위에 URL 을 넣고 **① 메타 가져오기** → **② 역설계 분석** 순서로 진행하세요. "
            "키는 사이드바에 있습니다."
        )


if __name__ == "__main__":
    main()
