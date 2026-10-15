import cv2
import numpy as np
import imageio_ffmpeg
import subprocess

# Create test 1920x1080 frame
frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
frame[:] = (30, 30, 30)
cv2.imwrite("test_karaoke_frame.jpg", frame)

# Create ASS file with word highlighting
ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: NewsSub,Arial,44,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.5,1.5,2,40,40,55,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Test sentence with 5 words
# Highlight each word in yellow (&H00FFFF&)
words = ["Валдайский", "удар", "изменил", "всю", "геополитику"]
dur_per_word = 0.6
events = []
for i, active_word in enumerate(words):
    start = f"0:00:{i*dur_per_word:05.2f}"
    end = f"0:00:{(i+1)*dur_per_word:05.2f}"
    line_parts = []
    for j, w in enumerate(words):
        if j == i:
            line_parts.append(f"{{\\c&H00FFFF&}}{w}{{\\c&HFFFFFF&}}")
        else:
            line_parts.append(w)
    text = " ".join(line_parts)
    events.append(f"Dialogue: 0,{start},{end},NewsSub,,0,0,0,,{text}")

with open("test_karaoke.ass", "w", encoding="utf-8") as f:
    f.write(ass_header + "\n".join(events))

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
cmd = [
    ffmpeg_exe, "-y", "-i", "test_karaoke_frame.jpg",
    "-vf", "ass=test_karaoke.ass",
    "test_karaoke_out.jpg"
]
res = subprocess.run(cmd, capture_output=True, text=True)
print("FFmpeg return code:", res.returncode)
if res.returncode == 0:
    print("SUCCESS! Rendered test_karaoke_out.jpg")
else:
    print("FFmpeg error:", res.stderr[-300:])
