"""
Telegram Notifier Service - Sends notifications with thumbnails, stats, and download/edit links.
"""
import os
import json
import logging
from pathlib import Path
import httpx

import config

logger = logging.getLogger(__name__)

TELEGRAM_CONFIG_FILE = config.BASE_DIR / "telegram_config.json"


def get_telegram_config() -> dict:
    """Read Telegram settings from JSON file or environment variables."""
    cfg = {
        "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "server_url": os.getenv("SERVER_PUBLIC_URL", "http://45.147.31.53:8501"),
        "enabled": False,
    }
    if TELEGRAM_CONFIG_FILE.exists():
        try:
            with open(TELEGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception as e:
            logger.warning(f"Failed to read telegram config: {e}")

    # Set enabled if both bot_token and chat_id are present
    if cfg["bot_token"] and cfg["chat_id"]:
        cfg["enabled"] = cfg.get("enabled", True)
    else:
        cfg["enabled"] = False

    return cfg


def save_telegram_config(bot_token: str, chat_id: str, server_url: str = None, enabled: bool = True) -> dict:
    """Save Telegram settings to disk."""
    current = get_telegram_config()
    server_url = server_url.rstrip("/") if server_url else current.get("server_url", "http://45.147.31.53:8501")
    
    clean_token = bot_token.strip()
    if "..." in clean_token or not clean_token:
        clean_token = current.get("bot_token", "")
    
    clean_chat_id = str(chat_id).strip() or current.get("chat_id", "")
    
    cfg = {
        "bot_token": clean_token,
        "chat_id": clean_chat_id,
        "server_url": server_url.strip(),
        "enabled": bool(enabled and clean_token and clean_chat_id),
    }
    try:
        with open(TELEGRAM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        logger.info("Telegram config saved successfully")
    except Exception as e:
        logger.error(f"Failed to save telegram config: {e}")
        raise
    return cfg


async def send_test_message(bot_token: str, chat_id: str, server_url: str = "http://45.147.31.53:8501") -> dict:
    """Send a test message to verify credentials."""
    current = get_telegram_config()
    clean_token = bot_token.strip()
    if "..." in clean_token or not clean_token:
        clean_token = current.get("bot_token", "")

    clean_chat_id = str(chat_id).strip() or current.get("chat_id", "")
    server_url = (server_url or current.get("server_url") or "http://45.147.31.53:8501").rstrip("/")

    if not clean_token or not clean_chat_id:
        return {"success": False, "error": "Токен бота или Chat ID не заполнены"}

    bot_token = clean_token
    chat_id = clean_chat_id

    text = (
        "🤖 <b>Тестовое уведомление: News Video Generator</b>\n\n"
        "✅ Бот успешно подключен к серверу!\n"
        "Теперь при завершении каждого ролика вы будете получать видео, обложку и кнопки управления прямо в этот чат.\n\n"
        f"🌐 <b>Сервер:</b> {server_url}"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "🌐 Открыть генератор", "url": server_url}]
            ]
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return {"success": True, "message": "Тестовое сообщение успешно отправлено!"}
            else:
                desc = data.get("description", "Неизвестная ошибка Telegram API")
                return {"success": False, "error": f"Ошибка Telegram: {desc}"}
    except Exception as e:
        logger.error(f"Telegram test error: {e}")
        return {"success": False, "error": f"Сетевая ошибка: {str(e)}"}


async def notify_job_completed(job_id: str, job: dict):
    """
    Send formatted completion notification with thumbnail photo and inline buttons.
    """
    cfg = get_telegram_config()
    if not cfg.get("enabled") or not cfg.get("bot_token") or not cfg.get("chat_id"):
        logger.debug("Telegram notifications are disabled or not configured")
        return

    bot_token = cfg["bot_token"]
    chat_id = cfg["chat_id"]
    server_url = (cfg.get("server_url") or "http://45.147.31.53:8501").rstrip("/")

    result = job.get("result") or {}
    topic = job.get("topic", "Без темы")
    title = result.get("title") or topic
    
    script_chars = result.get("script_length", 0)
    segments = result.get("segments_count", 0)
    approx_min = max(1, round(script_chars / 850)) if script_chars else 0

    video_url = f"{server_url}/api/download/{job_id}/video"
    thumb_url = f"{server_url}/api/download/{job_id}/thumbnail"
    edit_url = f"{server_url}/?edit_thumb={job_id}"

    caption = (
        "🎬 <b>Готов новый видеоролик!</b>\n\n"
        f"🔥 <b>Заголовок:</b> {title}\n"
        f"📌 <b>Тема:</b> {topic}\n"
        f"⏱ <b>Хронометраж:</b> ~{approx_min} мин ({script_chars:,} знаков, {segments} слайдов)\n\n"
        f"📥 <a href=\"{video_url}\">Скачать видео (MP4)</a>\n"
        f"🖼 <a href=\"{thumb_url}\">Скачать обложку (JPG)</a>\n"
        f"✏️ <a href=\"{edit_url}\">Редактировать обложку</a>"
    )

    inline_keyboard = [
        [
            {"text": "📹 Скачать видео", "url": video_url},
            {"text": "🖼 Обложка", "url": thumb_url},
        ],
        [
            {"text": "✏️ Редактировать обложку", "url": edit_url},
            {"text": "🌐 Открыть сайт", "url": server_url},
        ]
    ]

    # Look for thumbnail file to send as photo
    thumb_path = None
    if result.get("thumbnail_path"):
        p = Path(result["thumbnail_path"])
        if p.exists():
            thumb_path = p
    if not thumb_path:
        # Check standard job dir
        job_thumb = config.OUTPUT_DIR / job_id / "thumbnail.jpg"
        if job_thumb.exists():
            thumb_path = job_thumb

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if thumb_path and thumb_path.exists():
                # Send Photo with Caption
                photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                with open(thumb_path, "rb") as f:
                    files = {"photo": (thumb_path.name, f, "image/jpeg")}
                    data = {
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps({"inline_keyboard": inline_keyboard}),
                    }
                    resp = await client.post(photo_url, data=data, files=files)
                    res_json = resp.json()
                    if res_json.get("ok"):
                        logger.info(f"[{job_id}] Telegram photo notification sent successfully")
                        return

            # Fallback to sendMessage if photo upload wasn't used or failed
            msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": caption,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": inline_keyboard},
            }
            resp = await client.post(msg_url, json=payload)
            res_json = resp.json()
            if res_json.get("ok"):
                logger.info(f"[{job_id}] Telegram message notification sent successfully")
            else:
                logger.warning(f"[{job_id}] Telegram notification failed: {res_json}")
    except Exception as e:
        logger.error(f"[{job_id}] Telegram notification error: {e}")
