import json
import logging
import time
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Optional

from src.utils.gemini_client import GeminiClient
from src.suno_generator import SunoClient
from src.project_manager import ProjectManager

logger = logging.getLogger(__name__)

router = APIRouter()
gemini_client = GeminiClient()
manager = ProjectManager()

from pydantic import BaseModel

class MusicAnalyzeRequest(BaseModel):
    transcript_text: str
    duration_seconds: float
    project_name: str
    episode_name: str = None

class MusicGenerateRequest(BaseModel):
    prompt: str = ""
    tags: str
    duration_seconds: float
    project_name: str
    cookies: Dict[str, str]

class ScriptMusicPlanRequest(BaseModel):
    script_text: str
    project_hint: Optional[str] = None
    target_blocks: int = 8

def _music_paths(project_name: str):
    if project_name == "__STUDIO__":
        root = manager.studio_path
    else:
        root = manager.projects_path / project_name

    return {
        "root": root,
        "music_dir": root / "music",
        "status_file": root / ".music_gen_status.json",
        "is_studio": project_name == "__STUDIO__",
    }


def _safe_json_array(raw_text: str):
    json_str = gemini_client.parse_json(raw_text)
    start = json_str.find("[")
    end = json_str.rfind("]")
    if start != -1 and end != -1:
        json_str = json_str[start:end + 1]
    return json.loads(json_str)


@router.post("/script_plan")
async def analyze_script_music_plan(req: ScriptMusicPlanRequest):
    """
    Splits a full script into semantic music blocks and returns Suno-ready prompts.
    This does not call Suno; it prepares a cue sheet for the Studio workflow.
    """
    script_text = req.script_text.strip()
    if len(script_text) < 80:
        raise HTTPException(status_code=400, detail="Script is too short for music planning")

    target_blocks = max(3, min(req.target_blocks, 14))

    prompt = f"""
Ты — музыкальный супервайзер для видеоэссе и YouTube-документалистики.
Разбей сценарий на {target_blocks} смысловых музыкальных блоков. Каждый блок должен отражать не только настроение речи, но и тему видео, культурный контекст и узнаваемую стилистику объекта.

Контекст/название видео, если автор указал:
{req.project_hint or "Не указано"}

Сценарий:
\"\"\"{script_text}\"\"\"

Правила:
1. Если тема указывает на эпоху, жанр или франшизу, отрази это в музыке: например, Ганс Ланда -> 1940s European wartime tension, chamber strings, noir; Spider-Man -> heroic comic-book orchestral, modern action, Marvel-like adventure.
2. Не пиши имена защищенных композиторов как требование имитации. Используй описания жанра, эпохи, инструментов и драматургии.
3. suno_tags строго на английском, до 120 символов, через запятую, обязательно instrumental.
4. suno_prompt на английском, 1-2 предложения, как режиссерское описание для Suno. Без вокала и без lyrics.
5. script_excerpt — короткий русский фрагмент/пересказ того места сценария, к которому относится блок.
6. estimated_duration_seconds — примерная длина трека для блока, 25-120 секунд.

Верни только валидный JSON-массив без markdown:
[
  {{
    "id": 1,
    "title": "Название блока на русском",
    "script_excerpt": "Короткий фрагмент или пересказ блока",
    "narrative_summary": "Что происходит в мысли/аргументе автора",
    "emotional_function": "Какую эмоцию должна поддерживать музыка",
    "musical_direction": "Музыкальное направление на русском",
    "suno_tags": "cinematic noir, 1940s chamber strings, slow tension, instrumental",
    "suno_prompt": "Instrumental cue with muted strings and period noir atmosphere...",
    "estimated_duration_seconds": 60
  }}
]
"""

    try:
        response = gemini_client.generate_content(prompt)
        data = _safe_json_array(response.text)
        if not isinstance(data, list) or not data:
            raise ValueError("Expected a non-empty JSON array")

        blocks = []
        for index, item in enumerate(data[:target_blocks], start=1):
            if not isinstance(item, dict):
                continue
            block = {
                "id": int(item.get("id") or index),
                "title": str(item.get("title") or f"Block {index}"),
                "script_excerpt": str(item.get("script_excerpt") or ""),
                "narrative_summary": str(item.get("narrative_summary") or ""),
                "emotional_function": str(item.get("emotional_function") or ""),
                "musical_direction": str(item.get("musical_direction") or ""),
                "suno_tags": str(item.get("suno_tags") or "cinematic background score, instrumental")[:140],
                "suno_prompt": str(item.get("suno_prompt") or ""),
                "estimated_duration_seconds": int(item.get("estimated_duration_seconds") or 60),
            }
            blocks.append(block)

        if not blocks:
            raise ValueError("Gemini returned no usable blocks")

        return {"blocks": blocks}
    except Exception as e:
        logger.error(f"Failed to create script music plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analyze")
