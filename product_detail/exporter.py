"""HTML → PNG 변환 (Playwright 전체 페이지 스크린샷).

Playwright 가 없거나 Chromium 이 없으면 None 을 반환한다
(앱은 HTML 다운로드 / 미리보기로 graceful degrade).
"""
from __future__ import annotations

import glob
import os
import tempfile
from typing import Optional


def _autodetect_chromium() -> Optional[str]:
    """PLAYWRIGHT_BROWSERS_PATH 안에 실제로 존재하는 chrome 실행파일을 찾는다.
    playwright 가 기대하는 버전과 실제 다운로드된 버전이 어긋날 때 폴백용.
    """
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not base or not os.path.isdir(base):
        return None
    for pat in ("chromium-*/chrome-linux/chrome",
                "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"):
        hits = sorted(glob.glob(os.path.join(base, pat)), reverse=True)
        for h in hits:
            if os.access(h, os.X_OK):
                return h
    return None


def html_to_png(html: str, viewport_width: int = 720) -> Optional[bytes]:
    """주어진 HTML 문자열을 한 장 PNG(전체 페이지)로 캡처해 바이트 반환."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as f:
        f.write(html)
        path = f.name

    png_bytes: Optional[bytes] = None
    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
            if not exe:
                exe = _autodetect_chromium()
            if exe:
                launch_kwargs["executable_path"] = exe
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(
                    viewport={"width": viewport_width, "height": 1200},
                    device_scale_factor=2,
                )
                page.goto("file://" + path, wait_until="networkidle", timeout=20000)
                png_bytes = page.screenshot(full_page=True, type="png")
            finally:
                browser.close()
    except Exception:
        png_bytes = None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    return png_bytes
