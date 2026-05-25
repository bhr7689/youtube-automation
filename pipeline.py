#!/usr/bin/env python3
"""mp3 → MP4 무인 자동화 파이프라인 (K-Trot AI Factory · Step 6~8).

폴더를 통합 지점으로 삼는다. 사람이 직접 Suno 결과 mp3 를 떨구든, 비공식 Suno
API 가 떨구든, 파이프라인은 inbox 폴더만 감시하므로 둘 다 그대로 동작한다.

폴더 구조 (--root, 기본 ./pipeline_data):
    inbox/<job_id>/        ← 작업 투입 (job.json + 오디오 + 선택 배경)
    output/<job_id>/       ← 결과물 (<job_id>.mp4, .srt, meta.json)
    processed/<job_id>/    ← 성공한 입력 보관 (재처리 방지 = 멱등성)
    failed/<job_id>/       ← 실패한 입력 + error.log
    pipeline_log.jsonl     ← 처리 이력 한 줄/건

job.json (모두 선택, 합리적 기본값):
    {
      "title": "달려보자 인생길",
      "audio": ["track1.mp3", "track2.mp3"],   # 생략 시 폴더 내 오디오 이름순 전체
      "background": "bg.jpg",                    # 이미지/영상. 생략 시 단색 배경 자동 생성
      "background_color": "0x101418",
      "lyrics": "얼씨구 좋다\n달려보자 인생길",   # 단일 곡 가사 (균등 분배 SRT)
      "tracks": [                                 # 고급: 곡별 가사로 멀티 SRT
        {"audio": "track1.mp3", "lyrics_lines": ["...", "..."]}
      ],
      "resolution": "1920x1080",
      "audio_bitrate": "192k",
      "crf": 22,
      "fade_seconds": 2.0,
      "burn_subtitles": false                     # true 면 영상에 자막 굽기
    }

실행:
    python pipeline.py --once                 # inbox 1회 스캔 후 종료 (cron/n8n 용)
    python pipeline.py --watch --interval 30  # 데몬 모드 (폴더 상시 감시)
    python pipeline.py init                    # 폴더 구조 + 샘플 job.json 생성
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from media_core import (
    concat_audio_files,
    encode_music_video,
    ffprobe_duration,
    find_ffmpeg,
    fmt_duration,
    generate_srt,
)

AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm")

DEFAULT_ROOT = os.getenv("PIPELINE_ROOT", "./pipeline_data")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{_now_iso()}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 폴더 관리
# ---------------------------------------------------------------------------

class Pipeline:
    def __init__(self, root: str, *, min_age: float = 10.0):
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.output = self.root / "output"
        self.processed = self.root / "processed"
        self.failed = self.root / "failed"
        self.log_file = self.root / "pipeline_log.jsonl"
        self.min_age = min_age
        for d in (self.inbox, self.output, self.processed, self.failed):
            d.mkdir(parents=True, exist_ok=True)

    # -- 작업 발견 --------------------------------------------------------

    def discover_jobs(self) -> list[Path]:
        """처리 준비된 inbox 작업 폴더 목록."""
        jobs: list[Path] = []
        for entry in sorted(self.inbox.iterdir()):
            if not entry.is_dir():
                continue
            if self._is_ready(entry):
                jobs.append(entry)
        return jobs

    def _is_ready(self, job_dir: Path) -> bool:
        """job.json 이 있고, 폴더가 충분히 '안정'되어야 준비 완료.

        업로드가 진행 중인(부분 전송) 폴더를 건드리지 않기 위해 최근
        수정 시각이 min_age 초보다 오래됐는지 확인한다. `.ready` 마커
        파일이 있으면 나이 검사를 건너뛴다(투입자가 완료를 명시).
        """
        if not (job_dir / "job.json").exists():
            # job.json 이 없어도 오디오만 있으면 최소 작업으로 인정
            if not any(p.suffix.lower() in AUDIO_EXTS for p in job_dir.iterdir()):
                return False
        if (job_dir / ".ready").exists():
            return True
        newest = max((p.stat().st_mtime for p in job_dir.rglob("*")), default=0.0)
        return (time.time() - newest) >= self.min_age

    # -- 작업 처리 --------------------------------------------------------

    def process_all(self) -> int:
        jobs = self.discover_jobs()
        if not jobs:
            log("처리할 작업이 없습니다.")
            return 0
        log(f"{len(jobs)}개 작업 발견.")
        done = 0
        for job_dir in jobs:
            try:
                self.process_job(job_dir)
                done += 1
            except Exception as e:  # 한 작업 실패가 전체를 멈추지 않게
                log(f"❌ '{job_dir.name}' 실패: {e}")
                self._move_to_failed(job_dir, traceback.format_exc())
        return done

    def process_job(self, job_dir: Path) -> None:
        job_id = job_dir.name
        log(f"▶ '{job_id}' 처리 시작.")
        cfg = self._load_config(job_dir)

        audio_paths = self._resolve_audio(job_dir, cfg)
        if not audio_paths:
            raise ValueError("오디오 파일을 찾지 못했습니다.")

        out_dir = self.output / job_id
        work_dir = out_dir / "work"
        out_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        # 1) 오디오 결합 (단일이면 그대로 사용)
        if len(audio_paths) == 1:
            combined = audio_paths[0]
        else:
            combined = str(work_dir / "combined.m4a")
            ok, msg = concat_audio_files(audio_paths, combined, bitrate="320k")
            if not ok:
                raise RuntimeError(f"오디오 결합 실패: {msg}")

        per_durations = [ffprobe_duration(p) or 0.0 for p in audio_paths]
        total_duration = sum(per_durations) or (ffprobe_duration(combined) or 0.0)

        # 2) SRT 생성
        srt_path: str | None = None
        srt_tracks = self._build_srt_tracks(cfg, audio_paths, per_durations, total_duration)
        if srt_tracks:
            srt_content = generate_srt(srt_tracks)
            srt_path = str(out_dir / f"{job_id}.srt")
            Path(srt_path).write_text(srt_content, encoding="utf-8")
            log(f"  자막 SRT 생성: {Path(srt_path).name}")

        # 3) 배경 확보 (없으면 단색 자동 생성)
        visual_path, is_image = self._resolve_background(job_dir, work_dir, cfg)

        # 4) 인코딩
        mp4_path = str(out_dir / f"{job_id}.mp4")
        resolution = str(cfg.get("resolution", "1920x1080"))
        burn = bool(cfg.get("burn_subtitles", False))
        log(
            f"  ffmpeg 인코딩 중... (길이 {fmt_duration(total_duration)}, "
            f"{resolution}, {len(audio_paths)}곡, 자막굽기={burn})"
        )
        ok, ff_log = encode_music_video(
            combined,
            visual_path,
            mp4_path,
            is_image=is_image,
            resolution=resolution,
            audio_bitrate=str(cfg.get("audio_bitrate", "192k")),
            crf=int(cfg.get("crf", 22)),
            fade_seconds=float(cfg.get("fade_seconds", 0.0)),
            audio_duration=total_duration,
            subtitles_path=(srt_path if (burn and srt_path) else None),
        )
        if not ok:
            raise RuntimeError(f"인코딩 실패: {ff_log[-800:]}")

        # 5) 메타데이터 + 정리
        meta = {
            "job_id": job_id,
            "title": cfg.get("title", job_id),
            "status": "success",
            "created_at": _now_iso(),
            "audio_files": [Path(p).name for p in audio_paths],
            "total_duration_sec": round(total_duration, 2),
            "total_duration_h": fmt_duration(total_duration),
            "resolution": resolution,
            "mp4": Path(mp4_path).name,
            "srt": Path(srt_path).name if srt_path else None,
            "burn_subtitles": burn,
        }
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.rmtree(work_dir, ignore_errors=True)
        self._append_log(meta)
        self._move_to_processed(job_dir)
        log(f"✅ '{job_id}' 완료 → {mp4_path}")

    # -- 설정/입력 해석 ---------------------------------------------------

    def _load_config(self, job_dir: Path) -> dict:
        cfg_path = job_dir / "job.json"
        if not cfg_path.exists():
            return {}
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"job.json 파싱 오류: {e}") from e

    def _resolve_audio(self, job_dir: Path, cfg: dict) -> list[str]:
        named = cfg.get("audio")
        if named:
            paths = [str(job_dir / name) for name in named]
            missing = [p for p in paths if not Path(p).exists()]
            if missing:
                raise FileNotFoundError(f"job.json 의 오디오 누락: {missing}")
            return paths
        found = sorted(
            p for p in job_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS
        )
        return [str(p) for p in found]

    def _build_srt_tracks(
        self,
        cfg: dict,
        audio_paths: list[str],
        per_durations: list[float],
        total_duration: float,
    ) -> list[dict]:
        tracks = cfg.get("tracks")
        if tracks:
            name_to_dur = {
                Path(p).name: d for p, d in zip(audio_paths, per_durations)
            }
            out: list[dict] = []
            for tr in tracks:
                audio_name = tr.get("audio", "")
                lines = tr.get("lyrics_lines") or _split_lyrics(tr.get("lyrics", ""))
                out.append({
                    "title": tr.get("title", audio_name),
                    "duration": name_to_dur.get(audio_name, 0.0),
                    "lyrics_lines": lines,
                })
            return out
        lyrics = cfg.get("lyrics")
        if lyrics:
            return [{
                "title": cfg.get("title", ""),
                "duration": total_duration,
                "lyrics_lines": _split_lyrics(lyrics),
            }]
        return []

    def _resolve_background(
        self, job_dir: Path, work_dir: Path, cfg: dict
    ) -> tuple[str, bool]:
        named = cfg.get("background")
        if named:
            path = job_dir / named
            if not path.exists():
                raise FileNotFoundError(f"배경 파일 없음: {named}")
            return str(path), path.suffix.lower() in IMAGE_EXTS
        # job.json 에 없으면 폴더 내 이미지/영상 자동 탐색
        for p in sorted(job_dir.iterdir()):
            if p.suffix.lower() in IMAGE_EXTS:
                return str(p), True
            if p.suffix.lower() in VIDEO_EXTS:
                return str(p), False
        # 그래도 없으면 단색 배경 생성
        color = str(cfg.get("background_color", "0x101418"))
        resolution = str(cfg.get("resolution", "1920x1080"))
        bg = work_dir / "bg.png"
        _generate_solid_background(color, resolution, str(bg))
        log(f"  배경 없음 → 단색({color}) 배경 자동 생성.")
        return str(bg), True

    # -- 이동/기록 --------------------------------------------------------

    def _move_to_processed(self, job_dir: Path) -> None:
        self._safe_move(job_dir, self.processed / job_dir.name)

    def _move_to_failed(self, job_dir: Path, error_text: str) -> None:
        dest = self.failed / job_dir.name
        self._safe_move(job_dir, dest)
        try:
            (dest / "error.log").write_text(error_text, encoding="utf-8")
        except Exception:
            pass
        self._append_log({
            "job_id": job_dir.name,
            "status": "failed",
            "created_at": _now_iso(),
            "error": error_text.strip().splitlines()[-1] if error_text.strip() else "",
        })

    def _safe_move(self, src: Path, dest: Path) -> None:
        if dest.exists():
            dest = dest.with_name(f"{dest.name}_{int(time.time())}")
        shutil.move(str(src), str(dest))

    def _append_log(self, record: dict) -> None:
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _split_lyrics(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _generate_solid_background(color: str, resolution: str, out_path: str) -> None:
    """ffmpeg lavfi 로 단색 PNG 1장 생성 (PIL 불필요)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg 가 없어 배경을 생성할 수 없습니다.")
    proc = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner",
            "-f", "lavfi",
            "-i", f"color=c={color}:s={resolution}",
            "-frames:v", "1",
            out_path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"배경 생성 실패: {(proc.stderr or '')[-400:]}")


