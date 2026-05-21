"""
Shorts Generator — Main orchestrator for the clip generation pipeline.

Pipeline:
1. Transcribe video via Whisper  (subtitle_burner.transcribe_audio)
2. Detect highlights via Gemini  (highlight_detector.detect_highlights)
3. For each highlight:
   a. Cut clip via ffmpeg
   b. Crop to 9:16 (center-crop)
   c. Generate ASS subtitles
   d. Burn subtitles into the clip
4. Save results + metadata
"""

import os
import json
import uuid
import time
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Callable, Optional

from src.shorts.subtitle_burner import (
    transcribe_audio,
    generate_ass_file,
    burn_subtitles,
)
from src.shorts.highlight_detector import detect_highlights

logger = logging.getLogger(__name__)

# Base directory for shorts jobs
SHORTS_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent / "_shorts"


def _get_video_info(video_path: str) -> dict:
    """Get video duration, width, height via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])

    # Find video stream
    width, height = 1920, 1080
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 1920))
            height = int(stream.get("height", 1080))
            break

    return {"duration": duration, "width": width, "height": height}


def _cut_clip(
    source_path: str,
    output_path: str,
    start: float,
    end: float,
) -> str:
    """Cut a segment from source video using ffmpeg (fast seek)."""
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", source_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[-500:]}")
    return output_path


def _crop_vertical(
    input_path: str,
    output_path: str,
    src_width: int,
    src_height: int,
) -> str:
    """
    Crop video to 9:16 vertical format (center-crop).
    Output: 1080x1920 (or proportional).
    """
    # Calculate crop dimensions
    target_ratio = 9 / 16  # width/height
    src_ratio = src_width / src_height

    if src_ratio > target_ratio:
        # Source is wider → crop horizontally
        new_w = int(src_height * target_ratio)
        new_h = src_height
        crop_filter = f"crop={new_w}:{new_h}:(iw-{new_w})/2:0"
    else:
        # Source is taller → crop vertically
        new_w = src_width
        new_h = int(src_width / target_ratio)
        crop_filter = f"crop={new_w}:{new_h}:0:(ih-{new_h})/2"

    # Then scale to 1080x1920
    scale_filter = "scale=1080:1920"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"{crop_filter},{scale_filter}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg crop failed: {result.stderr[-500:]}")
    return output_path


def _generate_thumbnail(video_path: str, thumb_path: str, time_sec: float = 1.0):
    """Extract a single frame as thumbnail."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(time_sec),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        thumb_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True)


