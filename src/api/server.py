import asyncio
import logging
import json
import time
import os
import tempfile
from typing import Optional
import queue # Синхронная очередь
from pydantic import BaseModel
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import yaml
from dotenv import load_dotenv

from src.project_manager import ProjectManager
from src.api.models import IngestRequest, ProjectCreateRequest, ProjectCreateFromStudioRequest, EpisodeCreateRequest, EpisodeUpdateRequest, GroupCreateRequest, GroupUpdateRequest, AutoTimelinePlanRequest

# ...


from src.utils.app_paths import ensure_app_structure, get_library_path
from src.utils.tmdb_client import TMDBClient
from src.api.translate import router as translate_router
from src.api.tts import router as tts_router
from src.api.brainstorm import router as brainstorm_router
from src.api.music_gen import router as music_router
from src.api.youtube_trends import router as youtube_router

# === ГЛОБАЛЬНАЯ ОЧЕРЕДЬ ===
msg_queue = queue.Queue()
active_websockets = set()

async def broadcast_messages():
    """Background task to broadcast messages to all connected WebSockets."""
    while True:
        while not msg_queue.empty():
            try:
                msg = msg_queue.get_nowait()
                dead = set()
                for ws in active_websockets:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                active_websockets.difference_update(dead)
            except queue.Empty:
                break
        await asyncio.sleep(0.1)



# === ЛОГИРОВАНИЕ ===
class QueueHandler(logging.Handler):
    def emit(self, record):
        try:
            entry = json.dumps({
                "type": "log",
                "message": self.format(record),
                "level": record.levelname
            })
            msg_queue.put(entry)
        except:
            pass

logger = logging.getLogger()
logger.setLevel(logging.INFO)
queue_handler = QueueHandler()
formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s')
queue_handler.setFormatter(formatter)
logger.addHandler(queue_handler)

# === ИНИЦИАЛИЗАЦИЯ ===
# Инициализируем структуру папок в документах
app_root = ensure_app_structure()
logger.info(f"📂 App Data Directory: {app_root}")

manager = ProjectManager()

tmdb_key = os.getenv("TMDB_API_KEY") or manager.config.get("api_keys", {}).get("tmdb")
tmdb_client = TMDBClient(tmdb_key) if tmdb_key else None

app = FastAPI(title="Sculptor AI Backend")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_messages())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/images", StaticFiles(directory=get_library_path()), name="images")

# === TRANSLATE ROUTER ===
app.include_router(translate_router, prefix="/translate", tags=["translate"])

# === TTS ROUTER ===
from src.api.tts import router as tts_router
app.include_router(tts_router, prefix="/tts", tags=["tts"])

# === SHORTS ROUTER ===
from src.shorts.router import router as shorts_router
app.include_router(shorts_router, prefix="/shorts", tags=["shorts"])
app.include_router(brainstorm_router, prefix="/brainstorm", tags=["brainstorm"])

# === MUSIC ROUTER ===
app.include_router(music_router, prefix="/music", tags=["music"])

# === YOUTUBE TRENDS ROUTER ===
app.include_router(youtube_router, prefix="/youtube", tags=["youtube"])

# Mount shorts static files for thumbnails/clips
from pathlib import Path as _Path
_shorts_dir = _Path(__file__).resolve().parent.parent.parent / "_shorts"
_shorts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/shorts_static", StaticFiles(directory=str(_shorts_dir)), name="shorts_static")

# === ENDPOINTS ===

# === ЭПИЗОДЫ (MANUAL SEGMENTATION) ===

class LocateRequest(BaseModel):
    new_path: str

@app.get("/library/{alias}/details")
def get_source_details(alias: str):
    details = manager.get_source_details(alias)
    if not details:
        return {"error": "Source not found"}, 404
    return details

@app.post("/library/{alias}/locate")
def locate_source(alias: str, req: LocateRequest):
    success = manager.update_source_path(alias, req.new_path)
    if not success:
        return {"error": "Failed to update"}, 400
    return {"status": "updated", "path": req.new_path}

