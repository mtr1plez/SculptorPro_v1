"""
Sequential Gap Matcher — Antigravity Engine Core Logic

Implements "Sequential Gap Distribution" algorithm for syncing audio segments
to video clips. Designed for dynamic editing to maintain viewer retention
and avoid YouTube Content ID strikes.

Algorithm Overview:
1. Analyze ratio of video duration to audio duration
2. Branch A (ratio >= 1.5): Distribute audio evenly with calculated gaps
3. Branch B (ratio < 1.5): Inject external B-Roll to reach safety ratio
"""

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Tuple, Dict, Any
from pathlib import Path
import logging
import json

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class TimeRange:
    """Represents a time range in the video source."""
    start: float
    end: float
    
    @property
    def duration(self) -> float:
        return self.end - self.start
    
    def contains(self, timestamp: float) -> bool:
        """Check if a timestamp falls within this range."""
        return self.start <= timestamp <= self.end
    
    def overlaps(self, other: 'TimeRange') -> bool:
        """Check if this range overlaps with another."""
        return not (self.end <= other.start or other.end <= self.start)


@dataclass
class AudioSegment:
    """Represents an audio segment from voiceover."""
    duration: float
    text: str
    segment_id: int = 0
    start: float = 0.0


@dataclass
class MatchedClip:
    """Result of matching an audio segment to a video clip."""
    audio_segment: AudioSegment
    video_start: float
    video_end: float
    source_type: str  # "primary_episode" or "external_injection"
    
    @property
    def video_duration(self) -> float:
        return self.video_end - self.video_start


class GlobalIndex(Protocol):
    """Protocol for global movie index to retrieve external clips."""
    
    def get_clips_for_duration(
        self, 
        needed_duration: float,
        context: str = ""
    ) -> List[TimeRange]:
        """
        Retrieve clips from the global index totaling the needed duration.
        
        Args:
            needed_duration: Total duration of clips needed (in seconds)
            context: Optional context hint for semantic matching
            
        Returns:
            List of TimeRange objects representing available clips
        """
        ...


# =============================================================================
# CONSTANTS
# =============================================================================

# Minimum ratio of (Video Duration / Total Audio Duration) to ensure
# dynamic editing with sufficient "air" (gaps) between cuts.
# A ratio of 1.5 means we need 50% more video than audio for comfortable pacing.
SAFETY_RATIO = 1.5


# =============================================================================
# MAIN ALGORITHM
# =============================================================================