class ShortsGenerator:
    """Main orchestrator for shorts generation pipeline."""

    def __init__(self, shorts_base_dir: Optional[str] = None):
        self.shorts_dir = Path(shorts_base_dir) if shorts_base_dir else SHORTS_DIR
        self.shorts_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, video_path: str, options: dict) -> str:
        """
        Create a new shorts generation job.
        Returns job_id.
        """
        job_id = str(uuid.uuid4())[:8]
        job_dir = self.shorts_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "clips").mkdir(exist_ok=True)
        (job_dir / "thumbnails").mkdir(exist_ok=True)

        # Copy source video
        source_ext = Path(video_path).suffix
        source_dest = job_dir / f"source{source_ext}"
        shutil.copy2(video_path, source_dest)

        meta = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "progress_text": "Ожидание…",
            "source_path": str(source_dest),
            "original_filename": Path(video_path).name,
            "options": options,
            "created_at": time.time(),
            "clips": [],
            "error": None,
        }
        self._save_meta(job_id, meta)
        logger.info("Created shorts job %s", job_id)
        return job_id

    def generate(
        self,
        job_id: str,
        progress_callback: Optional[Callable] = None,
    ):
        """
        Run the full shorts generation pipeline.
        This is meant to be called as a background task.
        """
        meta = self._load_meta(job_id)
        if not meta:
            raise ValueError(f"Job {job_id} not found")

        source_path = meta["source_path"]
        options = meta.get("options", {})
        job_dir = self.shorts_dir / job_id

        whisper_model = options.get("whisper_model", "small")
        subtitle_style = options.get("subtitle_style", "bold_white")
        custom_subtitle_style = options.get("custom_subtitle_style", None)
        subtitles_enabled = options.get("subtitles", True)
        clip_count = options.get("clip_count", 5)
        min_duration = options.get("min_duration", 30)
        max_duration = options.get("max_duration", 90)
        words_per_line = options.get("words_per_line", 3)
        language = options.get("language", None)

        def report(percent: int, text: str):
            meta["progress"] = percent
            meta["progress_text"] = text
            meta["status"] = "processing"
            self._save_meta(job_id, meta)
            if progress_callback:
                progress_callback(percent, text)

        try:
            # ---- Step 1: Get video info ----
            report(5, "Анализ видео…")
            info = _get_video_info(source_path)
            logger.info("Video: %dx%d, %.1fs", info["width"], info["height"], info["duration"])

            # ---- Step 2: Transcribe ----
            report(10, "Транскрибирование (Whisper)… Это может занять несколько минут")
            transcript = transcribe_audio(source_path, whisper_model=whisper_model, language=language)

            # Save transcript
            transcript_path = job_dir / "transcript.json"
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(transcript, f, ensure_ascii=False, indent=2)

            report(40, "Транскрипция готова. Поиск интересных моментов…")

            # ---- Step 3: Detect highlights ----
            highlights = detect_highlights(
                transcript=transcript,
                video_duration=info["duration"],
                count=clip_count,
                min_duration=min_duration,
                max_duration=max_duration,
            )

            # Save highlights
            highlights_path = job_dir / "highlights.json"
            with open(highlights_path, "w", encoding="utf-8") as f:
                json.dump(highlights, f, ensure_ascii=False, indent=2)

            report(50, f"Найдено {len(highlights)} моментов. Нарезка клипов…")

            # ---- Step 4: Generate clips ----
            clips_info = []
            total = len(highlights)

            for idx, hl in enumerate(highlights):
                clip_num = idx + 1
                pct = 50 + int(45 * clip_num / total)
                report(pct, f"Генерация клипа {clip_num}/{total}: {hl['title']}")

                try:
                    clip_result = self._process_single_clip(
                        job_dir=job_dir,
                        source_path=source_path,
                        highlight=hl,
                        clip_index=clip_num,
                        src_width=info["width"],
                        src_height=info["height"],
                        transcript=transcript,
                        subtitle_style=subtitle_style,
                        custom_subtitle_style=custom_subtitle_style,
                        subtitles_enabled=subtitles_enabled,
                        words_per_line=words_per_line,
                    )
                    clips_info.append(clip_result)
                except Exception as e:
                    logger.error("Failed to generate clip %d: %s", clip_num, e)
                    clips_info.append({
                        "index": clip_num,
                        "error": str(e),
                        "title": hl["title"],
                    })

            # ---- Done ----
            meta["clips"] = clips_info
            meta["status"] = "done"
            meta["progress"] = 100
            meta["progress_text"] = f"Готово! {len([c for c in clips_info if 'error' not in c])} клипов"
            self._save_meta(job_id, meta)

            if progress_callback:
                progress_callback(100, meta["progress_text"])

            logger.info("Job %s completed: %d clips", job_id, len(clips_info))

        except Exception as e:
            logger.error("Job %s failed: %s", job_id, e)
            meta["status"] = "error"
            meta["error"] = str(e)
            meta["progress_text"] = f"Ошибка: {e}"
            self._save_meta(job_id, meta)
            if progress_callback:
                progress_callback(0, f"Ошибка: {e}")
            raise

    def _process_single_clip(
        self,
        job_dir: Path,
        source_path: str,
        highlight: dict,
        clip_index: int,
        src_width: int,
        src_height: int,
        transcript: dict,
        subtitle_style: str,
        custom_subtitle_style: Optional[dict],
        subtitles_enabled: bool,
        words_per_line: int,
    ) -> dict:
        """Process a single highlight into a finished clip."""
        clips_dir = job_dir / "clips"
        thumbs_dir = job_dir / "thumbnails"

        start = highlight["start"]
        end = highlight["end"]
        duration = end - start

        # 4a. Cut raw clip
        raw_clip = str(clips_dir / f"raw_{clip_index:03d}.mp4")
        _cut_clip(source_path, raw_clip, start, end)

        # 4b. Crop to vertical 9:16
        cropped_clip = str(clips_dir / f"cropped_{clip_index:03d}.mp4")
        _crop_vertical(raw_clip, cropped_clip, src_width, src_height)

        # Clean up raw
        os.remove(raw_clip)

        final_clip = cropped_clip

        # 4c + 4d. Subtitles
        if subtitles_enabled:
            # Filter transcript segments for this clip's time range
            clip_transcript = self._slice_transcript(transcript, start, end)

            if clip_transcript["segments"]:
                ass_path = str(clips_dir / f"subs_{clip_index:03d}.ass")
                generate_ass_file(
                    transcript=clip_transcript,
                    output_path=ass_path,
                    video_width=1080,
                    video_height=1920,
                    style_name=subtitle_style,
                    custom_style=custom_subtitle_style,
                    words_per_line=words_per_line,
                )

                final_path = str(clips_dir / f"clip_{clip_index:03d}.mp4")
                burn_subtitles(cropped_clip, ass_path, final_path)

                # Clean up intermediate
                os.remove(cropped_clip)
                os.remove(ass_path)
                final_clip = final_path

        # Rename if still the cropped version
        if final_clip == cropped_clip:
            final_path = str(clips_dir / f"clip_{clip_index:03d}.mp4")
            os.rename(cropped_clip, final_path)
            final_clip = final_path

        # Generate thumbnail
        thumb_path = str(thumbs_dir / f"thumb_{clip_index:03d}.jpg")
        _generate_thumbnail(final_clip, thumb_path, time_sec=2.0)

        # File size
        file_size = os.path.getsize(final_clip) if os.path.exists(final_clip) else 0

        return {
            "index": clip_index,
            "title": highlight["title"],
            "hook": highlight.get("hook", ""),
            "score": highlight.get("score", 5),
            "start": start,
            "end": end,
            "duration": round(duration, 2),
            "filename": os.path.basename(final_clip),
            "thumbnail": os.path.basename(thumb_path),
            "file_size": file_size,
        }

    def _slice_transcript(self, transcript: dict, start: float, end: float) -> dict:
        """Extract transcript segments within a time range, rebasing timestamps to 0."""
        sliced = []
        for seg in transcript.get("segments", []):
            # Segment overlaps with clip?
            if seg["end"] <= start or seg["start"] >= end:
                continue

            # Rebase to clip-local time
            new_seg = {
                "start": max(0, seg["start"] - start),
                "end": min(end - start, seg["end"] - start),
                "text": seg["text"],
                "words": [],
            }
            for w in seg.get("words", []):
                if w["end"] <= start or w["start"] >= end:
                    continue
                new_seg["words"].append({
                    "word": w["word"],
                    "start": round(max(0, w["start"] - start), 3),
                    "end": round(min(end - start, w["end"] - start), 3),
                })

            if new_seg["words"]:
                sliced.append(new_seg)

        return {"segments": sliced, "text": " ".join(s["text"] for s in sliced)}

    # ---- Job management ----

    def get_job(self, job_id: str) -> Optional[dict]:
        return self._load_meta(job_id)

    def list_jobs(self) -> list[dict]:
        """List all shorts jobs."""
        jobs = []
        if not self.shorts_dir.exists():
            return jobs
        for d in sorted(self.shorts_dir.iterdir()):
            if d.is_dir():
                meta = self._load_meta(d.name)
                if meta:
                    jobs.append({
                        "job_id": meta["job_id"],
                        "status": meta["status"],
                        "progress": meta["progress"],
                        "progress_text": meta.get("progress_text", ""),
                        "original_filename": meta.get("original_filename", ""),
                        "created_at": meta.get("created_at", 0),
                        "clip_count": len(meta.get("clips", [])),
                    })
        return jobs

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and all its files."""
        job_dir = self.shorts_dir / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
            logger.info("Deleted job %s", job_id)
            return True
        return False

    def get_clip_path(self, job_id: str, clip_index: int) -> Optional[str]:
        """Get the absolute path to a clip file."""
        clip_path = self.shorts_dir / job_id / "clips" / f"clip_{clip_index:03d}.mp4"
        if clip_path.exists():
            return str(clip_path)
        return None

    def get_thumbnail_path(self, job_id: str, clip_index: int) -> Optional[str]:
        """Get the absolute path to a thumbnail file."""
        thumb_path = self.shorts_dir / job_id / "thumbnails" / f"thumb_{clip_index:03d}.jpg"
        if thumb_path.exists():
            return str(thumb_path)
        return None

    def _save_meta(self, job_id: str, meta: dict):
        meta_path = self.shorts_dir / job_id / "job_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _load_meta(self, job_id: str) -> Optional[dict]:
        meta_path = self.shorts_dir / job_id / "job_meta.json"
        if not meta_path.exists():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
