"""
News Video Generator - Configuration
"""
import os
import random
from pathlib import Path

# === Paths ===
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
FONTS_DIR = BASE_DIR / "fonts"
STATIC_DIR = BASE_DIR / "static"

# Create directories
for d in [OUTPUT_DIR, TEMP_DIR, FONTS_DIR, STATIC_DIR]:
    d.mkdir(exist_ok=True)

# === Gemini API Keys (rotation) ===
GEMINI_KEYS_FILE = BASE_DIR / "gemini_keys.txt"

def load_gemini_keys() -> list[str]:
    """Load all Gemini API keys from file, ignoring comments and blank lines."""
    if not GEMINI_KEYS_FILE.exists():
        return []
    with open(GEMINI_KEYS_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

GEMINI_KEYS = load_gemini_keys()
_key_index = 0

def get_next_gemini_key() -> str:
    """Get next API key with round-robin rotation."""
    global _key_index
    if not GEMINI_KEYS:
        raise ValueError("No Gemini API keys found in gemini_keys.txt")
    key = GEMINI_KEYS[_key_index % len(GEMINI_KEYS)]
    _key_index += 1
    return key

def get_random_gemini_key() -> str:
    """Get a random API key."""
    if not GEMINI_KEYS:
        raise ValueError("No Gemini API keys found in gemini_keys.txt")
    return random.choice(GEMINI_KEYS)

# === Image API Keys & Cloudflare Proxy ===
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")  # Pexels key issuance paused
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "57828495-1dce467eaf711523347304b33")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "jEZe1ipjRckExo0VfUT4Er86nYU49bfNjbj7AorIHRc")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

IMAGE_PROXY_FILE = BASE_DIR / "image_proxy_worker.txt"

def get_image_proxy_worker() -> str:
    """Get custom Cloudflare Worker image proxy URL if configured."""
    env_val = os.getenv("IMAGE_PROXY_WORKER_URL", "").strip()
    if env_val:
        return env_val.rstrip("/")
    if IMAGE_PROXY_FILE.exists():
        try:
            val = IMAGE_PROXY_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val.rstrip("/")
        except Exception:
            pass
    return ""

IMAGE_PROXY_WORKER_URL = get_image_proxy_worker()