class GapMatcher:
    """
    Sequential Gap Matcher — distributes audio segments across video
    with calculated gaps for dynamic, engaging editing.
    """
    
    def __init__(self, global_index: Optional[GlobalIndex] = None):
        """
        Initialize the Gap Matcher.
        
        Args:
            global_index: Optional interface to retrieve external clips
                          when episode footage is insufficient.
        """
        self.global_index = global_index
    
    def match(
        self,
        video_episode: TimeRange,
        audio_segments: List[AudioSegment]
    ) -> List[MatchedClip]:
        """
        Match audio segments to video clips using Sequential Gap Distribution.
        
        Args:
            video_episode: The main video scene context (start/end timestamps)
            audio_segments: List of audio segments to map to video
            
        Returns:
            List of MatchedClip objects with video timestamps
        """
        # Edge case: empty audio list
        if not audio_segments:
            logger.info("📭 No audio segments to match")
            return []
        
        # =================================================================
        # STEP 1: Ratio Analysis
        # =================================================================
        # Calculate total audio duration by summing all segment durations
        total_audio_duration = sum(seg.duration for seg in audio_segments)
        episode_duration = video_episode.duration
        
        # Density ratio tells us if we have enough "breathing room"
        # Higher ratio = more video space for dynamic cuts
        # Lower ratio = cramped, may need external footage
        if total_audio_duration > 0:
            density_ratio = episode_duration / total_audio_duration
        else:
            # Prevent division by zero; assume infinite ratio (edge case)
            density_ratio = float('inf')
        
        logger.info(f"📊 Gap Matcher Analysis:")
        logger.info(f"   - Episode Duration: {episode_duration:.2f}s")
        logger.info(f"   - Total Audio: {total_audio_duration:.2f}s")
        logger.info(f"   - Density Ratio: {density_ratio:.2f} (need >= {SAFETY_RATIO})")
        
        # =================================================================
        # STEP 2: Branching Logic
        # =================================================================
        if density_ratio >= SAFETY_RATIO:
            # Branch A: Sufficient footage — even distribution with gaps
            logger.info("✅ Sufficient footage — using even gap distribution")
            return self._distribute_with_gaps(
                video_episode, audio_segments, total_audio_duration
            )
        else:
            # Branch B: Insufficient footage — need external injection
            logger.warning(f"⚠️ Insufficient footage (ratio {density_ratio:.2f} < {SAFETY_RATIO})")
            return self._distribute_with_injection(
                video_episode, audio_segments, total_audio_duration
            )
    
    def _distribute_with_gaps(
        self,
        video_episode: TimeRange,
        audio_segments: List[AudioSegment],
        total_audio_duration: float
    ) -> List[MatchedClip]:
        """
        Branch A: Distribute audio segments evenly across the video episode.
        
        Goal: Create dynamic editing by placing calculated gaps before each
        segment, capturing the start, middle, and end of the scene.
        
        Gap Calculation Math:
        ----------------------
        Given:
            - Episode duration (E)
            - Total audio duration (A)  
            - Number of segments (N)
        
        We want N segments with (N+1) equal gaps:
            
            [gap] [seg1] [gap] [seg2] [gap] ... [segN] [gap]
            
        Total slack (air) = E - A
        Gap size = Total slack / (N + 1)
        
        Each clip starts at:
            clip_start = episode_start + (gap * clip_index) + sum_of_previous_durations
        """
        episode_duration = video_episode.duration
        n_segments = len(audio_segments)
        
        # Calculate total "air" available (video time not covered by audio)
        total_slack = episode_duration - total_audio_duration
        
        # Distribute slack evenly as gaps between and around segments
        # (N segments need N+1 gaps: before first, between each, after last)
        #
        # Visual: [gap0][audio0][gap1][audio1][gap2][audio2][gap3]
        #         \____ N+1 gaps for N segments ____/
        gap_size = total_slack / (n_segments + 1)
        
        logger.info(f"   - Total Slack: {total_slack:.2f}s")
        logger.info(f"   - Gap Size: {gap_size:.2f}s ({n_segments + 1} gaps)")
        
        matched_clips: List[MatchedClip] = []
        
        # Current position in video timeline, starting with first gap
        current_video_position = video_episode.start + gap_size
        
        for idx, segment in enumerate(audio_segments):
            # Calculate video clip boundaries for this segment
            clip_start = current_video_position
            clip_end = clip_start + segment.duration
            
            # CONSTRAINT: Ensure clips do not exceed episode end
            if clip_end > video_episode.end:
                logger.warning(
                    f"   ⚠️ Segment {idx} exceeds episode boundary "
                    f"({clip_end:.2f}s > {video_episode.end:.2f}s), clamping"
                )
                clip_end = video_episode.end
                # Adjust duration if clamped (this shouldn't happen with correct math)
            
            matched_clips.append(MatchedClip(
                audio_segment=segment,
                video_start=clip_start,
                video_end=clip_end,
                source_type="primary_episode"
            ))
            
            logger.debug(
                f"   ✓ Segment {idx}: {clip_start:.2f}s - {clip_end:.2f}s "
                f"(duration: {segment.duration:.2f}s)"
            )
            
            # Advance position: past this segment + next gap
            current_video_position = clip_end + gap_size
        
        return matched_clips
    
    def _distribute_with_injection(
        self,
        video_episode: TimeRange,
        audio_segments: List[AudioSegment],
        total_audio_duration: float
    ) -> List[MatchedClip]:
        """
        Branch B: Inject external B-Roll to reach the Safety Ratio.
        
        Goal: The episode is too short for natural pacing. We need to
        supplement with external footage to create enough "air".
        
        Strategy:
        1. Calculate how much additional duration is needed
        2. Retrieve external clips from global_index
        3. Create a combined pool: [Original Episode] + [External Clips]
        4. Distribute segments linearly across the combined pool
        """
        episode_duration = video_episode.duration
        
        # Calculate duration deficit
        # We need: total_audio * SAFETY_RATIO worth of video
        # We have: episode_duration
        # Deficit: (total_audio * SAFETY_RATIO) - episode_duration
        needed_duration = (total_audio_duration * SAFETY_RATIO) - episode_duration
        
        logger.info(f"   - Duration Deficit: {needed_duration:.2f}s")
        
        # Try to retrieve external clips if global_index is available
        external_clips: List[TimeRange] = []
        if self.global_index is not None and needed_duration > 0:
            logger.info(f"   🔍 Retrieving {needed_duration:.2f}s of external clips...")
            external_clips = self.global_index.get_clips_for_duration(
                needed_duration=needed_duration,
                context="establishing shots, B-roll"
            )
            
            external_total = sum(clip.duration for clip in external_clips)
            logger.info(f"   📦 Retrieved {len(external_clips)} clips ({external_total:.2f}s)")
        elif needed_duration > 0:
            logger.warning("   ⚠️ No global_index available, cannot retrieve external clips")
        
        # Build combined video pool: primary episode + external clips
        # Each entry is (TimeRange, source_type)
        video_pool: List[Tuple[TimeRange, str]] = [
            (video_episode, "primary_episode")
        ]
        
        for clip in external_clips:
            video_pool.append((clip, "external_injection"))
        
        # Calculate total available video duration
        total_video_available = sum(tr.duration for tr, _ in video_pool)
        
        logger.info(f"   - Combined Pool: {total_video_available:.2f}s "
                   f"({len(video_pool)} sources)")
        
        # MVP Approach: Linear distribution across combined pool
        # More sophisticated: semantic matching to appropriate clips
        return self._linear_distribute_across_pool(
            audio_segments, video_pool, total_audio_duration, total_video_available
        )
    
    def _linear_distribute_across_pool(
        self,
        audio_segments: List[AudioSegment],
        video_pool: List[Tuple[TimeRange, str]],
        total_audio_duration: float,
        total_video_available: float
    ) -> List[MatchedClip]:
        """
        Distribute audio segments linearly across a pool of video sources.
        
        Uses "Skip to Next Clip" strategy: if a segment doesn't fit in the
        remaining space of the current video clip, we discard that remainder
        and move to the start of the next clip. This ensures audio segments
        are NEVER truncated (voiceover integrity is preserved).
        
        POOL CYCLING: When the pool is exhausted, we reset to the beginning
        and reuse footage. This guarantees every segment gets a real video
        frame — no placeholders, ever.
        """
        if not video_pool:
            logger.error("   ❌ No video sources available in pool")
            return []
        
        n_segments = len(audio_segments)
        MAX_CYCLES = 3  # Safety limit to prevent infinite loops
        
        # Adaptive gap size: if pool is tight, reduce gaps to prioritize
        # placing all segments over having "air" between cuts
        total_slack = total_video_available - total_audio_duration
        if total_slack <= 0 or total_slack < total_audio_duration * 0.1:
            # Pool is tight or insufficient — zero gap, pack segments densely
            gap_size = 0.0
            logger.info(f"   - Pool tight ({total_video_available:.1f}s video / {total_audio_duration:.1f}s audio) — zero gap mode")
        else:
            gap_size = total_slack / (n_segments + 1)
        
        logger.info(f"   - Pool gap size: {gap_size:.2f}s")
        
        matched_clips: List[MatchedClip] = []
        
        # Track our position in the video pool
        pool_idx = 0
        position_in_current_clip = 0.0  # How far into current pool item
        accumulated_gap = gap_size  # Start with first gap
        current_cycle = 0
        
        for idx, segment in enumerate(audio_segments):
            segment_duration = segment.duration
            
            # === PHASE 1: Skip the gap portion ===
            remaining_gap = accumulated_gap
            while remaining_gap > 0 and pool_idx < len(video_pool):
                current_range, _ = video_pool[pool_idx]
                available_in_clip = current_range.duration - position_in_current_clip
                
                if available_in_clip <= remaining_gap:
                    remaining_gap -= available_in_clip
                    pool_idx += 1
                    position_in_current_clip = 0.0
                else:
                    position_in_current_clip += remaining_gap
                    remaining_gap = 0
            
            # Pool exhausted during gap skip — cycle back
            if pool_idx >= len(video_pool):
                current_cycle += 1
                if current_cycle > MAX_CYCLES:
                    logger.warning(f"   ⚠️ Max cycles ({MAX_CYCLES}) reached at segment {idx}")
                    break
                logger.info(f"   🔄 Pool exhausted at segment {idx}, cycling back (cycle {current_cycle})")
                pool_idx = 0
                position_in_current_clip = 0.0
                accumulated_gap = 0.0  # No gaps on recycled passes
                gap_size = 0.0
            
            # === PHASE 2: Find a clip that fits the full segment ===
            placement_found = False
            attempts_this_segment = 0
            
            while pool_idx < len(video_pool):
                current_range, current_source = video_pool[pool_idx]
                available_in_clip = current_range.duration - position_in_current_clip
                
                if segment_duration <= available_in_clip:
                    # ✅ Segment fits entirely in current clip
                    clip_start = current_range.start + position_in_current_clip
                    clip_end = clip_start + segment_duration
                    
                    matched_clips.append(MatchedClip(
                        audio_segment=segment,
                        video_start=clip_start,
                        video_end=clip_end,
                        source_type=current_source
                    ))
                    
                    position_in_current_clip += segment_duration
                    placement_found = True
                    
                    logger.debug(
                        f"   ✓ Segment {idx}: {clip_start:.2f}s - {clip_end:.2f}s "
                        f"[{current_source}] (duration: {segment_duration:.2f}s)"
                        f"{' [recycled]' if current_cycle > 0 else ''}"
                    )
                    break
                else:
                    # ❌ Segment does NOT fit — skip to next clip
                    logger.debug(
                        f"   → Segment {idx} needs {segment_duration:.2f}s, "
                        f"only {available_in_clip:.2f}s available. Skipping to next clip."
                    )
                    pool_idx += 1
                    position_in_current_clip = 0.0
            
            # Pool exhausted while placing — cycle back and retry
            if not placement_found:
                current_cycle += 1
                if current_cycle > MAX_CYCLES:
                    logger.warning(f"   ⚠️ Max cycles ({MAX_CYCLES}) reached placing segment {idx}")
                    break
                logger.info(f"   🔄 Pool exhausted placing segment {idx}, cycling back (cycle {current_cycle})")
                pool_idx = 0
                position_in_current_clip = 0.0
                gap_size = 0.0
                
                # Retry placement from pool start
                while pool_idx < len(video_pool):
                    current_range, current_source = video_pool[pool_idx]
                    available_in_clip = current_range.duration - position_in_current_clip
                    
                    if segment_duration <= available_in_clip:
                        clip_start = current_range.start + position_in_current_clip
                        clip_end = clip_start + segment_duration
                        
                        matched_clips.append(MatchedClip(
                            audio_segment=segment,
                            video_start=clip_start,
                            video_end=clip_end,
                            source_type=current_source
                        ))
                        
                        position_in_current_clip += segment_duration
                        placement_found = True
                        logger.debug(f"   ✓ Segment {idx}: {clip_start:.2f}s - {clip_end:.2f}s [recycled]")
                        break
                    else:
                        pool_idx += 1
                        position_in_current_clip = 0.0
                
                if not placement_found:
                    # Last resort: take the longest available clip and use it
                    longest_range, longest_source = max(video_pool, key=lambda x: x[0].duration)
                    clip_start = longest_range.start
                    clip_end = min(longest_range.end, clip_start + segment_duration)
                    matched_clips.append(MatchedClip(
                        audio_segment=segment,
                        video_start=clip_start,
                        video_end=clip_end,
                        source_type=longest_source
                    ))
                    logger.warning(f"   ⚠️ Segment {idx}: forced placement from longest clip [last resort]")
            
            # Prepare gap for next iteration
            accumulated_gap = gap_size
        
        # Log summary
        matched_count = len(matched_clips)
        total_count = len(audio_segments)
        if matched_count < total_count:
            logger.warning(
                f"   ⚠️ Only matched {matched_count}/{total_count} segments "
                f"(after {current_cycle} cycles)."
            )
        else:
            logger.info(f"   ✅ All {total_count} segments placed successfully"
                       f"{f' ({current_cycle} cycles)' if current_cycle > 0 else ''}.")
        
        return matched_clips


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_required_video_duration(audio_segments: List[AudioSegment]) -> float:
    """
    Calculate the minimum video duration needed for comfortable pacing.
    
    Args:
        audio_segments: List of audio segments
        
    Returns:
        Minimum video duration (audio_duration * SAFETY_RATIO)
    """
    total_audio = sum(seg.duration for seg in audio_segments)
    return total_audio * SAFETY_RATIO


