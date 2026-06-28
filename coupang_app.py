"""
쿠팡 콘텐츠 자동수집기 — Streamlit UI
coupang_crawl.py 를 subprocess 로 호출해 결과를 표시합니다.
"""
import streamlit as st
import subprocess, sys, os, json, re
from pathlib import Path

st.set_page_config(page_title="쿠팡 콘텐츠 자동수집", page_icon="🛒", layout="wide")

st.title("🛒 쿠팡 콘텐츠 자동수집기")
st.caption("쿠팡 상품 링크를 넣으면 가격·리뷰·이미지를 자동으로 가져옵니다.")

CORE = os.path.join(os.path.dirname(__file__), "coupang_crawl.py")


def run_crawl(url: str) -> dict:
    """coupang_crawl.py 를 subprocess 로 실행해 JSON 결과 반환"""
    try:
        proc = subprocess.run(
            [sys.executable, CORE, "--json", url],
            capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        # stdout 에서 JSON 줄 찾기
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        # JSON 없으면 에러 반환
        return {"error": proc.stderr.strip() or proc.stdout.strip() or "알 수 없는 오류"}
    except subprocess.TimeoutExpired:
        return {"error": "시간 초과 (120초). 네트워크 상태를 확인하세요."}
    except Exception as e:
        return {"error": str(e)}


# ── 입력 영역 ────────────────────────────────────────────────
url = st.text_input(
    "쿠팡 상품 링크",
    placeholder="https://www.coupang.com/vp/products/... 또는 https://link.coupang.com/a/...",
    help="단축 링크(link.coupang.com)도 자동으로 실제 URL로 변환합니다."
)

col_btn, col_clear = st.columns([1, 5])
with col_btn:
    go = st.button("🔍 수집 시작", type="primary", use_container_width=True)
with col_clear:
    if st.button("🗑️ 초기화"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ── 수집 실행 ────────────────────────────────────────────────
if go and url.strip():
    with st.spinner("수집 중... (최대 2분 소요)"):
        result = run_crawl(url.strip())
    st.session_state["result"] = result

# ── 결과 표시 ────────────────────────────────────────────────
result = st.session_state.get("result")
if result:
    if result.get("error"):
        st.error(f"오류: {result['error']}")
        st.info("💡 쿠팡이 봇을 차단했을 수 있어요. 잠시 후 다시 시도하거나, 상품명·가격·후기를 직접 복사해 주세요.")
    else:
        # 기본 정보
        st.subheader(result.get("title", "(제목 없음)"))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("현재가", result.get("price") or "—")
        col2.metric("원가", result.get("original_price") or "—")
        col3.metric("할인율", result.get("discount_rate") or "—")
        col4.metric("평점", result.get("rating") or "—")

        st.caption(f"리뷰 수: {result.get('review_count') or '—'}  |  URL: {result.get('url','')}")

        st.divider()

        # 이미지
        images = result.get("images", [])
        if images:
            st.subheader("🖼️ 이미지")
            cols = st.columns(min(len(images), 3))
            for i, img in enumerate(images[:6]):
                src = img if img.startswith("http") else "https:" + img
                cols[i % 3].image(src, use_container_width=True)

        # 리뷰
        reviews = result.get("reviews", [])
        st.subheader(f"💬 구매자 리뷰 ({len(reviews)}개)")
        if reviews:
            for r in reviews:
                st.markdown(f"- {r}")
        else:
            st.info("리뷰를 자동 수집하지 못했습니다. 상품 페이지에서 2~3개를 직접 복사해 주세요.")

        st.divider()

        # 콘텐츠 초안
        st.subheader("📋 콘텐츠 초안 (복사해서 사용)")
        title = result.get("title", "")
        price = result.get("price", "")
        discount = result.get("discount_rate", "")
        orig = result.get("original_price", "")
        rating = result.get("rating", "")

        summary_text = f"""[상품명]
{title}

[가격 정보]
현재가: {price}
원가: {orig}
할인율: {discount}

[평점]
{rating or '정보 없음'}

[구매자 리뷰]
{chr(10).join(f'- {r}' for r in reviews) if reviews else '(직접 입력 필요)'}

[상품 URL]
{result.get('url', '')}
"""
        st.code(summary_text, language=None)

        # JSON 다운로드
        st.download_button(
            "⬇️ 결과 JSON 다운로드",
            data=json.dumps(result, ensure_ascii=False, indent=2),
            file_name=f"coupang_{re.sub(r'[^\\w가-힣]', '_', title)[:30]}.json",
            mime="application/json"
        )
