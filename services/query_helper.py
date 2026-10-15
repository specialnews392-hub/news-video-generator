"""
Query Helper - Thematic query sanitization and context anchoring.
Guarantees that image queries strictly reflect the news video topic and headline,
completely eliminating irrelevant objects (tables, chairs, microphones, diagrams, laptops, etc.).
Provides an extensive pool of diverse, sharp visual queries for video generation and replacement.
Works dynamically for ANY topic (Migration, Economy & Pensions, Defence, Politics, etc.).
"""
import re
import logging

logger = logging.getLogger(__name__)

# Forbidden words that produce irrelevant stock photos, office furniture, stationery or abstract charts
FORBIDDEN_OBJECT_TERMS = {
    # German
    "tisch", "tische", "runder tisch", "stuhl", "stühle", "buerostuhl", "bürostuhl",
    "mikrofon", "mikrofone", "mikro", "laptop", "computer", "pc", "tastatur",
    "diagramm", "diagramme", "grafik", "grafiken", "statistik", "statistiken",
    "tabelle", "tabellen", "balkendiagramm", "kurvendiagramm", "chart", "charts",
    "ordner", "aktenordner", "papier", "papiere", "dokument", "dokumente",
    "schreibtisch", "büro", "buero", "bueroraum", "büroraum",
    "nahaufnahme", "detailaufnahme", "hände", "haende", "hand", "kugelschreiber", "stift",
    "leerer raum", "symbolbild tisch", "symbolbild mikrofon",
    
    # English
    "table", "tables", "round table", "chair", "chairs", "desk", "office chair",
    "microphone", "microphones", "mic", "laptop", "computer", "keyboard",
    "diagram", "diagrams", "chart", "charts", "graph", "graphs", "statistics",
    "table sheet", "spreadsheet", "folder", "folders", "paper", "papers", "document",
    "office", "close up table", "close up mic", "hands", "pen",
    
    # Russian
    "стол", "столы", "круглый стол", "стул", "стулья", "кресло",
    "микрофон", "микрофоны", "ноутбук", "компьютер", "клавиатура",
    "диаграмма", "диаграммы", "график", "графики", "статистика", "статистики",
    "таблица", "таблицы", "папка", "папки", "бумага", "бумаги", "документ",
    "кабинет", "офис", "ручка", "руки", "крупный план стол", "крупный план микрофон",
}

# Thematic modifier angles by category to ensure high visual variety without repetition
THEMATIC_ANGLES = [
    "{topic}",
    "{title}",
    "{topic} Politik Debatte",
    "{topic} Regierung Statement",
    "{topic} Bürger Öffentlichkeit",
    "{topic} Pressekonferenz Politiker",
    "{topic} Kontrolle Einsatz",
    "{title} Deutschland",
    "{topic} Menschen Bericht",
    "{topic} Bundestag Diskussion",
    "{topic} Bundespolizei Einsatz",
    "{topic} Ministerium Konferenz",
    "{topic} Grenzstation Kontrolle",
    "{topic} Versammlung Demonstration",
    "{topic} Kanzleramt Statement",
    "{topic} Justiz Gerichtsverhandlung",
    "{topic} Berlin Regierungsviertel",
    "{topic} Stadt Rathaus Sitzung",
    "{topic} Sicherheit Lagebericht",
    "{topic} Europa Brüssel Gipfel",
    "{topic} Nachrichten Sprecher",
    "{topic} Gesetz Abstimmung",
    "{topic} Polizei Absperrung",
    "{topic} Protest Bürger",
    "{topic} Dokumente Unterzeichnung",
    "{topic} Opposition Kritik",
    "{topic} Fakten Überprüfung",
    "{topic} Reform Konzept",
    "{topic} Ankunft Flughafen Kontrolle",
    "{topic} Beamte Einsatzort",
    "{topic} Tagesschau Bericht",
    "{topic} Bundesrat Debatte",
    "{topic} Politik Interview",
    "{topic} Konfrontation Streit",
    "{topic} Wahlen Umfrage",
]


