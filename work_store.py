"""🔄 작업 공유 저장소 — 여러 PC에서 '무슨 작업을 했는지'를 git 으로 자동 동기화.

설계(비개발자·다중 PC·충돌 방지):
- 작업 1건 = **고유 이름의 개별 JSON 파일**(shared_work/<ts>_<rand>.json). 파일명이 겹치지
  않으므로 두 PC 가 동시에 만들어도 git 이 내용 충돌 없이 자동 병합.
- git 대상은 **shared_work/ 폴더만**(코드·키·DB 는 절대 안 건드림). `git add shared_work` 만 사용.
- 동기화 = commit(로컬 새 작업) → pull(다른 PC 작업 받기) → push. 오프라인이면 조용히 실패(로컬은 유지).

각 작업엔 machine(PC 이름)·시각이 붙어 "언제 어느 PC 에서 무슨 작업" 이 한눈에 보인다.
stdlib 만 사용.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK_DIR = ROOT / "shared_work"


def machine_name() -> str:
    return os.environ.get("WORK_MACHINE", "").strip() or socket.gethostname() or "PC"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def save_work(kind: str, title: str, payload: dict | None = None,
              summary: str = "") -> dict:
    """작업 1건을 개별 파일로 저장 → 그 레코드 반환."""
    WORK_DIR.mkdir(exist_ok=True)
    wid = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    rec = {
        "id": wid, "kind": kind, "title": (title or "")[:200],
        "summary": (summary or "")[:400],
        "machine": machine_name(), "ts": _now_iso(),
        "payload": payload or {},
    }
    (WORK_DIR / f"{wid}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def list_work(limit: int = 200, kind: str | None = None) -> list[dict]:
    """저장된 작업(다른 PC 것 포함) 최신순."""
    if not WORK_DIR.exists():
        return []
    out = []
    for f in WORK_DIR.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if kind and rec.get("kind") != kind:
            continue
        # payload 는 목록에서 제외(가벼운 목록) — 상세는 get_work
        out.append({k: v for k, v in rec.items() if k != "payload"})
    out.sort(key=lambda r: r.get("id", ""), reverse=True)
    return out[:limit]


def get_work(wid: str) -> dict | None:
    if any(c in wid for c in ("/", "\\", "..")):
        return None
    f = WORK_DIR / f"{wid}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_work(wid: str) -> bool:
    if any(c in wid for c in ("/", "\\", "..")):
        return False
    f = WORK_DIR / f"{wid}.json"
    if f.exists():
        f.unlink()
        return True
    return False


# ── git 동기화 ────────────────────────────────────────────────
def _git(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return 127, "git 미설치"
    except subprocess.TimeoutExpired:
        return 124, "시간 초과"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def current_branch() -> str:
    code, out = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    return out if code == 0 and out else "claude/youtube-discovery-dashboard-eqO5N"


def sync(push: bool = True) -> dict:
    """shared_work 만 commit → pull(다른 PC 작업 받기) → push. 결과 상태 반환.

    안전: `git add shared_work` 만 → 코드/키/DB 는 절대 커밋 안 됨.
    오프라인·권한 실패는 격리(로컬 작업은 그대로 보존).
    """
    if os.environ.get("WORK_SYNC", "on").lower() == "off":
        return {"ok": False, "disabled": True, "machine": machine_name(),
                "count": len(list(WORK_DIR.glob("*.json"))) if WORK_DIR.exists() else 0,
                "steps": [{"step": "disabled", "ok": True, "msg": "WORK_SYNC=off (동기화 꺼짐)"}]}
    WORK_DIR.mkdir(exist_ok=True)
    branch = current_branch()
    steps = []

    def step(name, code, out):
        steps.append({"step": name, "ok": code == 0, "msg": out[:300]})
        return code == 0

    # 1) 로컬 새 작업 커밋(shared_work 만)
    _git(["add", "shared_work"])
    code, out = _git(["diff", "--cached", "--quiet", "--", "shared_work"])
    committed = False
    if code == 1:                 # 스테이지에 변경 있음
        c2, o2 = _git(["-c", "user.name=shorts-sync",
                       "-c", "user.email=sync@local",
                       "commit", "-m", f"work: {machine_name()} 작업 동기화", "--", "shared_work"])
        committed = step("commit", c2, o2)
    else:
        steps.append({"step": "commit", "ok": True, "msg": "새 작업 없음"})

    # 2) pull(다른 PC 작업 병합) — shared_work 는 개별 파일이라 충돌 없음
    c3, o3 = _git(["pull", "--no-edit", "--no-rebase", "origin", branch], timeout=90)
    pulled = step("pull", c3, o3)

    # 3) push(로컬 작업 공유)
    pushed = False
    if push and pulled:
        c4, o4 = _git(["push", "origin", branch], timeout=90)
        pushed = step("push", c4, o4)
        if not pushed:            # 누가 먼저 push 했으면 pull 후 1회 재시도
            _git(["pull", "--no-edit", "--no-rebase", "origin", branch], timeout=90)
            c5, o5 = _git(["push", "origin", branch], timeout=90)
            pushed = step("push-retry", c5, o5)

    ok = pulled and (pushed or not push)
    return {"ok": ok, "branch": branch, "committed": committed,
            "pulled": pulled, "pushed": pushed, "machine": machine_name(),
            "count": len(list(WORK_DIR.glob("*.json"))), "steps": steps}


# ── 자기검증(임시 폴더에서, 실제 remote 안 건드림) ──────────────
if __name__ == "__main__":
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    WORK_DIR = tmp / "shared_work"

    r1 = save_work("shorts_hook", "옛날과 달라진 복원 수준 ㄷㄷ",
                   {"titles": ["a", "b"], "script": ["x"]}, summary="후킹 대본 10제목")
    r2 = save_work("sre_analyze", "감동 카테고리 역설계", {"score": 86}, summary="바이럴 86점")
    assert (WORK_DIR / f"{r1['id']}.json").exists()

    lst = list_work()
    assert len(lst) == 2 and lst[0]["id"] == r2["id"], "최신순"
    assert "payload" not in lst[0], "목록은 payload 제외(가벼움)"
    assert lst[0]["machine"] and lst[0]["ts"]

    full = get_work(r1["id"])
    assert full and full["payload"]["titles"] == ["a", "b"]

    only = list_work(kind="shorts_hook")
    assert len(only) == 1 and only[0]["kind"] == "shorts_hook"

    assert delete_work(r2["id"]) and len(list_work()) == 1
    assert get_work("../etc/passwd") is None

    print(f"작업 저장 예시: [{r1['ts']} · {r1['machine']}] {r1['title']}")
    print("✅ work_store self-test 통과 — 개별파일 저장/최신순 목록/상세/삭제/경로가드")
