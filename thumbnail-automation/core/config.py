"""
환경변수 + 전역 상수 관리.
모든 모듈은 여기서 설정을 가져온다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── 경로 ──────────────────────────────────────────────
ROOT_DIR   = Path(__file__).parent.parent
DATA_DIR   = ROOT_DIR / "data"
THUMB_DIR  = DATA_DIR / "thumbnails"
GEN_DIR    = DATA_DIR / "generated"
VOCAB_DIR  = ROOT_DIR / "vocab"
DB_PATH    = DATA_DIR / "thumbnail.db"

for _d in (DATA_DIR, THUMB_DIR, GEN_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── API 키 ────────────────────────────────────────────
YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY", "")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")   # Imagen 3 + Vision 분석 + 한 끗 AI
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")   # DALL-E 3
REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY", "") # Stable Diffusion XL
PINTEREST_TOKEN  = os.getenv("PINTEREST_TOKEN", "")  # optional

# ── 수집 설정 ─────────────────────────────────────────
MAX_CHANNELS_PER_CATEGORY = 20   # 카테고리당 수집 채널 수
MAX_VIDEOS_PER_CHANNEL    = 50   # 채널당 수집 영상 수
MIN_VIEW_COUNT            = 10_000  # 최소 조회수 필터

# ── 분석 설정 ─────────────────────────────────────────
ANALYSIS_MODEL  = "gemini-1.5-flash"   # Vision 분석용
GENERATION_MODEL = "dall-e-3"          # 이미지 생성용
IMAGE_SIZE       = "1792x1024"         # YouTube 썸네일 비율 (16:9)

# ── 썸네일 카테고리 (감정 분류) ──────────────────────────
CATEGORIES = {
    "트로트_그리움":  {"emotion": "nostalgia",  "color_temp": "warm"},
    "트로트_흥":     {"emotion": "joy",         "color_temp": "vivid"},
    "트로트_효도":   {"emotion": "gratitude",   "color_temp": "warm"},
    "먹방_욕망":     {"emotion": "desire",       "color_temp": "warm"},
    "반전_호기심":   {"emotion": "curiosity",    "color_temp": "cool"},
    "공포_불안":     {"emotion": "fear",         "color_temp": "cold"},
}

# ── 한 끗 유형 ────────────────────────────────────────
HOOK_TYPES = ["시선강탈", "감정과잉", "정보불완전", "비현실대비", "레트로리마스터"]
