"""자동 컷편집 — 컷 플래너 (도구③ v1).

설계(ideas): 원본 롱폼 → 쇼츠(세로). narration job(manifest.json)의 문장별 duration 에
맞춰 원본에서 3~5초 서브클립을 배분하고, 세그먼트마다 변형(줌·미러·속도)을 다양화한다.
변형 규칙(끄기 불가 원칙):
  1) 확대(줌 1.1~1.3)  2) 좌우 반전(일부)  3) 동일 원본 구간 5초+ 연속 금지
  4) 원본 오디오 최소화 + TTS 내레이션 + BGM + 일본어 자막 burn-in

산출: ① 컷 플랜 JSON(자체 스키마=진실원본) ② CapCut draft 스켈레톤(A안) ③ ffmpeg 스크립트(B안 백업).
실제 영상 렌더는 사용자 PC(CapCut 또는 ffmpeg)에서. 여기선 '무엇을 어떻게 자를지' 계획을 만든다.
"""
from __future__ import annotations

import json
import os
import random
import time

CUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cut_plans")
CANVAS = {"w": 1080, "h": 1920, "fps": 30}   # 쇼츠 세로


def _split_duration(total_ms: int, mn: int, mx: int, rnd: random.Random) -> list[int]:
    """한 문장 길이를 3~5초 세그먼트로 분할(마지막은 짧을 수 있음, 최소 0.8초)."""
    segs, rem = [], total_ms
    while rem > mx:
        L = int(rnd.uniform(mn, mx))
        segs.append(L)
        rem -= L
    if rem > 0:
        segs.append(max(rem, 800))
    return segs


