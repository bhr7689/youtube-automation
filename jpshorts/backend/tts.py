"""TTS + narration job 패키지 — 문장별 일본어 음성 + manifest/자막/ZIP.

설계(ideas): 문장별 개별 합성(⭐) → 문장마다 정확한 duration → 컷편집이 manifest.json
하나로 문장·시간·오디오·자막을 전부 읽는다.

TTS 엔진: VOICEVOX(로컬 http://127.0.0.1:50021). 미가동이면 '무음 WAV(추정 길이)'로
폴백 — 패키지(manifest+SRT)는 항상 완성되어 컷편집으로 넘어갈 수 있다(음성은 나중에 교체).
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.parse
import urllib.request
import wave
import zipfile

import translator

VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "narration_jobs")
SR = 48000  # 48kHz 16bit mono

# 시안의 4개 화자 → VOICEVOX speaker id
VOICES = [
    {"id": 3,  "key": "zundamon",  "name": "🌱 ずんだもん", "desc": "귀엽고 친근한 톤 (가장 인기)"},
    {"id": 2,  "key": "metan",     "name": "🌸 四国めたん", "desc": "차분한 여성 톤, 정보·다큐형"},
    {"id": 8,  "key": "tsumugi",   "name": "🌷 春日部つむぎ", "desc": "밝고 또렷한 톤"},
    {"id": 10, "key": "hau",       "name": "🍀 雨晴はう", "desc": "부드럽고 따스한 톤, 시니어 친화"},
]


def voicevox_available() -> bool:
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _synth_voicevox(text: str, speaker: int, speed: float) -> bytes | None:
    try:
        q = urllib.parse.urlencode({"text": text, "speaker": speaker})
        req = urllib.request.Request(f"{VOICEVOX_URL}/audio_query?{q}", method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            query = json.loads(r.read())
        query["speedScale"] = speed
        body = json.dumps(query).encode()
        req2 = urllib.request.Request(
            f"{VOICEVOX_URL}/synthesis?speaker={speaker}", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req2, timeout=60) as r:
            return r.read()
    except Exception:
        return None


def _silent_wav(duration_ms: int) -> bytes:
    """무음 WAV(48kHz 16bit mono) — TTS 미가동 시 길이 자리표시자."""
    frames = int(SR * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def _wav_duration_ms(data: bytes) -> int:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return int(1000 * w.getnframes() / w.getframerate())
    except Exception:
        return 0


def _srt_time(ms: int) -> str:
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_job(sentences: list[dict], voice: int = 3, speed: float = 1.2,
              pause_ms: int = 300, source_lang: str = "ko") -> dict:
    """문장 리스트 → narration job 폴더(manifest/script/audio/srt) + ZIP.

    sentences: [{"id":1,"jp":"...","src":"..."}, ...]
    반환: manifest dict (+ zip_path, engine).
    """
    os.makedirs(JOBS_DIR, exist_ok=True)
    job_id = "nj_" + time.strftime("%Y%m%d_%H%M%S")
    job_dir = os.path.join(JOBS_DIR, job_id)
    audio_dir = os.path.join(job_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    use_vv = voicevox_available()
    engine = "voicevox" if use_vv else "silent_fallback"

    manifest_sentences = []
    srt_lines = []
    cursor = 0
    full_pcm = bytearray()
    for i, s in enumerate(sentences, 1):
        jp = s.get("jp", "").strip()
        if not jp:
            continue
        name = f"{i:03d}.wav"
        wav = _synth_voicevox(jp, voice, speed) if use_vv else None
        if wav is None:
            dur = translator.estimate_duration_ms(jp, speed)
            wav = _silent_wav(dur)
        with open(os.path.join(audio_dir, name), "wb") as f:
            f.write(wav)
        dur = _wav_duration_ms(wav) or translator.estimate_duration_ms(jp, speed)

        start, end = cursor, cursor + dur
        srt_lines.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{jp}\n")
        cursor = end + pause_ms
        manifest_sentences.append({
            "id": i, "src": s.get("src", ""), "jp": jp,
            "audio": f"audio/{name}", "duration_ms": dur, "pause_after_ms": pause_ms,
            # 원본 장면 앵커(ms) — scriptwriter 가 붙임. 컷편집이 이 시간을 자름.
            "src_anchor_ms": s.get("src_anchor_ms"),
        })

    manifest = {
        "job_id": job_id,
        "voice": f"voicevox:{voice}",
        "engine": engine,
        "language": "ja",
        "source_script_lang": source_lang,
        "speed": speed,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_duration_ms": cursor,
        "sentence_count": len(manifest_sentences),
        "sentences": manifest_sentences,
    }
    with open(os.path.join(job_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(job_dir, "script_jp.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(s["jp"] for s in manifest_sentences))
    with open(os.path.join(job_dir, "subtitle.srt"), "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))

    # ZIP
    zip_path = os.path.join(job_dir, f"{job_id}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(job_dir):
            for fn in files:
                if fn.endswith(".zip"):
                    continue
                fp = os.path.join(root, fn)
                z.write(fp, os.path.relpath(fp, job_dir))

    manifest["zip_path"] = zip_path
    manifest["engine_note"] = (
        "VOICEVOX 로 실제 음성 합성" if use_vv
        else "VOICEVOX 미가동 → 무음(추정 길이) WAV. 자막·타임라인은 정상. "
             "VOICEVOX 실행 후 다시 만들면 실제 음성이 들어갑니다.")
    return manifest


def list_jobs() -> list[dict]:
    if not os.path.isdir(JOBS_DIR):
        return []
    out = []
    for jid in sorted(os.listdir(JOBS_DIR), reverse=True):
        mf = os.path.join(JOBS_DIR, jid, "manifest.json")
        if os.path.isfile(mf):
            try:
                with open(mf, encoding="utf-8") as f:
                    m = json.load(f)
                out.append({"job_id": m["job_id"], "sentence_count": m.get("sentence_count"),
                            "total_duration_ms": m.get("total_duration_ms"),
                            "created_at": m.get("created_at"), "engine": m.get("engine")})
            except Exception:
                pass
    return out


def job_zip_path(job_id: str) -> str | None:
    p = os.path.join(JOBS_DIR, job_id, f"{job_id}.zip")
    return p if os.path.isfile(p) else None
