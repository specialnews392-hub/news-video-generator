"""
Script Generator - Uses Gemini API to create news scripts from articles.
"""
import asyncio
import logging
import json
import time
from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)


def _create_client(api_key: str = None):
    """Create a Gemini client with the given or next rotated key."""
    key = api_key or config.get_next_gemini_key()
    http_opts = None
    if getattr(config, "GEMINI_BASE_URL", None):
        http_opts = types.HttpOptions(base_url=config.GEMINI_BASE_URL)
    return genai.Client(api_key=key, http_options=http_opts)


async def generate_script(
    articles: list[dict],
    topic: str,
    lang: str = "ru",
    target_length: int = None,
    previous_titles: list[str] = None,
) -> dict:
    """
    Generate a unique, non-repeating news script from articles using Gemini.
    """
    if target_length is None:
        target_length = config.TARGET_SCRIPT_LENGTH
        
    if previous_titles is None:
        from services import news_fetcher
        previous_titles = news_fetcher.get_recent_video_titles(limit=10)
    
    # Prepare anti-repetition block
    anti_repeat_block = ""
    if previous_titles:
        prev_list = "\n".join(f"  • {t}" for t in previous_titles)
        anti_repeat_block = f"""
======================================================================
🚨 СТРОЖАЙШИЙ ЗАПРЕТ НА ПОВТОРЕНИЕ И КЛИШЕ-ШАБЛОНЫ! 🚨
Предыдущие выпуски на канале УЖЕ ВЫХОДИЛИ со следующими заголовками:
{prev_list}

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
1. Использовать шаблонные клише вроде:
   • "MIGRATIONS-KRISE IN DEUTSCHLAND: WENN DIE FAKTEN IGNORIERT WERDEN!"
   • "MIGRATIONS-KRISE IN BERLIN: WENN DIE REALITÄT IGNORIERT WIRD!"
   • Любые конструкции с "WENN DIE FAKTEN IGNORIERT WERDEN" или "WENN DIE REALITÄT IGNORIERT WIRD"!
   • Шаблоны "[ТЕМА]-WAHN: WENN..." или "СРОЧНО! [Кто-то] в ПАНИКЕ"!
2. Заголовок и сценарий ОБЯЗАНЫ отражать КОНКРЕТНОЕ ОСТРОЕ СОБЫТИЕ, ЗАКОН, РЕШЕНИЕ ИЛИ ФИГУРУ из собранных статей!
   Примеры живых форматов заголовка:
   - Событие / решение: 'BEZAHLKARTE-BESCHLUSS: JETZT DREHT DIE BUNDESREGIERUNG DEN GELDHAHN ZU!'
   - Конфликт / ультиматум: 'MERZ-ULTIMATUM: ASYL-VERHANDLUNGEN VOR DEM BRUCH!'
   - Граница / полиция: 'GRENZ-ALARM: POLIZEI MELDET NEUE REKORD-ZURÜCKWEISUNGEN!'
   - Расследование / факты: 'BAMF-LAGEBERICHT: DIE ZAHLEN, DIE BERLIN NERVÖS MACHEN!'
   - Реформа / закон: 'NOTLAGE-PARAGRAPH 72: DIE RADIKALE WENDE AN DEN GRENZEN!'
3. Пересказывать те же новости и сюжеты! Выбери из собранных статей ДРУГИЕ свежие события, другие конфликты, других спикеров!
======================================================================
"""
    
    # Prepare articles text with explicit source attribution and character counts
    articles_text = ""
    for i, article in enumerate(articles[:15], 1):
        text = (article.get("full_text") or article.get("summary") or "").strip()
        text_len = len(text)
        if text_len > 4000:
            text = text[:4000] + "..."
        is_lead = "🔥 [HAUPT-THEMA / LEIT-ARTIKEL]" if (i == 1 or article.get("is_primary_search")) else ""
        articles_text += f"\n=== ПЕРВОИСТОЧНИК {i}: {article.get('source', 'СМИ')} {is_lead} (Объём фактуры: {text_len} знаков) ===\n"
        articles_text += f"Заголовок: {article['title']}\n"
        articles_text += f"Ссылка: {article.get('link', 'N/A')}\n"
        articles_text += f"Дата публикации: {article.get('published', 'N/A')}\n"
        articles_text += f"РЕАЛЬНЫЙ ТЕКСТ И ФАКТЫ ИЗ СТАТЬИ:\n{text}\n"
    
    lang_names = {
        "ru": "русском", "en": "английском", "de": "немецком",
        "fr": "французском", "es": "испанском", "zh": "китайском",
        "ar": "арабском", "pt": "португальском", "it": "итальянском",
        "ja": "японском", "ko": "корейском", "uk": "украинском",
        "tr": "турецком", "hi": "хинди",
    }
    lang_name = lang_names.get(lang, "русском")
    
    num_paragraphs = max(20, int(target_length / 650))

    if lang == "de":
        prompt = f"""Du bist der leitende Chefredakteur und Drehbuchautor eines der reichweitenstärksten deutschen Analyse- und Investigativ-Kanäle auf YouTube (über 1,5 Mio. Abonnenten, im packenden Stil von 'Achtung, Reichelt!', 'Vermietet Tagebuch', 'Marc Friedrich'). Deine Dokumentationen und Berichte fesseln die Zuschauer von der ersten Sekunde an durch packende Dramaturgie, schonungslose Fakten, scharfe Analysen und lebendige, flüssige deutsche Sprache (Hochdeutsch).

Thema der Sendung: "{topic}"
{anti_repeat_block}

======================================================================
🚨 STRIKTE FAKTENBINDUNG & ABSOLUTE THEMEN-TREUE (KEIN THEMENWECHSEL!):
======================================================================
Unten findest du ECHTE, VOLLSTÄNDIGE TEXTE aktueller Artikel führender Medien.
1. ZWINGENDE VORGABE: Das gesamte Skript, der YouTube-Titel und das Thumbnail MÜSSEN zu 100% genau das oben genannte Hauptthema behandeln: "{topic}"!
2. Es ist STRENGSTENS VERBOTEN, das Thema eigenmächtig auf andere, zusammenhanglose Kriminalfälle oder Nebenartikel zu wechseln! Die Story aus Artikel 1 bzw. dem zum Thema "{topic}" passenden Artikel ist die ABSOLUTE HAUPTGESCHICHTE.
3. Dein Skript MUSS auf ECHTEN Fakten, Statistiken, Zahlen, Behörden, Namen und direkten Zitaten aus den Texten basieren!
4. Erfinde KEINE Fantasie-Ereignisse. Zitiere Quellen natürlich im Textfluss:
   «Wie berichtet...», «Nach offiziellen Zahlen...», «Wie das Medium aufdeckt...».

======================================================================
📖 STIL UND NARRATIV — PACKENDE HOCHDEUTSCHE ANALYSE:
======================================================================
• Schreibe genau {num_paragraphs} AUSFÜHRLICHE, GEHALTVOLLE ABSÄTZE im Array "paragraphs".
• JEDER ABSATZ besteht aus 4-6 gut formulierten, flüssigen Sätzen (ca. 600-750 Zeichen pro Absatz, Gesamtlänge ca. {target_length} Zeichen).
• Nutze lebendige deutsche Überleitungen: «Tatsache ist...», «Gleichzeitig zeigt sich...», «Während in Berlin noch diskutiert wird...», «Besonders brisant dabei...», «Doch hinter den Kulissen...», «Das bitterste Detail daran...», «Experten schlagen längst Alarm...».
• Der Text ist für die professionelle Sprecherstimme bestimmt: natürlich, dynamisch, spannend, mit klarer Haltung und ohne hölzerne Phrasen!
• Gliedere die Sendung in 5 Akte:
  1. Akt 1 (Absätze 1-5): Dramatischer Einstieg und Chronik des Geschehens (Was ist passiert, wo, Ausmaß, Schockwellen in der Politik).
  2. Akt 2 (Absätze 6-10): Konfrontation, Panik der Verantwortlichen, Aussagen aus Berlin und Brüssel, Fakten & Zahlen.
  3. Akt 3 (Absätze 11-15): Hintergründe und Ursachen (Warum das System versagt hat, was bisher verschwiegen wurde).
  4. Akt 4 (Absätze 16-19): Politische Konsequenzen (Forderungen von Opposition & Bürgern, Debatte über Grenzkontrollen & Abschiebungen).
  5. Akt 5 (Absätze 20-{num_paragraphs}): PERSÖNLICHE MEINUNG DES AUTORS, scharfes Fazit, Publikumsfrage & Abo-Aufruf.

======================================================================
🎯 ZWINGENDE VORGABE: PERSÖNLICHE MEINUNG DES AUTORS AM ENDE DES VIDEOS:
======================================================================
Die letzten 2-3 Absätze VOR der Verabschiedung MÜSSEN zwingend die pointierte, persönliche Meinung und den Kommentar des Autors/Moderators zur behandelten Thematik enthalten!
• Der Autor bleibt kein unbeteiligter Beobachter, sondern bezieht klare Kante mit eigener analytischer Haltung:
  «Meiner Ansicht nach zeigt dieses Ereignis schonungslos...»,
  «Meine persönliche Haltung dazu ist eindeutig: Wer jetzt noch zögert, beschleunigt den Kontrollverlust...»,
  «Ich bin überzeugt davon, dass diese Beschlüsse zu spät kommen, weil...»,
  «Wenn Sie mich fragen, liegt der eigentliche Skandal darin, dass...».
• Der Autor zieht ein schonungsloses Fazit über die Zukunft des Landes, stellt den Zuschauern eine direkte Frage zu seiner These und fordert zur Diskussion in den Kommentaren sowie zum Abonnieren auf.

ARTIKEL:
{articles_text}

ANTWORT STRENG IM JSON-FORMAT:
{{
    "main_lead_story": "Kurz auf Deutsch: Welches zentrale Ereignis aus den Artikeln steht im Fokus (1-2 Sätze)",
    "title": "PACKENDER, REICHWEITENSTARKER YOUTUBE-TITEL (bis 75 Zeichen, mit GROSSBUCHSTABEN und Emotionen, z.B. 'MIGRATIONS-HAMMER: JETZT GREIFT MERZ DURCH!' oder 'SKANDAL IN BERLIN: FAESER VERLIERT DIE KONTROLLE!')",
    "title_ru": "Точный и понятный перевод названия ролика на РУССКИЙ язык для автора",
    "thumbnail_hook": "ULTRA-PACKENDER THUMBNAIL-TEXT (3-5 Worte in GROSSBUCHSTABEN für das YouTube-Vorschaubild, z.B. 'MIGRATIONS-SCHOCK! MERZ GREIFT DURCH' oder 'ALARM IN BERLIN! GRENZEN DICHT')",
    "thumbnail_hook_ru": "Перевод текста обложки на РУССКИЙ язык для автора",
    "thumbnail_query": "Präziser Suchbegriff für das Hintergrundbild (3-4 Worte, z.B. 'Friedrich Merz wütend Nahaufnahme', 'Nancy Faeser Pressekonferenz ernst', 'Bundespolizei Grenzkontrolle')",
    "description": "Fesselnde Videobeschreibung für YouTube auf Deutsch (bis 200 Zeichen)",
    "paragraphs": [
        "Text von Absatz 1 auf Deutsch...",
        "Text von Absatz 2 auf Deutsch...",
        ... (genau {num_paragraphs} Absätze; die letzten 2-3 Absätze enthalten die deutliche PERSÖNLICHE MEINUNG des Autors zum Thema und sein Fazit!)
    ],
    "search_queries": [
        "Suchbegriff für Bild 1 (z.B. Friedrich Merz Nahaufnahme Mimik)",
        ... (100-130 präzise Bild-Suchbegriffe auf Deutsch/Englisch fokussiert auf Gesichter und Emotionen)
    ]
}}
"""
    else:
        prompt = f"""Ты главный сценарист и редактор топового аналитического YouTube-канала (более 2 млн подписчиков). Твои видео смотрят миллионы зрителей на одном дыхании благодаря мощной кинематографичной драматургии, глубокому анализу и великолепному живому языку на {lang_name} языке.

Тема выпуска: "{topic}"
{anti_repeat_block}

======================================================================
🔍 СТРОЖАЙШАЯ ПРИВЯЗКА К РЕАЛЬНОЙ ФАКТУРЕ (АНТИ-ВЫМЫСЕЛ / ГАРАНТИЯ ДОСТОВЕРНОСТИ):
======================================================================
Ниже тебе предоставлены РЕАЛЬНЫЕ ПОЛНЫЕ ТЕКСТЫ свежих статей от ведущих информационных агентств (Интерфакс, Коммерсантъ, Ведомости, РБК и др.).
1. Твой сценарий ОБЯЗАН быть основан на РЕАЛЬНЫХ фактах, цифрах, должностях, фамилиях и прямых цитатах из приведенных ниже текстов!
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать несуществующие события, приписывать спикерам вымышленные слова или сочинять фантастические повороты из головы!
3. Обязательно цитируй и органично упоминай первоисточники в повествовании:
   «Как передает Интерфакс...», «По официальным данным...», «Издание Коммерсантъ подчеркивает...», «Согласно сообщениям аналитиков...».
4. Твоя задача — не выдумать сказку, а провести глубокий, захватывающий аналитический разбор РЕАЛЬНОГО события, раскрыв его подоплёку и геополитические последствия.

======================================================================
🚨 КРИТИЧЕСКОЕ ТРЕБОВАНИЕ: СТРОГОЕ СООТВЕТСТВИЕ ЗАДАННОЙ ТЕМЕ: "{topic}"! 🚨
Ниже представлен список проверенных статей с реальными текстами.

ТВОЯ ГЛАВНАЯ ЗАДАЧА:
1. ВНИМАТЕЛЬНО ИЗУЧИ ВСЕ СТАТЬИ И ВЫБЕРИ ИЗ НИХ РОВНО ОДНО САМОЕ ВАЖНОЕ СОБЫТИЕ, КОТОРОЕ СТРОГО ОТНОСИТСЯ К ТЕМЕ: "{topic}"!
   Если в теме указан конкретный человек (например, Андрей Белоусов, Владимир Путин, Дональд Трамп) или тема (Внутренняя политика, Экономика, Оборона) — ГЛАВНЫЙ СЮЖЕТ, ЗАГОЛОВОК, ОБЛОЖКА И ВЕСЬ ВЫПУСК ОБЯЗАНЫ БЫТЬ ПОСВЯЩЕНЫ ИМЕННО ЭТОМУ ЧЕЛОВЕКУ И ЕГО РЕШЕНИЯМ!
   КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО подменять тему посторонними новостями!
2. ВЕСЬ РОЛИК ДОЛЖЕН БЫТЬ ПОСВЯЩЕН ИМЕННО ЭТОМУ ОДНОМУ СОБЫТИЮ (расследование, хроника, закулисье, цитаты, последствия).

❌ СТРОЖАЙШЕ ЗАПРЕЩЕНО:
- ДЕЛАТЬ ТЕКСТ ПОХОЖИМ НА СПИСОК РАЗРОЗНЕННЫХ ЗАГОЛОВКОВ ИЛИ ЛОЗУНГОВ!
- Писать короткими изолированными фразами по одной строчке.
- Прыгать с темы на тему (3 фразы про Германию -> 3 фразы про сухогруз -> 3 фразы про Японию).

======================================================================
📖 СТИЛЬ И СТРУКТУРА ТЕКСТА — ЖИВОЙ, СВЯЗНЫЙ ЛИТЕРАТУРНЫЙ НАРРАТИВ:
======================================================================
Текст сценария должен читаться как непрерывное, захватывающее расследование авторитетного блогера на {lang_name} языке:
• Текст разбивается строго на {num_paragraphs} РАЗВЕРНУТЫХ, ПОЛНОЦЕННЫХ АБЗАЦЕВ в массиве "paragraphs".
• В КАЖДОМ АБЗАЦЕ должно быть по 4-6 сложных, богатых предложений (примерно 600-750 символов на абзац).
• Предложения внутри абзаца ДОЛЖНЫ БЫТЬ ТЕСНО СВЯЗАНЫ МЕЖДУ СОБОЙ! Используй союзы, вводные слова и логические мостики:
  «Дело в том, что...», «В то же время...», «По сообщениям осведомленных источников...»,
  «Именно поэтому в Брюсселе началась...», «Однако за закрытыми дверями происходило совсем другое...»,
  «Более того, как отмечают ведущие эксперты...», «Впрочем, в Москве на этот счет...».
• Текст для озвучки диктором — плавный, живой, с естественной интонацией, без рубленых фраз!

======================================================================
📏 ОБЪЕМ ТЕКСТА — СТРОГО {target_length} ЗНАКОВ (ОТ {target_length - 500} ДО {target_length + 2000}):
======================================================================
• При скорости чтения около 850 символов в минуту {target_length} знаков дадут полноценные 12-16 минут хронометража!
• Напиши ровно {num_paragraphs} развернутых абзацев по 650-700 символов, чтобы гарантированно набрать нужный объем.
• Разверни сюжет в 5 актах:
  1. Акт 1 (Абзацы 1-5): Драматический хук и детальная хроника события (что случилось, где, масштабы, эффект разорвавшейся бомбы).
  2. Акт 2 (Абзацы 6-10): Прямое столкновение сторон, паника оппонентов, жесткие заявления, сорванные маски и точные цитаты.
  3. Акт 3 (Абзацы 11-15): Закулисье и тайный замысел (что предшествовало событию, почему многолетний план оппонентов рухнул).
  4. Акт 4 (Абзацы 16-19): Геополитический перелом (последствия для мирового баланса сил, крах стратегий, трещины в альянсах).
  5. Акт 5 (Абзацы 20-{num_paragraphs}): ЛИЧНОЕ АВТОРСКОЕ МНЕНИЕ О ТЕМЕ ВЫПУСКА, финальный вердикт, вопрос зрителю и призыв подписаться.

======================================================================
🎯 СТРОЖАЙШЕЕ ТРЕБОВАНИЕ: ЛИЧНОЕ АВТОРСКОЕ МНЕНИЕ В ФИНАЛЕ РОЛИКА:
======================================================================
Финальная часть выпуска (последние 2-3 абзаца перед прощанием) ОБЯЗАТЕЛЬНО должна содержать четко выраженное, смелое ЛИЧНОЕ МНЕНИЕ АВТОРА о поднятой теме!
• Автор не является безликим диктором, он — лидер мнений со своей твердой позицией:
  «На мой взгляд, эта ситуация со всей очевидностью доказывает...»,
  «Моя личная позиция здесь однозначна: любые попытки закрыть глаза на проблему приведут лишь к...»,
  «Я глубоко убежден, что эти полумеры не дадут результата, потому что...»,
  «И если вы спросите мое авторское мнение, то корень проблемы лежит совсем в другой плоскости...».
• Автор подводит свой собственный глубокий итог, прямо обращается к зрителям: «А что думаете по этому поводу вы? Согласны ли вы с моим выводом? Напишите свое мнение в комментариях под этим видео...» и призывает подписаться на канал.

СТАТЬИ:
{articles_text}

ОТВЕТ строго в формате JSON:
{{
    "main_lead_story": "Кратко: какое ОДНО конкретное событие из статей выбрано за основу выпуска (1-2 предложения)",
    "title": "КЛИКБЕЙТНЫЙ заголовок для YouTube (до 75 символов, с КАПСОМ и эмоцией!)",
    "title_ru": "Точный перевод названия ролика на русский язык",
    "thumbnail_hook": "СВЕРХКРАТКИЙ, МОЩНЕЙШИЙ ТЕКСТ ДЛЯ ОБЛОЖКИ (всего 3-5 убойных слов капсом для YouTube-превью, например: 'МЕРЦ В ЯРОСТИ! ПЛАН РУХНУЛ' или 'УДАР В СПИНУ: ШОК В БЕРЛИНЕ')",
    "thumbnail_hook_ru": "Перевод текста обложки на русский язык",
    "thumbnail_query": "Точный поисковый запрос (3-4 слова) для фона обложки: главный герой события с яркой эмоцией или место действия (например: 'Фридрих Мерц Бундестаг эмоции', 'Олаф Шольц трибуна', 'Военный корабль Черное море')",
    "description": "Интригующее описание для YouTube (до 200 символов)",
    "paragraphs": [
        "Текст абзаца 1 (развернутый текст из 4-6 предложений, связное повествование с союзами и переходами, 600-750 знаков)...",
        "Текст абзаца 2...",
        ... (всего ровно {num_paragraphs} полноценных абзацев общим объемом {target_length} знаков; последние 2-3 абзаца ОБЯЗАТЕЛЬНО содержат яркое ЛИЧНОЕ МНЕНИЕ АВТОРА о теме выпуска!)
    ],
    "search_queries": [
        "поисковый запрос для кадра 1 (персона, эмоция, крупный план)",
        ... (100-130 точных поисковых запросов)
    ]
}}

ВАЖНЕЙШЕЕ ПРАВИЛО ДЛЯ search_queries:
Создай 100-130 поисковых запросов (3-5 слов).
ОНИ ОБЯЗАНЫ БЫТЬ СТРОГО ПРИВЯЗАНЫ К ТЕМЕ "{topic}" И ЛИЦАМ ЛЮДЕЙ/ПОЛИТИКОВ:
1. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ любые неодушевленные предметы и канцелярия:
   - НИКАКИХ столов, стульев, микрофонов, ноутбуков, компьютеров, диаграмм, графиков, таблиц, бумаг или пустых кабинетов!
   - Запрещены слова: "Tisch", "runder Tisch", "Mikrofon", "Stuhl", "Laptop", "Computer", "Diagramm", "Grafik", "Statistik", "Tabelle", "table", "chair", "microphone", "стол", "стул", "микрофон", "диаграмма".
   - Если в предложении говорится метафора («сели за стол переговоров», «подошли к микрофону», «согласно статистике»), запрос должен быть НЕ про стол/микрофон, а про КОНКРЕТНЫХ ЛЮДЕЙ и ТЕМУ: например "Olaf Scholz Friedrich Merz Streit", "{topic} Pressekonferenz", "Polizei Berlin Einsatz"!
2. ВСЕ ЗАПРОСЫ ДОЛЖНЫ БЫТЬ ОРИЕНТИРОВАНЫ НА ЛЮДЕЙ, ЛИЦА И РЕАЛЬНЫЕ СОБЫТИЯ ПО ТЕМЕ "{topic}":
   - Называй конкретных лидеров и участников из текста выпуска (политики, министры, силовики, судьи, граждане).
   - Добавляй эмоции и действия: "крупный план лицо злой", "спорит на трибуне жесты", "эмоциональное выступление кричит", "растерянный взгляд лицо", "сердитый недоволен", "напряженные переговоры", "пресс-конференция жесткий ответ", "демонстрация граждане протест", "полиция контроль".
3. СТРОГО ЗАПРЕЩЕНО: абстрактные пустые слова ("политика", "новости", "дипломатия", "стратегия") без привязки к теме!
"""

    # Try with aggressive key rotation - try many keys and fallback models
    models_to_try = [config.GEMINI_MODEL] + config.GEMINI_FALLBACK_MODELS
    models_to_try = list(dict.fromkeys(models_to_try))  # deduplicate preserving order
    
    last_error = None
    total_keys = len(config.GEMINI_KEYS)
    
    for model_name in models_to_try:
        # Try all available keys for each model
        keys_to_try = total_keys
        for key_attempt in range(keys_to_try):
            try:
                key = config.get_next_gemini_key()
                client = _create_client(key)
                
                logger.info(f"Trying model={model_name}, key #{config._key_index % total_keys}")
                
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.85,
                        max_output_tokens=16384,
                        response_mime_type="application/json",
                    ),
                )
                
                result_text = response.text.strip()
                
                # Parse JSON
                result = json.loads(result_text)
                
                # Extract paragraphs or segments
                paragraphs = result.get("paragraphs", [])
                if not paragraphs and "segments" in result:
                    # Fallback if model returned segments instead of paragraphs
                    raw_segs = [s.strip() for s in result["segments"] if s.strip()]
                    if raw_segs and len(raw_segs[0]) < 250:
                        # Group every 4 short sentences into a paragraph
                        paragraphs = [" ".join(raw_segs[i:i+4]) for i in range(0, len(raw_segs), 4)]
                    else:
                        paragraphs = raw_segs
                        
                if not paragraphs:
                    raise ValueError("No paragraphs or segments in response")
                    
                # Clean paragraphs
                paragraphs = [p.strip() for p in paragraphs if p.strip()]
                full_script = "\n\n".join(paragraphs)
                
                # Derive sentence-level visual segments for video slides
                import re
                segments = []
                for p in paragraphs:
                    sents = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', p) if s.strip()]
                    for sent in sents:
                        if len(sent) > 160:
                            parts = [pt.strip() for pt in re.split(r'(?<=[,;—–:])\s+', sent) if pt.strip()]
                            if len(parts) > 1:
                                cur = ""
                                for pt in parts:
                                    if len(cur) + len(pt) < 140:
                                        cur = (cur + " " + pt).strip()
                                    else:
                                        if cur:
                                            segments.append(cur)
                                        cur = pt
                                if cur:
                                    segments.append(cur)
                            else:
                                segments.append(sent)
                        else:
                            segments.append(sent)
                
                # Ensure queries
                queries = result.get("search_queries", [])
                queries = [q.strip() for q in queries if q.strip()]
                
                # Align queries with segments
                while len(queries) < len(segments):
                    fallback_idx = len(queries)
                    seg_text = segments[fallback_idx] if fallback_idx < len(segments) else topic
                    clean_words = [w.strip(".,;:!?\"'«»()[]") for w in seg_text.split() if len(w) > 3]
                    
                    if lang == "de":
                        # In German, capitalized words are nouns/names
                        nouns = [w for w in clean_words if w and w[0].isupper() and w.lower() not in {"dass", "wenn", "oder", "aber", "auch", "eine", "einer", "eines", "dieser", "diese", "dieses", "sein", "ihre", "nach", "fuer", "ueber", "unter"}]
                        if len(nouns) >= 2:
                            queries.append(f"{' '.join(nouns[:3])} Deutschland")
                        else:
                            de_fallbacks = [
                                f"{topic} Deutschland Politik",
                                f"{topic} Bundestag Debatte",
                                f"{topic} Pressekonferenz",
                                f"{topic} Aktuell Nachrichten",
                                f"{topic} Regierung Berlin",
                            ]
                            queries.append(de_fallbacks[fallback_idx % len(de_fallbacks)])
                    elif lang == "ru":
                        ru_fallbacks = [
                            f"{topic} новости события",
                            f"{topic} репортаж крупный план",
                            f"{topic} пресс-конференция",
                            f"{topic} заявление политики",
                        ]
                        queries.append(ru_fallbacks[fallback_idx % len(ru_fallbacks)])
                    else:
                        queries.append(f"{topic} news report")
                
                # Enforce title uniqueness and sanitize repetitive cliches
                raw_title = result.get("title", "").strip()
                cliche_triggers = [
                    "WENN DIE FAKTEN IGNORIERT", "WENN DIE REALITÄT IGNORIERT",
                    "WENN DIE REALITAET IGNORIERT", "IGNORIERT WERDEN", "IGNORIERT WIRD"
                ]
                from services.news_fetcher import _title_similarity
                is_cliche = any(trg in raw_title.upper() for trg in cliche_triggers)
                is_dupe_title = any(_title_similarity(raw_title.lower(), pt.lower()) > 0.5 for pt in (previous_titles or []))

                if is_cliche or is_dupe_title:
                    lead = result.get("main_lead_story", "")
                    words_lead = [w for w in lead.split() if len(w) > 3][:4]
                    lead_phrase = " ".join(words_lead).upper() if words_lead else "WICHTIGE ENTSCHEIDUNG"
                    short_top = " ".join(topic.split()[:2]).upper()
                    if lang == "de":
                        remedy_title = f"{short_top}-HAMMER: {lead_phrase} ERSCHÜTTERT BERLIN!"
                    elif lang == "ru":
                        remedy_title = f"{short_top}: ГЛАВНОЕ РЕШЕНИЕ — {lead_phrase}!"
                    else:
                        remedy_title = f"{short_top} REPORT: {lead_phrase}!"
                    logger.warning(f"Sanitized repetitive title: '{raw_title}' -> '{remedy_title}'")
                    result["title"] = remedy_title[:75]

                result["paragraphs"] = paragraphs
                result["script"] = full_script
                result["segments"] = segments
                from services.translator import translate_to_ru
                if not result.get("title_ru"):
                    result["title_ru"] = translate_to_ru(result.get("title", ""))
                if not result.get("thumbnail_hook_ru"):
                    result["thumbnail_hook_ru"] = translate_to_ru(result.get("thumbnail_hook", ""))
                
                script_len = len(result["script"])
                logger.info(f"Generated script: {script_len} chars, {len(paragraphs)} paragraphs, {len(segments)} visual slides (model={model_name})")
                return result
                
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error (model={model_name}, key_attempt={key_attempt + 1}): {e}")
                try:
                    import re
                    json_match = re.search(r'\{[\s\S]*\}', result_text)
                    if json_match:
                        result = json.loads(json_match.group())
                        result["script"] = "\n\n".join(result.get("segments", []))
                        if result.get("segments"):
                            return result
                except:
                    pass
                last_error = e
                    
            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                
                # If rate limited or quota exceeded - backoff intelligently so 1-minute RPM window rolls over
                if any(kw in error_str for kw in ["429", "quota", "rate", "resource_exhausted", "limit"]):
                    # If this key has quota_limit_value: 0 (regional zero quota), sleeping does not help - skip immediately!
                    if "quota_limit_value': '0'" in error_str or "quota_limit_value\": \"0\"" in error_str:
                        logger.warning(f"Key has 0 regional quota (europe-west1: 0). Skipping immediately to next key.")
                        continue
                    
                    logger.warning(f"Key rate-limited (model={model_name}, attempt={key_attempt + 1}): {str(e)[:120]}")
                    if key_attempt < 2:
                        await asyncio.sleep(1.5)
                    else:
                        wait_sec = min(30, 8 + (key_attempt - 2) * 8)
                        logger.warning(f"Project RPM limit reached for project keys. Pausing {wait_sec}s for the 1-minute quota window to roll over...")
                        await asyncio.sleep(wait_sec)
                    continue
                
                # If model is experiencing temporary high demand (503)
                if "503" in error_str or "unavailable" in error_str or "high demand" in error_str:
                    logger.warning(f"Model {model_name} temporarily busy (503 high demand), trying next attempt/model: {str(e)[:120]}")
                    await asyncio.sleep(1.5)
                    continue

                # If model not found - skip to next model
                if "404" in error_str or "not_found" in error_str or "no longer available" in error_str:
                    logger.warning(f"Model {model_name} not available, trying next model")
                    break  # break inner loop, go to next model
                
                # Other error - log and try next key
                logger.error(f"Gemini error (model={model_name}, attempt={key_attempt + 1}): {e}")
                await asyncio.sleep(1)
    
    raise RuntimeError(f"Failed to generate script after trying all keys and models. Last error: {last_error}")


