"""ffmpeg / SRT 미디어 처리 코어.

Streamlit 대시보드(app.py)와 무인 자동화 파이프라인(pipeline.py)이 공유하는
순수 함수 모음. Streamlit 의존성이 없어 헤드리스 환경에서도 그대로 import 가능.
"""

from __future__ import annotations

import shutil
import subprocess


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_duration(path: str) -> float | None:
    """초 단위 길이. ffprobe 없으면 None 반환."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None


def concat_audio_files(
    audio_paths: list[str], output_path: str, *, bitrate: str = "320k"
) -> tuple[bool, str]:
    """여러 오디오를 하나로 이어붙임. concat 필터로 재인코딩(샘플레이트 통일)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다."
    if not audio_paths:
        return False, "이어붙일 오디오가 없습니다."
    if len(audio_paths) == 1:
        try:
            shutil.copyfile(audio_paths[0], output_path)
            return True, "단일 파일 복사 완료."
        except Exception as e:
            return False, f"단일 파일 복사 실패: {e}"

    cmd: list[str] = [ffmpeg, "-y", "-hide_banner"]
    for p in audio_paths:
        cmd += ["-i", p]
    n = len(audio_paths)
    filter_str = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    cmd += [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "aac",
        "-b:a", bitrate,
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60 * 2)
    except subprocess.TimeoutExpired:
        return False, "오디오 이어붙이기가 2시간 안에 끝나지 않았습니다."
    return proc.returncode == 0, (proc.stderr or "")[-2400:]


def format_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(tracks: list[dict]) -> str:
    """
    tracks: [{"title": str, "duration": float, "lyrics_lines": list[str]}]
    각 트랙 안에서는 가사 라인을 트랙 길이에 따라 균등 분배,
    트랙 간에는 누적 타임스탬프로 SRT 한 파일을 만든다.
    """
    out: list[str] = []
    cumulative = 0.0
    counter = 1
    for tr in tracks:
        duration = max(float(tr.get("duration", 0) or 0), 0.0)
        lines = [ln.strip() for ln in tr.get("lyrics_lines", []) if ln.strip()]
        if not lines or duration <= 0:
            cumulative += duration
            continue
        per_line = duration / len(lines)
        for i, line in enumerate(lines):
            start = cumulative + i * per_line
            end = cumulative + (i + 1) * per_line
            out.append(str(counter))
            out.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
            out.append(line)
            out.append("")
            counter += 1
        cumulative += duration
    return "\n".join(out).strip() + "\n"


def encode_music_video(
    audio_path: str,
    visual_path: str,
    output_path: str,
    *,
    is_image: bool,
    resolution: str = "1920x1080",
    audio_bitrate: str = "192k",
    crf: int = 22,
    fade_seconds: float = 0.0,
    audio_duration: float | None = None,
    subtitles_path: str | None = None,
) -> tuple[bool, str]:
    """ffmpeg 로 합성. (성공여부, 로그 꼬리 ~2KB) 반환."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg 가 PATH 에 없습니다. 시스템에 ffmpeg 를 설치해주세요."

    cmd: list[str] = [ffmpeg, "-y", "-hide_banner"]

    # 입력 0: 비주얼 (이미지면 loop, 영상이면 stream_loop)
    if is_image:
        cmd += ["-loop", "1"]
    else:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", visual_path]

    # 입력 1: 오디오
    cmd += ["-i", audio_path]

    # ffmpeg 필터(scale/pad)는 "WxH" 가 아닌 "W:H" 형식을 요구한다.
    try:
        _w, _h = resolution.lower().split("x")
        res_pair = f"{int(_w)}:{int(_h)}"
    except ValueError:
        res_pair = resolution

    # 해상도 맞춤(레터박스), yuv420p 로 호환성 확보.
    vf_parts = [
        f"scale={res_pair}:force_original_aspect_ratio=decrease",
        f"pad={res_pair}:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=1",
    ]
    if subtitles_path:
        # 경로의 콜론/역슬래시 등 ffmpeg 필터 그래프 특수문자 이스케이프.
        esc = (
            subtitles_path
            .replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )
        vf_parts.append(
            f"subtitles='{esc}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF&,"
            "OutlineColour=&H80000000&,BorderStyle=3,Outline=2,Shadow=0,MarginV=60'"
        )
    vf = ",".join(vf_parts)

    cmd += [
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        "-shortest",
    ]
    if is_image:
        cmd += ["-tune", "stillimage", "-r", "24"]

    # 오디오 페이드 인/아웃 (선택).
    if fade_seconds > 0 and audio_duration and audio_duration > fade_seconds * 2:
        fade_out_start = max(audio_duration - fade_seconds, 0)
        cmd += [
            "-af",
            f"afade=t=in:st=0:d={fade_seconds},"
            f"afade=t=out:st={fade_out_start}:d={fade_seconds}",
        ]

    cmd.append(output_path)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
    except subprocess.TimeoutExpired:
        return False, "1시간 안에 인코딩이 끝나지 않았습니다. 해상도/CRF 를 조정해보세요."
    log_tail = (proc.stderr or "")[-2400:]
    return proc.returncode == 0, log_tail


def fmt_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "??"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
