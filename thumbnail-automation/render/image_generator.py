import logging
import os
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.config import GEMINI_API_KEY, OPENAI_API_KEY, GEN_DIR
from core.store import insert_generated, update_generated_status
from core.utils import new_id

logger = logging.getLogger(__name__)

REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY", "")

ENGINES = {
    "imagen3": {"name": "Imagen 3 (Google)", "key": "GEMINI_API_KEY",
        "available": bool(GEMINI_API_KEY), "best_for": "자연스러운 인물, 감성 썸네일", "size": "16:9"},
    "dalle3": {"name": "DALL-E 3 (OpenAI)", "key": "OPENAI_API_KEY",
        "available": bool(OPENAI_API_KEY), "best_for": "창의적 합성, 텍스트 포함 썸네일", "size": "1792x1024"},
    "sd": {"name": "Stable Diffusion XL (Replicate)", "key": "REPLICATE_API_KEY",
        "available": bool(REPLICATE_API_KEY), "best_for": "스타일 자유도 높음, 애니/아트 느낌", "size": "1344x768"},
}


def available_engines():
    return [{"id": k, **v} for k, v in ENGINES.items() if v["available"]]


def _run_engine(engine_id, prompt, negative, count):
    if engine_id == "imagen3":
        from render.imagen_client import generate
        return generate(prompt, count=count)
    elif engine_id == "dalle3":
        from render.dalle_client import generate
        return generate(prompt, count=count)
    elif engine_id == "sd":
        from render.sd_client import generate
        return generate(prompt, negative=negative, count=count)
    raise ValueError(f"알 수 없는 엔진: {engine_id}")


def generate_images(analysis_id, prompt, negative="", hook_type="", ctr_score=0.0,
                    engines=None, count_per_engine=2, parallel=True):
    target_engines = engines or [e["id"] for e in available_engines()]
    if not target_engines:
        raise RuntimeError("사용 가능한 이미지 생성 API가 없습니다.")
    results = []

    def _run(eid):
        try:
            paths = _run_engine(eid, prompt, negative, count_per_engine)
            saved = []
            for p in paths:
                gen_id = new_id("gen")
                insert_generated({"gen_id": gen_id, "analysis_id": analysis_id,
                    "hook_type": hook_type, "prompt_text": prompt, "image_path": str(p),
                    "ctr_score": ctr_score, "status": "pending", "feedback": ""})
                saved.append({"engine": eid, "gen_id": gen_id, "image_path": str(p), "status": "ok"})
            return {"engine": eid, "paths": saved, "error": None}
        except Exception as e:
            return {"engine": eid, "paths": [], "error": str(e)}

    if parallel and len(target_engines) > 1:
        with ThreadPoolExecutor(max_workers=len(target_engines)) as ex:
            futures = {ex.submit(_run, eid): eid for eid in target_engines}
            for f in as_completed(futures):
                r = f.result()
                results.extend(r["paths"])
                if r["error"]:
                    results.append({"engine": r["engine"], "gen_id": None, "image_path": None, "status": f"error: {r['error']}"})
    else:
        for eid in target_engines:
            r = _run(eid)
            results.extend(r["paths"])
            if r["error"]:
                results.append({"engine": eid, "gen_id": None, "image_path": None, "status": f"error: {r['error']}"})
    return results
