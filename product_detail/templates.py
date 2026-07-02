"""상세페이지 HTML 템플릿.

모바일 세로(720px) · 따뜻한 톤 · 큰 글씨 · 5070 친화.
섹션 순서는 4단 깔때기를 따른다:
  Hero[맛있겠다] → Hook[맛있겠다 폭격] → 소구점 → Taste[먹고 싶다]
  → Size → Fresh[사고 싶다] → Farm → Cook[먹고 싶다 재점화]
  → Spec → Package → Reviews[사야겠다] → Trust[사야겠다] → CTA → (광고) → 푸터

동영상(움짤)은 taste·cook 섹션에 자동 부착되어 식욕 자극을 강화한다.
"""
from __future__ import annotations

import base64
import io
import html as html_lib
import mimetypes
from typing import Optional

from PIL import Image


PAGE_WIDTH = 720

# ── 식욕 색감 테마 (색채 심리학) ──────────────────────────────────────────
# 빨강·주황·노랑 = 식욕 자극 / 파랑 = 식욕 억제(수산물도 CTA는 따뜻한 색 유지)
THEMES = {
    "fresh_orange": {   # 🍊 범용 — 따뜻한 오렌지 (달콤·구움·기본)
        "bg": "#faf6f0",
        "primary": "#ea580c", "primary_deep": "#c2410c",
        "chip_bg": "#fff7ed", "chip_border": "#fdba74", "chip_text": "#9a3412",
        "tag_bg": "#ffedd5", "tag_text": "#c2410c",
        "hook_from": "#4b2e0f", "hook_to": "#2a1607",
        "hook_kicker": "#ffd28a", "hook_body": "#f5e7d2",
        "cta_shadow": "rgba(234,88,12,0.35)",
    },
    "appetite_red": {   # 🔥 식욕 레드 — 고기·매운맛·구이 (도파민 최강)
        "bg": "#fbf5f0",
        "primary": "#d62300", "primary_deep": "#a81b00",
        "chip_bg": "#fef2f2", "chip_border": "#fca5a5", "chip_text": "#991b1b",
        "tag_bg": "#fee2e2", "tag_text": "#b91c1c",
        "hook_from": "#450a0a", "hook_to": "#1c0505",
        "hook_kicker": "#fecaca", "hook_body": "#fee2e2",
        "cta_shadow": "rgba(214,35,0,0.35)",
    },
    "juicy_berry": {    # 🍉 과즙 베리 — 수박·딸기·과일 (빨강 과육 + 초록 신선 대비)
        "bg": "#fdf7f7",
        "primary": "#e63946", "primary_deep": "#c1121f",
        "chip_bg": "#f0fdf4", "chip_border": "#86efac", "chip_text": "#166534",
        "tag_bg": "#ffe4e6", "tag_text": "#be123c",
        "hook_from": "#7f1d1d", "hook_to": "#3f0d12",
        "hook_kicker": "#bbf7d0", "hook_body": "#ffe4e6",
        "cta_shadow": "rgba(230,57,70,0.35)",
    },
    "ocean_fresh": {    # 🌊 바다 신선 — 수산물 (신뢰 청록 + CTA는 식욕 주황 유지)
        "bg": "#f4f9f9",
        "primary": "#ea580c", "primary_deep": "#0e7490",
        "chip_bg": "#ecfeff", "chip_border": "#67e8f9", "chip_text": "#155e75",
        "tag_bg": "#cffafe", "tag_text": "#0e7490",
        "hook_from": "#164e63", "hook_to": "#082f38",
        "hook_kicker": "#a5f3fc", "hook_body": "#e0f7fa",
        "cta_shadow": "rgba(234,88,12,0.35)",
    },
    "golden_honey": {   # 🍯 골든 허니 — 치킨·빵·꿀·튀김·고구마 (노릇노릇 황금)
        "bg": "#fdfaf2",
        "primary": "#d97706", "primary_deep": "#b45309",
        "chip_bg": "#fffbeb", "chip_border": "#fcd34d", "chip_text": "#92400e",
        "tag_bg": "#fef3c7", "tag_text": "#b45309",
        "hook_from": "#451a03", "hook_to": "#1f0d02",
        "hook_kicker": "#fde68a", "hook_body": "#fef3c7",
        "cta_shadow": "rgba(217,119,6,0.35)",
    },
}
DEFAULT_THEME = "fresh_orange"