async def analyze_music_mood(req: MusicAnalyzeRequest):
    """
    Step 1: Analyzes transcript text via Gemini to provide Suno-compatible music tags.
    """
    logger.info(f"🎵 Analyzing mood for project: {req.project_name}, duration: {req.duration_seconds}s")
    
    prompt = f"""
Ты — профессиональный 'AI Music Supervisor' и аудиорежиссер для кино.
Тебе нужно проанализировать текст транскрипта эпизода и его продолжительность, и создать набор тегов (до 100 символов суммарно) для генератора Suno AI и опциональный промпт. Теги должны описывать настроение, жанр, темп и инструменты.

Текст эпизода:
"{req.transcript_text}"

Хронометраж: {int(req.duration_seconds)} секунд.
Название эпизода (если есть): {req.episode_name or 'Нет'}

Правила:
1. Теги пиши строго на английском языке через запятую.
2. Жанры могут быть 'cinematic', 'ambient', 'orchestral', 'synthwave', 'lo-fi' и т.д.
3. Обязательно в конце пиши тег "[instrumental]" или "instrumental".
4. Продолжительность влияет на темп: если сцена короткая (< 10 сек) и это экшен, то 'fast tempo, intense'. Если длинная - 'slow build-up, atmospheric'.

Твой ответ должен быть валидным JSON объектом (без разметки markdown):
{{
  "tags": "dark cinematic ambient, tension strings, slow tempo, instrumental",
  "reasoning": "Краткое описание почему выбрано такое настроение на русском"
}}
"""
    try:
        response = gemini_client.generate_content(prompt)
        json_str = gemini_client.parse_json(response.text)
        data = json.loads(json_str)
        
        if not isinstance(data, dict) or "tags" not in data:
            raise ValueError("Invalid format: expected 'tags' key in JSON")
            
        return {"tags": data["tags"], "reasoning": data.get("reasoning", "")}

    except Exception as e:
        logger.error(f"Failed to analyze music mood: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def background_generate_music(project_name: str, tags: str, prompt: str, cookies: Dict[str, str]):
    """Background task to poll Suno and download the MP3"""
    paths = _music_paths(project_name)
    status_file = paths["status_file"]
    music_dir = paths["music_dir"]
    music_dir.mkdir(exist_ok=True, parents=True)
    
    def update_status(percent, status):
        try:
            with open(status_file, 'w') as f:
                json.dump({
                    "percent": percent,
                    "status": status,
                    "timestamp": time.time()
                }, f)
        except Exception as e:
            logger.error(f"Cannot update music status: {e}")

    try:
        update_status(10, "Initializing Suno API...")
        suno_client = SunoClient(cookies=cookies)
        
        update_status(20, "Sending generation request...")
        clip_ids = suno_client.generate(tags=tags, prompt=prompt, make_instrumental=True)
        
        if not clip_ids:
            raise Exception("Failed to get clip IDs")
            
        update_status(40, "Polling for completion (this can take 1-2 minutes)...")
        status, audio_url = suno_client.poll(clip_ids, timeout=300)
        
        if status != "complete" or not audio_url:
            raise Exception(f"Suno generation failed or timed out. Status: {status}")
            
        # Clean tags for filename
        safe_name = "".join([c if c.isalnum() else "_" for c in tags[:20]])
        filename = f"suno_{int(time.time())}_{safe_name}.mp3"
        save_path = music_dir / filename
        
        update_status(80, "Downloading generated track...")
        success = suno_client.download(audio_url, str(save_path))
        
        if not success:
            raise Exception("Failed to download MP3 file")
            
        if paths["is_studio"]:
            index_file = music_dir / "studio_music_index.json"
            try:
                if index_file.exists():
                    with open(index_file, "r") as f:
                        index_data = json.load(f)
                else:
                    index_data = []
                index_data.insert(0, {
                    "filename": filename,
                    "tags": tags,
                    "prompt": prompt,
                    "created_at": time.time()
                })
                with open(index_file, "w") as f:
                    json.dump(index_data[:200], f, indent=2)
            except Exception as e:
                logger.warning(f"Could not update Studio music index: {e}")
        else:
            manager.save_music_track(project_name, filename)
        update_status(100, f"Completed. Saved as {filename}")

    except Exception as e:
        logger.error(f"Music generation task error: {e}")
        update_status(-1, str(e))

@router.post("/generate")
async def generate_music(req: MusicGenerateRequest, background_tasks: BackgroundTasks):
    """
    Step 2: Submits generation job to Suno using provided cookies and tags.
    """
    logger.info(f"🎵 Starting generation for project: {req.project_name}. Tags: {req.tags}")
    
    # Initialize status file
    paths = _music_paths(req.project_name)
    if not paths["root"].exists():
        raise HTTPException(status_code=404, detail="Project or Studio not found")

    status_file = paths["status_file"]
    with open(status_file, 'w') as f:
        json.dump({
            "percent": 0,
            "status": "Queued...",
            "timestamp": time.time()
        }, f)
        
    background_tasks.add_task(
        background_generate_music,
        req.project_name,
        req.tags,
        req.prompt,
        req.cookies
    )
    
    return {"status": "started"}

@router.get("/{project_name}/status")
async def get_generation_status(project_name: str):
    """
    Polls the status of the current music generation.
    """
    status_file = _music_paths(project_name)["status_file"]
    
    if not status_file.exists():
        return {"percent": -1, "status": "not_started"}
        
    try:
        with open(status_file, 'r') as f:
            data = json.load(f)
            
        # Cleanup status file when done
        if data.get("percent", 0) >= 100 or data.get("percent", 0) == -1:
            status_file.unlink(missing_ok=True)
            
        return data
    except Exception:
        return {"percent": -1, "status": "unknown"}


@router.get("/studio/tracks")
async def list_studio_music_tracks():
    music_dir = manager.studio_path / "music"
    if not music_dir.exists():
        return []

    index_by_name = {}
    index_file = music_dir / "studio_music_index.json"
    if index_file.exists():
        try:
            with open(index_file, "r") as f:
                for item in json.load(f):
                    if isinstance(item, dict) and item.get("filename"):
                        index_by_name[item["filename"]] = item
        except Exception:
            index_by_name = {}

    files = []
    for f in music_dir.iterdir():
        if f.is_file() and f.suffix.lower() in [".mp3", ".wav", ".m4a", ".flac", ".ogg"]:
            meta = index_by_name.get(f.name, {})
            files.append({
                "filename": f.name,
                "path": str(f.absolute()),
                "size": f.stat().st_size,
                "created_at": meta.get("created_at") or os.path.getmtime(f),
                "tags": meta.get("tags", ""),
                "prompt": meta.get("prompt", ""),
            })
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return files


@router.get("/studio/tracks/{filename}/play")
async def play_studio_music_track(filename: str):
    music_path = manager.studio_path / "music" / filename
    if not music_path.exists():
        raise HTTPException(status_code=404, detail="Music file not found")

    ext = music_path.suffix.lower()
    media_types = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".flac": "audio/flac", ".ogg": "audio/ogg"}
    return FileResponse(str(music_path), media_type=media_types.get(ext, "audio/mpeg"))


