"""🔌 SRE-OS Provider Adapter — LLM 프로바이더 추상화 (원본 스펙 §Provider Adapter 채택).

원칙:
- **Mock First**: 키가 하나도 없으면 llm_json() 이 None 을 반환 → 런타임은 규칙기반으로 완주.
  (규칙기반이 곧 Mock 이다 — 키 없이도 전체 흐름이 끝까지 동작한다.)
- **다중 프로바이더**: Anthropic(claude) / OpenAI(gpt-4o) / Gemini(flash) 중 있는 것을 사용.
  우선순위: 환경변수 SRE_PROVIDER 지정 > anthropic > openai > gemini.
- **구조화 JSON**: llm_json() 은 항상 dict 를 목표로 파싱(코드펜스·잡텍스트 방어).
- **격리**: 라이브러리 미설치·키 오류·파싱 실패 어느 경우든 예외를 삼키고 None 반환 →
  한 프로바이더가 죽어도 다음으로 폴백하거나 규칙기반으로 내려간다.

concept_maker._llm(백엔드) 과 같은 개념이나, 저장소 루트에서 백엔드 경로 의존 없이
독립적으로 쓰도록 재구현(sre_runtime 이 루트 모듈이므로).
"""
from __future__ import annotations

import json
import os
import re

# 프로바이더별 마지막 오류(디버깅·상태표시용)
LAST_ERROR: dict[str, str] = {"anthropic": "", "openai": "", "gemini": ""}

_ORDER = ("anthropic", "openai", "gemini")
_ENV_KEY = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
_MODEL = {
    "anthropic": os.environ.get("SRE_ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
    "openai": os.environ.get("SRE_OPENAI_MODEL", "gpt-4o"),
    "gemini": os.environ.get("SRE_GEMINI_MODEL", "gemini-2.0-flash"),
}


def _has(provider: str) -> bool:
    return bool(os.environ.get(_ENV_KEY.get(provider, ""), "").strip())


def available() -> list[str]:
    """키가 있는 프로바이더 목록(우선순위 순)."""
    return [p for p in _ORDER if _has(p)]


def active_provider() -> str:
    """실제로 쓸 프로바이더 이름. 아무 키도 없으면 'mock'."""
    forced = os.environ.get("SRE_PROVIDER", "").strip().lower()
    if forced in _ORDER and _has(forced):
        return forced
    av = available()
    return av[0] if av else "mock"


def is_live() -> bool:
    return active_provider() != "mock"


# ── 프로바이더별 호출(문자열 반환, 실패 시 None) ─────────────────
def _call_anthropic(system: str, user: str) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=_MODEL["anthropic"],
            max_tokens=4000,
            system=system + "\n\n반드시 유효한 JSON 객체 하나만 출력하라(코드펜스 금지).",
            messages=[{"role": "user", "content": user}],
        )
        LAST_ERROR["anthropic"] = ""
        parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
        return ("".join(parts)).strip()
    except Exception as e:   # noqa: BLE001
        LAST_ERROR["anthropic"] = str(e)[:400]
        return None


def _call_openai(system: str, user: str) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        r = client.chat.completions.create(
            model=_MODEL["openai"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.7,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        LAST_ERROR["openai"] = ""
        return (r.choices[0].message.content or "").strip()
    except Exception as e:   # noqa: BLE001
        LAST_ERROR["openai"] = str(e)[:400]
        return None


def _call_gemini(system: str, user: str) -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel(_MODEL["gemini"])
        cfg = {"temperature": 0.7, "response_mime_type": "application/json"}
        r = model.generate_content(system + "\n\n" + user, generation_config=cfg)
        LAST_ERROR["gemini"] = ""
        return (r.text or "").strip()
    except Exception as e:   # noqa: BLE001
        LAST_ERROR["gemini"] = str(e)[:400]
        return None


_CALLERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


# ── JSON 파싱(방어적) ─────────────────────────────────────────
def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    t = text.strip()
    # 코드펜스 제거
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # 첫 { ~ 마지막 } 사이만 재시도
    i, j = t.find("{"), t.rfind("}")
    if 0 <= i < j:
        try:
            obj = json.loads(t[i:j + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


# ── 외부 진입점 ───────────────────────────────────────────────
def llm_json(system: str, user: str, provider: str | None = None) -> dict | None:
    """구조화 JSON 응답을 dict 로 반환. 키 없음/실패/파싱실패 → None(규칙기반 폴백 신호).

    provider 미지정 시 active_provider() 하나만 시도(비용 절약). 지정 시 그것만.
    """
    prov = provider or active_provider()
    if prov == "mock":
        return None
    caller = _CALLERS.get(prov)
    if not caller:
        return None
    return _parse_json(caller(system, user))


def status() -> dict:
    """상태 조회(화면·health 용)."""
    return {
        "active": active_provider(),
        "available": available(),
        "live": is_live(),
        "models": {p: _MODEL[p] for p in _ORDER if _has(p)},
        "errors": {k: v for k, v in LAST_ERROR.items() if v},
    }


# ── 자기검증(키 없이) ─────────────────────────────────────────
if __name__ == "__main__":
    # 키 없는 환경: mock 이어야 하고 llm_json 은 None
    # (실행 환경에 실제 키가 있으면 live 로 나올 수 있음 — 그 경우도 정상)
    print("status:", status())

    # 파서 단위 검증(프로바이더 무관)
    assert _parse_json('{"a":1}') == {"a": 1}
    assert _parse_json('```json\n{"a":2}\n```') == {"a": 2}
    assert _parse_json('설명... {"a":3, "b":[1,2]} 끝') == {"a": 3, "b": [1, 2]}
    assert _parse_json("깨진 텍스트") is None
    assert _parse_json(None) is None
    assert _parse_json('[1,2,3]') is None    # dict 아니면 None

    # 강제 mock: SRE_PROVIDER=mock 흉내 — 키가 없으면 자동 mock
    if not available():
        assert active_provider() == "mock"
        assert llm_json("s", "u") is None
        print("✅ (키 없음) mock 경로 확인 — llm_json None 반환")
    else:
        print(f"ℹ️ 실제 키 감지({available()}) — 라이브 프로바이더 사용 가능")
    print("✅ sre_provider self-test 통과 — 파서 4종 + 프로바이더 선택 로직")
