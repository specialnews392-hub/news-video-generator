"""
Translation & Headline Generation Helper
Provides fast Russian translation for headlines/thumbnails and AI headline variations.
"""
import json
import logging
import urllib.parse
import urllib.request
import re
from google import genai
import config

logger = logging.getLogger(__name__)


_TRANSLATION_CACHE: dict[str, str] = {}


def translate_to_ru(text: str) -> str:
    """Translate text to Russian quickly via Google Translate web API or fallback."""
    if not text or not text.strip():
        return ""
    
    clean_text = text.strip()
    if clean_text in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[clean_text]
    
    # 1. Try Google Translate gtx
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ru&dt=t&q=" + urllib.parse.quote(clean_text)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and data[0]:
                res = "".join([part[0] for part in data[0] if part and part[0]]).strip()
                if res:
                    _TRANSLATION_CACHE[clean_text] = res
                    return res
    except Exception as e:
        logger.warning(f"Google Translate API failed for '{text[:30]}': {e}")
    
    # 2. Fallback to MyMemory API if Google rate-limits
    try:
        url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(clean_text[:200])}&langpair=de|ru"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = (data.get("responseData") or {}).get("translatedText")
            if res and not res.startswith("MYMEMORY WARNING"):
                _TRANSLATION_CACHE[clean_text] = res.strip()
                return res.strip()
    except Exception as e:
        logger.warning(f"MyMemory fallback failed for '{text[:30]}': {e}")
    
    return clean_text



async def generate_thumbnail_headline_variants(
    topic: str,
    current_title: str = "",
    lead_story: str = "",
    lang: str = "de",
    count: int = 4,
) -> list[dict]:
    """Use Gemini to generate multiple high-CTR clickbait thumbnail hooks with Russian translations."""
    lang_labels = {
        "de": "Немецкий (Deutsch)",
        "en": "Английский (English)",
        "ru": "Русский",
    }
    target_lang = lang_labels.get(lang, "Немецкий (Deutsch)")

    prompt = f"""Ты — шеф-редактор и специалист по кликбейтам для топового YouTube-канала.
Тема ролика: "{topic}"
Главный инфоповод: "{lead_story or current_title or topic}"
Язык канала: {target_lang}

Придумай {count} СВЕРХ-ЦЕПЛЯЮЩИХ, КЛИКБЕЙТНЫХ вариантов текста для ОБЛОЖКИ (превью) YouTube:
1. Текст на обложке должен быть ОЧЕНЬ коротким (3-5 слов КАПСОМ на языке канала).
2. Формула успеха: шок-триггер + персона/закон + драматический глагол (например: "BÜRGERGELD 2026: DAS ENDE DROHT!", "MERZ GREIFT DURCH: ALARM IN BERLIN!", "RENTE IN GEFAHR: SCHOCK-REFORM").
3. Для каждого варианта ОБЯЗАТЕЛЬНО укажи понятный и точный перевод на РУССКИЙ язык, чтобы автор понимал суть!

ОТВЕТЬ СТРОГО В ФОРМАТЕ JSON (без markdown-оберток):
[
    {{
        "text": "ТЕКСТ НА ОБЛОЖКУ НА ЯЗЫКЕ КАНАЛА (КАПСОМ, 3-5 СЛОВ)",
        "text_ru": "Точный перевод на русский язык"
    }}
]
"""

    models_to_try = [config.GEMINI_MODEL] + config.GEMINI_FALLBACK_MODELS
    models_to_try = list(dict.fromkeys(models_to_try))

    for model_name in models_to_try:
        for key in config.GEMINI_KEYS[:6]:
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                raw = response.text.strip()
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                data = json.loads(raw)
                if isinstance(data, list) and len(data) > 0:
                    # Sanitize and ensure Russian translation
                    variants = []
                    for item in data[:count]:
                        t = item.get("text", "").strip().upper()
                        t_ru = item.get("text_ru", "").strip() or translate_to_ru(t)
                        if t:
                            variants.append({"text": t, "text_ru": t_ru})
                    if variants:
                        return variants
            except Exception as e:
                logger.debug(f"Gemini thumbnail variant error with {model_name}: {e}")
                continue

    # Fallback default variations if Gemini unavailable
    fallback_templates = {
        "de": [
            ("REFORM BESCHLOSSEN: BÜRGERGELD VOR DEM AUS?", "Реформа принята: конец Bürgergeld?"),
            ("RENTE 2026: DIE BITTERE WAHRHEIT ENTHÜLLT!", "Пенсии 2026: горькая правда раскрыта!"),
            ("MERZ GREIFT DURCH: RADIKALE WENDE IN BERLIN!", "Мерц наводит порядок: радикальный поворот в Берлине!"),
            ("SCHOCK FÜR MILLIONEN: REGIERUNG KÜRZT HILFEN!", "Шок для миллионов: правительство урезает помощь!"),
        ],
        "ru": [
            ("РЕШЕНИЕ ПРИНЯТО: СРОЧНОЕ ЗАЯВЛЕНИЕ ВЛАСТЕЙ!", "Решение принято: срочное заявление властей!"),
            ("СИТУАЦИЯ ВЫШЛА ИЗ-ПОД КОНТРОЛЯ: ЧТО ДАЛЬШЕ?", "Ситуация вышла из-под контроля: что дальше?"),
            ("СКАНДАЛ ГОДА: ВСЯ ПРАВДА РАСКРЫТА!", "Скандал года: вся правда раскрыта!"),
            ("УДАР В СПИНУ: ПЛАН ПОЛНОСТЬЮ ПРОВАЛИЛСЯ!", "Удар в спину: план полностью провалился!"),
        ]
    }
    t_list = fallback_templates.get(lang, fallback_templates["de"])
    return [{"text": t, "text_ru": tru} for t, tru in t_list]
