import streamlit as st

st.set_page_config(page_title="이용약관", page_icon="📄", layout="centered")

st.markdown(
    """
<style>
.main .block-container { max-width: 520px; padding-top: 1.2rem; }
h1 { font-size: 1.6rem !important; }
h3 { font-size: 1.1rem !important; margin-top: 1.2rem; }
p, li { font-size: 0.95rem; line-height: 1.6; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("📄 이용약관")
st.caption("최종 업데이트: 2026-06-24")

st.markdown(
    """
### 1. 서비스 안내
본 앱(이하 "서비스")은 사용자가 직접 업로드한 음악·이미지 파일을 이어붙여
긴 음악 파일(MP3) 및 영상(MP4)을 생성하는 도구입니다.

### 2. 사용자의 책임
- 사용자는 본인이 **저작권을 보유하거나, 합법적으로 사용 권한이 있는**
  음악·이미지 파일만 업로드해야 합니다.
- 타인의 저작물을 무단으로 업로드·재가공·배포함으로써 발생하는 모든 책임은
  사용자에게 있습니다.

### 3. 콘텐츠 처리
- 업로드한 파일은 결과물 생성을 위해서만 임시로 처리되며, 처리가 끝나면
  자동으로 삭제됩니다. 서비스는 사용자의 파일을 별도 저장·수집하지 않습니다.

### 4. 면책
- 본 서비스는 "있는 그대로(as-is)" 제공되며, 결과물의 품질·정확성·법적 안전성에
  대해 어떠한 보증도 하지 않습니다.
- 서비스 이용으로 발생한 직·간접적 손해에 대해 운영자는 책임을 지지 않습니다.

### 5. 금지 행위
- 타인의 저작권·초상권을 침해하는 콘텐츠 업로드
- 불법·음란·폭력·차별 등 공서양속에 반하는 콘텐츠 생성
- 서비스의 정상적 운영을 방해하는 행위

### 6. 약관 변경
약관은 서비스 개선을 위해 변경될 수 있으며, 변경 시 본 페이지에 공지합니다.
"""
)

st.markdown("---")
st.page_link("app.py", label="← 앱으로 돌아가기")
