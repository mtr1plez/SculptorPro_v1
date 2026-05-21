"""
Audio Translate API endpoints.
Handles audio transcription (Whisper) and text translation (Gemini).
"""
import os
import tempfile
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from src.utils.gemini_client import GeminiClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

# === WHISPER MODEL (lazy load) ===
_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            import torch
            import whisper
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Whisper dependencies are not installed: {exc}",
            ) from exc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if torch.backends.mps.is_available():
            device = "cpu"  # MPS не поддерживается Whisper напрямую
        logger.info(f"🎙 Loading Whisper model (medium) on {device}...")
        _whisper_model = whisper.load_model("medium", device=device)
    return _whisper_model


# === GEMINI CONFIG ===
# Configuration is now handled internally by GeminiClient

# === MODELS ===
class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration: float


class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "ru"
    target_lang: str = "en"


class TranslateResponse(BaseModel):
    translated_text: str


# === ENDPOINTS ===

@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Транскрибирует загруженный аудио файл через Whisper.
    Поддерживает: MP3, WAV, M4A, FLAC, OGG
    """
    allowed_types = ["audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", 
                     "audio/x-m4a", "audio/flac", "audio/ogg", "video/mp4"]
    
    # Проверяем тип файла (или расширение, если MIME не определён)
    ext = Path(audio.filename).suffix.lower()
    allowed_ext = [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4"]
    
    if audio.content_type not in allowed_types and ext not in allowed_ext:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported audio format: {audio.content_type or ext}"
        )
    
    # Сохраняем во временный файл
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        logger.info(f"🎙 Transcribing uploaded audio: {audio.filename}")
        
        return _transcribe_file(tmp_path, cleanup=True)
        
    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ProjectAudioRequest(BaseModel):
    project_name: str
    filename: str

@router.post("/transcribe_project_audio", response_model=TranscribeResponse)
async def transcribe_project_audio(req: ProjectAudioRequest):
    """Transcribes an audio file existing in a project."""
    home = Path.home()
    projects_path = home / "Documents" / "SculptorPro" / "projects"
    
    file_path = projects_path / req.project_name / "audio" / req.filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    logger.info(f"🎙 Transcribing project audio: {file_path}")
    return _transcribe_file(str(file_path), cleanup=False)

class StudioAudioRequest(BaseModel):
    filename: str

@router.post("/transcribe_studio_audio", response_model=TranscribeResponse)
async def transcribe_studio_audio(req: StudioAudioRequest):
    """Transcribes an audio file existing in the Studio."""
    from src.utils.app_paths import get_studio_path
    
    file_path = get_studio_path() / "audio" / req.filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    logger.info(f"🎙 Transcribing studio audio: {file_path}")
    return _transcribe_file(str(file_path), cleanup=False)


def _transcribe_file(file_path: str, cleanup: bool = False):
    try:
        model = get_whisper_model()
        result = model.transcribe(file_path, fp16=False, task="transcribe")
        
        full_text = result.get("text", "").strip()
        language = result.get("language", "unknown")
        
        duration = 0.0
        if result.get("segments"):
            duration = result["segments"][-1].get("end", 0.0)
            
        return TranscribeResponse(
            text=full_text,
            language=language,
            duration=duration
        )
    finally:
        if cleanup and os.path.exists(file_path):
            os.unlink(file_path)


@router.post("/translate", response_model=TranslateResponse)
async def translate_text(req: TranslateRequest):
    """
    Переводит текст с одного языка на другой через Gemini API.
    """
    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(
            status_code=500, 
            detail="GOOGLE_API_KEY not configured in .env"
        )
    
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text provided")
    
    # Маппинг языков для промпта
    lang_names = {
        "ru": "Russian",
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "fr": "French",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean"
    }
    
    source_name = lang_names.get(req.source_lang, req.source_lang)
    target_name = lang_names.get(req.target_lang, req.target_lang)
    
    prompt = f"""Translate the following text from {source_name} to {target_name}.

IMPORTANT RULES:
- Keep the original meaning and tone
- Preserve punctuation and paragraph structure
- Do NOT add any explanations or notes
- Return ONLY the translated text

Text to translate:
{req.text}

Translation:"""

    try:
        logger.info(f"🌐 Translating {len(req.text)} chars: {source_name} → {target_name}")
        
        client = GeminiClient()
        response = client.generate_content(prompt)
        
        translated = response.text.strip()
        
        logger.info(f"✅ Translation complete: {len(translated)} chars")
        
        return TranslateResponse(translated_text=translated)
        
    except Exception as e:
        logger.error(f"❌ Translation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
