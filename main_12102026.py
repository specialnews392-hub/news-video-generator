"""
News Video Generator - Main FastAPI Server
"""
import asyncio
import json
import logging
import uuid
import traceback
from datetime import datetime
import time
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
import httpx
from pydantic import BaseModel

import config
from services import (
    news_fetcher, script_generator, tts_engine,
    image_searcher, image_analyzer, video_compiler,
    thumbnail_generator, telegram_notifier
)

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# === FastAPI App ===
app = FastAPI(title="News Video Generator", version="1.0.0")

# Serve static files
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

# === Persistent job tracking ===
JOBS_FILE = config.OUTPUT_DIR / "jobs_state.json"

def _load_jobs() -> dict[str, dict]:
    if JOBS_FILE.exists():
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data)} jobs from disk")
                from services.translator import translate_to_ru
                for j in data.values():
                    t_ru = j.get("title_ru")
                    if not t_ru and j.get("language") != "ru":
                        t = j.get("generated_title") or (j.get("result") or {}).get("title")
                        if t:
                            t_ru = translate_to_ru(t)
                            j["title_ru"] = t_ru
                    h_ru = j.get("thumbnail_hook_ru")
                    if not h_ru and j.get("language") != "ru":
                        h = j.get("thumbnail_hook") or (j.get("script_data") or {}).get("thumbnail_hook")
                        if h:
                            h_ru = translate_to_ru(h)
                            j["thumbnail_hook_ru"] = h_ru
                    if j.get("result"):
                        if t_ru and not j["result"].get("title_ru"):
                            j["result"]["title_ru"] = t_ru
                        if h_ru and not j["result"].get("thumbnail_hook_ru"):
                            j["result"]["thumbnail_hook_ru"] = h_ru
                return data
        except Exception as e:
            logger.warning(f"Failed to load jobs state: {e}")
    return {}

def _save_jobs():
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save jobs state: {e}")

jobs: dict[str, dict] = _load_jobs()


class VideoRequest(BaseModel):
    topic: str
    language: str = "ru"
    voice_id: str = "ru-dmitry"
    theme: str = "default"
    voice_rate: str = "+0%"
    target_length: int = 15000  # Default: 15,000 chars (~12-15 minutes narration)
    skip_image_analysis: bool = True  # skip by default since Gemini Vision often 503s
    is_preview: bool = False  # Fast preview mode (~30s, 4 slides) for testing subtitles & thumbnail
    ken_burns: bool = False  # Ken Burns dynamic camera drift / zoom
    transitions: bool = True  # Smooth slide crossfade transitions
    review_slides: bool = False  # Interactive slide moderation/replacement before compiling video
    acute_angle_id: str = ""  # Targeted acute sub-angle ID if chosen in UI


class BatchVideoRequest(BaseModel):
    topics: list[str]
    language: str = "ru"
    voice_id: str = "ru-dmitry"
    theme: str = "default"
    voice_rate: str = "+0%"
    target_length: int = 15000
    skip_image_analysis: bool = True
    is_preview: bool = False
    ken_burns: bool = False
    transitions: bool = True
    review_slides: bool = False


# Concurrency limit: maximum 1 heavy FFmpeg render pipeline at a time to prevent CPU freezing/OOM
PIPELINE_SEMAPHORE = asyncio.Semaphore(1)

# Review slide events map for jobs awaiting manual slide approval
_SLIDE_REVIEW_EVENTS: dict[str, asyncio.Event] = {}

# Active pipeline asyncio tasks map for instant cancellation
_RUNNING_TASKS: dict[str, asyncio.Task] = {}


# === Routes ===

@app.get("/")
async def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))


@app.get("/api/voices")
async def get_voices():
    """Return all available voices."""
    return {"voices": config.ALL_VOICES}


@app.get("/api/languages")
async def get_languages():
    return {
        "languages": [
            {"code": code, "name": name, "voice": config.TTS_VOICES[code]}
            for code, name in config.TTS_VOICE_NAMES.items()
        ]
    }


@app.get("/api/themes")
async def get_themes():
    return {
        "themes": [
            {"id": tid, "name": tid.capitalize(), "colors": colors}
            for tid, colors in config.THEME_COLORS.items()
        ]
    }


@app.get("/api/preview-voice/{voice_id}")
async def preview_voice(voice_id: str):
    """Generate a short voice preview clip for specific voice."""
    voice_info = config.VOICES_BY_ID.get(voice_id)
    if not voice_info:
        raise HTTPException(status_code=404, detail=f"Voice '{voice_id}' not found")
    
    preview_texts = {
        "ru": "Это голос для вашего новостного ролика. Сегодня мы обсудим самые важные события дня.",
        "en": "This is the voice for your news video. Today we will discuss the most important events.",
        "de": "Dies ist die Stimme fuer Ihr Nachrichtenvideo. Heute besprechen wir die wichtigsten Ereignisse.",
        "fr": "C'est la voix pour votre video d'actualites. Aujourd'hui nous discutons des evenements les plus importants.",
        "es": "Esta es la voz para su video de noticias. Hoy discutiremos los eventos mas importantes.",
        "uk": "Це голос для вашого новинного ролика. Сьогодни ми обговоримо найважливиши подii.",
        "zh": "Zhe shi ninde xinwen shipin de shengyin. Jintian women jiang taolun zui zhongyao de shijian.",
        "ar": "Hatha huwa alsawt li fideo al'akhbar alkhass bik.",
        "pt": "Esta e a voz para seu video de noticias. Hoje discutiremos os eventos mais importantes.",
        "it": "Questa e la voce per il tuo video di notizie. Oggi discuteremo degli eventi piu importanti.",
        "ja": "Kore wa anata no nyuusu bideo no koe desu. Kyou wa mottomo juuyou na dekigoto ni tsuite hanashimasu.",
        "ko": "I geos-eun dangsin-ui nyuseu bidio-ui moksoli ibnida.",
        "hi": "Yah aapke samachar video ke liye awaaz hai.",
        "tr": "Bu, haber videonuz icin sestir. Bugun en onemli olaylari tartisacagiz.",
    }
    
    lang = voice_info["lang"]
    preview_text = preview_texts.get(lang, preview_texts["en"])
    if voice_info.get("engine") == "gemini":
        selected_voice = f"gemini:{voice_info.get('gemini_voice', 'Charon')}"
    else:
        selected_voice = voice_info.get("edge", config.TTS_VOICES.get(lang, "ru-RU-DmitryNeural"))
    
    preview_dir = config.TEMP_DIR / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    
    # Use voice_id in path to cache per voice
    result = await tts_engine.generate_segmented_speech(
        segments=[preview_text],
        output_dir=preview_dir / voice_id,
        lang=lang,
        voice=selected_voice,
    )
    
    audio_path = result["combined_audio"]
    
    if not Path(audio_path).exists():
        raise HTTPException(status_code=500, detail="Failed to generate preview")
    
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"preview_{voice_id}.mp3",
    )


