"""🖐️ 화면 지문 매칭 — 프레임 dHash(차이 해시)로 "같은 영상인지" 대조.

'누가 먼저 숏폼화했나'의 심장. 사장님이 발견한 쇼츠의 프레임 지문을, 후보 영상들의
프레임 지문과 대조해 **진짜 같은 콘텐츠**만 남긴다(제목·우연 일치 배제 → 신뢰도 HIGH).

원리(dHash, difference hash):
- 프레임을 9x8 흑백으로 줄여 좌우 인접 픽셀 밝기 대소만 비교 → 64비트 지문.
- 밝기·대비·약간의 크롭/리사이즈/재인코딩에 강함(쇼츠 재업의 흔한 변형에 강함).
- 두 지문의 다른 비트 수(Hamming) 적을수록 같은 장면.

의존성: PIL(Pillow)만. 프레임 추출은 ffmpeg(사장님 PC) — 이 모듈은 '이미지 → 지문 → 대조'
순수 로직이라 키/네트워크 없이 self-test 가능.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from PIL import Image

HASH_SIZE = 8          # 8x8 → 64비트
_BITS = HASH_SIZE * HASH_SIZE


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def extract_frames(video_path: str, n: int = 12) -> list["Image.Image"]:
    """영상에서 균등 간격 n개 프레임 추출(ffmpeg) → PIL 이미지 리스트.

    ffmpeg 없거나 실패하면 []. 실제 다운로드·추출은 사장님 PC(ffmpeg 로컬).
    """
    ff = _ffmpeg()
    if not ff or not os.path.isfile(video_path):
        return []
    tmp = tempfile.mkdtemp(prefix="ffp_")
    try:
        # 영상 길이로 균등 간격 fps 계산(n장 골고루) — 길이 모르면 초당 1장
        dur = 0.0
        probe = shutil.which("ffprobe")
        if probe:
            r = subprocess.run(
                [probe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path], capture_output=True, text=True, timeout=30)
            try:
                dur = float((r.stdout or "0").strip())
            except Exception:
                dur = 0.0
        fps = max(0.2, round(n / dur, 3)) if dur > 0 else 1.0
        subprocess.run(
            [ff, "-y", "-i", video_path, "-vf",
             f"fps={fps},scale=160:-1", "-frames:v", str(n),
             os.path.join(tmp, "f_%03d.png")],
            capture_output=True, timeout=120)
        imgs = []
        for fn in sorted(os.listdir(tmp)):
            if fn.endswith(".png"):
                with Image.open(os.path.join(tmp, fn)) as im:
                    imgs.append(im.copy())
        return imgs
    except Exception:
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def signature_of_video(video_path: str, n: int = 12) -> list[int]:
    """영상 파일 → 프레임 지문 리스트(다운로드된 후보 대조용)."""
    return frame_hashes(extract_frames(video_path, n))


def dhash(img: "Image.Image", size: int = HASH_SIZE) -> int:
    """이미지 → 64비트 dHash(정수)."""
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = g.load()
    bits = 0
    idx = 0
    for y in range(size):
        for x in range(size):
            bits |= (1 << idx) if px[x, y] < px[x + 1, y] else 0
            idx += 1
    return bits


def dhash_file(path: str, size: int = HASH_SIZE) -> int:
    with Image.open(path) as im:
        return dhash(im, size)


def hamming(a: int, b: int) -> int:
    """두 지문의 다른 비트 수."""
    return bin(a ^ b).count("1")


def similarity(a: int, b: int) -> float:
    """0.0~1.0 (1=동일 장면)."""
    return round(1.0 - hamming(a, b) / _BITS, 3)


def frame_hashes(images) -> list[int]:
    """PIL 이미지 리스트(또는 파일경로 리스트) → 지문 리스트."""
    out = []
    for im in images:
        if isinstance(im, str):
            out.append(dhash_file(im))
        else:
            out.append(dhash(im))
    return out


def contains(query_sig: list[int], cand_sig: list[int], *,
             per_frame_thresh: float = 0.82) -> dict:
    """query(발견한 쇼츠) 프레임들이 candidate(후보 영상) 안에 들어있는가.

    각 query 프레임이 candidate 프레임 중 하나와 충분히 닮으면(≥thresh) '있음'.
    반환: {coverage(0~1), matched, total, isMatch, bestPerFrame}
    """
    if not query_sig or not cand_sig:
        return {"coverage": 0.0, "matched": 0, "total": len(query_sig),
                "isMatch": False, "bestPerFrame": []}
    matched = 0
    best_list = []
    for qh in query_sig:
        best = max(similarity(qh, ch) for ch in cand_sig)
        best_list.append(best)
        if best >= per_frame_thresh:
            matched += 1
    coverage = round(matched / len(query_sig), 3)
    # 콘텐츠 일치 판정: query 프레임의 과반 이상이 후보에서 발견
    return {"coverage": coverage, "matched": matched, "total": len(query_sig),
            "isMatch": coverage >= 0.5, "bestPerFrame": best_list}


def rank_candidates(query_sig: list[int], candidates: list[dict], *,
                    per_frame_thresh: float = 0.82) -> list[dict]:
    """후보들[{id, sig, ...}] 을 query 와의 콘텐츠 일치도(coverage) 순으로 정렬.

    각 후보에 match(coverage/isMatch) 를 붙여 반환. isMatch=True 만 진짜 파생/원본 후보.
    """
    out = []
    for c in candidates:
        m = contains(query_sig, c.get("sig", []), per_frame_thresh=per_frame_thresh)
        out.append({**{k: v for k, v in c.items() if k != "sig"}, "match": m})
    out.sort(key=lambda c: c["match"]["coverage"], reverse=True)
    return out


# ── 자기검증(합성 이미지) ─────────────────────────────────────
if __name__ == "__main__":
    def _hgrad(w=64, h=64, invert=False, bright=0):
        """가로 그라데이션 이미지."""
        im = Image.new("L", (w, h))
        px = im.load()
        for y in range(h):
            for x in range(w):
                v = int(255 * x / (w - 1))
                if invert:
                    v = 255 - v
                px[x, y] = max(0, min(255, v + bright))
        return im

    def _vgrad(w=64, h=64):
        im = Image.new("L", (w, h)); px = im.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = int(255 * y / (h - 1))
        return im

    a = dhash(_hgrad())
    a_bright = dhash(_hgrad(bright=40))     # 밝기만 다름 → 같은 지문이어야
    a_resized = dhash(_hgrad(w=200, h=120)) # 크기만 다름 → 거의 같아야
    v = dhash(_vgrad())                     # 세로 그라데이션 → 완전 다름
    a_inv = dhash(_hgrad(invert=True))      # 좌우 반전 밝기 → 많이 달라야

    assert similarity(a, a) == 1.0
    assert similarity(a, a_bright) == 1.0, f"밝기 불변이어야: {similarity(a,a_bright)}"
    assert similarity(a, a_resized) >= 0.95, f"리사이즈 강건: {similarity(a,a_resized)}"
    assert similarity(a, v) < 0.6, f"세로/가로는 달라야: {similarity(a,v)}"
    assert similarity(a, a_inv) < 0.3, f"반전은 많이 달라야: {similarity(a,a_inv)}"
    print(f"동일 {similarity(a,a)} · 밝기 {similarity(a,a_bright)} · "
          f"리사이즈 {similarity(a,a_resized)} · 세로 {similarity(a,v)} · 반전 {similarity(a,a_inv)}")

    # contains: 쇼츠(3프레임)가 후보(그 3프레임 + 무관 2개)에 포함
    frames = [_hgrad(bright=b) for b in (0, 30, 60)]
    short_sig = frame_hashes(frames)
    cand_same = frame_hashes([_vgrad()] + frames + [_vgrad()])   # 같은 콘텐츠 포함
    cand_diff = frame_hashes([_vgrad(), _hgrad(invert=True)])    # 무관
    m1 = contains(short_sig, cand_same)
    m2 = contains(short_sig, cand_diff)
    assert m1["isMatch"] and m1["coverage"] == 1.0, m1
    assert not m2["isMatch"], m2
    print(f"포함 판정 — 같은 콘텐츠 coverage {m1['coverage']} (match) · 무관 {m2['coverage']} (no)")

    # rank: 여러 후보 중 콘텐츠 일치가 위로
    ranked = rank_candidates(short_sig, [
        {"id": "무관", "sig": cand_diff},
        {"id": "원본롱폼", "sig": cand_same},
    ])
    assert ranked[0]["id"] == "원본롱폼" and ranked[0]["match"]["isMatch"]
    print(f"랭킹 1위: {ranked[0]['id']} (coverage {ranked[0]['match']['coverage']})")

    # 영상 → 프레임 → 지문 (ffmpeg 있으면 실제 영상으로 end-to-end)
    if _ffmpeg():
        import tempfile as _tf
        d = _tf.mkdtemp()
        vid = os.path.join(d, "t.mp4")
        subprocess.run([_ffmpeg(), "-y", "-f", "lavfi", "-i",
                        "testsrc=duration=2:size=320x240:rate=10",
                        "-pix_fmt", "yuv420p", vid], capture_output=True, timeout=60)
        sig1 = signature_of_video(vid, n=8)
        sig2 = signature_of_video(vid, n=8)   # 같은 영상 재추출
        assert len(sig1) >= 3, f"프레임 추출 실패: {len(sig1)}"
        m = contains(sig1, sig2)
        assert m["isMatch"] and m["coverage"] >= 0.8, m
        print(f"영상→지문 end-to-end: {len(sig1)}프레임 · 자기대조 coverage {m['coverage']}")
        shutil.rmtree(d, ignore_errors=True)
    else:
        print("(ffmpeg 없음 — 영상 추출 테스트 건너뜀. 사장님 PC 에선 동작)")

    print("\n✅ frame_fingerprint self-test 통과 — dHash·강건성·포함판정·랭킹·영상추출")
