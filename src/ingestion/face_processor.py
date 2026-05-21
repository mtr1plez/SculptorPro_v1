import os
import cv2
import numpy as np
import json
import logging
from pathlib import Path
from tqdm import tqdm
import pickle

from insightface.app import FaceAnalysis
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize

logger = logging.getLogger(__name__)

class FaceProcessor:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.keyframes_dir = self.output_dir / "keyframes"
        self.faces_path = self.output_dir / "faces_clusters.json"
        self.face_reps_path = self.output_dir / "face_representatives.json"

        self.app = None 

    def _load_model(self):
        if self.app is None:
            logger.info("⚡️ Loading LIGHTWEIGHT InsightFace model (buffalo_s)...")
            # buffalo_s - супер-быстрая модель. Точность ниже, но скорость х10.
            # det_size=(640, 640) - стандартное разрешение.
            self.app = FaceAnalysis(name='buffalo_s', providers=['CPUExecutionProvider'])
            self.app.prepare(ctx_id=0, det_size=(640, 640))

    def process_faces(self):
        # SKIP LOGIC
        if self.faces_path.exists() and self.face_reps_path.exists():
            logger.info(f"⏭️  Face data exists. Skipping.")
            return

        if not self.keyframes_dir.exists():
            logger.error(f"Keyframes dir not found.")
            return

        self._load_model()

        image_files = sorted(list(self.keyframes_dir.glob("*.jpg")))
        logger.info(f"🔍 Scanning faces in {len(image_files)} keyframes...")

        all_embeddings = []
        embedding_map = [] 

        # --- ЭТАП 1: Строгая фильтрация ---
        detected_count = 0
        skipped_low_quality = 0

        for img_path in tqdm(image_files, desc="Detecting Faces"):
            img = cv2.imread(str(img_path))
            if img is None: continue
            
            try:
                faces = self.app.get(img)
            except Exception: continue
            
            if not faces: continue

            scene_id = "_".join(img_path.stem.split("_")[:-1])

            for face in faces:
                # ОЧЕНЬ ВАЖНО: Поднимаем порог качества до 0.60
                # Мы игнорируем размытые лица, которые служат "мостиком" для склеивания разных людей.
                if face.det_score < 0.60: 
                    skipped_low_quality += 1
                    continue 

                all_embeddings.append(face.embedding)
                embedding_map.append({
                    "scene_id": scene_id,
                    "filename": img_path.name,
                    "score": float(face.det_score)
                })
                detected_count += 1

        logger.info(f"📊 Faces detected: {detected_count}. Skipped blur/bad: {skipped_low_quality}")
        
        if detected_count == 0:
            logger.warning("⚠️ No high-quality faces found! Try lowering threshold slightly.")
            with open(self.faces_path, 'w') as f: json.dump({}, f)
            with open(self.face_reps_path, 'w') as f: json.dump({}, f)
            return

        # --- ЭТАП 2: Дробление Кластеров ---
        logger.info("Pre-normalizing embeddings...")
        X = normalize(np.array(all_embeddings))

        logger.info("🧩 Clustering faces (Fragmentation Mode)...")
        
        # eps=0.40 -> ЭКСТРЕМАЛЬНО низкий порог.
        # Это заставит алгоритм считать "одним лицом" только почти идентичные фотки.
        # Микаэль разобьется на 3-4 разных кластера, но зато он НЕ склеится с Лисбет.
        clustering = DBSCAN(eps=0.40, min_samples=2, metric="cosine", n_jobs=-1).fit(X)
        
        labels = clustering.labels_
        
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        logger.info(f"🔢 Statistics: {n_clusters} clusters (fragments) found.")

        # --- ЭТАП 3: Сохранение ---
        scene_faces = {} 
        representative_faces = {} 

        for idx, label in enumerate(labels):
            if label == -1: continue 
            
            person_id = f"person_{label}"
            data = embedding_map[idx]
            s_id = data["scene_id"]

            if s_id not in scene_faces: scene_faces[s_id] = set()
            scene_faces[s_id].add(person_id)
            
            if person_id not in representative_faces:
                representative_faces[person_id] = {"path": data["filename"], "score": data["score"]}
            else:
                if data["score"] > representative_faces[person_id]["score"]:
                    representative_faces[person_id] = {"path": data["filename"], "score": data["score"]}

        with open(self.face_reps_path, 'w') as f:
            json.dump(representative_faces, f, indent=2)

        final_json = {k: list(v) for k, v in scene_faces.items()}
        with open(self.faces_path, 'w') as f:
            json.dump(final_json, f, indent=2)

        logger.info(f"💾 Saved data to {self.faces_path}")