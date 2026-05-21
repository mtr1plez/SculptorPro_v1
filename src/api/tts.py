import logging
import os
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from src.utils.elevenlabs_client import ElevenLabsClient
from src.project_manager import ProjectManager

logger = logging.getLogger(__name__)
router = APIRouter()
manager = ProjectManager()

class VoicesRequest(BaseModel):
    api_key: str

class GenerateRequest(BaseModel):
    api_key: str
    text: str
    voice_id: str
    project_name: str
    filename: str = None # Optional custom filename

@router.post("/voices")
def get_voices(req: VoicesRequest):
    """
    Fetches available voices from ElevenLabs using the provided API key.
    """
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")
        
    try:
        client = ElevenLabsClient(req.api_key)
        voices = client.get_voices()
        return voices
    except Exception as e:
        logger.error(f"Error fetching voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/generate")
def generate_audio(req: GenerateRequest):
    """
    Generates audio via ElevenLabs and saves it to the project's audio folder.
    """
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")
    
    if req.project_name == "__STUDIO__":
        project_path = manager.studio_path
    else:
        project_path = manager.projects_path / req.project_name
        
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project or Studio not found")
        
    audio_dir = project_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine filename
    if req.filename:
        filename = req.filename
        if not filename.endswith(".mp3"):
            filename += ".mp3"
    else:
        # Sequential naming
        import re
        prefix = "Studio" if req.project_name == "__STUDIO__" else req.project_name
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)(?:-([a-zA-Z0-9]+))?\.mp3$")
        max_index = 0
        existing_files = list(audio_dir.glob(f"{prefix}-*.mp3"))
        
        for f in existing_files:
            match = pattern.match(f.name)
            if match:
                try:
                    idx = int(match.group(1))
                    if idx > max_index:
                        max_index = idx
                except: pass
        
        new_index = max_index + 1
        filename = f"{prefix}-{new_index}-TTS.mp3"
    
    file_path = audio_dir / filename
    
    try:
        client = ElevenLabsClient(req.api_key)
        audio_generator = client.generate_audio(req.text, req.voice_id)
        
        # Save audio
        with open(file_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)
                
        logger.info(f"✅ Generated TTS audio: {file_path}")
        
        return {
            "status": "generated",
            "filename": filename,
            "path": str(file_path)
        }
        
    except Exception as e:
        logger.error(f"Error generating audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))
