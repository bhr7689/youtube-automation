"""공통 유틸리티 — 로깅, 파일 IO, 해시, 이미지 다운로드."""
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger(__name__)


# ── 로깅 셋업 ─────────────────────────────────────────────

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


# ── ID 생성 ───────────────────────────────────────────────

def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}_{uid}" if prefix else uid


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


# ── 이미지 다운로드 ───────────────────────────────────────

def download_image(url: str, dest_dir: Path, filename: str | None = None) -> Path | None:
    """URL에서 이미지를 다운로드해 dest_dir에 저장. 실패 시 None 반환."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = filename or (url_hash(url) + ".jpg")
    dest  = dest_dir / fname
    if dest.exists():
        return dest
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest
    except Exception as e:
        logger.warning("이미지 다운로드 실패 %s: %s", url, e)
        return None


# ── 재시도 래퍼 ───────────────────────────────────────────

def retry(fn: Callable, times: int = 3, delay: float = 2.0):
    """fn을 최대 times회 재시도. 모두 실패하면 마지막 예외를 올린다."""
    last_err = None
    for attempt in range(times):
        try:
            return fn()
        except Exception as e:
            last_err = e
            wait = delay * (2 ** attempt)
            logger.warning("재시도 %d/%d (%.0fs 후): %s", attempt + 1, times, wait, e)
            time.sleep(wait)
    raise last_err


# ── JSON 안전 로드 ────────────────────────────────────────

def safe_json_loads(text: str | None, default=None):
    if not text:
        return default
    import json
    try:
        return json.loads(text)
    except Exception:
        return default