@app.get("/library/{alias}/episodes")
def get_episodes(alias: str):
    eps = manager.get_episodes(alias)
    if eps is None:
        return {"error": "Source not found"}, 404
    return eps

@app.post("/library/{alias}/episodes")
def add_episode(alias: str, req: EpisodeCreateRequest):
    new_ep = manager.add_episode(alias, req.name, req.start_time, req.end_time)
    if not new_ep:
        return {"error": "Source not found"}, 404
    return new_ep

@app.put("/library/{alias}/episodes/{ep_id}")
def update_episode(alias: str, ep_id: str, req: EpisodeUpdateRequest):
    updated = manager.update_episode(alias, ep_id, req.name, req.start_time, req.end_time)
    if not updated:
        return {"error": "Episode not found"}, 404
    return updated

@app.delete("/library/{alias}/episodes/{ep_id}")
def delete_episode(alias: str, ep_id: str):
    success = manager.delete_episode(alias, ep_id)
    if not success:
        return {"error": "Not found"}, 404
    return {"status": "deleted"}

@app.get("/library/{alias}/characters")
def get_characters(alias: str):
    chars = manager.get_characters(alias)
    return chars


# === AUTO-EPISODE SEGMENTATION (AI) ===

class AutoEpisodeRequest(BaseModel):
    force: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None

@app.post("/library/{alias}/auto-episodes")
async def auto_generate_episodes(alias: str, background_tasks: BackgroundTasks, req: AutoEpisodeRequest = None):
    """Triggers AI-powered automatic episode segmentation for a source."""
    logger.info(f"🤖 API Request: Auto-segmenting episodes for '{alias}'...")

    force = req.force if req else False

    # Status file for polling (reliable, no queue race conditions)
    status_file = manager.library_path / alias / ".auto_seg_status.json"

    def progress_report(percent, status):
        try:
            status_data = {
                "percent": percent,
                "status": status,
                "alias": alias,
                "task": "auto_episodes",
                "timestamp": time.time()
            }
            with open(status_file, 'w') as f:
                json.dump(status_data, f)
        except Exception as e:
            logger.warning(f"Failed to write status file: {e}")

    # Write initial status
    progress_report(0, "Starting...")

    background_tasks.add_task(
        manager.auto_generate_episodes,
        alias,
        progress_report,
        force,
        req.start_time if req else None,
        req.end_time if req else None,
    )
    return {"status": "started", "task": f"Auto-segment episodes for {alias}"}


@app.get("/library/{alias}/auto-episodes/status")
async def get_auto_episodes_status(alias: str):
    """Poll auto-segmentation progress."""
    status_file = manager.library_path / alias / ".auto_seg_status.json"
    if not status_file.exists():
        return {"percent": -1, "status": "not_started"}
    try:
        with open(status_file, 'r') as f:
            data = json.load(f)
        # Cleanup status file when done
        if data.get("percent", 0) >= 100 or data.get("status", "").startswith("Error"):
            status_file.unlink(missing_ok=True)
        return data
    except Exception:
        return {"percent": -1, "status": "unknown"}


# === DECISION ANALYSIS ===

class DecisionAnalysisRequest(BaseModel):
    character: str
    goal: str

@app.post("/library/{alias}/decisions/analyze")
def analyze_decisions(alias: str, req: DecisionAnalysisRequest):
    try:
        result = manager.analyze_decisions(alias, req.character, req.goal)
        return result
    except FileNotFoundError:
        return {"error": "Episodes not found"}, 404
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {"error": str(e)}, 500

@app.get("/library/{alias}/decisions")
def get_decisions_list(alias: str):
    """Get list of available decision analyses."""
    try:
        return manager.get_decision_analyses(alias)
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/library/{alias}/decisions/{analysis_id}")
def get_decision_detail(alias: str, analysis_id: str):
    """Get content of a specific analysis."""
    try:
        return manager.get_decision_analysis(alias, analysis_id)
    except FileNotFoundError:
        return {"error": "Analysis not found"}, 404
    except Exception as e:
        return {"error": str(e)}, 500

