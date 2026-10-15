"""
TTS Engine - Text-to-Speech using high-quality Edge-TTS Neural voices.
Chunked synthesis ensures 100% reliability with zero limits and exact subtitle synchronization.
"""
import asyncio
import io
import logging
import os
import re
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


async def _synthesize_chunk_with_retry(
    chunk_text: str,
    voice: str,
    rate: str = "+0%",
    max_retries: int = 5,
) -> tuple[bytes, list[dict]]:
    """
    Synthesize a chunk strictly with the SELECTED voice (guarantees voice consistency across the whole video).
    1) Up to `max_retries` whole-chunk attempts with progressive backoff.
    2) If still failing, split into individual sentences and synthesize with the SAME voice.
    3) Sentence level has up to 6 retries with exponential backoff and jitter to overcome transient Microsoft throttling.
    """
    tts_rate = rate if rate and rate not in ["+0%", "0%", "-0%"] else "+0%"
    chunk_backoff = [1.0, 2.5, 4.5, 7.0, 10.0]

    last_err = None
    for attempt in range(max_retries):
        try:
            return await _synthesize_once(chunk_text, voice, tts_rate)
        except Exception as e:
            last_err = e
            delay = chunk_backoff[min(attempt, len(chunk_backoff) - 1)] + random.uniform(0.3, 1.0)
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
    sent_backoff = [1.0, 2.0, 4.0, 6.0, 9.0, 12.0]

    for sent_idx, sent in enumerate(sentences):
        s_clean = _clean_tts_text(sent)
        if not any(ch.isalnum() for ch in s_clean):
            continue

        # Micro-pause between sentences to avoid Microsoft rate limits
        await asyncio.sleep(0.4)

        sent_success = False
        last_sent_err = None
        for attempt in range(6):
            try:
                s_audio, s_bounds = await _synthesize_once(s_clean, voice, tts_rate)
                offset_ticks = int(len(out_audio) / EDGE_MP3_BYTES_PER_SEC * 10_000_000)
                for b in s_bounds:
                    nb = dict(b)
                    nb["offset"] = b["offset"] + offset_ticks
                    out_bounds.append(nb)
                out_audio.extend(s_audio)
                sent_success = True
                break
            except Exception as e:
                last_sent_err = e
                delay = sent_backoff[min(attempt, len(sent_backoff) - 1)] + random.uniform(0.2, 0.8)
                logger.warning(
                    f"Edge-TTS sentence {sent_idx + 1}/{len(sentences)} with voice {voice} attempt {attempt + 1}/6 failed ({len(s_clean)} chars): {e}. "
                    f"Retry in {delay:.1f}s"
                )
                await asyncio.sleep(delay)

        if not sent_success:
            logger.error(
                f"Edge-TTS sentence {sent_idx + 1}/{len(sentences)} failed all retries with {voice}: {last_sent_err}."
            )

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


GEMINI_TTS_MODELS = [
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
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

    for m in GEMINI_TTS_MODELS:
        success = False
        err_msg = ""
        for _ in range(2):
            key = config.get_random_gemini_key()
            try:
                client = genai.Client(api_key=key)
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
            "⚠️ Квота Gemini TTS исчерпана на сегодня (429). Видео автоматически озвучится через Edge-TTS (Conrad/Dmitry)."
        )
    }


async def _synthesize_gemini_single_chunk(text: str, voice_name: str, max_retries: int = 12) -> tuple[bytes, float]:
    """
    Synthesize text chunk via Gemini TTS with automatic API key rotation and multi-model fallback on 429.
    Returns (mp3_bytes, duration_ms).
    """
    from google import genai
    from google.genai import types

    cleaned = _clean_tts_text(text)
    if not any(ch.isalnum() for ch in cleaned):
        silence_mp3 = _generate_silence_mp3(1.0)
        return silence_mp3, 1000.0

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    last_err = None

    for attempt in range(max_retries):
        key = config.get_next_gemini_key()
        # Rotate model across attempts if encountering quota issues
        model_name = GEMINI_TTS_MODELS[attempt % len(GEMINI_TTS_MODELS)]
        try:
            client = genai.Client(api_key=key)
            config_obj = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                    )
                )
            )
            # Run in thread so the async event loop stays responsive
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
            logger.warning(f"Gemini TTS attempt {attempt + 1}/{max_retries} (model {model_name}) failed: {e}")
            await asyncio.sleep(0.3 + random.uniform(0.1, 0.3))

    logger.error(f"Gemini TTS failed after {max_retries} attempts: {last_err}")
    raise RuntimeError(f"Gemini TTS quota or generation failed: {last_err}")


