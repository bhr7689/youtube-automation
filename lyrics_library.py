"""작사가 프롬프트 도서관 — 장르별 가사 + 작사 패턴 + writer_prompt 저장소.

recipes.py 가 Suno 곡 프롬프트의 자산이라면, 이쪽은 **작사가 프롬프트의 자산**.
파일을 분리해 두 자산이 섞이지 않도록 한다(lyrics_library.json).

Streamlit 비의존 — 헤드리스 호출 가능.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

LIBRARY_PATH = Path(__file__).parent / "lyrics_library.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"lyr_{int(time.time() * 1000)}_{random.randint(100, 999)}"


def load(path: str | Path = LIBRARY_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {"entries": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": []}
    data.setdefault("entries", [])
    return data


def _write(data: dict, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_entry(
    *,
    name: str,
    genre: str,
    lyrics_text: str,
    patterns: dict[str, list[str]] | None = None,
    writer_prompt: str = "",
    summary: str = "",
    rationale: str = "",
    transcript_source: str = "",
    source_video_id: str | None = None,
    source_url: str = "",
    notes: str = "",
    path: str | Path = LIBRARY_PATH,
) -> dict:
    data = load(path)
    entry = {
        "id": _new_id(),
        "name": (name or "").strip() or "이름없는 가사",
        "genre": (genre or "").strip(),
        "lyrics_text": (lyrics_text or "").strip(),
        "summary": (summary or "").strip(),
        "patterns": {k: list(v) for k, v in (patterns or {}).items() if v},
        "writer_prompt": (writer_prompt or "").strip(),
        "rationale": (rationale or "").strip(),
        "transcript_source": (transcript_source or "").strip(),
        "source_video_id": source_video_id,
        "source_url": (source_url or "").strip(),
        "notes": (notes or "").strip(),
        "created_at": _now_iso(),
    }
    data["entries"].append(entry)
    _write(data, path)
    return entry


def list_entries(path: str | Path = LIBRARY_PATH) -> list[dict]:
    return load(path)["entries"]


def get_entry(entry_id: str, path: str | Path = LIBRARY_PATH) -> dict | None:
    for e in load(path)["entries"]:
        if e["id"] == entry_id:
            return e
    return None


def delete_entry(entry_id: str, path: str | Path = LIBRARY_PATH) -> bool:
    data = load(path)
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]
    if len(data["entries"]) != before:
        _write(data, path)
        return True
    return False


def update_entry(
    entry_id: str, *, path: str | Path = LIBRARY_PATH, **fields,
) -> dict | None:
    """알려진 필드만 부분 수정. 전체 덮어쓰기 방지."""
    allowed = {
        "name", "genre", "notes", "writer_prompt", "summary",
        "lyrics_text", "source_url",
    }
    data = load(path)
    for e in data["entries"]:
        if e["id"] == entry_id:
            for k, v in fields.items():
                if k in allowed:
                    e[k] = v
            _write(data, path)
            return e
    return None


def distinct_genres(path: str | Path = LIBRARY_PATH) -> list[str]:
    seen = {(e.get("genre") or "").strip() for e in load(path)["entries"]}
    return sorted(g for g in seen if g)


def merged_writer_prompt(genre: str, *, path: str | Path = LIBRARY_PATH) -> str:
    """한 장르의 모든 entry writer_prompt 를 묶어 '메타 프롬프트' 생성.

    같은 장르 안의 다양한 곡들 스타일을 한 페르소나로 합쳐 보여줘서,
    AI 작사가에게 통째로 줄 수 있게 한다.
    """
    entries = [e for e in load(path)["entries"]
               if (e.get("genre") or "").strip() == genre.strip()]
    if not entries:
        return ""
    lines = [
        f"# {genre} 작사가 페르소나 (참고 곡 {len(entries)}개 종합)",
        "",
        "## 공통 화법·패턴",
    ]
    seen: set[str] = set()
    bullets: list[str] = []
    for e in entries:
        for dim, vals in (e.get("patterns") or {}).items():
            for v in vals:
                key = f"{dim}:{v}"
                if key not in seen:
                    seen.add(key)
                    bullets.append(f"- [{dim}] {v}")
    lines.extend(bullets[:50])  # 너무 길어지지 않게 50개로 제한
    lines.append("")
    lines.append("## 참고 곡 페르소나 (각 곡별 작사 지시문)")
    for e in entries:
        wp = (e.get("writer_prompt") or "").strip()
        if not wp:
            continue
        lines.append(f"\n### {e.get('name','')}")
        lines.append(wp)
    return "\n".join(lines)


if __name__ == "__main__":
    tmp = Path("/tmp/_lyr_demo.json")
    tmp.unlink(missing_ok=True)
    save_entry(
        name="엄마생각", genre="트로트",
        lyrics_text="엄마가 보고싶어 눈을 감으면...",
        patterns={"tone": ["회상", "그리움"], "themes": ["어머니"]},
        writer_prompt="당신은 회상·그리움 톤의 트로트 작사가입니다.",
        summary="회상·그리움 1인칭",
        path=tmp,
    )
    save_entry(
        name="고향길", genre="트로트",
        lyrics_text="굽이굽이 산길 따라 고향가는 길...",
        patterns={"tone": ["향수"], "themes": ["고향", "여정"]},
        writer_prompt="당신은 향수·여정 톤의 트로트 작사가입니다.",
        path=tmp,
    )
    print("genres:", distinct_genres(path=tmp))
    print()
    print(merged_writer_prompt("트로트", path=tmp))
    tmp.unlink(missing_ok=True)