@router.delete("/studio/tracks/{filename}")
async def delete_studio_music_track(filename: str):
    music_path = manager.studio_path / "music" / filename
    if not music_path.exists():
        raise HTTPException(status_code=404, detail="Music file not found")
    music_path.unlink()
    return {"status": "deleted"}


from fastapi import UploadFile, File
from fastapi.responses import FileResponse

@router.post("/upload")
async def upload_music(project_name: str, file: UploadFile = File(...)):
    """
    Upload an MP3/WAV file as the project's background music track.
    """
    project_dir = manager.projects_path / project_name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    
    music_dir = project_dir / "music"
    music_dir.mkdir(exist_ok=True, parents=True)
    
    # Clean filename
    ext = Path(file.filename).suffix.lower() if file.filename else ".mp3"
    if ext not in [".mp3", ".wav", ".m4a", ".flac", ".ogg"]:
        raise HTTPException(status_code=400, detail="Unsupported audio format")
    
    safe_name = "".join([c if c.isalnum() or c in "._-" else "_" for c in Path(file.filename).stem[:30]])
    filename = f"upload_{int(time.time())}_{safe_name}{ext}"
    save_path = music_dir / filename
    
    # Write file
    content = await file.read()
    with open(save_path, 'wb') as f:
        f.write(content)
    
    # Register in project metadata
    manager.save_music_track(project_name, filename)
    
    logger.info(f"🎵 Music uploaded for project '{project_name}': {filename} ({len(content)} bytes)")
    return {"status": "ok", "filename": filename}


@router.get("/{project_name}/play")
async def play_music(project_name: str):
    """
    Stream the project's music file for in-browser playback.
    """
    project_dir = manager.projects_path / project_name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get music filename from project meta
    meta_path = project_dir / "project_meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="No project metadata")
    
    with open(meta_path, 'r') as f:
        meta = json.load(f)
    
    music_filename = meta.get("music_track")
    if not music_filename:
        raise HTTPException(status_code=404, detail="No music track set")
    
    music_path = project_dir / "music" / music_filename
    if not music_path.exists():
        raise HTTPException(status_code=404, detail="Music file not found")
    
    # Determine media type
    ext = music_path.suffix.lower()
    media_types = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".flac": "audio/flac", ".ogg": "audio/ogg"}
    media_type = media_types.get(ext, "audio/mpeg")
    
    return FileResponse(str(music_path), media_type=media_type)
