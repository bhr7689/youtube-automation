"""음악 이어붙이기 + 이미지 슬라이드 영상 만들기 앱"""
import json
import os
import random
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="음악 이어붙이기",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# 모바일 세로화면 친화 스타일
st.markdown(
    """
<style>
.main .block-container {
    max-width: 480px;
    padding-top: 1.2rem;
    padding-bottom: 6rem;
}
.stButton button {
    width: 100%;
    height: 3.4rem;
    font-size: 1.15rem;
    font-weight: 700;
    border-radius: 12px;
}
.stDownloadButton button {
    width: 100%;
    height: 3.2rem;
    font-size: 1.05rem;
    font-weight: 700;
    border-radius: 12px;
}
h1 { font-size: 1.7rem !important; }
h2 { font-size: 1.3rem !important; }
.big-label {
    font-size: 1.1rem;
    font-weight: 700;
    margin-top: 1.2rem;
    margin-bottom: 0.4rem;
}
.ad-box {
    margin-top: 2rem;
    padding: 1rem;
    background: #f3f4f6;
    text-align: center;
    border-radius: 10px;
    color: #9ca3af;
    font-size: 0.9rem;
}
.footer-links {
    text-align: center;
    font-size: 0.85rem;
    color: #888;
    margin-top: 1.5rem;
}
.footer-links a { color: #666; margin: 0 0.5rem; }
[data-testid="stFileUploaderDropzone"] { padding: 0.8rem; }

/* 잘못 올린 파일의 X 버튼이 툴팁에 가려 안 눌리는 문제 — 강제로 위로 올림 */
[data-testid="stFileUploaderFile"] button,
[data-testid="stFileUploader"] button[kind="icon"] {
    z-index: 9999 !important;
    position: relative !important;
}
[data-testid="stFileUploaderFile"] [data-testid="stTooltipIcon"],
[data-testid="stFileUploader"] [role="tooltip"] {
    pointer-events: none !important;
}
</style>
""",
    unsafe_allow_html=True,
)


DUR_MAP = {"1시간": 3600, "2시간": 7200, "3시간": 10800, "6시간": 21600}
IMG_INTERVAL = 270  # 4분 30초

# 패닝 방향 모드 — 라벨: 내부코드
PAN_MODES = {
    "번갈아 자동 (이미지마다 방향 교대)": "alternate",
    "왔다 갔다 (왼→오→왼 부드럽게)": "bounce_lr",
    "왔다 갔다 (오→왼→오 부드럽게)": "bounce_rl",
    "모두 왼쪽 → 오른쪽": "all_ltr",
    "모두 오른쪽 → 왼쪽": "all_rtl",
    "다양하게 자동 (매 이미지 다른 효과)": "variety",
    "대각선 좌상→우하": "all_diag_lt_rb",
    "대각선 우상→좌하": "all_diag_rt_lb",
    "천천히 드리프트 (미묘한 흔들림)": "all_drift",
}

# variety 모드에서 이미지마다 순회할 효과 목록
VARIETY_ROTATION = [
    "ltr",
    "bounce_rl",
    "diagonal_lt_rb",
    "rtl",
    "drift_slow",
    "bounce_lr",
    "diagonal_rt_lb",
]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

# 사용자 라이브러리 (자주 쓰는 자연소리·이미지 영구 보관) — gitignore 됨
LIBRARY_DIR = Path(__file__).parent / "library"


def library_dir(kind):
    """kind: 'sounds' 또는 'images'."""
    d = LIBRARY_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_library_items(kind):
    d = library_dir(kind)
    return sorted([p for p in d.iterdir() if p.is_file()], key=lambda p: p.name.lower())


