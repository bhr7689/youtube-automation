"""🗄️ SRE-OS 저장소 — 분석 실행(Run)·에이전트 실행·결과 버전을 SQLite 에 축적.

원본 스펙 §15 Entity(Project/Source/AnalysisRun/AgentRun/ResultVersion/Experiment)를
기존 프로젝트 관례(store.py)에 맞춰 SQLite 로 구현. 단일 사용자(사장님)라 User/Workspace 는 생략.

핵심 개념(원본 §10 채택):
- **Idempotency**: 같은 입력(idempotency_key)으로 재실행하면 새 Run 을 만들지 않고
  기존 완료 Run 을 재사용 → LLM 비용·시간 낭비 방지. (force=True 로 강제 재실행 가능)
- **버전 관리**: 결과를 result_version 에 누적 저장 → 되돌리기/비교 가능.
- **재시도**: 에이전트별 상태(ok/failed)를 agent_run 에 기록 → 실패 에이전트만 재실행.

stdlib sqlite3 만 사용. 런타임·FastAPI·cron 어디서든 import 가능.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).parent / "sre_os.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sre_project (
    project_id   TEXT PRIMARY KEY,
    name         TEXT,
    markets      TEXT,          -- JSON list ["KR","JP"]
    created_at   REAL
);

CREATE TABLE IF NOT EXISTS sre_source (
    source_id    TEXT PRIMARY KEY,
    project_id   TEXT,
    kind         TEXT,          -- script/transcript/keyword/idea
    url          TEXT,
    text         TEXT,
    created_at   REAL
);

CREATE TABLE IF NOT EXISTS sre_run (
    run_id           TEXT PRIMARY KEY,
    project_id       TEXT,
    source_id        TEXT,
    idempotency_key  TEXT,       -- 같은 입력 재실행 차단 키
    status           TEXT,       -- pending/running/done/failed
    provider         TEXT,
    mock             INTEGER,    -- 1=규칙기반(키 없음)
    markets          TEXT,       -- JSON list
    created_at       REAL,
    updated_at       REAL
);
CREATE INDEX IF NOT EXISTS idx_run_idem ON sre_run(idempotency_key);

CREATE TABLE IF NOT EXISTS sre_agent_run (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT,
    agent        TEXT,          -- 에이전트 코드(A01…) 또는 role
    status       TEXT,          -- ok/failed/skipped
    ms           INTEGER,       -- 소요 ms
    summary      TEXT,
    error        TEXT,
    created_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_agentrun_run ON sre_agent_run(run_id);

CREATE TABLE IF NOT EXISTS sre_result_version (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT,
    version      INTEGER,       -- 1,2,3…
    report_json  TEXT,          -- 최종 리포트 전체
    created_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_result_run ON sre_result_version(run_id);
"""


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def idempotency_key(kind: str, text: str, markets, provider: str) -> str:
    """입력 동일성 판단 키 — 종류+본문+시장+프로바이더 해시."""
    payload = json.dumps(
        {"kind": kind, "text": text or "",
         "markets": sorted(markets or []), "provider": provider},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def connect(path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str | Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


# ── 프로젝트 / 소스 ────────────────────────────────────────────
def create_project(name: str, markets: list[str],
                   path: str | Path = DB_PATH) -> str:
    init_db(path)
    pid = _uid("proj")
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO sre_project(project_id,name,markets,created_at) VALUES(?,?,?,?)",
            (pid, name, json.dumps(markets, ensure_ascii=False), _now()),
        )
    return pid


def add_source(project_id: str, kind: str, text: str, url: str = "",
               path: str | Path = DB_PATH) -> str:
    sid = _uid("src")
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO sre_source(source_id,project_id,kind,url,text,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (sid, project_id, kind, url, text, _now()),
        )
    return sid


# ── Run (Idempotency 포함) ────────────────────────────────────
def find_done_run(idem: str, path: str | Path = DB_PATH) -> dict | None:
    """같은 입력의 완료된 Run 이 있으면 반환(재사용용)."""
    init_db(path)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM sre_run WHERE idempotency_key=? AND status='done'"
            " ORDER BY updated_at DESC LIMIT 1", (idem,),
        ).fetchone()
    return dict(row) if row else None


