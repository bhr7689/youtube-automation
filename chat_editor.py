"""chat_editor.py — 대화로 썸네일·제목 다듬기.

사용자와 채팅하며 제목·썸네일 문구·장면(이미지 프롬프트)을 반복 수정.
각 턴마다 LLM 이 {reply, title, thumb_text, scene} 을 돌려줘 작업물을 갱신한다.
키 없으면 안내. Streamlit 비의존.
"""
from __future__ import annotations

import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jpshorts", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def chat(history: list[dict], working: dict, genre: str = "", brief: str = "") -> dict:
    """history=[{role,content}], working={title,thumb_text,scene} → 갱신된 작업물+reply."""
    try:
        import concept_maker as CM
    except Exception:                   # noqa: BLE001
        CM = None

    convo = "\n".join(f"{'사용자' if m['role'] == 'user' else '도우미'}: {m['content']}"
                      for m in history[-8:])
    prompt = f"""너는 유튜브 '{genre}' 채널의 썸네일·제목 편집 도우미다.
사용자와 대화하며 제목·썸네일 문구·장면(영어 이미지 프롬프트)을 다듬는다.
장르 공식/우리 시그니처: {brief or '(없음)'}

현재 작업물:
- 제목: {working.get('title', '')}
- 썸네일 문구(이미지 위 한글): {working.get('thumb_text', '')}
- 장면(영어, 글자 없는 배경): {working.get('scene', '')}

대화:
{convo}

사용자의 마지막 요청을 반영해 개선하라. 요청 없는 항목은 기존 값 유지.
반드시 아래 JSON 만 출력:
{{"reply":"<사용자에게 한국어로 무엇을 바꿨는지 짧게>",
  "title":"<제목>","thumb_text":"<썸네일 문구>","scene":"<장면 영어>"}}"""

    if CM is not None:
        raw = CM._llm(prompt, json_mode=True)
        if raw:
            try:
                d = json.loads(raw) if raw.strip().startswith("{") else (CM._parse_json(raw) or {})
                return {
                    "reply": d.get("reply", "수정했어요."),
                    "title": d.get("title", working.get("title", "")),
                    "thumb_text": d.get("thumb_text", working.get("thumb_text", "")),
                    "scene": d.get("scene", working.get("scene", "")),
                }
            except Exception:           # noqa: BLE001
                pass
    return {"reply": "AI 편집은 OpenAI/Gemini 키가 필요해요(설정 탭).", **working}
