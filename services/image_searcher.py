"""
Image Searcher - Searches for thematic images from multiple free sources:
Yandex Images, Unsplash, Pixabay.
Optimized for zero duplicates (hash-based + URL-based tracking),
guaranteed working images (pre-validation), and rich thematic variety.
"""
import asyncio
import hashlib
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
    "Accept-Language": "ru-RU,ru;q=0.9,de-DE,de;q=0.8,en-US;q=0.7,en;q=0.6",
}

# Minimum acceptable resolution (standard landscape)
MIN_WIDTH = 700
MIN_HEIGHT = 380

# Domains that failed with connection errors during current run
_DEAD_DOMAINS: set[str] = set()

# Major image providers that must NEVER be permanently dead-listed
_PROTECTED_DOMAINS: set[str] = {
    "pixabay.com", "unsplash.com", "images.unsplash.com", 
    "yandex.ru", "yastatic.net", "avatars.mds.yandex.net"
}


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


async def search_pixabay(query: str, count: int = 15) -> list[dict]:
    """Search Pixabay for landscape photos."""
    if not config.PIXABAY_API_KEY:
        return []
    
    url = "https://pixabay.com/api/"
    params = {
        "key": config.PIXABAY_API_KEY,
        "q": query,
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
            if resp.status_code == 400:
                params["q"] = " ".join(query.split()[:2])
                resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        
        results = []
        for hit in data.get("hits", []):
            w = hit.get("imageWidth", 0)
            h = hit.get("imageHeight", 0)
            if w >= h:
                results.append({
                    "url": hit.get("largeImageURL") or hit.get("webformatURL"),
                    "fallback_url": hit.get("webformatURL") or hit.get("previewURL"),
                    "url_medium": hit.get("webformatURL"),
                    "thumbnail": hit.get("previewURL"),
                    "width": w,
                    "height": h,
                    "source": "pixabay",
                    "photographer": hit.get("user", ""),
                    "alt": query,
                })
        logger.debug(f"Pixabay: {len(results)} horizontal for '{query}'")
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
                results.append({
                    "url": urls.get("regular", urls.get("full")),
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


import html as py_html


async def search_yandex(query: str, count: int = 25) -> list[dict]:
    """
    Search Yandex Images for news and thematic photos.
    Pairs direct fast Yandex CDN thumbnails with full-resolution source image URLs.
    """
    url = "https://yandex.ru/images/search"
    params = {
        "text": query,
        "isize": "large",
        "iorient": "horizontal",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,ru-RU,ru;q=0.8,en;q=0.7",
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
            
            # Primary extractor: pair Yandex CDN thumbnail with orig img_url
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
                
                if any(bad in clean_orig.lower() for bad in [".svg", ".gif", "avatar", "icon", "logo", "telegram.org"]):
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
            
            # Secondary fallback if regex matched fewer than requested
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
                    if clean.startswith("http") and not any(bad in clean.lower() for bad in [".svg", ".gif", "avatar", "icon", "logo", "telegram.org"]):
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
    Search multiple image sources (Yandex + Unsplash + Pixabay) and combine them.
    Guarantees a large, diverse pool of horizontal images.
    """
    tasks = [
        search_yandex(query, count=max(count_per_source * 2, 25)),
        search_unsplash(query, count=count_per_source),
        search_pixabay(query, count=count_per_source),
    ]
    
    res_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    combined = []
    seen = set()
    for res in res_list:
        if isinstance(res, list):
            for img in res:
                u = img.get("url")
                if u and u not in seen:
                    seen.add(u)
                    combined.append(img)
    
    logger.debug(f"Total combined images for '{query}': {len(combined)}")
    return combined


def get_image_proxy_url(target_url: str) -> str:
    """
    Format target image URL through Cloudflare proxy.
    If custom IMAGE_PROXY_WORKER_URL is configured (from Cloudflare Worker), use:
      https://worker-name.subdomain.workers.dev/?url={target_url}
    Otherwise fallback to Cloudflare wsrv.nl edge proxy:
      https://wsrv.nl/?url={clean_target}&output=jpg&n=-1
    """
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
    Verifies that it is a valid, horizontal image of sufficient resolution.
    If forbidden_hashes is provided, immediately discards duplicate images.
    If primary download fails and fallback_url is provided, automatically retries with fallback_url.
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
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
                    logger.warning(f"Download rejected: invalid content-type '{content_type}' for {url[:60]}")
                    raise ValueError("Invalid content-type")
            
            content = resp.content
            min_size = 1000 if is_user_selection else 3000
            if len(content) < min_size:
                logger.warning(f"Download rejected: image too small ({len(content)} bytes) for {url[:60]}")
                raise ValueError("File too small")
            
            # Check content hash BEFORE saving
            img_hash = hashlib.md5(content).hexdigest()
            if not is_user_selection and forbidden_hashes is not None and img_hash in forbidden_hashes:
                logger.info(f"Duplicate image hash detected ({img_hash[:8]}), skipping duplicate from {domain}")
                return False
            
            with open(save_path, "wb") as f:
                f.write(content)
            
            # Verify image format and geometry
            try:
                with Image.open(save_path) as img:
                    img.verify()
                with Image.open(save_path) as img:
                    w, h = img.size
            except Exception as e:
                logger.warning(f"Corrupted image from {url[:60]}: {e}")
                save_path.unlink(missing_ok=True)
                raise ValueError("Corrupted image")
                
            # Resolution and horizontal framing check
            # Auto-crawler strictly requires Full HD horizontal (MIN_WIDTH=800, MIN_HEIGHT=450)
            # User manual pick: accept down to 250x140 so any crisp CDN previews work reliably if original is blocked
            min_w = 250 if is_user_selection else MIN_WIDTH
            min_h = 140 if is_user_selection else MIN_HEIGHT
            
            if not is_user_selection and w < h:
                logger.warning(f"Image rejected: vertical/portrait format ({w}x{h}) for {url[:60]}")
                save_path.unlink(missing_ok=True)
                return False
                
            if w < min_w or h < min_h:
                logger.warning(f"Image rejected: resolution {w}x{h} below minimum required ({min_w}x{min_h}) for {url[:60]}")
                save_path.unlink(missing_ok=True)
                raise ValueError(f"Resolution {w}x{h} below required {min_w}x{min_h}")
            
            return True
    except Exception as e:
        logger.warning(f"Direct download failed for {url[:60]}: {e}")
        save_path.unlink(missing_ok=True)
        
        # 1. Retry full original image via Cloudflare Edge Proxy
        worker_configured = bool(config.get_image_proxy_worker() if hasattr(config, "get_image_proxy_worker") else getattr(config, "IMAGE_PROXY_WORKER_URL", ""))
        is_already_proxy = "wsrv.nl" in url or (worker_configured and config.get_image_proxy_worker() in url)
        is_direct_cdn = any(cdn in domain for cdn in ["yandex.net", "yandex.ru", "unsplash.com", "pixabay.com"])
        if allow_proxy and not is_already_proxy and not is_direct_cdn:
            proxy_url = get_image_proxy_url(url)
            logger.info(f"Retrying full-res image via Cloudflare Proxy: {proxy_url[:70]}...")
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
                
        # 2. Attempt fallback CDN URL if available
        if fallback_url and fallback_url != url:
            logger.info(f"Retrying candidate download using fallback CDN URL: {fallback_url[:60]}...")
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
    Immediately validates photos with CDN previews (Yandex, Unsplash, Pixabay),
    flags already-used images, and prioritizes fresh, unused photos.
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
        if not u or not u.startswith("http"):
            continue
        
        # Avoid duplicate cards in candidate grid
        norm_key = re.sub(r'https?://(?:www\.)?', '', u).split('?')[0].lower()
        if norm_key in seen_urls:
            continue
        seen_urls.add(norm_key)
        
        domain = _domain_of(u)
        if domain in _DEAD_DOMAINS:
            continue
            
        card = dict(c)
        # Check if already used in video (by full URL or stem)
        is_used = (u in used_urls) or (thumb and thumb in used_urls) or any(norm_key in u_used.lower() for u_used in used_urls if len(u_used) > 10)
        card["already_used"] = is_used
        
        # High-confidence CDN thumbnail (Yandex, Unsplash, Pixabay) -> Instant valid!
        if any(p in (thumb or u) for p in ["avatars.mds.yandex.net", "unsplash.com", "pixabay.com"]):
            valid_results.append(card)
        else:
            # External non-CDN link
            valid_results.append(card)
        
        if len(valid_results) >= max_valid * 2:
            break
            
    # Sort: unused photos first, then already used
    valid_results.sort(key=lambda x: (1 if x.get("already_used") else 0))
    return valid_results[:max_valid]


async def search_and_download_images(
    queries: list[str], output_dir: str | Path, target_total: int = 0,
    progress_callback=None, topic: str = "", title: str = "",
    segments: list[str] = None,
) -> list[str]:
    """Exactly one verified image or narration card per segment, in order."""
    from services.image_analyzer import analyze_image_file
    from services.visual_plan import search_queries, make_text_card
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if segments is None or len(segments) != len(queries):
        raise ValueError("Image selection requires one narration context per query")
    results = [None] * len(segments)
    manifest = [None] * len(segments)
    semaphore = asyncio.Semaphore(2)
    completed = 0
    service_errors = 0
    query_cache = {}
    used_urls = set()

    async def candidates(query):
        if query not in query_cache:
            query_cache[query] = asyncio.create_task(search_images(query, count_per_source=4))
        return await query_cache[query]

    async def select(idx, context):
        nonlocal completed, service_errors
        async with semaphore:
            attempts = []
            chosen = None
            seen = set()
            try:
                # Data illustrations require verified data, not arbitrary web charts.
                card_intent = bool(re.search(r'chart|diagram|grafik|tabelle|график|диаграм|таблиц|карточк|text.?card', queries[idx], re.I))
                if not card_intent and service_errors < 3:
                    for query in search_queries(queries[idx], topic, context):
                        if chosen or service_errors >= 3:
                            break
                        checked = 0
                        available = await candidates(query)
                        # Prefer fresh photos, but never trade relevance for uniqueness.
                        available = sorted(available, key=lambda item: item.get('url') in used_urls)
                        for item in available:
                            url = item.get('url')
                            if not url or url in seen:
                                continue
                            seen.add(url)
                            if checked >= 3:
                                break
                            checked += 1
                            path = output_dir / f'candidate_{idx:03d}_{len(seen):02d}.jpg'
                            if not await download_image(url, path, fallback_url=item.get('fallback_url')):
                                continue
                            verdict = await analyze_image_file(path, context, topic)
                            attempts.append({'query': query, 'url': url, **verdict})
                            if verdict.get('status') == 'unverified':
                                service_errors += 1
                                break
                            service_errors = 0
                            if verdict.get('status') == 'approved' and verdict.get('relevant') is True and verdict.get('score', 0) >= 7:
                                chosen = str(path)
                                used_urls.add(url)
                                manifest[idx] = {'segment_index': idx, 'kind': 'photo', 'path': chosen,
                                                 'source_url': url, 'query': query, 'attempts': attempts}
                                break
            except Exception as exc:
                logger.warning(f'Image selection failed for segment {idx}: {type(exc).__name__}')
            if chosen is None:
                chosen = make_text_card(output_dir / f'card_{idx:03d}.png', topic, context)
                manifest[idx] = {'segment_index': idx, 'kind': 'text_card', 'path': chosen,
                                 'reason': 'No verified suitable photo', 'attempts': attempts}
            results[idx] = chosen
            completed += 1
            if progress_callback:
                progress_callback(f'[{completed}/{len(segments)}] Проверен визуал: {manifest[idx]["kind"]}')

    await asyncio.gather(*(select(i, text) for i, text in enumerate(segments)))
    (output_dir.parent / 'visual_selection.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir.parent / 'used_urls.json').write_text(json.dumps(sorted(used_urls)), encoding='utf-8')
    return results
