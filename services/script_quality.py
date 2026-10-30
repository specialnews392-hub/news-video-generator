"""Local acceptance checks for full-length narrated news videos."""
import re
import math


MIN_NARRATION_SECONDS = 450  # 7.5 minutes minimum for long-form target (~8-12 min range)


class ScriptQualityError(ValueError):
    """Content needs editorial work, not another API key."""


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+(?:[-’']\w+)*\b", text, re.UNICODE))


def word_targets(target_length=None):
    if not target_length or target_length >= 14000:
        # Standard long-form (~8-12 minutes target @ ~140 wpm): target ~1600 words, min ~1100 words (~7.8-11 min)
        target = 1600
        min_words = 1100
    else:
        # User specified custom shorter target length on slider
        target = max(800, int(target_length / 7.6))
        min_words = max(600, int(target * 0.75))
    return min_words, target


def validate_narration_duration(seconds: float, is_preview=False, target_length=None):
    if is_preview:
        return
    min_seconds = MIN_NARRATION_SECONDS
    if target_length and target_length < 12000:
        min_seconds = max(240, int(target_length * 0.035))
    if not math.isfinite(seconds) or seconds < min_seconds:
        raise ScriptQualityError(
            f"Озвучка длится {seconds or 0:.0f} сек., минимум — "
            f"{min_seconds} сек. Сценарий необходимо дополнить "
            "подтверждёнными фактами и повторно озвучить. Короткий выпуск не принят."
        )


def measure_narration_duration(path):
    from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos
    info = ffmpeg_parse_infos(str(path))
    if not info.get("audio_found"):
        raise ScriptQualityError("В файле озвучки не найдена аудиодорожка.")
    return float(info["duration"])
