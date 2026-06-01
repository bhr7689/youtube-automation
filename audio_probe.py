"""오디오 다운로드 + librosa 실측 분석 (BPM/키/에너지).

`analyzer.py` 가 메타데이터 추정이고 `lyrics_analyzer.py` 가 가사 분석이라면,
이 모듈은 **곡의 실제 소리** 단서를 뽑는다. 옵트인이며, 저작권/ToS 회색지대이므로
호출 측에서 사용자 동의를 받은 뒤에만 호출해야 한다.

추출 신호:
    - tempo_bpm        librosa.beat.beat_track (estimated tempo)
    - key, mode        chroma_cqt + Krumhansl-Schmuckler key profile correlation
    - duration_sec
    - rms_mean         평균 라우드니스(에너지)
    - rms_peak
    - spectral_centroid_mean   밝기 (sub-bass 위주면 낮음, 시밤발 많으면 높음)
    - zero_crossing_rate_mean  보컬/잡음 비율 단서
    - onset_rate       초당 어택 횟수(리듬 밀도)

CLI/헤드리스 호출 가능. Streamlit 비의존.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path


# Krumhansl-Schmuckler 키 프로파일 (major/minor 12음 가중치)
_KEY_PROFILES_MAJOR = [
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88,
]
_KEY_PROFILES_MINOR = [
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17,
]
_PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class AudioFeatures:
    tempo_bpm: float | None = None
    key: str = ""           # 예: "A"
    mode: str = ""          # "major" | "minor"
    key_label: str = ""     # 예: "A minor"
    key_confidence: float | None = None
    duration_sec: float | None = None
    rms_mean: float | None = None
    rms_peak: float | None = None
    spectral_centroid_mean: float | None = None
    zero_crossing_rate_mean: float | None = None
    onset_rate: float | None = None
    sample_rate: int | None = None
    audio_path: str = ""    # 디버그/재활용용
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return self.tempo_bpm is not None and not self.error

    def summary(self) -> str:
        bits: list[str] = []
        if self.tempo_bpm:
            bits.append(f"BPM {self.tempo_bpm:.0f}")
        if self.key_label:
            bits.append(f"키 {self.key_label}")
        if self.duration_sec:
            mm, ss = divmod(int(self.duration_sec), 60)
            bits.append(f"길이 {mm}:{ss:02d}")
        if self.rms_mean is not None:
            bits.append(f"에너지 {self.rms_mean:.3f}")
        return "  ·  ".join(bits)


# ---------------------------------------------------------------------------
# 1) 오디오 다운로드 (yt-dlp)
# ---------------------------------------------------------------------------

def _import_yt_dlp():
    try:
        import yt_dlp  # type: ignore
        return yt_dlp
    except ImportError:
        return None


def download_audio(video_id: str, workdir: Path) -> Path:
    yt_dlp = _import_yt_dlp()
    out_template = str(workdir / f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"
    if yt_dlp is None:
        if shutil.which("yt-dlp") is None:
            raise RuntimeError("yt-dlp 가 설치되어 있지 않습니다.")
        proc = subprocess.run(
            ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio",
             "-o", out_template, url],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp 실패: {(proc.stderr or '')[-400:]}")
    else:
        with yt_dlp.YoutubeDL({
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": out_template, "quiet": True, "no_warnings": True,
        }) as ydl:
            ydl.download([url])

    candidates = list(workdir.glob(f"{video_id}.*"))
    if not candidates:
        raise RuntimeError("오디오 추출 후 파일을 찾을 수 없습니다.")
    return candidates[0]


# ---------------------------------------------------------------------------
# 2) librosa 실측
# ---------------------------------------------------------------------------

def _detect_key(chroma_mean) -> tuple[str, str, float]:
    """chroma 평균 벡터 → 가장 높은 상관관계의 키/모드 추정."""
    import numpy as np

    chroma = np.asarray(chroma_mean, dtype=float)
    if chroma.sum() <= 0:
        return "", "", 0.0
    chroma = chroma / chroma.sum()

    maj = np.asarray(_KEY_PROFILES_MAJOR, dtype=float)
    min_ = np.asarray(_KEY_PROFILES_MINOR, dtype=float)
    maj = maj / maj.sum()
    min_ = min_ / min_.sum()

    best = ("", "", -1.0)
    for i in range(12):
        rolled_maj = np.roll(maj, i)
        rolled_min = np.roll(min_, i)
        # Pearson correlation
        for profile, mode in [(rolled_maj, "major"), (rolled_min, "minor")]:
            x = chroma - chroma.mean()
            y = profile - profile.mean()
            denom = (np.linalg.norm(x) * np.linalg.norm(y)) or 1e-9
            corr = float((x * y).sum() / denom)
            if corr > best[2]:
                best = (_PITCH_NAMES[i], mode, corr)
    return best


def analyze_audio_file(audio_path: str | os.PathLike) -> AudioFeatures:
    """오디오 파일 → 실측 특성. 모노 22050Hz 로 다운샘플링하여 빠르게."""
    try:
        import librosa
        import numpy as np
    except ImportError as e:
        return AudioFeatures(error=f"librosa 미설치: {e}")

    audio_path = str(audio_path)
    try:
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
    except Exception as e:
        return AudioFeatures(error=f"오디오 로드 실패: {type(e).__name__}: {e}")

    if y.size == 0:
        return AudioFeatures(error="빈 오디오")

    feats = AudioFeatures(audio_path=audio_path, sample_rate=int(sr))
    feats.duration_sec = float(librosa.get_duration(y=y, sr=sr))

    # 템포 + 비트
    try:
        tempo, _beats = librosa.beat.beat_track(y=y, sr=sr)
        # librosa 0.10+ 는 tempo 가 array 일 수 있음
        feats.tempo_bpm = float(np.atleast_1d(tempo)[0])
    except Exception as e:
        feats.error = f"BPM 추정 실패: {e}"

    # 키 추정 (chroma_cqt 평균 → Krumhansl)
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = chroma.mean(axis=1)
        key, mode, conf = _detect_key(chroma_mean)
        feats.key, feats.mode = key, mode
        feats.key_label = f"{key} {mode}" if key else ""
        feats.key_confidence = round(conf, 3) if conf else None
    except Exception:
        pass

    # 라우드니스 / 밝기 / 어택 밀도
    try:
        rms = librosa.feature.rms(y=y)
        feats.rms_mean = float(np.mean(rms))
        feats.rms_peak = float(np.max(rms))
    except Exception:
        pass
    try:
        sc = librosa.feature.spectral_centroid(y=y, sr=sr)
        feats.spectral_centroid_mean = float(np.mean(sc))
    except Exception:
        pass
    try:
        zcr = librosa.feature.zero_crossing_rate(y)
        feats.zero_crossing_rate_mean = float(np.mean(zcr))
    except Exception:
        pass
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        if feats.duration_sec and feats.duration_sec > 0:
            feats.onset_rate = round(len(onsets) / feats.duration_sec, 3)
    except Exception:
        pass

    return feats


# ---------------------------------------------------------------------------
# 3) 통합 진입점: video_id → AudioFeatures
# ---------------------------------------------------------------------------

def probe_video(
    video_id: str,
    *,
    workdir: str | os.PathLike | None = None,
    keep_audio: bool = False,
) -> AudioFeatures:
    """video_id → yt-dlp 다운로드 → librosa 분석. 임시 폴더 정리까지 처리."""
    cleanup = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="audio_probe_"))
        cleanup = True
    else:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

    try:
        audio_path = download_audio(video_id, workdir)
    except Exception as e:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)
        return AudioFeatures(error=f"오디오 다운로드 실패: {type(e).__name__}: {e}")

    feats = analyze_audio_file(audio_path)
    if cleanup and not keep_audio:
        shutil.rmtree(workdir, ignore_errors=True)
        feats.audio_path = ""  # 정리되었으므로 경로 무효화
    return feats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, json, re

    p = argparse.ArgumentParser(description="유튜브 영상 → librosa 실측 분석")
    p.add_argument("video", help="URL 또는 11자 video_id")
    p.add_argument("--keep-audio", action="store_true",
                   help="다운로드한 오디오를 삭제하지 않고 보관")
    args = p.parse_args()

    vid = args.video
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", vid)
    if m:
        vid = m.group(1)
    elif not re.match(r"^[A-Za-z0-9_-]{11}$", vid):
        raise SystemExit("유효하지 않은 video_id")

    feats = probe_video(vid, keep_audio=args.keep_audio)
    print(json.dumps(feats.as_dict(), ensure_ascii=False, indent=2))
    if feats.ok:
        print(f"\n요약: {feats.summary()}")
