"""상세페이지 HTML 템플릿.

모바일 세로(폭 720px 기준) · 따뜻한 톤 · 큰 글씨 · 5070 친화.
섹션 순서는 4단 깔때기를 따른다:
  Hero[맛있겠다] → 소구점 → Taste[먹고 싶다] → Fresh[사고 싶다]
  → Cook[먹고 싶다 재점화] → Spec → Trust[사야겠다] → CTA → (광고) → 푸터
"""
from __future__ import annotations

import base64
import io
import html as html_lib
from typing import Optional

from PIL import Image


PAGE_WIDTH = 720  # 모바일 세로 기준(레티나 환경에서도 또렷)


def _img_to_data_uri(img: Optional[Image.Image]) -> str:
    if img is None:
        return ""
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _esc(text: str) -> str:
    return html_lib.escape(str(text or ""))


CSS = """
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
      'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    color: #1f2933;
    background: #faf6f0;
    -webkit-text-size-adjust: 100%;
    word-break: keep-all;
    line-height: 1.55;
  }
  .page {
    width: __PAGE_WIDTH__px;
    max-width: 100%;
    margin: 0 auto;
    background: #ffffff;
    overflow: hidden;
  }
  .hero { position: relative; }
  .hero img {
    display: block; width: 100%; height: auto;
  }
  .hero-overlay {
    position: absolute; left: 0; right: 0; bottom: 0;
    padding: 48px 36px 36px;
    background: linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.55) 60%, rgba(0,0,0,0.78) 100%);
    color: #fff;
  }
  .hero-headline {
    font-size: 56px; font-weight: 900; letter-spacing: -1.5px; margin: 0 0 12px;
    text-shadow: 0 2px 12px rgba(0,0,0,0.45);
  }
  .hero-sub { font-size: 26px; font-weight: 600; opacity: 0.95; margin: 0; }
  .name-block { padding: 36px 36px 8px; }
  .product-name {
    font-size: 40px; font-weight: 800; color: #c2410c; letter-spacing: -1px; margin: 0 0 6px;
  }
  .subtitle { font-size: 26px; font-weight: 500; color: #4b5563; margin: 0; }
  .appeals {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 12px; padding: 28px 24px;
  }
  .appeal {
    background: #fff7ed; border: 2px solid #fdba74; border-radius: 16px;
    padding: 18px 8px; text-align: center;
    font-size: 22px; font-weight: 700; color: #9a3412;
  }
  .section { padding: 40px 36px; border-top: 1px solid #f1e9dd; }
  .section h2 {
    font-size: 36px; font-weight: 800; letter-spacing: -1px; margin: 0 0 18px;
    color: #1f2933;
  }
  .section h2 .tag {
    display: inline-block; vertical-align: middle;
    font-size: 18px; font-weight: 700; color: #c2410c;
    background: #ffedd5; border-radius: 999px; padding: 4px 12px; margin-right: 10px;
  }
  .section p { font-size: 26px; line-height: 1.6; color: #1f2933; margin: 0; }
  .section .full-img { margin-top: 22px; }
  .section .full-img img { display: block; width: 100%; height: auto; border-radius: 18px; }

  .spec-table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  .spec-table th, .spec-table td {
    padding: 18px 16px; font-size: 24px; border-bottom: 1px solid #f1e9dd;
    text-align: left;
  }
  .spec-table th {
    width: 36%; color: #6b7280; font-weight: 600; background: #fafaf6;
  }
  .spec-table td { color: #1f2933; font-weight: 700; }

  .cook-list { list-style: none; padding: 0; margin: 6px 0 0; }
  .cook-list li {
    font-size: 24px; padding: 18px 0; border-bottom: 1px dashed #e5d9c4;
    color: #1f2933; font-weight: 600;
  }
  .cook-list li::before {
    content: "🍳"; margin-right: 10px;
  }

  .trust-points { list-style: none; padding: 0; margin: 6px 0 0; }
  .trust-points li {
    font-size: 24px; padding: 14px 0 14px 36px; position: relative;
    color: #1f2933; font-weight: 600;
  }
  .trust-points li::before {
    content: "✓"; position: absolute; left: 0; top: 12px;
    color: #16a34a; font-weight: 900; font-size: 28px;
  }

  .cta-wrap { padding: 36px; }
  .cta {
    display: block; width: 100%; text-align: center;
    background: #ea580c; color: #fff; font-size: 32px; font-weight: 800;
    padding: 26px 16px; border-radius: 20px; text-decoration: none;
    box-shadow: 0 8px 20px rgba(234,88,12,0.35);
  }

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
    .appeal { font-size: 16px; padding: 14px 4px; }
    .section h2 { font-size: 26px; }
    .section p, .spec-table th, .spec-table td,
    .cook-list li, .trust-points li { font-size: 18px; }
    .cta { font-size: 22px; padding: 20px 12px; }
  }
""".replace("__PAGE_WIDTH__", str(PAGE_WIDTH))


def render_page(copy, images: dict, *, include_ad_slot: bool = True) -> str:
    """copy: CopyResult, images: {label: PIL.Image} → 자체 완결 HTML 문자열."""
    hero_img = images.get("hero")
    close_img = images.get("close_up")
    cook_img = images.get("cook_example")

    appeals_html = "".join(
        f'<div class="appeal">{_esc(a)}</div>' for a in (copy.appeals or [])[:3]
    )

    spec_rows = ""
    for it in (copy.spec_section.get("items") or []):
        spec_rows += (
            f'<tr><th>{_esc(it.get("label",""))}</th>'
            f'<td>{_esc(it.get("value",""))}</td></tr>'
        )

    cook_items = "".join(
        f"<li>{_esc(t)}</li>" for t in (copy.cook_section.get("tips") or [])
    )
    trust_items = "".join(
        f"<li>{_esc(p)}</li>" for p in (copy.trust_section.get("points") or [])
    )

    hero_data = _img_to_data_uri(hero_img)
    close_data = _img_to_data_uri(close_img)
    cook_data = _img_to_data_uri(cook_img)

    ad_block = (
        '<div class="ad-slot">광고 영역(앱인토스 정책: 광고는 항상 화면 맨 아래)</div>'
        if include_ad_slot else ""
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
<title>{_esc(copy.product_name)}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" />
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" />
<style>{CSS}</style>
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

  <section class="appeals">{appeals_html}</section>

  <section class="section">
    <h2><span class="tag">먹고 싶다</span>{_esc(copy.taste_section.get('title',''))}</h2>
    <p>{_esc(copy.taste_section.get('body',''))}</p>
    {f'<div class="full-img"><img src="{close_data}" alt="close-up" /></div>' if close_data else ''}
  </section>

  <section class="section">
    <h2><span class="tag">사고 싶다</span>{_esc(copy.fresh_section.get('title',''))}</h2>
    <p>{_esc(copy.fresh_section.get('body',''))}</p>
  </section>

  <section class="section">
    <h2><span class="tag">먹고 싶다</span>{_esc(copy.cook_section.get('title',''))}</h2>
    <ul class="cook-list">{cook_items}</ul>
    {f'<div class="full-img"><img src="{cook_data}" alt="cook" /></div>' if cook_data else ''}
  </section>

  <section class="section">
    <h2>{_esc(copy.spec_section.get('title','제품 정보'))}</h2>
    <table class="spec-table">{spec_rows}</table>
  </section>

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
