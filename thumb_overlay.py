"""thumb_overlay.py — 생성된 씬 이미지 위에 한글 문구를 코드로 또렷이 얹기.

이미지 모델이 한/일 글자를 뭉개는 문제를 피하려고, 배경(씬)만 모델이 만들고
문구는 여기서 PIL 로 깨끗하게 렌더링한다. 폰트·위치를 고정하면 채널 정체성도 통일.
Streamlit 비의존.
"""
from __future__ import annotations

import base64
import io
import os
import re

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:                       # noqa: BLE001
    Image = None

# 한글 렌더 가능 폰트 후보 (플랫폼별)
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",     # Windows 맑은고딕
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",                        # macOS
]


def _find_font(size: int):
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:           # noqa: BLE001
                continue
    return ImageFont.load_default()


def has_korean_font() -> bool:
    return any(os.path.exists(p) for p in _FONT_CANDIDATES)


def _to_image(ref: str):
    """data:image URL 또는 파일경로 → PIL Image."""
    if ref.startswith("data:image"):
        b64 = ref.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    if os.path.exists(ref):
        return Image.open(ref).convert("RGB")
    raise ValueError("이미지 참조를 열 수 없음(http 는 미지원)")


def _wrap(text: str, max_chars: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    # 사용자가 준 줄바꿈 우선, 없으면 길이 기준 래핑
    if "\n" in text:
        return [ln.strip() for ln in text.split("\n") if ln.strip()][:3]
    words = re.split(r"\s+", text)
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]


def overlay_title(image_ref: str, text: str, position: str = "bottom"):
    """씬 이미지 위에 문구를 얹은 PIL Image 반환. 문구 없으면 원본 그대로.
    실패(폰트/PIL 없음)해도 원본을 돌려줘 흐름이 안 끊기게."""
    if Image is None:
        return image_ref
    try:
        img = _to_image(image_ref)
    except Exception:                   # noqa: BLE001
        return image_ref
    if not (text or "").strip():
        return img

    W, H = img.size
    lines = _wrap(text, max_chars=max(8, W // 90))
    if not lines:
        return img
    font = _find_font(int(H * 0.085))
    draw = ImageDraw.Draw(img, "RGBA")

    # 줄 높이 측정
    def _h(s):
        b = draw.textbbox((0, 0), s, font=font)
        return b[3] - b[1], b[2] - b[0]
    line_hs = [_h(s) for s in lines]
    total_h = sum(h for h, _ in line_hs) + int(H * 0.02) * (len(lines) - 1)
    pad = int(H * 0.04)
    y0 = (H - total_h - pad) if position == "bottom" else pad

    # 가독성용 반투명 그라디언트 밴드
    band = Image.new("RGBA", (W, total_h + pad * 2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rectangle([0, 0, W, total_h + pad * 2], fill=(0, 0, 0, 110))
    img.paste(Image.alpha_composite(img.crop((0, y0 - pad, W, y0 + total_h + pad)).convert("RGBA"), band),
              (0, y0 - pad))
    draw = ImageDraw.Draw(img, "RGBA")

    y = y0
    for (h, w), s in zip(line_hs, lines):
        x = (W - w) // 2
        # 외곽선(검정) + 본문(흰색) — 어떤 배경에서도 또렷
        for dx in (-3, 0, 3):
            for dy in (-3, 0, 3):
                draw.text((x + dx, y + dy), s, font=font, fill=(0, 0, 0, 235))
        draw.text((x, y), s, font=font, fill=(255, 255, 255, 255))
        y += h + int(H * 0.02)
    return img


def to_data_url(img) -> str:
    if isinstance(img, str):
        return img
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
