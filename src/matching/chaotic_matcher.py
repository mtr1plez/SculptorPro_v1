"""
Chaotic Matcher — for video essays and dynamic editing.

Key Rules:
1. Character First: If segment specifies a character, we filters scenes strictly to those containing the character.
2. Strict Phrase Alignment: Prefer clips that can cover the full segment duration.
3. Cooldown: 60s gap between reusing the same scene ID.
4. Max Usage: A single scene ID can be used max 3 times per video.
"""

import json
import logging
import random
import re
import torch
import clip
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from tqdm import tqdm

logger = logging.getLogger(__name__)

class ChaoticMatcher:
    
    COOLDOWN_RATIO = 0.3       # Cooldown = total_duration * ratio (dynamic)
    COOLDOWN_MAX = 60.0         # Never exceed this
    MAX_USES_PER_SCENE = 3
    SOURCE_PENALTY_BASE = 0.6  # Score multiplier per consecutive same-source use
    SOURCE_DIVERSITY_BONUS = 0.08  # Score bonus when switching to a different source
    
    def __init__(self, library_path: str, model_name: str = "ViT-B/32"):
        self.library_path = Path(library_path)
        self.device = "cpu"
        
        logger.info("🧠 Loading CLIP model for Chaotic Matching...")
        self.model, _ = clip.load(model_name, device=self.device)
        
        self.loaded_sources: Dict = {}
        self.aliases: Dict[str, str] = {}
        self._load_aliases()

    def _load_aliases(self) -> None:
        """Load character name aliases mappings."""
        aliases_path = self.library_path / "aliases.json"
        if aliases_path.exists():
            try:
                with open(aliases_path, "r", encoding="utf-8") as f:
                    self.aliases = json.load(f)
            except Exception:
                pass

    def _resolve_character_name(self, name: str) -> List[str]:
        """Resolve character name including aliases."""
        if not name:
            return []
        
        names = {name.lower()}
        alias_value = self.aliases.get(name)
        alias_value_lower = self.aliases.get(name.lower())
        if alias_value:
            names.add(alias_value.lower())
        if alias_value_lower:
            names.add(alias_value_lower.lower())
        for alias, full_name in self.aliases.items():
            if name.lower() in {alias.lower(), full_name.lower()}:
                names.add(alias.lower())
                names.add(full_name.lower())
        return list(names)

    def _character_matches(self, requested_name: str, scene_characters: List[str]) -> bool:
        """Match character names by normalized names/aliases, avoiding substring false positives."""
        if not requested_name:
            return True

        requested_names = self._resolve_character_name(requested_name)
        scene_names = set()
        for character in scene_characters:
            scene_names.update(self._resolve_character_name(character))

        for requested in requested_names:
            requested_tokens = re.findall(r"[a-z0-9]+", requested.lower())
            if not requested_tokens:
                continue
            for scene_name in scene_names:
                if requested == scene_name:
                    return True
                scene_tokens = re.findall(r"[a-z0-9]+", scene_name.lower())
                if len(requested_tokens) == 1 and requested_tokens[0] in scene_tokens:
                    return True
                if len(requested_tokens) > 1 and all(token in scene_tokens for token in requested_tokens):
                    return True
        return False

    def _normalize_episode_ranges(
        self,
        episode_time_ranges: Optional[List[Any]]
    ) -> Optional[Dict[Optional[str], List[Tuple[float, float]]]]:
        """
        Normalize legacy global ranges and source-aware ranges.

        Accepted entries:
        - (start, end): applies to every source (legacy)
        - (source_name, start, end): applies only to source_name
        - {"source": source_name, "start": start, "end": end}
        - {"source_alias": source_name, "start": start, "end": end}
        """
        if not episode_time_ranges:
            return None

        normalized: Dict[Optional[str], List[Tuple[float, float]]] = {}
        for item in episode_time_ranges:
            source_name = None
            start = None
            end = None

            if isinstance(item, dict):
                source_name = item.get("source") or item.get("source_alias")
                start = item.get("start")
                end = item.get("end")
            elif isinstance(item, (list, tuple)):
                if len(item) == 2:
                    start, end = item
                elif len(item) == 3:
                    source_name, start, end = item

            if start is None or end is None:
                logger.warning(f"⚠️ Ignoring malformed episode range: {item}")
                continue

            start = float(start)
            end = float(end)
            if end <= start:
                logger.warning(f"⚠️ Ignoring invalid episode range: {item}")
                continue

            normalized.setdefault(source_name, []).append((start, end))

        for ranges in normalized.values():
            ranges.sort(key=lambda value: value[0])
        return normalized or None

    def _allowed_ranges_for_scene(
        self,
        scene: Dict,
        source_name: str,
        range_map: Optional[Dict[Optional[str], List[Tuple[float, float]]]]
    ) -> List[Tuple[float, float]]:
        """Return scene/range intersections for this source."""
        s_start = float(scene["time"]["start"])
        s_end = float(scene["time"]["end"])
        if s_end <= s_start:
            return []

        if not range_map:
            return [(s_start, s_end)]

        ranges = []
        if None in range_map:
            ranges.extend(range_map[None])
        if source_name in range_map:
            ranges.extend(range_map[source_name])

        if not ranges:
            return []

        intersections = []
        for r_start, r_end in ranges:
            start = max(s_start, r_start)
            end = min(s_end, r_end)
            if end > start:
                intersections.append((start, end))
        return intersections

    def _load_source(self, source_name: str) -> Optional[Dict]:
        """Load movie index and embeddings (Copied/Adapted from SmartMatcher)."""
        if source_name in self.loaded_sources:
            return self.loaded_sources[source_name]

        source_dir = self.library_path / source_name
        index_path = source_dir / "master_index.json"
        emb_path = source_dir / "embeddings.npy"

        if not index_path.exists() or not emb_path.exists():
            logger.error(f"❌ Missing index/embeddings for {source_name}")
            return None

        # Load Index
        with open(index_path, 'r') as f:
            index_data = json.load(f)
        
        if isinstance(index_data, dict) and "scenes" in index_data:
            master_index = index_data["scenes"]
            source_video_path = index_data.get("source_video_path")
        else:
            master_index = index_data
            source_video_path = None
        
        # Load Embeddings
        embeddings = np.load(emb_path, allow_pickle=True).item()
        
        valid_scenes = []
        ordered_vectors = []
        
        for scene in master_index:
            s_id = scene['id']
            if s_id in embeddings:
                ordered_vectors.append(embeddings[s_id])
                valid_scenes.append(scene)
        
        if not ordered_vectors:
            return None
        
        matrix = np.array(ordered_vectors)
        norm = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / (norm + 1e-8)

        # Load Character Map (DYNAMIC MAP)
        char_map_path = source_dir / "character_map.json"
        character_map = {}
        if char_map_path.exists():
            try:
                with open(char_map_path, 'r') as f:
                    character_map = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load character map for {source_name}: {e}")

        data = {
            "scenes": valid_scenes,
            "matrix": torch.from_numpy(matrix).float().to(self.device),
            "source_name": source_name,
            "source_video_path": source_video_path,
            "character_map": character_map  # {person_id: "Name"}
        }
        self.loaded_sources[source_name] = data
        return data

    def _encode_text(self, text: str) -> torch.Tensor:
        tokens = clip.tokenize([text], truncate=True).to(self.device)
        with torch.no_grad():
            emb = self.model.encode_text(tokens).float()
            emb /= emb.norm(dim=-1, keepdim=True)
        return emb

    def _get_scene_characters(self, scene: Dict, character_map: Dict) -> List[str]:
        """
        Extract character list using DYNAMIC character map.
        Prioritizes raw_ids mapping over stale 'characters' list.
        """
        content = scene.get("content", {})
        raw_ids = content.get("raw_ids", [])
        
        resolved_names = []
        
        # 1. Try to resolve via ID
        for pid in raw_ids:
            if pid in character_map:
                resolved_names.append(character_map[pid].lower())
                
        # 2. Add existing static names (fallback)
        static_names = [c.lower() for c in content.get("characters", [])]
        resolved_names.extend(static_names)
        
        return list(set(resolved_names))

    def _overlap_duration(
        self,
        start: float,
        end: float,
        used_intervals: List[Tuple[float, float]]
    ) -> float:
        overlap = 0.0
        for used_start, used_end in used_intervals:
            inter_start = max(start, used_start)
            inter_end = min(end, used_end)
            if inter_end > inter_start:
                overlap += inter_end - inter_start
        return overlap

    def _pick_window(
        self,
        allowed_ranges: List[Tuple[float, float]],
        duration: float,
        used_intervals: List[Tuple[float, float]],
        allow_overlap: bool = False
    ) -> Optional[Tuple[float, float]]:
        """
        Pick an in/out window inside allowed ranges while avoiding source-time reuse.

        Chaotic matching intentionally allows the same scene to be used more than
        once, but repeated uses should land on different source frames.
        """
        ranges_that_fit = [
            (start, end) for start, end in allowed_ranges
            if end - start >= duration
        ]

        if not ranges_that_fit:
            if allow_overlap:
                range_start, range_end = max(allowed_ranges, key=lambda item: item[1] - item[0])
                return range_start, range_end
            return None

        zero_overlap = []
        low_overlap = []
        for range_start, range_end in ranges_that_fit:
            max_offset = (range_end - range_start) - duration
            if max_offset <= 0:
                starts = [range_start]
            else:
                starts = []
                offset = 0.0
                while offset <= max_offset:
                    starts.append(range_start + offset)
                    offset += 0.5
                end_start = range_end - duration
                if starts[-1] < end_start:
                    starts.append(end_start)

            for start in starts:
                end = start + duration
                overlap = self._overlap_duration(start, end, used_intervals)
                if overlap <= 0.1:
                    zero_overlap.append(start)
                elif allow_overlap and overlap < duration:
                    low_overlap.append((overlap, start))

        if zero_overlap:
            start = random.choice(zero_overlap)
            return start, start + duration

        if allow_overlap and low_overlap:
            low_overlap.sort(key=lambda item: item[0])
            start = random.choice([item[1] for item in low_overlap[:3]])
            return start, start + duration

        return None

    def _detect_secondary_characters(self, text: str, primary_char: str, active_sources: List[Dict]) -> Optional[str]:
        """
        Scan text for names of other characters present in the sources.
        """
        if not text: return None
        
        # Gather all known names
        all_names = set()
        for src in active_sources:
            cmap = src.get("character_map", {})
            for name in cmap.values():
                all_names.add(name)
        
        for alias, full_name in self.aliases.items():
            all_names.add(alias)
            all_names.add(full_name)
            
        text_lower = text.lower()
        
        detected = []
        for name in sorted(all_names, key=lambda value: (-len(value), value.lower())):
            if name.lower() == "unknown": continue
            if primary_char and name.lower() in primary_char.lower(): continue
            if primary_char and primary_char.lower() in name.lower(): continue
            
            if len(name) < 3: continue
            
            if f" {name.lower()} " in f" {text_lower} " or \
               f" {name.lower()}." in f" {text_lower} " or \
               f" {name.lower()}," in f" {text_lower} ":
                   detected.append(name)
        
        if detected:
            raw = detected[0]
            if raw in self.aliases:
                return self.aliases[raw]
            return raw
            
        return None

    def match(
        self, 
        script_path: str, 
        output_path: str, 
        source_names: List[str],
        episode_time_ranges: Optional[List[Tuple[float, float]]] = None,
        source_selection_mode: str = "score"
    ) -> None:
        """
        Main execution flow for Chaotic Matcher.
        """
        script_path = Path(script_path)
        with open(script_path, 'r') as f:
            script = json.load(f)

        # 1. Load Sources
        active_sources = []
        for src in source_names:
            data = self._load_source(src)
            if data: active_sources.append(data)
        
        if not active_sources:
            logger.error("❌ No valid sources!")
            return

        final_edl = []
        
        # Usage tracking
        # scene_id -> list of float (timestamps in output timeline where it was used)
        scene_usage_timeline: Dict[str, List[float]] = {}
        # scene_id -> usage count
        scene_usage_count: Dict[str, int] = {}
        
        # Source diversity tracking
        last_used_source: Optional[str] = None
        source_consecutive_count: int = 0  # How many times in a row the same source was picked
        source_usage_total: Dict[str, int] = {}  # Total usage per source
        source_used_intervals: Dict[str, List[Tuple[float, float]]] = {}
        
        current_timeline_time = 0.0
        
        num_sources = len(active_sources)
        logger.info(f"🎲 Running CHAOTIC Matcher for {len(script)} segments across {num_sources} sources...")
        if source_selection_mode not in {"score", "alternate"}:
            logger.warning(f"⚠️ Unknown source selection mode '{source_selection_mode}', using score")
            source_selection_mode = "score"
        strict_source_order = [src["source_name"] for src in active_sources]
        next_strict_source_idx = 0

        range_map = self._normalize_episode_ranges(episode_time_ranges)

        if range_map:
            total_ranges = sum(len(ranges) for ranges in range_map.values())
            logger.info(f"⏳ Constraining match to {total_ranges} episode ranges")
        
        for segment in tqdm(script, desc="Chaotic Matching"):
            duration = segment.get("duration", 5.0)
            text_query = segment.get("visual_query", "")
            target_char = segment.get("character")
            
            # Detect Secondary Character
            secondary_char = self._detect_secondary_characters(segment.get("text", ""), target_char, active_sources)
            if secondary_char:
                logger.debug(f"Detected secondary character: {secondary_char} (Primary: {target_char})")

            # --- CANDIDATE SELECTION STRATEGY ---
            # 0. Strict Dual: Match Primary AND Secondary AND Duration
            # 1. Strict: Match Character AND Duration
            # 2. Relaxed Duration: Match Character, allow shorter source and mark it in EDL
            # 3. Visual Only: Ignore Character, Match Duration
            # 4. Desperate: Any scene
            
            strategy_used = "Strict"
            
            # Helper to fetch candidates
            def get_candidates(require_primary=True, require_secondary=False, min_duration=0.0):
                cands = []
                for src_data in active_sources:
                    for i, scene in enumerate(src_data["scenes"]):
                        allowed_ranges = self._allowed_ranges_for_scene(
                            scene,
                            src_data["source_name"],
                            range_map
                        )
                        if not allowed_ranges:
                            continue

                        # Check Duration inside the allowed portion, not the whole scene.
                        max_allowed_duration = max(end - start for start, end in allowed_ranges)
                        if max_allowed_duration < min_duration:
                            continue
                        
                        s_chars = []
                        if require_primary or require_secondary:
                            s_chars = self._get_scene_characters(scene, src_data.get("character_map", {}))

                        # Check Primary
                        if require_primary and target_char:
                            if not self._character_matches(target_char, s_chars):
                                continue
                        
                        # Check Secondary    
                        if require_secondary and secondary_char:
                            if not self._character_matches(secondary_char, s_chars):
                                continue
                        
                        cands.append((i, src_data, allowed_ranges, max_allowed_duration))
                return cands

            # Try 0: Strict Dual + Strict Duration
            valid_indices = []
            if secondary_char:
                valid_indices = get_candidates(require_primary=True, require_secondary=True, min_duration=duration)
                if valid_indices: strategy_used = "Strict_Dual"

            # Try 1: Strict Character + Strict Duration
            if not valid_indices:
                valid_indices = get_candidates(require_primary=bool(target_char), require_secondary=False, min_duration=duration)
                strategy_used = "Strict" # or "Strict_Primary"
            
            # Try 2: Strict Character + Loose Duration (if strict failed)
            if not valid_indices and target_char:
                valid_indices = get_candidates(require_primary=True, require_secondary=False, min_duration=0.0)
                strategy_used = "Character_LooseDur"
            
            # Try 3: Visual Only + Strict Duration (if character failed)
            if not valid_indices:
                valid_indices = get_candidates(require_primary=False, require_secondary=False, min_duration=duration)
                strategy_used = "Visual_StrictDur"
                if target_char:
                    logger.debug(f"⚠️ Character '{target_char}' not found. Falling back to visual match.")
                
            # Try 4: Everything (Desperate)
            if not valid_indices:
                valid_indices = get_candidates(require_primary=False, require_secondary=False, min_duration=0.0)
                strategy_used = "Desperate"

            if not valid_indices:
                # LAST RESORT: grab ANY scene from ANY source to avoid gaps
                logger.warning(f"⚠️ No candidates for '{text_query}'. Using first available scene (last resort).")
                for src_data in active_sources:
                    if src_data["scenes"]:
                        allowed_ranges = self._allowed_ranges_for_scene(
                            src_data["scenes"][0],
                            src_data["source_name"],
                            range_map
                        )
                        if not allowed_ranges:
                            continue
                        valid_indices = [(0, src_data, allowed_ranges, max(end - start for start, end in allowed_ranges))]
                        strategy_used = "LastResort"
                        break
                
                if not valid_indices:
                    logger.error(f"❌ IMPOSSIBLE: No scenes found at all for '{text_query}'")
                    current_timeline_time += duration
                    continue

            # --- RERANKING WITH CLIP + SOURCE DIVERSITY ---
            ranked_candidates = []
            
            if text_query:
                text_emb = self._encode_text(text_query)
                
                for src_data in active_sources:
                    # Filter indices belonging to this source
                    src_matches = [
                        (i, allowed_ranges, max_allowed_duration)
                        for i, src, allowed_ranges, max_allowed_duration in valid_indices
                        if src == src_data
                    ]
                    src_indices = [i for i, _, _ in src_matches]
                    if not src_indices: continue
                    
                    sub_matrix = src_data["matrix"][src_indices]
                    sims = torch.matmul(text_emb, sub_matrix.T).view(-1).cpu().numpy()
                    
                    for k, (idx, allowed_ranges, max_allowed_duration) in enumerate(src_matches):
                        ranked_candidates.append({
                            "score": float(sims[k]),
                            "source": src_data,
                            "scene": src_data["scenes"][idx],
                            "allowed_ranges": allowed_ranges,
                            "max_allowed_duration": max_allowed_duration
                        })
            else:
                for i, src_data, allowed_ranges, max_allowed_duration in valid_indices:
                    ranked_candidates.append({
                        "score": random.random(),
                        "source": src_data,
                        "scene": src_data["scenes"][i],
                        "allowed_ranges": allowed_ranges,
                        "max_allowed_duration": max_allowed_duration
                    })
            
            # --- APPLY SOURCE DIVERSITY ADJUSTMENT ---
            # When multiple sources are available, penalize scores for sources used
            # consecutively and reward switching to a different source
            if num_sources > 1 and last_used_source is not None:
                for cand in ranked_candidates:
                    cand_source = cand["source"]["source_name"]
                    if cand_source == last_used_source:
                        # Exponential penalty for consecutive same-source usage
                        penalty = self.SOURCE_PENALTY_BASE ** source_consecutive_count
                        cand["adjusted_score"] = cand["score"] * penalty
                    else:
                        # Bonus for switching to a different source
                        cand["adjusted_score"] = cand["score"] + self.SOURCE_DIVERSITY_BONUS
                # Sort by adjusted_score for source diversity
                ranked_candidates.sort(key=lambda x: x.get("adjusted_score", x["score"]), reverse=True)
            else:
                ranked_candidates.sort(key=lambda x: x["score"], reverse=True)
            
            # --- SELECTION WITH LIMITS ---
            selected_match = None

            def candidate_is_available(cand):
                s_id = cand["scene"]["id"]
                usage_key = (cand["source"]["source_name"], s_id)
                source_path = cand["source"].get("source_video_path") or cand["source"]["source_name"]
                
                # Max Uses Check
                if scene_usage_count.get(usage_key, 0) >= self.MAX_USES_PER_SCENE:
                    return False

                if not self._pick_window(
                    cand["allowed_ranges"],
                    duration,
                    source_used_intervals.get(source_path, []),
                    allow_overlap=False
                ):
                    return False
                
                # Cooldown Check
                if usage_key in scene_usage_timeline:
                    is_cooling = False
                    cooldown = min(self.COOLDOWN_MAX, current_timeline_time * self.COOLDOWN_RATIO) if current_timeline_time > 0 else 5.0
                    for t in scene_usage_timeline[usage_key]:
                        if abs(current_timeline_time - t) < cooldown:
                            is_cooling = True
                            break
                    if is_cooling:
                        return False
                return True

            def select_best_for_source(source_name, respect_limits=True):
                for cand in ranked_candidates:
                    if cand["source"]["source_name"] != source_name:
                        continue
                    if not respect_limits or candidate_is_available(cand):
                        return cand
                return None

            if source_selection_mode == "alternate" and num_sources > 1:
                # Try the next source in group order first, then rotate through the
                # remaining sources only if the target source cannot satisfy this segment.
                for offset in range(num_sources):
                    source_idx = (next_strict_source_idx + offset) % num_sources
                    selected_match = select_best_for_source(strict_source_order[source_idx], respect_limits=True)
                    if selected_match:
                        next_strict_source_idx = (source_idx + 1) % num_sources
                        break

                if not selected_match:
                    for offset in range(num_sources):
                        source_idx = (next_strict_source_idx + offset) % num_sources
                        selected_match = select_best_for_source(strict_source_order[source_idx], respect_limits=False)
                        if selected_match:
                            next_strict_source_idx = (source_idx + 1) % num_sources
                            logger.warning(f"⚠️ Exhausted limits for '{text_query}'. Reusing top match from alternating source.")
                            break
            else:
                # First pass: try to respect limits
                for cand in ranked_candidates:
                    if candidate_is_available(cand):
                        selected_match = cand
                        break
            
            # Second pass: Ignore cooldown/limits if necessary (Fail safe)
            if not selected_match and ranked_candidates:
                selected_match = ranked_candidates[0]
                logger.warning(f"⚠️ Exhausted limits for '{text_query}'. Reusing top match ignoring cooldown.")

            if selected_match:
                scene = selected_match["scene"]
                src_data = selected_match["source"]
                
                allowed_ranges = selected_match.get("allowed_ranges") or [
                    (float(scene["time"]["start"]), float(scene["time"]["end"]))
                ]
                source_path = src_data.get("source_video_path") or src_data["source_name"]
                
                # Handling Duration
                picked_window = self._pick_window(
                    allowed_ranges,
                    duration,
                    source_used_intervals.get(source_path, []),
                    allow_overlap=False
                )
                if not picked_window:
                    picked_window = self._pick_window(
                        allowed_ranges,
                        duration,
                        source_used_intervals.get(source_path, []),
                        allow_overlap=True
                    )
                if picked_window:
                    in_point, out_point = picked_window
                    if out_point - in_point < duration - 0.001:
                        strategy_used = f"{strategy_used}_ShortSource"
                else:
                    range_start, range_end = max(allowed_ranges, key=lambda item: item[1] - item[0])
                    in_point = range_start
                    out_point = range_end
                    strategy_used = f"{strategy_used}_ShortSource"
                
                # Record Usage
                s_id = scene["id"]
                usage_key = (src_data["source_name"], s_id)
                scene_usage_count[usage_key] = scene_usage_count.get(usage_key, 0) + 1
                if usage_key not in scene_usage_timeline:
                    scene_usage_timeline[usage_key] = []
                scene_usage_timeline[usage_key].append(current_timeline_time)
                source_used_intervals.setdefault(source_path, []).append((in_point, out_point))
                
                # Track source diversity
                chosen_source = src_data["source_name"]
                if chosen_source == last_used_source:
                    source_consecutive_count += 1
                else:
                    source_consecutive_count = 1
                last_used_source = chosen_source
                source_usage_total[chosen_source] = source_usage_total.get(chosen_source, 0) + 1

                final_edl.append({
                    "segment_id": segment.get("segment_id", 0),
                    "text": segment.get("text", ""),
                    "source_file": scene["visual"]["path"],
                    "source_project_alias": chosen_source,
                    "source_video_path": src_data["source_video_path"],
                    "scene_id": s_id,
                    "in_point": in_point,
                    "out_point": out_point,
                    "duration": out_point - in_point,
                    "target_duration": duration,
                    "timeline_start": segment.get("start", 0.0),
                    "match_score": selected_match["score"],
                    "match_type": strategy_used
                })
            
            # Always advance timeline to maintain sync
            current_timeline_time += duration

        # Save Output
        with open(output_path, 'w') as f:
            json.dump(final_edl, f, indent=2)
        
        # Log source distribution
        if source_usage_total:
            dist_str = ", ".join(f"{k}: {v}" for k, v in sorted(source_usage_total.items(), key=lambda x: -x[1]))
            logger.info(f"📊 Source distribution: {dist_str}")
        
        logger.info(f"✅ Chaotic Match Complete. {len(final_edl)} cuts.")
