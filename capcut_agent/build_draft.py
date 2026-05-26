"""보존 구간 → CapCut 점프컷 드래프트 생성 (pycapcut).

각 보존 구간을 하나의 VideoSegment 로 만든다.
- source_timerange: 원본 영상에서 잘라올 위치(무음 제거)
- target_timerange: 타임라인상의 위치(앞 구간 뒤에 붙여 무음을 없앰)
VideoSegment 는 오디오를 포함하므로 영상 트랙만으로 음성이 싱크된 채 점프컷된다.
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

import pycapcut as p

SEC = 1_000_000  # 마이크로초


def default_draft_folder() -> str:
    """CapCut 드래프트 루트 폴더.

    우선순위: 환경변수 CAPCUT_DRAFT_DIR → OS 표준 위치(존재할 때) → 로컬 폴백.
    사용자 진단(detect_capcut.py) 결과 표준 위치는 flat 레이아웃으로 pycapcut 호환.
    """
    env = os.environ.get("CAPCUT_DRAFT_DIR")
    if env:
        return os.path.expandvars(os.path.expanduser(env))
    if sys.platform.startswith("win"):
        std = os.path.expandvars(
            r"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft"
        )
        return std
    if sys.platform == "darwin":
        return os.path.expanduser(
            "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"
        )
    # Linux 등: 검증용 로컬 폴더
    return os.path.abspath("./capcut_drafts")


def _us(seconds: float) -> int:
    return int(round(seconds * SEC))


def build_jumpcut_draft(
    video_path: str,
    keeps: List[Tuple[float, float]],
    width: int,
    height: int,
    fps: int = 30,
    draft_name: Optional[str] = None,
    draft_folder: Optional[str] = None,
) -> str:
    """점프컷 드래프트를 만들고 드래프트 폴더 경로를 반환."""
    if not keeps:
        raise ValueError("보존 구간이 없습니다. 영상 전체가 무음으로 감지되었을 수 있습니다.")

    video_path = os.path.abspath(video_path)
    if draft_name is None:
        base = os.path.splitext(os.path.basename(video_path))[0]
        draft_name = f"{base}_jumpcut"
    root = draft_folder or default_draft_folder()
    os.makedirs(root, exist_ok=True)

    folder = p.DraftFolder(root)
    script = folder.create_draft(draft_name, width, height, fps=fps, allow_replace=True)

    material = p.VideoMaterial(video_path)
    script.add_material(material)
    script.add_track(p.TrackType.video)

    timeline = 0  # 타임라인 누적 위치(µs)
    for start, end in keeps:
        dur = _us(end - start)
        if dur <= 0:
            continue
        seg = p.VideoSegment(
            material,
            target_timerange=p.Timerange(timeline, dur),
            source_timerange=p.Timerange(_us(start), dur),
        )
        script.add_segment(seg)
        timeline += dur

    script.save()
    return os.path.join(root, draft_name)


if __name__ == "__main__":
    from silence import analyze

    if len(sys.argv) < 2:
        print("usage: python build_draft.py <video> [draft_folder]")
        raise SystemExit(1)
    video = sys.argv[1]
    folder = sys.argv[2] if len(sys.argv) > 2 else None
    info, silences, keeps = analyze(video)
    print(f"media: {info.width}x{info.height} {info.fps}fps {info.duration:.2f}s")
    print(f"보존 구간 {len(keeps)}개, 컷 {max(0, len(keeps) - 1)}개")
    path = build_jumpcut_draft(
        video, keeps, info.width, info.height, info.fps, draft_folder=folder
    )
    kept = sum(e - s for s, e in keeps)
    print(f"✅ 드래프트 생성: {path}")
    print(f"   {info.duration:.2f}s → {kept:.2f}s (무음 {info.duration - kept:.2f}s 제거)")