# === SCREENPLAY ===

@app.post("/library/{alias}/screenplay")
async def upload_screenplay(alias: str, file: UploadFile = File(...)):
    """Upload a screenplay/script file (.txt or .pdf) for script-based decision analysis."""
    try:
        content = await file.read()
        ext = os.path.splitext(file.filename or "")[1].lower()

        if ext == ".pdf":
            import fitz  # pymupdf
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                doc = fitz.open(tmp_path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            finally:
                os.unlink(tmp_path)
            if not text.strip():
                return {"error": "PDF contains no extractable text (scanned/image-only PDF?)"}, 400
        elif ext == ".txt" or not ext:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                return {"error": "File must be a UTF-8 text file (.txt)"}, 400
        else:
            return {"error": f"Unsupported file type: {ext}. Use .txt or .pdf"}, 400

        result = manager.upload_screenplay(alias, text, file.filename)
        return result
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        logger.error(f"Screenplay upload failed: {e}")
        return {"error": str(e)}, 500

@app.delete("/library/{alias}/screenplay")
def delete_screenplay(alias: str):
    """Remove uploaded screenplay."""
    try:
        return manager.delete_screenplay(alias)
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/library/{alias}/screenplay/status")
def get_screenplay_status(alias: str):
    """Check if screenplay exists and return preview."""
    try:
        return manager.get_screenplay_status(alias)
    except Exception as e:
        return {"error": str(e)}, 500


@app.get("/status")
def health_check():
    lib_path = manager.library_path
    lib_count = len(list(lib_path.glob("*"))) if lib_path.exists() else 0
    return {"status": "running", "library_count": lib_count}

@app.get("/library")
def get_library():
    movies = []
    lib_path = manager.library_path
    
    if lib_path.exists():
        for folder in lib_path.iterdir():
            if folder.is_dir() and not folder.name.startswith('.'):
                master_index_path = folder / "master_index.json"
                status_file = folder / ".ingest_status.json"  # <--- НОВОЕ
                has_index = master_index_path.exists()
                
                # === ЧИТАЕМ СТАТУС ОБРАБОТКИ ===
                ingest_status = None
                if status_file.exists():
                    try:
                        with open(status_file, 'r') as f:
                            ingest_status = json.load(f)
                    except: pass
                
                # TMDB Logic (оставляем как было)
                thumbnail_url = None
                cache_file = folder / ".tmdb_cache"
                
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r') as f:
                            thumbnail_url = f.read().strip()
                    except: pass
                
                if not thumbnail_url and tmdb_client:
                    search_query = folder.name
                    if has_index:
                        try:
                            with open(master_index_path, 'r') as f:
                                meta = json.load(f)
                                search_query = meta.get("movie_name", folder.name)
                        except: pass
                    
                    try:
                        found_poster = tmdb_client.get_poster_url(search_query)
                        if found_poster:
                            thumbnail_url = found_poster
                            with open(cache_file, 'w') as f:
                                f.write(thumbnail_url)
                    except: pass
                
                if not thumbnail_url:
                    faces_dir = folder / "faces"
                    if faces_dir.exists():
                        images = list(faces_dir.glob("*.jpg"))
                        if images:
                            target_img = images[min(5, len(images)-1)]
                            thumbnail_url = f"http://localhost:8000/images/{folder.name}/faces/{target_img.name}"

                # === ФОРМИРУЕМ ОТВЕТ ===
                movie_data = {
                    "alias": folder.name,
                    "ready": has_index,
                    "path": str(folder.absolute()),
                    "thumbnail": thumbnail_url
                }
                
                # Добавляем статус обработки, если он есть
                if ingest_status:
                    movie_data["ingest_status"] = ingest_status.get("status", "unknown")
                    movie_data["percent"] = ingest_status.get("percent", 0)
                    movie_data["progress_text"] = ingest_status.get("progress_text", "")
                
                movies.append(movie_data)
    
    return movies

# === ВОТ ЭТИ ЭНДПОИНТЫ БЫЛИ ПОТЕРЯНЫ ===
@app.get("/projects")
def get_projects():
    projs = []
    proj_path = manager.projects_path
    
    # Создаем папку projects если её нет
    if not proj_path.exists():
        proj_path.mkdir(parents=True, exist_ok=True)

    if proj_path.exists():
        for folder in proj_path.iterdir():
            if folder.is_dir() and not folder.name.startswith('.'):
                projs.append({
                    "name": folder.name, 
                    "path": str(folder.absolute()),
                    "project_type": "segmented"
                })
    return projs

@app.get("/projects/{name}")
def get_project_details(name: str):
    details = manager.get_project_details(name)
    if not details:
        return {"error": "Project not found"}
    return details

@app.post("/projects/create")
def create_project(req: ProjectCreateRequest):
    manager.create_project(req.name, req.matching_mode)
    return {"status": "created", "name": req.name, "mode": req.matching_mode, "type": "segmented"}

@app.post("/projects/create_from_studio")
def create_project_from_studio(req: ProjectCreateFromStudioRequest):
    try:
        result = manager.create_project_from_studio(req.name, req.matching_mode, req.audio_filename)
        return result
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        logger.error(f"Error creating project from studio: {e}")
        return {"error": str(e)}, 500

# === STUDIO ENDPOINTS ===
@app.get("/studio/audio")
def get_studio_audio():
    """Lists all audio files in the global Studio folder."""
    studio_dir = manager.studio_path / "audio"
    if not studio_dir.exists():
        return []
        
    files = []
    for f in studio_dir.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            files.append({
                "filename": f.name,
                "path": str(f.absolute()),
                "size": f.stat().st_size
            })
    # Sort files by creation time inside the map or directly if OS supports, otherwise we just return them.
    files.sort(key=lambda x: os.path.getmtime(x["path"]), reverse=True)
    return files

@app.post("/studio/audio")
async def upload_studio_audio(custom_filename: str = None, variant: str = None, file: UploadFile = File(...)):
    """Uploads an audio file directly to the Studio 'audio' folder."""
    try:
        studio_dir = manager.studio_path / "audio"
        studio_dir.mkdir(parents=True, exist_ok=True)
        
        if custom_filename:
             if not custom_filename.lower().endswith('.wav'):
                 custom_filename += ".wav"
             new_filename = custom_filename
             file_path = studio_dir / new_filename
        else:
            # Basic numbering
            import re
            pattern = re.compile(rf"^Studio-(\d+)(?:-([a-zA-Z0-9]+))?\.wav$")
            max_index = 0
            existing_files = list(studio_dir.glob("Studio-*.wav"))
            for f in existing_files:
                match = pattern.match(f.name)
                if match:
                    try:
                        idx = int(match.group(1))
                        if idx > max_index:
                            max_index = idx
                    except: pass
            
            new_index = max_index + 1
            suffix = f"-{variant}" if variant else ""
            new_filename = f"Studio-{new_index}{suffix}.wav"
            file_path = studio_dir / new_filename
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        return {"status": "uploaded", "path": str(file_path), "filename": new_filename}
    except Exception as e:
        logger.error(f"Failed to upload studio audio: {e}")
        return {"error": str(e)}, 500

@app.delete("/studio/audio/{filename}")
def delete_studio_audio(filename: str):
    """Deletes a specific audio file from the Studio folder."""
    file_path = manager.studio_path / "audio" / filename
    if not file_path.exists():
        return {"error": "File not found"}, 404
        
    try:
        file_path.unlink()
        return {"status": "deleted"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/studio/audio/{filename}/play")
def play_studio_audio(filename: str):
    """Plays an audio file from the Studio folder mapping directly or transcoded for browser."""
    audio_path = manager.studio_path / "audio" / filename
        
    if not audio_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    serve_path = audio_path
    if audio_path.suffix.lower() == '.wav':
        safe_wav_path = audio_path.parent / f".{audio_path.stem}.browser.wav"
        if not safe_wav_path.exists():
            import subprocess
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(audio_path),
                    "-acodec", "pcm_s16le", str(safe_wav_path)
                ], capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg transcoding failed: {e.stderr.decode()}")
            except Exception as e:
                logger.error(f"FFmpeg execution failed: {e}")
        
        if safe_wav_path.exists():
            serve_path = safe_wav_path

    import mimetypes
    mime_type, _ = mimetypes.guess_type(str(serve_path))
    if mime_type is None:
        mime_type = "application/octet-stream"
        
    return FileResponse(str(serve_path), media_type=mime_type)

from src.api.models import SegmentedTimelineSaveRequest
from fastapi import HTTPException

@app.post("/projects/{name}/audio/transcribe")
def transcribe_project_audio(name: str):
    try:
        res = manager.transcribe_project_audio(name)
        return {"status": "success", "transcript": res}
    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects/{name}/transcript")
def get_project_transcript(name: str):
    try:
        return manager.get_project_transcript(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/projects/{name}/segmented_timeline")
def save_segmented_timeline(name: str, req: SegmentedTimelineSaveRequest):
    try:
        # Backward compatibility for Pydantic V1/V2
        items_dict = [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in req.items]
        manager.save_segmented_timeline(name, items_dict)
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/projects/{name}/segmented_timeline/auto_plan")
def auto_plan_segmented_timeline(name: str, req: AutoTimelinePlanRequest):
    try:
        model_id = None
        if req.model:
            from src.utils.gemini_client import AVAILABLE_MODELS
            model_info = AVAILABLE_MODELS.get(req.model)
            if model_info:
                model_id = model_info["id"]
            else:
                logger.warning(f"⚠️ Unknown model key '{req.model}', using default")

        result = manager.auto_plan_segmented_timeline(
            project_name=name,
            script_text=req.script_text,
            source_aliases=req.source_aliases,
            group_ids=req.group_ids or [],
            model_name=model_id,
            save=req.save,
        )
        return {"status": "planned", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Auto timeline planning failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# === TIMELINE ENDPOINTS ===
from src.api.models import TrackAddRequest

@app.post("/projects/{name}/tracks")
def add_track(name: str, req: TrackAddRequest):
    track = manager.add_track(
        name, req.audio_path, req.source_alias,
        req.episode_ids, req.episode_names,
        req.segmentation_mode, req.character_names
    )
    if not track:
        return {"error": "Failed to add track"}, 400
    return track

@app.delete("/projects/{name}/tracks/{track_id}")
def remove_track(name: str, track_id: str):
    success = manager.remove_track(name, track_id)
    if not success:
        return {"error": "Track not found"}, 404
    return {"status": "deleted"}

from src.api.models import TrackUpdateRequest

@app.put("/projects/{name}/tracks/{track_id}")
def update_track(name: str, track_id: str, req: TrackUpdateRequest):
    success = manager.update_track(
        name, track_id, req.episode_ids, req.episode_names,
        req.segmentation_mode, req.character_names
    )
    if not success:
        return {"error": "Track not found"}, 404
    return {"status": "updated"}


# === AUDIO MANAGEMENT ENDPOINTS ===
@app.post("/projects/{name}/audio")
async def upload_project_audio(name: str, custom_filename: str = None, variant: str = None, file: UploadFile = File(...)):
    """Uploads an audio file directly to the project's 'audio' folder."""
    try:
        project_path = manager.projects_path / name
        if not project_path.exists():
            return {"error": "Project not found"}, 404
        
        audio_dir = project_path / "audio"
        audio_dir.mkdir(exist_ok=True)
        
        if custom_filename:
             # Use provided custom filename (e.g. Test1_Eng.wav)
             # Ensure it ends with .wav if not provided
             if not custom_filename.lower().endswith('.wav'):
                 custom_filename += ".wav"
             new_filename = custom_filename
             file_path = audio_dir / new_filename
        else:
            # Sequential Naming Logic
            # Pattern: {ProjectName}-{Index}{-Eng?}.wav
            # Find max index by regex to handle suffixes
            import re
            pattern = re.compile(rf"^{re.escape(name)}-(\d+)(?:-([a-zA-Z0-9]+))?\.wav$")
            
            max_index = 0
            existing_files = list(audio_dir.glob(f"{name}-*.wav"))
            
            for f in existing_files:
                match = pattern.match(f.name)
                if match:
                    try:
                        idx = int(match.group(1))
                        if idx > max_index:
                            max_index = idx
                    except: pass
            
            new_index = max_index + 1
            suffix = "-Eng" if variant == "ENG" else ""
            new_filename = f"{name}-{new_index}{suffix}.wav"
            file_path = audio_dir / new_filename
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        return {"status": "uploaded", "path": str(file_path), "filename": new_filename}
    except Exception as e:
        logger.error(f"Failed to upload audio: {e}")
        return {"error": str(e)}, 500

@app.post("/projects/{name}/input")
async def upload_project_input_audio(name: str, file: UploadFile = File(...)):
    """Uploads an audio file directly to the project's 'input' folder (for Segmented projects)."""
    try:
        project_path = manager.projects_path / name
        if not project_path.exists():
            return {"error": "Project not found"}, 404
        
        input_dir = project_path / "input"
        input_dir.mkdir(exist_ok=True)
        
        filename = file.filename
        if not filename.lower().endswith('.wav') and not filename.lower().endswith('.mp3'):
             filename += ".wav"
             
        file_path = input_dir / filename
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        return {"status": "uploaded", "path": str(file_path), "filename": filename}
    except Exception as e:
        logger.error(f"Failed to upload input audio: {e}")
        return {"error": str(e)}, 500


class OpenPathRequest(BaseModel):
    path: str

@app.get("/system/paths")
def get_system_paths():
    return {
        "app_root": str(app_root),
        "library": str(manager.library_path),
        "projects": str(manager.projects_path),
        "studio": str(manager.studio_path),
    }

@app.post("/system/open_path")
def open_system_path(req: OpenPathRequest):
    import subprocess
    import platform
    
    path = req.path
    if not Path(path).exists():
        return {"error": "Path not found"}, 404
        
    try:
        system = platform.system()
        if system == "Darwin":  # macOS
            subprocess.call(["open", path])
        elif system == "Windows":
            subprocess.call(["explorer", path])
        elif system == "Linux":
            subprocess.call(["xdg-open", path])
        return {"status": "opened", "path": path}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/projects/{name}/audio")
def get_project_audio(name: str):
    """Lists all audio files in the project's 'audio' folder."""
    project_path = manager.projects_path / name
    if not project_path.exists():
        return {"error": "Project not found"}, 404
        
    audio_dir = project_path / "audio"
    if not audio_dir.exists():
        return []
        
    files = []
    for f in audio_dir.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            files.append({
                "filename": f.name,
                "path": str(f.absolute()),
                "size": f.stat().st_size
            })
    return files


@app.get("/projects/{name}/audio/{filename}/play")
def play_project_audio(name: str, filename: str):
    project_dir = manager.projects_path / name
    
    # Try input dir first (standard), then audio dir (studio recordings)
    audio_path = project_dir / "input" / filename
    if not audio_path.exists():
        audio_path = project_dir / "audio" / filename
        
    if not audio_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    serve_path = audio_path
    if audio_path.suffix.lower() == '.wav':
        safe_wav_path = audio_path.parent / f".{audio_path.stem}.browser.wav"
        if not safe_wav_path.exists():
            import subprocess
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(audio_path),
                    "-acodec", "pcm_s16le", str(safe_wav_path)
                ], capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg transcoding failed: {e.stderr.decode()}")
            except Exception as e:
                logger.error(f"FFmpeg execution failed: {e}")
        
        if safe_wav_path.exists():
            serve_path = safe_wav_path

    import mimetypes
    mime_type, _ = mimetypes.guess_type(str(serve_path))
    if mime_type is None:
        mime_type = "application/octet-stream"
        
    return FileResponse(str(serve_path), media_type=mime_type)

@app.get("/projects/{name}/audio/{filename}/peaks")
def get_audio_peaks(name: str, filename: str, num_peaks: int = 500):
    """Pre-compute waveform peaks using ffmpeg to support all formats (float WAV, mp3, mp4)."""
    project_dir = manager.projects_path / name
    
    audio_path = project_dir / "input" / filename
    if not audio_path.exists():
        audio_path = project_dir / "audio" / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    cache_path = audio_path.parent / f".{audio_path.stem}.peaks.json"
    if cache_path.exists():
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            if cached.get("source_size") == audio_path.stat().st_size:
                return cached
        except Exception:
            pass
    
    import subprocess
    import struct
    import math
    
    try:
        # Get duration first using ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        duration = float(probe_res.stdout.strip())
        
        # Decode audio to raw 16-bit PCM mono at 8000Hz via stdout pipe
        sample_rate = 8000
        cmd = [
            "ffmpeg", "-i", str(audio_path),
            "-ac", "1", "-ar", str(sample_rate),
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-"
        ]
        res = subprocess.run(cmd, capture_output=True, check=True)
        raw_data = res.stdout
        
        # Unpack raw 16-bit little-endian samples
        n_samples = len(raw_data) // 2
        samples = struct.unpack(f"<{n_samples}h", raw_data)
        
        # Compute local max peaks
        chunk_size = max(1, n_samples // num_peaks)
        peaks = []
        
        for i in range(0, n_samples, chunk_size):
            chunk = samples[i:i + chunk_size]
            if chunk:
                peak = max(abs(min(chunk)), abs(max(chunk)))
                peaks.append(peak)
                
        # Normalize to 0.0 - 1.0
        max_val = max(peaks) if peaks else 1
        max_val = max_val or 1
        peaks = [round(p / max_val, 4) for p in peaks]
        
        result = {
            "peaks": peaks,
            "duration": duration,
            "source_size": audio_path.stat().st_size,
        }
        
        try:
            with open(cache_path, 'w') as f:
                json.dump(result, f)
        except Exception:
            pass
            
        return result
        
    except Exception as e:
        logger.error(f"Failed to generate peaks for {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/projects/{name}/audio/{filename}")
def delete_project_audio(name: str, filename: str):
    """Deletes a specific audio file from the project."""
    project_path = manager.projects_path / name
    if not project_path.exists():
        return {"error": "Project not found"}, 404
    
    file_path = project_path / "audio" / filename
    if not file_path.exists():
        return {"error": "File not found"}, 404
        
    try:
        file_path.unlink()
        return {"status": "deleted"}
    except Exception as e:
        return {"error": str(e)}, 500

class RenameAudioRequest(BaseModel):
    new_name: str

@app.put("/projects/{name}/audio/{filename}/rename")
def rename_project_audio(name: str, filename: str, req: RenameAudioRequest):
    """Renames a specific audio file in the project."""
    project_path = manager.projects_path / name
    if not project_path.exists():
        return {"error": "Project not found"}, 404
    
    audio_dir = project_path / "audio"
    file_path = audio_dir / filename
    if not file_path.exists():
        return {"error": "File not found"}, 404
    
    # Ensure new name implies .wav if missing
    new_name = req.new_name
    if not new_name.lower().endswith('.wav'):
        new_name += ".wav"
        
    new_path = audio_dir / new_name
    
    if new_path.exists():
        return {"error": "File with new name already exists"}, 400
        
    try:
        file_path.rename(new_path)
        return {"status": "renamed", "new_name": new_name}
    except Exception as e:
        return {"error": str(e)}, 500

class BuildSegmentedRequest(BaseModel):
    model: Optional[str] = None

@app.get("/models")
def get_available_models():
    """Returns list of available Gemini models for UI dropdown."""
    from src.utils.gemini_client import AVAILABLE_MODELS, DEFAULT_MODEL_KEY
    models = []
    for key, info in AVAILABLE_MODELS.items():
        models.append({
            "key": key,
            "id": info["id"],
            "label": info["label"],
            "default": key == DEFAULT_MODEL_KEY
        })
    return models

@app.post("/projects/{name}/build_segmented")
async def build_segmented(name: str, background_tasks: BackgroundTasks, req: BuildSegmentedRequest = None):
    model_id = None
    if req and req.model:
        from src.utils.gemini_client import AVAILABLE_MODELS
        model_info = AVAILABLE_MODELS.get(req.model)
        if model_info:
            model_id = model_info["id"]
            logger.info(f"🚀 API Request: Segmented Build for {name} with model {req.model} ({model_id})")
        else:
            logger.warning(f"⚠️ Unknown model key '{req.model}', using default")
            logger.info(f"🚀 API Request: Segmented Build for {name}...")
    else:
        logger.info(f"🚀 API Request: Segmented Build for {name}...")
    
    def progress_report(percent, status):
        """Handle both legacy string status and extended dict format."""
        if isinstance(status, dict):
            msg = json.dumps({
                "type": "progress",
                "alias": name,
                "percent": percent,
                "status": status.get("text", ""),
                "step": status.get("step"),
                "current_track": status.get("current_track"),
                "total_tracks": status.get("total_tracks"),
                "track_name": status.get("track_name")
            })
        else:
            msg = json.dumps({
                "type": "progress",
                "alias": name,
                "percent": percent,
                "status": status
            })
        msg_queue.put(msg)
    background_tasks.add_task(
        manager.build_segmented_timeline_project,
        name,
        progress_report,
        model_id
    )
    return {"status": "started", "task": f"Build Segmented {name}"}
# ========================================

@app.post("/ingest")
async def run_ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    logger.info(f"🚀 API Request: Ingesting {req.alias}...")
    
    def progress_report(percent, status):
        msg = json.dumps({
            "type": "progress",
            "alias": req.alias,
            "percent": percent,
            "status": status
        })
        msg_queue.put(msg)

    background_tasks.add_task(
        manager.ingest_source, 
        req.file_path, 
        req.alias, 
        req.fullname,
        progress_report
    )
    return {"status": "started", "task": f"Ingest {req.alias}"}



@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    try:
        while True:
            # Just keep the connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception as e:
        active_websockets.discard(websocket)

@app.delete("/library/{alias}")
def delete_library_item(alias: str):
    success = manager.delete_source_from_library(alias)
    if not success:
        return {"error": "Not found"}, 404
    return {"status": "deleted"}

@app.delete("/projects/{name}")
def delete_project_item(name: str):
    success = manager.delete_project(name)
    if not success:
        return {"error": "Not found"}, 404
    return {"status": "deleted"}

# === GROUPS ===

@app.get("/groups")
def list_groups():
    return manager.get_groups()

@app.get("/groups/{group_id}")
def get_group(group_id: str):
    group = manager.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group

@app.post("/groups")
def create_group(req: GroupCreateRequest):
    try:
        items = [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in req.items]
        group = manager.create_group(req.name, items)
        return group
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/groups/{group_id}")
def update_group(group_id: str, req: GroupUpdateRequest):
    try:
        items = None
        if req.items is not None:
            items = [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in req.items]
        group = manager.update_group(group_id, name=req.name, items=items)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/groups/{group_id}")
def delete_group(group_id: str):
    success = manager.delete_group(group_id)
    if not success:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "deleted"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
# Load local environment variables before wiring API clients.
load_dotenv()