def create_run(*, project_id: str, source_id: str, idem: str,
               provider: str, mock: bool, markets: list[str],
               path: str | Path = DB_PATH) -> str:
    init_db(path)
    rid = _uid("run")
    now = _now()
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO sre_run(run_id,project_id,source_id,idempotency_key,"
            "status,provider,mock,markets,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rid, project_id, source_id, idem, "running", provider,
             1 if mock else 0, json.dumps(markets, ensure_ascii=False), now, now),
        )
    return rid


def set_run_status(run_id: str, status: str, path: str | Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE sre_run SET status=?, updated_at=? WHERE run_id=?",
                     (status, _now(), run_id))


def get_run(run_id: str, path: str | Path = DB_PATH) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM sre_run WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


# ── 에이전트 실행 로그 ─────────────────────────────────────────
def log_agent(run_id: str, agent: str, status: str, ms: int,
              summary: str = "", error: str = "",
              path: str | Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO sre_agent_run(run_id,agent,status,ms,summary,error,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (run_id, agent, status, ms, summary, error, _now()),
        )


def agent_runs(run_id: str, path: str | Path = DB_PATH) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT agent,status,ms,summary,error FROM sre_agent_run"
            " WHERE run_id=? ORDER BY id", (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── 결과 버전 ─────────────────────────────────────────────────
def save_result(run_id: str, report: dict, path: str | Path = DB_PATH) -> int:
    """새 버전으로 결과 저장 → 버전 번호 반환."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM sre_result_version WHERE run_id=?",
            (run_id,)).fetchone()
        ver = (row["v"] or 0) + 1
        conn.execute(
            "INSERT INTO sre_result_version(run_id,version,report_json,created_at)"
            " VALUES(?,?,?,?)",
            (run_id, ver, json.dumps(report, ensure_ascii=False), _now()),
        )
    return ver


def latest_result(run_id: str, path: str | Path = DB_PATH) -> dict | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT report_json FROM sre_result_version WHERE run_id=?"
            " ORDER BY version DESC LIMIT 1", (run_id,)).fetchone()
    return json.loads(row["report_json"]) if row else None


def result_versions(run_id: str, path: str | Path = DB_PATH) -> list[int]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT version FROM sre_result_version WHERE run_id=? ORDER BY version",
            (run_id,)).fetchall()
    return [r["version"] for r in rows]


# ── 자기검증 ──────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "test_sre.db"
    init_db(tmp)

    pid = create_project("테스트 채널", ["KR", "JP"], path=tmp)
    sid = add_source(pid, "script", "안녕하세요 오늘은…", path=tmp)
    idem = idempotency_key("script", "안녕하세요 오늘은…", ["KR", "JP"], "mock")

    assert find_done_run(idem, path=tmp) is None, "아직 완료 Run 없어야"
    rid = create_run(project_id=pid, source_id=sid, idem=idem,
                     provider="mock", mock=True, markets=["KR", "JP"], path=tmp)

    log_agent(rid, "A01", "ok", 3, "입력 정규화", path=tmp)
    log_agent(rid, "A03", "ok", 5, "구조 분해", path=tmp)
    log_agent(rid, "A06", "failed", 1, "감정 DNA", error="테스트 실패", path=tmp)
    runs = agent_runs(rid, path=tmp)
    assert len(runs) == 3 and runs[2]["status"] == "failed"

    v1 = save_result(rid, {"hello": 1}, path=tmp)
    v2 = save_result(rid, {"hello": 2}, path=tmp)
    assert (v1, v2) == (1, 2)
    assert latest_result(rid, path=tmp)["hello"] == 2
    assert result_versions(rid, path=tmp) == [1, 2]

    set_run_status(rid, "done", path=tmp)
    found = find_done_run(idem, path=tmp)
    assert found and found["run_id"] == rid, "완료 Run 재사용 가능해야"

    print("✅ sre_store self-test 통과 — 프로젝트/소스/Run/Idempotency/에이전트/버전")
