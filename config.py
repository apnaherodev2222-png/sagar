"""
📋 PDF Mitra Pro v2 - Configuration & Constants
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# TELEGRAM BOT CONFIG
# ============================================================
TOKEN = os.getenv("BOT_TOKEN", "8794443522:AAEfzM9ESC2Jj79arozgECbEwfV9C6UslS4")
OWNER_ID = int(os.getenv("OWNER_ID", "5628671567"))
OWNER_LABEL = "👑 Owner: @Xalonexdev03"
PORT = int(os.getenv("PORT", "8080"))

# ============================================================
# AI PROVIDERS & MODELS
# ============================================================
GEMINI_MODEL = "gemini-3.6-flash"
MISTRAL_MODEL = "mistral-small-latest"
OPENROUTER_MODEL = "openrouter/free"
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_FALLBACK_MODELS = ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

AI_PROVIDERS = {
    "gemini": {"label": "Gemini", "model": GEMINI_MODEL},
    "mistral": {"label": "Mistral AI", "model": MISTRAL_MODEL},
    "openrouter": {"label": "OpenRouter", "model": OPENROUTER_MODEL},
    "groq": {"label": "Groq", "model": GROQ_MODEL},
}

# ============================================================
# QUOTAS & LIMITS (Production Guardrails)
# ============================================================
# PDF Creation Limits
FREE_DAILY_PDFS = 5
PREMIUM_DAILY_PDFS = 50
MAX_PDFS_TO_MERGE = 20
MAX_PDF_PAGES = 100
MAX_OCR_PAGES = 20
MAX_MERGED_PAGES = 200

# File Size Limits
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_IMAGE_PIXELS = 40_000_000  # 40M pixels
MAX_ZIP_UNCOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_TTF_FILES_PER_ZIP = 40

# Text & Content Limits
MAX_TEXT_CHARS_PER_BATCH = 100_000
MAX_IMAGES_PER_PDF = 50
MAX_PDF_CHAT_CONTEXT_CHARS = 24000
PDF_CHAT_TOP_K = 6  # Retrieval result count
MAX_INDEX_CHUNKS = 5000
MAX_AI_QUERY_CHARS = 8000

# AI Request Limits
AI_FREE_DAILY_REQUESTS = 30
AI_PREMIUM_DAILY_REQUESTS = 300
AI_REQUESTS_PER_MINUTE = 8
MAX_CONCURRENT_AI_PER_USER = 1
AI_FREE_DAILY_FALLBACKS = 5
AI_PREMIUM_DAILY_FALLBACKS = 20

# Timeouts (seconds)
AI_PROOFREAD_TOTAL_TIMEOUT = 30
AI_PROOFREAD_REQUEST_TIMEOUT = 8
AI_PROOFREAD_CHUNK_CHARS = 12000
HTTP_REQUEST_TIMEOUT = 25
PDF_EXTRACTION_TIMEOUT = 60

# Cleanup
TEMP_MAX_AGE_HOURS = 24
FONT_MAX_AGE_DAYS = 30
DOCUMENT_SESSION_TTL_HOURS = 2

# ============================================================
# DIRECTORIES
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FONTS_DIR = DATA_DIR / "fonts"
TEMP_DIR = DATA_DIR / "temp"
LOGS_DIR = BASE_DIR / "logs"

# Create directories
for directory in [DATA_DIR, FONTS_DIR, TEMP_DIR, LOGS_DIR]:
    directory.mkdir(exist_ok=True, parents=True)

# Database
DATABASE_PATH = str(DATA_DIR / "pdf_bot.db")

# ============================================================
# FONT CONFIGURATION
# ============================================================
HINDI_FONT_URL = (
    "https://github.com/googlefonts/noto-fonts/raw/main/"
    "hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
)
HINDI_FONT_PATH = FONTS_DIR / "NotoSansDevanagari-Regular.ttf"

# ============================================================
# LOGGING
# ============================================================
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ============================================================
# FEATURE FLAGS
# ============================================================
ENABLE_HARFBUZZ = os.getenv("ENABLE_HARFBUZZ", "true").lower() == "true"
ENABLE_PYMUPDF = os.getenv("ENABLE_PYMUPDF", "true").lower() == "true"
ENABLE_OCR = os.getenv("ENABLE_OCR", "true").lower() == "true"
ENABLE_WEBHOOKS = os.getenv("ENABLE_WEBHOOKS", "false").lower() == "true"

# ============================================================
# FLASK KEEP-ALIVE
# ============================================================
FLASK_HOST = "0.0.0.0"
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# ============================================================
# RATE LIMITING
# ============================================================
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_CLEANUP_INTERVAL = 3600  # seconds

# ============================================================
# CACHE
# ============================================================
FONT_METADATA_CACHE_SIZE = 100
CHUNK_CACHE_SIZE = 1000
