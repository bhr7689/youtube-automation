import logging
from pathlib import Path
from datetime import datetime

from core.config import GEMINI_API_KEY, GEN_DIR
from core.utils import new_id

logger = logging.getLogger(__name__)


def generate(prompt, count=4, size="1024x576"):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 없음")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
    aspect = "16:9" if "576" in size or "1024x576" in size else "1:1"
    try:
        resp = client.models.generate_images(
            model="imagen-3.0-generate-001", prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=min(count, 4), aspect_ratio=aspect,
                safety_filter_level="block_only_high", person_generation="allow_adult"))
    except Exception as e:
        logger.error("Imagen 3 생성 실패: %s", e)
        raise
    paths = []
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    for i, img in enumerate(resp.generated_images):
        fpath = GEN_DIR / f"imagen_{ts}_{i}.png"
        fpath.write_bytes(img.image.image_bytes)
        paths.append(fpath)
    return paths
