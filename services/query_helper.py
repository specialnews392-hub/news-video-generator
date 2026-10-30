"""
Query Helper - Thematic query sanitization and context anchoring.
Guarantees that image queries strictly reflect real documentary/editorial scenes,
completely eliminating irrelevant objects (tables, chairs, sofas, microphones, diagrams,
charts, scanned forms, ID cards, laptops, YouTube logos, grammar tables, etc.).
Provides an extensive pool of diverse, sharp visual queries for video generation and replacement.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Forbidden words that produce irrelevant stock photos, office furniture, stationery, forms, or charts
FORBIDDEN_OBJECT_TERMS = {
    # German furniture / office objects
    "tisch", "tische", "runder tisch", "stuhl", "stühle", "buerostuhl", "bürostuhl",
    "sofa", "sofas", "couch", "sessel", "möbel", "moebel", "einrichtung", "wartezimmer",
    "schreibtisch", "büro", "buero", "bueroraum", "büroraum", "arbeitsplatz", "besprechungsraum",
    # Audio / tech / screens / gaming
    "mikrofon", "mikrofone", "mikro", "laptop", "computer", "pc", "tastatur",
    "bildschirm", "monitor", "display", "smartphone", "handy", "telefon",
    "gaming", "videospiel", "videospiele", "konsole",
    # Charts / maps / stats
    "diagramm", "diagramme", "grafik", "grafiken", "statistik", "statistiken",
    "tabelle", "tabellen", "balkendiagramm", "kurvendiagramm", "chart", "charts",
    "prozent", "umfrage", "karte", "landkarte", "skala", "kurve", "infografik",
    # Documents / forms / IDs / signs
    "ordner", "aktenordner", "akten", "aktenstapel", "papier", "papiere", "dokument", "dokumente",
    "formular", "attest", "krankmeldung", "arbeitsunfähigkeit", "arbeitsunfähigkeitsbescheinigung",
    "bescheinigung", "ausweis", "personalausweis", "pass", "reisepass", "antrag", "vertrag",
    "schild", "plakat", "zettel", "brief", "unterschrift",
    # Generic closeups & YouTube / social media
    "nahaufnahme", "detailaufnahme", "hände", "haende", "hand", "kugelschreiber", "stift",
    "leerer raum", "symbolbild", "youtube", "abspann", "kanal", "abo", "abonnieren",
    "logo", "icon", "banner", "thumbnail",

    # English
    "table", "tables", "round table", "chair", "chairs", "desk", "office chair", "sofa", "couch",
    "microphone", "microphones", "mic", "laptop", "computer", "keyboard", "screen", "monitor",
    "diagram", "diagrams", "chart", "charts", "graph", "graphs", "statistics", "map",
    "table sheet", "spreadsheet", "folder", "folders", "paper", "papers", "document", "form",
    "office", "close up table", "close up mic", "hands", "pen", "id card", "passport",

    # Russian
    "стол", "столы", "круглый стол", "стул", "стулья", "кресло", "диван", "мебель",
    "микрофон", "микрофоны", "ноутбук", "компьютер", "клавиатура", "экран", "монитор",
    "диаграмма", "диаграммы", "график", "графики", "статистика", "статистики", "карта",
    "таблица", "таблицы", "папка", "папки", "бумага", "бумаги", "документ", "справка", "бланк",
    "кабинет", "офис", "ручка", "руки", "крупный план стол", "крупный план микрофон",
}

# Conversational / grammatical stopwords that must NEVER be sent to image search engines
CONVERSATIONAL_STOPWORDS = {
    "wenn", "dann", "weil", "denn", "deshalb", "obwohl", "dass", "aber", "oder", "doch",
    "sind", "ist", "war", "waren", "wird", "werden", "wurde", "wurden", "haben", "hat", "hatte",
    "viele", "viel", "mehr", "weniger", "irgendwann", "überlastet", "ueberlastet",
    "dieser", "diese", "dieses", "diesem", "diesen", "jeder", "jede", "jedes",
    "nicht", "kein", "keine", "keinen", "schon", "noch", "immer", "wieder", "heute", "jetzt",
    "warum", "wieso", "weshalb", "wie", "was", "wer", "wo", "wann", "welche", "welcher",
    "alle", "alles", "allen", "einer", "eine", "einen", "einem", "eines", "der", "die", "das",
    "und", "in", "im", "an", "am", "auf", "aus", "bei", "mit", "nach", "von", "vor", "zu", "zum", "zur",
    "für", "fuer", "über", "ueber", "unter", "durch", "gegen", "ohne", "um", "so", "es", "sie", "wir", "ihr",
}

# Semantic mapping from problematic query themes to authentic photojournalistic scenes
SCENE_REPLACEMENT_RULES = [
    (r"wartezimmer|arztpraxis|patient|attest|krankmeldung|arbeitsunfähigkeit|aok|krankenkasse|kassensitz",
     [
         "Arzt Patient Gespräch Behandlung Klinik Deutschland",
         "Krankenhaus Ärzte Pflegepersonal Station Deutschland",
         "Medizinische Untersuchung Arztpraxis Gesundheit Deutschland",
         "Klinik Personal Ärzte Visite Krankenhaus Deutschland",
     ]),
    (r"psychotherapie|therapie|psycholog|depression|beratung|familie|eltern|kind",
     [
         "Psychologe Beratung Gespräch Praxis Deutschland",
         "Sozialberatung Familie Unterstützung Gespräch Deutschland",
         "Gesprächstherapie Ärztin Patientin Beratung Deutschland",
     ]),
    (r"sofa|couch|erschöpft|müde|erholung|feierabend|stress|belastung",
     [
         "Pendler Bahnhof Feierabend Menschenmenge Deutschland",
         "Passanten Fußgängerzone Alltag Stadt Deutschland",
         "Arbeitnehmer Pause Großstadt Straße Deutschland",
     ]),
    (r"büro|schreibtisch|akten|dokument|arbeitsplatz|mitarbeiter|arbeitnehmer|besprechung|unternehmen|betrieb",
     [
         "Mitarbeiter Team Diskussion Unternehmen Deutschland",
         "Arbeitnehmer Produktion Werkhalle Industrie Deutschland",
         "Konferenz Gespräch Kollegen Arbeitswelt Deutschland",
         "Fachkräfte Arbeit Handwerk Industrie Deutschland",
     ]),
    (r"sozialsystem|rente|bürgergeld|haushalt|regierung|politik|bundestag|krise|reform",
     [
         "Bundestag Plenarsaal Debatte Politiker Berlin",
         "Reichstag Regierungsviertel Berlin Politik Deutschland",
         "Bundesregierung Pressekonferenz Statement Berlin",
         "Passanten Bürger Innenstadt Deutschland Alltag",
     ]),
    (r"prozent|grafik|diagramm|tabelle|umfrage|statistik|karte|zahlen",
     [
         "Menschen Fußgängerzone Einkaufsstraße Deutschland Alltag",
         "Bürger Öffentlichkeit Stadtzentrum Deutschland",
         "Arbeitnehmer Pendler Stadtverkehr Deutschland",
     ]),
    (r"youtube|abspann|kanal|abo|bildschirm|computer|gaming|videospiel",
     [
         "Journalisten Nachrichtenredaktion Fernsehstudio Deutschland",
         "IT Spezialisten Entwickler Team Technologie Deutschland",
         "Medien Redaktion Arbeit Nachrichten Deutschland",
     ]),
]

# Diverse documentary/editorial visual angles
THEMATIC_ANGLES = [
    "{topic} Bundestag Debatte Berlin",
    "{topic} Bürger Innenstadt Deutschland",
    "{topic} Pressekonferenz Politiker Berlin",
    "Arzt Patient Behandlung Klinik Deutschland",
    "Arbeitnehmer Industrie Werkhalle Deutschland",
    "Krankenhaus Pflegepersonal Ärzte Deutschland",
    "Passanten Fußgängerzone Großstadt Deutschland",
    "Bundestag Regierungsviertel Berlin Politik",
    "Mitarbeiter Team Besprechung Unternehmen Deutschland",
    "Pendler Bahnhof Stadtverkehr Deutschland",
    "Soziale Arbeit Ehrenamt Hilfe Deutschland",
    "Senioren Bürger Alltag Stadt Deutschland",
    "Kanzleramt Berlin Regierung Politik",
    "Fachkräfte Handwerk Produktion Deutschland",
    "Rathaus Behörde Bürgeramt Deutschland",
    "Klinik Ambulanz Medizinische Versorgung Deutschland",
]


def clean_query_text(text: str) -> str:
    """Strip special chars, markdown artifacts, punctuation."""
    if not text:
        return ""
    cleaned = re.sub(r'[*#_`!?:;\"\'«»(){}\[\],.—–-]', ' ', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def extract_topic_core(topic: str) -> str:
    """
    Extract concrete German nouns/entities from a potentially conversational headline.
    For example: 'Wenn es so viele sind, dann ist das Sozialsystem irgendwann überlastet'
    -> 'Sozialsystem Deutschland'
    """
    cleaned = clean_query_text(topic)
    if not cleaned:
        return "Deutschland Politik Gesellschaft"

    # Find capitalized words (German nouns) that aren't conversational stopwords or forbidden objects
    nouns = []
    for w in cleaned.split():
        w_low = w.lower()
        if len(w) >= 4 and w[0].isupper() and w_low not in CONVERSATIONAL_STOPWORDS and w_low not in FORBIDDEN_OBJECT_TERMS:
            if w not in nouns:
                nouns.append(w)

    if nouns:
        core = " ".join(nouns[:3])
        if "deutschland" not in core.lower() and "berlin" not in core.lower():
            core = f"{core} Deutschland"
        return core

    return "Deutschland Gesellschaft Politik"


def contains_forbidden_objects(query: str) -> bool:
    """Check if query contains any forbidden inanimate object words or conversational clauses."""
    if not query:
        return True
    q_lower = query.lower()
    words = re.findall(r'\b\w+\b', q_lower)
    if not words:
        return True

    for w in words:
        if w in FORBIDDEN_OBJECT_TERMS:
            return True

    # Reject if query starts with conversational conjunctions ("Wenn es so...", "Weil...", etc.)
    if words[0] in {"wenn", "weil", "obwohl", "dass", "warum", "wieso", "wie"}:
        return True

    # Reject if more than half of words are conversational stopwords
    stop_count = sum(1 for w in words if w in CONVERSATIONAL_STOPWORDS)
    if len(words) >= 5 and stop_count >= len(words) // 2:
        return True

    for phrase in [
        "runder tisch", "round table", "круглый стол",
        "symbolbild tisch", "close up", "nahaufnahme mikrofon",
        "youtube kanal", "abspann"
    ]:
        if phrase in q_lower:
            return True
    return False


def extract_key_entities(text: str) -> list[str]:
    """Extract prominent names, capitalized political entities or institutions from text snippet."""
    if not text:
        return []
    cleaned = clean_query_text(text)
    candidates = re.findall(r'\b[A-ZÄÖÜ][a-zäöüß]{3,}\b', cleaned)

    filtered = []
    for c in candidates:
        c_low = c.lower()
        if c_low not in CONVERSATIONAL_STOPWORDS and c_low not in FORBIDDEN_OBJECT_TERMS:
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
    Build a comprehensive, diversified pool of high-quality photojournalistic search queries.
    """
    core_topic = extract_topic_core(topic or title)
    short_noun = core_topic.split()[0] if core_topic else "Deutschland"

    pool = []
    seen = set()

    def add_q(q_candidate: str):
        c = clean_query_text(q_candidate)
        words = [w for w in c.split() if w.lower() not in FORBIDDEN_OBJECT_TERMS and w.lower() not in CONVERSATIONAL_STOPWORDS]
        final_q = " ".join(words[:6])
        if len(final_q) >= 5 and not contains_forbidden_objects(final_q):
            norm = final_q.lower()
            if norm not in seen:
                seen.add(norm)
                pool.append(final_q)

    # 1. Add all journalistic scene replacements
    for _, scenes in SCENE_REPLACEMENT_RULES:
        for sc in scenes:
            add_q(sc)

    # 2. Add thematic angle templates
    for tmpl in THEMATIC_ANGLES:
        add_q(tmpl.format(topic=short_noun, title=core_topic))

    # 3. Extract entities from context
    full_context = f"{lead_story} {title}"
    if segments:
        full_context += " " + " ".join(segments[:15])
    entities = extract_key_entities(full_context)
    for ent in entities[:5]:
        add_q(f"{ent} Deutschland Foto")
        add_q(f"{ent} Politik Bürger Deutschland")

    while len(pool) < count and pool:
        pool.append(pool[len(pool) % len(pool)])

    return pool[:count]


