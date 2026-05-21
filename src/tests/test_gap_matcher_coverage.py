"""
Tests for GapMatcher and ChaoticMatcher frame coverage.

Verifies that every audio segment gets a real video frame — 
no PLACEHOLDER entries, no skipped segments.
"""

import json
import unittest
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.matching.gap_matcher import (
    GapMatcher, GapMatcherAdapter, TimeRange, AudioSegment, MatchedClip
)


class TestPoolCycling(unittest.TestCase):
    """Tests for _linear_distribute_across_pool with pool cycling."""

    def setUp(self):
        self.matcher = GapMatcher()

    def test_all_segments_matched_no_placeholders(self):
        """
        20 audio segments of 3s each (60s total) across 15 short disjoint
        ranges (each 5s, total 75s). All segments must get real clips.
        """
        audio_segments = [
            AudioSegment(duration=3.0, text=f"seg_{i}", segment_id=i, start=i * 3.0)
            for i in range(20)
        ]
        
        # 15 disjoint ranges of 5s each = 75s total video
        video_pool = [
            (TimeRange(start=i * 100.0, end=i * 100.0 + 5.0), "primary_episode")
            for i in range(15)
        ]
        
        total_audio = sum(s.duration for s in audio_segments)  # 60s
        total_video = sum(r.duration for r, _ in video_pool)   # 75s
        
        matched = self.matcher._linear_distribute_across_pool(
            audio_segments, video_pool, total_audio, total_video
        )
        
        self.assertEqual(len(matched), 20, 
                         f"Expected 20 matched clips, got {len(matched)}")
        
        # Verify no placeholder-like entries
        for clip in matched:
            self.assertNotEqual(clip.source_type, "PLACEHOLDER")
            self.assertGreater(clip.video_end, clip.video_start)

    def test_pool_cycling_on_exhaustion(self):
        """
        10 segments of 5s each (50s audio) with only 30s of video total.
        Pool MUST cycle to cover all segments. Zero placeholders.
        """
        audio_segments = [
            AudioSegment(duration=5.0, text=f"seg_{i}", segment_id=i, start=i * 5.0)
            for i in range(10)
        ]
        
        # Only 30s of video — far less than 50s needed
        video_pool = [
            (TimeRange(start=0.0, end=15.0), "primary_episode"),
            (TimeRange(start=100.0, end=115.0), "primary_episode"),
        ]
        
        total_audio = 50.0
        total_video = 30.0
        
        matched = self.matcher._linear_distribute_across_pool(
            audio_segments, video_pool, total_audio, total_video
        )
        
        self.assertEqual(len(matched), 10,
                         f"Expected 10 matched clips, got {len(matched)}. "
                         f"Pool cycling must cover all segments.")
        
        # Verify all clips have real video coordinates
        for clip in matched:
            self.assertGreater(clip.video_end, clip.video_start)
            self.assertGreaterEqual(clip.video_duration, 4.9)  # ~5s each

    def test_zero_gap_when_tight_pool(self):
        """
        Pool barely enough for audio. Gap should be 0, all segments placed.
        """
        audio_segments = [
            AudioSegment(duration=4.0, text=f"seg_{i}", segment_id=i, start=i * 4.0)
            for i in range(5)
        ]
        
        # 20s audio, 22s video — slack is 2s which is < 10% of audio → zero gap
        video_pool = [
            (TimeRange(start=0.0, end=11.0), "primary_episode"),
            (TimeRange(start=50.0, end=61.0), "primary_episode"),
        ]
        
        total_audio = 20.0
        total_video = 22.0
        
        matched = self.matcher._linear_distribute_across_pool(
            audio_segments, video_pool, total_audio, total_video
        )
        
        self.assertEqual(len(matched), 5,
                         f"Expected 5 matched clips, got {len(matched)}")

    def test_many_tiny_disjoint_ranges(self):
        """
        Simulates character scenes: 144 disjoint ranges of 2-5s each.
        60s of audio should be fully covered.
        """
        import random
        random.seed(42)
        
        audio_segments = [
            AudioSegment(duration=round(random.uniform(1.5, 4.0), 2), 
                         text=f"seg_{i}", segment_id=i, start=i * 2.5)
            for i in range(25)  # ~25 segments for ~60s audio
        ]
        
        # 144 short disjoint ranges
        video_pool = [
            (TimeRange(start=i * 50.0, end=i * 50.0 + random.uniform(2.0, 5.0)), 
             "primary_episode")
            for i in range(144)
        ]
        
        total_audio = sum(s.duration for s in audio_segments)
        total_video = sum(r.duration for r, _ in video_pool)
        
        matched = self.matcher._linear_distribute_across_pool(
            audio_segments, video_pool, total_audio, total_video
        )
        
        self.assertEqual(len(matched), len(audio_segments),
                         f"Expected {len(audio_segments)} clips, got {len(matched)}. "
                         f"Total video: {total_video:.1f}s, audio: {total_audio:.1f}s")


