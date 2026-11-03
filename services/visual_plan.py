"""Keep narration, visual intent and search terms aligned."""
import re
from pathlib import Path
from services.query_helper import sanitize_segment_query, extract_topic_core, contains_forbidden_objects


def split_text_into_short_segments(text: str, max_words: int = 12, max_chars: int = 85) -> list[str]:
    """Split any paragraph into short visual segments guaranteed to be <= 6-7s narration."""
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    # Step 1: Split by sentence delimiters [.!?…]
    raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', text) if s.strip()]

    # Clause boundary pattern (colons, semicolons, dashes, commas + conjunctions, or simple commas)
    clause_pattern = re.compile(
        r'(?<=[:;—–])\s+|'
        r'(?<=,)\s+(?=(?:dass|weil|obwohl|während|wenn|da|wie|um|jedoch|sondern|aber|sowie|und|oder|welche|welcher|welches|die|der|das|den|dem|что|когда|который|если|чтобы)\b)|'
        r'(?<=,)\s+'
    , re.IGNORECASE)

    pieces = []
    for s in raw_sentences:
        s_words = s.split()
        if len(s_words) <= max_words and len(s) <= max_chars:
            pieces.append(s)
            continue

        clauses = [c.strip() for c in clause_pattern.split(s) if c.strip()]
        for c in clauses:
            c_words = c.split()
            if len(c_words) <= max_words and len(c) <= max_chars:
                pieces.append(c)
                continue

            # Sub-split long clauses by conjunctions / prepositions or word count
            sub_splits = re.split(r'\s+(?=(?:und|oder|aber|sowie|sowie auch|mit|für|durch|bei|über|in|nach|vor)\b)', c, flags=re.IGNORECASE)
            cur_chunk = ''
            for sub in sub_splits:
                sub = sub.strip()
                if not sub:
                    continue
                if cur_chunk and (len((cur_chunk + ' ' + sub).split()) > max_words or len(cur_chunk + ' ' + sub) > max_chars):
                    pieces.append(cur_chunk.strip())
                    cur_chunk = sub
                else:
                    cur_chunk = (cur_chunk + ' ' + sub).strip()
            if cur_chunk:
                pieces.append(cur_chunk.strip())

    # Final pass: Ensure strictly no piece exceeds max_words (split at ~8-10 words)
    final_segments = []
    for p in pieces:
        p_words = p.split()
        if len(p_words) <= max_words and len(p) <= max_chars:
            final_segments.append(p)
        else:
            chunk_size = min(max_words, 9)
            for i in range(0, len(p_words), chunk_size):
                final_segments.append(' '.join(p_words[i:i + chunk_size]))

    # Merge very tiny fragments (1-2 words) with previous segment if they fit
    merged = []
    for seg in final_segments:
        if merged and len(seg.split()) <= 2 and (len(merged[-1].split()) + len(seg.split()) <= max_words) and (len(merged[-1]) + len(seg) + 1 <= max_chars):
            merged[-1] = (merged[-1] + ' ' + seg).strip()
        else:
            merged.append(seg)

    return merged


def build_visual_segments(paragraphs, visual_plan, topic):
    """Build dynamic visual segments for slides, strictly capping each slide to 4-7 seconds."""
    plans = {}
    for item in visual_plan or []:
        idx = item.get('paragraph_index')
        if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(paragraphs):
            plans.setdefault(idx, item)

    segments, queries = [], []
    for idx, paragraph in enumerate(paragraphs):
        plan = plans.get(idx, {})
        base_query = plan.get('search_query') or plan.get('visual') or topic

        # Split paragraph into short segments guaranteed to not exceed 6-7 seconds (max ~12 words, ~85 chars)
        sub_segs = split_text_into_short_segments(paragraph, max_words=12, max_chars=85)
        for sub_idx, sub_text in enumerate(sub_segs):
            segments.append(sub_text)
            if sub_idx == 0:
                queries.append(base_query)
            else:
                sub_q = sanitize_segment_query(base_query, topic=topic, index=sub_idx, segment_text=sub_text)
                queries.append(sub_q or base_query)

    return segments, queries


def search_queries(query, topic, context, index=0):
    def clean(value):
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\säöüÄÖÜß-]', ' ', value)).strip()

    raw_q = clean(query)
    if contains_forbidden_objects(raw_q):
        primary = sanitize_segment_query(raw_q, topic=topic, index=index, segment_text=context)
    else:
        primary = ' '.join(raw_q.split()[:8])

    anchor = extract_topic_core(topic) if len(clean(topic).split()) > 4 else ' '.join(clean(topic).split()[:5])
    alt_scene = sanitize_segment_query("", topic=topic, index=index + 3, segment_text=context)

    candidates = [primary, f'{primary} {anchor}'.strip(), alt_scene, anchor]
    # Concrete thematic fallback; never inject police/borders into unrelated topics.
    if re.search(r'rent[en]|pension|пенси', topic + ' ' + context, re.I):
        candidates.insert(1, 'Deutsche Rentenversicherung Beratung Senioren Deutschland')
    return list(dict.fromkeys(q for q in candidates if q))[:3]


def make_text_card(path, topic, text):
    """Render only supplied narration, never invent numbers or charts."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = [str(p) for p in (Path(__file__).resolve().parents[1] / 'fonts').glob('*.ttf')]
    fonts += ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              'C:/Windows/Fonts/arial.ttf']
    font_path = next((p for p in fonts if Path(p).is_file()), None)
    if not font_path:
        raise RuntimeError('Для текстовых карточек установите шрифт DejaVu Sans.')
    image = Image.new('RGB', (1920, 1080), '#101c2e')
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 110, 112, 790), fill='#47c7bd')
    header = ImageFont.truetype(font_path, 32)
    # No possibly misleading clipped topic; use a neutral section label.
    draw.text((150, 110), 'NEWS | KONTEXT', font=header, fill='#47c7bd')
    for size in range(58, 23, -2):
        font = ImageFont.truetype(font_path, size)
        lines, line = [], ''
        for word in text.split():
            candidate = (line + ' ' + word).strip()
            if line and draw.textlength(candidate, font=font) > 1600:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines) * (size + 18) <= 590:
            break
    if len(lines) * (size + 18) > 590:
        raise ValueError('Слишком длинный фрагмент для читаемой карточки.')
    for i, line in enumerate(lines):
        draw.text((150, 225 + i * (size + 18)), line, font=font, fill='#f4f7fb')
    # Keep bottom clear for narration subtitles.
    image.save(path)
    return str(path)
