"""채널 브랜드 브리프 — 모든 생성 앱이 공유하는 채널 정체성 메모리.

이 모듈이 가진 한 줄 약속:
  "이 채널은 어떤 사람을 위해, 어떤 약속을, 어떤 톤으로 전달하는가?"
를 한 번 정해 두면, 가사 생성기·역설계·제목·채널 설명 생성기 등
모든 앱이 같은 브리프를 LLM 프롬프트에 자동으로 주입한다.

저장: channel_brief.json (gitignore 대상 — 사용자 편집 보존)
시드: SEED_BRIEFS — 코드에 박힘. 새 키 추가 시 자동 보충.

사용 예시:
    from channel_brief import load_brief, as_prompt_block
    brief = load_brief()
    prompt = base_prompt + "\n\n" + as_prompt_block(brief)
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

BRIEF_PATH = Path(__file__).resolve().parent / "channel_brief.json"


# ────────────────────────────────────────────────────────────────────────────
# 시드 — 사용자가 명시한 '스텔라장식 프렌치 샹송 카페' 채널 톤을 기본값으로.
# 다른 채널을 운영하면 사이드바에서 편집하거나 새 브리프를 추가.
# ────────────────────────────────────────────────────────────────────────────
SEED_BRIEFS: dict[str, dict] = {
    "parisian_chanson_cafe": {
        # ── 1) 정체성 ────────────────────────────────────────────────
        "channel_name": "파리지앵 샹송 카페",
        "one_line_identity": (
            "비 오는 파리의 작은 카페에서 들려오는, "
            "스텔라장식 톤의 부드러운 프렌치 샹송 채널"
        ),
        # ── 2) 누가 듣는가 (타깃) ────────────────────────────────────
        "target_audience": (
            "하루의 끝에 혼자 커피를 마시며 잠시 숨 돌리고 싶은 30~50대. "
            "잠들기 전, 공부할 때, 카페에서 조용히 일할 때 배경으로 두기 좋아하는 사람."
        ),
        # ── 3) 약속 (이 채널을 보면 무엇을 얻는가) ───────────────────
        "promise": (
            "지친 마음이 따뜻해지는 7분의 휴식. "
            "복잡한 머릿속을 잠시 비워주는, 가사 없이도 위로가 되는 멜로디."
        ),
        # ── 4) 감정 키워드 (SEO + 감성) ──────────────────────────────
        "emotional_keywords": [
            "위로", "휴식", "감성", "잠들기 전", "비 오는 날",
            "혼자 듣는", "카페 음악", "잔잔한", "따뜻한", "꿈결",
        ],
        # ── 5) 음악적 키워드 (SEO) ───────────────────────────────────
        "music_keywords": [
            "프렌치 샹송", "아코디언", "피아노", "어쿠스틱",
            "재즈 무드", "보사노바", "스텔라장식 스타일",
        ],
        # ── 6) 톤 앤 매너 (글쓰기 규칙) ──────────────────────────────
        "tone_and_manner": (
            "따뜻하고 조용한 친구가 옆에서 속삭이듯. "
            "느낌표는 거의 안 쓰고, 줄임표(…)로 여운을 남긴다. "
            "전문 용어보다 그림이 그려지는 감각어를 쓴다."
        ),
        # ── 7) 금지 (절대 쓰지 말 것) ────────────────────────────────
        "avoid": [
            "강한 명령형 ('지금 당장 구독!')",
            "과장된 광고체 ('대박', '레전드')",
            "타 플랫폼 우회 표현",
            "정치·종교 코멘트",
        ],
        # ── 8) 시그니처 문구 (반복 노출되는 한 줄) ──────────────────
        "signature_lines": [
            "오늘의 당신께, 7분의 위로를.",
            "비 오는 파리의 작은 카페에서 보내드립니다.",
        ],
        # ── 9) CTA 스타일 (강요 X, 초대 O) ──────────────────────────
        "cta_style": (
            "강요하지 말고 초대하듯. "
            "'마음에 드신다면 구독해 두세요. 매일 한 곡, 조용히 올라옵니다.' 정도의 톤."
        ),
        # ── 10) 발행 리듬 ────────────────────────────────────────────
        "upload_rhythm": "매일 한 곡, 7~12분 길이의 카페 무드 음악",
    },

    # 두 번째 시드 — 5070 트로트 채널 (사용자가 트로트도 운영하면 선택)
    "hometown_memory_trot": {
        "channel_name": "고향의 봄, 마음의 노래",
        "one_line_identity": (
            "어머니가 흥얼거리시던 그 시절 트로트, "
            "5070 세대의 따뜻한 추억을 깨우는 채널"
        ),
        "target_audience": (
            "50~70대 부모님 세대, 그리고 부모님께 들려드리고 싶은 자녀 세대. "
            "차에서, 마당에서, 주방에서 배경으로 틀어두기 좋아하는 분들."
        ),
        "promise": (
            "잊고 있던 그 시절의 봄날이 다시 떠오르는 노래. "
            "어머니 손맛처럼 따뜻한, 익숙하지만 새로운 트로트."
        ),
        "emotional_keywords": [
            "추억", "그리움", "어머니", "고향", "옛날 노래",
            "5070", "효도", "따뜻한", "정겨운", "봄날",
        ],
        "music_keywords": [
            "트로트", "흥 트로트", "발라드 트로트", "효도 트로트",
            "아코디언", "어쿠스틱 기타", "5070 음악",
        ],
        "tone_and_manner": (
            "정겹고 다정하게. 어르신께 말하듯 또박또박, "
            "추억을 함께 떠올리는 친구처럼 자연스럽게."
        ),
        "avoid": [
            "젊은 세대 은어 ('갓생', 'TMI' 등)",
            "강한 마케팅 문구",
            "타 플랫폼 우회 표현",
        ],
        "signature_lines": [
            "오늘도 어머니 생각나는 한 곡, 올려드립니다.",
            "그 시절 봄날을 다시 만나는 시간.",
        ],
        "cta_style": (
            "어르신께 자연스럽게 권하듯. "
            "'마음에 드시면 종 모양 눌러두세요. 매일 한 곡, 빠지지 않고 올립니다.'"
        ),
        "upload_rhythm": "매일 한 곡, 4~6분 길이의 트로트",
    },
}


# ────────────────────────────────────────────────────────────────────────────
# 저장 / 불러오기
# ────────────────────────────────────────────────────────────────────────────
def _default_state() -> dict:
    return {
        "current": "parisian_chanson_cafe",
        "briefs": deepcopy(SEED_BRIEFS),
    }


def load_state() -> dict:
    """전체 상태(현재 선택 + 모든 브리프) 로드. 없으면 시드로 생성."""
    if not BRIEF_PATH.exists():
        state = _default_state()
        save_state(state)
        return state
    try:
        with BRIEF_PATH.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        state = _default_state()
        save_state(state)
        return state

    # 새 시드 키가 추가된 경우 자동 보충 (사용자 편집은 보존)
    state.setdefault("briefs", {})
    for key, seed in SEED_BRIEFS.items():
        if key not in state["briefs"]:
            state["briefs"][key] = deepcopy(seed)
    state.setdefault("current", "parisian_chanson_cafe")
    if state["current"] not in state["briefs"]:
        state["current"] = next(iter(state["briefs"]))
    return state


def save_state(state: dict) -> None:
    BRIEF_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_brief(name: str | None = None) -> dict:
    """현재 선택된 브리프(또는 지정된 브리프) 로드."""
    state = load_state()
    key = name or state["current"]
    return deepcopy(state["briefs"].get(key, next(iter(state["briefs"].values()))))


def save_brief(key: str, brief: dict) -> None:
    state = load_state()
    state["briefs"][key] = brief
    save_state(state)


def set_current(key: str) -> None:
    state = load_state()
    if key in state["briefs"]:
        state["current"] = key
        save_state(state)


def list_briefs() -> list[tuple[str, str]]:
    """[(key, channel_name), ...] 형태로 모든 브리프 나열."""
    state = load_state()
    return [(k, v.get("channel_name", k)) for k, v in state["briefs"].items()]


def create_brief(key: str, channel_name: str, base_key: str | None = None) -> None:
    """새 브리프 추가. base_key가 있으면 그것을 복제, 없으면 빈 템플릿."""
    state = load_state()
    if base_key and base_key in state["briefs"]:
        new = deepcopy(state["briefs"][base_key])
    else:
        new = deepcopy(next(iter(SEED_BRIEFS.values())))
    new["channel_name"] = channel_name
    # 키 중복 시 _2, _3 ... 자동 접미
    base = key
    i = 2
    while key in state["briefs"]:
        key = f"{base}_{i}"
        i += 1
    state["briefs"][key] = new
    state["current"] = key
    save_state(state)


def delete_brief(key: str) -> None:
    state = load_state()
    if len(state["briefs"]) <= 1:
        return  # 마지막 1개 보호
    state["briefs"].pop(key, None)
    if state["current"] == key:
        state["current"] = next(iter(state["briefs"]))
    save_state(state)


# ────────────────────────────────────────────────────────────────────────────
# 프롬프트 블록 — 다른 앱들이 LLM 프롬프트에 그대로 붙여 넣을 수 있도록
# ────────────────────────────────────────────────────────────────────────────
def as_prompt_block(brief: dict | None = None) -> str:
    """브리프를 LLM이 이해하기 쉬운 한국어 프롬프트 블록으로 변환."""
    if brief is None:
        brief = load_brief()

    def _join(items: list) -> str:
        return ", ".join(items) if items else "(없음)"

    return f"""[채널 브랜드 브리프 — 모든 출력은 이 정체성을 따른다]
