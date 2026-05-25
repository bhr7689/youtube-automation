"""레시피 저장소 — '나만의 자산' 레이어.

스튜디오에서 만든 조합(picks)에 이름을 붙여 recipes.json 에 저장하고, 여러
레시피를 섞어(블렌딩) 새 조합을 만든다. Streamlit 의존성이 없어 헤드리스로
테스트/호출 가능. 향후 역설계 분석기가 추출한 picks 도 source_video_id 와 함께
같은 형식으로 적재하면 그대로 자산이 된다.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

RECIPES_PATH = Path(__file__).parent / "recipes.json"

# 한 곡에 보통 하나만 어울리는 단일선택 차원 (블렌딩 시 충돌 방지).
SINGLE_DIMS = {"mood", "vocal_gender", "vocal_ensemble", "vocal_register"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_recipes(path: str | Path = RECIPES_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {"recipes": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"recipes": []}
    data.setdefault("recipes", [])
    return data


def _write(data: dict, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _new_id() -> str:
    return f"rcp_{int(time.time() * 1000)}_{random.randint(100, 999)}"


def save_recipe(
    name: str,
    preset: str,
    picks: dict[str, list[str]],
    *,
    bpm: int | None = None,
    hook: str = "",
    source_video_id: str | None = None,
    notes: str = "",
    path: str | Path = RECIPES_PATH,
) -> dict:
    """현재 조합을 레시피로 저장(append). 같은 이름이 있으면 새 버전으로 함께 보관."""
    data = load_recipes(path)
    clean_picks = {k: list(v) for k, v in picks.items() if not k.startswith("_") and v}
    recipe = {
        "id": _new_id(),
        "name": name.strip() or "이름없는 레시피",
        "preset": preset,
        "picks": clean_picks,
        "bpm": int(bpm) if bpm else None,
        "hook": hook.strip(),
        "source_video_id": source_video_id,
        "notes": notes.strip(),
        "created_at": _now_iso(),
    }
    data["recipes"].append(recipe)
    _write(data, path)
    return recipe


def list_recipes(path: str | Path = RECIPES_PATH) -> list[dict]:
    return load_recipes(path)["recipes"]


def get_recipe(recipe_id: str, path: str | Path = RECIPES_PATH) -> dict | None:
    for r in load_recipes(path)["recipes"]:
        if r["id"] == recipe_id:
            return r
    return None


def delete_recipe(recipe_id: str, path: str | Path = RECIPES_PATH) -> bool:
    data = load_recipes(path)
    before = len(data["recipes"])
    data["recipes"] = [r for r in data["recipes"] if r["id"] != recipe_id]
    if len(data["recipes"]) != before:
        _write(data, path)
        return True
    return False


def blend_recipes(
    recipes: list[dict],
    *,
    preset: str | None = None,
    per_dim_cap: int = 3,
    seed: int | None = None,
) -> tuple[str, dict[str, list[str]]]:
    """여러 레시피를 섞어 새 조합(picks)을 만든다.

    - 단일선택 차원(무드/성별/편성/음색)은 후보 중 하나만 선택(충돌 방지).
    - 다중 차원(악기/솔로/기교 등)은 합집합 후 per_dim_cap 개로 제한.
    - BPM 은 평균. preset 은 지정값 또는 첫 레시피 것.
    """
    if not recipes:
        raise ValueError("블렌딩할 레시피가 없습니다.")
    rng = random.Random(seed)
    preset = preset or recipes[0]["preset"]

    all_dims: set[str] = set()
    for r in recipes:
        all_dims.update(r.get("picks", {}).keys())

    merged: dict[str, list[str]] = {}
    for dim in all_dims:
        pool: list[str] = []
        for r in recipes:
            pool.extend(r.get("picks", {}).get(dim, []))
        seen: set[str] = set()
        uniq = [x for x in pool if not (x in seen or seen.add(x))]
        if not uniq:
            continue
        if dim in SINGLE_DIMS:
            merged[dim] = [rng.choice(uniq)]
        elif per_dim_cap and len(uniq) > per_dim_cap:
            merged[dim] = rng.sample(uniq, per_dim_cap)
        else:
            merged[dim] = uniq

    bpms = [int(r["bpm"]) for r in recipes if r.get("bpm")]
    if bpms:
        merged["_bpm"] = [str(round(sum(bpms) / len(bpms)))]
    return preset, merged


if __name__ == "__main__":
    # 헤드리스 데모 (임시 파일).
    tmp = Path("/tmp/_recipes_demo.json")
    tmp.unlink(missing_ok=True)

    save_recipe(
        "눈물 트로트", "kr_trot",
        {"mood": ["tearful, emotional, heartfelt"], "solo": ["saxophone solo"],
         "vocal_gender": ["male vocal"], "vocal_register": ["deep low baritone, rich chest voice"]},
        bpm=70, path=tmp,
    )
    save_recipe(
        "흥 트로트", "kr_trot",
        {"mood": ["festive, joyful, celebratory"], "instruments": ["janggu", "synth brass stabs"],
         "vocal_gender": ["female vocal"], "vocal_technique": ["emotional belting"]},
        bpm=122, path=tmp,
    )
    rs = list_recipes(tmp)
    print("저장된 레시피:", [r["name"] for r in rs])
    preset, blended = blend_recipes(rs, seed=3)
    print("블렌딩 결과 picks:", json.dumps(blended, ensure_ascii=False))
    tmp.unlink(missing_ok=True)