def auto_theme(category: str = "", hint: str = "") -> str:
    """카테고리·제품명·메모로 식욕 색감 테마 자동 선택."""
    t = f"{category} {hint}"

    def has(*words):
        return any(w in t for w in words)

    if has("수산", "해산", "생선", "갈치", "고등어", "새우", "오징어", "전복",
           "조개", "굴", "문어", "회", "멸치"):
        return "ocean_fresh"
    if has("정육", "고기", "한우", "삼겹", "불고기", "갈비", "매운", "떡볶이",
           "닭갈비", "육포", "곱창", "제육"):
        return "appetite_red"
    if has("과일", "수박", "딸기", "포도", "복숭아", "한라봉", "귤", "사과",
           "멜론", "참외", "자두", "베리", "망고"):
        return "juicy_berry"
    if has("치킨", "튀김", "빵", "베이커리", "꿀", "도넛", "고구마", "감자",
           "황금", "버터", "치즈"):
        return "golden_honey"
    return DEFAULT_THEME


def _img_to_data_uri(img: Optional[Image.Image]) -> str:
    if img is None:
        return ""
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _video_to_data_uri(data: bytes, filename: str = "") -> str:
    """업로드된 영상 바이트 → data URI. (mp4/webm/gif 자동 매핑)"""
    if not data:
        return ""
    mime, _ = mimetypes.guess_type(filename or "x.mp4")
    if not mime or not mime.startswith(("video/", "image/gif")):
        mime = "video/mp4"
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _esc(text) -> str:
    return html_lib.escape(str(text or ""))


def _video_block(uri: str, mime_hint: str = "") -> str:
    """GIF는 <img>, mp4/webm은 <video autoplay muted loop playsinline>."""
    if not uri:
        return ""
    is_gif = "image/gif" in uri or mime_hint == "image/gif"
    if is_gif:
        return f'<div class="full-img"><img src="{uri}" alt="motion" /></div>'
    return (
        '<div class="full-img">'
        f'<video src="{uri}" autoplay muted loop playsinline preload="auto" '
        'style="width:100%;height:auto;border-radius:18px;display:block;"></video>'
        "</div>"
    )


