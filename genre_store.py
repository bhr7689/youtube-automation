"""genre_store.py — 장르(=채널 프로젝트) 저장소.

여러 장르 채널을 새로 개설하는 게 목적. 장르마다 독립된 프로젝트:
- benchmarks: 벤치마킹 링크(채널/영상) + 🔖북마크 + 🔔알림 토글
- basket: 🧺 레퍼런스 바구니 {썸네일 이미지 + 제목 + 출처 + 메모}
- identity: 채널 정체성 브리프(색·폰트·문구 톤)

`thumb_title_lab.json` 은 gitignore — 사장님 로컬 편집 보존.
코드 안 SEED_PROJECTS 로 최초 시드(분류한 채널). 새 시드는 기존 편집 보존하며 보충.
"""
from __future__ import annotations

import json
import os
import re

STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "thumb_title_lab.json")

FOCUS_BUCKET = "⭐ 집중 벤치마킹"

# 분류 완료된 채널로 장르 프로젝트 시드 (인벤토리 기반)
SEED_PROJECTS: dict[str, dict] = {
    FOCUS_BUCKET: {
        "note": "지금 집중 벤치마킹할 채널만 모음. 🔔알림 + 썸네일·제목 분석 → 내 채널 적용.",
        "benchmarks": [],
    },
    "파리샹송 (프렌치팝)": {
        "note": "🗼 주력 후보. 스텔라장·라따뚜이·에펠탑·프렌치팝. 여자 보컬 경쾌 재즈풍 피아노.",
        "benchmarks": ["https://www.youtube.com/@oaplaylist", "https://www.youtube.com/@Jayurhy",
                       "https://www.youtube.com/@OOOffi", "https://www.youtube.com/@JazzRecording"],
    },
    "재즈·카페 BGM": {
        "note": "cozy jazz. 야경·카페·창가 무드, 딥톤 색보정.",
        "benchmarks": ["https://www.youtube.com/@Mysig.Sounds", "https://www.youtube.com/@maruko_jazz",
                       "https://www.youtube.com/@groove_salon", "https://www.youtube.com/@AmberBrewJazz",
                       "https://www.youtube.com/@EMMAJAZZRADIO"],
    },
    "보사노바·여름 카페": {
        "note": "☀️ 일본/도쿄 여름 키워드 장악. 비비드 여름 무드.",
        "benchmarks": ["https://www.youtube.com/@CozyBossaCafeMelodies",
                       "https://www.youtube.com/@played_for_you"],
    },
    "감성 / Lofi": {
        "note": "⭐ @meloenvy = 제목·썸네일 우리 채널 레퍼런스.",
        "benchmarks": ["https://www.youtube.com/@meloenvy", "https://www.youtube.com/@UnwindLofiRoom"],
    },
    "클래식": {
        "note": "일본 정통 피아노·클래식. 잔잔·서정.",
        "benchmarks": [],
    },
    "🙏 종교 (CCM·불교)": {
        "note": "기독교 CCM 찬양·워십 + 불교 음악·찬불가·명상. 종교 음악 채널.",
        "benchmarks": [
            "https://www.youtube.com/@CCMCOMPANY",
            "https://www.youtube.com/channel/UCfuQHdNwJTa_E1ExHoEUwTw",
            "https://www.youtube.com/channel/UC0e2fHWBwjXxxzI6g7jxhuA",
            "https://www.youtube.com/channel/UCdmrs7ze65mn8po3lOw_scw",
            "https://www.youtube.com/channel/UCT32yJHkouI8pecc0KJgd9A",
            "https://www.youtube.com/channel/UCSpcGjm85BCFUk7oo84OS-g",
        ],
    },
}


def _blank_benchmark(url: str) -> dict:
    return {"url": url.strip(), "bookmark": False, "alarm": False, "channel_id": "", "note": ""}


def _load_raw() -> dict:
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_state() -> dict:
    """저장본 + 시드 병합. 저장본 우선(편집 보존), 새 시드 프로젝트만 보충."""
    data = _load_raw()
    projects = dict(data.get("projects", {}))
    for name, seed in SEED_PROJECTS.items():
        if name not in projects:
            projects[name] = {
                "note": seed["note"],
                "benchmarks": [_blank_benchmark(u) for u in seed["benchmarks"]],
                "basket": [], "identity": {},
            }
    for p in projects.values():         # 스키마 보정
        p.setdefault("note", ""); p.setdefault("benchmarks", [])
        p.setdefault("basket", []); p.setdefault("identity", {})
    current = data.get("current") or next(iter(projects), "")
    if current not in projects:
        current = next(iter(projects), "")
    return {"projects": projects, "current": current}


def save_state(state: dict) -> None:
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── 프로젝트(장르) ────────────────────────────────────────────
def list_projects() -> list[str]:
    return list(load_state()["projects"].keys())


def current_project() -> str:
    return load_state()["current"]


def set_current(name: str) -> dict:
    st = load_state()
    if name in st["projects"]:
        st["current"] = name
        save_state(st)
    return st


