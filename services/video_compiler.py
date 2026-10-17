"""
Video Compiler - Assembles slideshow video from images with audio and subtitles.
Uses MoviePy + FFmpeg. Optimized for speed.
"""
import asyncio
import logging
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw
import numpy as np

import config

logger = logging.getLogger(__name__)

# Progress callback - set by main.py
_progress_callback = None

def set_progress_callback(callback):
    global _progress_callback
    _progress_callback = callback

def _report_progress(msg):
    if _progress_callback:
        _progress_callback(msg)
    logger.info(msg)


def _prepare_image(image_path: str, width: int = 1920, height: int = 1080) -> str:
    """Resize/crop to exact dimensions."""
    try:
        img = Image.open(image_path).convert("RGB")
        img_ratio = img.width / img.height
        target_ratio = width / height
        
        if img_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))
        
        img = img.resize((width, height), Image.LANCZOS)
        prepared_path = str(Path(image_path).with_suffix('')) + "_prepared.jpg"
        img.save(prepared_path, quality=90)
        return prepared_path
    except Exception as e:
        logger.error(f"Failed to prepare image {image_path}: {e}")
        raise e


def _create_placeholder(base_path: str, width: int = 1920, height: int = 1080) -> str:
    """Create a stylized TV news studio background with subtle texture (used only if 0 photos exist)."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    # Elegant deep blue-indigo gradient
    for y in range(height):
        r = int(14 + (y / height) * 22)
        g = int(20 + (y / height) * 28)
        b = int(45 + (y / height) * 45)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    # Subtle digital news grid accents
    for x in range(0, width, 120):
        draw.line([(x, 0), (x, height)], fill=(25, 38, 70), width=1)
    for y in range(0, height, 120):
        draw.line([(0, y), (width, y)], fill=(25, 38, 70), width=1)
    
    placeholder_path = str(Path(base_path).parent / f"placeholder_{Path(base_path).stem}.jpg")
    img.save(placeholder_path, quality=90)
    return placeholder_path


async def compile_video(
    image_paths: list[str],
    audio_path: str,
    output_path: str | Path,
    segment_timings: list[dict] = None,
    subtitles_path: str = None,
    fps: int = None,
    ken_burns: bool = False,
    transitions: bool = True,
) -> str:
    """Compile video using FFmpeg directly (much faster than MoviePy)."""
    if fps is None:
        fps = config.VIDEO_FPS
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    result = await asyncio.to_thread(
        _compile_video_ffmpeg,
        image_paths, audio_path, str(output_path),
        segment_timings, subtitles_path, fps, ken_burns, transitions,
    )
    return result


def _generate_crossfade_frames(img1_path: str, img2_path: str, out_dir: Path, idx: int, num_frames: int = 6) -> list[tuple[str, float]]:
    """Generate intermediate crossfade frames between two images using Pillow (or OpenCV if available)."""
    trans_duration = 0.48
    frame_dur = trans_duration / num_frames

    # 1. Try OpenCV if available
    try:
        import cv2
        im1 = cv2.imread(str(img1_path))
        im2 = cv2.imread(str(img2_path))
        if im1 is not None and im2 is not None:
            if im1.shape != im2.shape:
                im2 = cv2.resize(im2, (im1.shape[1], im1.shape[0]))
            frames = []
            for f in range(num_frames):
                alpha = (f + 1) / (num_frames + 1.0)
                blend = cv2.addWeighted(im1, 1.0 - alpha, im2, alpha, 0)
                out_file = out_dir / f"trans_{idx:03d}_{f}.jpg"
                cv2.imwrite(str(out_file), blend, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frames.append((str(out_file), frame_dur))
            if frames:
                return frames
    except Exception:
        pass

    # 2. Rock-solid Pillow fallback (guaranteed in requirements.txt, works in headless Linux & Codespaces)
    try:
        from PIL import Image
        with Image.open(str(img1_path)) as i1, Image.open(str(img2_path)) as i2:
            im1 = i1.convert("RGB")
            im2 = i2.convert("RGB")
            if im1.size != im2.size:
                im2 = im2.resize(im1.size, Image.BILINEAR)
            frames = []
            for f in range(num_frames):
                alpha = (f + 1) / (num_frames + 1.0)
                blend = Image.blend(im1, im2, alpha)
                out_file = out_dir / f"trans_{idx:03d}_{f}.jpg"
                blend.save(str(out_file), quality=85)
                frames.append((str(out_file), frame_dur))
            return frames
    except Exception as e:
        logger.warning(f"Failed to generate crossfade {idx}: {e}")
        return []


def _detect_best_encoder(ffmpeg_path: str) -> tuple[str, list[str]]:
    """Auto-detect the fastest available H.264 encoder.
    Returns (encoder_name, extra_flags).
    Priority: h264_nvenc (NVIDIA GPU) > h264_qsv (Intel) > libx264 (CPU).
    """
    # Try NVENC (NVIDIA MX450 / GTX / RTX)
    try:
        test_cmd = [
            ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
            "-c:v", "h264_nvenc", "-preset", "p4", "-f", "null", "-",
        ]
        r = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            logger.info("✅ NVENC encoder available (NVIDIA GPU)")
            return "h264_nvenc", ["-preset", "p4", "-rc", "vbr", "-cq", "26"]
    except Exception:
        pass

    # Try QSV (Intel Iris Xe)
    try:
        test_cmd = [
            ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
            "-c:v", "h264_qsv", "-preset", "veryfast", "-f", "null", "-",
        ]
        r = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            logger.info("✅ QSV encoder available (Intel GPU)")
            return "h264_qsv", ["-preset", "veryfast"]
    except Exception:
        pass

    # Fallback: libx264 with stillimage tuning (ideal for slideshows)
    logger.info("Using libx264 CPU encoder with -tune stillimage")
    return "libx264", ["-preset", "veryfast", "-tune", "stillimage"]


# Cache encoder detection across calls
_cached_encoder: tuple[str, list[str]] | None = None


def _render_transition_blend(
    ffmpeg_path: str,
    clip_a: str,
    clip_b: str,
    out_trans_path: str,
    dur_a: float,
    trans_sec: float = 0.5,
) -> bool:
    """Render a buttery-smooth crossfade between clip_a tail and clip_b head using FFmpeg native blend."""
    try:
        start_t = max(dur_a - trans_sec, 0.0)
        fc = (
            f"[0:v]trim=start={start_t:.3f}:end={dur_a:.3f},setpts=PTS-STARTPTS[v0]; "
            f"[1:v]trim=start=0:end={trans_sec:.3f},setpts=PTS-STARTPTS[v1]; "
            f"[v0][v1]blend=all_expr='A*(1-T/{trans_sec:.3f})+B*(T/{trans_sec:.3f})'[vout]"
        )
        cmd = [
            ffmpeg_path, "-y",
            "-i", str(clip_a), "-i", str(clip_b),
            "-filter_complex", fc,
            "-map", "[vout]",
            "-t", f"{trans_sec:.3f}",
            "-c:v", "libx264",
            "-g", "1",
            "-preset", "ultrafast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(out_trans_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return proc.returncode == 0 and os.path.exists(out_trans_path)
    except Exception as e:
        logger.warning(f"Transition blend failed: {e}")
        return False


def _generate_ken_burns_clip(
    ffmpeg_path: str,
    img_path: str,
    out_clip_path: str,
    duration: float,
    idx: int,
    fps: int = 24,
) -> bool:
    """Generate a single clip with silky-smooth Ken Burns camera pan/zoom motion.
    Every pattern starts at zoom 1.000 (full frame) to eliminate any initial jump or twitching.
    Works reliably with or without OpenCV (falls back to Pillow or native image).
    """
    in_file = str(img_path)
    up_created = False
    try:
        # Graceful high-res upscale: eliminates zoompan integer coordinate jitter
        # Try cv2 first, then Pillow, then fallback to original in_file without failing
        try:
            import cv2
            im = cv2.imread(str(img_path))
            if im is not None:
                up_path = str(Path(out_clip_path).with_suffix('')) + f"_up_{idx}.jpg"
                up = cv2.resize(im, (4800, 2700), interpolation=cv2.INTER_LINEAR)
                cv2.imwrite(up_path, up, [cv2.IMWRITE_JPEG_QUALITY, 85])
                in_file = up_path
                up_created = True
        except Exception:
            try:
                from PIL import Image
                with Image.open(str(img_path)) as im:
                    up_path = str(Path(out_clip_path).with_suffix('')) + f"_up_{idx}.jpg"
                    up = im.resize((4800, 2700), Image.BILINEAR)
                    up.save(up_path, quality=85)
                    in_file = up_path
                    up_created = True
            except Exception:
                in_file = str(img_path)

        num_frames = max(1, int(round(duration * fps)))
        pattern = idx % 4
        # All patterns start at zoom 1.000 so the initial frame matches full frame perfectly
        if pattern == 0:
            # 0: Gentle Center Zoom-In (1.00 -> ~1.048)
            expr = "z='min(zoom+0.00035,1.048)':x='trunc(iw/2-(iw/zoom/2))':y='trunc(ih/2-(ih/zoom/2))'"
        elif pattern == 1:
            # 1: Gentle Upper-Third Zoom-In (focus on face / speaker)
            expr = "z='min(zoom+0.00035,1.048)':x='trunc(iw/2-(iw/zoom/2))':y='trunc(ih/3-(ih/zoom/3))'"
        elif pattern == 2:
            # 2: Gentle Drift Right & Zoom-In
            expr = "z='min(zoom+0.0003,1.045)':x='trunc(iw/3-(iw/zoom/3))':y='trunc(ih/2-(ih/zoom/2))'"
        else:
            # 3: Gentle Drift Left & Zoom-In
            expr = "z='min(zoom+0.0003,1.045)':x='trunc(2*iw/3-(2*iw/zoom/3))':y='trunc(ih/2-(ih/zoom/2))'"

        vf = f"zoompan={expr}:d={num_frames}:s=1920x1080:fps={fps}"

        cmd = [
            ffmpeg_path, "-y",
            "-r", str(fps),
            "-i", in_file,
            "-vf", vf,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264",
            "-g", "1",
            "-preset", "ultrafast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(out_clip_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return proc.returncode == 0 and os.path.exists(out_clip_path)
    except Exception as e:
        logger.warning(f"Ken Burns clip generation failed for slide {idx}: {e}")
        return False
    finally:
        if up_created and os.path.exists(in_file):
            try:
                os.remove(in_file)
            except:
                pass


def _compile_video_ffmpeg(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    segment_timings: list[dict],
    subtitles_path: str,
    fps: int,
    ken_burns: bool = False,
    transitions: bool = True,
) -> str:
    """Compile using FFmpeg directly — 10-50x faster than MoviePy."""
    global _cached_encoder
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except:
        ffmpeg_path = "ffmpeg"
    
    # Detect best encoder once
    if _cached_encoder is None:
        _cached_encoder = _detect_best_encoder(ffmpeg_path)
    encoder, encoder_flags = _cached_encoder
    logger.info(f"Using encoder: {encoder} {encoder_flags}")
    
    _report_progress("Подготовка изображений...")
    
    # Validate audio file
    audio_p = Path(audio_path)
    if not audio_p.exists() or audio_p.stat().st_size == 0:
        raise RuntimeError(f"Аудиофайл озвучки отсутствует или пуст (0 байт): {audio_path}")

    # Get audio duration
    duration_cmd = [ffmpeg_path, "-i", audio_path, "-f", "null", "-"]
    try:
        result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=30)
        import re
        match = re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', result.stderr)
        if match:
            h, m, s, ms = match.groups()
            total_duration = int(h)*3600 + int(m)*60 + int(s) + int(ms)/100
        else:
            total_duration = 300  # fallback 5 min
    except:
        total_duration = 300
    
    _report_progress(f"Аудио: {total_duration:.0f} сек")
    
    # 1. Collect all existing, readable valid images
    valid_pool = []
    for p in image_paths:
        if p and Path(p).exists() and Path(p).is_file():
            try:
                if Path(p).stat().st_size > 5000:
                    valid_pool.append(str(Path(p).resolve()))
            except Exception:
                pass
    valid_pool = list(dict.fromkeys(valid_pool))
    logger.info(f"Compiler valid image pool: {len(valid_pool)} unique photos for {len(image_paths)} slides")

    # 2. Sanitize image_paths to guarantee NO gaps or empty strings
    clean_image_paths = []
    last_valid = valid_pool[0] if valid_pool else None
    for i, p in enumerate(image_paths):
        if p and Path(p).exists() and Path(p).is_file() and str(Path(p).resolve()) in valid_pool:
            last_valid = str(Path(p).resolve())
            clean_image_paths.append(last_valid)
        else:
            # Substitute gap seamlessly from previous slide or pool
            if last_valid:
                chosen = last_valid
            elif valid_pool:
                chosen = valid_pool[i % len(valid_pool)]
            else:
                chosen = None
            if chosen:
                logger.warning(f"Video compiler: slide {i} image was missing/empty. Substituted with: {Path(chosen).name}")
            clean_image_paths.append(chosen)

    # Prepare all images in parallel (order preserved)
    from concurrent.futures import ThreadPoolExecutor
    workers = max(2, min(8, (os.cpu_count() or 4)))
    
    def _prep_one(args):
        i, path = args
        if path and Path(path).exists():
            try:
                return _prepare_image(path)
            except Exception as e:
                logger.error(f"Failed to prepare image {path}: {e}")
        # If preparation failed, try candidates from valid_pool
        for fb_path in valid_pool:
            try:
                if Path(fb_path).exists():
                    return _prepare_image(fb_path)
            except Exception:
                continue
        return _create_placeholder(str(Path(output_path).parent / f"placeholder_{i}.jpg"))
    
    prepared = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, prep in enumerate(pool.map(_prep_one, enumerate(clean_image_paths))):
            prepared.append(prep)
            if (i + 1) % 20 == 0:
                _report_progress(f"Подготовка картинок: {i + 1}/{len(clean_image_paths)}")
    
    # Calculate durations for each slide
    num_slides = len(prepared)
    if segment_timings and len(segment_timings) == num_slides:
        durations = [max(t["duration_ms"] / 1000, 1.0) for t in segment_timings]
        total_slides_dur = sum(durations)
        if abs(total_slides_dur - total_duration) > 2:
            ratio = total_duration / total_slides_dur
            durations = [d * ratio for d in durations]
    else:
        slide_dur = total_duration / num_slides
        durations = [slide_dur] * num_slides
    
    workdir = Path(output_path).parent.resolve()
    concat_file = str(workdir / "concat_list.txt")
    trans_dir = workdir / "transitions"
    kb_clips_dir = workdir / "kb_clips"
    use_kb_concat = False

    trans_sec = 0.5
    # Optional Ken Burns dynamic camera motion
    if ken_burns:
        _report_progress(f"Генерация динамики Ken Burns ({num_slides} слайдов)...")
        kb_clips_dir.mkdir(parents=True, exist_ok=True)
        
        def _render_kb_slide(args):
            i, (img, dur) = args
            # For slide 0: dur[0]. For slide i >= 1: dur[i] + trans_sec for smooth crossfade overlap
            clip_dur = dur if (not transitions or i == 0 or num_slides == 1) else (dur + trans_sec)
            clip_path = kb_clips_dir / f"kb_{i:04d}.mp4"
            ok = _generate_ken_burns_clip(ffmpeg_path, img, str(clip_path), clip_dur, i, fps)
            return (i, clip_path if ok else None)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            rendered_clips = list(pool.map(_render_kb_slide, enumerate(zip(prepared, durations))))
            
        all_kb_ok = all(clip_p is not None and clip_p.exists() for _, clip_p in rendered_clips)
        if all_kb_ok:
            sorted_clips = [clip_p for _, clip_p in sorted(rendered_clips, key=lambda x: x[0])]
            
            if transitions and num_slides > 1:
                _report_progress(f"Создание бесшовных переходов (blend) между кадрами...")
                kb_trans_dir = workdir / "kb_trans"
                kb_chunks_dir = workdir / "kb_chunks"
                kb_trans_dir.mkdir(parents=True, exist_ok=True)
                kb_chunks_dir.mkdir(parents=True, exist_ok=True)

                # 1. Render all transition blends in parallel using FFmpeg native blend
                def _render_one_trans(i):
                    dur_a = durations[0] if i == 0 else (durations[i] + trans_sec)
                    trans_p = kb_trans_dir / f"trans_{i:04d}.mp4"
                    ok = _render_transition_blend(ffmpeg_path, sorted_clips[i], sorted_clips[i+1], str(trans_p), dur_a, trans_sec)
                    return (i, trans_p if ok else None)

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    trans_results = dict(pool.map(_render_one_trans, range(num_slides - 1)))

                # 2. Slice chunks with instant stream copy (-c copy) and write concat list
                with open(concat_file, "w", encoding="utf-8") as f:
                    for i in range(num_slides):
                        chunk_p = kb_chunks_dir / f"chunk_{i:04d}.mp4"
                        if i == 0:
                            c_dur = max(durations[0] - trans_sec, 0.1)
                            subprocess.run([ffmpeg_path, '-y', '-i', str(sorted_clips[0]), '-t', f"{c_dur:.3f}", '-c', 'copy', str(chunk_p)], capture_output=True)
                        elif i < num_slides - 1:
                            c_dur = max(durations[i] - trans_sec, 0.1)
                            subprocess.run([ffmpeg_path, '-y', '-ss', f"{trans_sec:.3f}", '-i', str(sorted_clips[i]), '-t', f"{c_dur:.3f}", '-c', 'copy', str(chunk_p)], capture_output=True)
                        else:
                            subprocess.run([ffmpeg_path, '-y', '-ss', f"{trans_sec:.3f}", '-i', str(sorted_clips[i]), '-t', f"{durations[i]:.3f}", '-c', 'copy', str(chunk_p)], capture_output=True)

                        rel_chunk = os.path.relpath(chunk_p, workdir).replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{rel_chunk}'\n")

                        if i < num_slides - 1 and trans_results.get(i) and trans_results[i].exists():
                            rel_trans = os.path.relpath(trans_results[i], workdir).replace("\\", "/").replace("'", "'\\''")
                            f.write(f"file '{rel_trans}'\n")
            else:
                # Direct motion concat without transitions
                with open(concat_file, "w", encoding="utf-8") as f:
                    for clip_p in sorted_clips:
                        rel_clip = os.path.relpath(clip_p, workdir).replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{rel_clip}'\n")

            use_kb_concat = True
            logger.info(f"Ken Burns successfully generated {len(rendered_clips)} motion clips (transitions={transitions})")
        else:
            logger.warning("Some Ken Burns clips failed, falling back to static slides")

    # Static slideshow mode (when ken_burns is False or failed)
    if not use_kb_concat:
        if transitions:
            _report_progress(f"Создание плавных переходов (crossfade) для {num_slides} слайдов...")
            trans_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate all crossfade frames in parallel first
            with ThreadPoolExecutor(max_workers=workers) as pool:
                all_trans = list(pool.map(
                    lambda i: _generate_crossfade_frames(prepared[i], prepared[i + 1], trans_dir, i, num_frames=6),
                    range(len(prepared) - 1),
                ))
            
            with open(concat_file, "w", encoding="utf-8") as f:
                for i, (img_path, dur) in enumerate(zip(prepared, durations)):
                    rel_img = os.path.relpath(img_path, workdir).replace("\\", "/").replace("'", "'\\''")
                    
                    if i < len(prepared) - 1:
                        static_dur = max(dur - 0.48, 0.5) if all_trans[i] else dur
                        f.write(f"file '{rel_img}'\n")
                        f.write(f"duration {static_dur:.3f}\n")
                        
                        for tf_path, tf_dur in all_trans[i]:
                            rel_tf = os.path.relpath(tf_path, workdir).replace("\\", "/").replace("'", "'\\''")
                            f.write(f"file '{rel_tf}'\n")
                            f.write(f"duration {tf_dur:.3f}\n")
                    else:
                        f.write(f"file '{rel_img}'\n")
                        f.write(f"duration {dur:.3f}\n")
                        
                rel_last = os.path.relpath(prepared[-1], workdir).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{rel_last}'\n")
        else:
            # Direct static concat (no transitions, no Ken Burns)
            _report_progress(f"Прямая сборка слайдов без переходов...")
            with open(concat_file, "w", encoding="utf-8") as f:
                for img_path, dur in zip(prepared, durations):
                    rel_img = os.path.relpath(img_path, workdir).replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{rel_img}'\n")
                    f.write(f"duration {dur:.3f}\n")
                rel_last = os.path.relpath(prepared[-1], workdir).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{rel_last}'\n")
    
    # Prepare subtitles for burning directly in pass 1
    temp_subs = None
    subtitles_filter = None
    if subtitles_path and Path(subtitles_path).exists():
        try:
            sub_p = Path(subtitles_path).resolve()
            if sub_p.suffix.lower() == ".ass":
                temp_subs = workdir / "subs_to_burn.ass"
                if sub_p != temp_subs:
                    import shutil
                    shutil.copy2(sub_p, temp_subs)
                subtitles_filter = f"fps={fps},ass={temp_subs.name}"
                logger.info(f"ASS Karaoke subtitles filter enabled: {subtitles_filter}")
            else:
                temp_subs = workdir / "subs_to_burn.srt"
                if sub_p != temp_subs:
                    import shutil
                    shutil.copy2(sub_p, temp_subs)
                style = (
                    "PlayResX=1920,PlayResY=1080,"
                    "FontName=Arial,FontSize=42,Bold=1,PrimaryColour=&H00FFFFFF,"
                    "OutlineColour=&H00000000,BackColour=&H80000000,"
                    "Outline=3.5,Shadow=1.5,Alignment=2,MarginV=55"
                )
                subtitles_filter = f"fps={fps},subtitles={temp_subs.name}:force_style='{style}'"
                logger.info(f"SRT subtitles filter enabled: {subtitles_filter}")
        except Exception as e:
            logger.warning(f"Failed to prepare subtitles filter: {e}")

    audio_resolved = str(Path(audio_path).resolve())
    output_resolved = str(Path(output_path).resolve())

    # Build FFmpeg command for single-pass compilation with multi-threading
    cmd = [
        ffmpeg_path,
        "-y",  # overwrite
        "-threads", "0",
        "-f", "concat",
        "-safe", "0",
        "-i", "concat_list.txt",
        "-i", audio_resolved,
    ]
    if subtitles_filter:
        cmd.extend(["-vf", subtitles_filter])
        
    cmd.extend([
        "-c:v", encoder,
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
    ] + encoder_flags + [
        "-threads", "0",
        "-movflags", "+faststart",
        output_resolved,
    ])
    
    _report_progress("FFmpeg: компиляция видео с переходами и субтитрами...")
    logger.info(f"FFmpeg cmd in {workdir}: {' '.join(cmd[:10])}...")
    
    compilation_ok = False
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=str(workdir))
        if proc.returncode != 0:
            logger.error(f"FFmpeg crossfade error: {proc.stderr[-500:]}")
            _report_progress("FFmpeg ошибка переходов, применяем прямую сборку FFmpeg...")
            _compile_video_ffmpeg_direct(ffmpeg_path, prepared, durations, audio_path, output_path, fps, subtitles_path)
        else:
            compilation_ok = True
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg crossfade timed out, falling back to direct FFmpeg")
        _compile_video_ffmpeg_direct(ffmpeg_path, prepared, durations, audio_path, output_path, fps, subtitles_path)
    
    # Cleanup subtitles temp file
    if temp_subs and temp_subs.exists():
        try:
            temp_subs.unlink()
        except:
            pass
            
    # Clean up concat file, transitions & ken burns clips
    try:
        if os.path.exists(concat_file):
            os.remove(concat_file)
        import shutil
        shutil.rmtree(trans_dir, ignore_errors=True)
        shutil.rmtree(kb_clips_dir, ignore_errors=True)
        shutil.rmtree(workdir / "kb_trans", ignore_errors=True)
        shutil.rmtree(workdir / "kb_chunks", ignore_errors=True)
    except:
        pass
    
    out_p = Path(output_path)
    if not out_p.exists() or out_p.stat().st_size == 0:
        raise RuntimeError(f"Сборка видео не удалась: итоговый файл не создан или пуст (0 байт) [{output_path}]")

    _report_progress(f"Видео готово: {out_p.name}")
    logger.info(f"Video compiled successfully: {output_path} ({out_p.stat().st_size / (1024*1024):.1f} MB)")
    return output_path


def _compile_video_ffmpeg_direct(ffmpeg_path, prepared, durations, audio_path, output_path, fps, subtitles_path=None):
    """Direct fast FFmpeg fallback without transitions - finishes in seconds."""
    _report_progress("Быстрая сборка FFmpeg (прямая склейка)...")
    logger.info("Using direct FFmpeg concat fallback")
    
    workdir = Path(output_path).parent.resolve()
    concat_file = str(workdir / "concat_direct.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for img_path, dur in zip(prepared, durations):
            rel_img = os.path.relpath(img_path, workdir).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{rel_img}'\n")
            f.write(f"duration {dur:.3f}\n")
        rel_last = os.path.relpath(prepared[-1], workdir).replace("\\", "/").replace("'", "'\\''")
        f.write(f"file '{rel_last}'\n")
    
    subtitles_filter = None
    temp_subs = None
    if subtitles_path and Path(subtitles_path).exists():
        try:
            import shutil
            sub_p = Path(subtitles_path).resolve()
            if sub_p.suffix.lower() == ".ass":
                temp_subs = workdir / "subs_to_burn_direct.ass"
                if sub_p != temp_subs:
                    shutil.copy2(sub_p, temp_subs)
                subtitles_filter = f"fps={fps},ass={temp_subs.name}"
            else:
                temp_subs = workdir / "subs_to_burn_direct.srt"
                if sub_p != temp_subs:
                    shutil.copy2(sub_p, temp_subs)
                style = "PlayResX=1920,PlayResY=1080,FontName=Arial,FontSize=42,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Outline=3.5,Shadow=1.5,Alignment=2,MarginV=55"
                subtitles_filter = f"fps={fps},subtitles={temp_subs.name}:force_style='{style}'"
        except Exception as e:
            logger.warning(f"Could not prepare subs for direct concat: {e}")

    audio_resolved = str(Path(audio_path).resolve())
    output_resolved = str(Path(output_path).resolve())

    cmd = [
        ffmpeg_path,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", "concat_direct.txt",
        "-i", audio_resolved,
    ]
    if subtitles_filter:
        cmd.extend(["-vf", subtitles_filter])
        
    cmd.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-preset", "ultrafast",
        "-movflags", "+faststart",
        output_resolved,
    ])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, cwd=str(workdir))
        if proc.returncode != 0:
            err_msg = proc.stderr[-400:] if proc.stderr else "Unknown error"
            logger.error(f"Direct FFmpeg failed: {err_msg}")
            raise RuntimeError(f"FFmpeg fallback error: {err_msg}")
        else:
            logger.info("Direct FFmpeg fallback succeeded!")
    finally:
        try:
            os.remove(concat_file)
            if temp_subs and temp_subs.exists():
                temp_subs.unlink()
        except:
            pass
    return output_path


def _burn_subtitles_ffmpeg(ffmpeg_path, input_video, srt_path, output_video):
    """Fallback burn subtitles using FFmpeg with CWD isolation."""
    import shutil
    srt_p = Path(srt_path).resolve()
    if not srt_p.exists():
        logger.warning(f"SRT file not found: {srt_p}, copying video without subs")
        if input_video != output_video and os.path.exists(input_video):
            os.replace(input_video, output_video)
        return
        
    workdir = Path(input_video).parent.resolve()
    temp_srt = workdir / "subs_to_burn.srt"
    try:
        shutil.copy2(srt_p, temp_srt)
    except Exception as e:
        logger.warning(f"Failed to copy srt to workdir: {e}")
        temp_srt = srt_p

    style = (
        "FontName=Arial,FontSize=26,Bold=1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BackColour=&H80000000,"
        "Outline=2,Shadow=1,MarginV=45"
    )

    in_name = Path(input_video).name
    out_name = Path(output_video).name
    
    cmd = [
        ffmpeg_path,
        "-y",
        "-i", in_name,
        "-vf", f"subtitles={temp_srt.name}:force_style='{style}'",
        "-c:v", "libx264",
        "-c:a", "copy",
        "-preset", "ultrafast",
        out_name,
    ]

    logger.info(f"Burning subtitles in {workdir}: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=str(workdir))
        if proc.returncode != 0:
            logger.error(f"FFmpeg subtitles failed (rc={proc.returncode}): {proc.stderr[-400:]}")
            if input_video != output_video and os.path.exists(input_video):
                os.replace(input_video, output_video)
        else:
            logger.info("Subtitles successfully burned into video!")
            if input_video != output_video and os.path.exists(input_video):
                try:
                    os.remove(input_video)
                except:
                    pass
    except Exception as e:
        logger.error(f"Error burning subtitles: {e}")
        if input_video != output_video and os.path.exists(input_video):
            os.replace(input_video, output_video)
    finally:
        if temp_srt.exists() and temp_srt != srt_p:
            try:
                temp_srt.unlink()
            except:
                pass