CSS = """
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
      'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    color: #1f2933;
    background: __BG__;
    -webkit-text-size-adjust: 100%;
    word-break: keep-all;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }
  .page {
    width: __PAGE_WIDTH__px;
    max-width: 100%;
    margin: 0 auto;
    background: #ffffff;
    overflow: hidden;
  }
  /* HERO */
  .hero { position: relative; }
  .hero img { display: block; width: 100%; height: auto; }
  .hero-overlay {
    position: absolute; left: 0; right: 0; bottom: 0;
    padding: 48px 36px 36px;
    background: linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.55) 60%, rgba(0,0,0,0.78) 100%);
    color: #fff;
  }
  .hero-headline {
    font-size: 52px; font-weight: 900; letter-spacing: -1.2px; margin: 0 0 10px;
    text-shadow: 0 2px 12px rgba(0,0,0,0.45);
  }
  .hero-sub { font-size: 24px; font-weight: 500; opacity: 0.92; margin: 0; letter-spacing: -0.3px; }
  /* 이름 블록 */
  .name-block { padding: 40px 40px 10px; }
  .product-name {
    font-size: 38px; font-weight: 800; color: __PRIMARY_DEEP__; letter-spacing: -1px; margin: 0 0 8px;
  }
  .subtitle { font-size: 23px; font-weight: 400; color: #6b7280; margin: 0; letter-spacing: -0.3px; }
  /* HOOK (큰 후크 배너) */
  .hook {
    margin: 28px 0 0; padding: 68px 40px;
    background: linear-gradient(180deg, __HOOK_FROM__ 0%, __HOOK_TO__ 100%);
    color: #fffaf2; text-align: center;
  }
  .hook .kicker {
    display: inline-block; font-size: 17px; font-weight: 700; letter-spacing: 3px;
    color: __HOOK_KICKER__; margin-bottom: 20px; text-transform: none;
  }
  .hook h2 {
    font-size: 44px; font-weight: 900; letter-spacing: -1px; margin: 0 0 18px;
    color: #fff; line-height: 1.3;
  }
  .hook p {
    font-size: 22px; line-height: 1.75; margin: 0 auto; color: __HOOK_BODY__;
    max-width: 560px; font-weight: 400;
  }
  /* 소구점 */
  .appeals {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 10px; padding: 30px 40px;
  }
  .appeal {
    background: #ffffff; border: 1.5px solid __CHIP_BORDER__; border-radius: 14px;
    padding: 18px 8px; text-align: center;
    font-size: 21px; font-weight: 700; color: __CHIP_TEXT__;
    letter-spacing: -0.3px;
  }
  /* 일반 섹션 */
  .section { padding: 52px 40px; border-top: 1px solid #f2ede4; }
  .section h2 {
    font-size: 33px; font-weight: 800; letter-spacing: -0.8px; margin: 0 0 20px;
    color: #191f28; line-height: 1.35;
  }
  .section h2 .tag {
    display: inline-block; vertical-align: 4px;
    font-size: 15px; font-weight: 700; color: __TAG_TEXT__;
    background: __TAG_BG__; border-radius: 999px; padding: 4px 12px; margin-right: 10px;
    letter-spacing: 0;
  }
  .section p { font-size: 24px; line-height: 1.75; color: #3d4753; margin: 0; }
  .section .full-img { margin-top: 22px; }
  .section .full-img img,
  .section .full-img video { display: block; width: 100%; height: auto; border-radius: 18px; }

  /* SPEC 표 / SIZE 카드 */
  .spec-table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  .spec-table th, .spec-table td {
    padding: 19px 4px; font-size: 22px; border-bottom: 1px solid #f2ede4; text-align: left;
  }
  .spec-table th { width: 34%; color: #8b95a1; font-weight: 500; }
  .spec-table td { color: #191f28; font-weight: 600; }
  .spec-table tr:last-child th, .spec-table tr:last-child td { border-bottom: none; }
  .size-cards {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 18px;
  }
  .size-card {
    background: __CHIP_BG__; border-radius: 14px; padding: 16px 8px; text-align: center;
  }
  .size-card .label { font-size: 16px; color: __CHIP_TEXT__; font-weight: 600; }
  .size-card .value { font-size: 22px; color: #1f2933; font-weight: 800; margin-top: 4px; }

  /* COOK 리스트 — 이모지 대신 번호, 정갈하게 */
  .cook-list { list-style: none; padding: 0; margin: 6px 0 0; counter-reset: cook; }
  .cook-list li {
    font-size: 23px; padding: 20px 0; border-bottom: 1px solid #f2ede4;
    color: #3d4753; font-weight: 500; display: flex; align-items: baseline;
  }
  .cook-list li:last-child { border-bottom: none; }
  .cook-list li::before {
    counter-increment: cook; content: counter(cook, decimal-leading-zero);
    color: __PRIMARY__; font-weight: 800; font-size: 19px;
    margin-right: 16px; flex: none; letter-spacing: 1px;
  }

  /* REVIEWS */
  .reviews { display: grid; gap: 12px; margin-top: 6px; }
  .review { background: #faf9f7; border-radius: 14px; padding: 22px 24px; }
  .review .stars { color: #f59e0b; font-size: 19px; letter-spacing: 3px; }
  .review .who { font-size: 16px; color: #8b95a1; margin-top: 6px; }
  .review .text { font-size: 21px; color: #3d4753; margin-top: 10px; line-height: 1.65; }

  /* TRUST */
  .trust-points { list-style: none; padding: 0; margin: 6px 0 0; }
  .trust-points li {
    font-size: 23px; padding: 15px 0 15px 40px; position: relative;
    color: #191f28; font-weight: 600; letter-spacing: -0.3px;
  }
  .trust-points li::before {
    content: "✓"; position: absolute; left: 2px; top: 13px;
    color: #16a34a; font-weight: 900; font-size: 24px;
  }

  /* CTA */
  .cta-wrap { padding: 36px; }
  .cta {
    display: block; width: 100%; text-align: center;
    background: __PRIMARY__; color: #fff; font-size: 32px; font-weight: 800;
    padding: 26px 16px; border-radius: 20px; text-decoration: none;
    box-shadow: 0 8px 20px __CTA_SHADOW__;
  }

  /* AD / FOOTER */
  .ad-slot {
    margin: 24px 36px 24px;
    background: #f3f4f6; color: #9ca3af; border-radius: 12px;
    padding: 16px; text-align: center; font-size: 14px;
  }
  .footer {
    padding: 24px 36px 40px; text-align: center;
    font-size: 18px; color: #9ca3af;
  }
  .footer a { color: #9ca3af; margin: 0 8px; text-decoration: underline; }

  @media (max-width: 600px) {
    .hero-headline { font-size: 40px; }
    .hero-sub { font-size: 20px; }
    .product-name { font-size: 30px; }
    .subtitle { font-size: 20px; }
    .hook { padding: 40px 22px; }
    .hook h2 { font-size: 32px; }
    .hook p { font-size: 18px; }
    .appeal { font-size: 16px; padding: 14px 4px; }
    .section h2 { font-size: 26px; }
    .section p, .spec-table th, .spec-table td,
    .cook-list li, .trust-points li, .review .text { font-size: 18px; }
    .size-card .value { font-size: 18px; }
    .cta { font-size: 22px; padding: 20px 12px; }
  }
""".replace("__PAGE_WIDTH__", str(PAGE_WIDTH))


