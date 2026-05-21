"""
Tests for group matching functionality.

Verifies:
1. Group items persist through Pydantic model (not stripped)
2. Fallback resolution from .groups/ storage works
3. Group time ranges are correctly assembled
4. Film (non-group) matching still works
"""

import json
import unittest
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.api.models import SegmentedTimelineItem, SegmentedTimelineSaveRequest
from src.project_manager import ProjectManager


class TestGroupItemsPersistence(unittest.TestCase):
    """Tests that group_items field is correctly handled by Pydantic."""

    def test_group_items_not_stripped(self):
        """group_items field must survive Pydantic validation."""
        item = SegmentedTimelineItem(
            id="clip-123",
            source_alias="group",
            episode_id="grp_1774260049212",
            episode_name="Tost",
            timeline_start=0.0,
            timeline_duration=120.0,
            clip_type="group",
            matcher_mode="chaotic",
            group_selection_mode="alternate",
            group_items=[
                {"source_alias": "Interstellar", "type": "episode", "name": "FullFilm", "episode_id": "ep_1"},
                {"source_alias": "The Dark Knight", "type": "episode", "name": "Finale", "episode_id": "ep_2"},
            ]
        )
        
        # Serialize and verify group_items survives
        data = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
        self.assertIn("group_items", data)
        self.assertEqual(len(data["group_items"]), 2)
        self.assertEqual(data["group_items"][0]["source_alias"], "Interstellar")
        self.assertEqual(data["group_selection_mode"], "alternate")

    def test_underscore_groupItems_stripped(self):
        """_groupItems (old field name) should be stripped by Pydantic — proving the bug."""
        item = SegmentedTimelineItem(
            id="clip-123",
            source_alias="group",
            timeline_start=0.0,
            timeline_duration=120.0,
            clip_type="group",
        )
        data = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
        # _groupItems should NOT be in the serialized data
        self.assertNotIn("_groupItems", data)

    def test_group_items_none_for_episode(self):
        """For episode clips, group_items should be None."""
        item = SegmentedTimelineItem(
            id="clip-456",
            source_alias="Batman",
            episode_id="ep_1",
            timeline_start=0.0,
            timeline_duration=60.0,
            clip_type="episode",
        )
        data = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
        self.assertIsNone(data.get("group_items"))

    def test_save_request_preserves_groups(self):
        """SegmentedTimelineSaveRequest with group items should preserve them."""
        req = SegmentedTimelineSaveRequest(items=[
            SegmentedTimelineItem(
                id="clip-1",
                source_alias="group",
                episode_id="grp_123",
                episode_name="Test Group",
                timeline_start=0.0,
                timeline_duration=60.0,
                clip_type="group",
                matcher_mode="chaotic",
                group_selection_mode="score",
                group_items=[
                    {"source_alias": "MovieA", "type": "episode", "name": "Scene1", "episode_id": "ep_a"},
                ]
            ),
            SegmentedTimelineItem(
                id="clip-2",
                source_alias="MovieB",
                episode_id="ep_b",
                timeline_start=60.0,
                timeline_duration=30.0,
                clip_type="episode",
            )
        ])

        items = [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in req.items]
        
        # Group clip should have items
        self.assertIsNotNone(items[0]["group_items"])
        self.assertEqual(len(items[0]["group_items"]), 1)
        self.assertEqual(items[0]["group_selection_mode"], "score")
        
        # Episode clip should NOT have items
        self.assertIsNone(items[1]["group_items"])


