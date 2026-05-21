"""
Subtitle Burner — Whisper-based transcription + ASS subtitle generation + burn-in.

Uses openai-whisper (already installed) for word-level timestamps,
then generates styled ASS subtitles (TikTok/Reels style) and burns them
into the video via ffmpeg.
"""

import os
import json
import logging
import subprocess
import tempfile
from typing import Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# ASS style presets  (TikTok / Reels look)
# ============================================================

SUBTITLE_STYLES = {
    "bold_white": {
        "fontname": "Arial",
        "fontsize": 18,
        "primary_color": "&H00FFFFFF",   # white
        "outline_color": "&H00000000",   # black outline
        "back_color": "&H80000000",      # semi-transparent shadow
        "bold": -1,
        "outline": 3,
        "shadow": 1,
        "alignment": 2,  # bottom-center
        "margin_v": 60,
    },
    "yellow_pop": {
        "fontname": "Arial",
        "fontsize": 20,
        "primary_color": "&H0000FFFF",   # yellow (BGR)
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "bold": -1,
        "outline": 4,
        "shadow": 2,
        "alignment": 2,
        "margin_v": 60,
    },
    "neon_green": {
        "fontname": "Arial",
        "fontsize": 18,
        "primary_color": "&H0000FF00",
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "bold": -1,
        "outline": 3,
        "shadow": 1,
        "alignment": 2,
        "margin_v": 60,
    },
}


def _fmt_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp  h:mm:ss.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def transcribe_audio(video_path: str, whisper_model: str = "small",
                     language: Optional[str] = None) -> dict:
    """
    Run Whisper on the video file and return word-level segments.

    Returns:
        {
            "text": "full transcript...",
            "segments": [
                {
                    "start": 0.0, "end": 2.5,
                    "text": "Hello world",
                    "words": [{"word": "Hello", "start": 0.0, "end": 1.0}, ...]
                },
                ...
            ]
        }
    """
    import whisper

    logger.info("Loading Whisper model '%s' …", whisper_model)
    model = whisper.load_model(whisper_model)

    logger.info("Transcribing: %s", video_path)
    result = model.transcribe(
        video_path,
        language=language,
        word_timestamps=True,
        verbose=False,
    )

    # Flatten segments into a simpler structure
    segments = []
    for seg in result.get("segments", []):
        words = []
        for w in seg.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })
        segments.append({
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"].strip(),
            "words": words,
        })

    return {
        "text": result.get("text", "").strip(),
        "language": result.get("language", ""),
        "segments": segments,
    }


def _chunk_words(segments: list, max_words: int = 3) -> List[dict]:
    """
    Group word-level timestamps into subtitle chunks of `max_words` words.
    Returns list of {start, end, text}.
    """
    all_words = []
    for seg in segments:
        all_words.extend(seg.get("words", []))

    chunks = []
    for i in range(0, len(all_words), max_words):
        group = all_words[i : i + max_words]
        if not group:
            continue
        text = " ".join(w["word"] for w in group)
        chunks.append({
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": text,
        })
    return chunks


def generate_ass_file(
    transcript: dict,
    output_path: str,
    video_width: int = 1080,
    video_height: int = 1920,
    style_name: str = "bold_white",
    custom_style: Optional[dict] = None,
    words_per_line: int = 3,
) -> str:
    """
    Generate an ASS subtitle file from Whisper transcript.
    Returns path to .ass file.
    """
    base_style = SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES["bold_white"])
    style = {**base_style}
    if custom_style:
        # Override preset fields with anything provided by user
        style.update(custom_style)
        
    chunks = _chunk_words(transcript["segments"], max_words=words_per_line)

    header = f"""[Script Info]
Title: SculptorPro Shorts Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['fontname']},{style['fontsize']},{style['primary_color']},&H000000FF,{style['outline_color']},{style['back_color']},{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},{style['alignment']},40,40,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for chunk in chunks:
        start = _fmt_ass_time(chunk["start"])
        end = _fmt_ass_time(chunk["end"])
        # Uppercase for TikTok-style pop
        text = chunk["text"].upper()
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("ASS subtitles written → %s  (%d chunks)", output_path, len(chunks))
    return output_path


def burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
) -> str:
    """
    Burn ASS subtitles into the video using ffmpeg.
    Returns path to output video.
    """
    # Escape paths for ASS filter (colons & backslashes)
    safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"ass='{safe_ass}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info("Burning subtitles: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg subtitle burn failed:\n%s", result.stderr)
        raise RuntimeError(f"ffmpeg subtitle burn failed: {result.stderr[-500:]}")

    logger.info("Subtitles burned → %s", output_path)
    return output_path
