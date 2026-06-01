"""유튜브 자막 → 가사 텍스트 추출 (Whisper API fallback).

전략:
    1) youtube-transcript-api 로 자막 가져오기 시도
       - 수동 자막(채널 주인이 단 것) 우선 → 자동 자막 → 다른 언어 + 자동 번역
    2) 자막이 없거나 비활성화면, OPENAI_API_KEY 가 주어진 경우 Whisper API 로 fallback
       - yt-dlp 로 오디오만 추출 → OpenAI audio.transcriptions.create

본 모듈은 Streamlit 의존성이 없다. 헤드리스 테스트/CLI 호출 가능.
저작권 안전: Whisper fallback 은 사용자가 명시적으로 활성화한 경우에만 작동.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path


DEFAULT_LANGS = ("ko", "en", "ja", "zh-Hans", "zh-Hant")


@dataclass
class TranscriptResult:
    text: str = ""
    source: str = ""              # "manual" | "auto" | "translated" | "whisper" | ""
    language: str = ""
    segments: list[dict] = field(default_factory=list)
    error: str = ""               # 사람이 읽을 수 있는 실패 사유

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


# ---------------------------------------------------------------------------
# 1) YouTube 자막 시도
# ---------------------------------------------------------------------------

def _segments_to_text(segments: list[dict]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for s in segments:
        line = (s.get("text") or "").replace("\n", " ").strip()
        if not line:
            continue
        # 같은 줄이 연속해서 반복되면(자동 자막 중복) 한 번만 남김
        if lines and lines[-1] == line:
            continue
        lines.append(line)
        seen.add(line)
    return "\n".join(lines)


def fetch_youtube_transcript(
    video_id: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGS,
) -> TranscriptResult:
    """수동 → 자동 → 번역 순서로 자막을 시도. 모두 실패하면 error 채워서 반환."""
    try:
        from youtube_transcript_api import (
            YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound,
            VideoUnavailable,
        )
    except ImportError as e:
        return TranscriptResult(error=f"youtube-transcript-api 미설치: {e}")

    api = YouTubeTranscriptApi()
    try:
        tlist = api.list(video_id)
    except TranscriptsDisabled:
        return TranscriptResult(error="이 영상은 자막이 비활성화되어 있습니다.")
    except VideoUnavailable:
        return TranscriptResult(error="영상을 찾을 수 없거나 접근 불가합니다.")
    except Exception as e:
        return TranscriptResult(error=f"자막 목록 조회 실패: {type(e).__name__}: {e}")

    # (a) 수동 자막
    try:
        t = tlist.find_manually_created_transcript(list(languages))
        snippets = t.fetch().to_raw_data()
        text = _segments_to_text(snippets)
        if text:
            return TranscriptResult(
                text=text, source="manual",
                language=t.language_code, segments=snippets,
            )
    except (NoTranscriptFound, Exception):
        pass

    # (b) 자동 자막
    try:
        t = tlist.find_generated_transcript(list(languages))
        snippets = t.fetch().to_raw_data()
        text = _segments_to_text(snippets)
        if text:
            return TranscriptResult(
                text=text, source="auto",
                language=t.language_code, segments=snippets,
            )
    except (NoTranscriptFound, Exception):
        pass

    # (c) 다른 언어 자막을 우선 언어로 자동 번역
    for t in tlist:
        if not getattr(t, "is_translatable", False):
            continue
        target = languages[0]
        try:
            translated = t.translate(target).fetch().to_raw_data()
            text = _segments_to_text(translated)
            if text:
                return TranscriptResult(
                    text=text, source="translated",
                    language=target, segments=translated,
                )
        except Exception:
            continue

    return TranscriptResult(error="사용 가능한 자막이 없습니다.")


# ---------------------------------------------------------------------------
# 2) Whisper fallback (옵트인)
# ---------------------------------------------------------------------------

def _have_yt_dlp() -> bool:
    return shutil.which("yt-dlp") is not None or _import_yt_dlp() is not None


def _import_yt_dlp():
    try:
        import yt_dlp  # type: ignore
        return yt_dlp
    except ImportError:
        return None


def _download_audio(video_id: str, workdir: Path) -> Path:
    """yt-dlp 로 m4a(또는 opus) 오디오만 추출. ffmpeg 가 있으면 mp3 로 변환."""
    yt_dlp = _import_yt_dlp()
    out_template = str(workdir / f"{video_id}.%(ext)s")
    if yt_dlp is None:
        # 시스템 바이너리 fallback
        cmd = [
            "yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio",
            "-o", out_template, f"https://www.youtube.com/watch?v={video_id}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"yt-dlp 실패: {(proc.stderr or '')[-400:]}"
            )
    else:
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    candidates = list(workdir.glob(f"{video_id}.*"))
    if not candidates:
        raise RuntimeError("오디오 추출 후 파일을 찾을 수 없습니다.")
    return candidates[0]


def fetch_whisper_transcript(
    video_id: str,
    *,
    api_key: str,
    model: str = "whisper-1",
    language: str | None = "ko",
    workdir: str | os.PathLike | None = None,
) -> TranscriptResult:
    """yt-dlp 로 오디오만 받아 Whisper API 로 받아쓰기.

    저작권/ToS: 사용자가 권리 보유한 영상이거나 학습 목적 fair use 임을 가정한다.
    호출 측에서 사용자 동의를 받은 뒤에만 호출해야 한다.
    """
    if not api_key:
        return TranscriptResult(error="OpenAI API 키가 필요합니다.")
    try:
        from openai import OpenAI
    except ImportError as e:
        return TranscriptResult(error=f"openai 미설치: {e}")

    cleanup = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="whisper_dl_"))
        cleanup = True
    else:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

    try:
        audio_path = _download_audio(video_id, workdir)
    except Exception as e:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)
        return TranscriptResult(error=f"오디오 추출 실패: {type(e).__name__}: {e}")

    try:
        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=model, file=f,
                language=language or None,
                response_format="verbose_json",
            )
        text = (getattr(resp, "text", None) or "").strip()
        segments_raw = getattr(resp, "segments", None) or []
        segments: list[dict] = []
        for s in segments_raw:
            d = s if isinstance(s, dict) else getattr(s, "model_dump", lambda: {})()
            if d:
                segments.append({
                    "text": d.get("text", ""),
                    "start": d.get("start"),
                    "duration": d.get("end", 0) - d.get("start", 0)
                                if d.get("end") is not None else None,
                })
        return TranscriptResult(
            text=text, source="whisper",
            language=language or "", segments=segments,
        )
    except Exception as e:
        return TranscriptResult(error=f"Whisper 호출 실패: {type(e).__name__}: {e}")
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3) 통합 진입점
# ---------------------------------------------------------------------------

def get_lyrics(
    video_id: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGS,
    openai_key: str | None = None,
    allow_whisper: bool = False,
) -> TranscriptResult:
    """1차 자막 시도 → 실패 시(allow_whisper=True) Whisper fallback."""
    r = fetch_youtube_transcript(video_id, languages=languages)
    if r.ok:
        return r
    if allow_whisper and openai_key:
        return fetch_whisper_transcript(
            video_id, api_key=openai_key, language=languages[0],
        )
    return r


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, json

    p = argparse.ArgumentParser(description="유튜브 자막 → 가사 추출")
    p.add_argument("video_id", help="11자 YouTube video_id 또는 URL")
    p.add_argument("--whisper", action="store_true",
                   help="자막 없으면 OpenAI Whisper API 로 fallback")
    p.add_argument("--openai-key", default=os.getenv("OPENAI_API_KEY", ""))
    args = p.parse_args()

    vid = args.video_id
    # URL 이면 v= 추출
    import re
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", vid)
    if m:
        vid = m.group(1)

    r = get_lyrics(vid, openai_key=args.openai_key, allow_whisper=args.whisper)
    print(json.dumps({
        "source": r.source, "language": r.language, "error": r.error,
        "n_segments": len(r.segments), "text_preview": r.text[:300],
    }, ensure_ascii=False, indent=2))