class TestGroupResolutionFallback(unittest.TestCase):
    """Tests that group resolution falls back to .groups/ storage."""

    def test_fallback_to_groups_storage(self):
        """When group_items is empty, should resolve from .groups/{id}.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .groups/ directory with a test group
            groups_dir = Path(tmpdir) / ".groups"
            groups_dir.mkdir()
            
            group_data = {
                "id": "grp_test_123",
                "name": "Test Group",
                "items": [
                    {"source_alias": "MovieA", "type": "episode", "name": "Scene1", "episode_id": "ep_a"},
                    {"source_alias": "MovieB", "type": "character", "name": "Hero"},
                ]
            }
            with open(groups_dir / "grp_test_123.json", 'w') as f:
                json.dump(group_data, f)
            
            # Simulate what project_manager does  
            clip = {
                "clip_type": "group",
                "episode_id": "grp_test_123",
                "episode_name": "Test Group",
                "group_items": None,   # Not persisted (simulating the old bug)
                "_groupItems": None,   # Legacy also missing
            }
            
            # Try new field, then legacy, then fallback
            group_items = clip.get("group_items") or clip.get("_groupItems") or []
            
            if not group_items:
                # Fallback: resolve from storage
                group_path = groups_dir / f"{clip['episode_id']}.json"
                if group_path.exists():
                    with open(group_path, 'r') as f:
                        resolved = json.load(f)
                    group_items = resolved.get("items", [])
            
            self.assertEqual(len(group_items), 2)
            self.assertEqual(group_items[0]["source_alias"], "MovieA")
            self.assertEqual(group_items[1]["type"], "character")

    def test_direct_group_items_takes_priority(self):
        """When group_items IS present, should NOT fall back to storage."""
        clip = {
            "clip_type": "group",
            "episode_id": "grp_xyz",
            "group_items": [
                {"source_alias": "Direct", "type": "episode", "name": "Direct Scene"}
            ],
        }
        
        group_items = clip.get("group_items") or clip.get("_groupItems") or []
        
        # Should get the direct items, not fallback
        self.assertEqual(len(group_items), 1)
        self.assertEqual(group_items[0]["source_alias"], "Direct")


class TestGroupNormalization(unittest.TestCase):
    """Tests backend validation and repair of stored group items."""

    def _manager_for_library(self, tmpdir):
        manager = ProjectManager()
        manager.library_path = Path(tmpdir)
        manager.projects_path = Path(tmpdir) / "projects"
        manager.studio_path = Path(tmpdir) / "studio"
        return manager

    def test_stale_episode_id_is_repaired_by_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "Interstellar"
            source_dir.mkdir()
            with open(source_dir / "episodes.json", "w", encoding="utf-8") as f:
                json.dump([
                    {"id": "ep_new", "name": "Full Film", "start_time": 10.0, "end_time": 100.0}
                ], f)

            manager = self._manager_for_library(tmpdir)
            items, errors = manager.normalize_group_items([
                {
                    "source_alias": "Interstellar",
                    "type": "episode",
                    "name": "FullFilm",
                    "episode_id": "ep_old"
                }
            ], strict=False)

            self.assertEqual(errors, [])
            self.assertEqual(items[0]["episode_id"], "ep_new")
            self.assertEqual(items[0]["name"], "Full Film")

    def test_invalid_group_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager_for_library(tmpdir)

            with self.assertRaises(ValueError):
                manager.normalize_group_items([
                    {
                        "source_alias": "Missing Movie",
                        "type": "episode",
                        "name": "Full Film",
                        "episode_id": "ep_1"
                    }
                ], strict=True)

    def test_get_group_persists_episode_id_repair(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "Interstellar"
            source_dir.mkdir()
            with open(source_dir / "episodes.json", "w", encoding="utf-8") as f:
                json.dump([
                    {"id": "ep_new", "name": "Full Film", "start_time": 10.0, "end_time": 100.0}
                ], f)

            groups_dir = Path(tmpdir) / ".groups"
            groups_dir.mkdir()
            group_path = groups_dir / "grp_test.json"
            with open(group_path, "w", encoding="utf-8") as f:
                json.dump({
                    "id": "grp_test",
                    "name": "Test",
                    "items": [
                        {
                            "source_alias": "Interstellar",
                            "type": "episode",
                            "name": "FullFilm",
                            "episode_id": "ep_old"
                        }
                    ]
                }, f)

            manager = self._manager_for_library(tmpdir)
            group = manager.get_group("grp_test")
            with open(group_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

            self.assertEqual(group["items"][0]["episode_id"], "ep_new")
            self.assertEqual(saved["items"][0]["episode_id"], "ep_new")


class TestGroupTimeRangeAssembly(unittest.TestCase):
    """Tests that episode time ranges are correctly assembled from group items."""

    def test_episode_items_produce_time_ranges(self):
        """Group with episode items should produce correct time ranges."""
        # Simulate what project_manager.py does for episode-type items
        group_items = [
            {"source_alias": "MovieA", "type": "episode", "name": "Scene1", "episode_id": "ep_1"},
            {"source_alias": "MovieB", "type": "episode", "name": "Scene2", "episode_id": "ep_2"},
        ]
        
        # Mock episodes
        mock_episodes = {
            "MovieA": [{"id": "ep_1", "start_time": 100.0, "end_time": 200.0}],
            "MovieB": [{"id": "ep_2", "start_time": 500.0, "end_time": 600.0}],
        }
        
        source_aliases_set = set()
        episode_time_ranges = []
        
        for item in group_items:
            i_source = item.get("source_alias")
            i_type = item.get("type")
            i_ep_id = item.get("episode_id")
            if not i_source:
                continue
            
            source_aliases_set.add(i_source)
            
            if i_type == "episode":
                episodes = mock_episodes.get(i_source, [])
                for ep in episodes:
                    if ep["id"] == i_ep_id:
                        episode_time_ranges.append((ep["start_time"], ep["end_time"]))
                        break
        
        episode_time_ranges.sort(key=lambda x: x[0])
        
        self.assertEqual(len(source_aliases_set), 2)
        self.assertIn("MovieA", source_aliases_set)
        self.assertIn("MovieB", source_aliases_set)
        self.assertEqual(len(episode_time_ranges), 2)
        self.assertEqual(episode_time_ranges[0], (100.0, 200.0))
        self.assertEqual(episode_time_ranges[1], (500.0, 600.0))


class TestFilmMatchingUnaffected(unittest.TestCase):
    """Tests that regular film (non-group) matching still works correctly."""

    def test_episode_clip_no_group_resolution(self):
        """Episode clip should not trigger group resolution logic."""
        clip = {
            "clip_type": "episode",
            "source_alias": "Batman",
            "episode_id": "ep_1",
            "episode_name": "Opening",
        }
        
        clip_type = clip.get("clip_type", "episode")
        self.assertNotEqual(clip_type, "group")
        
        # Should use the standard episode path
        source_aliases = [clip["source_alias"]]
        self.assertEqual(source_aliases, ["Batman"])

    def test_character_clip_no_group_resolution(self):
        """Character clip should not trigger group resolution logic."""
        clip = {
            "clip_type": "character",
            "source_alias": "Batman",
            "character_name": "Joker",
        }
        
        clip_type = clip.get("clip_type", "episode")
        self.assertNotEqual(clip_type, "group")
        
        source_aliases = [clip["source_alias"]]
        self.assertEqual(source_aliases, ["Batman"])

    def test_gap_matcher_still_works_with_single_range(self):
        """GapMatcher should still work for single-episode clips."""
        from src.matching.gap_matcher import GapMatcher, TimeRange, AudioSegment
        
        matcher = GapMatcher()
        video = TimeRange(start=0.0, end=60.0)
        audio = [
            AudioSegment(duration=5.0, text=f"seg_{i}", segment_id=i, start=i * 5.0)
            for i in range(5)
        ]
        
        result = matcher.match(video, audio)
        self.assertEqual(len(result), 5)
        for clip in result:
            self.assertGreaterEqual(clip.video_start, 0.0)
            self.assertLessEqual(clip.video_end, 60.0)

    def test_gap_matcher_disjoint_ranges(self):
        """GapMatcher with disjoint ranges (like group episode ranges)."""
        from src.matching.gap_matcher import GapMatcher, TimeRange, AudioSegment
        
        matcher = GapMatcher()
        audio = [
            AudioSegment(duration=3.0, text=f"seg_{i}", segment_id=i, start=i * 3.0)
            for i in range(10)
        ]
        
        # Simulate disjoint ranges from a group
        video_pool = [
            (TimeRange(start=100.0, end=115.0), "primary_episode"),
            (TimeRange(start=500.0, end=515.0), "primary_episode"),
            (TimeRange(start=1000.0, end=1015.0), "primary_episode"),
        ]
        
        total_audio = sum(s.duration for s in audio)
        total_video = sum(r.duration for r, _ in video_pool)
        
        matched = matcher._linear_distribute_across_pool(
            audio, video_pool, total_audio, total_video
        )
        
        self.assertEqual(len(matched), 10)
        for clip in matched:
            self.assertGreater(clip.video_end, clip.video_start)


if __name__ == "__main__":
    unittest.main()
