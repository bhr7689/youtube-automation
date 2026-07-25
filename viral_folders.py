"""viral_folders.py — 📁 감성 폴더 (컬렉션).

일본 쇼츠 앱의 컬렉션/북마크 방식을 1만+ 연구소에 이식.
비슷한 감성끼리 폴더로 저장하고, **폴더 안에서 썸네일·제목의 공통점·유사도**를 분석한다.

- 저장소: viral_folders.json (gitignore — 사장님이 만든 폴더는 이 PC 에 보존)
- 폴더 = {id, name, vibe, videos(스냅샷), created, updated}
- 자동 제안: viral_lab.cluster_by_style 로 비슷한 감성 묶음을 폴더 후보로
- 공통점 분석: 제목 승리공식 + 키워드 + 유사도(%) + 공통 단어 (썸네일 공통점은 앱에서 👁Vision)

Streamlit 비의존 · 헤드리스 테스트 가능.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from itertools import combinations

import tier_lab as T
import viral_lab as V

_HERE = os.path.dirname(os.path.abspath(__file__))
FOLDERS_PATH = os.path.join(_HERE, "viral_folders.json")


# ── 저장소 ───────────────────────────────────────────────────
def _load() -> dict:
    if not os.path.exists(FOLDERS_PATH):
        return {"folders": []}
    try:
        with open(FOLDERS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("folders"), list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {"folders": []}


def _save(store: dict) -> None:
    with open(FOLDERS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def _slug(name: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", (name or "").strip()).strip("-").lower()
    return s or "folder"


def list_folders() -> list[dict]:
    """폴더 목록(최근 갱신 순). 각 폴더에 size 부가."""
    fs = _load()["folders"]
    for f in fs:
        f["size"] = len(f.get("videos", []))
    return sorted(fs, key=lambda f: f.get("updated", ""), reverse=True)


def get_folder(fid: str) -> dict | None:
    return next((f for f in _load()["folders"] if f.get("id") == fid), None)


def _uniq_id(store: dict, base: str) -> str:
    ids = {f["id"] for f in store["folders"]}
    fid, n = base, 2
    while fid in ids:
        fid, n = f"{base}-{n}", n + 1
    return fid


def create_folder(name: str, videos: list[dict] | None = None, vibe: str = "") -> dict:
    store = _load()
    now = _dt.datetime.now().isoformat(timespec="seconds")
    fid = _uniq_id(store, _slug(name))
    vids = _dedup([V.normalize(v) for v in (videos or [])])
    folder = {"id": fid, "name": name.strip() or fid, "vibe": vibe,
              "videos": vids, "created": now, "updated": now}
    store["folders"].append(folder)
    _save(store)
    return folder


def _dedup(videos: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for v in videos:
        vid = v.get("video_id") or (v.get("title", "")[:24] + str(v.get("views", "")))
        by_id[vid] = v
    return sorted(by_id.values(), key=lambda v: v.get("views", 0), reverse=True)


def add_to_folder(fid: str, videos: list[dict]) -> dict | None:
    store = _load()
    f = next((x for x in store["folders"] if x["id"] == fid), None)
    if not f:
        return None
    merged = f.get("videos", []) + [V.normalize(v) for v in (videos or [])]
    f["videos"] = _dedup(merged)
    f["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    _save(store)
    return f


def remove_from_folder(fid: str, video_id: str) -> dict | None:
    store = _load()
    f = next((x for x in store["folders"] if x["id"] == fid), None)
    if not f:
        return None
    f["videos"] = [v for v in f.get("videos", []) if v.get("video_id") != video_id]
    f["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    _save(store)
    return f


def rename_folder(fid: str, name: str) -> dict | None:
    store = _load()
    f = next((x for x in store["folders"] if x["id"] == fid), None)
    if not f:
        return None
    f["name"] = name.strip() or f["name"]
    f["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    _save(store)
    return f


def delete_folder(fid: str) -> bool:
    store = _load()
    before = len(store["folders"])
    store["folders"] = [f for f in store["folders"] if f["id"] != fid]
    _save(store)
    return len(store["folders"]) < before


# ── 자동 제안 (비슷한 감성끼리) ──────────────────────────────
def suggest_folders(videos: list[dict], min_size: int = 2) -> list[dict]:
    """현재 표본을 감성(풍)끼리 자동으로 나눠 폴더 후보로 제안.

    반환: [{name, vibe, videos, size, formula}]  (2개 이상 묶음 우선)
    """
    out = []
    for c in V.cluster_by_style(videos):
        if c["size"] < min_size:
            continue
        out.append({"name": c["label"], "vibe": c["label"], "videos": c["videos"],
                    "size": c["size"], "formula": c["formula"]})
    return out


# ── 폴더 안 공통점·유사도 분석 ───────────────────────────────
_STOP = {w.lower() for w in T.GENRE_WORDS} | {"플레이리스트", "playlist", "모음",
                                              "mix", "믹스", "베스트"}


def _title_tokens(title: str) -> set[str]:
    return {t.lower() for t in T.tokenize(title) if t.lower() not in _STOP}


def similarity_pct(videos: list[dict]) -> int:
    """폴더 안 제목들의 평균 쌍별 유사도(자카드) → 0~100%."""
    toks = [_title_tokens(v.get("title", "")) for v in videos]
    toks = [t for t in toks if t]
    if len(toks) < 2:
        return 0
    sims = []
    for a, b in combinations(toks, 2):
        u = len(a | b)
        sims.append(len(a & b) / u if u else 0)
    return round(100 * sum(sims) / len(sims)) if sims else 0


def common_words(videos: list[dict], min_ratio: float = 0.4) -> list[tuple[str, int]]:
    """폴더 안 제목의 일정 비율 이상에서 반복되는 공통 단어."""
    from collections import Counter
    n = len(videos)
    if not n:
        return []
    cnt: Counter = Counter()
    for v in videos:
        cnt.update(_title_tokens(v.get("title", "")))
    need = max(2, round(n * min_ratio))
    return [(w, c) for w, c in cnt.most_common(20) if c >= need]


def folder_common(folder: dict) -> dict:
    """폴더 안 썸네일·제목의 공통점 종합(제목 공식 + 키워드 + 유사도 + 공통단어)."""
    hits = V.filter_hits(folder.get("videos", []))
    ana = V.analyze_hits(hits)
    return {
        "n": ana["n"],
        "formula": ana["formula"],
        "keywords": V.keyword_summary(ana["agg"]),
        "similarity": similarity_pct(hits),
        "common_words": common_words(hits),
        "top": ana["top"],
        "median_views": ana["median_views"],
    }


if __name__ == "__main__":  # 자기검증 (임시 파일)
    import tempfile
    FOLDERS_PATH = os.path.join(tempfile.gettempdir(), "vf_selftest.json")
    if os.path.exists(FOLDERS_PATH):
        os.remove(FOLDERS_PATH)
    vids = [
        {"video_id": "1", "title": "새벽 감성 재즈 플레이리스트 🌙", "views": 52000},
        {"video_id": "2", "title": "새벽 감성 재즈 라디오", "views": 30000},
        {"video_id": "3", "title": "비 오는 날 카페 보사노바", "views": 120000},
    ]
    sug = suggest_folders(vids)
    assert any("재즈" in s["name"] for s in sug), sug
    f = create_folder("새벽 재즈", [v for v in vids if "재즈" in v["title"]], vibe="새벽·재즈")
    assert len(get_folder(f["id"])["videos"]) == 2
    cm = folder_common(f)
    assert cm["n"] == 2 and cm["similarity"] > 0, cm
    assert any(w == "새벽" for w, _ in cm["common_words"]), cm["common_words"]
    add_to_folder(f["id"], [{"video_id": "9", "title": "새벽 감성 재즈 모음", "views": 15000}])
    assert len(get_folder(f["id"])["videos"]) == 3
    assert delete_folder(f["id"])
    print("suggest:", [(s["name"], s["size"]) for s in sug])
    print("공통단어:", cm["common_words"], "| 유사도:", cm["similarity"], "%")
    print("self-test OK")
