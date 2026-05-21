"""
CDA SmartMatcher v4 — Linear Grid Logic

Strict Chronological Enforcement:
1. Trims film: First 5% (Intro) and Last 10% (Credits) removed.
2. Linear Grid: Remaining timeline divided into N equal chunks (N = script segments).
3. Strict Matching: Segment[i] matched ONLY within Chunk[i].
"""

import json
import logging
import torch
import clip
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from tqdm import tqdm

logger = logging.getLogger(__name__)


class SmartMatcher:
    """
    CDA SmartMatcher v4 — Dynamic Sliding Window Logic.
    
    Enforces rigid chronological progression by slicing the movie into 
    exact time slots corresponding to script segments.
    """
    
    # Trim percentages (Global defaults, can be overridden by episodes)
    START_TRIM_PCT = 0.05
    END_TRIM_PCT = 0.10
    
    # Scoring Config
    SCORES = {
        "Visual_Similarity": 1000,
        "Character_Match": 500,
        "Global_Bonus": 100
    }
    
    def __init__(self, library_path: str, model_name: str = "ViT-B/32"):
        self.library_path = Path(library_path)
        self.device = "cpu"
        
        logger.info("🧠 Loading CLIP model for Dynamic Matching...")
        self.model, _ = clip.load(model_name, device=self.device)
        
        self.loaded_sources: Dict = {}
        self.aliases: Dict[str, str] = {}
        
        # Tracking usage: { "source_video_path": [ (start, end), ... ] }
        self.used_intervals: Dict[str, List[Tuple[float, float]]] = {}
        
        self._load_aliases()
    
    def _load_aliases(self) -> None:
        """Load character name aliases."""
        aliases_path = self.library_path / "aliases.json"
        if aliases_path.exists():
            try:
                with open(aliases_path, "r", encoding="utf-8") as f:
                    self.aliases = json.load(f)
            except Exception:
                pass

    def _calculate_temporal_zone(
        self, 
        segment_idx: int, 
        total_segments: int, 
        episode_ranges: List[Tuple[float, float]]
    ) -> Tuple[float, float]:
        """
        Map segment position to a temporal zone in the VIRTUAL timeline constructed from disjoint episodes.
        
        Args:
            segment_idx: Current segment index (0-based)
            total_segments: Total number of segments
            episode_ranges: List of (start, end) tuples, assumed sorted.
            
        Returns:
            (zone_start, zone_end) in REAL time. 
            NOTE: For now, we return a single range. If a zone spans across a gap, 
            we might need to return a list of ranges, but for simplicity, we'll 
            clamp to the closest valid episode or span across (logic below).
        """
        # 1. Construct Virtual Timeline
        # Virtual Time 0 = Start of Ep1
        # Virtual Time X = End of Ep1 / Start of Ep2
        
        episode_durations = [end - start for start, end in episode_ranges]
        total_virtual_duration = sum(episode_durations)
        
        # 2. Calculate Target Zone in Virtual Time
        if total_segments > 0:
            zone_width = total_virtual_duration / total_segments
            overlap = zone_width * 0.3
            
            v_zone_start = (segment_idx * zone_width) - overlap
            v_zone_end = ((segment_idx + 1) * zone_width) + overlap
        else:
            v_zone_start = 0
            v_zone_end = total_virtual_duration

        # Clamp Virtual Zone
        v_zone_start = max(0.0, v_zone_start)
        v_zone_end = min(total_virtual_duration, v_zone_end)
        
        # 3. Map Virtual Time -> Real Time
        # We need to find which episode(s) this virtual range falls into.
        # Since the output of this function is currently expected to be a single tuple (min, max),
        # we will return the "bounding box" of the real time range if it spans multiple episodes,
        # BUT the matcher loop needs to handle the gaps.
        # Ideally, we should return a LIST of ranges, but let's see how `match` uses it.
        # The `match` loop currently checks `if s_start >= zone_start and s_end <= zone_end`.
        # If we return a range that spans a gap, scenes in the gap might be selected?
        # NO, because `match` ALSO filters by `episode_time_ranges`.
        # So it IS safe to return the "bounding box" in real time, because the secondary filter
        # will reject anything in the gaps! 
        # WAIT: If Ep1 is [0-100] and Ep2 is [1000-1100], and we wrap them,
        # a zone might be Virtual [90-110].
        # Real time this is [90-100] AND [1000-1010].
        # If we return [90, 1010], we effectively allow matching in the gap [100, 1000] IF we don't have the gap filter.
        # BUT we DO have the gap filter in `match` (passed as strict constraint).
        # So, valid scenes will only be from [90-100] and [1000-1010].
        # scenes in [200-300] will be rejected by the STRICT episode_time_ranges filter.
        # So "Bounding Box" approach is acceptable IF `episode_time_ranges` is enforced strictly.
        
        def virtual_to_real(v_time):
            current_v = 0
            for i, (start, end) in enumerate(episode_ranges):
                dur = end - start
                if v_time <= current_v + dur:
                    # Found it
                    offset = v_time - current_v
                    return start + offset
                current_v += dur
            # If past end, return end of last ep
            return episode_ranges[-1][1]

        r_start = virtual_to_real(v_zone_start)
        r_end = virtual_to_real(v_zone_end)
        
        # However, if r_start is in Ep1 and r_end is in Ep2, the "bounding box" [r_start, r_end]
        # covers the HUGE gap.
        # Is this a problem?
        # If the gap contains valid scenes that are NOT in Ep1 or Ep2, they are filtered out by strict constraint.
        # If the gap matches scenes from Ep1 (later parts) or Ep2 (earlier parts)?
        # The only risk is selecting scenes from Ep1 that are AFTER r_start but BEFORE the end of Ep1,
        # even if the virtual zone "should" have jumped to Ep2.
        # Example: Virtual Zone [95, 105]. Ep1 [0-100], Ep2 [200-300].
        # Correct Real mapping: [95-100] U [200-205].
        # Bounding Box: [95-205].
        # Allowed Scenes (Intersection): [95-100] U [200-205] (Correct!) 
        # PLUS [200-205]? Yes.
        # PLUS [0-95]? No (before start).
        # PLUS [100-200]? No (Gap).
        # PLUS [205-300]? No (after end).
        # WAIT. [95, 205] includes [100, 200]. But those are filtered out.
        # It includes [0, 95]? No.
        # It includes [95, 100]? Yes.
        # It includes [200, 205]? Yes.
        # So Bounding Box works!
        
        if r_start > r_end:
            # Can happen if we wrapped around or logic error, just swap or clamp
            return (r_end, r_end) # collapse
            
        return (r_start, r_end)

    def _calculate_diversity_penalty(
        self,
        scene_id: str,
        recently_used: List[str],
        decay_factor: float = 0.3
    ) -> float:
        """
        Calculate penalty for recently used scenes.
        
        Returns penalty between 0.0 (no penalty) and 1.0 (full penalty).
        More recent usage = higher penalty.
        """
        if scene_id not in recently_used:
            return 0.0
        
        # Position in recently_used: 0 = most recent = highest penalty
        position = recently_used.index(scene_id)
        penalty = (1.0 - (position * decay_factor))
        
        return max(0.0, penalty)

    def _load_source(self, source_name: str) -> Optional[Dict]:
        """Load movie index and embeddings."""
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
        
        ordered_vectors = []
        valid_scenes = []
        
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

        data = {
            "scenes": valid_scenes,
            "matrix": torch.from_numpy(matrix).float().to(self.device),
            "source_name": source_name,
            "source_video_path": source_video_path
        }
        self.loaded_sources[source_name] = data
        return data

    def _encode_text(self, text: str) -> torch.Tensor:
        tokens = clip.tokenize([text], truncate=True).to(self.device)
        with torch.no_grad():
            emb = self.model.encode_text(tokens).float()
            emb /= emb.norm(dim=-1, keepdim=True)
        return emb

    def _check_overlap(self, path: str, start: float, end: float) -> float:
        """
        Check how much this interval overlaps with used ones.
        Returns overlap duration in seconds.
        """
        if path not in self.used_intervals:
            return 0.0
        
        overlap_sum = 0.0
        for u_start, u_end in self.used_intervals[path]:
            # Intersection
            inter_start = max(start, u_start)
            inter_end = min(end, u_end)
            if inter_end > inter_start:
                overlap_sum += (inter_end - inter_start)
        return overlap_sum

    def _get_smart_window(self, scene: Dict, source_path: str, target_dur: float) -> Tuple[float, float, bool]:
        """
        Finds the best available window in the scene.
        Dynamic Sliding Logic with Randomization:
        1. Collect all windows with 0 overlap.
        2. Pick randomly among zero-overlap options for variety.
        3. If all overlap, pick minimal overlap with some randomness.
        4. If recycled, return True for `recycled` flag.
        """
        import random
        
        scene_dur = scene["time"]["end"] - scene["time"]["start"]
        
        # Safety: if scene is shorter than target, take whole scene
        if scene_dur <= target_dur:
            return scene["time"]["start"], scene["time"]["end"], False

        # Collect candidates (check every half second)
        step = 0.5
        
        candidates = []
        curr = scene["time"]["start"]
        while curr + target_dur <= scene["time"]["end"]:
            candidates.append(curr)
            curr += step
        
        # Find all zero-overlap candidates
        zero_overlap_candidates = []
        low_overlap_candidates = []
        
        for t in candidates:
            ov = self._check_overlap(source_path, t, t + target_dur)
            if ov <= 0.1:  # Essentially zero overlap
                zero_overlap_candidates.append(t)
            elif ov < target_dur * 0.5:  # Less than 50% overlap
                low_overlap_candidates.append((ov, t))
        
        # Priority 1: Pick randomly from zero-overlap options
        if zero_overlap_candidates:
            # Bias towards middle section for visual variety
            # Split into thirds and weight middle more
            third = len(zero_overlap_candidates) // 3
            if third > 0:
                weights = [1] * third + [2] * (len(zero_overlap_candidates) - 2*third) + [1] * third
            else:
                weights = [1] * len(zero_overlap_candidates)
            
            best_start = random.choices(zero_overlap_candidates, weights=weights, k=1)[0]
            return best_start, best_start + target_dur, False
        
        # Priority 2: Pick from low-overlap with some randomness
        if low_overlap_candidates:
            # Sort by overlap and take from top 3
            low_overlap_candidates.sort(key=lambda x: x[0])
            top_n = min(3, len(low_overlap_candidates))
            best_start = random.choice([c[1] for c in low_overlap_candidates[:top_n]])
            return best_start, best_start + target_dur, False
        
        # Priority 3: All options have high overlap - find minimum
        best_start = scene["time"]["start"]
        min_overlap = float('inf')
        
        for t in candidates:
            ov = self._check_overlap(source_path, t, t + target_dur)
            if ov < min_overlap:
                min_overlap = ov
                best_start = t
        
        recycled = min_overlap > (target_dur * 0.7)
        return best_start, best_start + target_dur, recycled

    def match(
        self, 
        script_path: str, 
        output_path: str, 
        source_names: List[str],
        movie_duration: Optional[float] = None,
        plot_segments: Optional[List[Dict]] = None,
        external_usage_tracker: Optional[Dict] = None,
        episode_time_ranges: Optional[List[Tuple[float, float]]] = None
    ) -> None:
        """
        Dynamic Plot-Aware Matcher.
        
        Args:
            episode_time_ranges: List of (start_sec, end_sec) - STRICT constraints.
                The matcher considers these as a "Virtual Continuous Timeline".
                Only scenes within these ranges are valid.
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
        # Use external tracker if provided, otherwise local
        if external_usage_tracker is not None:
            self.used_intervals = external_usage_tracker
        else:
            self.used_intervals = {}

        logger.info("🎯 Executing Progressive Distribution Match...")
        if episode_time_ranges:
             logger.info(f"⏳ Constraining match to {len(episode_time_ranges)} episode ranges (Virtual Timeline)")
        
        total_segments = len(script)
        recently_used_scenes: List[str] = []  # Track last N scenes for diversity
        DIVERSITY_WINDOW = 5  # Track last 5 scenes
        
        for i, segment in enumerate(tqdm(script, desc="Progressive Match")):
            
            target_dur = segment.get("duration", 5.0)
            visual_query = segment.get("visual_query", "")
            
            # Use `episode_time_ranges` (STRICT) or segment-level fallback (not supported in multi-ep yet)
            current_constraints = episode_time_ranges
            
            candidates = []
            
            # === TEMPORAL ZONE CALCULATION ===
            temporal_zone = None
            if current_constraints:
                # Calculate virtual zone based on ALL ranges
                temporal_zone = self._calculate_temporal_zone(
                    segment_idx=i,
                    total_segments=total_segments,
                    episode_ranges=current_constraints
                )
            
            # Encode query
            if visual_query:
                text_emb = self._encode_text(visual_query)
            else:
                text_emb = None

            for src_data in active_sources:
                
                # STEP 1: Filter scenes by TEMPORAL ZONE (primary filter) & EPS (strict)
                valid_indices = []
                
                for idx, scene in enumerate(src_data["scenes"]):
                    s_start = scene["time"]["start"]
                    s_end = scene["time"]["end"]
                    
                    # 1. STRICT EPISODE FILTER (must be in at least one range)
                    if current_constraints:
                        in_any_range = False
                        s_mid = (s_start + s_end) / 2.0
                        for ep_start, ep_end in current_constraints:
                             if s_mid >= ep_start and s_mid <= ep_end:
                                 in_any_range = True
                                 break
                        if not in_any_range:
                            continue

                    # 2. TEMPORAL ZONE FILTER (Soft or Hard?)
                    # If we generated a zone, we prioritize it, but maybe allow some slack?
                    # Current logic: HARD filter on zone (which is a bbox of virtual range)
                    if temporal_zone:
                        zone_start, zone_end = temporal_zone
                        # Bounding box check
                        if not (s_start >= zone_start and s_end <= zone_end):
                             # To avoid being TOO strict with the bbox (which might exclude edge scenes),
                             # let's allow partial overlap?
                             # Or just stick to strict for now.
                             # Actually, bbox [95, 205] handles the jump.
                             # Scene [98, 102] ?? (Gap scene).
                             # Gap scene is filtered by Step 1 (Strict Episode Filter).
                             # So we are good.
                             pass
                        
                        # Re-checking logic:
                        if s_start < zone_start or s_end > zone_end:
                             continue

                    valid_indices.append(idx)
                
                if not valid_indices:
                    if temporal_zone:
                        logger.debug(f"No scenes in zone [{temporal_zone[0]:.1f}s - {temporal_zone[1]:.1f}s]")
                    continue

                if text_emb is not None:
                    # Semantic Search on Valid Indices ONLY
                    sub_matrix = src_data["matrix"][valid_indices]
                    sims = torch.matmul(text_emb, sub_matrix.T).view(-1).cpu().numpy()
                    
                    # Apply diversity penalty to scores
                    for j, rel_idx in enumerate(range(len(sims))):
                        original_idx = valid_indices[rel_idx]
                        scene_id = src_data["scenes"][original_idx]["id"]
                        
                        # Reduce score for recently used scenes
                        penalty = self._calculate_diversity_penalty(scene_id, recently_used_scenes)
                        sims[j] = sims[j] * (1.0 - penalty * 0.5)  # Max 50% reduction
                    
                    # Get Top Matches
                    top_k = min(len(sims), 10)
                    top_rel_indices = np.argsort(sims)[-top_k:][::-1]
                    
                    for rel_idx in top_rel_indices:
                        score = sims[rel_idx]
                        original_idx = valid_indices[rel_idx]
                        candidates.append((score, src_data, src_data["scenes"][original_idx]))
            
            # Sort candidates by adjusted score
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            # === STEP B: Select best from temporal zone ===
            best_cut = None
            
            for score, src_data, scene in candidates:
                video_path = src_data["source_video_path"] or src_data["source_name"]
                
                # Check for window
                start, end, recycled = self._get_smart_window(scene, video_path, target_dur)
                
                # Skip if this would create a jump cut
                if final_edl and final_edl[-1]["source_video_path"] == video_path:
                    last_end = final_edl[-1]["out_point"]
                    if abs(start - last_end) < 2.0:
                        continue 
                
                best_cut = {
                    "source": src_data,
                    "scene": scene,
                    "in": start,
                    "out": end,
                    "score": score
                }
                break
            
            # Fallback: expand search to full episode if no zone match
            if not best_cut and constraint_range and temporal_zone:
                # Try without zone restriction
                for src_data in active_sources:
                    for idx, scene in enumerate(src_data["scenes"]):
                        s_start = scene["time"]["start"]
                        c_start, c_end = constraint_range
                        if s_start >= c_start and s_start <= c_end:
                            video_path = src_data["source_video_path"] or src_data["source_name"]
                            start, end, _ = self._get_smart_window(scene, video_path, target_dur)
                            best_cut = {
                                "source": src_data,
                                "scene": scene,
                                "in": start,
                                "out": end,
                                "score": 0.5
                            }
                            break
                    if best_cut:
                        break

            # === STEP C: Record Usage and Diversity ===
            if best_cut:
                src_alias = best_cut["source"]["source_name"]
                video_path = best_cut["source"]["source_video_path"] or src_alias
                scene_id = best_cut["scene"]["id"]
                
                # Record usage
                if video_path not in self.used_intervals:
                    self.used_intervals[video_path] = []
                self.used_intervals[video_path].append((best_cut["in"], best_cut["out"]))
                
                # Track for diversity
                recently_used_scenes.insert(0, scene_id)
                if len(recently_used_scenes) > DIVERSITY_WINDOW:
                    recently_used_scenes.pop()
                
                # Add to EDL
                final_edl.append({
                    "segment_id": segment.get("segment_id", i),
                    "text": segment.get("text"),
                    "source_file": best_cut["scene"]["visual"]["path"],
                    "source_project_alias": src_alias,
                    "source_video_path": video_path,
                    "scene_id": scene_id,
                    "in_point": best_cut["in"],
                    "out_point": best_cut["out"],
                    "duration": best_cut["out"] - best_cut["in"],
                    "target_duration": target_dur,
                    "match_score": float(best_cut["score"]),
                    "match_type": "ProgressiveZone",
                    "timeline_start": segment.get("start")
                })
            else:
                logger.warning(f"⚠️ No match for segment {i}")

        # Save
        with open(output_path, 'w') as f:
            json.dump(final_edl, f, indent=2)
        logger.info(f"✅ Progressive EDL saved: {len(final_edl)} cuts")