@app.post("/api/generate")
async def start_generation(req: VideoRequest, background_tasks: BackgroundTasks):
    """Start video generation as a background job."""
    job_id = str(uuid.uuid4())[:8]
    
    is_busy = PIPELINE_SEMAPHORE.locked()
    step_msg = "В очереди на генерацию..." if is_busy else "Инициализация..."
    
    jobs[job_id] = {
        "id": job_id,
        "topic": req.topic,
        "language": req.language,
        "theme": req.theme,
        "status": "queued",
        "progress": 0,
        "current_step": step_msg,
        "detail": "Ожидание запуска конвейера..." if is_busy else "",
        "generated_title": "",
        "has_script": False,
        "steps_completed": [],
        "created_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }
    _save_jobs()
    t = asyncio.create_task(run_pipeline(job_id, req))
    _RUNNING_TASKS[job_id] = t
    t.add_done_callback(lambda _, jid=job_id: _RUNNING_TASKS.pop(jid, None))
    
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/generate-batch")
async def start_batch_generation(req: BatchVideoRequest, background_tasks: BackgroundTasks):
    """Start batch generation of multiple topics sequentially."""
    cleaned_topics = [t.strip() for t in req.topics if t and t.strip()]
    if not cleaned_topics:
        raise HTTPException(status_code=400, detail="Не указано ни одной темы для генерации")
    
    created_jobs = []
    total = len(cleaned_topics)
    
    for idx, topic in enumerate(cleaned_topics):
        job_id = str(uuid.uuid4())[:8]
        is_first = (idx == 0 and not PIPELINE_SEMAPHORE.locked())
        step_msg = "Инициализация..." if is_first else f"В очереди (задача {idx + 1} из {total})..."
        
        jobs[job_id] = {
            "id": job_id,
            "topic": topic,
            "language": req.language,
            "theme": req.theme,
            "status": "queued",
            "progress": 0,
            "current_step": step_msg,
            "detail": "Запуск конвейера..." if is_first else f"В очереди ({idx + 1}/{total})",
            "generated_title": "",
            "has_script": False,
            "steps_completed": [],
            "created_at": datetime.now().isoformat(),
            "result": None,
            "error": None,
        }
        
        single_req = VideoRequest(
            topic=topic,
            language=req.language,
            voice_id=req.voice_id,
            theme=req.theme,
            voice_rate=req.voice_rate,
            target_length=req.target_length,
            skip_image_analysis=req.skip_image_analysis,
            is_preview=req.is_preview,
        )
        t = asyncio.create_task(run_pipeline(job_id, single_req))
        _RUNNING_TASKS[job_id] = t
        t.add_done_callback(lambda _, jid=job_id: _RUNNING_TASKS.pop(jid, None))
        created_jobs.append({
            "id": job_id,
            "topic": topic,
            "status": "queued",
            "step": step_msg
        })
    
    _save_jobs()
    return {
        "status": "ok",
        "batch": True,
        "count": len(created_jobs),
        "jobs": created_jobs,
        "first_job_id": created_jobs[0]["id"] if created_jobs else None
    }


@app.get("/api/queue")
async def get_queue():
    """Get active and queued jobs state."""
    active_jobs = [
        j for j in jobs.values()
        if j.get("status") in ("running", "queued", "awaiting_slide_review")
    ]
    active_jobs.sort(key=lambda x: x.get("created_at", ""))
    return {"queue": active_jobs, "count": len(active_jobs)}


@app.get("/api/status/{job_id}")
@app.get("/api/job/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/job/{job_id}/script")
async def get_job_script(job_id: str):
    """Retrieve full generated script for viewing while pipeline is running or completed."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if "script_data" in job:
        return job["script_data"]
    
    # Try reading from disk
    script_path = config.OUTPUT_DIR / job_id / "script.txt"
    if script_path.exists():
        text = script_path.read_text(encoding="utf-8")
        return {
            "title": job.get("generated_title") or job.get("result", {}).get("title", ""),
            "description": job.get("result", {}).get("description", ""),
            "script": text,
        }
    raise HTTPException(status_code=404, detail="Script not yet generated")


@app.get("/api/job/{job_id}/sources")
async def get_job_sources(job_id: str):
    """Retrieve full extracted sources and raw article texts for factual confirmation."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if "sources" in job:
        return {
            "summary": job.get("sources_summary", {}),
            "sources": job["sources"],
        }
    
    # Try reading from disk
    sources_file = config.OUTPUT_DIR / job_id / "sources.json"
    if sources_file.exists():
        try:
            with open(sources_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
            
    raise HTTPException(status_code=404, detail="Sources not yet extracted")


@app.get("/api/gemini/tts-status")
async def get_gemini_tts_status():
    """Check Gemini TTS model availability and quota status across API keys."""
    try:
        from services.tts_engine import check_gemini_tts_status
        return await check_gemini_tts_status()
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
            "summary": f"Ошибка проверки квоты Gemini: {e}"
        }


@app.get("/api/jobs")
async def list_jobs():
    summary_jobs = []
    for j in jobs.values():
        item = dict(j)
        item.pop("sources", None)
        item.pop("script_data", None)
        summary_jobs.append(item)
    return {"jobs": summary_jobs}


@app.post("/api/job/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job immediately and release semaphore."""
    global PIPELINE_SEMAPHORE
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    job["status"] = "cancelled"
    job["current_step"] = "Отменено пользователем"
    job["detail"] = "Генерация прервана пользователем"
    _save_jobs()
    
    if job_id in _SLIDE_REVIEW_EVENTS:
        _SLIDE_REVIEW_EVENTS[job_id].set()
        _SLIDE_REVIEW_EVENTS.pop(job_id, None)

    # Cancel the asyncio pipeline task immediately
    if job_id in _RUNNING_TASKS:
        t = _RUNNING_TASKS.pop(job_id, None)
        if t and not t.done():
            t.cancel()

    # If no other running jobs exist, ensure semaphore is clean and not stuck
    active_running = [j for j in jobs.values() if j.get("status") == "running"]
    if not active_running:
        PIPELINE_SEMAPHORE = asyncio.Semaphore(1)

    logger.info(f"[{job_id}] Cancelled by user and task terminated")
    _refresh_queue_positions()
    return {"status": "cancelled", "job_id": job_id}


@app.post("/api/jobs/reset")
async def reset_all_running_jobs():
    """Cancel all active/running/queued jobs and release all pipeline locks immediately."""
    global PIPELINE_SEMAPHORE
    cancelled = []
    
    # 1. Cancel all active asyncio tasks
    for jid, t in list(_RUNNING_TASKS.items()):
        try:
            if not t.done():
                t.cancel()
        except Exception:
            pass
        _RUNNING_TASKS.pop(jid, None)

    # 2. Mark any active/queued jobs as cancelled
    for jid, j in jobs.items():
        if j.get("status") in ("running", "queued", "awaiting_slide_review"):
            j["status"] = "cancelled"
            j["current_step"] = "Отменено пользователем"
            j["detail"] = "Сброшено пользователем"
            cancelled.append(jid)
            if jid in _SLIDE_REVIEW_EVENTS:
                _SLIDE_REVIEW_EVENTS[jid].set()
    _SLIDE_REVIEW_EVENTS.clear()

    # 3. Reset pipeline semaphore so next job starts immediately without waiting
    PIPELINE_SEMAPHORE = asyncio.Semaphore(1)

    if cancelled:
        _save_jobs()
    logger.info(f"Reset {len(cancelled)} jobs and unlocked pipeline semaphore: {cancelled}")
    return {"status": "ok", "cancelled_jobs": cancelled}


# === Telegram Notifications Settings ===

class TelegramConfigRequest(BaseModel):
    bot_token: str
    chat_id: str
    server_url: str = ""
    enabled: bool = True


@app.get("/api/telegram/config")
async def get_telegram_settings():
    cfg = telegram_notifier.get_telegram_config()
    raw_token = cfg.get("bot_token", "")
    masked = ""
    if raw_token:
        masked = raw_token[:6] + "..." + raw_token[-4:] if len(raw_token) > 10 else "***"
    return {
        "enabled": cfg.get("enabled", False),
        "bot_token_masked": masked,
        "chat_id": cfg.get("chat_id", ""),
        "server_url": cfg.get("server_url", "http://45.147.31.53:8501"),
        "has_token": bool(raw_token),
    }


@app.post("/api/telegram/config")
async def save_telegram_settings(req: TelegramConfigRequest):
    cfg = telegram_notifier.save_telegram_config(
        bot_token=req.bot_token,
        chat_id=req.chat_id,
        server_url=req.server_url,
        enabled=req.enabled
    )
    return {"status": "ok", "enabled": cfg["enabled"], "cfg": cfg}


@app.post("/api/telegram/test")
async def test_telegram_settings(req: TelegramConfigRequest):
    res = await telegram_notifier.send_test_message(
        bot_token=req.bot_token,
        chat_id=req.chat_id,
        server_url=req.server_url
    )
    return res


@app.get("/api/download/{job_id}/{file_type}")
async def download_file(job_id: str, file_type: str):
    """Download video or thumbnail."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    result = job.get("result", {})
    
    if file_type == "video":
        path = result.get("video_path")
    elif file_type == "thumbnail":
        path = result.get("thumbnail_path")
    elif file_type == "script":
        path = result.get("script_path")
    elif file_type == "subtitles":
        path = result.get("subtitles_path")
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    media_type = "image/jpeg" if file_type == "thumbnail" else "application/octet-stream"
    return FileResponse(
        path,
        filename=Path(path).name,
        media_type=media_type,
    )


class ThumbnailRegenRequest(BaseModel):
    query: str = ""
    image_url: str = ""
    title: str = ""
    topic: str = ""
    offset: int = 0


class TranslateRequest(BaseModel):
    text: str


@app.get("/api/job/{job_id}/thumbnail")
async def get_job_thumbnail(job_id: str):
    """Serve the thumbnail image directly for browser display."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    result = job.get("result", {})
    path = result.get("thumbnail_path") or (config.OUTPUT_DIR / job_id / "thumbnail.jpg")
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(
        p,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/proxy-thumb")
async def proxy_thumb(url: str):
    """Proxy external candidate images to avoid browser CORS and hotlink blocks."""
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid url")
    try:
        ref = "https://yandex.ru/"
        if "pixabay.com" in url:
            ref = "https://pixabay.com/"
        elif "unsplash.com" in url:
            ref = "https://unsplash.com/"
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": ref,
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and resp.content:
                ct = resp.headers.get("content-type", "image/jpeg")
                return Response(
                    content=resp.content,
                    media_type=ct,
                    headers={"Cache-Control": "public, max-age=86400"},
                )
    except Exception as e:
        logger.debug(f"Proxy thumb failed for {url[:50]}: {e}")
    raise HTTPException(status_code=404, detail="Image could not be retrieved")


class AcuteSelectRequest(BaseModel):
    angle_id: str
    topic_query: str = ""


class AcuteDismissRequest(BaseModel):
    angle_ids: list[str]


@app.get("/api/topics/acute")
async def get_acute_topics(
    topic: str = "",
    lang: str = "de",
    offset: int = 0,
    exclude_ids: str = ""
):
    """Get live acute topics and investigative sub-angles for broad topics."""
    from services.news_fetcher import get_acute_topics_preview
    ex_list = [x.strip() for x in exclude_ids.split(",") if x.strip()] if exclude_ids else []
    result = await get_acute_topics_preview(topic=topic, lang=lang, offset=offset, exclude_ids=ex_list)
    return {"status": "ok", **result}


@app.post("/api/topics/acute/select")
async def select_acute_topic(req: AcuteSelectRequest):
    """Record an acute topic as selected/used so it won't be offered again."""
    from services.news_fetcher import mark_acute_angle_used
    mark_acute_angle_used(req.angle_id)
    return {"status": "ok", "selected_id": req.angle_id}


@app.post("/api/topics/acute/dismiss")
async def dismiss_acute_topics(req: AcuteDismissRequest):
    """Mark a batch of acute topic IDs as dismissed/skipped."""
    from services.news_fetcher import mark_acute_angles_dismissed
    mark_acute_angles_dismissed(req.angle_ids)
    return {"status": "ok", "dismissed_count": len(req.angle_ids)}


@app.post("/api/topics/acute/reset-history")
async def reset_acute_topics_history():
    """Reset the history of used acute topics to start fresh."""
    from services.news_fetcher import reset_acute_history
    reset_acute_history()
    return {"status": "ok", "message": "Acute topics history reset successfully"}


@app.get("/api/job/{job_id}/thumbnail/candidates")
async def get_thumbnail_candidates(job_id: str, query: str = ""):
    """Find background photo candidates for this job's thumbnail, pre-validating working links."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    script_data = job.get("script_data", {})
    result = job.get("result", {})

    active_query = query.strip()
    if not active_query:
        active_query = (
            script_data.get("thumbnail_query")
            or script_data.get("thumbnail_hook")
            or script_data.get("main_lead_story")
            or result.get("title")
            or job.get("topic")
            or "новости события"
        )
    # Clean query for image search
    clean_q = re.sub(r'[*#_`!?:;\"\'«»]', '', active_query).strip()
    words = clean_q.split()
    if len(words) > 5:
        clean_q = " ".join(words[:5])

    raw_candidates = await image_searcher.search_images(clean_q, count_per_source=15)
    valid_candidates = await image_searcher.validate_candidate_images(raw_candidates, max_valid=16)

    return {
        "query": clean_q,
        "current_title": script_data.get("thumbnail_hook") or result.get("title") or "",
        "current_topic": (job.get("topic") or "НОВОСТИ").upper(),
        "candidates": valid_candidates,
    }


@app.post("/api/job/{job_id}/thumbnail/regenerate")
async def regenerate_thumbnail(job_id: str, req: ThumbnailRegenRequest):
    """Regenerate the YouTube thumbnail with new text or background image."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    script_data = job.get("script_data", {})
    result = job.get("result", {})
    job_dir = config.OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = job_dir / "thumbnail.jpg"

    # 1. Determine title and topic badge
    title = (req.title.strip() or script_data.get("thumbnail_hook") or result.get("title") or job.get("topic") or "НОВОСТИ").upper()
    topic = (req.topic.strip() or job.get("topic") or "НОВОСТИ").upper()

    # 2. Determine background image
    bg_image_path = None
    target_bg = job_dir / "thumbnail_bg.jpg"

    if req.image_url:
        # User picked a specific candidate image from gallery
        if await image_searcher.download_image(req.image_url, target_bg):
            bg_image_path = str(target_bg)
    elif req.query.strip():
        # User entered a custom search query
        clean_q = re.sub(r'[*#_`!?:;\"\'«»]', '', req.query).strip()
        candidates = await image_searcher.search_yandex(clean_q, count=max(10, req.offset + 3))
        if candidates and req.offset < len(candidates):
            chosen = candidates[req.offset]
            if await image_searcher.download_image(chosen["url"], target_bg):
                bg_image_path = str(target_bg)
        if not bg_image_path and candidates:
            for c in candidates:
                if await image_searcher.download_image(c["url"], target_bg):
                    bg_image_path = str(target_bg)
                    break
    elif req.offset > 0:
        # User explicitly requested next candidate image via "Другое фото" (offset > 0)
        fallback_q = (
            script_data.get("thumbnail_query")
            or script_data.get("thumbnail_hook")
            or script_data.get("main_lead_story")
            or job.get("topic")
            or "новости события"
        )
        clean_q = re.sub(r'[*#_`!?:;\"\'«»]', '', fallback_q).strip()
        words = clean_q.split()
        if len(words) > 5:
            clean_q = " ".join(words[:5])
        candidates = await image_searcher.search_yandex(clean_q, count=12)
        if candidates:
            idx = req.offset % len(candidates)
            chosen = candidates[idx]
            if await image_searcher.download_image(chosen["url"], target_bg):
                bg_image_path = str(target_bg)

    # If no new background was requested (e.g. only title/topic edited), reuse existing CLEAN background!
    if not bg_image_path or not Path(bg_image_path).exists():
        # 1) Try standard clean background saved for this job
        clean_bg = job_dir / "thumbnail_bg.jpg"
        if clean_bg.exists() and clean_bg.stat().st_size > 1000:
            bg_image_path = str(clean_bg)
        else:
            # 2) Try any thumb_bg_*.jpg or user_thumb_bg_*.jpg in the folder
            bg_files = sorted(job_dir.glob("thumb_bg_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not bg_files:
                bg_files = sorted(job_dir.glob("user_thumb_bg_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
            if bg_files and bg_files[0].exists():
                bg_image_path = str(bg_files[0])
            else:
                # 3) Try temp images downloaded for this job
                temp_img_dir = config.TEMP_DIR / job_id / "images"
                if temp_img_dir.exists():
                    t_imgs = sorted(temp_img_dir.glob("*.jpg"), key=lambda p: p.stat().st_size, reverse=True)
                    if t_imgs:
                        bg_image_path = str(t_imgs[0])

    # 3. Generate thumbnail
    thumbnail_generator.generate_thumbnail(
        title=title,
        topic=topic,
        background_image_path=bg_image_path,
        output_path=thumbnail_path,
        theme=job.get("theme", "default"),
    )

    # 4. Update job metadata
    from services.translator import translate_to_ru
    title_ru = translate_to_ru(title)

    if "result" not in job or not job["result"]:
        job["result"] = {}
    job["result"]["thumbnail_path"] = str(thumbnail_path)
    job["result"]["thumbnail_hook"] = title
    job["result"]["thumbnail_hook_ru"] = title_ru
    job["thumbnail_hook"] = title
    job["thumbnail_hook_ru"] = title_ru
    if "script_data" in job and isinstance(job["script_data"], dict):
        job["script_data"]["thumbnail_hook"] = title
        job["script_data"]["thumbnail_hook_ru"] = title_ru
    _save_jobs()

    ts = int(time.time() * 1000)
    return {
        "status": "ok",
        "thumbnail_url": f"/api/job/{job_id}/thumbnail?t={ts}",
        "title": title,
        "title_ru": title_ru,
        "topic": topic,
    }


@app.post("/api/job/{job_id}/thumbnail/generate-titles")
async def generate_thumbnail_titles(job_id: str):
    """Generate multiple AI clickbait thumbnail headline variants with Russian translations."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    script_data = job.get("script_data", {})
    topic = job.get("topic", "")
    lead_story = script_data.get("main_lead_story", "")
    current_title = job.get("generated_title", "")
    lang = job.get("language", "de")

    from services import translator
    variants = await translator.generate_thumbnail_headline_variants(
        topic=topic,
        current_title=current_title,
        lead_story=lead_story,
        lang=lang,
        count=5,
    )
    return {"status": "ok", "variants": variants}


@app.post("/api/translate")
async def translate_text_endpoint(req: TranslateRequest):
    """Translate any text to Russian quickly."""
    from services.translator import translate_to_ru
    return {"status": "ok", "translation": translate_to_ru(req.text)}


@app.post("/api/job/{job_id}/thumbnail/upload")
async def upload_thumbnail_bg(
    job_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    topic: str = Form(""),
):
    """Upload custom image file as thumbnail background."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    job_dir = config.OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = job_dir / "thumbnail.jpg"

    content = await file.read()
    uploaded_bg = job_dir / "thumbnail_bg.jpg"
    with open(uploaded_bg, "wb") as f:
        f.write(content)

    t_title = (title.strip() or job.get("script_data", {}).get("thumbnail_hook") or job.get("result", {}).get("title") or "НОВОСТИ").upper()
    t_topic = (topic.strip() or job.get("topic") or "НОВОСТИ").upper()

    thumbnail_generator.generate_thumbnail(
        title=t_title,
        topic=t_topic,
        background_image_path=str(uploaded_bg),
        output_path=thumbnail_path,
        theme=job.get("theme", "default"),
    )

    if "result" not in job or not job["result"]:
        job["result"] = {}
    job["result"]["thumbnail_path"] = str(thumbnail_path)
    if "script_data" in job and isinstance(job["script_data"], dict):
        job["script_data"]["thumbnail_hook"] = t_title
    _save_jobs()

    ts = int(time.time() * 1000)
    return {
        "status": "ok",
        "thumbnail_url": f"/api/job/{job_id}/thumbnail?t={ts}",
        "title": t_title,
        "topic": t_topic,
    }


# === Slide Review & Replacement Routes ===

class SlideFlagRequest(BaseModel):
    flagged: bool


class SlideCandidatesRequest(BaseModel):
    query: str | None = None


class SelectCandidateRequest(BaseModel):
    url: str
    fallback_url: str = ""


_IMAGE_HASH_CACHE: dict[str, str] = {}

def _get_cached_image_hash(p: Path) -> str:
    path_str = str(p)
    if not p.exists() or not p.is_file():
        return ""
    mtime = int(p.stat().st_mtime)
    cache_key = f"{path_str}_{mtime}"
    if cache_key in _IMAGE_HASH_CACHE:
        return _IMAGE_HASH_CACHE[cache_key]
    h = image_searcher.compute_image_hash(p)
    if h:
        _IMAGE_HASH_CACHE[cache_key] = h
    return h


def _get_or_create_slide_thumbnail(job_id: str, index: int, src_path: Path, mtime: int) -> Path:
    """Generate or retrieve a fast, lightweight thumbnail (360x202) for slide moderation."""
    thumb_dir = config.OUTPUT_DIR / "temp" / job_id / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"slide_{index:03d}_{mtime}.jpg"
    if thumb_path.exists():
        return thumb_path
    
    try:
        from PIL import Image
        with Image.open(src_path) as img:
            img = img.convert("RGB")
            img.thumbnail((360, 202), Image.Resampling.BILINEAR)
            tmp_path = thumb_dir / f"slide_{index:03d}_{mtime}_tmp.jpg"
            img.save(tmp_path, format="JPEG", quality=75)
            tmp_path.replace(thumb_path)
            return thumb_path
    except Exception as e:
        logger.warning(f"Failed to create thumbnail for slide {index} ({src_path}): {e}")
        return src_path


@app.get("/api/job/{job_id}/slides")
async def get_job_slides(job_id: str):
    """Get all slides for moderation and preview."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    slides = job.get("slides", [])
    result = []
    for s in slides:
        idx = s["index"]
        p = Path(s["image_path"])
        mtime = int(p.stat().st_mtime) if p.exists() else 0
        dur_ms = s.get("duration_ms", 5000)
        result.append({
            "index": idx,
            "text": s.get("text", ""),
            "query": s.get("query", ""),
            "duration_ms": dur_ms,
            "duration_sec": round(dur_ms / 1000, 1),
            "image_url": f"/api/job/{job_id}/slide/{idx}?t={mtime}",
            "thumb_url": f"/api/job/{job_id}/slide/{idx}?thumb=1&t={mtime}",
            "flagged": s.get("flagged", False),
            "replaced": s.get("replaced", False),
        })
    return {
        "job_id": job_id,
        "topic": job.get("topic", ""),
        "status": job.get("status", ""),
        "slides": result,
        "total": len(result),
        "flagged_count": sum(1 for s in result if s["flagged"]),
        "replaced_count": sum(1 for s in result if s["replaced"]),
    }


@app.get("/api/job/{job_id}/slide/{index}")
async def get_slide_image(job_id: str, index: int, thumb: bool = False):
    """Serve local slide image (full-size or fast cached thumbnail)."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    slides = jobs[job_id].get("slides", [])
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=404, detail="Slide not found")
    p = Path(slides[index]["image_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    
    if thumb:
        mtime = int(p.stat().st_mtime)
        thumb_path = _get_or_create_slide_thumbnail(job_id, index, p, mtime)
        return FileResponse(str(thumb_path), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
        
    return FileResponse(str(p), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=60"})


@app.post("/api/job/{job_id}/slide/{index}/flag")
async def flag_slide(job_id: str, index: int, req: SlideFlagRequest):
    """Mark or unmark slide for replacement."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    slides = jobs[job_id].get("slides", [])
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=404, detail="Slide not found")
    slides[index]["flagged"] = req.flagged
    _save_jobs()
    return {"status": "ok", "index": index, "flagged": req.flagged}


@app.post("/api/job/{job_id}/slide/{index}/search-candidates")
async def search_slide_candidates(job_id: str, index: int, req: SlideCandidatesRequest = None):
    """Search online alternative photos for this slide, pre-validating links and tracking duplicates."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    slides = job.get("slides", [])
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=404, detail="Slide not found")
    
    slide = slides[index]
    from services.query_helper import build_thematic_replacement_query, clean_query_text
    
    topic = job.get("topic", "")
    title = job.get("script_data", {}).get("title") or job.get("result", {}).get("title") or ""
    lead_story = job.get("script_data", {}).get("main_lead_story", "")
    
    # If user provided explicit search query in input, use it (cleaned).
    # Otherwise generate a SMART thematic query anchored to topic & headline.
    if req and req.query and req.query.strip():
        q = clean_query_text(req.query.strip())
    else:
        q = build_thematic_replacement_query(
            topic=topic,
            title=title,
            lead_story=lead_story,
            index=index,
            segment_text=slide.get("text", "")
        )
    
    # Track used images in the video (using fast memory cache for file hashes & persistent used URLs)
    used_urls = set(job.get("used_urls", []))
    urls_file = config.OUTPUT_DIR / "temp" / job_id / "used_urls.json"
    if urls_file.exists():
        try:
            loaded_urls = json.loads(urls_file.read_text(encoding="utf-8"))
            used_urls.update(loaded_urls)
        except Exception:
            pass
            
    used_hashes = set()
    for s in slides:
        src_u = s.get("source_url")
        if src_u:
            used_urls.add(src_u)
        p_str = s.get("image_path", "")
        if p_str:
            p = Path(p_str)
            if p.exists() and p.is_file():
                h = _get_cached_image_hash(p)
                if h:
                    used_hashes.add(h)
                    s["image_hash"] = h
    
    # Search across Yandex, Unsplash, Pixabay for a wide pool
    raw_images = await image_searcher.search_images(q, count_per_source=15)
    
    # Fast validation and duplicate filtering
    valid_candidates = await image_searcher.validate_candidate_images(
        candidates=raw_images,
        max_valid=16,
        used_urls=used_urls,
        used_hashes=used_hashes,
    )
    
    from urllib.parse import quote_plus
    candidates = []
    for img in valid_candidates:
        u = img.get("url")
        thumb = img.get("thumbnail") or u
        fallback = img.get("fallback_url") or thumb or u
        if u:
            candidates.append({
                "url": u,
                "thumbnail": thumb,
                "fallback_url": fallback,
                "proxy_url": f"/api/proxy-thumb?url={quote_plus(u)}",
                "source": img.get("source", "web"),
                "alt": img.get("alt", q),
                "already_used": img.get("already_used", False),
            })
            
    return {
        "index": index,
        "query": q,
        "topic": topic,
        "title": title,
        "candidates": candidates
    }


@app.post("/api/job/{job_id}/slide/{index}/select-candidate")
async def select_slide_candidate(job_id: str, index: int, req: SelectCandidateRequest):
    """Download chosen candidate URL and assign as slide image."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    slides = job.get("slides", [])
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=404, detail="Slide not found")
    
    temp_dir = config.OUTPUT_DIR / "temp" / job_id / "images"
    temp_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    new_path = temp_dir / f"slide_{index:03d}_user_{ts}.jpg"
    
    fallback_u = getattr(req, "fallback_url", "")
    logger.info(f"Downloading user-selected candidate for slide {index} from URL: {req.url[:70]}...")
    ok = await image_searcher.download_image(req.url, new_path, is_user_selection=True, fallback_url=fallback_u)
    if not ok and fallback_u and fallback_u != req.url:
        logger.info(f"Retrying candidate download using fallback: {fallback_u[:70]}...")
        ok = await image_searcher.download_image(fallback_u, new_path, is_user_selection=True)
        
    if not ok:
        logger.warning(f"Failed to download candidate for slide {index} from {req.url}")
        raise HTTPException(status_code=400, detail="Не удалось скачать выбранное фото")
    
    # Track as used in job state
    if "used_urls" not in job:
        job["used_urls"] = []
    job["used_urls"].append(req.url)
    if fallback_u:
        job["used_urls"].append(fallback_u)
        
    slides[index]["image_path"] = str(new_path)
    slides[index]["source_url"] = req.url
    slides[index]["replaced"] = True
    slides[index]["flagged"] = False
    _save_jobs()
    
    # Pre-generate thumbnail immediately for instant UI refresh
    _get_or_create_slide_thumbnail(job_id, index, new_path, ts)
    
    return {
        "status": "ok",
        "index": index,
        "image_url": f"/api/job/{job_id}/slide/{index}?t={ts}",
        "thumb_url": f"/api/job/{job_id}/slide/{index}?thumb=1&t={ts}",
    }


@app.post("/api/job/{job_id}/slide/{index}/upload")
async def upload_slide_image(job_id: str, index: int, file: UploadFile = File(...)):
    """Upload custom image file for a specific slide."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    slides = jobs[job_id].get("slides", [])
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=404, detail="Slide not found")
    
    temp_dir = config.OUTPUT_DIR / "temp" / job_id / "images"
    temp_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    new_path = temp_dir / f"slide_{index:03d}_upload_{ts}.jpg"
    
    content = await file.read()
    with open(new_path, "wb") as f:
        f.write(content)
    
    slides[index]["image_path"] = str(new_path)
    slides[index]["replaced"] = True
    slides[index]["flagged"] = False
    _save_jobs()
    
    _get_or_create_slide_thumbnail(job_id, index, new_path, ts)
    
    return {
        "status": "ok",
        "index": index,
        "image_url": f"/api/job/{job_id}/slide/{index}?t={ts}",
        "thumb_url": f"/api/job/{job_id}/slide/{index}?thumb=1&t={ts}",
    }


@app.post("/api/job/{job_id}/slide/{index}/quick-cycle")
async def quick_cycle_slide(job_id: str, index: int):
    """Quickly switch slide to another photo from the project pool."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    slides = jobs[job_id].get("slides", [])
    if index < 0 or index >= len(slides):
        raise HTTPException(status_code=404, detail="Slide not found")
    
    valid_pool = [s["image_path"] for s in slides if Path(s["image_path"]).exists() and s["image_path"] != slides[index]["image_path"]]
    if not valid_pool:
        raise HTTPException(status_code=400, detail="Нет альтернативных фото в пуле ролика")
    
    chosen = valid_pool[(index * 13 + int(time.time())) % len(valid_pool)]
    slides[index]["image_path"] = chosen
    slides[index]["replaced"] = True
    slides[index]["flagged"] = False
    _save_jobs()
    
    ts = int(time.time() * 1000)
    _get_or_create_slide_thumbnail(job_id, index, Path(chosen), ts)
    
    return {
        "status": "ok",
        "index": index,
        "image_url": f"/api/job/{job_id}/slide/{index}?t={ts}",
        "thumb_url": f"/api/job/{job_id}/slide/{index}?thumb=1&t={ts}",
    }


@app.post("/api/job/{job_id}/slides/replace-flagged")
async def replace_flagged_slides(job_id: str):
    """Auto-replace all flagged slides with guaranteed unique, non-repeating photos strictly matching topic & headline."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    slides = job.get("slides", [])
    temp_dir = config.OUTPUT_DIR / "temp" / job_id / "images"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    from services.query_helper import build_thematic_replacement_query, build_thematic_query_pool
    topic = job.get("topic", "")
    title = job.get("script_data", {}).get("title") or job.get("result", {}).get("title") or ""
    lead_story = job.get("script_data", {}).get("main_lead_story", "")
    
    # 1. Pre-populate used image hashes from ALL existing unflagged slides in this video!
    used_hashes = set()
    used_urls = set()
    for s in slides:
        if not s.get("flagged") and s.get("image_path"):
            p = Path(s["image_path"])
            if p.exists() and p.is_file():
                h = image_searcher.compute_image_hash(p)
                if h:
                    used_hashes.add(h)
    
    # 2. Build deep dynamic query pool
    query_pool = build_thematic_query_pool(topic=topic, title=title, lead_story=lead_story, count=max(60, len(slides)))
    replaced_indices = []
    replace_counter = 0

    for slide in slides:
        if slide.get("flagged"):
            idx = slide["index"]
            primary_q = build_thematic_replacement_query(
                topic=topic,
                title=title,
                lead_story=lead_story,
                index=idx + replace_counter,
                segment_text=slide.get("text", "")
            )
            replace_counter += 1
            
            # Formulate query cascade for this slide
            queries_to_try = [primary_q]
            if query_pool:
                queries_to_try.append(query_pool[(idx + replace_counter * 3) % len(query_pool)])
                queries_to_try.append(query_pool[(idx + replace_counter * 7 + 1) % len(query_pool)])
            
            slide["query"] = primary_q
            downloaded = False
            
            for q in queries_to_try:
                if downloaded:
                    break
                candidates = await image_searcher.search_images(q, count_per_source=15)
                for c in candidates:
                    u = c.get("url")
                    if not u or u in used_urls:
                        continue
                    
                    new_p = temp_dir / f"slide_{idx:03d}_rep_{int(time.time()*1000)}.jpg"
                    if await image_searcher.download_image(u, new_p, forbidden_hashes=used_hashes):
                        new_h = image_searcher.compute_image_hash(new_p)
                        if new_h and new_h not in used_hashes:
                            used_hashes.add(new_h)
                            used_urls.add(u)
                            slide["image_path"] = str(new_p)
                            slide["replaced"] = True
                            slide["flagged"] = False
                            downloaded = True
                            replaced_indices.append(idx)
                            logger.info(f"[{job_id}] Auto-replaced slide #{idx+1} with fresh unique photo: {new_p.name} (hash={new_h[:8]})")
                            break
                        else:
                            new_p.unlink(missing_ok=True)
            
            if not downloaded:
                # If all external searches exhausted, try picking an unflagged image ONLY IF hash is distinct
                all_imgs = [s["image_path"] for s in slides if not s.get("flagged") and Path(s["image_path"]).exists() and s["image_path"] != slide["image_path"]]
                if all_imgs:
                    cand_img = all_imgs[(idx * 7) % len(all_imgs)]
                    slide["image_path"] = cand_img
                    slide["replaced"] = True
                    slide["flagged"] = False
                    replaced_indices.append(idx)
    
    _save_jobs()
    return {"status": "ok", "replaced_count": len(replaced_indices), "indices": replaced_indices}


@app.post("/api/job/{job_id}/slides/approve")
async def approve_slides(job_id: str):
    """Approve slides and resume video compilation."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    
    ev = _SLIDE_REVIEW_EVENTS.get(job_id)
    if ev:
        job["status"] = "running"
        job["current_step"] = "Сборка видео (с утвержденными слайдами)..."
        _save_jobs()
        ev.set()
        return {"status": "ok", "message": "Сборка видео успешно запущена"}
    else:
        return {"status": "ok", "message": "Слайды сохранены"}


class AcuteSelectRequest(BaseModel):
    angle_id: str
    topic_query: str = ""


# === Pipeline ===



async def run_pipeline(job_id: str, req: VideoRequest):
    """Main video generation pipeline with concurrency control."""
    if job_id not in jobs:
        return
    job = jobs[job_id]
    
    # If another job is currently rendering, mark status with queue position
    if PIPELINE_SEMAPHORE.locked():
        queue_pos = sum(
            1 for j in jobs.values()
            if j.get("status") == "queued" and j.get("created_at", "") <= job.get("created_at", "")
        )
        _update_job(job, "queued", 0, f"В очереди (позиция: {queue_pos})...", "queued",
                    detail="Ожидание завершения предыдущего ролика...")

    try:
        async with PIPELINE_SEMAPHORE:
            if job.get("status") == "cancelled":
                return
            await _run_pipeline_impl(job_id, req)
    except asyncio.CancelledError:
        logger.info(f"[{job_id}] Pipeline task cancelled.")
        job["status"] = "cancelled"
        job["current_step"] = "Отменено пользователем"
        job["detail"] = "Генерация прервана пользователем"
        _save_jobs()
    finally:
        _refresh_queue_positions()


async def _run_pipeline_impl(job_id: str, req: VideoRequest):
    job = jobs[job_id]
    
    def _check_cancelled():
        if job.get("status") == "cancelled":
            raise asyncio.CancelledError()

    try:
        _check_cancelled()
        job_dir = config.OUTPUT_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = config.TEMP_DIR / job_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # ====== STEP 1: Fetch News ======
        _check_cancelled()
        _update_job(job, "running", 5, "Поиск новостей и сбор первоисточников...", "search_started",
                    detail="Ленты агентств (РИА, Lenta, Коммерсантъ) + Google News")
        
        articles = await news_fetcher.fetch_news(
            topic=req.topic,
            lang=req.language,
            newsapi_key=config.NEWSAPI_KEY,
            acute_angle_id=req.acute_angle_id,
        )
        
        _check_cancelled()
        if not articles:
            raise RuntimeError(f"Не найдено новостей по теме: {req.topic}")
        
        articles_with_text = [a for a in articles if len(a.get("full_text", "")) >= 250]
        total_fact_chars = sum(len(a.get("full_text", "")) for a in articles_with_text)
        
        sources_payload = [
            {
                "title": a.get("title", ""),
                "source": a.get("source", "СМИ"),
                "url": a.get("link", ""),
                "text_len": len(a.get("full_text", "")),
                "preview": a.get("preview") or (a.get("full_text", "")[:300] + "..."),
                "full_text": a.get("full_text", ""),
            }
            for a in articles
        ]
        job["sources"] = sources_payload
        job["sources_summary"] = {
            "count": len(articles_with_text),
            "total_chars": total_fact_chars,
        }
        
        try:
            with open(job_dir / "sources.json", "w", encoding="utf-8") as f:
                json.dump({"summary": job["sources_summary"], "sources": sources_payload}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write sources.json: {e}")
        
        _update_job(job, "running", 15, f"Фактура получена: {len(articles_with_text)} статей", "news_fetched",
                    detail=f"Собрано {total_fact_chars:,} знаков проверенной фактуры из {len(articles_with_text)} статей")
        
        # ====== STEP 2: Generate Script ======
        _check_cancelled()
        _update_job(job, "running", 20, "Генерация уникального сценария (Gemini AI)...", "script_started",
                    detail=f"Модель: {config.GEMINI_MODEL}, цель: {req.target_length} знаков")
        
        recent_titles = news_fetcher.get_recent_video_titles(limit=6)
        if recent_titles:
            logger.info(f"Предыдущие заголовки для исключения повторов ({len(recent_titles)}): {recent_titles}")
        
        script_data = await script_generator.generate_script(
            articles=articles,
            topic=req.topic,
            lang=req.language,
            target_length=req.target_length,
            previous_titles=recent_titles,
        )
        
        # Save title to history immediately so future runs don't repeat it
        news_fetcher.save_news_history([], [], new_video_title=script_data["title"])
        
        main_lead = script_data.get("main_lead_story", "")

        # Save script
        script_path = job_dir / "script.txt"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(f"Title: {script_data['title']}\n")
            if main_lead:
                f.write(f"Main Lead Story: {main_lead}\n")
            f.write(f"Description: {script_data.get('description', '')}\n")
            f.write(f"{'='*60}\n\n")
            f.write(script_data["script"])
        
        script_len = len(script_data["script"])
        num_segments = len(script_data["segments"])
        
        # Save script data on job immediately for viewing via button
        from services.translator import translate_to_ru
        title_ru = script_data.get("title_ru") or translate_to_ru(script_data["title"])
        hook_text = script_data.get("thumbnail_hook", "")
        hook_ru = script_data.get("thumbnail_hook_ru") or translate_to_ru(hook_text)

        job["script_data"] = {
            "title": script_data["title"],
            "title_ru": title_ru,
            "thumbnail_hook": hook_text,
            "thumbnail_hook_ru": hook_ru,
            "main_lead_story": main_lead,
            "description": script_data.get("description", ""),
            "script": script_data["script"],
            "length": script_len,
            "segments_count": num_segments,
        }
        job["generated_title"] = script_data["title"]
        job["title_ru"] = title_ru
        job["thumbnail_hook"] = hook_text
        job["thumbnail_hook_ru"] = hook_ru
        job["main_lead_story"] = main_lead
        job["has_script"] = True
        
        # Log lead story & clickbait title prominently
        logger.info("\n" + "="*70)
        if main_lead:
            logger.info(f"🎯 [ГЛАВНАЯ ТЕМА-ОСНОВА]: {main_lead}")
        logger.info(f"🔥 [КЛИКБЕЙТНЫЙ ЗАГОЛОВОК]: {script_data['title']}")
        if title_ru:
            logger.info(f"🇷🇺 [ПЕРЕВОД ЗАГОЛОВКА]: {title_ru}")
        if hook_text:
            logger.info(f"🖼️ [ТЕКСТ НА ОБЛОЖКЕ]: {hook_text} (🇷🇺 {hook_ru})")
        logger.info("="*70 + "\n")
        
        _update_job(job, "running", 35, f"Сценарий готов: {script_len} знаков", "script_done",
                    detail=f"Заголовок: {script_data['title']} (🇷🇺 {title_ru})")
        
        # In fast preview mode: keep 4 slides (~20-25 sec)
        if req.is_preview:
            script_data["segments"] = script_data["segments"][:4]
            script_data["script"] = " ".join(script_data["segments"])
            if "search_queries" in script_data:
                script_data["search_queries"] = script_data["search_queries"][:4]
            num_segments = len(script_data["segments"])
            logger.info(f"[{job_id}] ⚡ ЭКСПРЕСС-ТЕСТ: ограничено до {num_segments} слайдов ({len(script_data['script'])} знаков)")
        
        # ====== STEP 3: Text-to-Speech ======
        _check_cancelled()
        voice_info = config.VOICES_BY_ID.get(req.voice_id)
        if voice_info:
            if voice_info.get("engine") == "gemini":
                voice = f"gemini:{voice_info.get('gemini_voice', 'Charon')}"
            else:
                voice = voice_info.get("edge", config.TTS_VOICES.get(req.language, "ru-RU-DmitryNeural"))
            voice_name = f"{voice_info['name']} ({voice_info['gender']})"
        else:
            voice = config.TTS_VOICES.get(req.language, config.TTS_VOICES["ru"])
            voice_name = voice
        
        _update_job(job, "running", 40, f"Озвучка и поиск фото (параллельно)...", "tts_started",
                    detail=f"Голос: {voice_name}, темп: {req.voice_rate}")
        
        search_queries = script_data.get("search_queries", [req.topic] * num_segments)
        
        # Combined progress for the two parallel stages: 40% -> 70%
        par_state = {"tts_pct": 0, "img_pct": 0, "tts_msg": "старт", "img_msg": "старт"}
        
        def _refresh_parallel_progress():
            job["progress"] = min(70, 40 + int(par_state["tts_pct"] * 0.15 + par_state["img_pct"] * 0.15))
            job["detail"] = f"🎙️ {par_state['tts_msg']}  |  🖼️ {par_state['img_msg']}"
        
        def tts_progress(pct, msg):
            par_state["tts_pct"] = pct
            par_state["tts_msg"] = msg
            _refresh_parallel_progress()
            logger.info(f"[{job['id']}] TTS {pct}%: {msg}")
        
        def img_progress(msg):
            import re
            m = re.search(r'\[(\d+)/(\d+)\]', msg)
            if m:
                cur, tot = int(m.group(1)), int(m.group(2))
                if tot > 0:
                    par_state["img_pct"] = int(cur / tot * 100)
                    par_state["img_msg"] = f"Фото {cur}/{tot}"
            _refresh_parallel_progress()
            logger.info(f"[{job['id']}] {msg}")
        
        tts_result, image_paths = await asyncio.gather(
            tts_engine.generate_segmented_speech(
                segments=script_data["segments"],
                output_dir=temp_dir / "audio",
                lang=req.language,
                voice=voice,
                rate=req.voice_rate,
                full_text=script_data["script"],
                progress_callback=tts_progress,
            ),
            image_searcher.search_and_download_images(
                queries=search_queries[:num_segments],
                output_dir=temp_dir / "images",
                progress_callback=img_progress,
                topic=req.topic,
                title=script_data.get("title", ""),
            ),
        )
        
        tts_engine_name = tts_result.get("engine", "unknown")
        downloaded_count = sum(1 for p in image_paths if p)
        _update_job(job, "running", 70, f"Озвучка готова, загружено {downloaded_count}/{num_segments} фото", "images_downloaded",
                    detail=f"Движок: {tts_engine_name} | Фото: {downloaded_count}, пропущено: {num_segments - downloaded_count}")
        
        # ====== STEP 5: Analyze Images (optional) ======
        _check_cancelled()
        if not req.skip_image_analysis and downloaded_count > 0:
            def analysis_progress(cur, total, msg):
                pct = 72 + int((cur / max(total, 1)) * 6)  # 72% to 78%
                job["progress"] = min(78, pct)
                job["detail"] = msg
                logger.info(f"[{job['id']}] {msg}")

            _update_job(job, "running", 72, "Анализ изображений (Gemini Vision)...", "analysis_started",
                        detail=f"Проверка {downloaded_count} фото на качество и тему...")
            
            analysis_results = await image_analyzer.filter_images(
                image_paths=image_paths,
                segments=script_data["segments"],
                topic=req.topic,
                progress_callback=analysis_progress,
            )
            
            approved_pool = [
                r["path"] for r in analysis_results 
                if r.get("relevant") and r.get("path") and Path(r["path"]).exists()
            ]
            for result in analysis_results:
                idx = result.get("segment_index", -1)
                if 0 <= idx < len(image_paths) and not result.get("relevant") and result.get("score", 0) < 4:
                    if approved_pool:
                        sub = approved_pool[idx % len(approved_pool)]
                        logger.info(f"Replacing rejected image for segment {idx} (score={result.get('score')}) with approved photo: {Path(sub).name}")
                        image_paths[idx] = sub
                    else:
                        logger.info(f"Image rejected: segment {idx}, score={result.get('score')}, reason={result.get('reason')}")
            
            _update_job(job, "running", 78, "Анализ изображений завершен", "analysis_done",
                        detail=f"Проверено {downloaded_count} изображений")
        
        # ====== PREPARE SLIDES METADATA ======
        _check_cancelled()
        segment_timings = tts_result.get("segment_timings", [])
        slides_data = []
        for s_idx, s_path in enumerate(image_paths):
            dur_ms = segment_timings[s_idx]["duration_ms"] if (s_idx < len(segment_timings)) else 5000
            s_text = script_data["segments"][s_idx] if (s_idx < len(script_data["segments"])) else ""
            s_q = search_queries[s_idx] if (s_idx < len(search_queries)) else req.topic
            slides_data.append({
                "index": s_idx,
                "image_path": str(s_path),
                "text": s_text,
                "query": s_q,
                "duration_ms": dur_ms,
                "flagged": False,
                "replaced": False,
            })
        job["slides"] = slides_data
        _save_jobs()

        # If user enabled manual slide review, pause pipeline and await approval
        if getattr(req, "review_slides", False):
            _update_job(
                job, "awaiting_slide_review", 75,
                f"Слайды готовы ({len(slides_data)} шт.) — ожидание модерации",
                "awaiting_slide_review",
                detail=f"Проверьте отобранные слайды в Студии слайдов перед сборкой видео."
            )
            _save_jobs()

            review_ev = asyncio.Event()
            _SLIDE_REVIEW_EVENTS[job_id] = review_ev
            logger.info(f"[{job_id}] ⏸️ Пауза перед сборкой: ожидание модерации {len(slides_data)} слайдов пользователем...")
            try:
                await review_ev.wait()
            finally:
                _SLIDE_REVIEW_EVENTS.pop(job_id, None)

            if job.get("status") == "cancelled":
                logger.info(f"[{job_id}] Задача отменена во время проверки слайдов.")
                return

            # Sync any slide replacements made by the user
            image_paths = [s["image_path"] for s in job["slides"]]
            logger.info(f"[{job_id}] ▶️ Слайды утверждены! Переход к сборке видео с {len(image_paths)} слайдами.")

        # ====== STEP 6: Compile Video ======
        _check_cancelled()
        _update_job(job, "running", 80, "Сборка видео...", "video_started",
                    detail=f"Слайдов: {num_segments}, разрешение: {config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}")

        
        video_path = job_dir / f"{_sanitize_filename(req.topic)}_{job_id}.mp4"
        
        # Set progress callback so video compiler can report detailed progress
        def video_progress(msg):
            job["detail"] = msg
            logger.info(f"[{job['id']}] Video: {msg}")
        
        video_compiler.set_progress_callback(video_progress)
        
        await video_compiler.compile_video(
            image_paths=image_paths,
            audio_path=tts_result["combined_audio"],
            output_path=video_path,
            segment_timings=tts_result.get("segment_timings"),
            subtitles_path=tts_result.get("subtitles_ass") or tts_result.get("subtitles_srt"),
            ken_burns=getattr(req, "ken_burns", False),
            transitions=getattr(req, "transitions", True),
        )
        
        _update_job(job, "running", 92, "Video skompilirovano", "video_done",
                    detail=f"Fajl: {video_path.name}")
        
        # ====== STEP 7: Generate Thumbnail ======
        _update_job(job, "running", 95, "Generacija oblozhki YouTube...", "thumbnail_started")
        
        # Dedicated search for high-impact thumbnail background matching this specific lead story
        thumb_query = (
            script_data.get("thumbnail_query")
            or script_data.get("thumbnail_hook")
            or script_data.get("main_lead_story")
            or req.topic
        )
        clean_q = re.sub(r'[*#_`!?:;\"\'«»]', '', thumb_query).strip()
        words = clean_q.split()
        if len(words) > 5:
            clean_q = " ".join(words[:5])

        bg_image = None
        try:
            candidates = await image_searcher.search_yandex(clean_q, count=8)
            if not candidates or len(candidates) < 2:
                backup = await image_searcher.search_images(clean_q, count_per_source=4)
                candidates.extend(backup)
            for c in candidates:
                u = c.get("url")
                if u:
                    cand_bg = job_dir / "thumbnail_bg.jpg"
                    if await image_searcher.download_image(u, cand_bg):
                        bg_image = str(cand_bg)
                        break
        except Exception as e:
            logger.warning(f"Dedicated thumbnail background search failed: {e}")

        # Fallback to downloaded video images
        if not bg_image or not Path(bg_image).exists():
            bg_image = next((p for p in image_paths if p), None)
        
        thumbnail_path = job_dir / "thumbnail.jpg"
        thumb_text = script_data.get("thumbnail_hook") or script_data["title"]
        thumbnail_generator.generate_thumbnail(
            title=thumb_text,
            topic=req.topic,
            background_image_path=bg_image,
            output_path=thumbnail_path,
            theme=req.theme,
        )
        
        _update_job(job, "running", 98, "Oblozhka gotova", "thumbnail_done")
        
        # ====== DONE ======
        job["result"] = {
            "video_path": str(video_path),
            "thumbnail_path": str(thumbnail_path),
            "script_path": str(script_path),
            "subtitles_path": tts_result.get("subtitles_srt", ""),
            "title": script_data["title"],
            "title_ru": job.get("title_ru", ""),
            "thumbnail_hook": thumb_text,
            "thumbnail_hook_ru": job.get("thumbnail_hook_ru", ""),
            "description": script_data.get("description", ""),
            "script_length": script_len,
            "segments_count": num_segments,
            "images_count": downloaded_count,
            "tts_engine": tts_engine_name,
            "sources": sources_payload,
            "sources_summary": job.get("sources_summary", {}),
        }
        
        _update_job(job, "completed", 100, "Готово!", "completed",
                    detail=f"Видео: {video_path.name}")
        logger.info(f"Job {job_id} completed: {video_path}")
        
        # Asynchronously send Telegram notification
        try:
            await telegram_notifier.notify_job_completed(job_id, job)
        except Exception as te:
            logger.warning(f"[{job_id}] Telegram notification failed: {te}")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}\n{traceback.format_exc()}")
        job["status"] = "failed"
        job["error"] = str(e)
        job["current_step"] = f"Ошибка: {str(e)[:200]}"
        _save_jobs()


def _refresh_queue_positions():
    """Recalculate and update queue status for all waiting jobs."""
    queued_jobs = [j for j in jobs.values() if j.get("status") == "queued"]
    queued_jobs.sort(key=lambda x: x.get("created_at", ""))
    total = len(queued_jobs)
    for idx, qj in enumerate(queued_jobs):
        pos = idx + 1
        qj["current_step"] = f"В очереди (задача {pos} из {total})..."
        qj["detail"] = f"Ожидание запуска ({pos} в очереди)..."
    _save_jobs()


def _update_job(job: dict, status: str, progress: int, step: str, step_id: str, detail: str = ""):
    """Update job status with detailed info and persist to disk."""
    if job.get("status") == "cancelled":
        return
    job["status"] = status
    job["progress"] = progress
    job["current_step"] = step
    job["detail"] = detail
    if step_id not in job["steps_completed"]:
        job["steps_completed"].append(step_id)
    _save_jobs()
    logger.info(f"[{job['id']}] {step} | {detail}")


def _sanitize_filename(name: str) -> str:
    """Sanitize string for use as filename."""
    import re
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    return name[:50]


# === Startup ===

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print("  News Video Generator")
    print("  http://localhost:8501")
    print("="*60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8501, log_level="info")
