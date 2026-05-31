import logging
import os
from pathlib import Path
from datetime import datetime

import httpx

from core.config import GEN_DIR

logger = logging.getLogger(__name__)

REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY", "")
SD_MODEL = "stability-ai/sdxl:39ed52f2319f9b2369ed6b77e11d74a8f51d0c38301a3f5baf04e07ae0e05f44"


def generate(prompt, negative="", count=2, size="1344x768"):
    if not REPLICATE_API_KEY:
        raise RuntimeError("REPLICATE_API_KEY 없음 (.env에 추가하세요)")
    import replicate
    w, h = (int(x) for x in size.split("x"))
    paths = []
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    for i in range(min(count, 4)):
        try:
            output = replicate.run(SD_MODEL, input={"prompt": prompt, "negative_prompt": negative,
                "width": w, "height": h, "num_inference_steps": 30, "guidance_scale": 7.5})
            url = output[0] if isinstance(output, list) else str(output)
            img_bytes = httpx.get(url, timeout=60).content
            fpath = GEN_DIR / f"sd_{ts}_{i}.png"
            fpath.write_bytes(img_bytes)
            paths.append(fpath)
        except Exception as e:
            logger.error("SD 생성 실패 #%d: %s", i, e)
            raise
    return paths
