"""
공구 중개업 메일 발송 모듈
- 인플루언서용 / 제조사용 템플릿
- SMTP 발송 (Gmail 기본, 다른 SMTP도 지원)
- 발송 전 미리보기, 발송 후 DB 기록
"""
import smtplib, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

# ── 템플릿 ────────────────────────────────────────────────

TEMPLATES = {
    "인플루언서_공구제안": {
        "subject": "[공구 제안] {item_name} 공동구매 협업 제안드립니다",
        "body": """안녕하세요, {influencer_name}님 😊

저는 공구 중개 전문 {sender_name}입니다.

평소 {influencer_name}님의 콘텐츠를 즐겨보며, 팔로워분들과의 신뢰 높은 소통에 늘 인상 깊었습니다.

이번에 {item_name} 관련 우수한 제조사를 발굴하여, {influencer_name}님과 함께 공동구매를 진행해보고자 연락드립니다.

📦 제안 내용
• 상품: {item_name}
• 카테고리: {category}
• 예상 공급가: {supply_price}
• 인플루언서 수수료: 판매액의 {commission_rate}%
• 배송: 제조사 직배송 (재고 부담 없음)

💡 저희 서비스
• 제조사 섭외·협상 전담
• 주문 취합·정산 대행
• CS 1차 대응 지원

관심 있으시면 편하게 답장 주세요.
더 자세한 자료를 바로 공유드리겠습니다.

감사합니다.
{sender_name} 드림
📧 {sender_email}
📱 {sender_phone}
""",
    },

    "인플루언서_시즌제안": {
        "subject": "[시즌 공구 제안] {season} 시즌 공동구매 기회를 잡으세요!",
        "body": """안녕하세요, {influencer_name}님!

공구 중개 전문 {sender_name}입니다.

곧 다가오는 {season} 시즌을 앞두고, 이 시기에 특히 잘 팔리는 상품들을 확보해두었습니다.

🗓️ {season} 인기 공구 아이템
{season_items}

위 상품들은 매년 {season} 시즌에 완판률이 높고, 팔로워 반응이 좋은 카테고리입니다.
{influencer_name}님의 팔로워 성향에 맞는 상품을 골라 제안드릴 수 있습니다.

✅ 진행 방식
1. 관심 상품 선택
2. 제조사 조건 협의 (저희가 진행)
3. 공구 일정 확정 후 진행

부담 없이 답장 주세요 :)

{sender_name} 드림
📧 {sender_email}
""",
    },

    "제조사_연결제안": {
        "subject": "[판로 제안] 인플루언서 공동구매 채널 연결해 드립니다",
        "body": """안녕하세요, {company}의 {contact_name}님.

저는 인플루언서 공구 중개 전문 {sender_name}입니다.

귀사의 {product_line} 제품을 팔로워 수만~수십만의 인플루언서와 연결하여 단기간에 대량 판매할 수 있는 기회를 제안드립니다.

📊 공동구매 채널의 강점
• 짧은 기간(3~7일) 집중 판매로 빠른 재고 회전
• 인플루언서 신뢰 기반 → 높은 구매 전환율
• 재고 직배송 → 중간 물류비 절감
• 브랜드 인지도 자연스럽게 상승

💼 저희 역할
• 귀사 제품에 맞는 인플루언서 매칭
• 공구 조건 협상 대행
• 주문 취합·정산 관리
• 추가 공구 기회 지속 연결

중개 수수료는 매출 발생 시에만 청구되며, 초기 비용은 전혀 없습니다.

한 번 미팅 가능하시면 더 자세히 안내드리겠습니다.

감사합니다.
{sender_name} 드림
📧 {sender_email}
📱 {sender_phone}
""",
    },

    "제조사_공급조건확인": {
        "subject": "공동구매 공급 조건 확인 요청 - {sender_name}",
        "body": """안녕하세요, {company} {contact_name}님.

지난번 연락드렸던 공구 중개 {sender_name}입니다.

현재 {product_line} 상품으로 공동구매를 기획 중입니다.
아래 조건을 확인해주실 수 있을까요?

📋 확인 요청 사항
1. 공급가 (소비자가 대비 %):
2. 최소 주문 수량:
3. 직배송 가능 여부:
4. 배송 소요 기간:
5. 반품/교환 정책:
6. 공구 전용 특가 적용 가능 여부:

회신 주시면 바로 인플루언서 매칭을 진행하겠습니다.

감사합니다.
{sender_name}
📧 {sender_email}
📱 {sender_phone}
""",
    },
}


def render_template(template_name: str, variables: dict) -> dict:
    """템플릿에 변수 치환 → {subject, body} 반환"""
    tpl = TEMPLATES.get(template_name)
    if not tpl:
        raise ValueError(f"템플릿 없음: {template_name}")
    subject = tpl["subject"].format_map(variables)
    body = tpl["body"].format_map(variables)
    return {"subject": subject, "body": body}


def send_email(
    to_email: str,
    subject: str,
    body: str,
    smtp_host: str = None,
    smtp_port: int = 587,
    smtp_user: str = None,
    smtp_password: str = None,
    from_name: str = None,
) -> tuple[bool, str]:
    """
    SMTP 메일 발송. 환경변수 또는 직접 파라미터로 설정.
    반환: (성공여부, 메시지)
    """
    smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_user = smtp_user or os.getenv("SMTP_USER", "")
    smtp_password = smtp_password or os.getenv("SMTP_PASSWORD", "")
    from_name = from_name or os.getenv("SENDER_NAME", smtp_user)

    if not smtp_user or not smtp_password:
        return False, "SMTP 계정 정보 없음 (SMTP_USER, SMTP_PASSWORD 환경변수 설정 필요)"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{smtp_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())

        return True, f"발송 완료 → {to_email}"
    except Exception as e:
        return False, str(e)


def get_template_names() -> list:
    return list(TEMPLATES.keys())


def get_template_variables(template_name: str) -> list:
    """템플릿에서 {변수} 목록 추출"""
    import re
    tpl = TEMPLATES.get(template_name, {})
    text = tpl.get("subject", "") + tpl.get("body", "")
    return sorted(set(re.findall(r"\{(\w+)\}", text)))
