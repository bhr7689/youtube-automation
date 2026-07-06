"""원본 소스 확보 — 합성 테스트 / yt-dlp(옵트인·가드레일).

⚠️ 저작권: 타인 저작물 원본을 무단 다운로드·재업로드하면 안 된다. yt-dlp 경로는
사용자가 '본인 영상/CC/허가 소스'임을 확인(copyright_ack)해야만 동작. 기본은 테스트 소스.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import renderer

SRC_DIR = renderer.SRC_DIR


def test_source(duration_s: int = 60) -> str:
    return renderer.generate_test_source(duration_s)


def ytdlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def fetch_url(url: str, max_seconds: int = 180) -> dict:
    """yt-dlp 로 소스 다운로드(옵트인 후 호출). 성공 시 {ok,path}, 실패 시 {ok:False,error}.

    가드레일: 호출부(main)에서 copyright_ack 확인. 여기선 다운로드만.
    """
    if not ytdlp_available():
        return {"ok": False, "error": "yt-dlp 미설치 — 사용자 PC 에서 `pip install yt-dlp` 후 사용."}
    os.makedirs(SRC_DIR, exist_ok=True)
    out = os.path.join(SRC_DIR, "src_%(id)s.%(ext)s")
    try:
        r = subprocess.run(
            ["yt-dlp", "-f", "mp4/best", "--no-playlist", "-o", out, url],
            capture_output=True, text=True, timeout=max_seconds)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or "다운로드 실패")[-300:]}
        # 가장 최근 파일
        files = sorted(
            (os.path.join(SRC_DIR, f) for f in os.listdir(SRC_DIR) if f.startswith("src_")),
            key=os.path.getmtime, reverse=True)
        return {"ok": True, "path": files[0]} if files else {"ok": False, "error": "파일 없음"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "다운로드 시간 초과"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
