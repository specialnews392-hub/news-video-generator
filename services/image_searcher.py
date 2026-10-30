"""
Image Searcher - Searches for thematic images from multiple free sources:
Pixabay, Unsplash, Yandex Images (strictly photo-filtered).
Optimized for zero duplicates (hash-based + URL-based tracking),
pixel-level anti-junk verification (blocks charts, tables, document scans,
white-background catalog cutouts, logos), and rich photojournalistic variety.
"""
import asyncio
import hashlib
import html as py_html
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus, unquote

import httpx
from bs4 import BeautifulSoup
from PIL import Image

import config

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
}

# Minimum acceptable resolution for automatic landscape news slides
MIN_WIDTH = 850
MIN_HEIGHT = 480

# Domains that failed with connection errors during current run
_DEAD_DOMAINS: set[str] = set()

# Major image providers that must NEVER be permanently dead-listed
_PROTECTED_DOMAINS: set[str] = {
    "pixabay.com", "unsplash.com", "images.unsplash.com",
    "yandex.ru", "yastatic.net", "avatars.mds.yandex.net"
}

# Domains & URL substrings that serve watermarked stock, school slides, furniture catalogs, or document templates
FORBIDDEN_URL_PATTERNS = (
    # Watermarked stock agencies
    "alamy.", "shutterstock.", "depositphotos.", "dreamstime.", "123rf.",
    "gettyimages.", "istockphoto.", "bigstockphoto.", "vecteezy.", "freepik.",
    "vectorstock.", "canstockphoto.", "pond5.",
    # School / presentation / grammar / gaming / social junk
    "tildacdn.", "infourok.", "studfile.", "present5.", "myshared.",
    "ppt-online.", "uchitelya.", "znanija.", "foxford.", "skyeng.",
    "uchi.ru", "yaklass.", "playerok.", "pikabu.", "vk.com", "ok.ru",
    "dzen.ru", "pinterest.", "pinimg.com", "wixmp.com", "deviantart.",
    "telegram.org",
    # Furniture / e-commerce / product catalogs / legal templates
    "bpe-einrichten", "moebel", "möbel", "einrichten", "ikea.", "otto.de",
    "home24.", "wayfair.", "xxxlutz.", "roller.de", "poco.de",
    "anwalt.org", "buerger-geld", "arbeitsvertrag",
    # Non-photo filename markers
    ".svg", ".gif", "avatar", "icon", "logo", "banner", "abspann",
    "grafik", "diagramm", "tabelle", "statistik", "infografik", "chart",
    "formular", "mustermann", "personalausweis", "ausweis", "bescheinigung",
    "attest", "krankmeldung", "vorlage", "muster", "weil_denn", "grammatik",
    "sozialversicherungssystem",
)


def _is_forbidden_url(url: str) -> bool:
    if not url:
        return True
    u_low = unquote(url).lower()
    return any(pat in u_low for pat in FORBIDDEN_URL_PATTERNS)


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def compute_image_hash(image_path: str | Path) -> str:
    """Compute MD5 hash of image bytes for deduplication."""
    try:
        p = Path(image_path)
        if p.exists() and p.is_file():
            return hashlib.md5(p.read_bytes()).hexdigest()
    except Exception:
        pass
    return ""


