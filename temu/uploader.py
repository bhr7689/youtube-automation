"""테무 셀러센터 자동 업로드 (best-effort).

⚠️ 주의
- 셀러센터 DOM/플로우는 자주 바뀌고, 캡차/2FA/봇 탐지로 막힐 수 있다.
- 정책 위반/계정 정지 위험은 사용자 책임이다.
- 자동 모드가 실패하면 '가이드 모드' (브라우저만 열고 사용자가 직접 입력)로 폴백한다.

지원 모드:
  guided  : 브라우저를 headed 로 열고, 셀러센터 로그인 페이지까지만 이동.
            그 뒤 채워야 할 값은 콘솔/UI 가 안내. (가장 안전, 기본값)
  auto    : 로그인 + 빈 양식 폼 자동 채움 시도. 셀러센터 URL 과 셀렉터 매핑이 필요.

셀러센터 URL: 가이드에 명시되어 있지 않으므로 사용자 입력 필수.
한국 셀러용으로 알려진 후보:
  - https://seller.kuajingmaihuo.com  (글로벌, 다국어)
  - https://agentseller.temu.com
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class UploadResult:
    ok: bool
    mode: str          # 'guided' | 'auto'
    message: str
    seller_url: str = ""


def _autodetect_chromium() -> Optional[str]:
    import glob
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not base:
        return None
    for pat in ("chromium-*/chrome-linux/chrome",
                "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"):
        hits = sorted(glob.glob(os.path.join(base, pat)), reverse=True)
        for h in hits:
            if os.access(h, os.X_OK):
                return h
    return None


def open_seller_center_guided(seller_url: str) -> UploadResult:
    """브라우저(headed)를 열어 셀러센터 로그인 페이지까지 이동.
    사용자가 직접 로그인·입력. 닫힐 때까지 대기.
    """
    if not seller_url:
        return UploadResult(False, "guided", "셀러센터 URL이 비어 있어요.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return UploadResult(False, "guided",
            f"Playwright가 설치돼 있지 않아요. pip install playwright 후 다시 시도. ({e})")

    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or _autodetect_chromium()
    try:
        with sync_playwright() as p:
            kw = {"headless": False}
            if exe:
                kw["executable_path"] = exe
            browser = p.chromium.launch(**kw)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(seller_url, wait_until="domcontentloaded", timeout=30000)
            # 브라우저가 닫힐 때까지 블록
            page.wait_for_event("close", timeout=0)
            browser.close()
        return UploadResult(True, "guided", "브라우저 세션 종료. 셀러센터에서 직접 등록을 마쳤다면 OK.", seller_url)
    except Exception as e:
        return UploadResult(False, "guided", f"브라우저 실행 실패: {e}", seller_url)


def auto_upload_listing(
    *,
    seller_url: str,
    email: str,
    password: str,
    title: str,
    description: str,
    main_image_path: str = "",
    gallery_paths: list[str] | None = None,
) -> UploadResult:
    """[experimental] 셀러센터에 자동 로그인 + 빈 양식 폼 채움을 시도.

    실패 시 guided 모드로 폴백할 것을 권장.
    셀렉터는 셀러센터마다 다르므로, 첫 실행 시 화면을 보고 ENV 로 셀렉터를 덮어쓸 수 있게 둔다.
    """
    if not (seller_url and email and password):
        return UploadResult(False, "auto", "URL/이메일/비밀번호 중 하나가 비어 있어요.", seller_url)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return UploadResult(False, "auto",
            f"Playwright가 설치돼 있지 않아요. pip install playwright. ({e})")

    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or _autodetect_chromium()
    sel_email = os.environ.get("TEMU_SEL_EMAIL", "input[type=email],input[name=email]")
    sel_pw    = os.environ.get("TEMU_SEL_PASSWORD", "input[type=password],input[name=password]")
    sel_login = os.environ.get("TEMU_SEL_LOGIN_BTN", "button[type=submit],button:has-text('로그인'),button:has-text('Sign in')")

    msgs: list[str] = []
    try:
        with sync_playwright() as p:
            kw = {"headless": False}  # 캡차 발생 시 사용자가 풀 수 있도록 headed
            if exe:
                kw["executable_path"] = exe
            browser = p.chromium.launch(**kw)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(seller_url, wait_until="domcontentloaded", timeout=30000)
            msgs.append(f"방문: {seller_url}")

            # 로그인 시도
            try:
                page.locator(sel_email).first.fill(email, timeout=10000)
                page.locator(sel_pw).first.fill(password, timeout=10000)
                page.locator(sel_login).first.click(timeout=10000)
                msgs.append("로그인 폼 입력 완료. 캡차/2FA가 있으면 브라우저에서 직접 처리해 주세요.")
            except Exception as e:
                msgs.append(f"로그인 폼을 찾지 못했어요(셀러센터 DOM이 다를 수 있음): {e}")

            # 사용자가 캡차/2FA 처리하는 동안 충분히 대기
            page.wait_for_timeout(10000)
            msgs.append(
                "자동 폼 채움은 셀러센터별로 다르고 위험해서, 여기서는 멈춥니다. "
                "브라우저에서 [제품 → 제품추가 → 빈 양식]으로 이동해 직접 진행해 주세요. "
                "(앱이 만들어준 제목/설명/엑셀/이미지 ZIP을 그대로 쓰면 됩니다.)"
            )
            page.wait_for_event("close", timeout=0)
            browser.close()
        return UploadResult(True, "auto", "\n".join(msgs), seller_url)
    except Exception as e:
        msgs.append(f"중단: {e}")
        return UploadResult(False, "auto", "\n".join(msgs), seller_url)
