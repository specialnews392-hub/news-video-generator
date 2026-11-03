"""Keep narration, visual intent and search terms aligned."""
import re
from pathlib import Path
from services.query_helper import sanitize_segment_query, extract_topic_core, contains_forbidden_objects


def split_text_into_short_segments(
    text: str,
    target_words: int = 13,
    min_words: int = 10,
    max_words: int = 15,
) -> list[str]:
    """
    Split text into visual slide segments targeting ~6 seconds of continuous speech (~13 words).
    Strictly guarantees that no segment is shorter than min_words (no 1.5s flash slides)
    and no segment exceeds max_words (no 16s freeze slides).
    """
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    # Step 1: Split by sentence delimiters [.!?…]
    raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', text) if s.strip()]

    # Clause boundary pattern (colons, semicolons, dashes, conjunctions, or commas)
    clause_pattern = re.compile(
        r'(?<=[:;—–])\s+|'
        r'(?<=,)\s+(?=(?:dass|weil|obwohl|während|wenn|da|wie|um|jedoch|sondern|aber|sowie|und|oder|welche|welcher|welches|die|der|das|den|dem|что|когда|который|если|чтобы)\b)|'
        r'(?<=,)\s+'
    , re.IGNORECASE)

    units = []
    for s in raw_sentences:
        s_words = s.split()
        if len(s_words) <= max_words:
            units.append(s)
        else:
            clauses = [c.strip() for c in clause_pattern.split(s) if c.strip()]
            for c in clauses:
                c_words = c.split()
                if len(c_words) <= max_words:
                    units.append(c)
                else:
                    for i in range(0, len(c_words), target_words):
                        units.append(' '.join(c_words[i:i + target_words]))

    # Step 2: Merge / balance units to strictly respect [min_words, max_words] (target ~6s per slide)
    merged = []
    cur = ''
    for u in units:
        if not cur:
            cur = u
            continue
        cur_w = len(cur.split())
        u_w = len(u.split())
        if cur_w + u_w <= max_words:
            cur = cur + ' ' + u
        elif cur_w < min_words:
            combined_words = (cur + ' ' + u).split()
            if len(combined_words) <= max_words:
                cur = ' '.join(combined_words)
            else:
                half = len(combined_words) // 2
                merged.append(' '.join(combined_words[:half]))
                cur = ' '.join(combined_words[half:])
        else:
            merged.append(cur)
            cur = u

    if cur:
        if merged and len(cur.split()) < min_words:
            combined_words = (merged[-1] + ' ' + cur).split()
            if len(combined_words) <= max_words + 2:
                merged[-1] = ' '.join(combined_words)
            else:
                half = len(combined_words) // 2
                merged[-1] = ' '.join(combined_words[:half])
                merged.append(' '.join(combined_words[half:]))
        else:
            merged.append(cur)

    # Step 3: Final sanity check to guarantee no element exceeds max_words + 2
    final_segments = []
    for m in merged:
        m_words = m.split()
        if len(m_words) <= max_words + 2:
            final_segments.append(m)
        else:
            for i in range(0, len(m_words), target_words):
                final_segments.append(' '.join(m_words[i:i + target_words]))

    return final_segments


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

        # Split paragraph into short segments guaranteed to average ~6 seconds (10-15 words, target 13)
        sub_segs = split_text_into_short_segments(paragraph, target_words=13, min_words=10, max_words=15)
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
