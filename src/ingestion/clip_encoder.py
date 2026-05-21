import torch
import clip
import os
import numpy as np
import json
import logging
from PIL import Image
from pathlib import Path
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Типы кадров, которые мы хотим различать
SHOT_TYPES = [
    "Extreme Close-Up",   # Глаз, деталь, палец
    "Close-Up Face",      # Лицо на весь экран
    "Medium Shot",        # По пояс
    "Two Shot",           # Два человека
    "Wide Angle",         # Общий план (комната, улица)
    "Scenery / Landscape" # Пейзаж без людей
]

class ClipEncoder:
    def __init__(self, output_dir, model_name="ViT-B/32"):
        self.output_dir = Path(output_dir)
        self.keyframes_dir = self.output_dir / "keyframes"
        self.embeddings_path = self.output_dir / "embeddings.npy"
        self.visual_tags_path = self.output_dir / "visual_tags.json"
        
        # Определяем устройство (Apple Silicon MPS или CPU)
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
            
        logger.info(f"👁 Loading CLIP model ({model_name}) on {self.device}...")
        self.model, self.preprocess = clip.load(model_name, device=self.device)
        
        # Подготавливаем текстовые векторы для определения типа кадра
        logger.info("📐 Pre-calculating shot type vectors...")
        text_inputs = clip.tokenize(SHOT_TYPES).to(self.device)
        with torch.no_grad():
            self.shot_type_features = self.model.encode_text(text_inputs)
            self.shot_type_features /= self.shot_type_features.norm(dim=-1, keepdim=True)

    def process_embeddings(self):
        """
        Генерирует векторы для картинок и определяет тип кадра.
        """
        if not self.keyframes_dir.exists():
            logger.error(f"Keyframes dir not found: {self.keyframes_dir}")
            return

        image_files = sorted(list(self.keyframes_dir.glob("*.jpg")))
        logger.info(f"👁 Encoding {len(image_files)} keyframes...")

        embeddings_dict = {} # scene_id -> [vector_start, vector_mid, vector_end]
        visual_tags = {}     # scene_id -> {"shot_type": "Close-Up", "probs": ...}

        # Чтобы не грузить память, процессим по одной картинке (CLIP быстрый)
        # Можно оптимизировать батчами, но для начала так безопаснее
        for img_path in tqdm(image_files, desc="CLIP Encoding"):
            try:
                # 1. Загрузка и препроцессинг
                image = self.preprocess(Image.open(img_path)).unsqueeze(0).to(self.device)
                
                # 2. Генерация эмбеддинга
                with torch.no_grad():
                    image_features = self.model.encode_image(image)
                    
                    # Нормализация вектора (важно для cosine similarity)
                    image_features /= image_features.norm(dim=-1, keepdim=True)

                    # 3. Определение типа кадра (Shot Classification)
                    # Считаем схожесть картинки с текстовыми описаниями планов
                    similarity = (100.0 * image_features @ self.shot_type_features.T).softmax(dim=-1)
                    values, indices = similarity[0].topk(1)
                    
                    best_shot_type = SHOT_TYPES[indices[0]]

                # Сохраняем данные
                # Получаем scene_id из имени файла (scene_0001_0.jpg -> scene_0001)
                scene_id = "_".join(img_path.stem.split("_")[:-1])
                
                # Сохраняем вектор как numpy array (переводим на CPU)
                vec_numpy = image_features.cpu().numpy()[0]
                
                if scene_id not in embeddings_dict:
                    embeddings_dict[scene_id] = []
                    visual_tags[scene_id] = {"shot_counts": {}}

                embeddings_dict[scene_id].append(vec_numpy)
                
                # Считаем голоса за тип кадра (у нас 3 кадра на сцену)
                # Если 2 из 3 кадров говорят Close-Up, значит это Close-Up
                current_counts = visual_tags[scene_id]["shot_counts"]
                current_counts[best_shot_type] = current_counts.get(best_shot_type, 0) + 1

            except Exception as e:
                logger.error(f"Error processing {img_path}: {e}")

        # Финализация данных
        final_embeddings = {}
        final_tags = {}

        for scene_id, vectors in embeddings_dict.items():
            # 1. Усредняем вектор сцены (берем среднее между 3 кадрами)
            # Это дает более стабильный вектор для поиска
            avg_vector = np.mean(vectors, axis=0)
            final_embeddings[scene_id] = avg_vector

            # 2. Определяем итоговый тип сцены (Majority Vote)
            counts = visual_tags[scene_id]["shot_counts"]
            most_frequent_shot = max(counts, key=counts.get)
            final_tags[scene_id] = most_frequent_shot

        # Сохранение на диск
        np.save(self.embeddings_path, final_embeddings)
        with open(self.visual_tags_path, 'w') as f:
            json.dump(final_tags, f, indent=2)

        logger.info(f"💾 Embeddings saved to: {self.embeddings_path}")
        logger.info(f"💾 Visual tags saved to: {self.visual_tags_path}")