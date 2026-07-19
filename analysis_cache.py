"""analysis_cache.py — 분석 결과 디스크 캐시.

Streamlit session_state 는 새로고침(F5)하면 사라져 같은 분석을 다시 돌려야 한다.
결과(구간분석·패턴분석·자동분류·생성 세트/이미지)를 로컬 JSON 에 저장해두면
새로고침해도 그대로 복원 → 재실행 시간·API 낭비 방지.

`analysis_cache.json` 은 gitignore. 키-값 저장(키=session_state 키).
"""
from __future__ import annotations

import json
import os

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_cache.json")


def load_all() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_all(data: dict) -> None:
    try:                                # 원자적 저장(쓰기 중단돼도 안 깨지게)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def set(key: str, value) -> None:      # noqa: A003
    data = load_all()
    data[key] = value
    _save_all(data)


def get(key: str, default=None):
    return load_all().get(key, default)


def delete(key: str) -> None:
    data = load_all()
    if key in data:
        del data[key]
        _save_all(data)
