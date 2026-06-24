"""음악 이어붙이기 + 이미지 슬라이드 영상 만들기 앱"""
import os
import random
import subprocess
import tempfile
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
</style>
""",
    unsafe_allow_html=True,
)


DUR_MAP = {"1시간": 3600, "2시간": 7200, "3시간": 10800, "6시간": 21600}
IMG_INTERVAL = 270  # 4분 30초


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


def build_video(image_paths, audio_path, total_seconds, workdir):
    """이미지를 왔다갔다(핑퐁) 순서로 4:30씩 보여주는 영상."""
    if len(image_paths) > 1:
        # 1,2,3,...,n,n-1,...,2 → 다시 처음으로 (왔다 갔다)
        pingpong = list(image_paths) + list(image_paths[-2:0:-1])
    else:
        pingpong = list(image_paths)

    n_slots = (total_seconds // IMG_INTERVAL) + 2  # 여유 있게
    img_list = workdir / "imglist.txt"
    with open(img_list, "w", encoding="utf-8") as f:
        last_path = None
        for i in range(n_slots):
            p = pingpong[i % len(pingpong)]
            f.write(f"file '{p.as_posix()}'\n")
            f.write(f"duration {IMG_INTERVAL}\n")
            last_path = p
        # concat demuxer 규약상 마지막 파일은 duration 없이 한 번 더
        f.write(f"file '{last_path.as_posix()}'\n")

    video_out = workdir / "output_video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(img_list),
        "-i", str(audio_path),
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-t", str(total_seconds),
        "-shortest",
        str(video_out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-800:])
    return video_out


# ===================== UI =====================
st.title("🎵 음악 이어붙이기")
st.caption("음악과 이미지를 골라 긴 영상으로 만들어요 · 캡컷에 그대로 가져가세요")

# 1) 음악 업로드
st.markdown('<div class="big-label">1️⃣ 음악 파일 올리기</div>', unsafe_allow_html=True)
music_files = st.file_uploader(
    "MP3 / WAV / M4A 등 여러 개 가능",
    type=["mp3", "wav", "m4a", "aac", "ogg", "flac"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    key="music",
)
if music_files:
    st.caption(f"✅ {len(music_files)}곡 선택됨")

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
    st.caption(f"🌿 {nature_file.name}")
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

# 5) 이미지 (선택)
st.markdown('<div class="big-label">5️⃣ 배경 이미지 (선택)</div>', unsafe_allow_html=True)
st.caption("올리면 **4분 30초**마다 이미지가 왔다 갔다 하는 영상도 같이 만들어요")
image_files = st.file_uploader(
    "JPG / PNG 여러 개",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    key="images",
)
if image_files:
    st.caption(f"🖼️ {len(image_files)}장 선택됨")

st.markdown("---")

# 만들기 버튼
go = st.button("🎬 만들기 시작", type="primary")

if go:
    if not music_files:
        st.error("음악 파일을 먼저 올려주세요!")
    else:
        target_sec = DUR_MAP[duration_choice]
        progress = st.progress(0, text="준비 중...")
        try:
            workdir = Path(tempfile.mkdtemp(prefix="merger_"))

            # 음악 파일 저장
            progress.progress(10, text="음악 파일 저장 중...")
            music_paths = []
            for i, mf in enumerate(music_files):
                # 파일명에 따옴표/공백이 있어도 안전하도록 새 이름 부여
                safe_name = f"track_{i:03d}{Path(mf.name).suffix.lower()}"
                p = workdir / safe_name
                with open(p, "wb") as f:
                    f.write(mf.getbuffer())
                music_paths.append(p)

            # 순서
            if order_mode == "랜덤 섞기":
                random.shuffle(music_paths)

            # 자연의 소리 저장 (있으면)
            nature_path = None
            if nature_file is not None:
                ext = Path(nature_file.name).suffix.lower() or ".mp3"
                nature_path = workdir / f"nature{ext}"
                with open(nature_path, "wb") as f:
                    f.write(nature_file.getbuffer())

            # 음악 합치기 (+ 자연의 소리 믹스)
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
            st.session_state.pop("video_path", None)

            # 이미지가 있으면 영상도
            if image_files:
                progress.progress(60, text="이미지 영상도 만드는 중...")
                img_paths = []
                for i, imf in enumerate(image_files):
                    ext = Path(imf.name).suffix.lower() or ".jpg"
                    p = workdir / f"img_{i:03d}{ext}"
                    with open(p, "wb") as f:
                        f.write(imf.getbuffer())
                    img_paths.append(p)

                video_out = build_video(img_paths, audio_out, target_sec, workdir)
                st.session_state["video_path"] = str(video_out)

            progress.progress(100, text="완성!")
            st.success("✅ 다 됐어요! 아래에서 다운로드 받으세요.")
        except Exception as e:
            progress.empty()
            st.error(f"오류가 났어요: {e}")

# 결과 다운로드
if st.session_state.get("audio_path") and os.path.exists(st.session_state["audio_path"]):
    st.markdown("### 🎁 결과물")
    audio_path = st.session_state["audio_path"]
    label = st.session_state.get("audio_label", "")
    with open(audio_path, "rb") as f:
        st.download_button(
            "📥 음악 MP3 다운로드",
            f,
            file_name=f"music_{label}.mp3",
            mime="audio/mpeg",
            key="dl_audio",
        )
    if st.session_state.get("video_path") and os.path.exists(st.session_state["video_path"]):
        with open(st.session_state["video_path"], "rb") as f:
            st.download_button(
                "📥 영상 MP4 다운로드",
                f,
                file_name=f"video_{label}.mp4",
                mime="video/mp4",
                key="dl_video",
            )
    st.caption("💡 이 파일을 **캡컷**에 그대로 가져가서 마무리하세요!")

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
