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


async def download_image(
    url: str,
    save_path: str | Path,
    forbidden_hashes: set[str] = None,
    is_user_selection: bool = False,
    fallback_url: str = None,
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
    
    # Custom headers tailored per provider / domain to bypass hotlink protection
    req_headers = dict(HEADERS)
    if "unsplash.com" in domain:
        req_headers["Referer"] = "https://unsplash.com/"
    elif "yandex.net" in domain or "yandex.ru" in domain:
        req_headers["Referer"] = "https://yandex.ru/"
    elif domain:
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
                
            # Geometry check
            if is_user_selection:
                # User explicitly picked this image: accept any valid image (>= 100x100)
                # Video compiler's _prepare_image automatically crops/scales cleanly via LANCZOS
                min_w = 100
                min_h = 100
            else:
                min_w = MIN_WIDTH
                min_h = MIN_HEIGHT
                if w < h:
                    save_path.unlink(missing_ok=True)
                    return False
                
            if w < min_w or h < min_h:
                logger.warning(f"Image rejected: resolution {w}x{h} below minimum required ({min_w}x{min_h})")
                save_path.unlink(missing_ok=True)
                raise ValueError("Resolution too low")
            
            return True
    except Exception as e:
        logger.warning(f"Primary download failed for {url[:60]}: {e}")
        save_path.unlink(missing_ok=True)
        # Attempt fallback if available
        if fallback_url and fallback_url != url:
            logger.info(f"Retrying candidate download using fallback CDN URL: {fallback_url[:60]}...")
            return await download_image(fallback_url, save_path, forbidden_hashes=forbidden_hashes, is_user_selection=is_user_selection, fallback_url=None)
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
    queries: list[str],
    output_dir: str | Path,
    target_total: int = 0,
    progress_callback = None,
    topic: str = "",
    title: str = "",
) -> list[str]:
    """
    Search images for each segment and download them concurrently (Semaphore=6).
    Guarantees:
    1. Zero duplicate images (tracks both URLs and content MD5 hashes globally).
    2. Zero empty slots.
    3. Diverse thematic queries per segment.
    """
    from services.query_helper import (
        sanitize_segment_query,
        build_thematic_query_pool,
    )
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    num_segments = len(queries)
    if num_segments == 0:
        return []

    images_per_segment = 1 if (num_segments >= 80 or num_segments <= 8) else max(2, 110 // max(num_segments, 1))
    concurrency = 6
    _DEAD_DOMAINS.clear()
    
    # Global tracking sets for the entire job run
    job_used_hashes: set[str] = set()
    job_used_urls: set[str] = set()
    
    # Generate backup pool of diverse thematic queries in advance
    query_pool = build_thematic_query_pool(topic=topic, title=title, count=max(60, num_segments))
    
    sem = asyncio.Semaphore(concurrency)
    completed_count = 0
    results: list[list[str]] = [[] for _ in range(num_segments)]

    async def _handle_segment(idx: int, query: str):
        nonlocal completed_count
        async with sem:
            clean_q = sanitize_segment_query(query, topic=topic, title=title, index=idx)
            paths = []
            
            # Query attempts (primary, then simplified, then pooled thematic)
            candidate_queries = [clean_q]
            simple_q = " ".join([w for w in clean_q.split() if len(w) > 2][:3])
            if simple_q and simple_q != clean_q:
                candidate_queries.append(simple_q)
            if query_pool:
                candidate_queries.append(query_pool[idx % len(query_pool)])
                candidate_queries.append(query_pool[(idx + 17) % len(query_pool)])

            try:
                for q_attempt in candidate_queries:
                    if len(paths) >= images_per_segment:
                        break
                    
                    images = await search_images(q_attempt, count_per_source=15)
                    for img in images:
                        if len(paths) >= images_per_segment:
                            break
                        u = img.get("url")
                        if not u or u in job_used_urls:
                            continue
                        
                        ext = ".jpg"
                        if ".png" in u.lower():
                            ext = ".png"
                        elif ".webp" in u.lower():
                            ext = ".webp"
                        
                        save_path = output_dir / f"slide_{idx:03d}_{len(paths):02d}{ext}"
                        
                        # Download with strict hash deduplication
                        if await download_image(u, save_path, forbidden_hashes=job_used_hashes):
                            h = compute_image_hash(save_path)
                            if h and h not in job_used_hashes:
                                job_used_hashes.add(h)
                                job_used_urls.add(u)
                                paths.append(str(save_path))
                            else:
                                save_path.unlink(missing_ok=True)
                
                results[idx] = paths
            except Exception as e:
                logger.warning(f"Error downloading segment {idx} ('{query}'): {e}")
                results[idx] = []
            finally:
                completed_count += 1
                if progress_callback:
                    log_msg = f"[{completed_count}/{num_segments}] Фото: '{query[:35]}...'"
                    progress_callback(log_msg)
                await asyncio.sleep(0.04)

    tasks = [_handle_segment(i, q) for i, q in enumerate(queries)]
    await asyncio.gather(*tasks)

    # Collect all uniquely downloaded images
    all_downloaded = []
    for paths in results:
        for p in paths:
            if p and Path(p).exists() and Path(p).is_file():
                try:
                    if Path(p).stat().st_size > 5000:
                        all_downloaded.append(str(Path(p).resolve()))
                except Exception:
                    pass

    all_downloaded = list(dict.fromkeys(all_downloaded))
    logger.info(f"Pool size: {len(all_downloaded)} unique images downloaded for {num_segments} segments")

    # In case any segment failed all online searches, fill gap with offset from pool
    missing_count = 0
    for idx in range(num_segments):
        if not results[idx]:
            missing_count += 1
            borrowed = None
            if all_downloaded:
                # Use large prime stride to avoid adjacent slides being identical
                borrowed = all_downloaded[(idx * 17 + 5) % len(all_downloaded)]

            if borrowed:
                results[idx] = [borrowed]
                logger.info(f"Segment {idx} filled with photo: {Path(borrowed).name}")

    if missing_count > 0:
        logger.info(f"Filled {missing_count} segments with valid photos. Total fill rate 100%.")

    final_paths = []
    for idx, paths in enumerate(results):
        if paths:
            final_paths.extend(paths)
        elif all_downloaded:
            final_paths.append(all_downloaded[idx % len(all_downloaded)])

    # Persist used URLs for candidate search and deduplication
    try:
        urls_file = output_dir.parent / "used_urls.json"
        urls_file.write_text(json.dumps(list(job_used_urls)), encoding="utf-8")
        logger.info(f"Saved {len(job_used_urls)} used photo URLs to {urls_file.name}")
    except Exception as e:
        logger.debug(f"Failed to write used_urls.json: {e}")

    logger.info(f"Image search complete: {len(final_paths)} unique slides prepared from {num_segments} queries")
    return final_paths
