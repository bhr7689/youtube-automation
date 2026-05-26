"""무음 감지 → 보존(speech) 구간 계산.

ffmpeg `silencedetect` 필터로 무음 구간을 찾고, 그 여집합(말하는 구간)에
약간의 패딩을 붙여 점프컷용 '보존 구간' 리스트를 만든다.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import List, Tuple

from mediautil import require_bin as _ffbin


@dataclass
class MediaInfo:
    width: int
    height: int
    fps: int
    duration: float  # seconds


def probe(path: str) -> MediaInfo:
    """ffprobe 로 해상도·fps·길이를 읽는다."""
    out = subprocess.run(
        [
            _ffbin("ffprobe"), "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", path,
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    fps = round(float(num) / float(den)) if float(den) else 30
    return MediaInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps or 30,
        duration=float(data["format"]["duration"]),
    )


def detect_silence(
    path: str, noise_db: float = -30.0, min_silence: float = 0.5
) -> List[Tuple[float, float]]:
    """무음 구간 [(start, end), ...] (초)."""
    proc = subprocess.run(
        [
            _ffbin("ffmpeg"), "-hide_banner", "-nostats", "-i", path,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    log = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", log)]
    silences: List[Tuple[float, float]] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        silences.append((s, e if e is not None else float("inf")))
    return silences


def keep_regions(
    duration: float,
    silences: List[Tuple[float, float]],
    pad: float = 0.10,
    min_keep: float = 0.20,
    merge_gap: float = 0.0,
) -> List[Tuple[float, float]]:
    """무음의 여집합(말하는 구간)에 패딩을 붙여 보존 구간을 만든다.

    - pad: 컷이 말 시작/끝을 자르지 않도록 양쪽으로 무음을 조금 남김
    - min_keep: 이보다 짧은 보존 구간은 버림(프레임 슬리버 방지)
    - merge_gap: 보존 구간 사이 간격이 이 값 이하이면 합침
    """
    # 무음을 정규화: inf 끝은 duration 으로 클램프, 정렬·병합
    norm: List[Tuple[float, float]] = []
    for s, e in sorted(silences):
        s = max(0.0, s)
        e = min(duration, e if e != float("inf") else duration)
        if e <= s:
            continue
        if norm and s <= norm[-1][1]:
            norm[-1] = (norm[-1][0], max(norm[-1][1], e))
        else:
            norm.append((s, e))

    # 여집합 = 보존 구간
    keeps: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in norm:
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        keeps.append((cursor, duration))

    # 패딩 적용 + 클램프
    padded: List[Tuple[float, float]] = []
    for s, e in keeps:
        padded.append((max(0.0, s - pad), min(duration, e + pad)))

    # 패딩으로 겹치거나 가까워진 구간 병합
    merged: List[Tuple[float, float]] = []
    for s, e in padded:
        if merged and s - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    return [(s, e) for s, e in merged if (e - s) >= min_keep]


def analyze(
    path: str,
    noise_db: float = -30.0,
    min_silence: float = 0.5,
    pad: float = 0.10,
    min_keep: float = 0.20,
) -> Tuple[MediaInfo, List[Tuple[float, float]], List[Tuple[float, float]]]:
    """편의 함수: (MediaInfo, 무음구간, 보존구간)."""
    info = probe(path)
    silences = detect_silence(path, noise_db=noise_db, min_silence=min_silence)
    keeps = keep_regions(info.duration, silences, pad=pad, min_keep=min_keep)
    return info, silences, keeps


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python silence.py <video>")
        raise SystemExit(1)
    info, silences, keeps = analyze(sys.argv[1])
    print(f"media: {info.width}x{info.height} {info.fps}fps {info.duration:.2f}s")
    print(f"silences ({len(silences)}): {silences}")
    print(f"keeps ({len(keeps)}): {keeps}")
    removed = info.duration - sum(e - s for s, e in keeps)
    print(f"제거됨: {removed:.2f}s / {info.duration:.2f}s")