async def analyze_image_relevance(
    image_url: str,
    context: str,
    topic: str,
) -> dict:
    """
    Use Gemini Vision to analyze if an image is relevant to the context.
    
    Returns:
        dict with 'relevant' (bool), 'score' (0-10), 'reason' (str)
    """
    try:
        key = config.get_next_gemini_key()
        client = _create_client(key)
        
        prompt = f"""Проанализируй изображение по ссылке и определи, подходит ли оно для новостного видеоролика.

Тема: {topic}
Контекст (текст слайда): {context[:500]}

Оцени по критериям:
1. Релевантность теме (0-10)
2. Качество изображения (наличие водяных знаков, низкое разрешение)
3. Подходит ли для новостного контента (нет шокирующего контента)

Ответ строго в JSON: {{"relevant": true/false, "score": 0-10, "reason": "пояснение"}}"""

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=config.GEMINI_VISION_MODEL,
            contents=[
                prompt,
                {"url": image_url} if image_url.startswith("http") else image_url,
            ],
            config={
                "temperature": 0.3,
                "max_output_tokens": 256,
                "response_mime_type": "application/json",
            },
        )
        
        return json.loads(response.text.strip())
        
    except Exception as e:
        logger.warning(f"Image analysis failed: {e}")
        return {"relevant": True, "score": 5, "reason": "Analysis unavailable"}
