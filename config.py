from pathlib import Path
import os

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    # requirements.txt installs python-dotenv; keep a clear error if dependencies are incomplete.
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent

# ==================== REQUIRED: TELEGRAM ====================
TOKEN = os.getenv("TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "5628671567"))
OWNER_LABEL = "👑 Owner"

# ==================== OPTIONAL: AI API KEYS ====================
# Add one or more keys here. Leave unused providers as empty strings.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

GEMINI_MODEL = "gemini-3.6-flash"
MISTRAL_MODEL = "mistral-small-latest"
OPENROUTER_MODEL = "openrouter/free"
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_FALLBACK_MODELS = ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
AI_PROVIDERS = {"gemini":"Gemini", "mistral":"Mistral AI", "openrouter":"OpenRouter", "groq":"Groq"}
AI_FREE_DAILY_FALLBACKS = 5
AI_PREMIUM_DAILY_FALLBACKS = 20
AI_PROOFREAD_TOTAL_TIMEOUT = 30
AI_PROOFREAD_REQUEST_TIMEOUT = 8
AI_PROOFREAD_CHUNK_CHARS = 12000
AI_FREE_DAILY_REQUESTS = 30
AI_PREMIUM_DAILY_REQUESTS = 300
AI_REQUESTS_PER_MINUTE = 8
MAX_CONCURRENT_AI_PER_USER = 1
MAX_AI_KEY_ATTEMPTS = int(os.getenv("MAX_AI_KEY_ATTEMPTS", "20"))
MAX_PDF_CHAT_CONTEXT_CHARS = 24000
PDF_CHAT_TOP_K = 6
MAX_INDEX_CHUNKS = 5000

FREE_DAILY_PDFS = 20
PREMIUM_DAILY_PDFS = 100
DEFAULT_PREMIUM_DAYS = 30
MAX_PREMIUM_DAYS = 3650

# ==================== OPTIONAL: CHANNEL GATE ====================
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
CHANNEL_GATE_ENABLED = os.getenv("CHANNEL_GATE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
CHANNEL_JOIN_URL = os.getenv("CHANNEL_JOIN_URL", "").strip()

# ==================== FILE / SERVER SETTINGS ====================
FONTS_DIR = BASE_DIR / "fonts"
TEMP_DIR = BASE_DIR / "temp"
DB_PATH = BASE_DIR / "pdf_mitra.db"
HINDI_FONT_PATH = FONTS_DIR / "NotoSansDevanagari-Regular.ttf"
HINDI_FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf"
MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_IMAGES_PER_PDF = 50
MAX_PDFS_TO_MERGE = 20
MAX_TTF_FILES_PER_ZIP = 40
MAX_ZIP_UNCOMPRESSED_SIZE = 100 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_OCR_PAGES = 20
MAX_MERGED_PAGES = 200
MAX_IMAGE_PIXELS = 40_000_000
MAX_TEXT_CHARS_PER_BATCH = 100_000
TEMP_MAX_AGE_HOURS = 24
PORT = 8080

FONTS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

