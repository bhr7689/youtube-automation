"""img_similar.py — 썸네일 이미지 유사도(perceptual hash) 묶기. 추가 의존성 없이 PIL 만.

'비슷하게 생긴 썸네일들'을 시각적으로 그룹핑해 한 결끼리 모은다.
average hash(aHash) — 8x8 흑백 평균 비교 64bit. Hamming 거리로 유사도.
Streamlit 비의존.
"""
from __future__ import annotations

import base64
import io

try:
    from PIL import Image
except Exception:                       # noqa: BLE001
    Image = None


def _to_img(ref: str):
    if ref.startswith("data:"):
        return Image.open(io.BytesIO(base64.b64decode(ref.split(",", 1)[1])))
    return Image.open(ref)


def ahash(ref: str, size: int = 8) -> int | None:
    if Image is None:
        return None
    try:
        img = _to_img(ref).convert("L").resize((size, size))
    except Exception:                   # noqa: BLE001
        return None
    px = list(img.getdata())
    avg = sum(px) / len(px)
    return sum(1 << i for i, p in enumerate(px) if p >= avg)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def group_similar(refs: list[str], threshold: int = 12) -> list[list[int]]:
    """이미지 참조 리스트 → 비슷한 것끼리 인덱스 그룹. threshold 작을수록 엄격."""
    hashes = [ahash(r) for r in refs]
    groups: list[list[int]] = []
    used: set[int] = set()
    for i in range(len(refs)):
        if i in used or hashes[i] is None:
            continue
        g = [i]
        used.add(i)
        for j in range(i + 1, len(refs)):
            if j in used or hashes[j] is None:
                continue
            if hamming(hashes[i], hashes[j]) <= threshold:
                g.append(j)
                used.add(j)
        groups.append(g)
    # 남은(해시 실패) 것도 개별 그룹
    for i in range(len(refs)):
        if i not in used:
            groups.append([i])
    return groups