SAMPLE_JOB = {
    "title": "달려보자 인생길",
    "lyrics": "얼씨구 좋다\n달려보자 인생길\n지나간 세월도\n오늘은 다시 봄날",
    "background_color": "0x101418",
    "resolution": "1920x1080",
    "audio_bitrate": "192k",
    "crf": 22,
    "fade_seconds": 2.0,
    "burn_subtitles": False,
}


def cmd_init(root: str) -> None:
    pipe = Pipeline(root)
    sample = pipe.inbox / "sample_job"
    sample.mkdir(exist_ok=True)
    (sample / "job.json").write_text(
        json.dumps(SAMPLE_JOB, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"폴더 구조 생성 완료: {pipe.root}")
    log(f"샘플 작업: {sample}/job.json  (여기에 .mp3 와 (선택) 배경 이미지를 넣으세요)")
    log("준비되면:  python pipeline.py --once")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mp3 → MP4 무인 자동화 파이프라인")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "init"],
                        help="run(기본) 또는 init(폴더 구조 생성)")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="파이프라인 루트 폴더")
    parser.add_argument("--once", action="store_true", help="1회 스캔 후 종료")
    parser.add_argument("--watch", action="store_true", help="데몬 모드(상시 감시)")
    parser.add_argument("--interval", type=float, default=30.0, help="watch 폴링 간격(초)")
    parser.add_argument("--min-age", type=float, default=10.0,
                        help="작업 폴더 안정 판단 임계(초). 부분 업로드 방지")
    args = parser.parse_args(argv)

    if args.command == "init":
        cmd_init(args.root)
        return 0

    if not find_ffmpeg():
        log("⚠️  경고: ffmpeg 가 PATH 에 없습니다. 인코딩 단계에서 실패합니다.")

    pipe = Pipeline(args.root, min_age=args.min_age)

    if args.watch:
        log(f"👀 감시 모드 시작 (root={pipe.root}, 간격={args.interval}s). Ctrl+C 로 중단.")
        try:
            while True:
                pipe.process_all()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("감시 모드 종료.")
            return 0

    # 기본/--once: 1회 스캔
    pipe.process_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