def plan_cuts(manifest: dict, source_duration_sec: float = 600.0,
              seg_min_s: float = 3.0, seg_max_s: float = 5.0,
              seed: str | None = None, loop: bool = True,
              sfx: bool = True) -> dict:
    rnd = random.Random(seed or manifest.get("job_id", "seed"))
    src_ms = max(int(source_duration_sec * 1000), 6000)
    mn, mx = int(seg_min_s * 1000), int(seg_max_s * 1000)

    segments = []
    out_cursor = 0
    seg_id = 0
    last_src_start = -10 ** 9
    for s in manifest.get("sentences", []):
        need = int(s.get("duration_ms", 0)) + int(s.get("pause_after_ms", 0))
        if need <= 0:
            continue
        anchor = s.get("src_anchor_ms")
        anchor_cursor = anchor if anchor is not None else None
        for seg_len in _split_duration(need, mn, mx, rnd):
            seg_id += 1
            speed = round(rnd.uniform(0.95, 1.05), 2)
            # 원본에서 이 세그먼트가 쓸 실제 길이(속도 반영)
            src_span = min(int(seg_len * speed), src_ms)
            if anchor_cursor is not None:
                # ⚓ 앵커 모드: 대본 문장이 가리키는 원본 장면부터 순차 진행
                #   (같은 문장의 후속 세그먼트는 이어지는 구간 → 문장-장면 정확 매칭)
                src_start = min(max(anchor_cursor, 0), max(0, src_ms - src_span))
                anchor_cursor = src_start + src_span
            else:
                # 앵커 없음(레거시): 직전과 5초+ 이격 랜덤 → 동일 구간 연속 재사용 금지
                src_start = 0
                for _ in range(10):
                    cand = rnd.randint(0, max(0, src_ms - src_span))
                    if abs(cand - last_src_start) > 5000:
                        src_start = cand
                        break
                    src_start = cand
            last_src_start = src_start
            segments.append({
                "seg_id": seg_id,
                "sentence_id": s["id"],
                "subtitle": s.get("jp", ""),
                "out_start_ms": out_cursor,
                "out_end_ms": out_cursor + seg_len,
                "dur_ms": seg_len,
                "src_start_ms": src_start,
                "src_end_ms": src_start + src_span,
                "zoom": round(rnd.uniform(1.1, 1.3), 2),
                "mirror": rnd.random() < 0.5,
                "speed": speed,
            })
            out_cursor += seg_len

    # 🔁 루프 컷: 마지막 세그먼트를 첫 세그먼트와 같은 원본 구간(다른 변형)으로
    #   → 영상 끝이 처음 장면으로 돌아가 재시청(루프율)을 만든다.
    if loop and len(segments) >= 3:
        first, last = segments[0], segments[-1]
        last["src_start_ms"] = first["src_start_ms"]
        last["src_end_ms"] = first["src_start_ms"] + (last["src_end_ms"] - last["src_start_ms"])
        last["zoom"] = round(min(first["zoom"] + 0.1, 1.3), 2)   # 같은 장면·다른 변형
        last["mirror"] = not first["mirror"]
        last["loop_back"] = True

    # 🔊 SFX 플랜: 문장 경계 whoosh + 클라이맥스(60% 지점) sting + 끝 직전 riser.
    #   실제 효과음 파일은 로열티프리로 사용자 준비 — 여기선 위치·종류만 지정.
    sfx_events = []
    if sfx and segments:
        prev_sentence = None
        for seg in segments:
            if prev_sentence is not None and seg["sentence_id"] != prev_sentence:
                sfx_events.append({"at_ms": seg["out_start_ms"], "type": "whoosh",
                                   "note": "문장 전환 — 컷 체감·패턴 인터럽트"})
            prev_sentence = seg["sentence_id"]
        climax = int(out_cursor * 0.6)
        sfx_events.append({"at_ms": climax, "type": "sting",
                           "note": "클라이맥스 — 감정 강조"})
        sfx_events.append({"at_ms": max(out_cursor - 2500, 0), "type": "riser",
                           "note": "마무리 직전 고조(루프 진입 준비)"})
        sfx_events.sort(key=lambda e: e["at_ms"])

    plan = {
        "plan_id": "cp_" + time.strftime("%Y%m%d_%H%M%S"),
        "job_id": manifest.get("job_id"),
        "canvas": CANVAS,
        "source_duration_sec": source_duration_sec,
        "total_ms": out_cursor,
        "segment_count": seg_id,
        "sentence_count": manifest.get("sentence_count"),
        "rules": {
            "zoom": "1.1~1.3", "mirror": "일부", "seg_len": f"{seg_min_s}~{seg_max_s}s",
            "no_continuous_5s": True,
            "audio": "원본 최소화 + TTS 내레이션 + BGM + 일본어 자막 burn-in",
        },
        "loop": loop,
        "sfx": sfx_events,
        "segments": segments,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save(plan)
    return plan


def _save(plan: dict) -> None:
    os.makedirs(CUT_DIR, exist_ok=True)
    with open(os.path.join(CUT_DIR, plan["plan_id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)


def list_plans(limit: int = 30) -> list[dict]:
    """저장된 컷 플랜 목록(최신순) — 작업 기록 화면용."""
    if not os.path.isdir(CUT_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(CUT_DIR), reverse=True):
        if fn.startswith("cp_") and fn.endswith(".json") and "_capcut" not in fn:
            try:
                with open(os.path.join(CUT_DIR, fn), encoding="utf-8") as f:
                    pl = json.load(f)
                out.append({"plan_id": pl["plan_id"], "job_id": pl.get("job_id"),
                            "segment_count": pl.get("segment_count"),
                            "total_ms": pl.get("total_ms"),
                            "created_at": pl.get("created_at"),
                            "loop": pl.get("loop", False)})
            except Exception:
                pass
            if len(out) >= limit:
                break
    return out


def load_plan(plan_id: str) -> dict | None:
    p = os.path.join(CUT_DIR, plan_id + ".json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── A안: CapCut draft 스켈레톤 ──────────────────────────
def to_capcut_draft(plan: dict, source_name: str = "source.mp4") -> dict:
    """CapCut(젠잉) draft_content 계열 스켈레톤. 변형을 굽지 않고 트랙/클립 속성으로 표현.

    주의: 실제 import 는 사용자 PC 의 CapCut 버전에 맞춰 pyJianYingDraft 로 변환 권장.
    여기선 컷·변형·자막·오디오를 구조화한 이식 가능한 형태로 내보낸다.
    """
    us = 1000  # ms→us 근사 배수(젠잉은 us 단위) — 스켈레톤이므로 단순화
    video_clips, text_clips = [], []
    for seg in plan["segments"]:
        video_clips.append({
            "type": "video", "source": source_name,
            "target_timerange": {"start": seg["out_start_ms"] * us, "duration": seg["dur_ms"] * us},
            "source_timerange": {"start": seg["src_start_ms"] * us,
                                  "duration": (seg["src_end_ms"] - seg["src_start_ms"]) * us},
            "scale": {"x": seg["zoom"], "y": seg["zoom"]},
            "flip": {"horizontal": seg["mirror"], "vertical": False},
            "speed": seg["speed"],
        })
        text_clips.append({
            "type": "text", "content": seg["subtitle"],
            "target_timerange": {"start": seg["out_start_ms"] * us, "duration": seg["dur_ms"] * us},
            "style": {"size": 12, "align": "center", "y": 0.82, "stroke": True},
        })
    return {
        "draft_type": "capcut_skeleton",
        "note": "CapCut 버전별 호환을 위해 사용자 PC 에서 pyJianYingDraft 로 변환 권장. "
                "변형은 클립 속성(scale/flip/speed)으로만 표현 — 영상에 굽지 않음.",
        "canvas_config": {"width": plan["canvas"]["w"], "height": plan["canvas"]["h"],
                          "fps": plan["canvas"]["fps"]},
        "duration": plan["total_ms"] * us,
        "tracks": [
            {"type": "video", "segments": video_clips},
            {"type": "audio", "segments": [
                {"type": "audio", "source": f"narration/{plan['job_id']}.wav",
                 "note": "번역봇 narration job 의 문장별 wav(또는 full.wav)", "volume": 1.0},
                {"type": "audio", "source": "bgm.mp3", "volume": 0.18,
                 "note": "잔잔한 피아노 BGM (선택)"},
            ] + [
                {"type": "audio", "source": f"sfx/{e['type']}.wav", "volume": 0.5,
                 "target_timerange": {"start": e["at_ms"] * us, "duration": 800 * us},
                 "note": e["note"]}
                for e in plan.get("sfx", [])
            ]},
            {"type": "text", "segments": text_clips},
        ],
    }


# ── B안: ffmpeg 백업 스크립트 ───────────────────────────
def to_ffmpeg_script(plan: dict, source_name: str = "source.mp4",
                     narration_name: str = "narration.wav") -> str:
    """원본이 있으면 바로 렌더 가능한 ffmpeg 계획(개념 스크립트).

    각 세그먼트를 잘라 세로 1080x1920 로 zoom/crop + (필요시)미러 + 속도, concat 후
    내레이션 오디오 + 자막(별도 SRT burn) 을 얹는다. (실제 실행은 사용자 PC)
    """
    W, H = plan["canvas"]["w"], plan["canvas"]["h"]
    lines = [
        "#!/bin/sh",
        "# 🎬 자동 컷편집 백업 렌더(ffmpeg) — 원본(source.mp4) + narration.wav 필요",
        f"# 캔버스 {W}x{H} 세로 쇼츠 · 세그먼트 {plan['segment_count']}개 · "
        f"총 {plan['total_ms']/1000:.1f}초",
        "set -e", "mkdir -p _seg",
    ]
    for seg in plan["segments"]:
        i = seg["seg_id"]
        ss = seg["src_start_ms"] / 1000
        du = (seg["src_end_ms"] - seg["src_start_ms"]) / 1000
        vf = [f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}",
              f"scale=iw*{seg['zoom']}:ih*{seg['zoom']}", f"crop={W}:{H}"]
        if seg["mirror"]:
            vf.append("hflip")
        if abs(seg["speed"] - 1.0) > 0.001:
            vf.append(f"setpts=PTS/{seg['speed']}")
        lines.append(
            f"ffmpeg -y -ss {ss:.2f} -t {du:.2f} -i {source_name} "
            f"-vf \"{','.join(vf)}\" -an _seg/seg{i:03d}.mp4")
    lines.append("# concat")
    lines.append("printf \"file '%s'\\n\" _seg/seg*.mp4 > _list.txt")
    lines.append("ffmpeg -y -f concat -safe 0 -i _list.txt -c copy _video.mp4")
    lines.append("# 내레이션 + (자막 SRT burn-in 은 subtitle.srt 사용)")
    lines.append(
        f"ffmpeg -y -i _video.mp4 -i {narration_name} "
        f"-vf \"subtitles=subtitle.srt:force_style='Alignment=2,FontSize=16'\" "
        f"-map 0:v -map 1:a -shortest -c:v libx264 -pix_fmt yuv420p output_shorts.mp4")
    lines.append("echo '✅ output_shorts.mp4 생성 완료'")
    return "\n".join(lines)


def save_capcut(plan_id: str, source_name: str = "source.mp4") -> str | None:
    plan = load_plan(plan_id)
    if not plan:
        return None
    draft = to_capcut_draft(plan, source_name)
    p = os.path.join(CUT_DIR, plan_id + "_capcut.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    return p


def save_ffmpeg(plan_id: str, source_name: str = "source.mp4") -> str | None:
    plan = load_plan(plan_id)
    if not plan:
        return None
    script = to_ffmpeg_script(plan, source_name)
    p = os.path.join(CUT_DIR, plan_id + "_render.sh")
    with open(p, "w", encoding="utf-8") as f:
        f.write(script)
    return p
