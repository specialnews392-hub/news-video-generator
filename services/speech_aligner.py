"""
Speech Aligner - High-precision word and sentence alignment using faster-whisper.
Aligns Gemini TTS audio with script segments to ensure 100% exact synchronization
between speech, visual slides, and karaoke subtitles.
Strictly 1-line, stable, non-jumping subtitles with zero start delay.
"""
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import imageio_ffmpeg

logger = logging.getLogger(__name__)

_whisper_model = None


def get_whisper_model(model_size: str = "base"):
    """Lazy-loaded cached WhisperModel singleton."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info(f"Loading faster-whisper model ({model_size}) for speech alignment...")
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("faster-whisper model loaded successfully.")
    return _whisper_model


def _load_audio_16k(audio_path: str | Path) -> np.ndarray:
    """
    Decode any audio file to 16kHz mono float32 numpy array using FFmpeg.
    Bypasses PyAV version inconsistencies and guarantees rock-solid audio loading.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-nostdin", "-threads", "0", "-i", str(audio_path),
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", "16000", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, check=True)
    if not res.stdout:
        raise ValueError(f"Decoded audio stream is empty for {audio_path}")
    return np.frombuffer(res.stdout, np.int16).flatten().astype(np.float32) / 32768.0


def _normalize_word(w: str) -> str:
    """Normalize word for robust matching (lowercase, no punctuation)."""
    return re.sub(r'[^\w]', '', w.lower())


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


def _generate_subtitles_from_words(
    words: list[dict],
    max_phrase_chars: int = 24,
    max_phrase_words: int = 4,
) -> tuple[str, str, str]:
    """
    Generate strictly 1-line, non-jumping SRT, VTT, and ASS karaoke subtitles.
    WrapStyle: 2 and compact phrases (2-4 words, ~22 chars) guarantee text never wraps
    or twitches between 1 and 2 lines.
    """
    if not words:
        return "", "", ""

    # Group words into natural, compact 1-line subtitle phrases
    phrases = []
    current_phrase = []
    current_chars = 0

    for idx, w in enumerate(words):
        w_text = w["word"].strip()
        if not w_text:
            continue

        w_len = len(w_text)
        prev_word = current_phrase[-1] if current_phrase else None

        # Check for natural break conditions
        is_break = False
        if prev_word:
            prev_text = prev_word["word"].strip()
            # 1. Punctuation break (sentence or strong clause boundary)
            if any(prev_text.endswith(p) for p in [".", "!", "?", "…"]):
                is_break = True
            # 2. Spoken pause break (silence > 450ms)
            elif w["start_ms"] - prev_word["end_ms"] > 450.0:
                is_break = True
            # 3. Strict 1-line cap: max 24 chars or max 4 words
            elif current_chars + 1 + w_len > max_phrase_chars or len(current_phrase) >= max_phrase_words:
                is_break = True

        if is_break and current_phrase:
            phrases.append(current_phrase)
            current_phrase = [w]
            current_chars = w_len
        else:
            current_phrase.append(w)
            current_chars += (w_len + 1) if len(current_phrase) > 1 else w_len

    if current_phrase:
        phrases.append(current_phrase)

    srt_lines = []
    vtt_lines = ["WEBVTT\n"]
    counter = 1

    # ASS Header with WrapStyle: 2 (no word wrap) to strictly enforce 1 single line
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: NewsKaraoke,Arial,40,&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.2,1.2,2,100,100,65,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_events = []

    for p in phrases:
        if not p:
            continue
        p_start_ms = p[0]["start_ms"]
        p_end_ms = p[-1]["end_ms"]
        extended_end_ms = p_end_ms + 250.0  # gentle tail to prevent blinking
        phrase_text = " ".join(w["word"] for w in p)

        # SRT & VTT
        start_str = _ms_to_srt_time(p_start_ms)
        end_str = _ms_to_srt_time(extended_end_ms)

        srt_lines.append(str(counter))
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(phrase_text)
        srt_lines.append("")

        vtt_start = start_str.replace(",", ".")
        vtt_end = end_str.replace(",", ".")
        vtt_lines.append(f"{vtt_start} --> {vtt_end}")
        vtt_lines.append(phrase_text)
        vtt_lines.append("")
        counter += 1

        # Continuous ASS Karaoke timeline without inter-word disappearing gaps
        for i, target_word_info in enumerate(p):
            w_start = target_word_info["start_ms"]
            # First word starts at phrase start
            if i == 0 and p_start_ms < w_start:
                w_start = p_start_ms

            # Active highlight ends exactly when the next word starts (no gaps!)
            if i < len(p) - 1:
                w_end = p[i + 1]["start_ms"]
            else:
                w_end = extended_end_ms

            if w_end <= w_start:
                w_end = w_start + 180.0

            formatted_parts = []
            for j, w_info in enumerate(p):
                if j == i:
                    formatted_parts.append(f"{{\\c&H0000D7FF&}}{w_info['word']}{{\\c&H00FFFFFF&}}")
                else:
                    formatted_parts.append(w_info["word"])

            ass_line = " ".join(formatted_parts)
            ass_events.append(
                f"Dialogue: 0,{_ms_to_ass_time(w_start)},{_ms_to_ass_time(w_end)},NewsKaraoke,,0,0,0,,{ass_line}"
            )

    ass_content = ass_header + "\n".join(ass_events)
    return "\n".join(srt_lines), "\n".join(vtt_lines), ass_content


