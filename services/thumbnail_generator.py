"""
Thumbnail Generator - Creates YouTube thumbnails using Pillow.
"""
import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

import config

logger = logging.getLogger(__name__)

# Try to find system fonts
# Try to find system fonts (Arial Black is king for YouTube thumbnails)
FONT_PATHS = [
    # Linux paths
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
    # Windows paths
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

def _get_font(size: int = 60, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Get the best available font."""
    for font_path in FONT_PATHS:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue
    
    # Check fonts directory
    fonts_dir = config.FONTS_DIR
    for font_file in fonts_dir.glob("*.ttf"):
        try:
            return ImageFont.truetype(str(font_file), size)
        except:
            continue
    
    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        current_line.append(word)
        line_text = " ".join(current_line)
        bbox = font.getbbox(line_text)
        line_width = bbox[2] - bbox[0]
        
        if line_width > max_width:
            if len(current_line) > 1:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(line_text)
                current_line = []
    
    if current_line:
        lines.append(" ".join(current_line))
    
    return lines


def clean_badge_topic(topic: str) -> str:
    """
    Format a clean, concise topic badge for thumbnails without source names.
    Strips trailing media outlet names like ' - Tagesschau', ' - Welt', ' - РИА Новости', etc.
    """
    if not topic:
        return ""
    
    t = str(topic).strip()
    if not t:
        return ""
    
    # 1. Strip trailing sources after dash / em-dash / en-dash / pipe / slash
    t = re.sub(
        r'\s*[-–—|/]\s*(tagesschau|spiegel|der spiegel|welt|die welt|focus|focus online|bild|n-tv|ntv|zdf|zdf heute|faz|sz|süddeutsche|zeit|die zeit|stern|rtl|t-online|handelsblatt|dpa|reuters|afp|ap|ria|риа|риа новости|lenta|lenta\.ru|тасс|интерфакс|коммерсантъ|ведомости|rambler|газета\.ru|известия|сми|google news|[a-zа-я0-9\s.]{2,24})\s*$',
        '',
        t,
        flags=re.IGNORECASE
    ).strip()
    
    # Generic strip of trailing dash followed by 1-3 words (outlet names)
    t = re.sub(r'\s+[-–—|]\s+[A-Za-zА-Яа-я0-9.\s]{2,25}$', '', t).strip()
    
    # 2. Strip leading source if followed by colon (e.g., "BILD: ...", "РИА: ...")
    t = re.sub(
        r'^(tagesschau|spiegel|welt|focus|bild|n-tv|zdf|faz|sz|zeit|риа новости|lenta|тасс|интерфакс|коммерсантъ)\s*:\s*',
        '',
        t,
        flags=re.IGNORECASE
    ).strip()
    
    # 3. Clean up trailing colons, semicolons, dashes
    t = re.sub(r'[\s:;&|–—\-,]+$', '', t).strip()
    
    # 4. If still longer than 30 chars, shorten to key topic
    if len(t) > 30:
        if ":" in t:
            parts = [p.strip() for p in t.split(":") if p.strip()]
            if parts and len(parts[0]) >= 4 and len(parts[0]) <= 28:
                t = parts[0]
            elif len(parts) > 1 and len(parts[1]) <= 28:
                t = parts[1]
        if len(t) > 28:
            words = t.split()
            if len(words) > 3:
                shortened = " ".join(words[:3])
                t = shortened if len(shortened) <= 28 else " ".join(words[:2])
                
    t = t.strip()
    return t.upper() if t else ""


def generate_thumbnail(
    title: str,
    topic: str = "",
    show_badge: bool = True,
    background_image_path: str = None,
    output_path: str | Path = None,
    theme: str = "default",
    font_size: int = None,
    text_x: int = None,
    text_y: int = None,
    text_align: str = "left",
    flip_horizontal: bool = False,
) -> str:
    """
    Generate a professional YouTube thumbnail (1280x720).
    - Subject/face remains clear, sharp and bright
    - Smooth dark gradient behind text for maximum contrast
    - Bold punchy typography (Arial Black) with multi-color emphasis
    - Optional category pill badge (can be hidden or cleared)
    - Full custom positioning (text_x, text_y, text_align, font_size, flip_horizontal)
    """
    width = config.THUMBNAIL_WIDTH
    height = config.THUMBNAIL_HEIGHT
    
    colors = config.THEME_COLORS.get(theme, config.THEME_COLORS["default"])
    accent = _hex_to_rgb(colors.get("accent", "#E50914"))
    
    if output_path is None:
        output_path = config.OUTPUT_DIR / "thumbnail.jpg"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Base Image: scale & crop to cover 1280x720
    if background_image_path and Path(background_image_path).exists():
        try:
            img = Image.open(background_image_path).convert("RGB")
            iw, ih = img.size
            scale = max(width / iw, height / ih)
            nw, nh = int(iw * scale), int(ih * scale)
            img = img.resize((nw, nh), Image.LANCZOS)
            
            # Crop slightly towards top-center where faces usually reside
            left = max(0, (nw - width) // 2)
            top = max(0, int((nh - height) * 0.3))
            img = img.crop((left, top, left + width, top + height))
            
            # Optional horizontal mirror
            if flip_horizontal:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            
            # Subtle contrast and color boost for punchy look
            img = ImageEnhance.Contrast(img).enhance(1.15)
            img = ImageEnhance.Color(img).enhance(1.12)
        except Exception as e:
            logger.warning(f"Failed to process background image: {e}")
            img = _create_gradient_background(width, height)
    else:
        img = _create_gradient_background(width, height)
        
    is_finance = (theme in ["finance_de", "economy_de"] or any(k in (str(topic) + " " + str(title)).lower() for k in ["rente", "bürgergeld", "steuer", "finanz", "wirtschaft", "gehalt", "kosten", "euro", "inflation"]))
    fade_color = (7, 20, 42) if is_finance else (8, 10, 15)

    # 2. Gradient Overlay: Position dark backing behind text
    is_text_on_right = (text_align == "right" and (text_x is None or text_x > 600)) or (text_x is not None and text_x > 640)
    is_text_centered = (text_align == "center" and text_x is not None and 350 <= text_x <= 930)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    
    if is_text_on_right:
        # Right dark fade
        fade_w = 820
        for x in range(width - fade_w, width):
            t = (width - x) / float(fade_w)
            alpha = int(248 * ((1.0 - t) ** 1.3))
            ov_draw.line([(x, 0), (x, height)], fill=(*fade_color, alpha))
        if is_finance:
            ov_draw.rectangle([(width - 6, 0), (width, height)], fill=(16, 185, 129, 230))
    elif is_text_centered:
        # Center vignette
        cx = text_x if text_x is not None else width // 2
        for x in range(width):
            dist = abs(x - cx) / float(width * 0.5)
            alpha = int(210 * max(0.0, 1.0 - dist * 0.9))
            ov_draw.line([(x, 0), (x, height)], fill=(*fade_color, alpha))
    else:
        # Left dark fade: from x=0 (alpha 248) to x=790 (alpha 0)
        for x in range(790):
            t = x / 790.0
            alpha = int(248 * ((1.0 - t) ** 1.3))
            ov_draw.line([(x, 0), (x, height)], fill=(*fade_color, alpha))
        if is_finance:
            ov_draw.rectangle([(0, 0), (6, height)], fill=(16, 185, 129, 230))

    # Top & bottom subtle vignette
    for y in range(90):
        alpha = int(120 * (1.0 - y / 90.0))
        ov_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    for y in range(height - 110, height):
        alpha = int(160 * ((y - (height - 110)) / 110.0))
        ov_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        
    base = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)
    
    # 3. Topic Badge (Optional, can be disabled or empty)
    cleaned_topic = clean_badge_topic(topic) if topic else ""
    has_badge = bool(show_badge and cleaned_topic)
    by = 48
    bh = 0
    if has_badge:
        badge_font = _get_font(size=24, bold=True)
        if is_finance:
            low = (str(topic) + " " + str(title)).lower()
            if "rente" in low:
                topic_text = "● RENTE 2026"
            elif "bürgergeld" in low:
                topic_text = "● BÜRGERGELD"
            elif "steuer" in low:
                topic_text = "● STEUER-REFORM"
            elif "inflation" in low or "preis" in low:
                topic_text = "● PREIS-SCHOCK"
            elif "gehalt" in low or "arbeit" in low or "job" in low:
                topic_text = "● ARBEIT & GEHALT"
            else:
                topic_text = "● WIRTSCHAFT & FINANZEN"
            badge_bg = (4, 120, 87)  # Deep Emerald
        else:
            topic_text = f"● {cleaned_topic}" if not cleaned_topic.startswith("●") else cleaned_topic
            badge_bg = accent

        bb = badge_font.getbbox(topic_text)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        pad_x = 22
        pad_y = 11
        bw = tw + pad_x * 2
        bh = th + pad_y * 2
        
        if is_text_on_right:
            bx = width - bw - 60
        elif is_text_centered:
            bx = (width - bw) // 2
        else:
            bx = 60
            
        draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=8, fill=badge_bg)
        if is_finance:
            draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=8, outline=(245, 158, 11), width=2)
        tx = bx + pad_x - bb[0]
        ty = by + pad_y - bb[1]
        draw.text((tx, ty), topic_text, font=badge_font, fill=(255, 255, 255))
    
    # 4. Title Typography
    clean_title = title.strip().upper()
    max_text_w = 1100 if is_text_centered else 760
    
    lines = []
    title_font = None
    chosen_font_size = 56
    
    if font_size and int(font_size) > 0:
        chosen_font_size = max(24, min(140, int(font_size)))
        title_font = _get_font(size=chosen_font_size, bold=True)
        lines = _wrap_text(clean_title, title_font, max_text_w)
    else:
        # Auto-scale font size so text fits comfortably in 2 to 4 lines with massive size!
        for candidate_size in [96, 88, 80, 72, 64, 56, 48, 42, 36, 32]:
            f = _get_font(size=candidate_size, bold=True)
            wrapped = _wrap_text(clean_title, f, max_text_w)
            cand_line_h = int(candidate_size * 1.22)
            total_cand_h = len(wrapped) * cand_line_h
            max_line_w = max((f.getbbox(l)[2] - f.getbbox(l)[0]) for l in wrapped) if wrapped else 0
            if len(wrapped) <= 4 and total_cand_h <= (height - 160) and max_line_w <= max_text_w:
                if len(wrapped) <= 3 or candidate_size <= 68:
                    lines = wrapped
                    title_font = f
                    chosen_font_size = candidate_size
                    break
                
        if not lines:
            chosen_font_size = 36
            title_font = _get_font(size=chosen_font_size, bold=True)
            lines = _wrap_text(clean_title, title_font, max_text_w)[:4]
        
    line_h = int(chosen_font_size * 1.22)
    total_h = len(lines) * line_h
    
    # Vertical positioning
    if text_y is not None:
        y_start = max(20, min(height - total_h - 20, int(text_y)))
    else:
        y_top_limit = (by + bh + 25) if (has_badge and not is_text_on_right) else 35
        y_start = max(y_top_limit, (height - total_h) // 2 + 10)
    
    # Alternating colors: Gold / White / Mint for finance, or Yellow / White for general news
    if is_finance:
        if len(lines) == 4:
            palette = [(245, 158, 11), (255, 255, 255), (52, 211, 153), (255, 255, 255)]
        elif len(lines) == 3:
            palette = [(245, 158, 11), (255, 255, 255), (52, 211, 153)]
        else:
            palette = [(245, 158, 11), (255, 255, 255)]
    else:
        if len(lines) == 4:
            palette = [(255, 222, 0), (255, 255, 255), (255, 222, 0), (255, 255, 255)]
        elif len(lines) == 3:
            palette = [(255, 222, 0), (255, 255, 255), (255, 255, 255)]
        else:
            palette = [(255, 222, 0), (255, 255, 255)]
    
    outline_r = max(3, int(chosen_font_size * 0.075))

    for i, line in enumerate(lines):
        bb = title_font.getbbox(line)
        lw = bb[2] - bb[0]
        
        if text_x is not None:
            if text_align == "center":
                lx = int(text_x - lw / 2)
            elif text_align == "right":
                lx = int(text_x - lw)
            else:
                lx = int(text_x)
        else:
            if text_align == "center":
                lx = (width - lw) // 2
            elif text_align == "right":
                lx = width - lw - 60
            else:
                lx = 60
                
        lx = max(20, min(width - lw - 20, lx))
        ly = y_start + i * line_h
        text_color = palette[i % len(palette)]
        
        # Deep drop shadow
        draw.text((lx + 5, ly + 6), line, font=title_font, fill=(0, 0, 0))
        draw.text((lx + 4, ly + 5), line, font=title_font, fill=(0, 0, 0))
        
        # Thick outline for maximum contrast on mobile YouTube feed
        for dx in range(-outline_r, outline_r + 1):
            for dy in range(-outline_r, outline_r + 1):
                if dx * dx + dy * dy <= outline_r * outline_r:
                    draw.text((lx + dx, ly + dy), line, font=title_font, fill=(0, 0, 0))
                    
        # Foreground text
        draw.text((lx, ly), line, font=title_font, fill=text_color)
        
    # Save high quality thumbnail
    base.save(str(output_path), quality=95)
    logger.info(f"Professional thumbnail generated ({chosen_font_size}pt, {len(lines)} lines, badge={has_badge}): {output_path}")
    return str(output_path)


def _create_gradient_background(width: int, height: int) -> Image.Image:
    """Create a dark, moody background for news."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    color1 = (10, 16, 26)
    color2 = (28, 38, 56)
    for y in range(height):
        t = y / height
        r = int(color1[0] + (color2[0] - color1[0]) * t)
        g = int(color1[1] + (color2[1] - color1[1]) * t)
        b = int(color1[2] + (color2[2] - color1[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def build_thumbnail_art_director_prompt(
    topic: str,
    title: str,
    verified_facts: str | list[str] = "",
    central_question: str = "",
    script_summary: str = "",
) -> str:
    """
    Format a high-converting art-director prompt for generating YouTube thumbnail concepts
    following German news channel standards.
    """
    if isinstance(verified_facts, (list, tuple)):
        clean_facts = [str(f).strip() for f in verified_facts if str(f).strip()]
        if clean_facts:
            verified_facts_str = "\n".join(f"— {f}" for f in clean_facts)
        else:
            verified_facts_str = "Подтвержденные факты из проверенных первоисточников выпуска."
    else:
        verified_facts_str = str(verified_facts).strip() or "Подтвержденные факты из проверенных первоисточников выпуска."

    if not central_question:
        central_question = f"В чем реальная причина и последствия события: {topic}?"

    if not script_summary:
        script_summary = f"Аналитический разбор темы «{topic}» и ее влияния на жизнь обычных людей."

    prompt_template = f"""Ты арт-директор немецкого новостного YouTube-канала. Разработай обложку с сильным кликовым потенциалом, которая вызывает любопытство и точно соответствует содержанию ролика.

ВХОДНЫЕ ДАННЫЕ:
Тема: {topic}
Заголовок ролика: {title}
Проверенные факты:
{verified_facts_str}
Главный конфликт или вопрос: {central_question}
Содержание и итоговый вывод: {script_summary}

ЗАДАЧА:
Предложи 3 существенно разные концепции:
1. Последствие для обычного человека.
2. Конфликт между обещанием и фактическим результатом.
3. Неожиданная цифра или важное ограничение.

Выбери наиболее сильную концепцию. Не обещай того, чего нет в видео.

ПРАВИЛА:
— Одна центральная мысль, понятная за секунду.
— Один главный герой или объект; второй — только для необходимого противопоставления.
— Крупный план, выразительная композиция, простая иерархия.
— Контрастный фон, ограниченная палитра, один яркий акцент.
— Оставь свободную область под крупную надпись.
— Надпись: 2–4 коротких немецких слова, естественных для носителя языка.
— Надпись должна дополнять заголовок, а не повторять его.
— Предпочитай конкретный смысл общим словам SCHOCK, HAMMER, SKANDAL.
— Вопрос допустим, только если видео действительно разбирает его.
— Цифры, суммы и даты используй исключительно из проверенных фактов.
— Не изображай вымышленные аресты, нападения, документы, цитаты или действия реальных людей.
— Не создавай впечатление документального кадра события, которого не было.
— Не используй мелкий текст, множество флагов, стрелок и лиц.
— Не размещай важные элементы в правом нижнем углу: там отображается длительность.

ФОРМАТ ОТВЕТА:
Для каждой концепции:
• идея;
• надпись на немецком;
• перевод на русский;
• почему зритель захочет открыть ролик;
• какой фрагмент сценария выполняет обещание обложки.

Затем для выбранной концепции выдай:
• IMAGE_PROMPT: подробное задание генератору изображения для YouTube-обложки 16:9, без текста и водяных знаков;
• OVERLAY_TEXT: точная немецкая надпись;
• TEXT_POSITION: расположение надписи;
• FACT_CHECK: подтверждение, что визуальное обещание соответствует фактам."""
    return prompt_template

