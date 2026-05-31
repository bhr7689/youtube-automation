import json
import logging
from datetime import datetime
from pathlib import Path

from core.config import VOCAB_DIR

logger = logging.getLogger(__name__)

CUSTOM_HOOKS_PATH = VOCAB_DIR / "custom_hooks.json"


def _load():
    if not CUSTOM_HOOKS_PATH.exists():
        CUSTOM_HOOKS_PATH.write_text(json.dumps({"custom_hooks": []}, ensure_ascii=False, indent=2))
    return json.loads(CUSTOM_HOOKS_PATH.read_text(encoding="utf-8")).get("custom_hooks", [])


def _save(hooks):
    CUSTOM_HOOKS_PATH.write_text(json.dumps({"custom_hooks": hooks}, ensure_ascii=False, indent=2), encoding="utf-8")


def list_custom_hooks():
    return _load()


def add_custom_hook(id, description, best_for, prompt_keywords, examples=None):
    hooks = _load()
    hooks = [h for h in hooks if h["id"] != id]
    new_hook = {"id": id, "description": description, "best_for": best_for,
        "prompt_keywords": prompt_keywords, "examples": examples or [],
        "created_at": datetime.utcnow().isoformat(), "source": "user"}
    hooks.append(new_hook)
    _save(hooks)
    return new_hook


def delete_custom_hook(id):
    hooks = _load()
    before = len(hooks)
    hooks = [h for h in hooks if h["id"] != id]
    if len(hooks) < before:
        _save(hooks)
        return True
    return False


def get_custom_hooks_for_category(category):
    return [h for h in _load() if not h.get("best_for") or category in h.get("best_for", [])]
