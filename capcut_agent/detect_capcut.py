"""CapCut 드래프트 환경 진단 (사용자 머신에서 실행).

목적: 제(클라우드)가 볼 수 없는 사용자 PC 의 실제 CapCut 드래프트 구조를 확인한다.
- 드래프트 루트 후보를 찾고
- 각 드래프트의 draft_content.json 위치를 검사해 레이아웃을 판정한다
    · flat        : <draft>/draft_content.json          (pycapcut 호환)
    · timelines   : <draft>/Timelines/<GUID>/draft_content.json (신버전, 별도 처리 필요)
출력 결과를 그대로 붙여주시면 빌더를 그 레이아웃에 맞춥니다.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from typing import List, Optional


def candidate_roots() -> List[str]:
    roots: List[str] = []
    env = os.environ.get("CAPCUT_DRAFT_DIR")
    if env:
        roots.append(env)
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA", "")
        roots += [
            os.path.join(local, "CapCut", "User Data", "Projects", "com.lveditor.draft"),
            os.path.join(local, "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
            r"C:\ex\CapCut Drafts",
        ]
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        roots += [
            os.path.join(home, "Movies", "CapCut", "User Data", "Projects", "com.lveditor.draft"),
            os.path.join(home, "Movies", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        ]
    return [r for r in roots if r]


def classify_draft(draft_dir: str) -> Optional[str]:
    if os.path.isfile(os.path.join(draft_dir, "draft_content.json")):
        return "flat"
    if glob.glob(os.path.join(draft_dir, "Timelines", "*", "draft_content.json")):
        return "timelines"
    # 일부 버전은 draft_info.json 사용
    if os.path.isfile(os.path.join(draft_dir, "draft_info.json")):
        return "flat(draft_info)"
    return None


def read_capcut_version() -> Optional[str]:
    if not sys.platform.startswith("win"):
        return None
    local = os.environ.get("LOCALAPPDATA", "")
    base = os.path.join(local, "CapCut", "Apps")
    if not os.path.isdir(base):
        return None
    vers = [d for d in os.listdir(base) if d[0:1].isdigit()]
    return ", ".join(sorted(vers)) or None


def main() -> None:
    print(f"플랫폼: {sys.platform}")
    ver = read_capcut_version()
    if ver:
        print(f"CapCut 버전(Apps): {ver}")
    roots = candidate_roots()
    found_any = False
    for root in roots:
        exists = os.path.isdir(root)
        print(f"\n[루트] {root}  {'존재' if exists else '없음'}")
        if not exists:
            continue
        found_any = True
        drafts = [
            d for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
        ]
        if not drafts:
            print("  (드래프트 없음)")
        for d in sorted(drafts)[:15]:
            ddir = os.path.join(root, d)
            layout = classify_draft(ddir) or "?(draft_content.json 못 찾음)"
            print(f"  - {d}: {layout}")
    if not found_any:
        print(
            "\n⚠️ CapCut 드래프트 루트를 못 찾았습니다. CapCut 을 한 번 실행해 드래프트를 "
            "만들거나, 환경변수 CAPCUT_DRAFT_DIR 로 경로를 지정하세요."
        )


if __name__ == "__main__":
    main()
