import streamlit as st

st.set_page_config(page_title="개인정보처리방침", page_icon="🔒", layout="centered")

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

st.title("🔒 개인정보처리방침")
st.caption("최종 업데이트: 2026-06-24")

st.markdown(
    """
### 1. 수집하는 개인정보 항목
본 앱은 별도의 회원가입·로그인 절차가 없으며, **이름·이메일·전화번호 등
개인을 식별할 수 있는 정보를 수집하지 않습니다.**

### 2. 업로드 파일 처리
- 사용자가 업로드한 음악·이미지 파일은 결과물 생성을 위한 일시적 처리에만
  사용되며, 처리 완료 후 **임시 폴더에서 자동 삭제**됩니다.
- 파일은 외부 서버로 전송되지 않으며, 별도 저장·백업·분석되지 않습니다.

### 3. 쿠키·세션
서비스 동작에 필요한 최소한의 세션 정보(현재 작업 상태)만 브라우저에 임시로
유지하며, 브라우저를 닫으면 사라집니다.

### 4. 제3자 제공
사용자의 어떠한 정보도 제3자에게 제공하지 않습니다.

### 5. 이용자의 권리
사용자는 언제든지 브라우저 새로고침을 통해 임시 데이터를 초기화할 수 있으며,
업로드 파일은 추가 보관되지 않으므로 별도의 삭제 요청이 필요하지 않습니다.

### 6. 문의
개인정보 관련 문의는 앱 운영자에게 연락 주시기 바랍니다.
"""
)

st.markdown("---")
st.page_link("app.py", label="← 앱으로 돌아가기")
