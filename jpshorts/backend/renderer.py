"""실제 렌더 — 컷 플랜을 ffmpeg 로 실행해 세로 쇼츠 mp4 생성 (B안 실행판).

- generate_test_source(): 저작권 안전한 합성 테스트 소스(장면번호·타임코드) 생성.
- render_plan(): 플랜의 세그먼트별로 컷+줌+크롭+미러+속도 → concat → 자막 burn-in
  + 내레이션 오디오 mux → output_shorts.mp4.

실제 원본(yt-dlp)은 source.py 에서 옵트인·가드레일과 함께. 여기선 '소스 파일'만 있으면
그게 무엇이든(테스트/CC/본인영상) 렌더한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess

CUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cut_plans")
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sources")


def _ff() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "default=nk=1:nw=1", path],
            capture_output=True, text=True, timeout=20)
        return float(out.stdout.strip() or 0)
    except Exception:
        return 0.0


def generate_test_source(duration_s: int = 60, name: str = "test_source.mp4") -> str:
    """저작권 안전한 합성 소스 — 색이 변하고 타임코드가 보여 컷이 눈에 띈다."""
    os.makedirs(SRC_DIR, exist_ok=True)
    path = os.path.join(SRC_DIR, name)
    if os.path.isfile(path) and _ffprobe_duration(path) >= duration_s - 1:
        return path
    # 가로 원본(1280x720)처럼 — 이후 세로로 크롭/줌
    vf = ("drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
          "text='SOURCE  %{pts\\:hms}':fontcolor=white:fontsize=54:x=(w-tw)/2:y=h-120,"
          "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
          "text='TEST CLIP (합성)':fontcolor=white@0.6:fontsize=40:x=(w-tw)/2:y=80")
    cmd = [
        _ff(), "-y",
        "-f", "lavfi", "-i", f"gradients=s=1280x720:d={duration_s}:speed=0.05",
        "-t", str(duration_s), "-vf", vf, "-r", "30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=180)
    return path


def _build_narration(job_dir: str, out_wav: str, total_ms: int) -> str | None:
    """narration job 의 문장 wav 들을 pause 반영해 하나로 합침(있으면). 없으면 None."""
    audio_dir = os.path.join(job_dir, "audio")
    if not os.path.isdir(audio_dir):
        return None
    wavs = sorted(f for f in os.listdir(audio_dir) if f.endswith(".wav"))
    if not wavs:
        return None
    listp = out_wav + ".txt"
    with open(listp, "w") as f:
        for w in wavs:
            f.write(f"file '{os.path.join(audio_dir, w)}'\n")
    try:
        subprocess.run([_ff(), "-y", "-f", "concat", "-safe", "0", "-i", listp,
                        "-ar", "48000", "-ac", "1", out_wav],
                       capture_output=True, timeout=120)
        return out_wav if os.path.isfile(out_wav) else None
    except Exception:
        return None


def render_plan(plan: dict, source_path: str, job_dir: str | None = None) -> dict:
    """컷 플랜 → output_shorts.mp4. 반환 {ok, out_path, error, log}."""
    W = plan["canvas"]["w"]
    H = plan["canvas"]["h"]
    plan_id = plan["plan_id"]
    work = os.path.join(CUT_DIR, plan_id + "_render")
    seg_dir = os.path.join(work, "seg")
    os.makedirs(seg_dir, exist_ok=True)
    src_dur = _ffprobe_duration(source_path) or 60.0

    seg_files = []
    for seg in plan["segments"]:
        i = seg["seg_id"]
        ss = min(max(seg["src_start_ms"] / 1000.0, 0), max(src_dur - 0.6, 0))
        out_dur = max(seg["dur_ms"] / 1000.0, 0.3)
        z = seg["zoom"]
        vf = [f"scale={W}:-2", f"crop={W}:{H}",
              f"scale=iw*{z}:ih*{z}", f"crop={W}:{H}"]
        if seg["mirror"]:
            vf.append("hflip")
        if abs(seg["speed"] - 1.0) > 0.001:
            vf.append(f"setpts=PTS/{seg['speed']}")
        segf = os.path.join(seg_dir, f"seg{i:03d}.mp4")
        cmd = [_ff(), "-y", "-ss", f"{ss:.2f}", "-i", source_path,
               "-t", f"{out_dur:.2f}", "-vf", ",".join(vf), "-an",
               "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-preset", "ultrafast", segf]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.isfile(segf):
            seg_files.append(segf)
        elif r.returncode != 0:
            return {"ok": False, "error": r.stderr.decode()[-400:]}

    if not seg_files:
        return {"ok": False, "error": "세그먼트 렌더 실패"}

    # concat
    listp = os.path.join(work, "list.txt")
    with open(listp, "w") as f:
        for s in seg_files:
            f.write(f"file '{s}'\n")
    video = os.path.join(work, "_video.mp4")
    subprocess.run([_ff(), "-y", "-f", "concat", "-safe", "0", "-i", listp,
                    "-c", "copy", video], capture_output=True, timeout=120)

    # 자막 burn-in (job_dir 의 subtitle.srt) + 내레이션 mux
    out_path = os.path.join(work, "output_shorts.mp4")
    vf_sub = None
    srt = os.path.join(job_dir, "subtitle.srt") if job_dir else None
    if srt and os.path.isfile(srt):
        srt_esc = srt.replace("\\", "/").replace(":", "\\:").replace("'", "")
        vf_sub = (f"subtitles='{srt_esc}':force_style="
                  "'Alignment=2,FontSize=15,MarginV=60,Outline=2,Shadow=1'")

    narration = None
    if job_dir:
        narration = _build_narration(job_dir, os.path.join(work, "narration.wav"),
                                     plan["total_ms"])

    cmd = [_ff(), "-y", "-i", video]
    if narration:
        cmd += ["-i", narration]
    if vf_sub:
        cmd += ["-vf", vf_sub]
    if narration:
        cmd += ["-map", "0:v", "-map", "1:a", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", out_path]
    r = subprocess.run(cmd, capture_output=True, timeout=240)
    if not os.path.isfile(out_path):
        return {"ok": False, "error": r.stderr.decode()[-400:]}

    return {"ok": True, "out_path": out_path,
            "duration_s": round(_ffprobe_duration(out_path), 1),
            "size_kb": round(os.path.getsize(out_path) / 1024),
            "segments": len(seg_files), "subtitles": bool(vf_sub),
            "narration": bool(narration)}


def render_output_path(plan_id: str) -> str | None:
    p = os.path.join(CUT_DIR, plan_id + "_render", "output_shorts.mp4")
    return p if os.path.isfile(p) else None