def _align_slide_timings(
    segments: list[str],
    words: list[dict],
    total_duration_ms: float,
) -> list[dict]:
    """
    Calculate slide changeover timings by aligning slide text to recognized words.
    Guarantees strict monotonicity and eliminates slide drift.
    """
    if not segments:
        return []

    if not words:
        # Fallback to even character distribution if no words recognized
        tot_chars = max(1, sum(len(s) for s in segments))
        cur = 0.0
        timings = []
        for s in segments:
            dur = total_duration_ms * (len(s) / tot_chars)
            timings.append({
                "start_ms": float(cur),
                "end_ms": float(cur + dur),
                "duration_ms": float(max(1000.0, dur)),
            })
            cur += dur
        return timings

    slide_timings = []
    w_idx = 0
    prev_end_ms = 0.0

    for i, slide in enumerate(segments):
        slide_tokens = [_normalize_word(x) for x in slide.split() if _normalize_word(x)]
        count = len(slide_tokens)

        if i == len(segments) - 1:
            end_ms = max(total_duration_ms, prev_end_ms + 1000.0)
        else:
            target_token = slide_tokens[-1] if slide_tokens else ""
            target_idx = min(len(words) - 1, w_idx + max(1, count) - 1)

            # Search a window around target_idx for matching token
            best_idx = target_idx
            min_dist = 999
            for cand in range(max(0, target_idx - 4), min(len(words), target_idx + 5)):
                if _normalize_word(words[cand]["word"]) == target_token:
                    if abs(cand - target_idx) < min_dist:
                        min_dist = abs(cand - target_idx)
                        best_idx = cand

            # Transition point: when the NEXT slide's speech begins, or when this slide's last word ends
            if best_idx < len(words) - 1:
                end_ms = words[best_idx + 1]["start_ms"]
            else:
                end_ms = words[best_idx]["end_ms"]

            w_idx = best_idx + 1

        # Safety checks: ensure slide stays on screen at least 1.5s and is strictly increasing
        if end_ms <= prev_end_ms + 1000.0:
            end_ms = prev_end_ms + 1500.0

        dur_ms = float(end_ms - prev_end_ms)
        slide_timings.append({
            "start_ms": float(prev_end_ms),
            "end_ms": float(end_ms),
            "duration_ms": dur_ms,
        })
        prev_end_ms = float(end_ms)

    return slide_timings


def align_speech(
    audio_path: str | Path,
    segments: list[str],
    lang: str = "ru",
    full_text: str = None,
    output_dir: Optional[Path] = None,
) -> dict:
    """
    Main entry point: Align speech audio with text segments.
    Returns synchronized slide timings, word boundaries, and subtitles.
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir) if output_dir else audio_path.parent

    # 1. Load audio
    audio_np = _load_audio_16k(audio_path)
    audio_dur_ms = (len(audio_np) / 16000.0) * 1000.0

    # 2. Transcribe with word timestamps
    # CRITICAL: Do NOT use initial_prompt! Passing initial_prompt causes Whisper
    # to think the first 20-30 seconds were already spoken, skipping the beginning of subtitles!
    model = get_whisper_model("base")
    whisper_lang = lang[:2].lower() if lang else "ru"

    whisper_segments, info = model.transcribe(
        audio_np,
        language=whisper_lang,
        word_timestamps=True,
        vad_filter=False,  # Audio from TTS is clean; vad_filter=False ensures 0.0s start is never cut
    )

    all_words = []
    all_boundaries = []
    for seg in whisper_segments:
        all_boundaries.append({
            "start_ms": seg.start * 1000.0,
            "dur_ms": (seg.end - seg.start) * 1000.0,
            "text": seg.text.strip(),
        })
        for w in (seg.words or []):
            clean = w.word.strip()
            if clean:
                all_words.append({
                    "word": clean,
                    "start_ms": w.start * 1000.0,
                    "end_ms": w.end * 1000.0,
                    "prob": getattr(w, "probability", 1.0),
                })

    first_word_time = f"{all_words[0]['start_ms'] / 1000:.2f}s" if all_words else "None"
    logger.info(f"Speech alignment complete: {len(all_words)} words (first at {first_word_time}), {len(all_boundaries)} speech segments ({audio_dur_ms / 1000:.1f}s)")

    # 3. Generate exact 1-line subtitles
    srt_content, vtt_content, ass_content = _generate_subtitles_from_words(all_words)

    subs_srt_path = output_dir / "subtitles.srt"
    subs_vtt_path = output_dir / "subtitles.vtt"
    subs_ass_path = output_dir / "subtitles.ass"

    with open(subs_srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    with open(subs_vtt_path, "w", encoding="utf-8") as f:
        f.write(vtt_content)
    with open(subs_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    # 4. Generate exact slide timings
    segment_timings = _align_slide_timings(
        segments=segments,
        words=all_words,
        total_duration_ms=audio_dur_ms,
    )

    return {
        "segment_timings": segment_timings,
        "word_boundaries": all_boundaries,
        "subtitles_srt": str(subs_srt_path),
        "subtitles_vtt": str(subs_vtt_path),
        "subtitles_ass": str(subs_ass_path),
        "total_duration_ms": audio_dur_ms,
    }