def clean_query_text(text: str) -> str:
    """Strip special chars, markdown artifacts, punctuation."""
    if not text:
        return ""
    cleaned = re.sub(r'[*#_`!?:;\"\'«»(){}\[\]]', ' ', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def contains_forbidden_objects(query: str) -> bool:
    """Check if query contains any forbidden inanimate object words."""
    if not query:
        return True
    q_lower = query.lower()
    words = re.findall(r'\b\w+\b', q_lower)
    for w in words:
        if w in FORBIDDEN_OBJECT_TERMS:
            return True
    for phrase in [
        "runder tisch", "round table", "круглый стол",
        "symbolbild tisch", "close up", "nahaufnahme mikrofon"
    ]:
        if phrase in q_lower:
            return True
    return False


def extract_key_entities(text: str) -> list[str]:
    """Extract prominent names, capitalized political entities or institutions from text snippet."""
    if not text:
        return []
    cleaned = clean_query_text(text)
    # Match capitalized words with length >= 4 (German nouns / names)
    candidates = re.findall(r'\b[A-ZÄÖÜ][a-zäöüß]{3,}\b', cleaned)
    
    # Ignore common grammatical words
    stopwords = {
        "Dass", "Wenn", "Aber", "Oder", "Weil", "Denn", "Doch", "Hier", "Dort",
        "Diese", "Dieser", "Dieses", "Nach", "Seit", "Durch", "Ueber", "Unter",
        "Wurde", "Werden", "Haben", "Hatte", "Gibt", "Kann", "Konnte", "Soll",
        "Viele", "Alles", "Nicht", "Immer", "Schon", "Jetzt", "Heute", "Wieder",
        "Dabei", "Damit", "Davon", "Dazu", "Trotz", "Wegen", "Bereits",
        "Dieser", "Diese", "Dieses", "Diesen", "Diesem", "Eines", "Einem",
        "Einer", "Einen", "Keine", "Kein", "Mehr", "Sehr", "Wann", "Warum",
        "Sowie", "Wobei", "Daraus", "Hierzu", "Indem", "Gegen", "Waehrend"
    }
    
    filtered = []
    for c in candidates:
        if c not in stopwords and not contains_forbidden_objects(c):
            if c not in filtered:
                filtered.append(c)
    return filtered[:6]


def build_thematic_query_pool(
    topic: str,
    title: str = "",
    lead_story: str = "",
    segments: list[str] = None,
    count: int = 50,
) -> list[str]:
    """
    Build a comprehensive, diversified pool of high-quality thematic image search queries.
    Anchored to the video topic, headline, lead story, and key actors/institutions.
    Guarantees no repetitive queries and filters out forbidden stock objects.
    """
    topic_clean = clean_query_text(topic)
    if not topic_clean:
        topic_clean = "Aktuelle Nachrichten Deutschland"
    
    title_clean = clean_query_text(title)
    if title_clean:
        words = title_clean.split()
        if len(words) > 5:
            title_clean = " ".join(words[:5])
    else:
        title_clean = topic_clean

    lead_clean = clean_query_text(lead_story)
    
    # Extract entities from all available context
    full_context = f"{lead_clean} {title_clean}"
    if segments:
        full_context += " " + " ".join(segments[:15])
    entities = extract_key_entities(full_context)
    
    pool = []
    seen = set()

    def add_q(q_candidate: str):
        c = clean_query_text(q_candidate)
        words = [w for w in c.split() if w.lower() not in FORBIDDEN_OBJECT_TERMS]
        final_q = " ".join(words[:6])
        if len(final_q) >= 5 and not contains_forbidden_objects(final_q):
            norm = final_q.lower()
            if norm not in seen:
                seen.add(norm)
                pool.append(final_q)

    # 1. Base topic and title variations
    add_q(topic_clean)
    if title_clean and title_clean.lower() != topic_clean.lower():
        add_q(title_clean)
    if lead_clean:
        lead_words = lead_clean.split()
        if len(lead_words) >= 3:
            add_q(" ".join(lead_words[:4]))

    # 2. Add entity-anchored queries (politicians, ministries, institutions)
    short_topic = " ".join(topic_clean.split()[:2])
    for ent in entities:
        add_q(f"{ent} Politiker")
        add_q(f"{short_topic} {ent}")
        add_q(f"{ent} Pressekonferenz")
        add_q(f"{ent} Statement")

    # 3. Add thematic angle templates
    for tmpl in THEMATIC_ANGLES:
        q_str = tmpl.format(topic=short_topic, title=title_clean)
        add_q(q_str)

    # 4. In case we need more, combine top entities with actions
    action_terms = [
        "Debatte", "Entscheidung", "Kontrolle", "Beratung", "Gipfel",
        "Einsatz", "Kritik", "Ergebnisse", "Zahlen Bericht", "Protest"
    ]
    for ent in entities[:4]:
        for act in action_terms:
            add_q(f"{ent} {act}")
            if len(pool) >= count:
                break
        if len(pool) >= count:
            break

    # 5. Fill remaining with varied topic angles if needed
    for i in range(len(pool), count):
        idx = i % len(THEMATIC_ANGLES)
        add_q(f"{topic_clean} {THEMATIC_ANGLES[idx].replace('{topic}', '').replace('{title}', '').strip()}")

    return pool[:count]


def build_thematic_replacement_query(
    topic: str,
    title: str = "",
    lead_story: str = "",
    index: int = 0,
    segment_text: str = "",
) -> str:
    """
    Build a fresh, highly relevant thematic query for replacing a slide.
    Never repeats broken stock queries. Firmly anchored to the topic and headline.
    """
    topic_clean = clean_query_text(topic)
    if not topic_clean:
        topic_clean = "Aktuelle Nachrichten Deutschland"
    
    # 1. Try extracting key political/event entity from segment voiceover text
    entities = extract_key_entities(segment_text) if segment_text else []
    
    # If we found a strong entity in segment, use it with high priority
    if entities:
        entity_name = entities[0]
        words = topic_clean.split()
        short_topic = " ".join(words[:2]) if len(words) >= 2 else topic_clean
        candidate_q = f"{short_topic} {entity_name}"
        if not contains_forbidden_objects(candidate_q):
            return candidate_q

    # Shorten title to 4-5 high-impact words
    title_clean = clean_query_text(title)
    if title_clean:
        words = title_clean.split()
        if len(words) > 5:
            title_clean = " ".join(words[:5])
    else:
        title_clean = topic_clean

    # Select template angle based on index
    angle_idx = index % len(THEMATIC_ANGLES)
    template = THEMATIC_ANGLES[angle_idx]
    
    short_topic = " ".join(topic_clean.split()[:3])
    base_q = template.format(topic=short_topic, title=title_clean)
    
    clean_q = clean_query_text(base_q)
    words = [w for w in clean_q.split() if w.lower() not in FORBIDDEN_OBJECT_TERMS]
    final_q = " ".join(words[:6])
    
    if len(final_q) < 5 or contains_forbidden_objects(final_q):
        return topic_clean
    
    return final_q


def sanitize_segment_query(query: str, topic: str, title: str = "", index: int = 0) -> str:
    """
    Sanitizes any segment search query.
    If query contains forbidden words (tables, chairs, microphones, etc.) or is empty/generic,
    replaces it with an anchored thematic query.
    """
    q_clean = clean_query_text(query)
    
    # If query is corrupted by irrelevant stock items or too short
    if not q_clean or len(q_clean.split()) < 2 or contains_forbidden_objects(q_clean):
        logger.info(f"Sanitizing irrelevant query '{query}' -> anchoring to topic '{topic}'")
        return build_thematic_replacement_query(topic=topic, title=title, index=index)
    
    # Ensure query contains at least some topic context if it's very abstract
    topic_words = set(clean_query_text(topic).lower().split())
    query_words = set(q_clean.lower().split())
    
    # If completely disconnected and short (e.g. 2 generic words like "streit diskussion")
    if len(query_words) <= 2 and not (topic_words & query_words):
        main_topic_anchor = " ".join(clean_query_text(topic).split()[:2])
        return f"{main_topic_anchor} {q_clean}"
    
    return q_clean
