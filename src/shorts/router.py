"""
Shorts API Router — FastAPI endpoints for the shorts generation workflow.
"""

import os
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.shorts.shorts_generator import ShortsGenerator

logger = logging.getLogger(__name__)

router = APIRouter()
generator = ShortsGenerator()


# ---- Request models ----

class GenerateRequest(BaseModel):
    video_path: Optional[str] = None   # if already on disk (e.g. from library)
    clip_count: int = 5
    min_duration: int = 30
    max_duration: int = 90
    subtitles: bool = True
    subtitle_style: str = "bold_white"
    custom_subtitle_style: Optional[dict] = None
    words_per_line: int = 3
    whisper_model: str = "small"
    language: Optional[str] = None


# ---- Endpoints ----

@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload a video file for shorts generation."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    # Validate extension
    allowed_ext = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported format: {ext}. Allowed: {allowed_ext}")

    # Save to a temp location
    temp_dir = tempfile.mkdtemp(prefix="shorts_upload_")
    save_path = os.path.join(temp_dir, file.filename)

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    logger.info("Uploaded video: %s (%d bytes)", save_path, len(content))

    return {
        "path": save_path,
        "filename": file.filename,
        "size": len(content),
    }


@router.post("/generate")
async def generate_shorts(req: GenerateRequest, background_tasks: BackgroundTasks):
    """
    Start shorts generation as a background task.
    Accepts either an uploaded video path or a path to a video already on disk.
    """
    video_path = req.video_path
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(400, f"Video not found: {video_path}")

    options = {
        "clip_count": req.clip_count,
        "min_duration": req.min_duration,
        "max_duration": req.max_duration,
        "subtitles": req.subtitles,
        "subtitle_style": req.subtitle_style,
        "custom_subtitle_style": req.custom_subtitle_style,
        "words_per_line": req.words_per_line,
        "whisper_model": req.whisper_model,
        "language": req.language,
    }

    job_id = generator.create_job(video_path, options)

    # Run in background
    background_tasks.add_task(generator.generate, job_id)

    return {"job_id": job_id, "status": "started"}


@router.get("/jobs")
async def list_jobs():
    """List all shorts generation jobs."""
    return generator.list_jobs()


@router.get("/job/{job_id}")
async def get_job(job_id: str):
    """Get details and status of a specific job."""
    job = generator.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    """Quick status poll for a job."""
    job = generator.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "progress_text": job.get("progress_text", ""),
    }


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and all its files."""
    success = generator.delete_job(job_id)
    if not success:
        raise HTTPException(404, f"Job {job_id} not found")
    return {"deleted": True}


@router.get("/download_raw")
async def download_raw(path: str):
    """Serve a local file directly (used for previews)."""
    if not path or not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path)


@router.get("/download/{job_id}/{clip_index}")
async def download_clip(job_id: str, clip_index: int):
    """Download a specific clip from a job."""
    clip_path = generator.get_clip_path(job_id, clip_index)
    if not clip_path:
        raise HTTPException(404, f"Clip {clip_index} not found in job {job_id}")
    return FileResponse(
        clip_path,
        media_type="video/mp4",
        filename=f"short_{job_id}_{clip_index:03d}.mp4",
    )


@router.get("/thumbnail/{job_id}/{clip_index}")
async def get_thumbnail(job_id: str, clip_index: int):
    """Get thumbnail for a specific clip."""
    thumb_path = generator.get_thumbnail_path(job_id, clip_index)
    if not thumb_path:
        raise HTTPException(404, f"Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/jpeg")