def is_junk_photo(image_path: str | Path) -> tuple[bool, str]:
    """
    Fast pixel-level heuristic check (~2ms) to reject non-photographic junk:
    - Transparent / palette PNG diagrams & clipart
    - Charts, infographics, logos, and text slides (low color diversity)
    - E-commerce furniture/product cutouts on solid white or studio grey backgrounds
    - Scanned forms, tables, and documents
    """
    try:
        with Image.open(image_path) as orig:
            fmt = orig.format
            mode = orig.mode
            if mode in ("P", "RGBA", "LA") or "transparency" in orig.info:
                return True, f"transparent/palette graphic ({fmt}/{mode})"

            w, h = orig.size
            ratio = w / max(h, 1)
            if ratio < 1.18 or ratio > 2.45:
                return True, f"non-standard aspect ratio ({ratio:.2f})"

            img = orig.convert("RGB")
            small = img.resize((100, 100))
            pixels = list(small.getdata())

            # 1. Color diversity in 16x16x16 RGB space (max 4096 buckets)
            # Real photographs have 180-800+ buckets; charts/logos/scans/cutouts have < 165
            colors = len(set((r // 16, g // 16, b // 16) for r, g, b in pixels))
            if colors < 170:
                return True, f"low color diversity ({colors} buckets - chart/scan/cutout)"

            # 2. Pure white background check (tables, document scans, catalog cutouts)
            white_pct = sum(1 for r, g, b in pixels if r > 235 and g > 235 and b > 235) / 100.0
            if white_pct > 20.0:
                return True, f"excessive white background ({white_pct:.1f}%)"

            # 3. Studio neutral grey background check (furniture catalogs)
            light_gray_pct = sum(
                1 for r, g, b in pixels if abs(r - g) < 10 and abs(g - b) < 10 and r > 175
            ) / 100.0
            if light_gray_pct > 50.0:
                return True, f"studio grey background ({light_gray_pct:.1f}%)"

            # 4. Border uniformity check (framed diagrams, white-bordered product shots)
            border = (
                [pixels[i] for i in range(100)]
                + [pixels[9900 + i] for i in range(100)]
                + [pixels[i * 100] for i in range(100)]
                + [pixels[i * 100 + 99] for i in range(100)]
            )
            border_flat = (
                sum(
                    1
                    for r, g, b in border
                    if (r > 230 and g > 230 and b > 230)
                    or (abs(r - g) < 8 and abs(g - b) < 8 and r > 180)
                )
                / len(border)
                * 100.0
            )
            if border_flat > 50.0:
                return True, f"uniform light border ({border_flat:.1f}%)"

        return False, "ok"
    except Exception as e:
        return True, f"unreadable image ({e})"


async def search_pixabay(query: str, count: int = 15) -> list[dict]:
    """Search Pixabay for landscape photos with German language support."""
    if not config.PIXABAY_API_KEY:
        return []

    url = "https://pixabay.com/api/"
    # Clean query to core visual words (Pixabay ANDs all terms; >3 terms often returns 0 or nature fallbacks)
    words = [w for w in query.split() if len(w) > 2 and w.lower() not in {"deutschland", "foto", "alltag", "bericht"}]
    short_q = " ".join(words[:3]) if words else query

    params = {
        "key": config.PIXABAY_API_KEY,
        "q": short_q,
        "lang": "de",
        "per_page": min(max(count, 10), 50),
        "orientation": "horizontal",
        "image_type": "photo",
        "safesearch": "true",
        "min_width": 1000,
        "order": "popular",
    }

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 400 or (resp.status_code == 200 and not resp.json().get("hits")):
                params["q"] = " ".join(words[:2]) if len(words) >= 2 else query.split()[0]
                resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for hit in data.get("hits", []):
            w = hit.get("imageWidth", 0)
            h = hit.get("imageHeight", 0)
            tags = (hit.get("tags") or "").lower()
            # Skip nature/animal filler if searching for social/political topics
            if any(nat in tags for nat in ("vögel", "kraniche", "schloss", "blumen", "katze", "hund", "tiere")):
                continue
            if w >= h:
                img_url = hit.get("largeImageURL") or hit.get("webformatURL")
                if not _is_forbidden_url(img_url):
                    results.append({
                        "url": img_url,
                        "fallback_url": hit.get("webformatURL") or hit.get("previewURL"),
                        "url_medium": hit.get("webformatURL"),
                        "thumbnail": hit.get("previewURL"),
                        "width": w,
                        "height": h,
                        "source": "pixabay",
                        "photographer": hit.get("user", ""),
                        "alt": hit.get("tags", query),
                    })
        logger.debug(f"Pixabay: {len(results)} horizontal for '{short_q}'")
        return results
    except Exception as e:
        logger.debug(f"Pixabay search error for '{query}': {e}")
        return []


async def search_unsplash(query: str, count: int = 15) -> list[dict]:
    """Search Unsplash for landscape photos."""
    if not config.UNSPLASH_ACCESS_KEY:
        return []

    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": query,
        "per_page": min(max(count, 10), 30),
        "orientation": "landscape",
        "order_by": "relevant",
    }
    headers = {"Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for photo in data.get("results", []):
            w = photo.get("width", 0)
            h = photo.get("height", 0)
            if w >= h:
                urls = photo.get("urls", {})
                img_url = urls.get("regular", urls.get("full"))
                if not _is_forbidden_url(img_url):
                    results.append({
                        "url": img_url,
                        "fallback_url": urls.get("regular") or urls.get("small"),
                        "url_medium": urls.get("regular"),
                        "thumbnail": urls.get("small"),
                        "width": w,
                        "height": h,
                        "source": "unsplash",
                        "photographer": photo.get("user", {}).get("name", ""),
                        "alt": photo.get("alt_description", query),
                    })
        logger.debug(f"Unsplash: {len(results)} horizontal for '{query}'")
        return results
    except Exception as e:
        logger.debug(f"Unsplash search error for '{query}': {e}")
        return []


async def search_yandex(query: str, count: int = 25) -> list[dict]:
    """
    Search Yandex Images strictly for real photographs (itype=photo),
    filtering out charts, tables, furniture catalogs, and watermarked stock sites.
    """
    url = "https://yandex.ru/images/search"
    params = {
        "text": query,
        "isize": "large",
        "iorient": "horizontal",
        "itype": "photo",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.debug(f"Yandex Images returned {resp.status_code} for '{query}'")
                return []

            raw_html = resp.text
            results = []
            seen_urls = set()

            blocks = re.findall(
                r'(avatars\.mds\.yandex\.net/i\?id=[a-zA-Z0-9_\-]+-images-thumbs(?:&amp;|&)n=\d+)[^"]*?img_url=([^&"\'\s]+)(?:[^"]*?alt&quot;:&quot;([^&"]+))?',
                raw_html
            )
            for thumb_part, raw_orig, raw_alt in blocks:
                thumb_url = "https://" + py_html.unescape(thumb_part)
                clean_orig = unquote(raw_orig).replace("\\/", "/")
                if "%" in clean_orig:
                    clean_orig = unquote(clean_orig)
                clean_orig = clean_orig.strip()
                if clean_orig.startswith("/http"):
                    clean_orig = clean_orig.lstrip("/")
                elif clean_orig.startswith("//"):
                    clean_orig = "https:" + clean_orig

                if _is_forbidden_url(clean_orig):
                    continue

                primary_url = clean_orig if clean_orig.startswith("http") else thumb_url
                if primary_url not in seen_urls:
                    seen_urls.add(primary_url)
                    alt_text = py_html.unescape(raw_alt) if raw_alt else query
                    results.append({
                        "url": primary_url,
                        "fallback_url": thumb_url,
                        "url_medium": thumb_url,
                        "thumbnail": thumb_url,
                        "width": 1920,
                        "height": 1080,
                        "source": "yandex",
                        "alt": alt_text,
                    })
                    if len(results) >= count:
                        break

            if len(results) < count:
                raw_urls = re.findall(r'img_url=([^&"\'\s]+)', raw_html)
                orig_urls = re.findall(r'"origUrl":"(https?:[^"]+)"', raw_html)
                thumb_urls = re.findall(r'(https?://avatars\.mds\.yandex\.net/i\?id=[a-zA-Z0-9_\-]+-images-thumbs[^\s"\'<>]*)', raw_html)
                for idx_u, u in enumerate(orig_urls + raw_urls):
                    clean = unquote(u).replace("\\/", "/")
                    if "%" in clean:
                        clean = unquote(clean)
                    clean = clean.strip()
                    if clean.startswith("/http"):
                        clean = clean.lstrip("/")
                    elif clean.startswith("//"):
                        clean = "https:" + clean
                    if clean.startswith("http") and not _is_forbidden_url(clean):
                        if clean not in seen_urls:
                            seen_urls.add(clean)
                            fb_thumb = thumb_urls[idx_u % len(thumb_urls)] if thumb_urls else clean
                            results.append({
                                "url": clean,
                                "fallback_url": fb_thumb,
                                "url_medium": fb_thumb,
                                "thumbnail": fb_thumb,
                                "width": 1920,
                                "height": 1080,
                                "source": "yandex",
                                "alt": query,
                            })
                            if len(results) >= count:
                                break

            logger.debug(f"Yandex Images: найдено {len(results)} фото с превью для '{query}'")
            return results
    except Exception as e:
        logger.debug(f"Yandex Images search failed for '{query}': {e}")
        return []


async def search_images(query: str, count_per_source: int = 15) -> list[dict]:
    """
    Search multiple image sources (Pixabay + Unsplash + photo-filtered Yandex) and interleave them,
    prioritizing clean photography from Pixabay and Unsplash before web-scraped Yandex images.
    """
    tasks = [
        search_pixabay(query, count=count_per_source),
        search_unsplash(query, count=count_per_source),
        search_yandex(query, count=max(count_per_source * 2, 20)),
    ]

    res_list = await asyncio.gather(*tasks, return_exceptions=True)
    px_res = res_list[0] if isinstance(res_list[0], list) else []
    un_res = res_list[1] if isinstance(res_list[1], list) else []
    ya_res = res_list[2] if isinstance(res_list[2], list) else []

    combined = []
    seen = set()

    def _add(img):
        u = img.get("url")
        if u and u not in seen and not _is_forbidden_url(u):
            seen.add(u)
            combined.append(img)

    # Interleave top Pixabay & Unsplash photos first, then clean Yandex photos
    max_len = max(len(px_res), len(un_res), len(ya_res), 1)
    for i in range(max_len):
        if i < len(px_res):
            _add(px_res[i])
        if i < len(un_res):
            _add(un_res[i])
        if i < len(ya_res):
            _add(ya_res[i])

    logger.debug(f"Total combined images for '{query}': {len(combined)}")
    return combined


def get_image_proxy_url(target_url: str) -> str:
    """Format target image URL through Cloudflare proxy."""
    from urllib.parse import quote
    worker = config.get_image_proxy_worker() if hasattr(config, "get_image_proxy_worker") else getattr(config, "IMAGE_PROXY_WORKER_URL", "")
    if worker:
        sep = "&" if "?" in worker else "?"
        return f"{worker}{sep}url={quote(target_url, safe='')}"

    clean = re.sub(r'^https?://', '', target_url)
    return f"https://wsrv.nl/?url={quote(clean, safe='')}&output=jpg&n=-1"


async def download_image(
    url: str,
    save_path: str | Path,
    forbidden_hashes: set[str] = None,
    is_user_selection: bool = False,
    fallback_url: str = None,
    allow_proxy: bool = True,
) -> bool:
    """
    Download image from URL to local path.
    Verifies that it is a valid, horizontal photograph of sufficient resolution
    and passes the anti-junk pixel filter (no charts, tables, studio cutouts, or scans).
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    if not is_user_selection and _is_forbidden_url(url):
        return False

    domain = _domain_of(url)
    if not is_user_selection and domain and domain in _DEAD_DOMAINS:
        return False

    req_headers = dict(HEADERS)
    if "unsplash.com" in domain:
        req_headers["Referer"] = "https://unsplash.com/"
    elif "yandex.net" in domain or "yandex.ru" in domain:
        req_headers["Referer"] = "https://yandex.ru/"
    elif "wikimedia.org" in domain or "wikipedia.org" in domain:
        req_headers["User-Agent"] = "NewsVideoGenerator/1.0 (https://github.com/news-video; news-bot@app.com)"
        req_headers["Referer"] = "https://commons.wikimedia.org/"
    elif domain and not domain.endswith(".workers.dev") and "wsrv.nl" not in domain:
        req_headers["Referer"] = f"https://{domain}/"

    try:
        timeout = httpx.Timeout(15.0, connect=6.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=req_headers)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            if not is_user_selection:
                if "image" not in content_type and not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    raise ValueError("Invalid content-type")

            content = resp.content
            min_size = 1000 if is_user_selection else 15000
            if len(content) < min_size:
                raise ValueError("File too small")

            img_hash = hashlib.md5(content).hexdigest()
            if not is_user_selection and forbidden_hashes is not None and img_hash in forbidden_hashes:
                logger.info(f"Duplicate image hash detected ({img_hash[:8]}), skipping duplicate from {domain}")
                return False

            with open(save_path, "wb") as f:
                f.write(content)

            try:
                with Image.open(save_path) as img:
                    img.verify()
                with Image.open(save_path) as img:
                    w, h = img.size
            except Exception as e:
                save_path.unlink(missing_ok=True)
                raise ValueError(f"Corrupted image: {e}")

            min_w = 250 if is_user_selection else MIN_WIDTH
            min_h = 140 if is_user_selection else MIN_HEIGHT

            if not is_user_selection and w < h:
                save_path.unlink(missing_ok=True)
                return False

            if w < min_w or h < min_h:
                save_path.unlink(missing_ok=True)
                raise ValueError(f"Resolution {w}x{h} below required {min_w}x{min_h}")

            # Anti-junk pixel check for automatic downloads
            if not is_user_selection:
                junk, junk_reason = is_junk_photo(save_path)
                if junk:
                    logger.info(f"Rejected junk image ({junk_reason}) from {domain}: {url[:65]}")
                    save_path.unlink(missing_ok=True)
                    return False

            return True
    except Exception as e:
        logger.debug(f"Direct download failed for {url[:60]}: {e}")
        save_path.unlink(missing_ok=True)

        worker_configured = bool(config.get_image_proxy_worker() if hasattr(config, "get_image_proxy_worker") else getattr(config, "IMAGE_PROXY_WORKER_URL", ""))
        is_already_proxy = "wsrv.nl" in url or (worker_configured and config.get_image_proxy_worker() in url)
        is_direct_cdn = any(cdn in domain for cdn in ["yandex.net", "yandex.ru", "unsplash.com", "pixabay.com"])
        if allow_proxy and not is_already_proxy and not is_direct_cdn:
            proxy_url = get_image_proxy_url(url)
            proxy_ok = await download_image(
                proxy_url,
                save_path,
                forbidden_hashes=forbidden_hashes,
                is_user_selection=is_user_selection,
                fallback_url=fallback_url,
                allow_proxy=False,
            )
            if proxy_ok:
                return True

        if fallback_url and fallback_url != url:
            return await download_image(
                fallback_url,
                save_path,
                forbidden_hashes=forbidden_hashes,
                is_user_selection=is_user_selection,
                fallback_url=None,
                allow_proxy=True,
            )
        return False


async def validate_candidate_images(
    candidates: list[dict],
    max_valid: int = 16,
    used_urls: set[str] = None,
    used_hashes: set[str] = None,
) -> list[dict]:
    """
    Fast asynchronous validation of candidate image URLs for UI preview and selection.
    """
    if not candidates:
        return []

    used_urls = used_urls or set()
    used_hashes = used_hashes or set()

    valid_results: list[dict] = []
    seen_urls: set[str] = set()

    for c in candidates:
        u = c.get("url", "")
        thumb = c.get("thumbnail", "")
        if not u or not u.startswith("http") or _is_forbidden_url(u):
            continue

        norm_key = re.sub(r'https?://(?:www\.)?', '', u).split('?')[0].lower()
        if norm_key in seen_urls:
            continue
        seen_urls.add(norm_key)

        domain = _domain_of(u)
        if domain in _DEAD_DOMAINS:
            continue

        card = dict(c)
        is_used = (u in used_urls) or (thumb and thumb in used_urls) or any(norm_key in u_used.lower() for u_used in used_urls if len(u_used) > 10)
        card["already_used"] = is_used
        valid_results.append(card)

        if len(valid_results) >= max_valid * 2:
            break

    valid_results.sort(key=lambda x: (1 if x.get("already_used") else 0))
    return valid_results[:max_valid]


async def search_and_download_images(
    queries: list[str], output_dir: str | Path, target_total: int = 0,
    progress_callback=None, topic: str = "", title: str = "",
    segments: list[str] = None,
) -> list[str]:
    """Download one unique, clean photojournalistic image per segment."""
    from services.visual_plan import search_queries, make_text_card
    from services.query_helper import sanitize_segment_query
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if segments is None:
        segments = queries
    if len(segments) != len(queries):
        raise ValueError("Image selection requires one narration context per query")

    results = [None] * len(segments)
    manifest = [None] * len(segments)
    semaphore = asyncio.Semaphore(6)
    completed = 0
    query_cache = {}
    used_urls = set()
    used_hashes = set()

    async def candidates(query):
        if query not in query_cache:
            query_cache[query] = asyncio.create_task(search_images(query, count_per_source=10))
        return await query_cache[query]

    async def select(idx, context):
        nonlocal completed
        async with semaphore:
            attempts = []
            chosen = None
            seen = set()
            try:
                clean_primary = sanitize_segment_query(
                    queries[idx], topic=topic, title=title, index=idx, segment_text=context
                )
                q_list = search_queries(clean_primary, topic, context, index=idx)
                for query in q_list:
                    if chosen:
                        break
                    available = await candidates(query)
                    available = sorted(available, key=lambda item: item.get('url') in used_urls)
                    for item in available:
                        url = item.get('url')
                        if not url or url in seen or url in used_urls:
                            continue
                        seen.add(url)
                        path = output_dir / f'slide_{idx:03d}_{len(seen):02d}.jpg'
                        if not await download_image(
                            url, path, forbidden_hashes=used_hashes, fallback_url=item.get('fallback_url')
                        ):
                            continue
                        img_hash = compute_image_hash(path)
                        if img_hash:
                            if img_hash in used_hashes:
                                path.unlink(missing_ok=True)
                                continue
                            used_hashes.add(img_hash)
                        chosen = str(path.resolve())
                        used_urls.add(url)
                        manifest[idx] = {
                            'segment_index': idx, 'kind': 'photo', 'path': chosen,
                            'source_url': url, 'query': query, 'attempts': attempts
                        }
                        break
            except Exception as exc:
                logger.warning(f'Image selection failed for segment {idx}: {type(exc).__name__}: {exc}')

            if chosen is None:
                chosen = make_text_card(output_dir / f'card_{idx:03d}.png', topic, context)
                manifest[idx] = {
                    'segment_index': idx, 'kind': 'text_card', 'path': chosen,
                    'reason': 'No suitable photo found', 'attempts': attempts
                }
            results[idx] = chosen
            completed += 1
            if progress_callback:
                progress_callback(f'[{completed}/{len(segments)}] Подобрано фото #{idx+1}')

    await asyncio.gather(*(select(i, text) for i, text in enumerate(segments)))
    (output_dir.parent / 'visual_selection.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir.parent / 'used_urls.json').write_text(json.dumps(sorted(used_urls)), encoding='utf-8')
    return results
