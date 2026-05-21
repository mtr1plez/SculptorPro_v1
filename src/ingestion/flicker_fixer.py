import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

class FlickerFixer:
    def __init__(self, source_dir):
        self.source_dir = Path(source_dir)
        self.data_path = self.source_dir / "scene_data.json"
        self.backup_path = self.source_dir / "scene_data_backup.json"

    def fix(self, offset=0.1):
        """
        Сдвигает начало каждой сцены на offset секунд, чтобы убрать фликеры.
        Создает бэкап, чтобы не применять фикс дважды.
        """
        # SKIP LOGIC
        if self.backup_path.exists():
            logger.info(f"🛡️ Scene data backup found. Flicker fix already applied. Skipping.")
            return

        if not self.data_path.exists():
            logger.error(f"❌ No scene data found at {self.data_path}")
            return

        logger.info(f"🩹 Applying flicker fix (+{offset}s start offset)...")

        # 1. Создаем бэкап оригинала
        try:
            shutil.copy(self.data_path, self.backup_path)
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return

        # 2. Читаем данные
        with open(self.data_path, 'r') as f:
            scenes = json.load(f)

        # 3. Модифицируем тайминги
        fixed_scenes = []
        skipped_count = 0
        
        for scene in scenes:
            original_start = scene['start_time']
            new_start = original_start + offset
            
            # Проверка безопасности: если сцена короче, чем сдвиг - мы её пропускаем или удаляем
            # (обычно это мусорные сцены по 0.1 сек)
            if new_start < scene['end_time']:
                scene['start_time'] = round(new_start, 3) # Округляем для красоты
                fixed_scenes.append(scene)
            else:
                skipped_count += 1

        # 4. Перезаписываем scene_data.json
        with open(self.data_path, 'w') as f:
            json.dump(fixed_scenes, f, indent=2)

        logger.info(f"✅ Flicker fix applied. Backup saved at {self.backup_path.name}")
        if skipped_count > 0:
            logger.warning(f"⚠️ Removed {skipped_count} micro-scenes that were shorter than {offset}s")