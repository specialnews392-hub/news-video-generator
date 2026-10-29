"""Local acceptance checks for full-length narrated news videos."""
import re
import math


MIN_NARRATION_SECONDS = 540  # 9 minutes minimum for 10-12 min long-form target


class ScriptQualityError(ValueError):
    """Content needs editorial work, not another API key."""


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+(?:[-’']\w+)*\b", text, re.UNICODE))


def word_targets(target_length=None):
    if not target_length or target_length >= 14000:
        # Standard long-form (10-12 minutes target @ ~140 wpm): target ~1800 words, min ~1350 words (~9.6-10 min)
        target = 1800
        min_words = 1350
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
        min_seconds = max(240, int(target_length * 0.04))
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