# === TTS Voices (Edge-TTS Neural voices & Gemini Experimental) ===
# Each voice has: id, edge_name, display_name, lang, gender
ALL_VOICES = [
    # German
    {"id": "de-conrad", "edge": "de-DE-ConradNeural", "name": "Conrad (Neural — Безлимитно ⭐)", "lang": "de", "gender": "м"},
    {"id": "de-killian", "edge": "de-DE-KillianNeural", "name": "Killian (Neural — Безлимитно ⭐)", "lang": "de", "gender": "м"},
    {"id": "de-katja", "edge": "de-DE-KatjaNeural", "name": "Katja (Neural — Безлимитно)", "lang": "de", "gender": "ж"},
    {"id": "de-gemini-puck", "engine": "gemini", "gemini_voice": "Puck", "name": "Gemini Puck (Лимит Google: 10/сутки)", "lang": "de", "gender": "м"},
    {"id": "de-gemini-charon", "engine": "gemini", "gemini_voice": "Charon", "name": "Gemini Charon (Лимит Google: 10/сутки)", "lang": "de", "gender": "м"},
    {"id": "de-gemini-fenrir", "engine": "gemini", "gemini_voice": "Fenrir", "name": "Gemini Fenrir (Лимит Google: 10/сутки)", "lang": "de", "gender": "м"},
    {"id": "de-gemini-kore", "engine": "gemini", "gemini_voice": "Kore", "name": "Gemini Kore (Лимит Google: 10/сутки)", "lang": "de", "gender": "ж"},
    {"id": "de-gemini-aoede", "engine": "gemini", "gemini_voice": "Aoede", "name": "Gemini Aoede (Лимит Google: 10/сутки)", "lang": "de", "gender": "ж"},
    # Russian
    {"id": "ru-dmitry", "edge": "ru-RU-DmitryNeural", "name": "Дмитрий (Neural — Безлимитно ⭐)", "lang": "ru", "gender": "м"},
    {"id": "ru-svetlana", "edge": "ru-RU-SvetlanaNeural", "name": "Светлана (Neural — Безлимитно)", "lang": "ru", "gender": "ж"},
    {"id": "ru-dariya", "edge": "ru-RU-DariyaNeural", "name": "Дария (Neural — Безлимитно)", "lang": "ru", "gender": "ж"},
    {"id": "ru-gemini-charon", "engine": "gemini", "gemini_voice": "Charon", "name": "Gemini Charon (Лимит Google: 10/сутки)", "lang": "ru", "gender": "м"},
    {"id": "ru-gemini-fenrir", "engine": "gemini", "gemini_voice": "Fenrir", "name": "Gemini Fenrir (Лимит Google: 10/сутки)", "lang": "ru", "gender": "м"},
    {"id": "ru-gemini-puck", "engine": "gemini", "gemini_voice": "Puck", "name": "Gemini Puck (Лимит Google: 10/сутки)", "lang": "ru", "gender": "м"},
    {"id": "ru-gemini-kore", "engine": "gemini", "gemini_voice": "Kore", "name": "Gemini Kore (Лимит Google: 10/сутки)", "lang": "ru", "gender": "ж"},
    # English
    {"id": "en-guy", "edge": "en-US-GuyNeural", "name": "Guy (Neural — Безлимитно ⭐)", "lang": "en", "gender": "м"},
    {"id": "en-andrew", "edge": "en-US-AndrewNeural", "name": "Andrew (Neural — Безлимитно)", "lang": "en", "gender": "м"},
    {"id": "en-brian", "edge": "en-US-BrianNeural", "name": "Brian (Neural — Безлимитно)", "lang": "en", "gender": "м"},
    {"id": "en-jenny", "edge": "en-US-JennyNeural", "name": "Jenny (Neural — Безлимитно)", "lang": "en", "gender": "ж"},
    {"id": "en-aria", "edge": "en-US-AriaNeural", "name": "Aria (Neural — Безлимитно)", "lang": "en", "gender": "ж"},
    {"id": "en-gemini-charon", "engine": "gemini", "gemini_voice": "Charon", "name": "Gemini Charon (Лимит Google: 10/сутки)", "lang": "en", "gender": "м"},
    {"id": "en-gemini-puck", "engine": "gemini", "gemini_voice": "Puck", "name": "Gemini Puck (Лимит Google: 10/сутки)", "lang": "en", "gender": "м"},
    # French
    {"id": "fr-henri", "edge": "fr-FR-HenriNeural", "name": "Henri", "lang": "fr", "gender": "м"},
    {"id": "fr-denise", "edge": "fr-FR-DeniseNeural", "name": "Denise", "lang": "fr", "gender": "ж"},
    # Spanish
    {"id": "es-alvaro", "edge": "es-ES-AlvaroNeural", "name": "Alvaro", "lang": "es", "gender": "м"},
    {"id": "es-elvira", "edge": "es-ES-ElviraNeural", "name": "Elvira", "lang": "es", "gender": "ж"},
    # Chinese
    {"id": "zh-yunxi", "edge": "zh-CN-YunxiNeural", "name": "Yunxi", "lang": "zh", "gender": "м"},
    {"id": "zh-xiaoxiao", "edge": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao", "lang": "zh", "gender": "ж"},
    # Arabic
    {"id": "ar-hamed", "edge": "ar-SA-HamedNeural", "name": "Hamed", "lang": "ar", "gender": "м"},
    {"id": "ar-zariyah", "edge": "ar-SA-ZariyahNeural", "name": "Zariyah", "lang": "ar", "gender": "ж"},
    # Portuguese
    {"id": "pt-antonio", "edge": "pt-BR-AntonioNeural", "name": "Antonio", "lang": "pt", "gender": "м"},
    {"id": "pt-francisca", "edge": "pt-BR-FranciscaNeural", "name": "Francisca", "lang": "pt", "gender": "ж"},
    # Italian
    {"id": "it-diego", "edge": "it-IT-DiegoNeural", "name": "Diego", "lang": "it", "gender": "м"},
    {"id": "it-elsa", "edge": "it-IT-ElsaNeural", "name": "Elsa", "lang": "it", "gender": "ж"},
    # Japanese
    {"id": "ja-keita", "edge": "ja-JP-KeitaNeural", "name": "Keita", "lang": "ja", "gender": "м"},
    {"id": "ja-nanami", "edge": "ja-JP-NanamiNeural", "name": "Nanami", "lang": "ja", "gender": "ж"},
    # Korean
    {"id": "ko-injoon", "edge": "ko-KR-InJoonNeural", "name": "InJoon", "lang": "ko", "gender": "м"},
    {"id": "ko-sunhi", "edge": "ko-KR-SunHiNeural", "name": "SunHi", "lang": "ko", "gender": "ж"},
    # Hindi
    {"id": "hi-madhur", "edge": "hi-IN-MadhurNeural", "name": "Madhur", "lang": "hi", "gender": "м"},
    {"id": "hi-swara", "edge": "hi-IN-SwaraNeural", "name": "Swara", "lang": "hi", "gender": "ж"},
    # Turkish
    {"id": "tr-ahmet", "edge": "tr-TR-AhmetNeural", "name": "Ahmet", "lang": "tr", "gender": "м"},
    {"id": "tr-emel", "edge": "tr-TR-EmelNeural", "name": "Emel", "lang": "tr", "gender": "ж"},
    # Ukrainian
    {"id": "uk-ostap", "edge": "uk-UA-OstapNeural", "name": "Остап", "lang": "uk", "gender": "м"},
    {"id": "uk-polina", "edge": "uk-UA-PolinaNeural", "name": "Полина", "lang": "uk", "gender": "ж"},
]

# Quick lookup by voice_id
VOICES_BY_ID = {v["id"]: v for v in ALL_VOICES}

# Default voice per language (first male voice)
TTS_VOICES = {}
TTS_VOICE_NAMES = {}
for v in ALL_VOICES:
    if v["lang"] not in TTS_VOICES and "edge" in v:
        TTS_VOICES[v["lang"]] = v["edge"]
        TTS_VOICE_NAMES[v["lang"]] = f"{v['name']} ({v['lang'].upper()})"

# === Video Settings ===
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 24
SLIDE_DURATION = 5  # seconds per image
CROSSFADE_DURATION = 0.7  # seconds for transition
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

# === Thumbnail Settings ===
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# === Script Settings ===
TARGET_SCRIPT_LENGTH = 15000  # Default 15,000 chars (~12-15 minutes narration)
MIN_SCRIPT_LENGTH = 12000
MAX_SCRIPT_LENGTH = 18000

# === Theme Colors (for thumbnails) ===
THEME_COLORS = {
    "default": {"primary": "#1a1a2e", "secondary": "#16213e", "accent": "#e94560", "text": "#ffffff"},
    "politics": {"primary": "#0d1b2a", "secondary": "#1b263b", "accent": "#e63946", "text": "#ffffff"},
    "economy": {"primary": "#0b132b", "secondary": "#1c2541", "accent": "#3a86ff", "text": "#ffffff"},
    "finance_de": {"primary": "#0a192f", "secondary": "#0f2744", "accent": "#10b981", "badge_bg": "#047857", "highlight": "#f59e0b", "text": "#ffffff"},
    "technology": {"primary": "#0a0a23", "secondary": "#1a1a40", "accent": "#00d4ff", "text": "#ffffff"},
    "military": {"primary": "#1a1a1a", "secondary": "#2d2d2d", "accent": "#ff6b35", "text": "#ffffff"},
    "world": {"primary": "#0d1321", "secondary": "#1d2d44", "accent": "#f0c808", "text": "#ffffff"},
    "society": {"primary": "#14213d", "secondary": "#1b3a5c", "accent": "#fca311", "text": "#ffffff"},
    "science": {"primary": "#0b0c10", "secondary": "#1f2833", "accent": "#66fcf1", "text": "#ffffff"},
}

# === Gemini Model & Proxy ===
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://gemini-proxy.akot4400.workers.dev")
GEMINI_MODEL = "gemini-3.5-flash-lite"  # Main model for script generation (higher daily limits)
GEMINI_VISION_MODEL = "gemini-3.8-flash"  # Vision model for image analysis (fast & high capacity)
GEMINI_FALLBACK_MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]