def save_to_library(kind, uploaded_file, custom_name=None):
    """업로드된 파일을 라이브러리 폴더에 영구 저장. 이름 중복은 _2, _3 자동 추가."""
    d = library_dir(kind)
    raw_name = custom_name or uploaded_file.name
    safe = raw_name.replace("/", "_").replace("\\", "_")
    target = d / safe
    if target.exists():
        stem, suffix = target.stem, target.suffix
        i = 2
        while (d / f"{stem}_{i}{suffix}").exists():
            i += 1
        target = d / f"{stem}_{i}{suffix}"
    with open(target, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return target


def delete_library_item(kind, name):
    d = library_dir(kind)
    target = d / name
    if target.exists() and target.is_file():
        try:
            target.unlink()
            # 비디오면 썸네일도 같이 제거
            if kind == "videos":
                thumb = d / ".thumbs" / f"{target.stem}.jpg"
                if thumb.exists():
                    try:
                        thumb.unlink()
                    except Exception:
                        pass
            return True
        except Exception:
            return False
    return False


def get_or_make_video_thumb(video_path):
    """비디오 첫 프레임을 작은 썸네일(.thumbs/이름.jpg)로 캐시."""
    thumb_dir = library_dir("videos") / ".thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb = thumb_dir / f"{Path(video_path).stem}.jpg"
    if thumb.exists():
        return thumb
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", "0", "-vframes", "1",
        "-vf", "scale=400:-2",
        "-q:v", "5",
        str(thumb),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        pass
    return thumb if thumb.exists() else None

PEXELS_PHOTO_API = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
PIXABAY_API = "https://pixabay.com/api/"

CROP_MODES = {
    "그대로": None,
    # 가로 자르기 ────
    "왼쪽만 (가로 50%)": "left_50",
    "오른쪽만 (가로 50%)": "right_50",
    "가운데만 (가로 50%)": "center_50",
    "왼쪽 위주 (가로 70%)": "left_70",
    "오른쪽 위주 (가로 70%)": "right_70",
    # 세로 자르기 ────
    "위쪽만 (세로 50%)": "top_50",
    "아래쪽만 (세로 50%)": "bottom_50",
    "가운데만 (세로 50%)": "vcenter_50",
    "위쪽 위주 (세로 70%)": "top_70",
    "아래쪽 위주 (세로 70%)": "bottom_70",
    # 사용자 정의 ────
    "직접 지정 ✂️ (슬라이더)": "custom",
}


def is_image(path):
    return Path(path).suffix.lower() in IMG_EXTS


def is_video(path):
    return Path(path).suffix.lower() in VID_EXTS


def search_pexels_images(keyword, count, api_key):
    """Pexels 사진 검색 → 미리보기 목록만 반환 (다운로드 X)."""
    qs = urllib.parse.urlencode({
        "query": keyword,
        "per_page": max(3, min(count, 30)),
        "orientation": "landscape",
    })
    req = urllib.request.Request(
        f"{PEXELS_PHOTO_API}?{qs}",
        headers={"Authorization": api_key, "User-Agent": "music-merger-app/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = []
    for p in data.get("photos", []):
        src = p.get("src", {})
        items.append({
            "source": "pexels",
            "id": f"pex_{p.get('id', '')}",
            "thumb_url": src.get("medium") or src.get("small") or src.get("tiny", ""),
            "full_url": src.get("large2x") or src.get("large") or src.get("original", ""),
        })
    return items


def search_pixabay(keyword, count, api_key):
    """Pixabay 사진 검색 → 미리보기 목록만 반환."""
    qs = urllib.parse.urlencode({
        "key": api_key,
        "q": keyword,
        "image_type": "photo",
        "per_page": max(3, min(count, 30)),
        "safesearch": "true",
        "orientation": "horizontal",
    })
    req = urllib.request.Request(
        f"{PIXABAY_API}?{qs}",
        headers={"User-Agent": "music-merger-app/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = []
    for h in data.get("hits", []):
        items.append({
            "source": "pixabay",
            "id": f"pix_{h.get('id', '')}",
            "thumb_url": h.get("previewURL") or h.get("webformatURL", ""),
            "full_url": h.get("largeImageURL") or h.get("webformatURL", ""),
        })
    return items


def download_url_to(url, out_path):
    req = urllib.request.Request(url, headers={"User-Agent": "music-merger-app/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out_path, "wb") as f:
        f.write(r.read())
    return out_path


def _crop_box(w, h, mode, h_range=None, v_range=None):
    """크롭 박스(left, top, right, bottom) 계산.
    custom 모드면 h_range=(min%, max%) v_range=(min%, max%) 사용."""
    if mode == "custom":
        h_min, h_max = h_range if h_range else (0, 100)
        v_min, v_max = v_range if v_range else (0, 100)
        if h_min >= h_max or v_min >= v_max:
            return None
        return (
            int(w * h_min / 100), int(h * v_min / 100),
            int(w * h_max / 100), int(h * v_max / 100),
        )
    return {
        "left_50":   (0,            0,            w // 2,       h),
        "right_50":  (w // 2,       0,            w,            h),
        "center_50": (w // 4,       0,            3 * w // 4,   h),
        "left_70":   (0,            0,            int(w * 0.7), h),
        "right_70":  (int(w * 0.3), 0,            w,            h),
        "top_50":    (0,            0,            w,            h // 2),
        "bottom_50": (0,            h // 2,       w,            h),
        "vcenter_50":(0,            h // 4,       w,            3 * h // 4),
        "top_70":    (0,            0,            w,            int(h * 0.7)),
        "bottom_70": (0,            int(h * 0.3), w,            h),
    }.get(mode)


def crop_pil_image(pil_img, mode, h_range=None, v_range=None):
    """PIL Image 메모리에서 자르기. 미리보기용."""
    if not mode:
        return pil_img
    if pil_img.mode in ("RGBA", "P"):
        pil_img = pil_img.convert("RGB")
    box = _crop_box(*pil_img.size, mode, h_range, v_range)
    return pil_img.crop(box) if box else pil_img


def crop_image(img_path, output_path, mode, h_range=None, v_range=None):
    """이미지 자르기 (파일 저장). 생성 시 사용."""
    if not mode:
        if str(img_path) != str(output_path):
            import shutil as _sh
            _sh.copyfile(img_path, output_path)
        return output_path
    from PIL import Image
    img = Image.open(img_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    box = _crop_box(*img.size, mode, h_range, v_range)
    if not box:
        return img_path
    img.crop(box).save(output_path, quality=92)
    return output_path


@st.cache_data(show_spinner=False)
def fetch_thumb_bytes(url):
    """URL 썸네일을 한 번만 받아 캐시 (자르기 모드 바꿔도 재다운로드 X)."""
    req = urllib.request.Request(url, headers={"User-Agent": "music-merger-app/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def preprocess_to_segment(input_path, output_path, fixed_duration=None, pan_direction=None):
    """이미지/영상을 1280x720 30fps mp4 세그먼트로 통일.
    이미지는 fixed_duration(기본 4:30) 길이로, 영상은 본래 길이로 인코딩.

    pan_direction='ltr' 또는 'rtl' 이면 이미지가 그 방향으로 천천히 패닝.
    영상 파일은 무시(원본 모션 유지)."""
    if is_image(input_path):
        duration = fixed_duration or IMG_INTERVAL
        MOVEMENT_DIRS = ("ltr", "rtl", "bounce_lr", "bounce_rl",
                         "diagonal_lt_rb", "diagonal_rt_lb", "drift_slow")
        if pan_direction in MOVEMENT_DIRS:
            y_override = None  # 세로 움직임 있는 효과만 세팅
            if pan_direction == "ltr":
                x_expr = f"(iw-1280)*t/{duration}"
            elif pan_direction == "rtl":
                x_expr = f"(iw-1280)*(1-t/{duration})"
            elif pan_direction == "bounce_lr":
                # 왼→오→왼 부드러운 왕복 (cos 곡선)
                x_expr = f"(iw-1280)*(0.5-0.5*cos(2*PI*t/{duration}))"
            elif pan_direction == "bounce_rl":  # 오→왼→오
                x_expr = f"(iw-1280)*(0.5+0.5*cos(2*PI*t/{duration}))"
            elif pan_direction == "diagonal_lt_rb":
                # 좌상 → 우하 대각선
                x_expr = f"(iw-1280)*t/{duration}"
                y_override = f"(ih-720)*t/{duration}"
            elif pan_direction == "diagonal_rt_lb":
                # 우상 → 좌하 대각선
                x_expr = f"(iw-1280)*(1-t/{duration})"
                y_override = f"(ih-720)*t/{duration}"
            else:  # drift_slow: 가운데 근처를 아주 살짝 사인파로 좌우 드리프트
                x_expr = f"(iw-1280)*(0.5+0.3*sin(2*PI*t/{duration}))"

            # 파노라마 친화: 가로가 충분히 긴 이미지면 전체 폭을 그대로 패닝.
            # 일반 비율은 캔버스를 키워 패닝 여백을 만든다.
            try:
                from PIL import Image
                with Image.open(input_path) as _img:
                    iw_src, ih_src = _img.size
                scaled_w_at_720h = int(iw_src * 720 / ih_src) if ih_src > 0 else 1280
            except Exception:
                scaled_w_at_720h = 0

            # 대각선/드리프트 세로 움직임이 있는 효과는 항상 큰 캔버스가 필요
            needs_vertical = y_override is not None
            if scaled_w_at_720h > 1280 and not needs_vertical:
                # 파노라마: 높이 720 맞추고 전체 폭 가로지름
                scale_str = "scale=-2:720"
                y_expr = "0"
            else:
                # 일반/세로 이미지 또는 대각선: 캔버스 확대 후 패닝 여백 확보
                scale_str = "scale=2240:1260:force_original_aspect_ratio=increase"
                y_expr = y_override if y_override else "(ih-720)/2"

            vf = (
                f"{scale_str},"
                f"crop=1280:720:'{x_expr}':'{y_expr}',"
                f"setsar=1,fps=30"
            )
        else:
            vf = (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30"
            )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duration), "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-500:])
    return output_path


def _probe_duration(path):
    """ffprobe로 길이(초)를 잰다."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def format_timestamp(seconds):
    """초 → YouTube 챕터 친화 문자열.
    1시간 미만은 MM:SS, 1시간 이상은 H:MM:SS (혼합 OK)."""
    s = int(seconds)
    if s < 3600:
        return f"{s // 60:02d}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def build_tracklist_text(music_items, target_seconds, crossfade_sec=0):
    """유튜브 설명란용 트랙리스트 텍스트.

    crossfade_sec>0 이면 각 곡 간 겹침(계단식)을 반영해서 다음 곡 시작 시각을 앞당김.
    """
    if not music_items:
        return ""
    durations = [max(_probe_duration(p), 1.0) for p, _ in music_items]
    n = len(music_items)

    lines = []
    t = 0.0
    while t < target_seconds:
        for i, ((_, orig_name), dur) in enumerate(zip(music_items, durations)):
            if t >= target_seconds:
                break
            time_str = format_timestamp(t)
            display = Path(orig_name).stem
            lines.append(f"{time_str} {display}")
            # 크로스페이드가 있으면 다음 곡은 crossfade_sec 초 겹침 시작
            if crossfade_sec > 0 and i < n - 1:
                t += max(1.0, dur - crossfade_sec)
            else:
                t += dur
    return "\n".join(lines)


def _build_crossfade_sequence(music_paths, crossfade_sec, workdir):
    """acrossfade 체인으로 음악을 부드럽게 이어붙인 한 시퀀스 파일 생성.
    앞 곡의 끝과 다음 곡의 처음을 crossfade_sec 초 동안 겹침 (계단식)."""
    seq = workdir / "sequence_xfade.mp3"
    if len(music_paths) == 1:
        import shutil as _sh
        _sh.copyfile(music_paths[0], seq)
        return seq

    inputs = []
    for p in music_paths:
        inputs.extend(["-i", str(p)])

    filter_parts = []
    last_label = "[0:a]"
    for i in range(1, len(music_paths)):
        new_label = f"[a{i:03d}]"
        filter_parts.append(
            f"{last_label}[{i}:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri{new_label}"
        )
        last_label = new_label

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", last_label,
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(seq),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-800:])
    return seq


def build_audio(music_paths, total_seconds, workdir,
                nature_path=None, nature_volume=0.3,
                nature_on_sec=0, nature_off_sec=0,
                join_mode="concat", crossfade_sec=8):
    """음악들을 이어붙여 정확한 길이의 mp3로 만든다. 자연의 소리가 있으면 위에 깐다.

    join_mode:
      - 'concat'    — 그대로 순차 이어붙이기 (기본)
      - 'crossfade' — 계단식 크로스페이드로 부드럽게 겹쳐 넘김

    nature_off_sec > 0 이면 on_sec 동안 들리고 off_sec 동안 쉬는 패턴 반복."""
    # 사이클 길이 계산 (join_mode 에 따라 다름)
    per_song = [max(_probe_duration(p), 0.1) for p in music_paths]
    if join_mode == "crossfade" and len(music_paths) > 1:
        # crossfade: 각 연결마다 crossfade_sec 초 겹침 → 총 길이가 짧아짐
        cycle_sec = sum(per_song) - (len(music_paths) - 1) * crossfade_sec
    else:
        cycle_sec = sum(per_song)
    if cycle_sec <= 0:
        raise RuntimeError("음악 파일에서 길이를 읽지 못했거나 크로스페이드 시간이 너무 길어요.")
    loops = int(total_seconds // cycle_sec) + 2

    playlist = workdir / "playlist.txt"
    if join_mode == "crossfade" and len(music_paths) > 1:
        # 1) 한 시퀀스를 acrossfade 로 만들고 → 그 시퀀스를 반복
        seq_path = _build_crossfade_sequence(music_paths, crossfade_sec, workdir)
        with open(playlist, "w", encoding="utf-8") as f:
            for _ in range(loops):
                f.write(f"file '{seq_path.as_posix()}'\n")
    else:
        # 순차 concat: 곡들을 반복 나열
        with open(playlist, "w", encoding="utf-8") as f:
            for _ in range(loops):
                for p in music_paths:
                    f.write(f"file '{p.as_posix()}'\n")

    music_concat = workdir / "music_concat.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(playlist),
        "-t", str(total_seconds),
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_concat),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-800:])

    if not nature_path:
        # 자연의 소리 없음 → 합친 음악이 그대로 결과
        final = workdir / "output_audio.mp3"
        music_concat.rename(final)
        return final

    # 자연의 소리를 음악 위에 깔기 (반복 재생)
    mixed = workdir / "output_audio.mp3"
    vol = max(0.0, min(2.0, float(nature_volume)))

    on_s = max(0, int(nature_on_sec))
    off_s = max(0, int(nature_off_sec))
    if on_s > 0 and off_s > 0:
        # 간격 모드: on_s 초 동안 vol, off_s 초 동안 0 으로 반복
        period = on_s + off_s
        # ffmpeg 필터 인자 내부 콤마는 백슬래시로 이스케이프
        vol_expr = f"if(lt(mod(t\\,{period})\\,{on_s})\\,{vol}\\,0)"
        nature_filter = f"[1:a]volume=volume='{vol_expr}':eval=frame[a1]"
    else:
        nature_filter = f"[1:a]volume={vol}[a1]"

    cmd_mix = [
        "ffmpeg", "-y",
        "-i", str(music_concat),
        "-stream_loop", "-1", "-i", str(nature_path),
        "-filter_complex",
        f"[0:a]volume=1.0[a0];{nature_filter};"
        f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]",
        "-map", "[out]",
        "-t", str(total_seconds),
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(mixed),
    ]
    res = subprocess.run(cmd_mix, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-800:])
    return mixed


def build_video(media_paths, total_seconds, workdir, audio_path=None,
                pan_enabled=True, pan_mode="alternate",
                image_duration=None, image_durations=None, progress_cb=None):
    """이미지/영상 혼합을 핑퐁 순서로 잇고, 정해진 길이로 채우는 영상.

    pan_mode:
      - alternate:     이미지마다 LTR/RTL 번갈아
      - all_ltr:       모두 왼→오
      - all_rtl:       모두 오→왼
      - bounce_lr/rl:  각 이미지 내에서 왕복 (cos)
      - variety:       매 이미지가 순회 목록에서 다른 효과 (다양하게)
      - all_diag_lt_rb / all_diag_rt_lb: 대각선
      - all_drift:     아주 살짝 사인파 드리프트
    image_duration: 모든 이미지에 같은 길이 적용 (미리보기 등).
    image_durations: [초1, 초2, ...] 이미지별 개별 길이 (곡 동기화용)."""
    default_dur = image_duration or IMG_INTERVAL
    segments = []
    image_idx = 0
    for i, p in enumerate(media_paths):
        seg = workdir / f"seg_{i:03d}.mp4"
        direction = None
        if pan_enabled and is_image(p):
            if pan_mode == "all_ltr":
                direction = "ltr"
            elif pan_mode == "all_rtl":
                direction = "rtl"
            elif pan_mode == "all_diag_lt_rb":
                direction = "diagonal_lt_rb"
            elif pan_mode == "all_diag_rt_lb":
                direction = "diagonal_rt_lb"
            elif pan_mode == "all_drift":
                direction = "drift_slow"
            elif pan_mode in ("bounce_lr", "bounce_rl"):
                direction = pan_mode
            elif pan_mode == "variety":
                direction = VARIETY_ROTATION[image_idx % len(VARIETY_ROTATION)]
            else:  # alternate
                direction = "ltr" if image_idx % 2 == 0 else "rtl"
            image_idx += 1
        # 이미지별 개별 길이 우선
        this_dur = default_dur
        if image_durations and i < len(image_durations):
            this_dur = max(1.0, float(image_durations[i]))
        preprocess_to_segment(p, seg, fixed_duration=this_dur, pan_direction=direction)
        segments.append(seg)
        if progress_cb:
            progress_cb(i + 1, len(media_paths))

    # 2) 핑퐁(왔다 갔다) 시퀀스
    if len(segments) > 1:
        pingpong = segments + segments[-2:0:-1]
    else:
        pingpong = segments

    # 3) 시퀀스 한 사이클 길이 측정 → 몇 번 반복하면 목표 길이를 덮는지
    seg_durations = {s: max(_probe_duration(s), 1.0) for s in segments}
    cycle = sum(seg_durations[s] for s in pingpong)
    if cycle <= 0:
        cycle = IMG_INTERVAL
    loops = max(1, int(total_seconds // cycle) + 2)

    # 4) concat 리스트 작성
    seg_list = workdir / "seglist.txt"
    with open(seg_list, "w", encoding="utf-8") as f:
        for _ in range(loops):
            for s in pingpong:
                f.write(f"file '{s.as_posix()}'\n")

    # 5) 합치기 (포맷 통일됐으니 비디오는 copy 가능)
    video_out = workdir / "output_video.mp4"
    if audio_path is None:
        # 무음 영상 — 캡컷에서 음악·자연소리와 따로 합치기 좋게
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(seg_list),
            "-c:v", "copy", "-an",
            "-t", str(total_seconds),
            str(video_out),
        ]
        fallback = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(seg_list),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-an",
            "-t", str(total_seconds),
            str(video_out),
        ]
    else:
        # 음악·자연소리를 그대로 영상에 깔기 (AAC 재인코딩)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(seg_list),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_seconds),
            "-shortest",
            str(video_out),
        ]
        fallback = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(seg_list),
            "-i", str(audio_path),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_seconds),
            "-shortest",
            str(video_out),
        ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        res2 = subprocess.run(fallback, capture_output=True, text=True)
        if res2.returncode != 0:
            raise RuntimeError(res2.stderr[-800:])
    return video_out


def _clear_uploader(key):
    """파일 업로더 칸을 비운다. X 버튼이 안 눌릴 때 대안."""
    st.session_state.pop(key, None)


# ===================== UI =====================
st.title("🎵 음악 이어붙이기")
st.caption("음악과 이미지를 골라 긴 영상으로 만들어요 · 캡컷에 그대로 가져가세요")

# 전역 초기화 버튼 (잘못 올린 파일이 X 버튼 안 눌릴 때 비상용)
with st.expander("⚙️ 막혔을 때 — 모든 업로드 한꺼번에 비우기"):
    st.caption("X 버튼이 안 눌릴 때 누르세요. 모든 업로드 칸이 비어요.")
    if st.button("🔄 모두 비우고 처음부터", key="clear_all"):
        for k in ("music", "nature", "nature_new", "media", "stock_paths", "stock_dir",
                  "lib_image_paths", "audio_path", "video_path", "workdir", "audio_label",
                  "search_results", "preview_path", "tracklist_text"):
            st.session_state.pop(k, None)
        # 라이브러리 체크박스/자르기 키도 해제 (파일은 유지, 선택만 비움)
        for k in list(st.session_state.keys()):
            if (k.startswith("use_lib_img_") or k.startswith("use_lib_vid_")
                    or k.startswith("lib_crop_")):
                st.session_state.pop(k, None)
        st.rerun()

# 1) 음악 업로드
st.markdown('<div class="big-label">1️⃣ 음악 파일 올리기 <span style="color:#dc2626;">*필수</span></div>', unsafe_allow_html=True)
music_files = st.file_uploader(
    "MP3 / WAV / M4A 등 여러 개 가능",
    type=["mp3", "wav", "m4a", "aac", "ogg", "flac"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    key="music",
)
if music_files:
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(f"✅ {len(music_files)}곡 선택됨")
    with c2:
        if st.button("🗑️ 빼기", key="clear_music", use_container_width=True):
            _clear_uploader("music")
            st.rerun()

# 2) 자연의 소리 (선택) — 라이브러리 + 새 업로드
st.markdown('<div class="big-label">2️⃣ 자연의 소리 (선택)</div>', unsafe_allow_html=True)
st.caption("빗소리·파도·새소리 같은 파일. 한 번 저장해두면 다음에 또 골라 쓸 수 있어요.")

saved_sounds = list_library_items("sounds")

# 라이브러리 관리(저장된 목록 + 삭제)
if saved_sounds:
    with st.expander(f"📁 내 자연소리 라이브러리 ({len(saved_sounds)}개 저장됨)"):
        for s in saved_sounds:
            c1, c2 = st.columns([5, 1])
            with c1:
                st.caption(f"🎵 {s.name}")
            with c2:
                if st.button("🗑️", key=f"del_snd_{s.name}", help=f"{s.name} 삭제"):
                    delete_library_item("sounds", s.name)
                    st.rerun()

# 사용할 자연 소리 선택
nature_source = st.radio(
    "어떻게 사용할까요?",
    ["사용 안 함", "라이브러리에서 선택", "새로 업로드"],
    horizontal=True,
    index=1 if saved_sounds else 0,
    key="nature_source",
)

nature_path_for_build = None  # 실제 빌드에 쓸 파일 경로 (Path 또는 None)
nature_file = None  # 새 업로드 UploadedFile (요약 카드용 호환)

if nature_source == "라이브러리에서 선택":
    if not saved_sounds:
        st.info("저장된 소리가 없어요. '새로 업로드' 를 골라 첫 파일을 추가해주세요.")
    else:
        chosen = st.selectbox(
            "저장된 자연 소리",
            options=[s.name for s in saved_sounds],
            key="nature_lib_select",
        )
        nature_path_for_build = library_dir("sounds") / chosen
        st.caption(f"🌿 선택됨: **{chosen}**")
        # 요약 카드용 더미 객체 (name 만 필요)
        class _LibFile:
            def __init__(self, name): self.name = name
        nature_file = _LibFile(chosen)

elif nature_source == "새로 업로드":
    new_sound = st.file_uploader(
        "MP3 / WAV / M4A 한 개",
        type=["mp3", "wav", "m4a", "aac", "ogg", "flac"],
        accept_multiple_files=False,
        label_visibility="collapsed",
        key="nature_new",
    )
    if new_sound is not None:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.caption(f"🌿 {new_sound.name}")
        with c2:
            if st.button("🗑️ 빼기", key="clear_nature_new", use_container_width=True):
                _clear_uploader("nature_new")
                st.rerun()
        save_to_lib = st.checkbox(
            f"💾 '{new_sound.name}' 을 라이브러리에 저장 (다음에도 쓸 수 있게)",
            value=True,
            key="save_nature_to_lib",
        )
        if save_to_lib and st.button("📥 지금 라이브러리에 저장", key="save_now_nature"):
            saved_path = save_to_library("sounds", new_sound)
            st.success(f"✅ 저장됨: {saved_path.name}")
            st.rerun()
        # 이번 실행에 임시로 쓰기 위해 file 객체 그대로 사용
        nature_file = new_sound

nature_volume_pct = 30
nature_pattern = "계속 들리게"
nature_on_sec = 0
nature_off_sec = 0
if nature_file is not None:
    nature_volume_pct = st.slider(
        "자연의 소리 크기 (음악 대비 %)",
        min_value=5, max_value=100, value=30, step=5,
        help="작게 깔리는 배경음으로는 20~40% 추천",
    )
    nature_pattern = st.radio(
        "들리는 방식",
        ["계속 들리게", "간격을 두고 들리게"],
        horizontal=True,
    )
    if nature_pattern == "간격을 두고 들리게":
        col_on, col_off = st.columns(2)
        with col_on:
            on_min = st.select_slider(
                "들리는 시간",
                options=[0.5, 1, 2, 3, 5, 10],
                value=1,
                format_func=lambda v: f"{int(v*60)}초" if v < 1 else f"{int(v)}분",
            )
        with col_off:
            off_min = st.select_slider(
                "쉬는 시간",
                options=[1, 2, 3, 5, 10, 15, 30],
                value=5,
                format_func=lambda v: f"{int(v)}분",
            )
        nature_on_sec = int(on_min * 60)
        nature_off_sec = int(off_min * 60)
        st.caption(
            f"🔁 패턴: **{nature_on_sec}초 들리고** → **{nature_off_sec}초 쉬기** 반복"
        )

# 3) 길이
st.markdown('<div class="big-label">3️⃣ 총 길이</div>', unsafe_allow_html=True)
duration_choice = st.radio(
    "총 길이",
    list(DUR_MAP.keys()),
    horizontal=True,
    label_visibility="collapsed",
)

# 4) 순서 + 이어붙이는 방식
st.markdown('<div class="big-label">4️⃣ 재생 순서</div>', unsafe_allow_html=True)
order_mode = st.radio(
    "재생 순서",
    ["순서대로 이어주기", "랜덤 섞기"],
    label_visibility="collapsed",
)

st.markdown(
    '<div class="big-label" style="margin-top:1rem;">이어붙이는 방식</div>',
    unsafe_allow_html=True,
)
join_mode_label = st.radio(
    "이어붙이는 방식",
    ["순차 (그대로 딱 잘라 이어붙임)", "계단식 (부드럽게 겹쳐서 크로스페이드)"],
    label_visibility="collapsed",
    help="계단식: 앞 곡의 마지막 몇 초와 다음 곡의 도입부 몇 초가 겹쳐 자연스럽게 넘어가요.",
)
join_mode = "crossfade" if "계단식" in join_mode_label else "concat"
crossfade_sec_val = 8
if join_mode == "crossfade":
    crossfade_sec_val = st.slider(
        "겹치는 시간 (초)",
        min_value=3, max_value=15, value=8, step=1,
        help="이 시간만큼 앞 곡 끝과 다음 곡 시작이 겹쳐요. 8초 정도가 자연스러워요.",
    )
    st.caption(f"🎚️ 계단식: **{crossfade_sec_val}초** 동안 부드럽게 겹쳐 다음 곡으로 넘어감")

# 곡에 맞춰 이미지 자동 전환 (곡 수와 이미지 수를 맞추는 게 이상적)
sync_images_to_songs = st.checkbox(
    "🎯 곡에 맞춰 이미지 자동 전환 (곡이 바뀔 때마다 이미지도 전환)",
    value=False,
    help="체크하면 이미지가 4:30 고정이 아니라 각 곡 길이에 맞춰 바뀌어요. "
         "곡과 이미지 수가 같을 때 이상적. 이미지가 적으면 순환 재사용.",
)

# 5) 배경 이미지·영상 (선택, 직접 업로드 + 라이브러리)
st.markdown('<div class="big-label">5️⃣ 배경 이미지·영상 (선택)</div>', unsafe_allow_html=True)
st.caption("직접 올린 이미지(4분 30초씩) · 영상(본래 길이)을 왔다 갔다 보여줘요 · "
           "**파노라마(가로로 긴 이미지)** 는 전체 폭을 그대로 가로지르며 패닝돼요")

# 이미지·영상 라이브러리 (저장된 것 중 골라 풀에 추가)
saved_images = list_library_items("images")
saved_videos = list_library_items("videos")
if "lib_image_paths" not in st.session_state:
    st.session_state["lib_image_paths"] = []

total_lib = len(saved_images) + len(saved_videos)
if total_lib > 0:
    with st.expander(
        f"📁 내 이미지·영상 라이브러리 (이미지 {len(saved_images)}장 · 영상 {len(saved_videos)}개) — 골라서 사용"
    ):
        st.caption("체크해서 이번에 사용 · 🗑️ 로 라이브러리에서 영구 삭제")

        # 이미지 먼저 (자르기 + 미리보기)
        if saved_images:
            st.markdown("**🖼️ 이미지** (자르기 모드 골라서 사용)")
            for row_start in range(0, len(saved_images), 2):
                row = saved_images[row_start:row_start + 2]
                cols = st.columns(2)
                for col, img in zip(cols, row):
                    with col:
                        crop_key = f"lib_crop_{img.name}"
                        crop_label = st.session_state.get(crop_key, "그대로")
                        crop_mode_now = CROP_MODES.get(crop_label)
                        h_range_now = st.session_state.get(f"{crop_key}_h", (0, 100))
                        v_range_now = st.session_state.get(f"{crop_key}_v", (0, 100))
                        # 자르기 적용된 미리보기
                        try:
                            if crop_mode_now:
                                from PIL import Image as _PILImage
                                _pil = _PILImage.open(str(img))
                                _cropped = crop_pil_image(
                                    _pil, crop_mode_now,
                                    h_range=h_range_now, v_range=v_range_now,
                                )
                                st.image(_cropped, use_container_width=True)
                                if crop_mode_now == "custom":
                                    st.caption(f"✂️ 가로 {h_range_now[0]}-{h_range_now[1]}% · 세로 {v_range_now[0]}-{v_range_now[1]}%")
                                else:
                                    st.caption(f"✂️ {crop_label}")
                            else:
                                st.image(str(img), use_container_width=True)
                        except Exception:
                            try:
                                st.image(str(img), use_container_width=True)
                            except Exception:
                                pass
                        st.caption(f"📁 {img.name[:24]}")
                        st.selectbox(
                            "자르기 (즉시 미리보기 반영)",
                            options=list(CROP_MODES.keys()),
                            key=crop_key,
                            label_visibility="collapsed",
                        )
                        if st.session_state.get(crop_key) == "직접 지정 ✂️ (슬라이더)":
                            st.slider("가로 범위 (%)", 0, 100, value=(0, 100), key=f"{crop_key}_h")
                            st.slider("세로 범위 (%)", 0, 100, value=(0, 100), key=f"{crop_key}_v")
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.checkbox("이번에 쓰기", key=f"use_lib_img_{img.name}")
                        with c2:
                            if st.button("🗑️", key=f"del_lib_img_{img.name}", help="영구 삭제"):
                                delete_library_item("images", img.name)
                                st.rerun()

        # 영상
        if saved_videos:
            st.markdown("**🎞️ 영상**")
            for row_start in range(0, len(saved_videos), 2):
                row = saved_videos[row_start:row_start + 2]
                cols = st.columns(2)
                for col, vid in zip(cols, row):
                    with col:
                        thumb = get_or_make_video_thumb(vid)
                        if thumb and thumb.exists():
                            try:
                                st.image(str(thumb), use_container_width=True)
                            except Exception:
                                pass
                        else:
                            st.caption("🎞️ (썸네일 없음)")
                        st.caption(f"📁 {vid.name[:24]}")
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.checkbox("이번에 쓰기", key=f"use_lib_vid_{vid.name}")
                        with c2:
                            if st.button("🗑️", key=f"del_lib_vid_{vid.name}", help="영구 삭제"):
                                delete_library_item("videos", vid.name)
                                st.rerun()

        # 선택된 라이브러리 미디어들을 추적
        chosen_imgs = [img for img in saved_images
                       if st.session_state.get(f"use_lib_img_{img.name}", False)]
        chosen_vids = [vid for vid in saved_videos
                       if st.session_state.get(f"use_lib_vid_{vid.name}", False)]
        st.session_state["lib_image_paths"] = (
            [str(p) for p in chosen_imgs] + [str(p) for p in chosen_vids]
        )
        if chosen_imgs or chosen_vids:
            st.caption(f"✅ 라이브러리에서 이미지 {len(chosen_imgs)}장 · 영상 {len(chosen_vids)}개 선택됨")
media_files = st.file_uploader(
    "JPG / PNG / MP4 / MOV 여러 개",
    type=["jpg", "jpeg", "png", "webp", "bmp", "mp4", "mov", "webm", "mkv", "m4v"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    key="media",
)
if media_files:
    n_img = sum(1 for m in media_files if Path(m.name).suffix.lower() in IMG_EXTS)
    n_vid = len(media_files) - n_img
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(f"🖼️ 이미지 {n_img}장 · 🎞️ 영상 {n_vid}개 선택됨")
    with c2:
        if st.button("🗑️ 빼기", key="clear_media", use_container_width=True):
            _clear_uploader("media")
            st.rerun()

    # 업로드한 이미지: 미리보기 + 좌우 자르기 모드 + 라이브러리 저장 옵션
    image_uploads = [m for m in media_files if Path(m.name).suffix.lower() in IMG_EXTS]
    if image_uploads:
        with st.expander(f"🔪 업로드한 이미지 {len(image_uploads)}장 미리보기 / 자르기 / 라이브러리에 저장"):
            st.caption("이미지마다 사용할 부분을 골라요. 영상 파일은 자르기 없음 (원본 그대로).")
            for row_start in range(0, len(image_uploads), 2):
                row = image_uploads[row_start:row_start + 2]
                cols = st.columns(2)
                for col, mf in zip(cols, row):
                    with col:
                        crop_key = f"up_crop_{mf.name}_{mf.size}"
                        crop_label = st.session_state.get(crop_key, "그대로")
                        crop_mode_now = CROP_MODES.get(crop_label)
                        h_range_now = st.session_state.get(f"{crop_key}_h", (0, 100))
                        v_range_now = st.session_state.get(f"{crop_key}_v", (0, 100))
                        # 자르기 모드에 맞춰 미리보기를 즉시 잘린 모습으로 표시
                        try:
                            if crop_mode_now:
                                import io
                                from PIL import Image as _PILImage
                                mf.seek(0)
                                _pil = _PILImage.open(io.BytesIO(mf.getvalue()))
                                _cropped = crop_pil_image(
                                    _pil, crop_mode_now,
                                    h_range=h_range_now, v_range=v_range_now,
                                )
                                st.image(_cropped, use_container_width=True)
                                if crop_mode_now == "custom":
                                    st.caption(f"✂️ 직접 지정: 가로 {h_range_now[0]}-{h_range_now[1]}% · 세로 {v_range_now[0]}-{v_range_now[1]}%")
                                else:
                                    st.caption(f"✂️ 자르기 적용: **{crop_label}**")
                            else:
                                st.image(mf, use_container_width=True)
                        except Exception:
                            try:
                                st.image(mf, use_container_width=True)
                            except Exception:
                                pass
                        st.caption(f"📁 {mf.name[:24]}")
                        st.selectbox(
                            "자르기 (선택 즉시 위 미리보기 반영)",
                            options=list(CROP_MODES.keys()),
                            key=crop_key,
                            label_visibility="collapsed",
                        )
                        # 직접 지정이면 가로·세로 범위 슬라이더
                        if st.session_state.get(crop_key) == "직접 지정 ✂️ (슬라이더)":
                            st.slider(
                                "가로 범위 (%)", 0, 100, value=(0, 100),
                                key=f"{crop_key}_h",
                            )
                            st.slider(
                                "세로 범위 (%)", 0, 100, value=(0, 100),
                                key=f"{crop_key}_v",
                            )
                        already_saved = (library_dir("images") / mf.name).exists()
                        if already_saved:
                            st.caption("💾 이미 라이브러리에 있음")
                        else:
                            if st.button("💾 라이브러리 저장", key=f"save_img_{mf.name}_{mf.size}",
                                         use_container_width=True):
                                save_to_library("images", mf)
                                st.rerun()

    # 업로드한 영상: 라이브러리 저장 옵션
    video_uploads = [m for m in media_files if Path(m.name).suffix.lower() in VID_EXTS]
    if video_uploads:
        with st.expander(f"🎞️ 업로드한 영상 {len(video_uploads)}개 라이브러리에 저장"):
            st.caption("영상도 라이브러리에 한 번 저장해두면 다음에 또 쓸 수 있어요.")
            for mf in video_uploads:
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.caption(f"🎞️ {mf.name}")
                with c2:
                    already_saved = (library_dir("videos") / mf.name).exists()
                    if already_saved:
                        st.caption("💾 이미 저장됨")
                    else:
                        if st.button("💾 저장", key=f"save_vid_{mf.name}_{mf.size}",
                                     use_container_width=True):
                            saved = save_to_library("videos", mf)
                            # 썸네일 미리 생성 (다음 라이브러리 표시 빠르게)
                            try:
                                get_or_make_video_thumb(saved)
                            except Exception:
                                pass
                            st.rerun()

# 6) 스톡 이미지 검색 · 미리보기 · 선택 · 자르기
st.markdown(
    '<div class="big-label">6️⃣ 스톡 이미지 검색·선택 (선택, Pexels·Pixabay)</div>',
    unsafe_allow_html=True,
)
with st.expander("🌐 키워드로 스톡 이미지 검색 → 미리보고 선택 → 자르기"):
    source = st.radio(
        "출처",
        ["Pixabay", "Pexels"],
        horizontal=True,
        help="둘 다 무료 스톡 사이트예요. 각자 다른 API 키 필요.",
    )
    if source == "Pixabay":
        key_help = "[Pixabay 무료 API 키 발급](https://pixabay.com/api/docs/) — 가입 후 'Your API key' 복사"
        ss_key = "pixabay_key"
        env_key = "PIXABAY_API_KEY"
    else:
        key_help = "[Pexels 무료 API 키 발급](https://www.pexels.com/api/) — 가입 후 'Your API Key' 복사"
        ss_key = "pexels_key"
        env_key = "PEXELS_API_KEY"
    st.caption(key_help)

    saved_key = st.session_state.get(ss_key, os.environ.get(env_key, ""))
    api_key = st.text_input(
        f"{source} API 키", value=saved_key, type="password",
        key=f"api_input_{source}",
        help="한 번 입력해두면 이 세션 동안 기억해요",
    )
    if api_key:
        st.session_state[ss_key] = api_key

    col_kw, col_cnt = st.columns([2, 1])
    with col_kw:
        stock_keyword = st.text_input(
            "키워드 (예: paris eiffel, ocean, 카페)",
            placeholder="paris eiffel tower",
            key=f"kw_{source}",
        )
    with col_cnt:
        stock_count = st.slider("결과 개수", 3, 30, 12, key=f"cnt_{source}")

    if st.button("🔍 검색하기", use_container_width=True, key=f"go_search_{source}"):
        if not api_key:
            st.error(f"{source} API 키를 먼저 입력해주세요.")
        elif not stock_keyword.strip():
            st.error("키워드를 입력해주세요.")
        else:
            with st.spinner(f"{source}에서 '{stock_keyword}' 검색 중..."):
                try:
                    if source == "Pixabay":
                        items = search_pixabay(stock_keyword.strip(), stock_count, api_key)
                    else:
                        items = search_pexels_images(stock_keyword.strip(), stock_count, api_key)
                    if not items:
                        st.warning("결과가 없어요. 다른 키워드로 시도해주세요.")
                    else:
                        st.session_state["search_results"] = items
                        # 기본은 모두 체크 + 자르기 그대로
                        for it in items:
                            st.session_state[f"sel_{it['id']}"] = True
                            st.session_state.setdefault(f"crop_{it['id']}", "그대로")
                        st.success(f"{len(items)}개 검색됨. 아래에서 골라주세요.")
                except Exception as e:
                    st.error(f"검색 실패: {e}")

    # 검색 결과 그리드
    results = st.session_state.get("search_results", [])
    if results:
        st.markdown("---")
        st.markdown(f"**🖼️ {len(results)}개 검색 결과** — 체크박스로 선택, 자르기 모드 골라주세요.")
        for row_start in range(0, len(results), 2):
            row = results[row_start:row_start + 2]
            cols = st.columns(2)
            for col, it in zip(cols, row):
                with col:
                    crop_key = f"crop_{it['id']}"
                    crop_label = st.session_state.get(crop_key, "그대로")
                    crop_mode_now = CROP_MODES.get(crop_label)
                    h_range_now = st.session_state.get(f"{crop_key}_h", (0, 100))
                    v_range_now = st.session_state.get(f"{crop_key}_v", (0, 100))
                    # 자르기 모드 즉시 미리보기 반영 (썸네일은 캐시됨)
                    try:
                        if crop_mode_now:
                            import io
                            from PIL import Image as _PILImage
                            _thumb_bytes = fetch_thumb_bytes(it["thumb_url"])
                            _pil = _PILImage.open(io.BytesIO(_thumb_bytes))
                            _cropped = crop_pil_image(
                                _pil, crop_mode_now,
                                h_range=h_range_now, v_range=v_range_now,
                            )
                            st.image(_cropped, use_container_width=True)
                            if crop_mode_now == "custom":
                                st.caption(f"✂️ 가로 {h_range_now[0]}-{h_range_now[1]}% · 세로 {v_range_now[0]}-{v_range_now[1]}%")
                            else:
                                st.caption(f"✂️ {crop_label}")
                        else:
                            st.image(it["thumb_url"], use_container_width=True)
                    except Exception:
                        st.caption("(이미지 미리보기 실패)")
                    st.checkbox("사용", value=True, key=f"sel_{it['id']}")
                    st.selectbox(
                        "자르기 (선택 즉시 위 미리보기 반영)",
                        options=list(CROP_MODES.keys()),
                        key=crop_key,
                        label_visibility="collapsed",
                    )
                    if st.session_state.get(crop_key) == "직접 지정 ✂️ (슬라이더)":
                        st.slider(
                            "가로 범위 (%)", 0, 100, value=(0, 100),
                            key=f"{crop_key}_h",
                        )
                        st.slider(
                            "세로 범위 (%)", 0, 100, value=(0, 100),
                            key=f"{crop_key}_v",
                        )

        if st.button("📥 선택한 것만 가져와서 풀에 추가", type="primary",
                     use_container_width=True, key="add_selected"):
            chosen = [it for it in results if st.session_state.get(f"sel_{it['id']}", False)]
            if not chosen:
                st.warning("하나 이상 체크해주세요.")
            else:
                if not st.session_state.get("stock_dir"):
                    st.session_state["stock_dir"] = tempfile.mkdtemp(prefix="stock_")
                stock_dir = Path(st.session_state["stock_dir"])
                if "stock_paths" not in st.session_state:
                    st.session_state["stock_paths"] = []
                added = 0
                with st.spinner(f"{len(chosen)}개 다운로드 + 자르기 중..."):
                    for it in chosen:
                        try:
                            offset = len(st.session_state["stock_paths"])
                            raw = stock_dir / f"raw_{offset:03d}.jpg"
                            download_url_to(it["full_url"], raw)
                            ck = f"crop_{it['id']}"
                            crop_label = st.session_state.get(ck, "그대로")
                            crop_mode = CROP_MODES.get(crop_label)
                            h_r = st.session_state.get(f"{ck}_h", (0, 100)) if crop_mode == "custom" else None
                            v_r = st.session_state.get(f"{ck}_v", (0, 100)) if crop_mode == "custom" else None
                            final = stock_dir / f"stock_{offset:03d}.jpg"
                            crop_image(raw, final, crop_mode, h_range=h_r, v_range=v_r)
                            try:
                                if raw.exists() and raw != final:
                                    raw.unlink()
                            except Exception:
                                pass
                            st.session_state["stock_paths"].append(str(final))
                            added += 1
                        except Exception as e:
                            st.warning(f"한 개 실패: {e}")
                st.success(f"✅ {added}개 추가 · 풀 총 {len(st.session_state['stock_paths'])}개")

    # 현재 풀 상태
    pool_n = len(st.session_state.get("stock_paths", []))
    if pool_n > 0:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.caption(f"📦 스톡 풀: **{pool_n}개** (만들기 누르면 같이 사용돼요)")
        with c2:
            if st.button("🗑️ 풀 비우기", key="clear_stock_pool", use_container_width=True):
                st.session_state["stock_paths"] = []
                st.session_state["stock_dir"] = None
                st.rerun()

# 이미지 좌우 패닝 효과 (켄번스)
pan_enabled = st.checkbox(
    "🎞️ 이미지에 좌우 패닝 효과 넣기 (살짝 움직임)",
    value=True,
    help="이미지가 4분 30초 동안 천천히 가로로 움직여요. "
         "체크 안 하면 정지 이미지로 컷 전환만 됩니다.",
)
pan_mode = "alternate"
if pan_enabled:
    pan_mode_label = st.selectbox(
        "패닝 방향",
        options=list(PAN_MODES.keys()),
        index=2,  # 기본: 왔다 갔다 (오→왼→오) — 사용자 요청에 맞춤
        help=(
            "**번갈아 자동**: 이미지마다 방향 교대 (자연스러운 다양성)\n\n"
            "**왔다 갔다**: 한 이미지 안에서 한쪽으로 갔다가 부드럽게 되돌아옴 (멈춤 없음)\n\n"
            "**모두 같은 방향**: 모든 이미지가 같은 방향으로 패닝"
        ),
    )
    pan_mode = PAN_MODES[pan_mode_label]

# 영상에 오디오 포함 여부 (기본: 무음 — 캡컷에서 합치기 좋게)
bake_audio_in_video = st.checkbox(
    "🎬 영상 MP4 에 음악·자연소리도 같이 깔기",
    value=False,
    help="기본은 무음 영상이에요 — 캡컷에서 음악과 따로 합치기 좋아요. 체크하면 음악과 자연소리가 영상에 같이 들어가요.",
)
if not bake_audio_in_video:
    st.caption("ℹ️ 영상은 **무음**으로 만들어요. MP3 와 MP4 를 따로 받아 캡컷에서 합치세요.")
else:
    st.caption("ℹ️ 영상에 음악·자연소리가 같이 들어가요. MP4 한 개로 바로 업로드 가능.")

st.markdown("---")

# ── 만들기 직전 요약 카드 ─────────────────────────
n_music = len(music_files) if music_files else 0
n_media_uploaded = len(media_files) if media_files else 0
n_stock = len(st.session_state.get("stock_paths", []))
n_lib = len(st.session_state.get("lib_image_paths", []))
n_media_total = n_media_uploaded + n_stock + n_lib
target_sec_preview = DUR_MAP[duration_choice]

# 매우 거친 예상 시간 (PC 성능에 따라 다름)
est_min = max(1, int(target_sec_preview / 1800))           # 음악 인코딩
if nature_file is not None:
    est_min += 1
est_min += max(0, n_media_total) * 1                       # 미디어당 ~1분
est_min += max(0, int(target_sec_preview / 7200))          # 최종 합성

summary_lines = []
if n_music:
    summary_lines.append(f"🎵 음악 **{n_music}곡** → **{duration_choice}** ({order_mode})")
else:
    summary_lines.append("🎵 음악 — _아직 안 올리셨어요_")
if nature_file is not None:
    if nature_on_sec > 0 and nature_off_sec > 0:
        summary_lines.append(
            f"🌿 자연 소리 {nature_volume_pct}% · {nature_on_sec}초 들리고 {nature_off_sec}초 쉬기"
        )
    else:
        summary_lines.append(f"🌿 자연 소리 {nature_volume_pct}% (계속)")
if n_media_total > 0:
    parts = []
    if n_media_uploaded:
        parts.append(f"직접 {n_media_uploaded}개")
    if n_lib:
        parts.append(f"라이브러리 {n_lib}개")
    if n_stock:
        parts.append(f"스톡 {n_stock}개")
    extra = "음악 같이 깔린 영상" if (bake_audio_in_video and n_music) else "무음 영상 (캡컷용)"
    summary_lines.append(f"🎬 배경 미디어 {n_media_total}개 ({' + '.join(parts)}) → **{extra}**")
else:
    if n_music:
        summary_lines.append("🎬 배경 없음 → MP3 만 생성")
summary_lines.append(f"⏱️ 예상 소요 **약 {est_min}분** _(PC 성능에 따라 달라요)_")

st.markdown(
    "<div style='background:#fefce8; border:1px solid #fde047; border-radius:10px; "
    "padding:0.8rem 1rem; margin-bottom:0.8rem; font-size:0.95rem; line-height:1.7;'>"
    "<b>📋 만들 내용 미리보기</b><br>"
    + "<br>".join(summary_lines) +
    "</div>",
    unsafe_allow_html=True,
)

# 미리보기 + 만들기 버튼
col_p, col_g = st.columns([1, 1])
with col_p:
    preview_clicked = st.button(
        "🔍 미리보기 30초",
        use_container_width=True,
        help="짧은 샘플 영상으로 어떻게 합쳐지는지 미리 봐요 (이미지 5초씩 빠르게 패닝)",
    )
with col_g:
    go = st.button("🎬 만들기 시작", type="primary", use_container_width=True)

# 미리보기 처리 — 선택된 미디어로 30초 무음 샘플 영상 생성
if preview_clicked:
    has_media_for_preview = (
        bool(media_files)
        or bool(st.session_state.get("stock_paths"))
        or bool(st.session_state.get("lib_image_paths"))
    )
    if not has_media_for_preview:
        st.warning("미리보기는 이미지·영상을 한 장이라도 선택한 후 가능해요!")
    else:
        with st.spinner("🔍 30초 미리보기 영상 만드는 중... (10~20초 걸려요)"):
            try:
                preview_dir = Path(tempfile.mkdtemp(prefix="preview_"))
                # 미디어 수집 + 자르기 적용 (만들기 로직과 동일하지만 preview_dir 에 저장)
                preview_media = []
                if media_files:
                    for i, imf in enumerate(media_files):
                        ext = Path(imf.name).suffix.lower() or ".jpg"
                        p = preview_dir / f"media_{i:03d}{ext}"
                        with open(p, "wb") as f:
                            f.write(imf.getbuffer())
                        if ext in IMG_EXTS:
                            ck = f"up_crop_{imf.name}_{imf.size}"
                            cmode = CROP_MODES.get(st.session_state.get(ck, "그대로"))
                            if cmode:
                                h_r = st.session_state.get(f"{ck}_h", (0, 100)) if cmode == "custom" else None
                                v_r = st.session_state.get(f"{ck}_v", (0, 100)) if cmode == "custom" else None
                                cp = preview_dir / f"media_{i:03d}_c{ext}"
                                crop_image(p, cp, cmode, h_range=h_r, v_range=v_r)
                                p = cp
                        preview_media.append(p)
                for lib_p_str in st.session_state.get("lib_image_paths", []):
                    if not os.path.exists(lib_p_str):
                        continue
                    lib_p = Path(lib_p_str)
                    if lib_p.suffix.lower() in IMG_EXTS:
                        ck = f"lib_crop_{lib_p.name}"
                        cmode = CROP_MODES.get(st.session_state.get(ck, "그대로"))
                        if cmode:
                            h_r = st.session_state.get(f"{ck}_h", (0, 100)) if cmode == "custom" else None
                            v_r = st.session_state.get(f"{ck}_v", (0, 100)) if cmode == "custom" else None
                            cp = preview_dir / f"lib_c_{lib_p.stem}{lib_p.suffix}"
                            crop_image(lib_p, cp, cmode, h_range=h_r, v_range=v_r)
                            preview_media.append(cp)
                            continue
                    preview_media.append(lib_p)
                for stock_p in st.session_state.get("stock_paths", []):
                    if os.path.exists(stock_p):
                        preview_media.append(Path(stock_p))

                if not preview_media:
                    st.error("미리볼 미디어가 없어요!")
                else:
                    # 각 이미지 5초씩 + 총 30초 (이미지 많으면 핑퐁 한 사이클)
                    preview_out = build_video(
                        preview_media, 30, preview_dir,
                        audio_path=None,
                        pan_enabled=pan_enabled,
                        pan_mode=pan_mode,
                        image_duration=5,
                    )
                    st.session_state["preview_path"] = str(preview_out)
            except Exception as e:
                st.error(f"미리보기 실패: {e}")

# 미리보기 영상 표시
if st.session_state.get("preview_path") and os.path.exists(st.session_state["preview_path"]):
    st.markdown("#### 🔍 30초 미리보기 (실제 영상은 이미지마다 4분 30초씩 천천히 패닝)")
    st.video(st.session_state["preview_path"])
    st.caption("⬆️ 어떻게 합쳐지고 흐를지 미리 보고, 마음에 들면 ⬇️ '만들기 시작' 누르세요.")

if go:
    has_music = bool(music_files)
    has_media_input = (
        bool(media_files)
        or bool(st.session_state.get("stock_paths"))
        or bool(st.session_state.get("lib_image_paths"))
    )
    if not has_music and not has_media_input:
        st.error("음악 또는 이미지/영상 중 하나는 꼭 올려주세요!")
    else:
        # 이전 임시폴더 정리 (디스크 청소)
        import shutil as _sh
        old_wd = st.session_state.get("workdir")
        if old_wd and os.path.exists(old_wd):
            try:
                _sh.rmtree(old_wd)
            except Exception:
                pass
        st.session_state.pop("audio_path", None)
        st.session_state.pop("video_path", None)

        target_sec = DUR_MAP[duration_choice]
        progress = st.progress(0, text="준비 중...")
        try:
            workdir = Path(tempfile.mkdtemp(prefix="merger_"))
            st.session_state["workdir"] = str(workdir)

            audio_out = None

            if has_music:
                # 음악 파일 저장 — 원본 파일명도 함께 보관 (트랙리스트용)
                progress.progress(10, text="음악 파일 저장 중...")
                music_items = []  # [(safe_path, original_name), ...]
                for i, mf in enumerate(music_files):
                    safe_name = f"track_{i:03d}{Path(mf.name).suffix.lower()}"
                    p = workdir / safe_name
                    with open(p, "wb") as f:
                        f.write(mf.getbuffer())
                    music_items.append((p, mf.name))
                if order_mode == "랜덤 섞기":
                    random.shuffle(music_items)
                music_paths = [item[0] for item in music_items]

                # 자연의 소리 경로 결정
                # - 라이브러리 선택: nature_path_for_build 에 이미 Path 가 들어있음 → 그대로 사용
                # - 새 업로드: workdir 에 저장 후 그 경로 사용
                nature_path = None
                if nature_path_for_build is not None and Path(nature_path_for_build).exists():
                    nature_path = Path(nature_path_for_build)
                elif nature_file is not None and hasattr(nature_file, "getbuffer"):
                    ext = Path(nature_file.name).suffix.lower() or ".mp3"
                    nature_path = workdir / f"nature{ext}"
                    with open(nature_path, "wb") as f:
                        f.write(nature_file.getbuffer())

                stage_msg = f"{duration_choice} 분량으로 이어붙이는 중... (몇 분 걸려요)"
                if nature_path is not None:
                    stage_msg = f"{duration_choice} 분량 + 자연의 소리 섞는 중... (몇 분 걸려요)"
                progress.progress(25, text=stage_msg)
                audio_out = build_audio(
                    music_paths, target_sec, workdir,
                    nature_path=nature_path,
                    nature_volume=nature_volume_pct / 100.0,
                    nature_on_sec=nature_on_sec,
                    nature_off_sec=nature_off_sec,
                    join_mode=join_mode,
                    crossfade_sec=crossfade_sec_val,
                )
                st.session_state["audio_path"] = str(audio_out)
                st.session_state["audio_label"] = duration_choice
                # 유튜브 설명란용 트랙리스트 생성 (크로스페이드 반영)
                try:
                    st.session_state["tracklist_text"] = build_tracklist_text(
                        music_items, target_sec,
                        crossfade_sec=(crossfade_sec_val if join_mode == "crossfade" else 0),
                    )
                except Exception:
                    st.session_state["tracklist_text"] = ""

            # 배경 미디어(직접 업로드 + 스톡 풀) 모으기
            media_paths = []
            if media_files:
                for i, imf in enumerate(media_files):
                    ext = Path(imf.name).suffix.lower() or ".jpg"
                    p = workdir / f"media_{i:03d}{ext}"
                    with open(p, "wb") as f:
                        f.write(imf.getbuffer())
                    # 업로드한 이미지에 자르기 모드 선택돼 있으면 적용
                    if ext in IMG_EXTS:
                        crop_key = f"up_crop_{imf.name}_{imf.size}"
                        crop_label = st.session_state.get(crop_key, "그대로")
                        crop_mode = CROP_MODES.get(crop_label)
                        if crop_mode:
                            h_r = st.session_state.get(f"{crop_key}_h", (0, 100)) if crop_mode == "custom" else None
                            v_r = st.session_state.get(f"{crop_key}_v", (0, 100)) if crop_mode == "custom" else None
                            cropped = workdir / f"media_{i:03d}_cropped{ext}"
                            crop_image(p, cropped, crop_mode, h_range=h_r, v_range=v_r)
                            p = cropped
                    media_paths.append(p)
            # 라이브러리에서 골라둔 이미지·영상 풀에 추가 (이미지는 자르기 모드 적용)
            for lib_p_str in st.session_state.get("lib_image_paths", []):
                if not os.path.exists(lib_p_str):
                    continue
                lib_p = Path(lib_p_str)
                if lib_p.suffix.lower() in IMG_EXTS:
                    lib_ck = f"lib_crop_{lib_p.name}"
                    lib_crop_label = st.session_state.get(lib_ck, "그대로")
                    lib_crop_mode = CROP_MODES.get(lib_crop_label)
                    if lib_crop_mode:
                        h_r = st.session_state.get(f"{lib_ck}_h", (0, 100)) if lib_crop_mode == "custom" else None
                        v_r = st.session_state.get(f"{lib_ck}_v", (0, 100)) if lib_crop_mode == "custom" else None
                        ext_lib = lib_p.suffix.lower()
                        cropped_lib = workdir / f"lib_cropped_{lib_p.stem}{ext_lib}"
                        crop_image(lib_p, cropped_lib, lib_crop_mode, h_range=h_r, v_range=v_r)
                        media_paths.append(cropped_lib)
                        continue
                media_paths.append(lib_p)
            for stock_p in st.session_state.get("stock_paths", []):
                if os.path.exists(stock_p):
                    media_paths.append(Path(stock_p))

            if media_paths:
                mode_msg = "음악 깔린 영상" if (bake_audio_in_video and audio_out) else "무음 영상"
                progress.progress(55, text=f"{mode_msg} 만드는 중... ({len(media_paths)}개 미디어 정규화)")

                def _prog(done, total):
                    pct = 55 + int(35 * done / max(1, total))
                    progress.progress(min(pct, 90), text=f"미디어 정규화 {done}/{total}...")

                video_audio = audio_out if (bake_audio_in_video and audio_out) else None
                # 곡 동기화: 각 이미지의 표시 시간을 곡 길이에 맞춤 (이미지가 적으면 순환)
                img_durations = None
                if sync_images_to_songs and has_music:
                    try:
                        song_durs = [max(_probe_duration(p), 1.0) for p, _ in music_items]
                        if join_mode == "crossfade" and len(song_durs) > 1:
                            # 크로스페이드로 겹치는 시간만큼 시간 차감 (마지막 곡 제외)
                            song_durs = [
                                d - crossfade_sec_val if i < len(song_durs) - 1 else d
                                for i, d in enumerate(song_durs)
                            ]
                        # 이미지 수 만큼 곡 순환
                        img_durations = [
                            song_durs[i % len(song_durs)] for i in range(len(media_paths))
                        ]
                    except Exception:
                        img_durations = None
                video_out = build_video(
                    media_paths, target_sec, workdir,
                    audio_path=video_audio,
                    pan_enabled=pan_enabled,
                    pan_mode=pan_mode,
                    image_durations=img_durations,
                    progress_cb=_prog,
                )
                st.session_state["video_path"] = str(video_out)
                st.session_state["audio_label"] = duration_choice

            progress.progress(100, text="완성!")
            st.success("✅ 다 됐어요! 아래에서 다운로드 받으세요.")
        except Exception as e:
            progress.empty()
            st.error(f"오류가 났어요: {e}")

# 결과 다운로드 + 미리보기 + 다시 시작하기
_has_audio_out = bool(st.session_state.get("audio_path")) and os.path.exists(
    st.session_state.get("audio_path", "")
)
_has_video_out = bool(st.session_state.get("video_path")) and os.path.exists(
    st.session_state.get("video_path", "")
)

if _has_audio_out or _has_video_out:
    st.markdown("### 🎁 결과물")
    label = st.session_state.get("audio_label", "")

    if _has_audio_out:
        audio_path = st.session_state["audio_path"]
        audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        with open(audio_path, "rb") as f:
            st.download_button(
                f"📥 음악 MP3 다운로드 ({audio_size_mb:.1f} MB)",
                f,
                file_name=f"music_{label}.mp3",
                mime="audio/mpeg",
                key="dl_audio",
            )
        with st.expander("🔊 다운로드 전 미리듣기"):
            st.caption("긴 파일은 처음 부분만 듣고 마음에 들면 다운로드하세요.")
            st.audio(audio_path, format="audio/mp3")

        # 유튜브 설명란용 트랙리스트 — 코드 블록의 우상단 📋 복사 버튼 활용
        tracklist = st.session_state.get("tracklist_text", "")
        if tracklist:
            st.markdown("#### 📋 유튜브 설명란용 트랙 리스트")
            st.caption(
                "아래 박스 우상단 **복사 아이콘** 을 눌러 그대로 복사 → "
                "유튜브 영상 설명에 붙여넣기. "
                "**첫 줄이 0:00** 으로 시작하고 챕터가 3개 이상이면 "
                "유튜브가 자동으로 클릭 가능한 챕터로 만들어줘요."
            )
            st.code(tracklist, language=None)
            st.download_button(
                "📥 트랙리스트 .txt 로 받기",
                tracklist.encode("utf-8"),
                file_name=f"tracklist_{label}.txt",
                mime="text/plain",
                key="dl_tracklist",
            )

    if _has_video_out:
        video_path = st.session_state["video_path"]
        video_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        with open(video_path, "rb") as f:
            st.download_button(
                f"📥 영상 MP4 다운로드 ({video_size_mb:.1f} MB)",
                f,
                file_name=f"video_{label}.mp4",
                mime="video/mp4",
                key="dl_video",
            )
        with st.expander("🎬 다운로드 전 미리보기"):
            st.caption("긴 영상은 로딩에 시간이 좀 걸려요.")
            st.video(video_path)

    st.caption("💡 이 파일을 **캡컷**에 그대로 가져가서 마무리하세요!")

    # 다시 시작하기 — 결과·임시 폴더 비우고 새로 시작
    if st.button("🔄 다시 시작하기 (결과 비우기)", key="reset", help="이번 결과물을 지우고 새로 만들 수 있어요"):
        import shutil as _sh
        wd = st.session_state.get("workdir")
        if wd and os.path.exists(wd):
            try:
                _sh.rmtree(wd)
            except Exception:
                pass
        for k in ("audio_path", "video_path", "workdir", "audio_label",
                  "preview_path", "tracklist_text"):
            st.session_state.pop(k, None)
        st.rerun()

# 약관 링크
st.markdown(
    '<div class="footer-links">'
    '<a href="/이용약관" target="_self">이용약관</a> · '
    '<a href="/개인정보처리방침" target="_self">개인정보처리방침</a>'
    '</div>',
    unsafe_allow_html=True,
)

# 광고 영역 (맨 아래 고정, 내용 안 가림)
st.markdown(
    '<div class="ad-box">광고 영역</div>',
    unsafe_allow_html=True,
)
