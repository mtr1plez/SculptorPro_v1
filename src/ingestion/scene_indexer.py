import os
import cv2
import json
import logging
from pathlib import Path
from tqdm import tqdm
from scenedetect import detect, ContentDetector, SceneManager, open_video
# Если scenedetect ругается на импорт save_images, можно убрать, он тут не используется напрямую
# from scenedetect.scene_manager import save_images 

# Настройка логгера
logger = logging.getLogger(__name__)

class SceneIndexer:
    def __init__(self, source_path, output_dir):
        """
        :param source_path: Путь к исходному видеофайлу
        :param output_dir: Путь к папке фильма в библиотеке (_library/Matrix/)
        """
        self.source_path = str(source_path)
        self.output_dir = Path(output_dir)
        
        # Создаем структуру папок
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.keyframes_dir = self.output_dir / "keyframes"
        self.keyframes_dir.mkdir(parents=True, exist_ok=True)
        
        self.metadata_path = self.output_dir / "scene_data.json"

    def process(self, threshold=27.0, min_scene_len=1.0):
        """
        Главная функция нарезки.
        Аргумент video_path не нужен, берем self.source_path
        """
        # Используем путь, сохраненный при инициализации
        video_path = self.source_path
        
        # --- ⚡️ SKIP LOGIC (ПРОВЕРКА НАЛИЧИЯ) ---
        if self.metadata_path.exists():
            # Проверяем, есть ли внутри хоть какие-то файлы
            has_keyframes = any(self.keyframes_dir.glob("*.jpg"))
            
            if has_keyframes:
                logger.info(f"⏭️  Scene data already exists at {self.metadata_path}. Skipping detection.")
                try:
                    with open(self.metadata_path, 'r') as f:
                        return json.load(f)
                except json.JSONDecodeError:
                    logger.warning("⚠️ Existing JSON is corrupted. Re-indexing...")
            else:
                logger.warning("⚠️ JSON exists but keyframes are missing. Re-indexing...")
        # ----------------------------------------

        logger.info(f"🎬 Starting scene detection for: {video_path}")

        # 1. Detect Scenes
        # Важно: open_video может кинуть ошибку, если файла нет, но мы проверили путь в менеджере
        video = open_video(video_path)
        scene_manager = SceneManager()
        
        # ContentDetector ищет изменения в пикселях (склейки)
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len * video.frame_rate))
        
        # Запуск детекции
        scene_manager.detect_scenes(video, show_progress=False) # show_progress=False чтобы не ломать логи WebSocket
        scene_list = scene_manager.get_scene_list()
        
        logger.info(f"✅ Detected {len(scene_list)} scenes. Extracting keyframes...")

        # 2. Extract Keyframes & Build Metadata
        scenes_data = []
        cap = cv2.VideoCapture(video_path)
        
        # Получаем FPS
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Используем tqdm для прогресса в консоли (в UI это не пойдет, но для дебага полезно)
        for i, scene in enumerate(tqdm(scene_list, desc="Processing Scenes")):
            start_frame = scene[0].get_frames()
            end_frame = scene[1].get_frames()
            
            # Вычисляем 3 точки: начало (10%), середина (50%), конец (90%)
            frame_points = [
                int(start_frame + (end_frame - start_frame) * 0.1),
                int(start_frame + (end_frame - start_frame) * 0.5),
                int(start_frame + (end_frame - start_frame) * 0.9)
            ]
            
            scene_id = f"scene_{i:04d}"
            saved_frames = []

            for idx, f_num in enumerate(frame_points):
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_num)
                ret, frame = cap.read()
                
                if ret:
                    # Имя файла: scene_0001_0.jpg
                    frame_filename = f"{scene_id}_{idx}.jpg"
                    frame_path = self.keyframes_dir / frame_filename
                    
                    # Ресайз для экономии места (1280px ширины достаточно)
                    h, w = frame.shape[:2]
                    new_w = 1280
                    if w > new_w:
                        new_h = int(h * (new_w / w))
                        frame_resized = cv2.resize(frame, (new_w, new_h))
                    else:
                        frame_resized = frame 
                    
                    cv2.imwrite(str(frame_path), frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    # Сохраняем относительный путь для портативности
                    try:
                        rel_path = frame_path.relative_to(self.output_dir)
                        saved_frames.append(str(rel_path))
                    except ValueError:
                        # Если вдруг пути не совпадают (редкий кейс), сохраняем имя
                        saved_frames.append(frame_filename)

            # Сохраняем метаданные сцены
            scene_record = {
                "scene_id": scene_id,
                "start_time": scene[0].get_seconds(),
                "end_time": scene[1].get_seconds(),
                "start_frame": start_frame,
                "end_frame": end_frame,
                "keyframes": saved_frames
            }
            scenes_data.append(scene_record)

        cap.release()

        # 3. Save JSON
        with open(self.metadata_path, 'w') as f:
            json.dump(scenes_data, f, indent=2)
            
        logger.info(f"💾 Scene data saved to: {self.metadata_path}")
        return scenes_data