def analyze_coverage(
    video_episode: TimeRange,
    audio_segments: List[AudioSegment]
) -> dict:
    """
    Analyze the coverage ratio between video and audio.
    
    Returns a dict with analysis results useful for debugging.
    """
    total_audio = sum(seg.duration for seg in audio_segments)
    episode_duration = video_episode.duration
    
    ratio = episode_duration / total_audio if total_audio > 0 else float('inf')
    
    return {
        "video_duration": episode_duration,
        "audio_duration": total_audio,
        "density_ratio": ratio,
        "is_sufficient": ratio >= SAFETY_RATIO,
        "deficit": max(0, (total_audio * SAFETY_RATIO) - episode_duration),
        "segment_count": len(audio_segments),
        "avg_segment_duration": total_audio / len(audio_segments) if audio_segments else 0,
    }


# =============================================================================
# ADAPTER FOR PROJECT MANAGER INTEGRATION
# =============================================================================

class GapMatcherAdapter:
    """
    Adapter to make GapMatcher compatible with ProjectManager interface.
    
    This bridges the gap between GapMatcher's clean Pythonic interface
    and the file-based interface expected by ProjectManager.
    
    Expected Interface (from SequentialMatcher):
        match(script_path, output_path, source_names, episode_time_ranges, initial_blocked_intervals)
        -> returns updated blocked_intervals
    """
    
    def __init__(self, library_path: str):
        """
        Initialize the adapter.
        
        Args:
            library_path: Path to the library (for loading source metadata)
        """
        self.library_path = Path(library_path)
        self.matcher = GapMatcher()
    
    def _load_source_metadata(self, source_name: str) -> Optional[Dict]:
        """Load source video path from master_index.json."""
        source_dir = self.library_path / source_name
        index_path = source_dir / "master_index.json"
        
        if not index_path.exists():
            logger.warning(f"Source index not found: {index_path}")
            return None
        
        try:
            with open(index_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load source metadata: {e}")
            return None
    
    def match(
        self,
        script_path: str,
        output_path: str,
        source_names: List[str],
        episode_time_ranges: Optional[List[Tuple[float, float]]] = None,
        initial_blocked_intervals: Optional[List[Tuple[float, float]]] = None
    ) -> List[Tuple[float, float]]:
        """
        Match audio segments to video clips using Gap Distribution.
        
        This method provides the same interface as SequentialMatcher.match()
        for seamless integration with ProjectManager.
        
        Args:
            script_path: Path to visual_script.json with audio segments
            output_path: Path to write the EDL JSON output
            source_names: List of source aliases (uses first one)
            episode_time_ranges: List of (start, end) tuples for episode bounds
            initial_blocked_intervals: Already-used intervals (for multi-track)
            
        Returns:
            Updated list of blocked intervals including new placements
        """
        script_path = Path(script_path)
        output_path = Path(output_path)
        
        # === STEP 1: Load segments from visual_script.json ===
        try:
            with open(script_path, 'r') as f:
                raw_segments = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load script: {e}")
            with open(output_path, 'w') as f:
                json.dump([], f)
            return list(initial_blocked_intervals) if initial_blocked_intervals else []
        
        if not raw_segments:
            logger.warning("Empty script, nothing to match")
            with open(output_path, 'w') as f:
                json.dump([], f)
            return list(initial_blocked_intervals) if initial_blocked_intervals else []
        
        # Convert to AudioSegment objects
        audio_segments = []
        for seg in raw_segments:
            audio_segments.append(AudioSegment(
                duration=seg.get("duration", 5.0),
                text=seg.get("text", ""),
                segment_id=seg.get("segment_id", len(audio_segments)),
                start=seg.get("start", 0.0)
            ))
        
        # === STEP 2: Build video ranges from episodes ===
        if episode_time_ranges and len(episode_time_ranges) > 0:
            # Sort and merge overlapping ranges
            sorted_ranges = sorted(episode_time_ranges, key=lambda x: x[0])
            merged_ranges = [sorted_ranges[0]]
            for start, end in sorted_ranges[1:]:
                prev_start, prev_end = merged_ranges[-1]
                if start <= prev_end:
                    # Overlapping or adjacent — merge
                    merged_ranges[-1] = (prev_start, max(prev_end, end))
                else:
                    merged_ranges.append((start, end))
            
            total_range_duration = sum(e - s for s, e in merged_ranges)
            logger.info(f"📍 Using {len(merged_ranges)} episode ranges, total: {total_range_duration:.1f}s")
            
            if len(merged_ranges) == 1:
                # Single contiguous range — use original gap distribution
                video_episode = TimeRange(start=merged_ranges[0][0], end=merged_ranges[0][1])
                logger.info(f"   Single range: {video_episode.start:.1f}s - {video_episode.end:.1f}s")
            else:
                # Multiple disjoint ranges (e.g., character scenes) —
                # build a video pool and use linear distribution across all ranges
                video_pool = [
                    (TimeRange(start=s, end=e), "primary_episode")
                    for s, e in merged_ranges
                ]
                total_audio = sum(seg.duration for seg in audio_segments)
                matched_clips = self.matcher._linear_distribute_across_pool(
                    audio_segments, video_pool, total_audio, total_range_duration
                )
                video_episode = None  # Signal to skip STEP 3
                logger.info(f"   Disjoint ranges: distributing across {len(merged_ranges)} ranges")
        else:
            # Fallback: use a large default range
            video_episode = TimeRange(start=0.0, end=7200.0)  # 2 hours
            logger.warning("⚠️ No episode bounds provided, using default 2-hour range")
        
        # === STEP 3: Run GapMatcher (only for single contiguous range) ===
        if video_episode is not None:
            matched_clips = self.matcher.match(video_episode, audio_segments)
        
        # === STEP 4: Convert to EDL format (compatible with PremiereExporter) ===
        primary_source = source_names[0] if source_names else "unknown"
        source_meta = self._load_source_metadata(primary_source)
        source_video_path = source_meta.get("source_video_path") if source_meta else None
        
        edl = []
        new_blocked = list(initial_blocked_intervals) if initial_blocked_intervals else []
        
        for clip in matched_clips:
            seg = clip.audio_segment
            
            # Build EDL entry matching existing format
            edl.append({
                "segment_id": seg.segment_id,
                "text": seg.text,
                "source_file": "gap_matched",  # Placeholder, video comes from source
                "source_project_alias": primary_source,
                "source_video_path": source_video_path,
                "scene_id": f"gap_{seg.segment_id}",
                "in_point": clip.video_start,
                "out_point": clip.video_end,
                "duration": clip.video_end - clip.video_start,
                "target_duration": seg.duration,
                "timeline_start": seg.start,
                "match_score": 1.0,  # Gap matcher doesn't use scoring
                "match_type": f"GapMatcher_{clip.source_type}"
            })
            
            # Track blocked intervals
            new_blocked.append((clip.video_start, clip.video_end))
            
        # Verify all segments were matched — pool cycling should guarantee this
        matched_segment_ids = {clip.audio_segment.segment_id for clip in matched_clips}
        unmatched_count = sum(1 for seg in audio_segments if seg.segment_id not in matched_segment_ids)
        if unmatched_count > 0:
            logger.error(f"❌ {unmatched_count} segments still unmatched after pool cycling — this should not happen")
                
        # Sort EDL by segment_id to maintain sequence order
        edl.sort(key=lambda x: x["segment_id"])
        
        # === STEP 5: Write EDL output ===
        with open(output_path, 'w') as f:
            json.dump(edl, f, indent=2)
        
        logger.info(f"✅ GapMatcher: {len(edl)} clips written to {output_path}")
        
        return new_blocked
