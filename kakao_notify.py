"""kakao_notify.py — 카카오톡 '나에게 보내기'(메모 API) 발송.

무료. 사장님 본인 카톡(나와의 채팅)으로만 발송. 친구/단톡 발송은 카카오 비즈니스
심사가 필요해 personal 알림엔 과함.

필요 환경변수(.env 또는 GitHub Secrets):
    KAKAO_REST_API_KEY   — 카카오 개발자 앱 REST API 키
    KAKAO_REFRESH_TOKEN  — get_kakao_token.py 로 1회 발급

access token 은 refresh token 으로 매번 갱신(6시간 만료 대응).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def _post(url: str, data: dict, headers: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def refresh_access_token(rest_key: str | None = None,
                         refresh_token: str | None = None) -> str:
    rest_key = rest_key or os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = refresh_token or os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not (rest_key and refresh_token):
        raise RuntimeError("KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 이 없습니다.")
    res = _post(_TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    })
    tok = res.get("access_token")
    if not tok:
        raise RuntimeError(f"토큰 갱신 실패: {res}")
    return tok


def send_to_me(text: str, link: str = "", access_token: str | None = None) -> bool:
    """나에게 텍스트 메모 발송. 성공 True."""
    token = access_token or refresh_access_token()
    template = {
        "object_type": "text",
        "text": text[:1900],
        "link": {"web_url": link or "https://youtube.com",
                 "mobile_web_url": link or "https://youtube.com"},
        "button_title": "영상 보기",
    }
    try:
        res = _post(_MEMO_URL,
                    {"template_object": json.dumps(template, ensure_ascii=False)},
                    headers={"Authorization": f"Bearer {token}"})
        return res.get("result_code") == 0
    except Exception as e:               # noqa: BLE001
        print("카톡 발송 오류:", e)
        return False


if __name__ == "__main__":
    ok = send_to_me("🎬 썸네일·제목 연구소 — 카톡 알림 테스트입니다.")
    print("발송 성공" if ok else "발송 실패 — 키/토큰 확인.")
