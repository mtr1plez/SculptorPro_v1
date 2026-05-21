import json
import logging
from pathlib import Path
from collections import Counter
from dotenv import load_dotenv
from PIL import Image

from src.utils.gemini_client import GeminiClient

load_dotenv()
logger = logging.getLogger(__name__)


class MetadataManager:
    def __init__(self, library_dir, movie_name="Unknown Movie", source_video_path=None):
        self.library_dir = Path(library_dir)
        self.movie_name = movie_name
        self.source_video_path = source_video_path
        self.keyframes_dir = self.library_dir / "keyframes"

        # Paths
        self.scene_data_path = self.library_dir / "scene_data.json"
        self.visual_tags_path = self.library_dir / "visual_tags.json"
        self.face_clusters_path = self.library_dir / "faces_clusters.json"
        self.face_reps_path = self.library_dir / "face_representatives.json"
        self.master_index_path = self.library_dir / "master_index.json"
        self.character_map_path = self.library_dir / "character_map.json"

        # Gemini
        try:
            self.client = GeminiClient(model_name="gemini-2.5-flash")
            self.gemini_ready = True
            logger.info("✨ Gemini Client connected.")
        except Exception as e:
            logger.warning(f"⚠️ Gemini disabled: {e}")
            self.gemini_ready = False

    # ------------------------------------------------------------------
    # Characters
    # ------------------------------------------------------------------

    def get_top_characters(self, limit=15):
        if not self.face_clusters_path.exists():
            return []

        with open(self.face_clusters_path, "r") as f:
            clusters = json.load(f)

        counter = Counter()
        for persons in clusters.values():
            for pid in persons:
                counter[pid] += 1

        top = [pid for pid, _ in counter.most_common(limit)]
        logger.info(f"🏆 Top {limit} characters: {top}")
        return top

    def identify_characters(self):
        if not self.gemini_ready or not self.face_reps_path.exists():
            return {}

        if self.character_map_path.exists():
            with open(self.character_map_path, "r", encoding="utf-8") as f:
                return json.load(f)

        with open(self.face_reps_path, "r") as f:
            reps = json.load(f)

        target_pids = self.get_top_characters(limit=15)
        images = []
        prompts = [
            f"You are analyzing the movie '{self.movie_name}'.",
            "These are faces of MAIN characters.",
            "Identify FICTIONAL character names.",
            "Do NOT use actor names.",
            "Return ONLY valid JSON: {\"person_X\": \"Name\"}"
        ]

        for pid in target_pids:
            if pid not in reps:
                continue

            img_path = self.keyframes_dir / reps[pid]["path"]
            if img_path.exists():
                images.append(Image.open(img_path))
                prompts.append(f"Image {len(images)} is labeled '{pid}'.")

        if not images:
            logger.warning("No character images found.")
            return {}

        try:
            response = self.client.generate_content(prompts + images)
            parsed = json.loads(self.client.parse_json(response.text))

            with open(self.character_map_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2, ensure_ascii=False)

            logger.info(f"✅ Characters identified: {parsed}")
            return parsed

        except Exception as e:
            logger.error(f"❌ Character identification failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # Master Index
    # ------------------------------------------------------------------

    def build_master_index(self):
        logger.info("📦 Building Master Index...")

        if not self.scene_data_path.exists():
            raise RuntimeError("scene_data.json not found")

        with open(self.scene_data_path, "r") as f:
            scenes = json.load(f)

        visual_tags = {}
        if self.visual_tags_path.exists():
            with open(self.visual_tags_path, "r") as f:
                visual_tags = json.load(f)

        face_clusters = {}
        if self.face_clusters_path.exists():
            with open(self.face_clusters_path, "r") as f:
                face_clusters = json.load(f)

        char_map = self.identify_characters()

        # Вычисляем длительность фильма для plot-aware метаданных
        movie_duration = max([s["end_time"] for s in scenes]) if scenes else 0
        
        # Константы для определения интро/титров
        INTRO_DURATION = 90  # Первые 90 секунд
        CREDITS_THRESHOLD = movie_duration - 180  # Последние 3 минуты
        
        scenes_index = []

        for scene in scenes:
            scene_id = scene["scene_id"]
            raw_ids = face_clusters.get(scene_id, [])
            scene_start = scene["start_time"]

            named_chars = [
                char_map[pid]
                for pid in raw_ids
                if pid in char_map and char_map[pid] != "Unknown"
            ]
            
            # Plot-aware метаданные
            is_intro = scene_start < INTRO_DURATION
            is_credits = scene_start > CREDITS_THRESHOLD if movie_duration > 0 else False
            plot_position = scene_start / movie_duration if movie_duration > 0 else 0.0

            scenes_index.append({
                "id": scene_id,
                "time": {
                    "start": scene["start_time"],
                    "end": scene["end_time"]
                },
                "visual": {
                    "shot_type": visual_tags.get(scene_id, "Unknown"),
                    "path": scene["keyframes"][1] if len(scene["keyframes"]) > 1 else ""
                },
                "content": {
                    "characters": named_chars,
                    "raw_ids": raw_ids
                },
                # Новые plot-aware метаданные
                "metadata": {
                    "is_intro": is_intro,
                    "is_credits": is_credits,
                    "plot_position": round(plot_position, 4)
                }
            })

        master_index = {
            "movie_name": self.movie_name,
            "source_video_path": str(self.source_video_path) if self.source_video_path else None,
            "scenes": scenes_index
        }

        with open(self.master_index_path, "w", encoding="utf-8") as f:
            json.dump(master_index, f, indent=2, ensure_ascii=False)

        logger.info(f"🎉 Master Index saved: {self.master_index_path}")
