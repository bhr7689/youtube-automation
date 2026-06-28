"""테무 이미지 패키징.

테무 권장 규격(공개 정보 기준):
- 정사각형 1340x1340 px (최소 800), 흰 배경
- JPG (또는 PNG), 5MB 이하 권장
- 첫 이미지가 메인. 나머지가 갤러리.

업로드한 사진을 자동으로:
  ① 정사각형 흰 배경 패딩
  ② 1340 리사이즈
  ③ JPG 압축
  ④ ZIP 패키지 (main.jpg, gallery_01.jpg ... + SKU_색상_사이즈.jpg)
사용자는 ZIP 만 다운로드 → 셀러센터에 일괄 업로드.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Iterable

from PIL import Image, ImageOps


TARGET_SIZE = 1340
BG_COLOR = (255, 255, 255)
JPG_QUALITY = 88


def _slug(text: str) -> str:
    text = (text or "").strip()
    # 한글·영문·숫자 외 제거, 공백→_
    text = re.sub(r"[^\w가-힣]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "x"


def to_temu_square(img: Image.Image, size: int = TARGET_SIZE) -> Image.Image:
    """긴 변을 size 에 맞춰 축소 → 정사각형 흰 배경 위에 중앙 배치."""
    img = img.convert("RGB")
    img = ImageOps.exif_transpose(img)
    w, h = img.size
    scale = size / max(w, h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), BG_COLOR)
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _save_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPG_QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


def build_image_pack(
    *,
    main_image: Image.Image | None,
    gallery: Iterable[Image.Image] = (),
    sku_images: dict[str, Image.Image] | None = None,
) -> tuple[bytes, dict]:
    """ZIP 바이트 + 매니페스트 dict 반환.

    매니페스트: {"main": "main.jpg", "gallery": [...], "sku": {sku_key: filename}}
    """
    manifest = {"main": "", "gallery": [], "sku": {}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if main_image is not None:
            name = "main.jpg"
            zf.writestr(name, _save_jpeg(to_temu_square(main_image)))
            manifest["main"] = name
        for i, g in enumerate(gallery, start=1):
            name = f"gallery_{i:02d}.jpg"
            zf.writestr(name, _save_jpeg(to_temu_square(g)))
            manifest["gallery"].append(name)
        if sku_images:
            for key, img in sku_images.items():
                name = f"sku_{_slug(key)}.jpg"
                zf.writestr(name, _save_jpeg(to_temu_square(img)))
                manifest["sku"][key] = name

        # 참고용 README
        readme = (
            "테무 이미지 패키지\n"
            "- 모든 이미지는 1340x1340 흰 배경 정사각형으로 정렬되어 있습니다.\n"
            "- 셀러센터 업로드:\n"
            "  1) 메인 이미지: main.jpg\n"
            "  2) 갤러리: gallery_*.jpg (순서대로)\n"
            "  3) SKU 이미지: sku_*.jpg (옵션 변형용)\n"
        )
        zf.writestr("README.txt", readme.encode("utf-8"))

    return buf.getvalue(), manifest
