import logging
from pathlib import Path
from datetime import datetime

import httpx

from core.config import OPENAI_API_KEY, GEN_DIR

logger = logging.getLogger(__name__)


def generate(prompt, count=1, size="1792x1024"):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 없음")
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    paths = []
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    for i in range(min(count, 4)):
        try:
            resp = client.images.generate(model="dall-e-3", prompt=prompt[:4000],
                size=size, quality="hd", style="vivid", n=1)
            image_url = resp.data[0].url
            img_bytes = httpx.get(image_url, timeout=30).content
            fpath = GEN_DIR / f"dalle_{ts}_{i}.png"
            fpath.write_bytes(img_bytes)
            paths.append(fpath)
        except Exception as e:
            logger.error("DALL-E 3 생성 실패 #%d: %s", i, e)
            raise
    return paths
