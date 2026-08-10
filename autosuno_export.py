"""🔗 AutoSuno 내보내기 — 우리 생성물(제목·스타일·가사)을 "망구 AutoSuno" 크롬 확장이
바로 대량 입력받는 포맷으로 변환한다.

AutoSuno(사이드패널) "곡 만들기" 화면은 여러 곡을 한 번에 받는 텍스트/파일 입력을 제공한다.
그 파서(_S)가 인식하는 유일한 계약은 **줄 단위 key 포맷**이다:

    title: <곡 제목>
    styles: <스타일, 콤마 구분 — 한 줄>
    lyrics:
    <가사 여러 줄>

    title: <다음 곡>
    styles: ...
    lyrics:
    ...

파서 규칙(확장 번들 inject/앱에서 역설계):
  - 정규식  ^[ \\t]*(title|styles?|lyrics?)[ \\t]*:[ \\t]*(.*)$   (대소문자 무시)
  - 새 `title:` 줄을 만나면 이전 곡을 확정(flush)하고 새 곡 시작.
  - `styles`(=style/styles) 값은 공백으로 이어붙여 한 줄로 합쳐짐.
  - `lyrics`(=lyric/lyrics) 이후의 줄들은 다음 `title:` 전까지 모두 가사로 수집됨.
    (가사 수집 중에는 styles:/lyrics: 같은 줄도 가사로 취급 — 오직 title: 만 곡을 가른다.)
  - 파일 로더는 .txt/.json/.csv 를 그냥 텍스트로 읽어 같은 파서에 넣는다 → 별도 JSON 스키마 없음.

따라서 이 모듈은 위 포맷의 **평문 텍스트**를 만들어 준다. 사용자는 AutoSuno 에서
"파일 불러오기"(생성된 .txt) 하거나 텍스트박스에 붙여넣은 뒤 "곡 만들기"만 누르면
전 곡이 자동 생성·다운로드된다.

stdlib 만 사용. Streamlit 비의존 → 어떤 생성 앱에서도 import 가능.
"""

from __future__ import annotations

import re

# AutoSuno 파서와 동일한 key 인식 정규식 (round-trip 검증용/방어용)
_KEY_RE = re.compile(r"^[ \t]*(title|styles?|lyrics?)[ \t]*:[ \t]*(.*)$", re.IGNORECASE)


def _one_line(s: str) -> str:
    """styles 는 반드시 한 줄 — 개행/중복 공백을 단일 공백으로 접는다."""
    return " ".join((s or "").split())


def song_block(title: str, styles: str = "", lyrics: str = "") -> str:
    """한 곡을 AutoSuno key 포맷 블록으로 변환."""
    title = _one_line(title) or "(무제)"
    styles = _one_line(styles)
    lyrics = (lyrics or "").strip("\n").rstrip()

    lines = [f"title: {title}"]
    if styles:
        lines.append(f"styles: {styles}")
    lines.append("lyrics:")
    if lyrics:
        lines.append(lyrics)
    return "\n".join(lines)


def _pick(song: dict, *keys: str) -> str:
    for k in keys:
        v = song.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return ""


def to_autosuno_text(songs: list[dict]) -> str:
    """곡 리스트 → AutoSuno 대량 입력 텍스트.

    각 song dict 는 아래 키 중 하나로 필드를 제공하면 된다(우리 여러 앱 호환):
      title  : title | 제목
      styles : styles | style | suno_style | 스타일
      lyrics : lyrics | suno_lyrics | lyrics_text | 가사
    title 이 비면 그 곡은 건너뛴다(파서도 title 없으면 버림).
    """
    blocks: list[str] = []
    for s in songs or []:
        title = _pick(s, "title", "제목")
        if not title.strip():
            continue
        styles = _pick(s, "styles", "style", "suno_style", "스타일")
        lyrics = _pick(s, "lyrics", "suno_lyrics", "lyrics_text", "가사")
        blocks.append(song_block(title, styles, lyrics))
    return ("\n\n".join(blocks) + "\n") if blocks else ""


def parse_autosuno_text(text: str) -> list[dict]:
    """AutoSuno 파서(_S)의 파이썬 포팅 — 왕복 검증 및 사용자 붙여넣기 미리보기용.

    반환: [{"title", "styles", "lyrics"}, ...]
    """
    songs: list[dict] = []
    cur: dict | None = None
    field: str | None = None

    def flush() -> None:
        nonlocal cur, field
        if not cur:
            return
        title = " ".join(" ".join(cur["title"]).split()).strip()
        styles = " ".join(" ".join(cur["styles"]).split()).strip()
        lyrics = "\n".join(cur["lyrics"]).strip()
        if title:
            songs.append({"title": title, "styles": styles, "lyrics": lyrics})
        cur = None
        field = None

    for line in (text or "").split("\n"):
        m = _KEY_RE.match(line)
        # 가사 수집 중에는 title: 만 새 key 로 인정 (styles:/lyrics: 는 가사로 흡수)
        if m and (field != "lyrics" or m.group(1).lower() == "title"):
            key = m.group(1).lower()
            val = m.group(2)
            if key == "title":
                flush()
                cur = {"title": [], "styles": [], "lyrics": []}
                field = "title"
                if val:
                    cur["title"].append(val)
            elif key.startswith("style"):
                cur = cur or {"title": [], "styles": [], "lyrics": []}
                field = "styles"
                if val:
                    cur["styles"].append(val)
            else:  # lyric(s)
                cur = cur or {"title": [], "styles": [], "lyrics": []}
                field = "lyrics"
                if val:
                    cur["lyrics"].append(val)
            continue
        if not cur or not field:
            continue
        cur[field].append(line)
    flush()
    return songs


DEFAULT_FILENAME = "AutoSuno_곡목록.txt"


def _selftest() -> None:
    songs = [
        {
            "title": "엄마의 봄",
            "suno_style": "warm trot, soft acoustic, sung in Korean",
            "suno_lyrics": "[Verse 1]\n(soft piano)\n봄바람이 불어오면\n엄마 생각이 나요\n\n[Chorus]\n고향의 봄이 그리워",
        },
        {
            "title": "  새벽 드라이브  ",
            "style": "synthwave,\n retro 80s,  neon",  # 개행/중복공백 → 한 줄로 접혀야
            "lyrics": "텅 빈 고속도로 위\n네온이 흐르고",
        },
        {"title": "", "styles": "무시됨", "lyrics": "제목 없어 버려짐"},  # title 없음 → skip
    ]
    text = to_autosuno_text(songs)
    print("=== 생성 텍스트 ===")
    print(text)

    back = parse_autosuno_text(text)
    assert len(back) == 2, f"곡 수 불일치: {len(back)}"
    assert back[0]["title"] == "엄마의 봄"
    assert back[0]["styles"] == "warm trot, soft acoustic, sung in Korean"
    assert "봄바람이 불어오면" in back[0]["lyrics"]
    assert "[Chorus]" in back[0]["lyrics"]
    assert back[1]["title"] == "새벽 드라이브"  # 앞뒤 공백 정리
    assert back[1]["styles"] == "synthwave, retro 80s, neon"  # 개행 접힘
    assert back[1]["lyrics"] == "텅 빈 고속도로 위\n네온이 흐르고"

    # 왕복 안정성: 재생성해도 동일
    assert to_autosuno_text(back) == text, "round-trip 불일치"
    print("✅ autosuno_export self-test 통과 (곡 2개, 왕복 일치)")


if __name__ == "__main__":
    _selftest()
