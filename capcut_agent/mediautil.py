"""ffmpeg/ffprobe 탐색 + 시간 포맷 (캡컷 에이전트 공용).

기존 저장소 media_core.py 의 검증된 헬퍼를 가져오되, Windows 런타임을 위해
PATH 뿐 아니라 흔한 설치 경로까지 뒤지도록 보강했다. (winget/choco/수동설치 시
ffmpeg 가 PATH 에 안 잡히는 경우가 흔하다 — 트랙 C 의 대표 함정.)
"""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from typing import List, Optional


def _candidates(name: str) -> List[str]:
    exe = name + (".exe" if sys.platform.startswith("win") else "")
    paths: List[str] = []
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA", "")
        prog = os.environ.get("ProgramFiles", r"C:\Program Files")
        # winget 설치 위치(버전 폴더 포함)는 글롭으로 따로 처리
        paths += [
            os.path.join(prog, "ffmpeg", "bin", exe),
            rf"C:\ffmpeg\bin\{exe}",
            os.path.join(local, "Microsoft", "WinGet", "Links", exe),
        ]
        # choco shim
        paths.append(rf"C:\ProgramData\chocolatey\bin\{exe}")
    elif sys.platform == "darwin":
        paths += [f"/opt/homebrew/bin/{exe}", f"/usr/local/bin/{exe}"]
    else:
        paths += [f"/usr/bin/{exe}", f"/usr/local/bin/{exe}"]
    return paths


@lru_cache(maxsize=8)
def find_bin(name: str) -> Optional[str]:
    """PATH → 흔한 설치 경로 순으로 ffmpeg/ffprobe 를 찾는다."""
    found = shutil.which(name)
    if found:
        return found
    for cand in _candidates(name):
        if os.path.isfile(cand):
            return cand
    # winget 버전 폴더 글롭 (Windows)
    if sys.platform.startswith("win"):
        import glob
        local = os.environ.get("LOCALAPPDATA", "")
        pattern = os.path.join(
            local, "Microsoft", "WinGet", "Packages",
            "*FFmpeg*", "**", name + ".exe",
        )
        hits = glob.glob(pattern, recursive=True)
        if hits:
            return hits[0]
    return None


def require_bin(name: str) -> str:
    path = find_bin(name)
    if not path:
        hint = (
            "winget install Gyan.FFmpeg"
            if sys.platform.startswith("win")
            else "brew install ffmpeg"
            if sys.platform == "darwin"
            else "apt-get install ffmpeg"
        )
        raise RuntimeError(f"{name} 를 찾을 수 없습니다. 설치: {hint}")
    return path


def format_srt_time(seconds: float) -> str:
    """SRT 타임코드 HH:MM:SS,mmm (media_core 와 동일 규약)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_duration(seconds: Optional[float]) -> str:
    if not seconds or seconds <= 0:
        return "??"
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    h = int(seconds // 3600)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
