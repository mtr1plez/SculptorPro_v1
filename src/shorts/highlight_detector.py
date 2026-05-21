"""
Highlight Detector — Uses Gemini to find the most engaging segments in a video transcript.

Sends the full Whisper transcript to Gemini and asks it to identify
viral-worthy moments with precise timestamps.
"""

import os
import json
import logging
from typing import List
from pathlib import Path

logger = logging.getLogger(__name__)


HIGHLIGHT_PROMPT = """You are a professional short-form content editor (TikTok/Reels/Shorts).

I will give you a full transcript of a video with timestamps.
Your job is to identify the {count} most engaging, viral-worthy segments.

Rules:
- Each segment should be {min_duration}-{max_duration} seconds long
- Pick moments with: strong hooks, emotional peaks, surprising info, funny moments, dramatic tension
- Segments must NOT overlap
- Provide a catchy short title for each clip (max 50 chars)
- Provide a "hook" — the first sentence that grabs attention (max 100 chars)
- Rate each segment's viral potential from 1-10

TRANSCRIPT:
{transcript}

Respond ONLY with a valid JSON array, no other text. Format:
[
  {{
    "start": 12.5,
    "end": 52.3,
    "title": "Catchy Title Here",
    "hook": "You won't believe what happens next...",
    "score": 8
  }},
  ...
]

Sort by score descending (best first). Return exactly {count} segments.
"""


def _format_transcript_for_prompt(transcript: dict) -> str:
    """Format Whisper transcript with timestamps for the prompt."""
    lines = []
    for seg in transcript.get("segments", []):
        start = seg["start"]
        end = seg["end"]
        text = seg["text"]
        lines.append(f"[{start:.1f}s - {end:.1f}s] {text}")
    return "\n".join(lines)


def detect_highlights(
    transcript: dict,
    video_duration: float,
    count: int = 5,
    min_duration: int = 30,
    max_duration: int = 90,
) -> List[dict]:
    """
    Use Gemini to analyze transcript and find engaging segments.

    Args:
        transcript: Whisper transcript dict with segments
        video_duration: Total video duration in seconds
        count: Number of clips to extract
        min_duration: Minimum clip duration (seconds)
        max_duration: Maximum clip duration (seconds)

    Returns:
        List of highlight dicts: [{start, end, title, hook, score}, ...]
    """
    from src.utils.gemini_client import GeminiClient

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_API_KEY not set — falling back to uniform split")
        return _uniform_fallback(video_duration, count, min_duration, max_duration)

    formatted_transcript = _format_transcript_for_prompt(transcript)

    prompt = HIGHLIGHT_PROMPT.format(
        count=count,
        min_duration=min_duration,
        max_duration=max_duration,
        transcript=formatted_transcript,
    )

    try:
        client = GeminiClient()
        response = client.generate_content(prompt)
        text = response.text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # remove first line
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        highlights = json.loads(text)

        # Validate and clamp
        validated = []
        for h in highlights:
            start = max(0.0, float(h.get("start", 0)))
            end = min(video_duration, float(h.get("end", start + min_duration)))
            duration = end - start
            if duration < 10:  # too short, skip
                continue
            validated.append({
                "start": round(start, 2),
                "end": round(end, 2),
                "title": str(h.get("title", f"Clip {len(validated)+1}"))[:50],
                "hook": str(h.get("hook", ""))[:100],
                "score": min(10, max(1, int(h.get("score", 5)))),
            })

        if validated:
            logger.info("Gemini returned %d highlights", len(validated))
            return sorted(validated, key=lambda x: x["score"], reverse=True)

        logger.warning("Gemini returned no valid highlights — using fallback")
        return _uniform_fallback(video_duration, count, min_duration, max_duration)

    except Exception as e:
        logger.error("Gemini highlight detection failed: %s", e)
        return _uniform_fallback(video_duration, count, min_duration, max_duration)


def _uniform_fallback(
    video_duration: float,
    count: int,
    min_duration: int,
    max_duration: int,
) -> List[dict]:
    """
    Fallback: split video into evenly-spaced clips.
    Used when Gemini is unavailable.
    """
    clip_duration = min(max_duration, max(min_duration, video_duration / (count + 1)))
    step = video_duration / (count + 1)

    highlights = []
    for i in range(count):
        start = step * (i + 0.5)
        end = min(start + clip_duration, video_duration)
        if end - start < 10:
            break
        highlights.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "title": f"Clip {i + 1}",
            "hook": "",
            "score": 5,
        })

    logger.info("Uniform fallback: %d clips of ~%.0fs", len(highlights), clip_duration)
    return highlights
