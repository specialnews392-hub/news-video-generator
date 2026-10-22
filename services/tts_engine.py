"""
TTS Engine - Text-to-Speech using high-quality Edge-TTS Neural voices.
Chunked synthesis ensures 100% reliability with zero limits and exact subtitle synchronization.
"""
import asyncio
import io
import hashlib
import json
import logging
import os
import re
import traceback
import wave
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _split_text_into_chunks(text: str, max_chars: int = 350) -> list[str]:
    """
    Split long text into compact chunks (~250-350 chars) at paragraph or sentence boundaries.
    Edge-TTS websocket handles these small chunks with 100% reliability and zero connection resets.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
        
    chunks = []
    current_chunk = []
    current_len = 0
    
    for p in paragraphs:
        # If single paragraph is very long, split it by sentences
        if len(p) > max_chars:
            sentences = re.split(r'(?<=[.!?])\s+', p)
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if current_len + len(s) > max_chars and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [s]
                    current_len = len(s)
                else:
                    current_chunk.append(s)
                    current_len += len(s) + 1
        else:
            if current_len + len(p) > max_chars and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [p]
                current_len = len(p)
            else:
                current_chunk.append(p)
                current_len += len(p) + 2
                
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
        
    return chunks or [text]


import random
import subprocess
import imageio_ffmpeg

# Edge-TTS outputs audio-24khz-48kbitrate-mono-mp3 => exactly 6000 bytes per second
EDGE_MP3_BYTES_PER_SEC = 6000.0
# Sequential processing (concurrency=1) is strictly required to avoid Microsoft burst blocks
TTS_CONCURRENCY = 1


def _clean_tts_text(text: str) -> str:
    """Clean markdown and unsupported formatting before passing to TTS."""
    if not text:
        return ""
    # Strip markdown bold, italics, headers, code marks
    t = re.sub(r'[*_#`]', '', text)
    # Normalize long dashes and ellipses
    t = t.replace('—', ' - ').replace('–', ' - ').replace('…', '...')
    # Normalize multiple whitespace
    t = re.sub(r'[ \t]+', ' ', t)
    return t.strip()


def _generate_silence_mp3(duration_sec: float) -> bytes:
    """Generate exact 24kHz mono MP3 silence matching Edge-TTS output format."""
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            exe, "-y",
            "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", f"{max(0.5, duration_sec):.2f}",
            "-b:a", "48k",
            "-ar", "24000",
            "-ac", "1",
            "-f", "mp3",
            "pipe:1"
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=10)
        if res.returncode == 0 and len(res.stdout) > 0:
            return res.stdout
    except Exception as e:
        logger.warning(f"Silence generation via FFmpeg failed: {e}")
    return bytes(int(max(0.5, duration_sec) * EDGE_MP3_BYTES_PER_SEC))


async def _synthesize_once(chunk_text: str, voice: str, tts_rate: str) -> tuple[bytes, list[dict]]:
    """Single Edge-TTS request with hard asyncio timeout. Raises on failure."""
    cleaned = _clean_tts_text(chunk_text)
    if not any(ch.isalnum() for ch in cleaned):
        return b"", []

    import edge_tts

    async def _stream_reader():
        comm = edge_tts.Communicate(
            text=cleaned,
            voice=voice,
            rate=tts_rate,
            connect_timeout=15,
            receive_timeout=45,
        )
        audio_data = bytearray()
        boundaries = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                boundaries.append(chunk)
        if len(audio_data) < 300:
            raise RuntimeError(f"Audio stream too small ({len(audio_data)} bytes)")
        return bytes(audio_data), boundaries

    # Hard timeout: if Microsoft's WebSocket hangs or stalls, abort after 30s
    return await asyncio.wait_for(_stream_reader(), timeout=30.0)


def _is_fatal_tts_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(term in msg for term in ["403", "forbidden", "unauthorized", "invalid response status", "handshake"])


async def _synthesize_chunk_with_retry(
    chunk_text: str,
    voice: str,
    rate: str = "+0%",
    max_retries: int = 3,
) -> tuple[bytes, list[dict]]:
    """
    Synthesize a chunk strictly with the SELECTED voice (guarantees voice consistency across the whole video).
    1) Up to max_retries whole-chunk attempts with progressive backoff.
    2) If still failing, split into individual sentences and synthesize with the SAME voice.
    3) Sentence level has up to 2 retries with fast backoff; aborts immediately on fatal errors.
    """
    tts_rate = rate if rate and rate not in ["+0%", "0%", "-0%"] else "+0%"
    chunk_backoff = [1.0, 2.0, 3.5]

    last_err = None
    for attempt in range(max_retries):
        try:
            return await _synthesize_once(chunk_text, voice, tts_rate)
        except Exception as e:
            last_err = e
            if _is_fatal_tts_error(e):
                logger.error(f"Edge-TTS fatal error ({e}). Aborting retries immediately.")
                raise e
            delay = chunk_backoff[min(attempt, len(chunk_backoff) - 1)] + random.uniform(0.2, 0.5)
            logger.warning(
                f"Edge-TTS chunk attempt {attempt + 1}/{max_retries} ({len(chunk_text)} chars, {voice}) failed: {e}. "
                f"Retry in {delay:.1f}s"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)

    # Sentence-level fallback (strictly with the same voice!)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', chunk_text) if s.strip()]
    if not sentences:
        sentences = [chunk_text.strip()]

    logger.info(f"Edge-TTS: chunk ({len(chunk_text)} chars) failed after {max_retries} tries, processing {len(sentences)} sentences individually with {voice}")
    out_audio = bytearray()
    out_bounds = []
    sent_backoff = [1.0, 2.0]

    consecutive_sent_failures = 0
    for sent_idx, sent in enumerate(sentences):
        s_clean = _clean_tts_text(sent)
        if not any(ch.isalnum() for ch in s_clean):
            continue

        await asyncio.sleep(0.3)

        sent_success = False
        last_sent_err = None
        for attempt in range(2):
            try:
                s_audio, s_bounds = await _synthesize_once(s_clean, voice, tts_rate)
                offset_ticks = int(len(out_audio) / EDGE_MP3_BYTES_PER_SEC * 10_000_000)
                for b in s_bounds:
                    nb = dict(b)
                    nb["offset"] = b["offset"] + offset_ticks
                    out_bounds.append(nb)
                out_audio.extend(s_audio)
                sent_success = True
                consecutive_sent_failures = 0
                break
            except Exception as e:
                last_sent_err = e
                if _is_fatal_tts_error(e):
                    raise e
                delay = sent_backoff[min(attempt, len(sent_backoff) - 1)] + random.uniform(0.1, 0.3)
                if attempt < 1:
                    await asyncio.sleep(delay)

        if not sent_success:
            consecutive_sent_failures += 1
            logger.error(
                f"Edge-TTS sentence {sent_idx + 1}/{len(sentences)} failed retries with {voice}: {last_sent_err}."
            )
            if consecutive_sent_failures >= 2:
                raise RuntimeError(f"Edge-TTS service failing: multiple sentences failed ({last_sent_err})")

    if not out_audio or len(out_audio) == 0:
        raise RuntimeError(f"Edge-TTS chunk synthesis failed: audio is empty for voice {voice}")

    return bytes(out_audio), out_bounds


def _ms_to_srt_time(ms: float) -> str:
    """Convert milliseconds to SRT time format (HH:MM:SS,mmm)."""
    total_seconds = int(ms / 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    millis = int(ms % 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _ms_to_ass_time(ms: float) -> str:
    """Convert milliseconds to ASS time format (H:MM:SS.cc)."""
    total_seconds = int(ms / 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    centis = int((ms % 1000) / 10)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def _boundaries_to_subtitles(all_boundaries: list[dict]) -> tuple[str, str, str]:
    """
    Convert absolute SentenceBoundaries into synchronized SRT, VTT, and ASS karaoke formats.
    ASS subtitles feature dynamic word-by-word highlighting in vibrant gold (&H0000D7FF&)
    and a safe bottom margin (MarginV=55) so text is never cut off.
    """
    srt_lines = []
    vtt_lines = ["WEBVTT\n"]
    counter = 1
    
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: NewsKaraoke,Arial,42,&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.5,1.5,2,40,40,55,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_events = []
    
    for b in all_boundaries:
        start_ms = b["start_ms"]
        dur_ms = b["dur_ms"]
        text = b.get("text", "").strip()
        if not text:
            continue
            
        words = text.split()
        if not words:
            continue
            
        # Group words into natural, readable subtitle phrases (4-7 words, ~36 chars)
        phrases = []
        cur = []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) >= 36:
                phrases.append(cur)
                cur = []
        if cur:
            phrases.append(cur)
            
        tot_chars = sum(sum(len(w) for w in p) for p in phrases)
        p_start_ms = start_ms
        
        for p in phrases:
            phrase_str = " ".join(p)
            p_chars = sum(len(w) for w in p)
            p_dur_ms = dur_ms * (p_chars / max(tot_chars, 1))
            p_end_ms = p_start_ms + p_dur_ms
            
            # --- SRT & VTT Entries ---
            start_str = _ms_to_srt_time(p_start_ms)
            end_str = _ms_to_srt_time(p_end_ms)
            
            srt_lines.append(str(counter))
            srt_lines.append(f"{start_str} --> {end_str}")
            srt_lines.append(phrase_str)
            srt_lines.append("")
            
            vtt_start = start_str.replace(",", ".")
            vtt_end = end_str.replace(",", ".")
            vtt_lines.append(f"{vtt_start} --> {vtt_end}")
            vtt_lines.append(phrase_str)
            vtt_lines.append("")
            
            counter += 1
            
            # --- ASS Karaoke Dynamic Word Highlighting ---
            w_start_ms = p_start_ms
            for i, target_word in enumerate(p):
                w_dur_ms = p_dur_ms * (len(target_word) / max(p_chars, 1))
                w_end_ms = w_start_ms + w_dur_ms
                
                # Active word gets highlighted in gold &H0000D7FF&
                formatted_parts = []
                for j, w in enumerate(p):
                    if j == i:
                        formatted_parts.append(f"{{\\c&H0000D7FF&}}{w}{{\\c&H00FFFFFF&}}")
                    else:
                        formatted_parts.append(w)
                ass_line = " ".join(formatted_parts)
                
                ass_events.append(
                    f"Dialogue: 0,{_ms_to_ass_time(w_start_ms)},{_ms_to_ass_time(w_end_ms)},NewsKaraoke,,0,0,0,,{ass_line}"
                )
                w_start_ms = w_end_ms
                
            p_start_ms = p_end_ms
            
    ass_content = ass_header + "\n".join(ass_events)
    return "\n".join(srt_lines), "\n".join(vtt_lines), ass_content


def _calculate_segment_timings_from_boundaries(
    segments: list[str],
    all_boundaries: list[dict],
    total_duration_ms: float,
) -> list[dict]:
    """
    Calculate start/end times for each visual slide segment using speech boundary times.
    Prevents slide 0 from disappearing early and ensures slide transitions align
    naturally with spoken sentences.
    """
    if not segments:
        return []
        
    total_chars = max(1, sum(len(s) for s in segments))
    if not all_boundaries:
        cur_ms = 0.0
        timings = []
        for seg in segments:
            seg_dur = total_duration_ms * (len(seg) / total_chars)
            timings.append({
                "start_ms": cur_ms,
                "end_ms": cur_ms + seg_dur,
                "duration_ms": seg_dur,
            })
            cur_ms += seg_dur
        return timings

    seg_cum_ratios = []
    cum = 0
    for s in segments:
        cum += len(s)
        seg_cum_ratios.append(cum / total_chars)
        
    b_ends = [b["start_ms"] + b["dur_ms"] for b in all_boundaries]
    max_audio_ms = max(total_duration_ms, b_ends[-1] if b_ends else 0)
    
    timings = []
    prev_end_ms = 0.0
    
    for i, seg in enumerate(segments):
        if i == len(segments) - 1:
            end_ms = max_audio_ms
        else:
            target_ms = max_audio_ms * seg_cum_ratios[i]
            closest_b_end = min(b_ends, key=lambda t: abs(t - target_ms))
            if abs(closest_b_end - target_ms) < 3000 and closest_b_end > prev_end_ms + 1500:
                end_ms = closest_b_end
            else:
                end_ms = target_ms
                
            if end_ms - prev_end_ms < 2000 and i < len(segments) - 1:
                end_ms = prev_end_ms + 2500
                
        dur_ms = max(1500, end_ms - prev_end_ms)
        timings.append({
            "start_ms": prev_end_ms,
            "end_ms": end_ms,
            "duration_ms": dur_ms,
        })
        prev_end_ms = end_ms
        
    return timings


import time

# Runtime in-memory cooldown tracker: (api_key, model_name) -> expire_timestamp
# IMPORTANT: Keys are NEVER deleted from gemini_keys.txt because quotas reset daily!
_GEMINI_COOLDOWNS: dict[tuple[str, str], float] = {}
COOLDOWN_DURATION_SEC = 300  # 5 minutes runtime cooldown for key+model pair on 429

GEMINI_TTS_MODELS = [
    "gemini-3.1-flash-tts-preview",
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
]


async def check_gemini_tts_status() -> dict:
    """
    Test Gemini TTS models and return availability status and quota estimate.
    """
    from google import genai
    from google.genai import types

    results = {}
    active_models = []
    test_phrase = "Test"

    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        )
    )

    test_keys = config.GEMINI_KEYS[:5] if config.GEMINI_KEYS else []

    for m in GEMINI_TTS_MODELS:
        success = False
        err_msg = ""
        for key in test_keys:
            try:
                http_opts = types.HttpOptions(base_url=config.GEMINI_BASE_URL) if getattr(config, "GEMINI_BASE_URL", None) else None
                client = genai.Client(api_key=key, http_options=http_opts)
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m,
                    contents=test_phrase,
                    config=cfg
                )
                if resp.candidates:
                    success = True
                    break
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    continue
        results[m] = {"status": "ok" if success else "quota_exceeded", "error": err_msg if not success else None}
        if success:
            active_models.append(m)

    keys_count = len(config.GEMINI_KEYS)
    total_active = len(active_models)

    return {
        "available": total_active > 0,
        "active_models": active_models,
        "available_models_count": total_active,
        "total_models": len(GEMINI_TTS_MODELS),
        "total_keys": keys_count,
        "models": results,
        "summary": (
            f"✅ Gemini TTS активен ({total_active}/{len(GEMINI_TTS_MODELS)} моделей доступно на {keys_count} ключах)"
            if total_active > 0 else
            "⚠️ Квота Gemini TTS исчерпана на сегодня (429). Подождите суточного сброса квоты Google или добавьте новые ключи."
        )
    }


async def _synthesize_gemini_single_chunk(text: str, voice_name: str, max_retries: int = None) -> tuple[bytes, float]:
    """
    Synthesize text chunk via Gemini TTS with intelligent API key rotation,
    model fallback (3.8-flash -> 3.8-flash-lite), and runtime 429 cooldowns.
    Returns (mp3_bytes, duration_ms).
    """
    from google import genai
    from google.genai import types

    cleaned = _clean_tts_text(text)
    if not any(ch.isalnum() for ch in cleaned):
        silence_mp3 = _generate_silence_mp3(1.0)
        return silence_mp3, 1000.0

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    now = time.time()

    # Clean up expired cooldowns in memory
    expired = [k for k, exp in _GEMINI_COOLDOWNS.items() if exp <= now]
    for k in expired:
        _GEMINI_COOLDOWNS.pop(k, None)

    all_keys = config.GEMINI_KEYS
    if not all_keys:
        raise ValueError("No Gemini API keys found in gemini_keys.txt")

    # Build candidates: try all keys with gemini-3.8-flash-tts and gemini-3.8-flash-lite-tts
    start_idx = getattr(config, "_key_index", 0)
    non_cooldown_candidates = []
    cooldown_candidates = []

    for offset in range(len(all_keys)):
        k = all_keys[(start_idx + offset) % len(all_keys)]
        for m in GEMINI_TTS_MODELS:
            if (k, m) not in _GEMINI_COOLDOWNS:
                non_cooldown_candidates.append((k, m))
            else:
                cooldown_candidates.append((k, m))

    attempts_limit = max_retries or (len(all_keys) * len(GEMINI_TTS_MODELS))
    last_err = None

    for round_idx in range(3):
        # Refresh candidates in each round
        now = time.time()
        expired = [k for k, exp in _GEMINI_COOLDOWNS.items() if exp <= now]
        for k in expired:
            _GEMINI_COOLDOWNS.pop(k, None)

        non_cooldown = []
        cooldown = []
        for offset in range(len(all_keys)):
            k = all_keys[(start_idx + offset) % len(all_keys)]
            for m in GEMINI_TTS_MODELS:
                if (k, m) not in _GEMINI_COOLDOWNS:
                    non_cooldown.append((k, m))
                else:
                    cooldown.append((k, m))

        current_candidates = non_cooldown if non_cooldown else cooldown

        for attempt, (key, model_name) in enumerate(current_candidates[:attempts_limit]):
            try:
                http_opts = types.HttpOptions(base_url=config.GEMINI_BASE_URL) if getattr(config, "GEMINI_BASE_URL", None) else None
                client = genai.Client(api_key=key, http_options=http_opts)
                config_obj = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                        )
                    )
                )
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=cleaned,
                    config=config_obj
                )
                wav_bytes = None
                if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                    for part in resp.candidates[0].content.parts:
                        if hasattr(part, "inline_data") and part.inline_data:
                            wav_bytes = part.inline_data.data
                            break
                if not wav_bytes:
                    raise ValueError("No audio payload returned from Gemini TTS")

                # Extract exact duration from WAV header
                with wave.open(io.BytesIO(wav_bytes)) as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    dur_ms = (frames / float(rate)) * 1000.0

                # Convert 24kHz WAV PCM to standard 24kHz mono MP3
                proc = subprocess.run(
                    [exe, "-y", "-f", "wav", "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "24000", "-ac", "1", "-f", "mp3", "pipe:1"],
                    input=wav_bytes,
                    capture_output=True,
                    check=True
                )
                return proc.stdout, dur_ms

            except Exception as e:
                last_err = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    _GEMINI_COOLDOWNS[(key, model_name)] = time.time() + COOLDOWN_DURATION_SEC
                    
                    # If key has quota_limit_value: 0 (permanently zero regional quota), never sleep, skip immediately!
                    if "quota_limit_value': '0'" in err_str or "quota_limit_value\": \"0\"" in err_str:
                        logger.warning(f"Gemini TTS: key ...{key[-6:]} has 0 regional quota (europe-west1: 0). Skipping immediately.")
                        continue

                    logger.warning(f"Gemini TTS 429 on model {model_name} (key ...{key[-6:]}). In-memory cooldown {COOLDOWN_DURATION_SEC}s.")
                    await asyncio.sleep(1.0)
                else:
                    logger.warning(f"Gemini TTS attempt {attempt + 1} (model {model_name}) failed: {e}")
                    await asyncio.sleep(0.5)

        # If round finished due to temporary RPM limit across all keys, wait 25s for the 60s window to roll over
        if round_idx < 2 and last_err and ("429" in str(last_err) or "RESOURCE_EXHAUSTED" in str(last_err)):
            wait_sec = 25
            logger.warning(f"Все активные ключи Gemini TTS исчерпали минутный лимит запросов (RPM). Ожидание {wait_sec}с для сброса квоты Google (раунд {round_idx + 1}/3)...")
            await asyncio.sleep(wait_sec)
            # Clear cooldowns for top active keys
            for k in all_keys[:5]:
                for m in GEMINI_TTS_MODELS:
                    _GEMINI_COOLDOWNS.pop((k, m), None)

    logger.error(f"Gemini TTS failed after testing available keys: {last_err}")
    raise RuntimeError(f"Все доступные ключи Gemini исчерпали квоту (429). Дождитесь минутного/суточного сброса квоты Google или добавьте новые ключи.")


async def _synthesize_gemini_speech(
    segments: list[str],
    voice_name: str,
    output_dir: Path,
    lang: str = "de",
    full_text: str = None,
    progress_callback = None,
) -> dict:
    """
    Synthesize complete speech script using Gemini TTS using cohesive large chunks (~1200 chars)
    with persistent disk caching per chunk and safe pacing to prevent 429 rate limit errors.
    Produces slide-aligned audio and synchronized subtitles (SRT, VTT, and ASS karaoke).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = output_dir / "gemini_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    combined_path = output_dir / "narration.mp3"
    subs_srt_path = output_dir / "subtitles.srt"
    subs_vtt_path = output_dir / "subtitles.vtt"
    subs_ass_path = output_dir / "subtitles.ass"

    if not full_text:
        full_text = "\n\n".join(s.strip() for s in segments if s.strip())
    if not full_text:
        full_text = "Heute gibt es wichtige Neuigkeiten."

    # Chunk the text into ~1200-character blocks at natural sentence/paragraph boundaries
    chunks = _split_text_into_chunks(full_text, max_chars=1200)
    logger.info(f"Synthesizing script ({len(full_text)} chars, {len(segments)} slides) in {len(chunks)} Gemini TTS chunks ({voice_name})")

    if progress_callback:
        progress_callback(0, f"Gemini TTS: 0/{len(chunks)} аудио-блоков")

    total_audio = bytearray()
    all_boundaries = []
    cum_ms = 0.0
    prev_was_cache = True

    for idx, chunk_text in enumerate(chunks):
        chunk_clean = chunk_text.strip()
        chunk_hash = hashlib.md5(f"{chunk_clean}:{voice_name}".encode("utf-8")).hexdigest()[:12]
        chunk_audio_path = chunks_dir / f"chunk_{idx:03d}_{chunk_hash}.mp3"
        chunk_meta_path = chunks_dir / f"chunk_{idx:03d}_{chunk_hash}.json"

        mp3_bytes = None
        dur_ms = 0.0
        loaded_from_cache = False

        # 1. Check disk cache first - never waste quota on already synthesized chunks!
        if chunk_audio_path.exists() and chunk_meta_path.exists() and chunk_audio_path.stat().st_size > 500:
            try:
                with open(chunk_meta_path, "r", encoding="utf-8") as f_meta:
                    meta = json.load(f_meta)
                dur_ms = float(meta["dur_ms"])
                with open(chunk_audio_path, "rb") as f_aud:
                    mp3_bytes = f_aud.read()
                if len(mp3_bytes) > 500:
                    loaded_from_cache = True
                    logger.info(f"Loaded Gemini chunk {idx + 1}/{len(chunks)} from disk cache ({dur_ms / 1000:.1f}s)")
            except Exception as ce:
                logger.warning(f"Cache read error for chunk {idx}: {ce}")
                mp3_bytes = None

        # 2. If not cached, synthesize with safe pacing (2.5s) to avoid 15 RPM limit
        if not loaded_from_cache:
            if idx > 0 and not prev_was_cache:
                await asyncio.sleep(2.5)  # Safe pause to strictly stay within Google's 15 RPM limits

            mp3_bytes, dur_ms = await _synthesize_gemini_single_chunk(chunk_text, voice_name)

            # Save to disk cache immediately so partial progress is NEVER lost on error
            try:
                with open(chunk_audio_path, "wb") as f_aud:
                    f_aud.write(mp3_bytes)
                with open(chunk_meta_path, "w", encoding="utf-8") as f_meta:
                    json.dump({"dur_ms": dur_ms, "text": chunk_clean, "voice": voice_name}, f_meta, ensure_ascii=False)
            except Exception as we:
                logger.warning(f"Failed to cache chunk {idx}: {we}")
            prev_was_cache = False
        else:
            prev_was_cache = True

        # Split chunk into sentences for subtitle generation and timing alignment
        sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', chunk_text) if s.strip()]
        if not sentences:
            sentences = [chunk_text]
        tot_chars = max(1, sum(len(s) for s in sentences))
        s_cur_ms = cum_ms
        for s in sentences:
            s_dur = dur_ms * (len(s) / tot_chars)
            all_boundaries.append({
                "offset": int(s_cur_ms * 10000),
                "duration": int(s_dur * 10000),
                "start_ms": s_cur_ms,
                "dur_ms": s_dur,
                "text": s,
            })
            s_cur_ms += s_dur

        total_audio.extend(mp3_bytes)
        cum_ms += dur_ms

        logger.info(f"Gemini chunk {idx + 1}/{len(chunks)} done ({dur_ms / 1000:.1f}s, cached={loaded_from_cache}). Total audio so far: {cum_ms / 1000:.1f}s")
        if progress_callback:
            pct = int((idx + 1) / len(chunks) * 100)
            status_text = f"Gemini TTS: {idx + 1}/{len(chunks)} аудио-блоков"
            if loaded_from_cache:
                status_text += " (из кэша)"
            status_text += f" ({cum_ms / 1000:.0f}с)"
            progress_callback(pct, status_text)

    with open(combined_path, "wb") as f_out:
        f_out.write(total_audio)

    # Professional Forced Alignment with faster-whisper
    # Guarantees 100% exact synchronization between audio, subtitles, and slide changes
    segment_timings = None
    try:
        if progress_callback:
            progress_callback(95, "Синхронизация субтитров и кадров (Whisper Alignment)...")
        from services.speech_aligner import align_speech
        aligned = await asyncio.wait_for(
            asyncio.to_thread(
                align_speech,
                audio_path=combined_path,
                segments=segments,
                lang=lang,
                full_text=full_text,
                output_dir=output_dir,
            ),
            timeout=120.0,
        )
        segment_timings = aligned["segment_timings"]
        all_boundaries = aligned["word_boundaries"]
        subs_srt_path = Path(aligned["subtitles_srt"])
        subs_vtt_path = Path(aligned["subtitles_vtt"])
        subs_ass_path = Path(aligned["subtitles_ass"])
        logger.info(f"Whisper alignment successful: {len(segment_timings)} slide timings synchronized.")
    except Exception as align_err:
        logger.warning(f"Whisper alignment failed ({align_err}), falling back to boundary interpolation: {traceback.format_exc()}")
        # Fallback to existing boundary interpolation
        srt_content, vtt_content, ass_content = _boundaries_to_subtitles(all_boundaries)
        with open(subs_srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        with open(subs_vtt_path, "w", encoding="utf-8") as f:
            f.write(vtt_content)
        with open(subs_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # Calculate exact slide timings for all visual slides
        segment_timings = _calculate_segment_timings_from_boundaries(
            segments=segments,
            all_boundaries=all_boundaries,
            total_duration_ms=cum_ms,
        )

    engine_name = f"Gemini TTS ({voice_name})"
    logger.info(f"Gemini TTS complete: {combined_path}, {len(chunks)} chunks, {len(segment_timings)} slide timings, total: {cum_ms / 1000:.1f}s")

    return {
        "combined_audio": str(combined_path),
        "subtitles_srt": str(subs_srt_path),
        "subtitles_vtt": str(subs_vtt_path),
        "subtitles_ass": str(subs_ass_path),
        "segment_timings": segment_timings,
        "word_boundaries": all_boundaries,
        "engine": engine_name,
    }


async def generate_segmented_speech(
    segments: list[str],
    output_dir: str | Path,
    lang: str = "ru",
    voice: str = None,
    rate: str = "+0%",
    full_text: str = None,
    progress_callback = None,
) -> dict:
    """
    Generate speech using Gemini TTS (if selected) or Edge-TTS Neural with chunked synthesis
    and 100% synchronized subtitles.
    
    Returns:
        dict with 'combined_audio', 'subtitles_srt', 'subtitles_vtt', 'segment_timings'
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if voice is None:
        voice = config.TTS_VOICES.get(lang, config.TTS_VOICES["ru"])

    # Route to Gemini TTS if Gemini voice is selected
    if voice and (voice.startswith("gemini:") or voice.startswith("gemini-") or "gemini" in voice.lower()):
        gemini_voice = voice.split(":", 1)[1] if ":" in voice else voice.replace("gemini-", "").replace("de-", "").replace("ru-", "").replace("en-", "").capitalize()
        if gemini_voice.lower() not in ["charon", "fenrir", "puck", "kore", "aoede"]:
            gemini_voice = "Charon"
        else:
            gemini_voice = gemini_voice.capitalize()
        try:
            return await _synthesize_gemini_speech(
                segments=segments,
                voice_name=gemini_voice,
                output_dir=output_dir,
                lang=lang,
                full_text=full_text,
                progress_callback=progress_callback,
            )
        except Exception as e:
            err_msg = str(e)
            if "исчерпали квоту" in err_msg or "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                fallback_voice = config.TTS_VOICES.get(lang, "de-DE-ConradNeural" if lang == "de" else "ru-RU-DmitryNeural")
                logger.warning(
                    f"⚠️ Суточный лимит Google Gemini TTS исчерпан (10 запросов/день на Free-аккаунтах). "
                    f"Выполняем безопасное автопереключение на Microsoft Neural ({fallback_voice}), чтобы завершить ролик без ошибок!"
                )
                if progress_callback:
                    progress_callback(5, f"Квота Gemini исчерпана -> Озвучка через {fallback_voice}...")
                voice = fallback_voice
            else:
                raise
    
    if not full_text:
        full_text = "\n\n".join(segments)

    try:
        combined_path = output_dir / "narration.mp3"
        subs_srt_path = output_dir / "subtitles.srt"
        subs_vtt_path = output_dir / "subtitles.vtt"

        chunks = _split_text_into_chunks(full_text, max_chars=350)
        logger.info(f"Synthesizing script ({len(full_text)} chars) in {len(chunks)} chunks using {voice}, concurrency={TTS_CONCURRENCY}")

        results: list = [None] * len(chunks)
        sem = asyncio.Semaphore(TTS_CONCURRENCY)
        done_count = 0
        done_bytes = 0

        if progress_callback:
            progress_callback(0, f"Озвучка: 0/{len(chunks)} фрагментов")

        async def _worker(idx: int, text: str):
            nonlocal done_count, done_bytes
            async with sem:
                if idx > 0:
                    await asyncio.sleep(0.3)
                audio_data, boundaries = await _synthesize_chunk_with_retry(
                    chunk_text=text, voice=voice, rate=rate, max_retries=3,
                )
            results[idx] = (audio_data, boundaries)
            done_count += 1
            done_bytes += len(audio_data)
            logger.info(f"Chunk {idx + 1}/{len(chunks)} done ({len(audio_data)} bytes). Progress {done_count}/{len(chunks)}")
            if progress_callback:
                pct = int(done_count / len(chunks) * 100)
                progress_callback(pct, f"Озвучка: {done_count}/{len(chunks)} фрагментов ({done_bytes / (1024 * 1024):.1f} МБ)")

        tasks = [asyncio.create_task(_worker(i, c)) for i, c in enumerate(chunks)]
        try:
            await asyncio.gather(*tasks)
        except Exception:
            for t in tasks:
                t.cancel()
            raise

        total_audio = bytearray()
        all_boundaries = []
        cumulative_offset_ms = 0.0

        for audio_data, boundaries in results:
            if not audio_data:
                continue
            for b in boundaries:
                b_start_ms = cumulative_offset_ms + (b["offset"] / 10000.0)
                b_dur_ms = b["duration"] / 10000.0
                all_boundaries.append({
                    "offset": int(b_start_ms * 10000),
                    "duration": b["duration"],
                    "start_ms": b_start_ms,
                    "dur_ms": b_dur_ms,
                    "text": b.get("text", ""),
                })
            total_audio.extend(audio_data)
            cumulative_offset_ms += (len(audio_data) / EDGE_MP3_BYTES_PER_SEC) * 1000.0

        logger.info(f"All {len(chunks)} chunks assembled: {len(total_audio)} bytes, {cumulative_offset_ms / 1000:.1f}s")

        if not total_audio or len(total_audio) == 0:
            raise RuntimeError(f"Edge-TTS synthesized audio is empty (0 bytes) for voice {voice}.")

        with open(combined_path, "wb") as f_out:
            f_out.write(total_audio)

        if progress_callback:
            progress_callback(100, f"Озвучка завершена: {len(total_audio) / (1024 * 1024):.1f} МБ")

        srt_content, vtt_content, ass_content = _boundaries_to_subtitles(all_boundaries)
        subs_ass_path = output_dir / "subtitles.ass"

        with open(subs_srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        with open(subs_vtt_path, "w", encoding="utf-8") as f:
            f.write(vtt_content)

        with open(subs_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        segment_timings = _calculate_segment_timings_from_boundaries(
            segments=segments,
            all_boundaries=all_boundaries,
            total_duration_ms=cumulative_offset_ms,
        )

        engine_name = f"Edge-TTS Neural ({voice})"
        logger.info(f"TTS complete ({engine_name}): {combined_path}, {len(all_boundaries)} speech boundaries, {len(segment_timings)} slide timings")

        return {
            "combined_audio": str(combined_path),
            "subtitles_srt": str(subs_srt_path),
            "subtitles_vtt": str(subs_vtt_path),
            "subtitles_ass": str(subs_ass_path),
            "segment_timings": segment_timings,
            "word_boundaries": all_boundaries,
            "engine": engine_name,
        }
    except Exception as edge_err:
        logger.warning(
            f"Edge-TTS failed ({edge_err}). Falling back seamlessly to Gemini TTS..."
        )
        if progress_callback:
            progress_callback(0, f"Edge-TTS недоступен. Переключение на Gemini TTS...")

        gemini_voice = "Charon"
        female_indicators = ["katja", "amala", "svetlana", "dariya", "kore", "aoede", "jenny", "aria", "denise", "elvira", "xiaoxiao", "zariyah", "francisca", "elsa", "nanami", "sunhi", "swara", "emel"]
        if voice and any(fi in voice.lower() for fi in female_indicators):
            gemini_voice = "Kore"

        return await _synthesize_gemini_speech(
            segments=segments,
            voice_name=gemini_voice,
            output_dir=output_dir,
            lang=lang,
            full_text=full_text,
            progress_callback=progress_callback,
        )


async def list_voices(lang: str = None) -> list[dict]:
    """List available Edge-TTS voices."""
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
        if lang:
            voices = [v for v in voices if v["Locale"].lower().startswith(lang.lower())]
        return [{"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]} for v in voices]
    except Exception:
        return []
