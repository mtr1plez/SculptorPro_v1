"""
Sequential Matcher v2.1 — со скачками между кадрами для YouTube.

Принцип работы:
1. Audio Length определяется по END последнего сегмента transcript (строго!)
2. Для каждого сегмента аудио CLIP выбирает лучший кадр из эпизода
3. Использованные временные интервалы БЛОКИРУЮТСЯ (никаких повторов)
4. Скачки между кадрами получаются автоматически (CLIP выбирает разные моменты)
5. Ratio 1.5 — это буфер на скачки (50% хронометража "теряется" при выборе)
6. ECM включается когда весь эпизод исчерпан и ratio < 1.5
7. Итог: Video Duration == Audio Duration, но с нарезкой кадров
"""

import json
import logging
import torch
import clip
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

logger = logging.getLogger(__name__)


class SequentialMatcher:
    """
    Матчер со скачками между кадрами.
    CLIP выбирает лучшие кадры, использованные интервалы блокируются.
    """
    
    def __init__(self, library_path: str, model_name: str = "ViT-B/32"):
        self.library_path = Path(library_path)
        self.device = "cpu"
        
        logger.info("📖 Loading CLIP model for Sequential Matching v2.1...")
        self.model, _ = clip.load(model_name, device=self.device)
        
        self.loaded_sources: Dict[str, Dict] = {}
    
    def _load_source(self, source_name: str) -> Optional[Dict]:
        """Загружает индекс сцен и эмбеддинги для источника."""
        if source_name in self.loaded_sources:
            return self.loaded_sources[source_name]

        source_dir = self.library_path / source_name
        index_path = source_dir / "master_index.json"
        emb_path = source_dir / "embeddings.npy"

        if not index_path.exists() or not emb_path.exists():
            logger.error(f"❌ Missing index/embeddings for {source_name}")
            return None

        with open(index_path, 'r') as f:
            index_data = json.load(f)
        
        if isinstance(index_data, dict) and "scenes" in index_data:
            scenes = index_data["scenes"]
            source_video_path = index_data.get("source_video_path")
        else:
            scenes = index_data
            source_video_path = None
        
        embeddings = np.load(emb_path, allow_pickle=True).item()
        
        valid_scenes = []
        ordered_vectors = []
        
        for scene in scenes:
            s_id = scene['id']
            if s_id in embeddings:
                ordered_vectors.append(embeddings[s_id])
                valid_scenes.append(scene)
        
        if not ordered_vectors:
            return None
        
        matrix = np.array(ordered_vectors)
        norm = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / (norm + 1e-8)

        data = {
            "scenes": valid_scenes,
            "matrix": torch.from_numpy(matrix).float().to(self.device),
            "source_name": source_name,
            "source_video_path": source_video_path
        }
        self.loaded_sources[source_name] = data
        return data

    def _encode_text(self, text: str) -> torch.Tensor:
        """Кодирует текст в CLIP embedding."""
        tokens = clip.tokenize([text], truncate=True).to(self.device)
        with torch.no_grad():
            emb = self.model.encode_text(tokens).float()
            emb /= emb.norm(dim=-1, keepdim=True)
        return emb

    def _intervals_overlap(self, a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
        """Проверяет пересечение двух интервалов."""
        return not (a_end <= b_start or b_end <= a_start)

    def _is_interval_blocked(self, start: float, end: float, blocked: List[Tuple[float, float]]) -> bool:
        """Проверяет, заблокирован ли интервал."""
        for b_start, b_end in blocked:
            if self._intervals_overlap(start, end, b_start, b_end):
                return True
        return False

    def _find_best_clip_match(
        self,
        text_query: str,
        source_data: Dict,
        duration_needed: float,
        blocked_intervals: List[Tuple[float, float]],
        episode_time_ranges: List[Tuple[float, float]],
        search_outside_episode: bool = False
    ) -> Optional[Dict]:
        """
        Ищет лучший кадр по CLIP, исключая заблокированные интервалы.
        
        Args:
            text_query: Текст для CLIP-matching
            source_data: Данные источника
            duration_needed: Нужная длительность
            blocked_intervals: Уже использованные интервалы
            episode_time_ranges: Список (start, end) разрешенных диапазонов
            search_outside_episode: Если True, ищет ВНЕ этих диапазонов (ECM режим)
        """
        scenes = source_data["scenes"]
        matrix = source_data["matrix"]
        
        # Кодируем текст
        if text_query:
            text_emb = self._encode_text(text_query)
        else:
            text_emb = None
        
        candidates = []
        
        for i, scene in enumerate(scenes):
            s_start = scene["time"]["start"]
            s_end = scene["time"]["end"]
            
            # Фильтр по эпизодам (disjoint ranges)
            # Сцена считается "в эпизоде", если она пересекается с любым из диапазонов
            in_any_episode = False
            for ep_start, ep_end in episode_time_ranges:
                # Пересечение: (StartA <= EndB) and (EndA >= StartB)
                if (s_start < ep_end) and (s_end > ep_start):
                    in_any_episode = True
                    break
            
            if search_outside_episode:
                # ECM: ищем ТОЛЬКО вне всех эпизодов
                if in_any_episode:
                    continue
            else:
                # Обычный режим: ищем ТОЛЬКО внутри любого из эпизодов
                if not in_any_episode:
                    continue
            
            # Для каждой сцены пробуем найти свободный интервал нужной длины
            # Начинаем с начала сцены и ищем первый незаблокированный участок
            
            # Потенциальные точки входа в сцену
            potential_in_points = [s_start]
            
            # Также добавляем точки сразу после заблокированных интервалов
            for b_start, b_end in blocked_intervals:
                if s_start < b_end < s_end:
                    potential_in_points.append(b_end)
            
            # Также добавляем точки начала эпизодов (если они внутри сцены)
            if not search_outside_episode:
                for ep_start, ep_end in episode_time_ranges:
                    if s_start < ep_start < s_end:
                        potential_in_points.append(ep_start)

            for in_point in potential_in_points:
                out_point = in_point + duration_needed
                
                # Проверяем: влезает ли в сцену?
                if out_point > s_end:
                    continue
                
                # В режиме эпизода: проверяем границы эпизодов
                valid_location = False
                if not search_outside_episode:
                    for ep_start, ep_end in episode_time_ranges:
                        # Интервал должен полностью лежать внутри одного из эпизодов
                        if in_point >= ep_start and out_point <= ep_end:
                            valid_location = True
                            break
                    if not valid_location:
                        continue
                else:
                    # В режиме ECM (вне эпизодов):
                    # Интервал НЕ должен пересекаться ни с одним эпизодом
                    overlaps_episode = False
                    for ep_start, ep_end in episode_time_ranges:
                        if not (out_point <= ep_start or in_point >= ep_end):
                            overlaps_episode = True
                            break
                    if overlaps_episode:
                        continue
                
                # Проверяем: не заблокирован ли?
                if self._is_interval_blocked(in_point, out_point, blocked_intervals):
                    continue
                
                # Считаем CLIP score
                clip_score = 0.0
                if text_emb is not None:
                    vec = matrix[i]
                    clip_score = float(torch.dot(text_emb.view(-1), vec))
                
                candidates.append({
                    "scene": scene,
                    "score": clip_score,
                    "in_point": in_point,
                    "out_point": out_point,
                    "idx": i
                })
        
        if not candidates:
            return None
        
        # Выбираем лучший по CLIP score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        
        return {
            "scene": best["scene"],
            "in_point": best["in_point"],
            "out_point": best["out_point"],
            "score": best["score"]
        }

    def match(
        self, 
        script_path: str, 
        output_path: str, 
        source_names: List[str],
        episode_time_ranges: Optional[List[Tuple[float, float]]] = None,
        initial_blocked_intervals: Optional[List[Tuple[float, float]]] = None
    ) -> List[Tuple[float, float]]:
        """
        Главный метод матчинга.
        
        Args:
            script_path: Путь к visual_script.json с сегментами
            output_path: Путь для сохранения EDL
            source_names: Список источников
            episode_time_ranges: Список (start, end) временных диапазонов эпизодов
            initial_blocked_intervals: Список уже занятых интервалов (от предудыщих треков)
            
        Returns:
            List[Tuple[float, float]]: Обновленный список заблокированных интервалов
        """
        script_path = Path(script_path)
        
        # === STEP 1: Загрузка сегментов ===
        with open(script_path, 'r') as f:
            segments = json.load(f)
        
        if not segments:
            logger.error("❌ Empty script, nothing to match")
            with open(output_path, 'w') as f:
                json.dump([], f)
            return initial_blocked_intervals or []
        
        # === STEP 2: Определяем Audio Length по END последнего сегмента ===
        last_segment = segments[-1]
        audio_length = last_segment.get("end", 0)
        
        # Fallback: если нет end, считаем по суммам duration
        if audio_length == 0:
            audio_length = sum(s.get("duration", 0) for s in segments)
        
        logger.info(f"🎵 Audio Length: {audio_length:.2f}s (from last segment end)")
        
        # === STEP 3: Загрузка источников ===
        active_sources = []
        for src in source_names:
            data = self._load_source(src)
            if data:
                active_sources.append(data)
        
        if not active_sources:
            logger.error("❌ No valid sources loaded")
            with open(output_path, 'w') as f:
                json.dump([], f)
            return initial_blocked_intervals or []
        
        primary_source = active_sources[0]
        
        # === STEP 4: Определяем Episode Length и Ratio ===
        if not episode_time_ranges:
            all_scenes = primary_source["scenes"]
            ep_start = all_scenes[0]["time"]["start"] if all_scenes else 0
            ep_end = all_scenes[-1]["time"]["end"] if all_scenes else audio_length
            episode_time_ranges = [(ep_start, ep_end)]
        
        # Calculate total available duration across all ranges
        total_episode_duration = sum(end - start for start, end in episode_time_ranges)
        
        if audio_length > 0:
            ratio = total_episode_duration / audio_length
        else:
            ratio = float('inf')
        
        ecm_enabled = ratio < 1.5
        
        logger.info(f"📊 Episodes Duration: {total_episode_duration:.1f}s ({len(episode_time_ranges)} ranges)")
        logger.info(f"📊 Ratio (EL/AL): {ratio:.2f}")
        
        if ecm_enabled:
            logger.info("⚠️ Ratio < 1.5: ECM будет активирован при нехватке хронометража")
        else:
            logger.info("✅ Ratio >= 1.5: Достаточно хронометража для скачков")
        
        # === STEP 5: CLIP-based матчинг со скачками ===
        blocked_intervals = list(initial_blocked_intervals) if initial_blocked_intervals else []
        final_edl = []
        unfilled_segments = []
        
        for segment in segments:
            segment_id = segment.get("segment_id", 0)
            duration = segment.get("duration", 5.0)
            text = segment.get("text", "")
            visual_query = segment.get("visual_query", text)
            
            # Ищем лучший кадр через CLIP (внутри эпизода)
            match = self._find_best_clip_match(
                visual_query,
                primary_source,
                duration,
                blocked_intervals,
                episode_time_ranges, # List of tuples
                search_outside_episode=False
            )
            
            if match:
                in_point = match["in_point"]
                out_point = match["out_point"]
                scene = match["scene"]
                score = match["score"]
                
                final_edl.append({
                    "segment_id": segment_id,
                    "text": text,
                    "source_file": scene["visual"]["path"],
                    "source_project_alias": primary_source["source_name"],
                    "source_video_path": primary_source["source_video_path"],
                    "scene_id": scene["id"],
                    "in_point": in_point,
                    "out_point": out_point,
                    "duration": out_point - in_point,
                    "target_duration": duration,
                    "timeline_start": segment.get("start", 0.0),
                    "match_score": score,
                    "match_type": "Sequential_CLIP"
                })
                
                # БЛОКИРУЕМ использованный интервал
                blocked_intervals.append((in_point, out_point))
                
                logger.debug(f"✓ Segment {segment_id}: {in_point:.2f}s - {out_point:.2f}s (CLIP score: {score:.3f})")
            else:
                # Нет места в эпизоде — в очередь на ECM
                logger.warning(f"⚠️ Segment {segment_id}: не найден свободный кадр в эпизоде")
                unfilled_segments.append(segment)
        
        # === STEP 6: ECM для незаполненных сегментов ===
        if unfilled_segments:
            if ecm_enabled:
                logger.info(f"🔀 ECM: Обрабатываем {len(unfilled_segments)} сегментов вне эпизода...")
                
                for segment in unfilled_segments:
                    segment_id = segment.get("segment_id", 0)
                    duration = segment.get("duration", 5.0)
                    text = segment.get("text", "")
                    visual_query = segment.get("visual_query", text)
                    
                    # Ищем вне эпизода
                    match = self._find_best_clip_match(
                        visual_query,
                        primary_source,
                        duration,
                        blocked_intervals,
                        episode_time_ranges,
                        search_outside_episode=True
                    )
                    
                    if match:
                        in_point = match["in_point"]
                        out_point = match["out_point"]
                        scene = match["scene"]
                        score = match["score"]
                        
                        final_edl.append({
                            "segment_id": segment_id,
                            "text": text,
                            "source_file": scene["visual"]["path"],
                            "source_project_alias": primary_source["source_name"],
                            "source_video_path": primary_source["source_video_path"],
                            "scene_id": scene["id"],
                            "in_point": in_point,
                            "out_point": out_point,
                            "duration": out_point - in_point,
                            "target_duration": duration,
                            "timeline_start": segment.get("start", 0.0),
                            "match_score": score,
                            "match_type": "Sequential_ECM"
                        })
                        
                        blocked_intervals.append((in_point, out_point))
                        logger.info(f"✓ Segment {segment_id}: {in_point:.2f}s - {out_point:.2f}s (ECM)")
                    else:
                        # ECM тоже не нашел — PLACEHOLDER
                        logger.error(f"❌ Segment {segment_id}: ECM не нашел сцену!")
                        final_edl.append({
                            "segment_id": segment_id,
                            "text": text,
                            "source_file": "PLACEHOLDER",
                            "source_project_alias": primary_source["source_name"],
                            "source_video_path": primary_source["source_video_path"],
                            "scene_id": "ECM_FAILED",
                            "in_point": 0,
                            "out_point": duration,
                            "duration": duration,
                            "target_duration": duration,
                            "timeline_start": segment.get("start", 0.0),
                            "match_score": 0,
                            "match_type": "Placeholder_ECM_Failed"
                        })
            else:
                # ECM отключен (ratio >= 1.5) — это странно, но обработаем
                logger.error(f"❌ {len(unfilled_segments)} сегментов без хрона, ECM отключен (ratio={ratio:.2f})")
                
                for segment in unfilled_segments:
                    segment_id = segment.get("segment_id", 0)
                    duration = segment.get("duration", 5.0)
                    text = segment.get("text", "")
                    
                    final_edl.append({
                        "segment_id": segment_id,
                        "text": text,
                        "source_file": "PLACEHOLDER",
                        "source_project_alias": primary_source["source_name"],
                        "source_video_path": primary_source["source_video_path"],
                        "scene_id": "NO_EPISODE_SPACE",
                        "in_point": 0,
                        "out_point": duration,
                        "duration": duration,
                        "target_duration": duration,
                        "timeline_start": segment.get("start", 0.0),
                        "match_score": 0,
                        "match_type": "Placeholder_NoSpace"
                    })
        
        # === STEP 7: Сортировка по segment_id ===
        final_edl.sort(key=lambda x: x["segment_id"])
        
        # === STEP 8: Валидация ===
        total_video_duration = sum(e["duration"] for e in final_edl)
        
        # Проверяем скачки (должны быть разные in_points)
        in_points = [e["in_point"] for e in final_edl if e["match_type"] != "Placeholder_ECM_Failed"]
        unique_scenes = len(set(e["scene_id"] for e in final_edl if e["scene_id"] not in ["ECM_FAILED", "NO_EPISODE_SPACE"]))
        
        logger.info(f"📊 Validation:")
        logger.info(f"   - Audio Length: {audio_length:.2f}s")
        logger.info(f"   - Video Duration: {total_video_duration:.2f}s")
        logger.info(f"   - Segments in EDL: {len(final_edl)}")
        logger.info(f"   - Segments in Script: {len(segments)}")
        logger.info(f"   - Unique scenes used: {unique_scenes}")
        logger.info(f"   - Total blocked intervals: {len(blocked_intervals)}")
        
        if len(final_edl) != len(segments):
            logger.warning(f"⚠️ Mismatch: EDL has {len(final_edl)} segments, script has {len(segments)}")
        
        if abs(total_video_duration - audio_length) > 0.5:
            logger.warning(f"⚠️ Duration mismatch: Video={total_video_duration:.2f}s, Audio={audio_length:.2f}s")
        
        # === SAVE ===
        with open(output_path, 'w') as f:
            json.dump(final_edl, f, indent=2)
        
        logger.info(f"✅ Sequential Match Complete. {len(final_edl)} cuts saved to {output_path}")
        
        return blocked_intervals
