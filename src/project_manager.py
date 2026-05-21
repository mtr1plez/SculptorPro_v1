import os
import sys
import time
import yaml
import argparse
import json
import shutil
import logging
from pathlib import Path
from dotenv import load_dotenv

# Настройка путей проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.app_paths import get_config_path, get_library_path, get_projects_path, get_studio_path

load_dotenv()
from src.analysis.script_parser import ScriptParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MANAGER] - %(message)s'
)
logger = logging.getLogger(__name__)


class ProjectManager:
    """Управляет проектами видео-эссе и библиотекой источников."""
    
    def __init__(self):
        """
        Инициализация менеджера проектов.
        """
        self.config = self._load_config()
        self._setup_directories()

    def _load_config(self):
        """Загружает конфигурацию из config.yaml."""
        config_path = get_config_path()
        config = None
        
        if config_path.exists() and config_path.is_file():
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading config: {e}")

        if config is None:
            logger.warning(f"⚠️ Config not found at {config_path}. Using defaults.")
            config = {
            "models": {
                "whisper": "medium",
                "face_detection": "buffalo_l"
            },
            "paths": {
                "library": "_library",
                "projects": "projects"
            }
        }

        config.setdefault("models", {})
        config.setdefault("paths", {})
        config["api_keys"] = {
            **config.get("api_keys", {}),
            "tmdb": os.getenv("TMDB_API_KEY", config.get("api_keys", {}).get("tmdb")),
        }
        return config

    def _setup_directories(self):
        """Создает необходимые директории проекта."""
        self.library_path = get_library_path()
        self.projects_path = get_projects_path()
        self.studio_path = get_studio_path()
        
        # Директории создаются автоматически в get_*_path()

    def _ensure_dir(self, path):
        """Создает директорию, если её не существует."""
        if not path.exists():
            os.makedirs(path)
            logger.info(f"Created directory: {path}")

    # === КОМАНДА 1: СОЗДАНИЕ ПРОЕКТА ===
    
    def create_project(self, project_name, matching_mode="chaotic"):
        """
        Создает структуру папок для нового видео-эссе (всегда segmented).
        
        Args:
            project_name: Название проекта
            matching_mode: Режим матчинга ("chaotic" или "sequential")
        """
        project_dir = self.projects_path / project_name
        
        if project_dir.exists():
            logger.warning(f"Project '{project_name}' already exists.")
            return

        structure = ['input', 'artifacts', 'output']
        for folder in structure:
            self._ensure_dir(project_dir / folder)
            
        # Create initial meta
        meta = {
            "name": project_name,
            "matching_mode": matching_mode,
            "project_type": "segmented",
            "created_at": time.time(),
            "status": "idle"
        }
        meta_path = project_dir / "project_meta.json"
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        
        logger.info(f"✅ Project '{project_name}' initialized successfully with mode '{matching_mode}'.")
        logger.info(f"👉 Put your voiceover audio into: {project_dir}/input/")
        return project_dir

    def create_project_from_studio(self, project_name, matching_mode="chaotic", audio_filename=None):
        """
        Creates a new project and copies an audio file from the Studio folder into its input/.
        """
        if not audio_filename:
            raise ValueError("Audio filename is required")
            
        studio_audio_path = self.studio_path / "audio" / audio_filename
        if not studio_audio_path.exists():
            raise FileNotFoundError(f"Studio audio file not found: {audio_filename}")
            
        # Create standard project
        project_dir = self.create_project(project_name, matching_mode)
        if not project_dir and (self.projects_path / project_name).exists():
            project_dir = self.projects_path / project_name
            
        # Copy audio file
        dest_audio_path = project_dir / "input" / audio_filename
        shutil.copy2(studio_audio_path, dest_audio_path)
        
        logger.info(f"✅ Copied studio audio '{audio_filename}' to project '{project_name}'")
        return {"status": "created", "name": project_name, "mode": matching_mode, "type": "segmented"}

    # === КОМАНДА 2: ИНДЕКСАЦИЯ ИСТОЧНИКА ===
    
    def ingest_source(self, file_path, alias, fullname=None, progress_callback=None):
        """
        Индексирует видеофайл и добавляет его в библиотеку.
        
        Args:
            file_path: Путь к видеофайлу
            alias: Короткое имя для библиотеки
            fullname: Полное название фильма (опционально)
            progress_callback: Функция для отчета о прогрессе (percent, text)
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"Source file not found: {file_path}")
            return

        source_name = alias
        movie_real_name = fullname if fullname else alias
        target_dir = self.library_path / source_name
        status_file = target_dir / ".ingest_status.json"

        def save_ingest_state(status, percent=0, text=""):
            """Сохраняет состояние обработки в файл."""
            self._ensure_dir(target_dir)
            status_data = {
                "status": status,
                "percent": percent,
                "progress_text": text,
                "last_updated": time.time()
            }
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)

        def report(percent, text):
            """Отправляет прогресс в callback и сохраняет в файл."""
            if progress_callback:
                progress_callback(percent, text)
            save_ingest_state("processing", percent, text)

        # Начало обработки
        report(0, "Initializing...")
        
        try:
            from src.ingestion.scene_indexer import SceneIndexer
            from src.ingestion.flicker_fixer import FlickerFixer
            from src.ingestion.face_processor import FaceProcessor
            from src.ingestion.clip_encoder import ClipEncoder
            from src.ingestion.metadata_manager import MetadataManager

            logger.info(f"🚀 Starting ingestion for '{movie_real_name}'...")

            # STEP 1: Детекция сцен
            report(10, "Detecting Scenes...")
            indexer = SceneIndexer(file_path, target_dir)
            indexer.process()

            # STEP 1.5: Исправление мерцаний
            report(25, "Fixing Flickers...")
            try:
                fixer = FlickerFixer(target_dir)
                fixer.fix(offset=0.2)
            except Exception as e:
                logger.warning(f"Flicker Fixer skipped/failed: {e}")

            # STEP 2: Детекция лиц
            report(30, "Scanning Faces (This takes time)...")
            fp = FaceProcessor(target_dir)
            fp.process_faces()

            # STEP 3: CLIP эмбеддинги
            report(80, "Building Index...")
            try:
                logger.info("🎨 Generating CLIP embeddings...")
                clip_model = self.config.get("models", {}).get("clip", "ViT-B/32")
                clip_encoder = ClipEncoder(target_dir, model_name=clip_model)
                clip_encoder.process_embeddings()
            except Exception as e:
                logger.error(f"Failed during CLIP encoding: {e}")
                save_ingest_state("failed", 0, "Error occurred")
                if progress_callback:
                    progress_callback(0, "Error occurred")
                return

            # STEP 4: Агрегация метаданных
            report(90, "Building Index...")
            try:
                logger.info(f"🧠 Linking everything together for '{movie_real_name}'...")
                meta = MetadataManager(
                    target_dir,
                    movie_name=movie_real_name,
                    source_video_path=file_path
                )
                meta.build_master_index()
            except Exception as e:
                logger.error(f"Failed during metadata aggregation: {e}")
                save_ingest_state("failed", 0, "Error occurred")
                if progress_callback:
                    progress_callback(0, "Error occurred")
                return

            # Завершение
            save_ingest_state("ready", 100, "Ready")
            if progress_callback:
                progress_callback(100, "Ready")
            logger.info(f"🎉 Source '{source_name}' is FULLY INDEXED inside library.")
            
        except Exception as e:
            logger.error(f"❌ INGEST FAILED: {e}")
            save_ingest_state("failed", 0, f"Error: {str(e)}")
            if progress_callback:
                progress_callback(0, f"Error: {str(e)}")

    # === ПОЛУЧЕНИЕ ИНФОРМАЦИИ О ПРОЕКТЕ ===
    
    def get_project_details(self, project_name):
        """
        Возвращает детали проекта.
        
        Args:
            project_name: Название проекта
            
        Returns:
            dict: Информация о проекте или None
        """
        project_dir = self.projects_path / project_name
        if not project_dir.exists():
            return None
            
        input_dir = project_dir / "input"
        meta_path = project_dir / "project_meta.json"
        
        # Проверяем наличие аудио
        audio_exists = False
        audio_filename = None
        if input_dir.exists():
            audio_files = [
                f.name for f in input_dir.glob("*.*")
                if f.suffix.lower() in ['.mp3', '.wav', '.m4a']
            ]
            if not audio_files and (project_dir / "audio").exists():
                audio_files = [
                    f.name for f in (project_dir / "audio").glob("*.*")
                    if f.suffix.lower() in ['.mp3', '.wav', '.m4a']
                ]
            audio_exists = len(audio_files) > 0
            if audio_exists:
                audio_filename = audio_files[0]

        # Читаем метаданные
        meta = {}
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
            except Exception:
                pass

        return {
            "name": project_name,
            "project_type": meta.get("project_type", "segmented"),
            "matching_mode": meta.get("matching_mode", "chaotic"),
            "audio_ready": audio_exists,
            "audio_filename": audio_filename,
            "sources": meta.get("sources", []),
            "timeline": meta.get("timeline", []),
            "segmented_timeline": meta.get("segmented_timeline", []),
            "status": meta.get("status", "idle"),
            "percent": meta.get("percent", 0),
            "progress_text": meta.get("progress_text", "Initializing..."),
            # Extended build progress fields
            "build_step": meta.get("build_step"),
            "current_track": meta.get("current_track"),
            "total_tracks": meta.get("total_tracks"),
            "track_name": meta.get("track_name"),
            "music_track": meta.get("music_track")
        }

    def get_project_meta(self, project_name):
        """Helper to load project metadata."""
        project_dir = self.projects_path / project_name
        meta_path = project_dir / "project_meta.json"
        
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    return json.load(f)
            except Exception:
                logger.error(f"Failed to load meta for {project_name}")
        return None


    
    def delete_source_from_library(self, alias):
        """
        Удаляет источник из библиотеки.
        
        Args:
            alias: Короткое имя источника
            
        Returns:
            bool: True если успешно удалено
        """
        target_dir = self.library_path / alias
        if target_dir.exists():
            shutil.rmtree(target_dir)
            logger.info(f"🗑 Deleted source: {alias}")
            return True
        return False

    def delete_project(self, project_name):
        """
        Удаляет проект полностью.
        """
        target_dir = self.projects_path / project_name
        if target_dir.exists():
            shutil.rmtree(target_dir)
            logger.info(f"🗑 Deleted project: {project_name}")
            return True
        return False

    # === ЭПИЗОДЫ (MANUAL SEGMENTATION) ===

    def get_source_details(self, alias):
        """
        Возвращает детали источника, включая длительность.
        """
        target_dir = self.library_path / alias
        if not target_dir.exists():
            return None
            
        master_index_path = target_dir / "master_index.json"
        duration = 0
        path = "Unknown"
        
        if master_index_path.exists():
            try:
                with open(master_index_path, 'r') as f:
                    data = json.load(f)
                    path = data.get("source_video_path", "Unknown")
                    scenes = data.get("scenes", [])
                    if scenes:
                        # Берем конец последней сцены как длительность
                        # Ищем максимальный end_time
                        duration = max([s["time"]["end"] for s in scenes])
            except: pass
            
        return {
            "alias": alias,
            "path": path,
            "duration": duration
        }

    def update_source_path(self, alias, new_path):
        """
        Обновляет путь к видеофайлу в master_index.json.
        """
        target_dir = self.library_path / alias
        if not target_dir.exists():
            return False
            
        master_index_path = target_dir / "master_index.json"
        if not master_index_path.exists():
            return False
            
        try:
            with open(master_index_path, 'r') as f:
                data = json.load(f)
            
            data["source_video_path"] = new_path
            
            with open(master_index_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"📍 Updated source path for {alias} to: {new_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to update source path: {e}")
            return False

    def get_episodes(self, alias):
        """
        Возвращает список эпизодов для источника.
        """
        source_dir = self.library_path / alias
        if not source_dir.exists():
            return None
        
        episodes_file = source_dir / "episodes.json"
        if not episodes_file.exists():
            return []
            
        try:
            with open(episodes_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading episodes for {alias}: {e}")
            return []

    def get_characters(self, alias):
        """
        Возвращает список персонажей с количеством сцен.
        Uses character_map.json for names and faces_clusters.json for scene counts.
        Returns: [{"name": "The Joker", "scene_count": 186}, ...]
        """
        source_dir = self.library_path / alias
        if not source_dir.exists():
            return []
        
        char_map_path = source_dir / "character_map.json"
        if not char_map_path.exists():
            return []
        
        try:
            with open(char_map_path, 'r', encoding='utf-8') as f:
                char_map = json.load(f)
            
            # Build reverse map: name → set of person_ids
            name_to_pids = {}
            for pid, name in char_map.items():
                if name and name != "Unknown":
                    name_to_pids.setdefault(name, set()).add(pid)
            
            # Count scenes per character using faces_clusters.json
            scene_counts = {name: 0 for name in name_to_pids}
            faces_path = source_dir / "faces_clusters.json"
            if faces_path.exists():
                with open(faces_path, 'r', encoding='utf-8') as f:
                    clusters = json.load(f)
                # clusters: {"scene_id": ["person_X", ...], ...}
                for scene_id, person_ids in clusters.items():
                    pid_set = set(person_ids)
                    for name, pids in name_to_pids.items():
                        if pids.intersection(pid_set):
                            scene_counts[name] += 1
            
            result = [
                {"name": name, "scene_count": scene_counts.get(name, 0)}
                for name in sorted(name_to_pids.keys())
            ]
            return result
        except Exception as e:
            logger.error(f"Error reading character_map for {alias}: {e}")
            return []

    def add_episode(self, alias, name, start_time, end_time):
        """
        Добавляет новый эпизод.
        """
        source_dir = self.library_path / alias
        if not source_dir.exists():
            return None
            
        episodes_file = source_dir / "episodes.json"
        episodes = []
        if episodes_file.exists():
            try:
                with open(episodes_file, 'r') as f:
                    episodes = json.load(f)
            except: pass
            
        new_episode = {
            "id": f"ep_{int(time.time()*1000)}", # Simple unique ID
            "name": name,
            "start_time": start_time,
            "end_time": end_time
        }
        
        episodes.append(new_episode)
        # Sort by start time
        episodes.sort(key=lambda x: x["start_time"])
        
        with open(episodes_file, 'w') as f:
            json.dump(episodes, f, indent=2)
            
        return new_episode

    def delete_episode(self, alias, episode_id):
        """
        Удаляет эпизод по ID.
        """
        source_dir = self.library_path / alias
        if not source_dir.exists():
            return False
            
        episodes_file = source_dir / "episodes.json"
        if not episodes_file.exists():
            return False
            
        try:
            with open(episodes_file, 'r') as f:
                episodes = json.load(f)
            
            new_episodes = [ep for ep in episodes if ep["id"] != episode_id]
            
            if len(new_episodes) == len(episodes):
                return False # Not found
                
            with open(episodes_file, 'w') as f:
                json.dump(new_episodes, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error deleting episode {episode_id}: {e}")
            return False

    def update_episode(self, alias, episode_id, name=None, start_time=None, end_time=None):
        """
        Обновляет данные эпизода по ID.
        
        Args:
            alias: Алиас источника
            episode_id: ID эпизода
            name: Новое название (опционально)
            start_time: Новое время начала в секундах (опционально)
            end_time: Новое время окончания в секундах (опционально)
            
        Returns:
            Updated episode dict или None если не найден
        """
        source_dir = self.library_path / alias
        if not source_dir.exists():
            return None
            
        episodes_file = source_dir / "episodes.json"
        if not episodes_file.exists():
            return None
            
        try:
            with open(episodes_file, 'r') as f:
                episodes = json.load(f)
            
            updated_episode = None
            for ep in episodes:
                if ep["id"] == episode_id:
                    if name is not None:
                        ep["name"] = name
                    if start_time is not None:
                        ep["start_time"] = float(start_time)
                    if end_time is not None:
                        ep["end_time"] = float(end_time)
                    updated_episode = ep
                    break
            
            if updated_episode is None:
                return None
            
            # Re-sort by start_time
            episodes.sort(key=lambda x: x["start_time"])
            
            with open(episodes_file, 'w') as f:
                json.dump(episodes, f, indent=2)
                
            logger.info(f"✅ Episode updated: {updated_episode['name']}")
            return updated_episode
            
        except Exception as e:
            logger.error(f"Error updating episode {episode_id}: {e}")
            return None

    # === AUTO-EPISODE SEGMENTATION ===

    def auto_generate_episodes(self, alias, progress_callback=None, force=False, start_time=None, end_time=None):
        """
        AI-powered automatic episode segmentation using Gemini Video API.
        
        This is an OPTIONAL step — it does NOT run during standard ingestion.
        It uploads the video to Gemini, asks it to identify semantic episode
        boundaries, and saves the result to episodes.json.
        
        Args:
            alias: Source alias in the library
            progress_callback: Optional function(percent, text) for progress
            force: If True, overwrite existing episodes
            start_time: Optional content start boundary in seconds
            end_time: Optional content end boundary in seconds
            
        Returns:
            List of generated episodes, or None on error
        """
        from src.ingestion.episode_segmenter import EpisodeSegmenter
        
        source_dir = self.library_path / alias
        if not source_dir.exists():
            logger.error(f"Source not found: {alias}")
            return None
        
        # scene_data.json is REQUIRED for the new scene-grouping approach
        scene_data = source_dir / "scene_data.json"
        if not scene_data.exists():
            error_msg = f"scene_data.json not found for {alias}. Run ingestion first."
            logger.error(f"❌ {error_msg}")
            if progress_callback:
                progress_callback(0, f"Error: {error_msg}")
            return None
        
        # Check existing episodes
        episodes_file = source_dir / "episodes.json"
        if episodes_file.exists() and not force:
            try:
                with open(episodes_file, 'r') as f:
                    existing = json.load(f)
                if existing:
                    logger.info(f"⏭️ {len(existing)} episodes already exist for {alias}. Use force=True to overwrite.")
                    if progress_callback:
                        progress_callback(100, f"Episodes already exist ({len(existing)} episodes)")
                    return existing
            except Exception:
                pass
        
        try:
            segmenter = EpisodeSegmenter(source_dir)
            episodes = segmenter.process(
                progress_callback=progress_callback,
                force=force,
                start_time=start_time,
                end_time=end_time,
            )
            return episodes
        except Exception as e:
            logger.error(f"❌ Auto-segmentation failed for {alias}: {e}")
            if progress_callback:
                progress_callback(0, f"Error: {str(e)}")
            return None

    def analyze_decisions(self, alias, character, goal):
        """
        Analyze character decisions using Gemini.
        """
        from src.ingestion.decision_analyzer import DecisionAnalyzer
        analyzer = DecisionAnalyzer(self.library_path, alias)
        return analyzer.analyze(character, goal)

    def get_decision_analyses(self, alias):
        """List all decision analyses for a source."""
        from src.ingestion.decision_analyzer import DecisionAnalyzer
        analyzer = DecisionAnalyzer(self.library_path, alias)
        return analyzer.get_analysis_list()

    def get_decision_analysis(self, alias, analysis_id):
        """Get a specific decision analysis."""
        from src.ingestion.decision_analyzer import DecisionAnalyzer
        analyzer = DecisionAnalyzer(self.library_path, alias)
        return analyzer.get_analysis(analysis_id)

    # === SCREENPLAY ===

    def upload_screenplay(self, alias, text, original_filename=None):
        """Save screenplay text to _library/{alias}/screenplay.txt."""
        source_dir = self.library_path / alias
        if not source_dir.exists():
            raise FileNotFoundError(f"Source not found: {alias}")
        
        screenplay_path = source_dir / "screenplay.txt"
        screenplay_path.write_text(text, encoding="utf-8")
        
        logger.info(f"📜 Screenplay uploaded for {alias} ({len(text)} chars, from: {original_filename})")
        return {
            "status": "ok",
            "chars": len(text),
            "lines": text.count("\n") + 1,
            "filename": original_filename
        }

    def delete_screenplay(self, alias):
        """Remove screenplay.txt for a source."""
        source_dir = self.library_path / alias
        if not source_dir.exists():
            raise FileNotFoundError(f"Source not found: {alias}")
        
        screenplay_path = source_dir / "screenplay.txt"
        if screenplay_path.exists():
            screenplay_path.unlink()
            logger.info(f"🗑️ Screenplay deleted for {alias}")
            return {"status": "deleted"}
        return {"status": "not_found"}

    def get_screenplay_status(self, alias):
        """Check if screenplay exists for a source."""
        source_dir = self.library_path / alias
        if not source_dir.exists():
            return {"exists": False}
        
        screenplay_path = source_dir / "screenplay.txt"
        if not screenplay_path.exists():
            return {"exists": False}
        
        text = screenplay_path.read_text(encoding="utf-8")
        return {
            "exists": True,
            "chars": len(text),
            "lines": text.count("\n") + 1,
            "preview": text[:200] + ("..." if len(text) > 200 else "")
        }

    # === 5. MULTI-TRACK AUDIO (TIMELINE) ===

    def add_track(self, project_name, audio_path, source_alias, episode_ids, episode_names,
                  segmentation_mode="episodes", character_names=None):
        """
        Добавляет новый аудио-трек в таймлайн проекта.
        Поддерживает два режима: episodes (по эпизодам) и characters (по персонажам).
        """
        project_dir = self.projects_path / project_name
        if not project_dir.exists():
            return None
        
        meta_path = project_dir / "project_meta.json"
        
        # Load Meta
        meta = {}
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
            except: pass
        
        # Init timeline
        if "timeline" not in meta:
            meta["timeline"] = []
            
        # Copy Audio
        input_dir = project_dir / "input"
        self._ensure_dir(input_dir)
        
        src_audio = Path(audio_path)
        if not src_audio.exists():
            logger.error(f"Audio not found: {audio_path}")
            return None
            
        # Unique ID for track
        track_id = f"track_{int(time.time()*1000)}"
        dest_filename = f"{track_id}{src_audio.suffix}"
        dest_audio = input_dir / dest_filename
        shutil.copy2(src_audio, dest_audio)
        
        # Create track object
        # Ensure episode_ids is a list
        if episode_ids and not isinstance(episode_ids, list):
            episode_ids = [episode_ids]
            
        new_track = {
            "id": track_id,
            "audio_file": dest_filename,
            "source_alias": source_alias,
            "episode_ids": episode_ids or [],
            "episode_names": episode_names or [],
            "segmentation_mode": segmentation_mode,
            "character_names": character_names or [],
            "original_name": src_audio.name
        }
        
        meta["timeline"].append(new_track)
        
        # Add source to global list if not exists
        if "sources" not in meta: meta["sources"] = []
        if source_alias not in meta["sources"]:
            meta["sources"].append(source_alias)
            
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
            
        return new_track

    def remove_track(self, project_name, track_id):
        project_dir = self.projects_path / project_name
        meta_path = project_dir / "project_meta.json"
        
        if not meta_path.exists(): return False
        
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            
            new_timeline = [t for t in meta.get("timeline", []) if t["id"] != track_id]
            if len(new_timeline) == len(meta.get("timeline", [])):
                return False
                
            meta["timeline"] = new_timeline
            
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)
            return True
        except: return False

    def update_track(self, project_name, track_id, episode_ids=None, episode_names=None,
                     segmentation_mode=None, character_names=None):
        """
        Updates an existing track's episode/character selection.
        """
        project_dir = self.projects_path / project_name
        meta_path = project_dir / "project_meta.json"
        
        if not meta_path.exists(): return False
        
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            
            updated = False
            for track in meta.get("timeline", []):
                if track["id"] == track_id:
                    if episode_ids is not None:
                        # Ensure list
                        if not isinstance(episode_ids, list):
                            episode_ids = [episode_ids]
                        track["episode_ids"] = episode_ids
                    
                    if episode_names is not None:
                        track["episode_names"] = episode_names

                    if segmentation_mode is not None:
                        track["segmentation_mode"] = segmentation_mode
                    
                    if character_names is not None:
                        track["character_names"] = character_names
                        
                    updated = True
                    break
            
            if not updated:
                return False
                
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to update track {track_id}: {e}")
            return False


    def get_timeline(self, project_name):
        project_dir = self.projects_path / project_name
        meta_path = project_dir / "project_meta.json"
        if not meta_path.exists(): return []
        try:
            with open(meta_path, 'r') as f:
                return json.load(f).get("timeline", [])
        except: return []

    def transcribe_project_audio(self, project_name):
        project_dir = self.projects_path / project_name
        input_dir = project_dir / "input"
        artifacts_dir = project_dir / "artifacts"
        self._ensure_dir(artifacts_dir)
        
        audio_files = [f for f in input_dir.iterdir() if f.suffix.lower() in [".mp3", ".wav", ".m4a"]]
        if not audio_files:
            raise Exception("No audio file found in project/input")
            
        audio_path = audio_files[0]
        transcript_path = artifacts_dir / "transcript.json"
        
        logger.info("🎙 Running Whisper for segmented project...")
        # Local import instead of global if AudioProcessor not present, but it is imported globally.
        from src.analysis.audio_processor import AudioProcessor
        processor = AudioProcessor(model_size=self.config["models"]["whisper"])
        transcript_data = processor.process(audio_path, transcript_path)
        return transcript_data

    def get_project_transcript(self, project_name):
        project_dir = self.projects_path / project_name
        transcript_path = project_dir / "artifacts" / "transcript.json"
        if transcript_path.exists():
            with open(transcript_path, 'r') as f:
                return json.load(f)
        return {"batches": []}

    def save_segmented_timeline(self, project_name, timeline_data):
        project_dir = self.projects_path / project_name
        meta_path = project_dir / "project_meta.json"
        with open(meta_path, 'r') as f:
            meta = json.load(f)
        meta["segmented_timeline"] = timeline_data
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

    def auto_plan_segmented_timeline(
        self,
        project_name,
        script_text,
        source_aliases,
        group_ids=None,
        model_name=None,
        save=True,
    ):
        project_dir = self.projects_path / project_name
        artifacts_dir = project_dir / "artifacts"
        meta_path = project_dir / "project_meta.json"

        if not project_dir.exists():
            raise FileNotFoundError(f"Project not found: {project_name}")
        if not script_text or not script_text.strip():
            raise ValueError("Exact script text is required")
        source_aliases = list(source_aliases or [])

        transcript = self.get_project_transcript(project_name)
        if not transcript or "batches" not in transcript:
            raise ValueError("Transcribe the project audio before auto planning")

        selected_groups = []
        for group_id in group_ids or []:
            group = self.get_group(group_id)
            if group:
                selected_groups.append(group)
                for item in group.get("items", []):
                    item_source = item.get("source_alias")
                    if item_source and item_source not in source_aliases:
                        source_aliases.append(item_source)
            else:
                logger.warning(f"⚠️ Auto planner ignored missing group: {group_id}")

        if not source_aliases:
            raise ValueError("Select at least one source or group with source items")

        from src.analysis.timeline_planner_agent import TimelinePlannerAgent

        planner = TimelinePlannerAgent(self.library_path, model_name=model_name)
        plan = planner.plan(
            script_text=script_text,
            transcript=transcript,
            source_aliases=source_aliases,
            groups=selected_groups,
        )

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        with open(artifacts_dir / "auto_timeline_script.txt", "w", encoding="utf-8") as f:
            f.write(script_text)
        with open(artifacts_dir / "auto_timeline_plan.json", "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        if save:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            meta["segmented_timeline"] = plan["items"]
            meta["auto_timeline_plan"] = {
                "created_at": time.time(),
                "source_aliases": source_aliases,
                "group_ids": group_ids or [],
                "model_name": model_name,
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

        return plan

    def save_music_track(self, project_name, filename):
        """
        Registers a generated music track in the project's metadata.
        """
        project_dir = self.projects_path / project_name
        meta_path = project_dir / "project_meta.json"
        
        if meta_path.exists():
            with open(meta_path, 'r') as f:
                meta = json.load(f)
                
            meta["music_track"] = filename
            
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)

    def build_segmented_timeline_project(self, project_name, progress_callback=None, model_name=None):
        """
        Build a segmented timeline project.
        
        Each clip in segmented_timeline defines:
          - timeline_start / timeline_duration: position on the audio timeline
          - source_alias / episode_id / episode_name: which episode to pull footage from
        
        For each clip, we:
          1. Find transcript segments that fall within this clip's time range
          2. Look up the episode's video time range from the library
          3. Run DirectorAgent + GapMatcher to produce EDL entries
          4. Combine all EDL entries and export via PremiereExporter
        """
        logger.info(f"🔨 Building SEGMENTED project '{project_name}'...")
        
        project_dir = self.projects_path / project_name
        input_dir = project_dir / "input"
        output_dir = project_dir / "output"
        artifacts_dir = project_dir / "artifacts"
        meta_path = project_dir / "project_meta.json"
        
        self._ensure_dir(output_dir)
        self._ensure_dir(artifacts_dir)
        
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
        except Exception:
            return
            
        segmented_timeline = meta.get("segmented_timeline", [])
        if not segmented_timeline:
            logger.error("Empty segmented timeline")
            return
            
        audio_files = [f for f in input_dir.iterdir() if f.suffix.lower() in [".mp3", ".wav", ".m4a"]]
        if not audio_files:
            logger.error("No audio file found")
            return
        audio_path = audio_files[0]
        
        transcript_data = self.get_project_transcript(project_name)
        if not transcript_data or "batches" not in transcript_data:
            logger.error("No transcript found")
            return
            
        batches = transcript_data.get("batches", [])
        if not batches:
            batches = transcript_data  # old format
        
        # Sort clips by timeline position
        segmented_timeline.sort(key=lambda c: c.get("timeline_start", 0))
        total_clips = len(segmented_timeline)
        
        def save_build_state(percent, text, step=None, current_track=None, track_name=None):
            meta["status"] = "building" if 0 < percent < 100 else ("ready" if percent >= 100 else "idle")
            meta["percent"] = percent
            meta["progress_text"] = text
            meta["build_step"] = step
            meta["current_track"] = current_track
            meta["total_tracks"] = total_clips
            meta["track_name"] = track_name
            meta["last_updated"] = time.time()
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)
                
        def report(percent, text, step=None, current_track=None, track_name=None):
            save_build_state(percent, text, step, current_track, track_name)
            if progress_callback:
                progress_callback(percent, {
                    "text": text,
                    "step": step,
                    "current_track": current_track,
                    "total_tracks": total_clips,
                    "track_name": track_name
                })
                
        report(0, "Initializing Segmented Build...", step="init")
        
        try:
            combined_edl = []
            audio_export_list = [(audio_path, transcript_data.get("duration", 0))]
            
            # Cache matcher instances to avoid re-loading CLIP model per clip
            _cached_chaotic_matcher = None
            _cached_gap_matcher = None
            from src.analysis.director_agent import DirectorAgent
            
            for i, clip in enumerate(segmented_timeline):
                clip_start = clip.get("timeline_start", 0)
                clip_duration = clip.get("timeline_duration", 10)
                clip_end = clip_start + clip_duration
                source_alias = clip.get("source_alias", "")
                episode_id = clip.get("episode_id", "")
                episode_name = clip.get("episode_name", "Unknown")
                
                clip_num = i + 1
                clip_base_pct = int((i / total_clips) * 80)
                clip_pct_per_step = int(80 / total_clips / 3)
                
                logger.info(f"📌 Clip {clip_num}/{total_clips}: {episode_name} "
                           f"[{clip_start:.1f}s → {clip_end:.1f}s] ({clip_duration:.1f}s)")
                
                # --- 1. Filter transcript segments for this clip's time range ---
                clip_segments = []
                for b in batches:
                    for seg in b.get("segments", []):
                        seg_mid = (seg["start"] + seg["end"]) / 2
                        if clip_start <= seg_mid <= clip_end:
                            clip_segments.append(seg)
                
                if not clip_segments:
                    # Create a dummy segment so we still get footage
                    clip_segments = [{
                        "start": clip_start,
                        "end": clip_end,
                        "text": "",
                        "visual_query": "cinematic movie scene",
                        "shot_type": "Medium Shot",
                        "character": None,
                        "mood": "Neutral",
                        "segment_id": 0
                    }]
                
                # --- 2. Resolve sources and time ranges ---
                clip_type = clip.get("clip_type", "episode")
                character_name = clip.get("character_name", "")
                matcher_mode = clip.get("matcher_mode", "sequential" if clip_type == "episode" else "chaotic")
                group_selection_mode = clip.get("group_selection_mode", "score")
                
                source_aliases = []
                episode_time_ranges = []
                source_episode_time_ranges = []
                clip_label = ""
                
                if clip_type == "group":
                    # Prefer current .groups/ storage over stale embedded timeline copies.
                    group_items = []
                    if episode_id:
                        group_data = self.get_group(episode_id)
                        if group_data:
                            group_items = group_data.get("items", [])
                            group_items, errors = self.normalize_group_items(group_items, strict=False)
                            for error in errors:
                                logger.warning(f"⚠️ Group '{episode_name}': {error}")
                            logger.info(f"📦 Resolved group '{episode_name}' from storage: {len(group_items)} items")
                        else:
                            logger.error(f"❌ Group '{episode_id}' not found in storage")
                    if not group_items:
                        group_items = clip.get("group_items") or clip.get("_groupItems") or []
                        if group_items:
                            group_items, errors = self.normalize_group_items(group_items, strict=False)
                            for error in errors:
                                logger.warning(f"⚠️ Group clip '{episode_name}': {error}")
                    source_aliases_seen = set()
                    clip_label = f"Group: {episode_name}"
                    
                    for item in group_items:
                        i_source = item.get("source_alias")
                        i_type = item.get("type")
                        i_name = item.get("name")
                        i_ep_id = item.get("episode_id")
                        if not i_source: continue
                        
                        if i_source not in source_aliases_seen:
                            source_aliases_seen.add(i_source)
                            source_aliases.append(i_source)
                        
                        if i_type == "character":
                            # resolve character scenes
                            char_map_path = self.library_path / i_source / "character_map.json"
                            master_index_path = self.library_path / i_source / "master_index.json"
                            if char_map_path.exists() and master_index_path.exists():
                                with open(char_map_path, 'r', encoding='utf-8') as f:
                                    char_map = json.load(f)
                                with open(master_index_path, 'r') as f:
                                    master_data = json.load(f)
                                name_to_pids = {}
                                for pid, cname in char_map.items():
                                    name_to_pids.setdefault(cname.lower(), set()).add(pid)
                                target_pids = name_to_pids.get(i_name.lower(), set())
                                for scene in master_data.get("scenes", []):
                                    raw_ids = set(scene.get("content", {}).get("raw_ids", []))
                                    if target_pids.intersection(raw_ids):
                                        episode_time_ranges.append((scene["time"]["start"], scene["time"]["end"]))
                                        source_episode_time_ranges.append({
                                            "source_alias": i_source,
                                            "start": scene["time"]["start"],
                                            "end": scene["time"]["end"]
                                        })
                        else:
                            episodes = self.get_episodes(i_source)
                            if episodes and i_ep_id:
                                for ep in episodes:
                                    if ep["id"] == i_ep_id:
                                        episode_time_ranges.append((ep["start_time"], ep["end_time"]))
                                        source_episode_time_ranges.append({
                                            "source_alias": i_source,
                                            "start": ep["start_time"],
                                            "end": ep["end_time"]
                                        })
                                        break
                    episode_time_ranges.sort(key=lambda x: x[0])
                    source_episode_time_ranges.sort(key=lambda x: x["start"])
                    if group_selection_mode not in {"score", "alternate"}:
                        logger.warning(f"⚠️ Unknown group selection mode '{group_selection_mode}', using score")
                        group_selection_mode = "score"
                    
                else:
                    source_aliases = [source_alias]
                    clip_label = character_name if clip_type == "character" else episode_name
                    
                    if clip_type == "character" and character_name:
                        char_map_path = self.library_path / source_alias / "character_map.json"
                        master_index_path = self.library_path / source_alias / "master_index.json"
                        if char_map_path.exists() and master_index_path.exists():
                            with open(char_map_path, 'r', encoding='utf-8') as f:
                                char_map = json.load(f)
                            with open(master_index_path, 'r') as f:
                                master_data = json.load(f)
                            name_to_pids = {}
                            for pid, name in char_map.items():
                                name_to_pids.setdefault(name.lower(), set()).add(pid)
                            target_pids = name_to_pids.get(character_name.lower(), set())
                            for scene in master_data.get("scenes", []):
                                raw_ids = set(scene.get("content", {}).get("raw_ids", []))
                                if target_pids.intersection(raw_ids):
                                    episode_time_ranges.append((scene["time"]["start"], scene["time"]["end"]))
                                    source_episode_time_ranges.append({
                                        "source_alias": source_alias,
                                        "start": scene["time"]["start"],
                                        "end": scene["time"]["end"]
                                    })
                            episode_time_ranges.sort(key=lambda x: x[0])
                            source_episode_time_ranges.sort(key=lambda x: x["start"])
                            logger.info(f"👤 Character '{character_name}' → {len(episode_time_ranges)} scene ranges")
                        else:
                            logger.warning(f"⚠️ character_map or master_index missing for {source_alias}")
                    else:
                        episodes = self.get_episodes(source_alias)
                        if episodes and episode_id:
                            for ep in episodes:
                                if ep["id"] == episode_id:
                                    episode_time_ranges.append((ep["start_time"], ep["end_time"]))
                                    source_episode_time_ranges.append({
                                        "source_alias": source_alias,
                                        "start": ep["start_time"],
                                        "end": ep["end_time"]
                                    })
                                    break
                        episode_time_ranges.sort(key=lambda x: x[0])
                        source_episode_time_ranges.sort(key=lambda x: x["start"])

                # --- 3. Run Director Agent ---
                report(
                    clip_base_pct + clip_pct_per_step,
                    f"Clip {clip_num}/{total_clips}: Analyzing scenes...",
                    step="director",
                    current_track=clip_num,
                    track_name=episode_name
                )
                
                clip_batch = [{
                    "batch_id": 0,
                    "segments": clip_segments,
                    "context_text": " ".join([s.get("text", "") for s in clip_segments])
                }]
                
                temp_transcript_path = artifacts_dir / f"clip_{i}_temp_transcript.json"
                with open(temp_transcript_path, 'w') as f:
                    json.dump(clip_batch, f)
                    
                clip_visual_script = artifacts_dir / f"clip_{i}_visual.json"
                director = DirectorAgent(self.library_path, model_name=model_name)
                director.process(temp_transcript_path, clip_visual_script, source_aliases)
                
                # Enrich visual queries with context and STRETCH segments to cover gaps
                with open(clip_visual_script, 'r') as f:
                    v_script = json.load(f)
                
                for idx, s in enumerate(v_script):
                    # Use segment text for CLIP matching (much more specific than generic label)
                    seg_text = s.get("text", "")
                    base_query = s.get("visual_query", "")
                    if seg_text:
                        s["visual_query"] = f"{seg_text} {base_query}"
                    else:
                        s["visual_query"] = f"{clip_label} {base_query}"
                    
                    # Ensure first segment starts precisely at the clip boundary
                    if idx == 0 and s.get("start", 0) > clip_start:
                        s["duration"] += (s["start"] - clip_start)
                        s["start"] = clip_start
                        
                    # Stretch current segment perfectly to the next segment or end of clip
                    if idx < len(v_script) - 1:
                        next_start = v_script[idx + 1].get("start", 0)
                        s["duration"] = next_start - s.get("start", 0)
                        s["end"] = next_start
                    else:
                        s["duration"] = clip_end - s.get("start", 0)
                        s["end"] = clip_end
                        
                with open(clip_visual_script, 'w') as f:
                    json.dump(v_script, f, indent=2)
                
                # --- 4. Match using appropriate matcher ---
                matcher_label = "chaotic" if matcher_mode == "chaotic" else "sequential"
                report(
                    clip_base_pct + clip_pct_per_step * 2,
                    f"Clip {clip_num}/{total_clips}: Matching ({matcher_label})...",
                    step="matcher",
                    current_track=clip_num,
                    track_name=clip_label
                )
                
                clip_edl_path = artifacts_dir / f"clip_{i}_edl.json"
                
                if matcher_mode == "chaotic":
                    if _cached_chaotic_matcher is None:
                        from src.matching.chaotic_matcher import ChaoticMatcher
                        _cached_chaotic_matcher = ChaoticMatcher(self.library_path)
                    _cached_chaotic_matcher.match(
                        clip_visual_script,
                        clip_edl_path,
                        source_aliases,
                        episode_time_ranges=(
                            source_episode_time_ranges
                            if source_episode_time_ranges
                            else episode_time_ranges if episode_time_ranges else None
                        ),
                        source_selection_mode=group_selection_mode if clip_type == "group" else "score"
                    )
                else:
                    if _cached_gap_matcher is None:
                        from src.matching.gap_matcher import GapMatcherAdapter
                        _cached_gap_matcher = GapMatcherAdapter(self.library_path)
                    _cached_gap_matcher.match(
                        clip_visual_script,
                        clip_edl_path,
                        source_aliases,
                        episode_time_ranges=episode_time_ranges if episode_time_ranges else None
                    )
                
                with open(clip_edl_path, 'r') as f:
                    clip_edl = json.load(f)
                combined_edl.extend(clip_edl)
            
            # --- 5. Export Final XML ---
            report(85, "Merging Timeline and Exporting XML...", step="export")
            final_edl_path = artifacts_dir / "segmented_timeline_edl.json"
            with open(final_edl_path, 'w') as f:
                json.dump(combined_edl, f, indent=2)
                
            # Add Music Track if exists
            music_filename = meta.get("music_track")
            if music_filename:
                music_path = project_dir / "music" / music_filename
                if music_path.exists():
                    audio_export_list.append((str(music_path), transcript_data.get("duration", 0)))
            
            output_xml = output_dir / f"{project_name}_segmented.xml"
            from src.matching.premiere_exporter import PremiereExporter
            exporter = PremiereExporter(fps=24)
            exporter.export(final_edl_path, output_xml, audio_export_list)
            
            report(100, "Build complete", step="done")
            logger.info(f"✅ Segmented Build '{project_name}' completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Segmented Build failed: {e}", exc_info=True)
            report(0, f"Error: {e}", step="error")

    # === GROUPS ===

    @staticmethod
    def _group_match_key(value):
        """Stable key for matching human-edited group names."""
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _group_compact_key(value):
        return ProjectManager._group_match_key(value).replace(" ", "")

    def _groups_dir(self):
        """Returns path to groups storage directory."""
        d = self.library_path / ".groups"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _resolve_group_episode_item(self, item, errors):
        source_alias = item.get("source_alias")
        source_dir = self.library_path / source_alias if source_alias else None
        if not source_alias or not source_dir.exists():
            errors.append(f"Source not found: {source_alias or '<missing>'}")
            return None

        episodes = self.get_episodes(source_alias) or []
        if isinstance(episodes, dict):
            episodes = episodes.get("episodes", [])

        episode_id = item.get("episode_id")
        name = item.get("name")

        matched = None
        if episode_id:
            matched = next((ep for ep in episodes if ep.get("id") == episode_id), None)

        if matched is None and name:
            name_key = self._group_match_key(name)
            compact_key = self._group_compact_key(name)
            matched = next(
                (
                    ep for ep in episodes
                    if self._group_match_key(ep.get("name")) == name_key
                    or self._group_compact_key(ep.get("name")) == compact_key
                ),
                None
            )

        if matched is None:
            label = name or episode_id or "<missing>"
            errors.append(f"Episode not found in {source_alias}: {label}")
            return None

        normalized = dict(item)
        normalized["source_alias"] = source_alias
        normalized["type"] = "episode"
        normalized["name"] = matched.get("name") or name
        normalized["episode_id"] = matched.get("id")
        return normalized

    def _resolve_group_character_item(self, item, errors):
        source_alias = item.get("source_alias")
        source_dir = self.library_path / source_alias if source_alias else None
        if not source_alias or not source_dir.exists():
            errors.append(f"Source not found: {source_alias or '<missing>'}")
            return None

        name = item.get("name")
        if not name:
            errors.append(f"Character item in {source_alias} has no name")
            return None

        characters = self.get_characters(source_alias) or []
        match_key = self._group_match_key(name)
        matched = next(
            (char for char in characters if self._group_match_key(char.get("name")) == match_key),
            None
        )
        if matched is None:
            errors.append(f"Character not found in {source_alias}: {name}")
            return None

        normalized = dict(item)
        normalized["source_alias"] = source_alias
        normalized["type"] = "character"
        normalized["name"] = matched.get("name") or name
        normalized.pop("episode_id", None)
        return normalized

    def normalize_group_items(self, items, strict=True):
        """
        Validate group items and repair stale episode IDs when the episode name
        still matches the current source metadata.
        """
        if not items:
            if strict:
                raise ValueError("Group must contain at least one item")
            return [], []

        normalized_items = []
        errors = []
        seen = set()

        for item in items:
            item = dict(item or {})
            item_type = item.get("type")

            if item_type == "episode":
                normalized = self._resolve_group_episode_item(item, errors)
            elif item_type == "character":
                normalized = self._resolve_group_character_item(item, errors)
            else:
                errors.append(f"Unknown group item type: {item_type or '<missing>'}")
                normalized = None

            if not normalized:
                continue

            identity = (
                normalized.get("source_alias"),
                normalized.get("type"),
                normalized.get("episode_id") if normalized.get("type") == "episode" else normalized.get("name"),
            )
            if identity in seen:
                continue
            seen.add(identity)
            normalized_items.append(normalized)

        if strict and errors:
            raise ValueError("; ".join(errors))
        if strict and not normalized_items:
            raise ValueError("Group has no valid items")

        return normalized_items, errors

    def get_groups(self):
        """Returns list of all groups."""
        groups_dir = self._groups_dir()
        groups = []
        for f in sorted(groups_dir.glob("*.json")):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    group = json.load(fh)
                group = self._normalize_group_record(group, persist_path=f)
                groups.append(group)
            except Exception as e:
                logger.warning(f"Failed to read group file {f}: {e}")
        return groups

    def _normalize_group_record(self, group, persist_path=None):
        items = group.get("items", [])
        normalized_items, errors = self.normalize_group_items(items, strict=False)
        if errors:
            group["validation_errors"] = errors
        else:
            group.pop("validation_errors", None)

        if not errors and normalized_items != items:
            group["items"] = normalized_items
            group["updated_at"] = time.time()
            if persist_path:
                with open(persist_path, 'w', encoding='utf-8') as f:
                    json.dump(group, f, indent=2, ensure_ascii=False)
                logger.info(f"📦 Group repaired: '{group.get('name', group.get('id'))}'")
        return group

    def get_group(self, group_id):
        """Returns a single group by ID."""
        path = self._groups_dir() / f"{group_id}.json"
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            group = json.load(f)
        return self._normalize_group_record(group, persist_path=path)

    def create_group(self, name, items):
        """Creates a new group and returns it."""
        items, _ = self.normalize_group_items(items, strict=True)
        group_id = f"grp_{int(time.time() * 1000)}"
        group = {
            "id": group_id,
            "name": name,
            "items": items,
            "created_at": time.time()
        }
        path = self._groups_dir() / f"{group_id}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(group, f, indent=2, ensure_ascii=False)
        logger.info(f"📦 Group created: '{name}' ({len(items)} items)")
        return group

    def update_group(self, group_id, name=None, items=None):
        """Updates an existing group."""
        path = self._groups_dir() / f"{group_id}.json"
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            group = json.load(f)
        if name is not None:
            group["name"] = name
        if items is not None:
            items, _ = self.normalize_group_items(items, strict=True)
            group["items"] = items
        group["updated_at"] = time.time()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(group, f, indent=2, ensure_ascii=False)
        logger.info(f"📦 Group updated: '{group['name']}'")
        return group

    def delete_group(self, group_id):
        """Deletes a group by ID."""
        path = self._groups_dir() / f"{group_id}.json"
        if not path.exists():
            return False
        path.unlink()
        logger.info(f"🗑 Group deleted: {group_id}")
        return True

def main():

    """CLI интерфейс для управления проектами."""
    parser = argparse.ArgumentParser(description="Sculptor Pro CLI Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Команда: create
    create_parser = subparsers.add_parser(
        "create",
        help="Create a new project workspace"
    )
    create_parser.add_argument(
        "--name",
        required=True,
        help="Name of the project (e.g. matrix_essay)"
    )

    # Команда: ingest
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Add a movie to the library"
    )
    ingest_parser.add_argument(
        "--file",
        required=True,
        help="Path to video file"
    )
    ingest_parser.add_argument(
        "--alias",
        required=True,
        help="Short name for the library (e.g. matrix)"
    )
    ingest_parser.add_argument(
        "--fullname",
        help="Full movie title for Gemini (e.g. 'The Matrix 1999')"
    )

    # Команда: build
    build_parser = subparsers.add_parser(
        "build",
        help="Generate XML from audio"
    )
    build_parser.add_argument(
        "--project",
        required=True,
        help="Project name"
    )
    build_parser.add_argument(
        "--sources",
        required=True,
        help="Comma-separated list of sources (e.g. matrix,fight_club)"
    )

    args = parser.parse_args()
    
    # Инициализация менеджера
    from src.utils.app_paths import ensure_app_structure
    ensure_app_structure()
    
    manager = ProjectManager()

    # Выполнение команд
    if args.command == "create":
        manager.create_project(args.name)
    elif args.command == "ingest":
        manager.ingest_source(args.file, args.alias, args.fullname)
    elif args.command == "build":
        manager.build_segmented_timeline_project(args.project)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
