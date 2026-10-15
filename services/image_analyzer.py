"""
Image Analyzer - Uses Gemini Vision to check if images are relevant to the topic.
Includes parallel processing, circuit breaker on 503 errors, and real-time progress callbacks.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)


async def analyze_image_file(
    image_path: str | Path,
    context: str,
    topic: str,
    timeout_sec: float = 7.0,
) -> dict:
    """
    Analyze a local image file for relevance to the news segment with strict timeout.
    
    Returns:
        dict with 'relevant' (bool), 'score' (0-10), 'reason' (str)
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return {"relevant": False, "score": 0, "reason": "File not found"}
    
    try:
        # Read image data
        with open(image_path, "rb") as f:
            image_data = f.read()
        
        # Determine mime type
        suffix = image_path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/jpeg")
        
        key = config.get_next_gemini_key()
        http_opts = None
        if getattr(config, "GEMINI_BASE_URL", None):
            http_opts = types.HttpOptions(base_url=config.GEMINI_BASE_URL)
        client = genai.Client(api_key=key, http_options=http_opts)
        
        prompt = f"""Analyze this image for use in a news video.

Topic: {topic}
Segment text: {context[:300]}

Rate the image on these criteria:
1. Relevance to the topic/segment (0-10)
2. Visual quality (no watermarks, good resolution)
3. Appropriate for news content

Respond in JSON: {{"relevant": true/false, "score": 0-10, "reason": "brief explanation"}}
A score >= 5 means the image is acceptable."""

        def _call_gemini():
            return client.models.generate_content(
                model=config.GEMINI_VISION_MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=prompt),
                            types.Part.from_bytes(
                                data=image_data,
                                mime_type=mime_type,
                            ),
                        ],
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=200,
                    response_mime_type="application/json",
                ),
            )

        # Enforce strict timeout
        response = await asyncio.wait_for(asyncio.to_thread(_call_gemini), timeout=timeout_sec)
        
        raw_text = (response.text or "").strip()
        if not raw_text:
            return {"relevant": True, "score": 6, "reason": "Empty Gemini response, accepted"}
        
        # Remove markdown fences if present
        if "```" in raw_text:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
            if m:
                raw_text = m.group(1).strip()
                
        result = json.loads(raw_text)
        score = int(result.get("score", 5))
        relevant = bool(result.get("relevant", score >= 5))
        reason = str(result.get("reason", ""))
        return {"relevant": relevant, "score": score, "reason": reason}
        
    except Exception as e:
        logger.warning(f"Image analysis skipped for {image_path.name}: {e}")
        # Default to accepting the image
        return {"relevant": True, "score": 5, "reason": f"Analysis skipped: {str(e)[:80]}"}


async def filter_images(
    image_paths: list[str],
    segments: list[str],
    topic: str,
    min_score: int = 4,
    progress_callback = None,
    concurrency: int = 4,
) -> list[dict]:
    """
    Analyze all images in parallel with progress updates and circuit breaker.
    
    Returns:
        list of dicts with 'path', 'segment_index', 'score', 'relevant', 'reason'
    """
    total = len(image_paths)
    results = [None] * total
    sem = asyncio.Semaphore(concurrency)
    
    completed_count = 0
    consecutive_errors = 0
    circuit_broken = False
    
    async def _process_one(idx: int, path: str, seg: str):
        nonlocal completed_count, consecutive_errors, circuit_broken
        
        if not path or not Path(path).exists():
            results[idx] = {
                "path": path or "",
                "segment_index": idx,
                "score": 0,
                "relevant": False,
                "reason": "No image file",
            }
            completed_count += 1
            return

        # If circuit broken, accept image without calling API
        if circuit_broken:
            results[idx] = {
                "path": path,
                "segment_index": idx,
                "score": 5,
                "relevant": True,
                "reason": "AI Vision busy, auto-accepted",
            }
            completed_count += 1
            return
            
        async with sem:
            if circuit_broken:
                results[idx] = {
                    "path": path,
                    "segment_index": idx,
                    "score": 5,
                    "relevant": True,
                    "reason": "AI Vision busy, auto-accepted",
                }
                completed_count += 1
                return

            res = await analyze_image_file(path, seg, topic)
            
            # Check for service-level errors (503 / timeout / failure)
            if "Analysis skipped" in res.get("reason", ""):
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    circuit_broken = True
                    logger.warning("Gemini Vision returned 3 consecutive errors (e.g. 503). Auto-accepting remaining images to avoid delay.")
            else:
                consecutive_errors = 0

            results[idx] = {
                "path": path,
                "segment_index": idx,
                "score": res.get("score", 5),
                "relevant": res.get("relevant", True),
                "reason": res.get("reason", ""),
            }
            completed_count += 1
            
            if progress_callback:
                try:
                    progress_callback(
                        completed_count, 
                        total, 
                        f"Анализ фото [{completed_count}/{total}]: {Path(path).name} (оценка {res.get('score', 5)}/10)"
                    )
                except Exception as cb_err:
                    logger.debug(f"Progress callback error: {cb_err}")

    # Launch all workers concurrently
    tasks = [_process_one(i, p, s) for i, (p, s) in enumerate(zip(image_paths, segments))]
    await asyncio.gather(*tasks)
    
    accepted = sum(1 for r in results if r and r.get("score", 0) >= min_score)
    logger.info(f"Image analysis complete: {accepted}/{total} accepted (min_score={min_score})")
    
    return results