def build_thematic_replacement_query(
    topic: str,
    title: str = "",
    lead_story: str = "",
    index: int = 0,
    segment_text: str = "",
    raw_query: str = "",
) -> str:
    """
    Build a fresh, photojournalistic query for a slide, matching segment context first.
    """
    combined_hint = f"{raw_query} {segment_text}".lower()
    for pattern, scenes in SCENE_REPLACEMENT_RULES:
        if re.search(pattern, combined_hint, re.I):
            return scenes[index % len(scenes)]

    core_topic = extract_topic_core(topic or title)
    short_noun = core_topic.split()[0] if core_topic else "Deutschland"
    tmpl = THEMATIC_ANGLES[index % len(THEMATIC_ANGLES)]
    return tmpl.format(topic=short_noun, title=core_topic)


def sanitize_segment_query(query: str, topic: str, title: str = "", index: int = 0, segment_text: str = "") -> str:
    """
    Sanitizes any segment search query.
    If query contains forbidden words (sofas, desks, charts, documents, YouTube, conversational sentences),
    replaces it with a concrete documentary photo scene query.
    """
    q_clean = clean_query_text(query)

    # Check if query matches any problematic scene rule or forbidden object
    if not q_clean or len(q_clean.split()) < 2 or contains_forbidden_objects(q_clean):
        new_q = build_thematic_replacement_query(
            topic=topic, title=title, index=index, segment_text=segment_text, raw_query=q_clean
        )
        logger.info(f"Sanitizing query '{query}' -> '{new_q}'")
        return new_q

    # Strip any remaining conversational stopwords from the query
    clean_words = [w for w in q_clean.split() if w.lower() not in CONVERSATIONAL_STOPWORDS and w.lower() not in FORBIDDEN_OBJECT_TERMS]
    if len(clean_words) < 2:
        return build_thematic_replacement_query(
            topic=topic, title=title, index=index, segment_text=segment_text, raw_query=q_clean
        )

    return " ".join(clean_words[:6])
