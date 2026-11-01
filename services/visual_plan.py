"""Keep narration, visual intent and search terms aligned."""
import re
from pathlib import Path
from services.query_helper import sanitize_segment_query, extract_topic_core, contains_forbidden_objects


def build_visual_segments(paragraphs, visual_plan, topic):
    plans = {}
    for item in visual_plan or []:
        idx = item.get('paragraph_index')
        if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(paragraphs):
            plans.setdefault(idx, item)
    segments, queries = [], []
    for idx, paragraph in enumerate(paragraphs):
        plan = plans.get(idx, {})
        query = plan.get('search_query') or plan.get('visual') or topic
        # Keep complete sentences together: avoid illustrating isolated clauses.
        group = ''
        for sentence in re.split(r'(?<=[.!?…])\s+', paragraph.strip()):
            if group and len(group) + len(sentence) > 160:
                segments.append(group)
                queries.append(query)
                group = ''
            group = (group + ' ' + sentence).strip()
        if group:
            segments.append(group)
            queries.append(query)
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