def _build_css(theme_key: str) -> str:
    """테마 토큰(__PRIMARY__ 등)을 실제 색으로 치환한 CSS 반환."""
    t = THEMES.get(theme_key) or THEMES[DEFAULT_THEME]
    css = CSS
    for k, v in t.items():
        css = css.replace("__" + k.upper() + "__", v)
    return css


def render_page(
    copy,
    images: dict,
    *,
    include_ad_slot: bool = True,
    video_taste: str = "",
    video_taste_mime: str = "",
    video_cook: str = "",
    video_cook_mime: str = "",
    extra_images: list | None = None,
    extra_videos: list | None = None,
    theme: str = DEFAULT_THEME,
) -> str:
    """copy: CopyResult, images: {label: PIL.Image}, video_*: data URI.

    extra_images: 슬롯에 배정되지 않은 추가 사진들 —
    '생생한 현장 컷' 띠로 조리 섹션 뒤에 전부 배치된다.
    extra_videos: [(data_uri, mime_hint), ...] 추가 움짤들 —
    후크 직후 / 산지 섹션 뒤 / 후기 직전 3개 지점에 순환 분산 배치되어
    스크롤 내내 식욕 자극이 끊기지 않게 한다.
    """
    hero_img = images.get("hero")
    close_img = images.get("close_up")
    size_img = images.get("size_compare")
    farm_img = images.get("farm")
    cook_img = images.get("cook_example")
    package_img = images.get("package")

    appeals_html = "".join(
        f'<div class="appeal">{_esc(a)}</div>' for a in (copy.appeals or [])[:3]
    )

    spec_rows = "".join(
        f'<tr><th>{_esc(it.get("label",""))}</th>'
        f'<td>{_esc(it.get("value",""))}</td></tr>'
        for it in (copy.spec_section.get("items") or [])
    )

    size_cards = "".join(
        f'<div class="size-card">'
        f'<div class="label">{_esc(it.get("label",""))}</div>'
        f'<div class="value">{_esc(it.get("value",""))}</div></div>'
        for it in (copy.size_section.get("items") or [])
    )

    cook_items = "".join(
        f"<li>{_esc(t)}</li>" for t in (copy.cook_section.get("tips") or [])
    )
    trust_items = "".join(
        f"<li>{_esc(p)}</li>" for p in (copy.trust_section.get("points") or [])
    )

    review_cards = "".join(
        (
            '<div class="review">'
            f'<div class="stars">{"★" * int(r.get("stars", 5))}</div>'
            f'<div class="who">{_esc(r.get("name",""))}</div>'
            f'<div class="text">"{_esc(r.get("text",""))}"</div>'
            "</div>"
        )
        for r in (copy.reviews_section.get("items") or [])
    )

    hero_data = _img_to_data_uri(hero_img)
    close_data = _img_to_data_uri(close_img)
    size_data = _img_to_data_uri(size_img)
    farm_data = _img_to_data_uri(farm_img)
    cook_data = _img_to_data_uri(cook_img)
    package_data = _img_to_data_uri(package_img)

    ad_block = (
        '<div class="ad-slot">광고 영역(앱인토스 정책: 광고는 항상 화면 맨 아래)</div>'
        if include_ad_slot else ""
    )

    hook = copy.hook_section or {}
    hook_block = ""
    if hook.get("title") or hook.get("body"):
        hook_block = f"""
      <section class="hook">
        {f'<span class="kicker">{_esc(hook.get("kicker",""))}</span>' if hook.get("kicker") else ''}
        <h2>{_esc(hook.get("title",""))}</h2>
        {f'<p>{_esc(hook.get("body",""))}</p>' if hook.get("body") else ''}
      </section>
        """

    taste_media = (
        _video_block(video_taste, video_taste_mime)
        if video_taste
        else (f'<div class="full-img"><img src="{close_data}" alt="close-up" /></div>' if close_data else "")
    )
    cook_media = (
        _video_block(video_cook, video_cook_mime)
        if video_cook
        else (f'<div class="full-img"><img src="{cook_data}" alt="cook" /></div>' if cook_data else "")
    )

    farm_block = ""
    if (copy.farm_section or {}).get("title") or (copy.farm_section or {}).get("body"):
        farm_block = f"""
      <section class="section">
        <h2>{_esc(copy.farm_section.get('title',''))}</h2>
        <p>{_esc(copy.farm_section.get('body',''))}</p>
        {f'<div class="full-img"><img src="{farm_data}" alt="farm" /></div>' if farm_data else ''}
      </section>
        """

    package_block = ""
    if (copy.package_section or {}).get("title") or (copy.package_section or {}).get("body"):
        package_block = f"""
      <section class="section">
        <h2>{_esc(copy.package_section.get('title',''))}</h2>
        <p>{_esc(copy.package_section.get('body',''))}</p>
        {f'<div class="full-img"><img src="{package_data}" alt="package" /></div>' if package_data else ''}
      </section>
        """

    # 추가 움짤 → 3개 지점(후크 직후/산지 뒤/후기 직전)에 순환 분산
    def _drool_section(blocks: list, title: str) -> str:
        if not blocks:
            return ""
        return (
            '<section class="section">'
            f'<h2><span class="tag">맛있겠다</span>{_esc(title)}</h2>'
            + "".join(blocks) + "</section>"
        )

    _vid_bands: list[list] = [[], [], []]
    for _i, _v in enumerate(extra_videos or []):
        _uri, _mime = (_v if isinstance(_v, (tuple, list)) else (_v, ""))
        blk = _video_block(_uri, _mime)
        if blk:
            _vid_bands[_i % 3].append(blk)
    band_after_hook = _drool_section(_vid_bands[0], "보기만 해도 침이 고여요")
    band_after_fresh = _drool_section(_vid_bands[1], "이 순간, 참을 수 있나요")
    band_before_reviews = _drool_section(_vid_bands[2], "한 번 더, 침샘 주의")

    extra_block = ""
    extra_uris = [_img_to_data_uri(im) for im in (extra_images or []) if im is not None]
    extra_uris = [u for u in extra_uris if u]
    if extra_uris:
        imgs_html = "".join(
            f'<div class="full-img"><img src="{u}" alt="extra" /></div>' for u in extra_uris
        )
        extra_block = f"""
      <section class="section">
        <h2><span class="tag">맛있겠다</span>생생한 현장 컷</h2>
        {imgs_html}
      </section>
        """

    reviews_block = ""
    if review_cards:
        reviews_block = f"""
      <section class="section">
        <h2><span class="tag">사야겠다</span>{_esc(copy.reviews_section.get('title','먼저 받아본 분들'))}</h2>
        <div class="reviews">{review_cards}</div>
      </section>
        """

    size_block = ""
    if size_cards or (copy.size_section or {}).get("body"):
        size_block = f"""
      <section class="section">
        <h2>{_esc(copy.size_section.get('title','크기와 양'))}</h2>
        {f'<p>{_esc(copy.size_section.get("body",""))}</p>' if copy.size_section.get('body') else ''}
        {f'<div class="size-cards">{size_cards}</div>' if size_cards else ''}
        {f'<div class="full-img"><img src="{size_data}" alt="size" /></div>' if size_data else ''}
      </section>
        """

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
<title>{_esc(copy.product_name)}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" />
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" />
<style>{_build_css(theme)}</style>
</head>
<body>
<div class="page">

  <section class="hero">
    {f'<img src="{hero_data}" alt="hero" />' if hero_data else ''}
    <div class="hero-overlay">
      <h1 class="hero-headline">{_esc(copy.hero_headline)}</h1>
      <p class="hero-sub">{_esc(copy.hero_sub)}</p>
    </div>
  </section>

  <section class="name-block">
    <h2 class="product-name">{_esc(copy.product_name)}</h2>
    <p class="subtitle">{_esc(copy.subtitle)}</p>
  </section>

  {hook_block}

  <section class="appeals">{appeals_html}</section>

  {band_after_hook}

  <section class="section">
    <h2><span class="tag">먹고 싶다</span>{_esc(copy.taste_section.get('title',''))}</h2>
    <p>{_esc(copy.taste_section.get('body',''))}</p>
    {taste_media}
  </section>

  {size_block}

  <section class="section">
    <h2><span class="tag">사고 싶다</span>{_esc(copy.fresh_section.get('title',''))}</h2>
    <p>{_esc(copy.fresh_section.get('body',''))}</p>
  </section>

  {band_after_fresh}

  {farm_block}

  <section class="section">
    <h2><span class="tag">먹고 싶다</span>{_esc(copy.cook_section.get('title',''))}</h2>
    <ul class="cook-list">{cook_items}</ul>
    {cook_media}
  </section>

  {extra_block}

  <section class="section">
    <h2>{_esc(copy.spec_section.get('title','제품 정보'))}</h2>
    <table class="spec-table">{spec_rows}</table>
  </section>

  {package_block}

  {band_before_reviews}

  {reviews_block}

  <section class="section">
    <h2><span class="tag">사야겠다</span>{_esc(copy.trust_section.get('title',''))}</h2>
    <ul class="trust-points">{trust_items}</ul>
  </section>

  <div class="cta-wrap">
    <a href="#" class="cta">{_esc(copy.cta or '지금 구매하기')}</a>
  </div>

  {ad_block}

  <div class="footer">
    <a href="?policy=terms">이용약관</a>·
    <a href="?policy=privacy">개인정보처리방침</a>
    <div style="margin-top:8px;">© AI 제품 상세페이지 자동 생성기</div>
  </div>
</div>
</body>
</html>
"""
