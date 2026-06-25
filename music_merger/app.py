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
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

PEXELS_PHOTO_API = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
PIXABAY_API = "https://pixabay.com/api/"

CROP_MODES = {
    "그대로": None,
    "왼쪽만 (50%)": "left_50",
    "오른쪽만 (50%)": "right_50",
    "가운데만 (50%)": "center_50",
    "왼쪽 위주 (70%)": "left_70",
    "오른쪽 위주 (70%)": "right_70",
}


def is_image(path):
    return Path(path).suffix.lower() in IMG_EXTS


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


def crop_image(img_path, output_path, mode):
    """이미지 좌우 자르기. mode: left_50 / right_50 / center_50 / left_70 / right_70."""
    if not mode:
        # 자르기 안 함 — 그대로 복사
        if str(img_path) != str(output_path):
            import shutil as _sh
            _sh.copyfile(img_path, output_path)
        return output_path
    from PIL import Image
    img = Image.open(img_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    boxes = {
        "left_50":  (0,            0, w // 2,       h),
        "right_50": (w // 2,       0, w,            h),
        "center_50":(w // 4,       0, 3 * w // 4,   h),
        "left_70":  (0,            0, int(w * 0.7), h),
        "right_70": (int(w * 0.3), 0, w,            h),
    }
    box = boxes.get(mode)
    if not box:
        return img_path
    img.crop(box).save(output_path, quality=92)
    return output_path


def preprocess_to_segment(input_path, output_path, fixed_duration=None, pan_direction=None):
    """이미지/영상을 1280x720 30fps mp4 세그먼트로 통일.
    이미지는 fixed_duration(기본 4:30) 길이로, 영상은 본래 길이로 인코딩.

    pan_direction='ltr' 또는 'rtl' 이면 이미지가 그 방향으로 천천히 패닝.
    영상 파일은 무시(원본 모션 유지)."""
    if is_image(input_path):
        duration = fixed_duration or IMG_INTERVAL
        if pan_direction in ("ltr", "rtl"):
            # 좌우 패닝: 캔버스를 키운 뒤 1280x720 뷰포트가 가로로 이동
            if pan_direction == "ltr":
                x_expr = f"(iw-1280)*t/{duration}"
            else:
                x_expr = f"(iw-1280)*(1-t/{duration})"
            vf = (
                f"scale=2240:1260:force_original_aspect_ratio=increase,"
                f"crop=1280:720:'{x_expr}':'(ih-720)/2',"
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


def build_audio(music_paths, total_seconds, workdir,
                nature_path=None, nature_volume=0.3,
                nature_on_sec=0, nature_off_sec=0):
    """음악들을 이어붙여 정확한 길이의 mp3로 만든다. 자연의 소리가 있으면 위에 깐다.

    nature_off_sec > 0 이면 on_sec 동안 들리고 off_sec 동안 쉬는 패턴 반복."""
    # 각 곡 길이를 미리 재서 총 길이 산출 → 몇 번 반복해야 목표 길이를 덮는지 계산
    per_song = [max(_probe_duration(p), 0.1) for p in music_paths]
    cycle_sec = sum(per_song)
    if cycle_sec <= 0:
        raise RuntimeError("음악 파일에서 길이를 읽지 못했습니다.")
    # 여유 있게 1번 더 반복
    loops = int(total_seconds // cycle_sec) + 2

    playlist = workdir / "playlist.txt"
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


def build_video(media_paths, total_seconds, workdir, audio_path=None, pan_enabled=True, progress_cb=None):
    """이미지/영상 혼합을 핑퐁 순서로 잇고, 정해진 길이로 채우는 영상.

    audio_path=None 이면 무음 영상 (캡컷에서 음악과 따로 합치기 좋게).
    pan_enabled=True 이면 이미지마다 좌우 패닝(켄번스). 짝수번 이미지는 왼→오,
    홀수번은 오→왼 으로 번갈아 가며 '왔다 갔다' 느낌이 살아남.
    이미지는 4:30씩, 영상은 본래 길이대로 나옴."""
    # 1) 각 입력을 1280x720 30fps mp4 세그먼트로 정규화
    segments = []
    image_idx = 0
    for i, p in enumerate(media_paths):
        seg = workdir / f"seg_{i:03d}.mp4"
        direction = None
        if pan_enabled and is_image(p):
            direction = "ltr" if image_idx % 2 == 0 else "rtl"
            image_idx += 1
        preprocess_to_segment(p, seg, fixed_duration=IMG_INTERVAL, pan_direction=direction)
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
        for k in ("music", "nature", "media", "stock_paths", "stock_dir",
                  "audio_path", "video_path", "workdir", "audio_label"):
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

# 2) 자연의 소리 (선택)
st.markdown('<div class="big-label">2️⃣ 자연의 소리 (선택)</div>', unsafe_allow_html=True)
st.caption("빗소리·파도·새소리 같은 파일을 올리면 음악 위에 살짝 깔아드려요")
nature_file = st.file_uploader(
    "MP3 / WAV / M4A 한 개",
    type=["mp3", "wav", "m4a", "aac", "ogg", "flac"],
    accept_multiple_files=False,
    label_visibility="collapsed",
    key="nature",
)
nature_volume_pct = 30
nature_pattern = "계속 들리게"
nature_on_sec = 0
nature_off_sec = 0
if nature_file is not None:
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(f"🌿 {nature_file.name}")
    with c2:
        if st.button("🗑️ 빼기", key="clear_nature", use_container_width=True):
            _clear_uploader("nature")
            st.rerun()
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

# 4) 순서
st.markdown('<div class="big-label">4️⃣ 재생 순서</div>', unsafe_allow_html=True)
order_mode = st.radio(
    "재생 순서",
    ["순서대로 이어주기", "랜덤 섞기"],
    label_visibility="collapsed",
)

# 5) 배경 이미지·영상 (선택, 직접 업로드)
st.markdown('<div class="big-label">5️⃣ 배경 이미지·영상 (선택)</div>', unsafe_allow_html=True)
st.caption("직접 올린 이미지(4분 30초씩) · 영상(본래 길이)을 왔다 갔다 보여줘요")
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
                    try:
                        st.image(it["thumb_url"], use_container_width=True)
                    except Exception:
                        st.caption("(이미지 미리보기 실패)")
                    st.checkbox("사용", value=True, key=f"sel_{it['id']}")
                    st.selectbox(
                        "자르기",
                        options=list(CROP_MODES.keys()),
                        key=f"crop_{it['id']}",
                        label_visibility="collapsed",
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
                            crop_label = st.session_state.get(f"crop_{it['id']}", "그대로")
                            crop_mode = CROP_MODES.get(crop_label)
                            final = stock_dir / f"stock_{offset:03d}.jpg"
                            crop_image(raw, final, crop_mode)
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
    help="이미지가 4분 30초 동안 왼→오 또는 오→왼 으로 천천히 움직여요. "
         "캡컷에서 좌우로 붙인 합성 이미지(예: 에펠탑+카페)에 특히 잘 어울려요. "
         "체크 안 하면 정지 이미지로 컷 전환만 됩니다.",
)

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
n_media_total = n_media_uploaded + n_stock
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

# 만들기 버튼
go = st.button("🎬 만들기 시작", type="primary")

if go:
    has_music = bool(music_files)
    has_media_input = bool(media_files) or bool(st.session_state.get("stock_paths"))
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
                # 음악 파일 저장
                progress.progress(10, text="음악 파일 저장 중...")
                music_paths = []
                for i, mf in enumerate(music_files):
                    safe_name = f"track_{i:03d}{Path(mf.name).suffix.lower()}"
                    p = workdir / safe_name
                    with open(p, "wb") as f:
                        f.write(mf.getbuffer())
                    music_paths.append(p)
                if order_mode == "랜덤 섞기":
                    random.shuffle(music_paths)

                # 자연의 소리 저장 (있으면)
                nature_path = None
                if nature_file is not None:
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
                )
                st.session_state["audio_path"] = str(audio_out)
                st.session_state["audio_label"] = duration_choice

            # 배경 미디어(직접 업로드 + 스톡 풀) 모으기
            media_paths = []
            if media_files:
                for i, imf in enumerate(media_files):
                    ext = Path(imf.name).suffix.lower() or ".jpg"
                    p = workdir / f"media_{i:03d}{ext}"
                    with open(p, "wb") as f:
                        f.write(imf.getbuffer())
                    media_paths.append(p)
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
                video_out = build_video(
                    media_paths, target_sec, workdir,
                    audio_path=video_audio,
                    pan_enabled=pan_enabled,
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
if st.session_state.get("audio_path") and os.path.exists(st.session_state["audio_path"]):
    st.markdown("### 🎁 결과물")
    audio_path = st.session_state["audio_path"]
    label = st.session_state.get("audio_label", "")
    audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

    # 음악 다운로드 + 미리듣기
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

    # 영상 다운로드 + 미리보기
    if st.session_state.get("video_path") and os.path.exists(st.session_state["video_path"]):
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
        for k in ("audio_path", "video_path", "workdir", "audio_label"):
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