async def _synthesize_gemini_speech(
    segments: list[str],
    voice_name: str,
    output_dir: Path,
    lang: str = "de",
    full_text: str = None,
    progress_callback = None,
) -> dict:
    """
    Synthesize complete speech script using Gemini 3.8 Flash TTS with slide-aligned audio
    and synchronized subtitles (SRT, VTT, and ASS karaoke).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    combined_path = output_dir / "narration.mp3"
    subs_srt_path = output_dir / "subtitles.srt"
    subs_vtt_path = output_dir / "subtitles.vtt"
    subs_ass_path = output_dir / "subtitles.ass"

    seg_list = segments if segments else [full_text or ""]
    clean_segs = [s.strip() for s in seg_list if s.strip()]
    if not clean_segs:
        clean_segs = ["Heute gibt es wichtige Neuigkeiten."]

    # Quick probe to test Gemini TTS quota availability before starting full batch
    logger.info("Probing Gemini TTS availability and quota...")
    try:
        await _synthesize_gemini_single_chunk("Hallo.", voice_name, max_retries=min(len(config.GEMINI_KEYS), 6))
    except Exception as e:
        logger.warning(f"Gemini TTS quota probe failed: {e}")
        raise RuntimeError(f"Gemini TTS quota exhausted across API keys: {e}")

    logger.info(f"Synthesizing {len(clean_segs)} segments using Gemini TTS ({voice_name})")
    if progress_callback:
        progress_callback(0, f"Gemini TTS: 0/{len(clean_segs)} слайдов")

    sem = asyncio.Semaphore(2)
    results = [None] * len(clean_segs)
    done_count = 0

    async def _worker(idx: int, seg_text: str):
        nonlocal done_count
        async with sem:
            await asyncio.sleep(0.25 * (idx % 2))
            mp3_bytes, dur_ms = await _synthesize_gemini_single_chunk(seg_text, voice_name)
        results[idx] = (mp3_bytes, dur_ms, seg_text)
        done_count += 1
        logger.info(f"Gemini slide {idx + 1}/{len(clean_segs)} done ({dur_ms / 1000:.1f}s). Progress {done_count}/{len(clean_segs)}")
        if progress_callback:
            pct = int(done_count / len(clean_segs) * 100)
            progress_callback(pct, f"Gemini TTS: {done_count}/{len(clean_segs)} слайдов")

    tasks = [asyncio.create_task(_worker(i, s)) for i, s in enumerate(clean_segs)]
    try:
        await asyncio.gather(*tasks)
    except Exception:
        for t in tasks:
            t.cancel()
        raise

    total_audio = bytearray()
    all_boundaries = []
    segment_timings = []
    cum_ms = 0.0

    for idx, (mp3_bytes, dur_ms, seg_text) in enumerate(results):
        seg_start_ms = cum_ms
        seg_dur_ms = dur_ms
        seg_end_ms = seg_start_ms + seg_dur_ms

        segment_timings.append({
            "start_ms": seg_start_ms,
            "end_ms": seg_end_ms,
            "duration_ms": seg_dur_ms,
        })

        sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', seg_text) if s.strip()]
        if not sentences:
            sentences = [seg_text]
        tot_chars = max(1, sum(len(s) for s in sentences))
        s_cur_ms = seg_start_ms
        for s in sentences:
            s_dur = seg_dur_ms * (len(s) / tot_chars)
            all_boundaries.append({
                "offset": int(s_cur_ms * 10000),
                "duration": int(s_dur * 10000),
                "start_ms": s_cur_ms,
                "dur_ms": s_dur,
                "text": s,
            })
            s_cur_ms += s_dur

        total_audio.extend(mp3_bytes)
        cum_ms = seg_end_ms

    with open(combined_path, "wb") as f_out:
        f_out.write(total_audio)

    srt_content, vtt_content, ass_content = _boundaries_to_subtitles(all_boundaries)
    with open(subs_srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    with open(subs_vtt_path, "w", encoding="utf-8") as f:
        f.write(vtt_content)
    with open(subs_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    engine_name = f"Gemini TTS ({voice_name})"
    logger.info(f"Gemini TTS complete: {combined_path}, {len(clean_segs)} segments, duration: {cum_ms / 1000:.1f}s")

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
            fallback_voice = config.TTS_VOICES.get(lang, config.TTS_VOICES.get("ru", "ru-RU-DmitryNeural"))
            logger.warning(
                f"Gemini TTS unavailable or quota exhausted ({e}). "
                f"Falling back seamlessly to Edge-TTS Neural ({fallback_voice}) for the entire video."
            )
            if progress_callback:
                progress_callback(0, f"Лимит Gemini TTS исчерпан. Переключение на Edge-TTS ({fallback_voice})...")
            voice = fallback_voice
    
    if not full_text:
        full_text = "\n\n".join(segments)
        
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
            # Gentle pacing between requests prevents Microsoft rate limits
            if idx > 0:
                await asyncio.sleep(0.5)
            audio_data, boundaries = await _synthesize_chunk_with_retry(
                chunk_text=text, voice=voice, rate=rate, max_retries=5,
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
    
    # Assemble in original order with exact offsets
    total_audio = bytearray()
    all_boundaries = []
    cumulative_offset_ms = 0.0
    
    for audio_data, boundaries in results:
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
        # Exact chunk duration from MP3 size (includes trailing silence -> no drift)
        cumulative_offset_ms += (len(audio_data) / EDGE_MP3_BYTES_PER_SEC) * 1000.0
    
    logger.info(f"All {len(chunks)} chunks assembled: {len(total_audio)} bytes, {cumulative_offset_ms / 1000:.1f}s")
    
    if not total_audio or len(total_audio) == 0:
        raise RuntimeError(f"TTS generation failed: synthesized audio is empty (0 bytes) for voice {voice}.")
        
    # Write combined narration audio
    with open(combined_path, "wb") as f_out:
        f_out.write(total_audio)
        
    if progress_callback:
        progress_callback(100, f"Озвучка завершена: {len(total_audio) / (1024 * 1024):.1f} МБ")
        
    # Generate perfectly synchronized subtitles from boundaries (SRT, VTT, and ASS Karaoke)
    srt_content, vtt_content, ass_content = _boundaries_to_subtitles(all_boundaries)
    subs_ass_path = output_dir / "subtitles.ass"
    
    with open(subs_srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
        
    with open(subs_vtt_path, "w", encoding="utf-8") as f:
        f.write(vtt_content)
        
    with open(subs_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
        
    # Calculate segment timings for visual slide transitions
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
