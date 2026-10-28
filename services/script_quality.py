"""Local acceptance checks for full-length narrated news videos."""
import re
import math


MIN_NARRATION_SECONDS = 600


class ScriptQualityError(ValueError):
    """Content needs editorial work, not another API key."""


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+(?:[-’']\w+)*\b", text, re.UNICODE))


def word_targets(target_length=None):
    # Legacy UI sends characters. Never let that lower the long-form minimum.
    target = max(2000, int((target_length or 0) / 8))
    return max(1800, int(target * 0.9)), target


def validate_narration_duration(seconds: float, is_preview=False):
    if is_preview:
        return
    if not math.isfinite(seconds) or seconds < MIN_NARRATION_SECONDS:
        raise ScriptQualityError(
            f"Озвучка длится {seconds or 0:.0f} сек., минимум — "
            f"{MIN_NARRATION_SECONDS} сек. Сценарий необходимо дополнить "
            "подтверждёнными фактами и повторно озвучить. Короткий выпуск не принят."
        )


def measure_narration_duration(path):
    from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos
    info = ffmpeg_parse_infos(str(path))
    if not info.get("audio_found"):
        raise ScriptQualityError("В файле озвучки не найдена аудиодорожка.")
    return float(info["duration"])