- 채널명: {brief.get('channel_name', '')}
- 정체성 한 줄: {brief.get('one_line_identity', '')}
- 누가 듣는가(타깃): {brief.get('target_audience', '')}
- 약속(이 채널을 보면 무엇을 얻는가): {brief.get('promise', '')}
- 감정 키워드: {_join(brief.get('emotional_keywords', []))}
- 음악 키워드: {_join(brief.get('music_keywords', []))}
- 톤 앤 매너: {brief.get('tone_and_manner', '')}
- 절대 쓰지 말 것: {_join(brief.get('avoid', []))}
- 시그니처 문구(반복 노출): {_join(brief.get('signature_lines', []))}
- CTA 스타일: {brief.get('cta_style', '')}
- 발행 리듬: {brief.get('upload_rhythm', '')}

[글쓰기 의식의 흐름 — 시청자가 "이 채널을 봐야겠다" 느끼게 만드는 4단 흐름]
1. 첫 줄 갈고리: 시청자가 지금 겪는 감정/상황을 한 문장으로 호명. (예: "오늘 하루도 길었죠.")
2. 그림 한 컷: 채널이 데려갈 장면을 시각·청각·온도로 그려준다.
3. 약속: 이 채널이 매일 무엇을 해줄지 짧게 약속.
4. 초대: 강요 없이 "함께 가요" 톤의 초대. (구독 강요 ❌)
"""


# ────────────────────────────────────────────────────────────────────────────
# CLI 자가검증
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    state = load_state()
    print("[브리프 목록]")
    for k, name in list_briefs():
        cur = " ← 현재" if k == state["current"] else ""
        print(f"  · {k}: {name}{cur}")
    print()
    print(as_prompt_block())