def add_project(name: str, note: str = "") -> dict:
    name = (name or "").strip()
    st = load_state()
    if name and name not in st["projects"]:
        st["projects"][name] = {"note": note.strip(), "benchmarks": [], "basket": [], "identity": {}}
        st["current"] = name
        save_state(st)
    return st


def delete_project(name: str) -> dict:
    st = load_state()
    if name in st["projects"] and len(st["projects"]) > 1:
        del st["projects"][name]
        if st["current"] == name:
            st["current"] = next(iter(st["projects"]), "")
        save_state(st)
    return st


def set_note(name: str, note: str) -> dict:
    st = load_state()
    if name in st["projects"]:
        st["projects"][name]["note"] = (note or "").strip()
        save_state(st)
    return st


# ── 벤치마킹 링크 ─────────────────────────────────────────────
def _split_urls(text: str) -> list[str]:
    return [u.strip() for u in re.split(r"[\s,]+", text or "") if u.strip()]


def add_benchmarks(name: str, text_or_list) -> dict:
    st = load_state()
    p = st["projects"].get(name)
    if p is None:
        return st
    existing = {b["url"] for b in p["benchmarks"]}
    items = text_or_list if isinstance(text_or_list, list) else _split_urls(text_or_list)
    for u in items:
        u = u.strip()
        if u and u not in existing:
            p["benchmarks"].append(_blank_benchmark(u))
            existing.add(u)
    save_state(st)
    return st


def remove_benchmark(name: str, url: str) -> dict:
    st = load_state()
    p = st["projects"].get(name)
    if p:
        p["benchmarks"] = [b for b in p["benchmarks"] if b["url"] != url]
        save_state(st)
    return st


def toggle_flag(name: str, url: str, flag: str, value: bool | None = None) -> dict:
    """flag = 'bookmark' | 'alarm'. 알림 ON 은 자동으로 북마크도 ON."""
    st = load_state()
    p = st["projects"].get(name)
    if p:
        for b in p["benchmarks"]:
            if b["url"] == url:
                b[flag] = (not b.get(flag, False)) if value is None else bool(value)
                if flag == "alarm" and b["alarm"]:
                    b["bookmark"] = True
                if flag == "bookmark" and not b["bookmark"]:
                    b["alarm"] = False   # 북마크 해제 시 알림도 해제
                break
        save_state(st)
    return st


def watch_list() -> list[dict]:
    """전 프로젝트에서 알림 ON 인 채널들 (watcher cron 대상)."""
    st = load_state()
    out = []
    for pname, p in st["projects"].items():
        for b in p["benchmarks"]:
            if b.get("alarm"):
                out.append({"project": pname, **b})
    return out


WATCH_EXPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "watch_channels.json")


def export_watch_channels(path: str = WATCH_EXPORT_PATH) -> int:
    """알림 ON 목록을 커밋 가능한 파일로 내보냄 (GitHub Actions cron 이 읽음).
    로컬 상태(thumb_title_lab.json)는 gitignore 라 Actions 가 못 보므로 이게 다리."""
    wl = [{"project": w["project"], "url": w["url"], "channel_id": w.get("channel_id", "")}
          for w in watch_list()]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"channels": wl}, f, ensure_ascii=False, indent=2)
    return len(wl)


def load_exported_watch(path: str = WATCH_EXPORT_PATH) -> list[dict]:
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8")).get("channels", [])
        except (json.JSONDecodeError, OSError):
            pass
    return []


# ── 레퍼런스 바구니 ───────────────────────────────────────────
def add_to_basket(name: str, thumb: str, title: str = "", source: str = "", note: str = "") -> dict:
    st = load_state()
    p = st["projects"].get(name)
    if p is not None:
        key = (thumb or "") + "|" + (title or "")
        if not any((b.get("thumb", "") + "|" + b.get("title", "")) == key for b in p["basket"]):
            p["basket"].append({"thumb": thumb, "title": title, "source": source, "note": note})
            save_state(st)
    return st


def remove_from_basket(name: str, index: int) -> dict:
    st = load_state()
    p = st["projects"].get(name)
    if p and 0 <= index < len(p["basket"]):
        p["basket"].pop(index)
        save_state(st)
    return st


def get_basket(name: str) -> list[dict]:
    return load_state()["projects"].get(name, {}).get("basket", [])


# ── 채널 정체성(장르 공식 프롬프트) ───────────────────────────
def set_identity(name: str, identity: dict) -> dict:
    st = load_state()
    if name in st["projects"]:
        st["projects"][name]["identity"] = identity
        save_state(st)
    return st


def get_identity(name: str) -> dict:
    return load_state()["projects"].get(name, {}).get("identity", {})


def set_signature(name: str, text: str) -> dict:
    """우리 채널만의 '결'(색·아트스타일·모티프·톤·차별점). 복제 방지용."""
    st = load_state()
    if name in st["projects"]:
        st["projects"][name].setdefault("identity", {})["signature"] = (text or "").strip()
        save_state(st)
    return st