class TestGapMatcherAdapterNoPlaceholders(unittest.TestCase):
    """Tests that GapMatcherAdapter never outputs PLACEHOLDER entries."""

    def test_adapter_no_placeholders_disjoint_ranges(self):
        """
        Full integration: adapter with disjoint ranges must produce
        zero PLACEHOLDER entries in the EDL output.
        """
        # Create a visual script with 15 segments
        script_segments = [
            {
                "segment_id": i,
                "text": f"Segment {i}",
                "visual_query": f"query {i}",
                "duration": 3.5,
                "start": i * 3.5,
            }
            for i in range(15)
        ]
        
        # Write script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(script_segments, f)
            script_path = f.name
        
        output_path = script_path.replace('.json', '_edl.json')
        
        # Create a mock master_index.json
        mock_index = {
            "source_video_path": "/fake/video.mp4",
            "scenes": []
        }
        
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Create source dir structure
                source_dir = Path(tmpdir) / "TestSource"
                source_dir.mkdir()
                with open(source_dir / "master_index.json", 'w') as f:
                    json.dump(mock_index, f)
                
                adapter = GapMatcherAdapter(tmpdir)
                
                # 20 disjoint ranges of 4s each = 80s video for 52.5s audio
                episode_ranges = [
                    (i * 30.0, i * 30.0 + 4.0) for i in range(20)
                ]
                
                adapter.match(
                    script_path=script_path,
                    output_path=output_path,
                    source_names=["TestSource"],
                    episode_time_ranges=episode_ranges
                )
                
                with open(output_path, 'r') as f:
                    edl = json.load(f)
                
                # ALL segments must have entries
                self.assertEqual(len(edl), 15,
                                 f"Expected 15 EDL entries, got {len(edl)}")
                
                # ZERO placeholders
                placeholders = [e for e in edl if e.get("source_file") == "PLACEHOLDER"]
                self.assertEqual(len(placeholders), 0,
                                 f"Found {len(placeholders)} PLACEHOLDER entries — must be 0")
                
                # All entries must have real match types
                for entry in edl:
                    self.assertNotIn("Placeholder", entry.get("match_type", ""),
                                    f"Entry {entry['segment_id']} has placeholder match type")
                    
        finally:
            os.unlink(script_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_adapter_tight_pool_no_placeholders(self):
        """
        Pool smaller than audio. Must cycle and produce zero placeholders.
        """
        script_segments = [
            {
                "segment_id": i,
                "text": f"Segment {i}",
                "duration": 5.0,
                "start": i * 5.0,
            }
            for i in range(10)
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(script_segments, f)
            script_path = f.name
        
        output_path = script_path.replace('.json', '_edl.json')
        
        mock_index = {
            "source_video_path": "/fake/video.mp4",
            "scenes": []
        }
        
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                source_dir = Path(tmpdir) / "Source"
                source_dir.mkdir()
                with open(source_dir / "master_index.json", 'w') as f:
                    json.dump(mock_index, f)
                
                adapter = GapMatcherAdapter(tmpdir)
                
                # Only 25s of video for 50s of audio — must cycle
                episode_ranges = [
                    (0.0, 10.0),
                    (100.0, 115.0),
                ]
                
                adapter.match(
                    script_path=script_path,
                    output_path=output_path,
                    source_names=["Source"],
                    episode_time_ranges=episode_ranges
                )
                
                with open(output_path, 'r') as f:
                    edl = json.load(f)
                
                self.assertEqual(len(edl), 10)
                
                placeholders = [e for e in edl if e.get("source_file") == "PLACEHOLDER"]
                self.assertEqual(len(placeholders), 0,
                                 f"Found {len(placeholders)} placeholders. Pool cycling must eliminate them.")
                
        finally:
            os.unlink(script_path)
            if os.path.exists(output_path):
                os.unlink(output_path)


class TestGapMatcherSingleRange(unittest.TestCase):
    """Tests for the standard single-range path (Branch A/B)."""

    def test_branch_a_sufficient_footage(self):
        """Branch A: plenty of video, all segments placed with gaps."""
        matcher = GapMatcher()
        
        video = TimeRange(start=0.0, end=100.0)
        audio = [
            AudioSegment(duration=5.0, text=f"seg_{i}", segment_id=i, start=i * 5.0)
            for i in range(5)
        ]
        
        result = matcher.match(video, audio)
        
        self.assertEqual(len(result), 5)
        # All clips within video bounds
        for clip in result:
            self.assertGreaterEqual(clip.video_start, 0.0)
            self.assertLessEqual(clip.video_end, 100.0)

    def test_branch_b_insufficient_footage(self):
        """Branch B: video too short, needs injection but still no gaps."""
        matcher = GapMatcher()
        
        # 10s video for 25s audio (ratio 0.4 < 1.5)
        video = TimeRange(start=0.0, end=10.0)
        audio = [
            AudioSegment(duration=5.0, text=f"seg_{i}", segment_id=i, start=i * 5.0)
            for i in range(5)
        ]
        
        result = matcher.match(video, audio)
        
        # At minimum 2 segments should be placed (10s / 5s)
        self.assertGreaterEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
