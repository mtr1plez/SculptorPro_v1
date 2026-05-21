"""
Tests for the rewritten EpisodeSegmenter (scene-grouping approach).
"""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Mock google.generativeai before importing the segmenter
mock_genai = MagicMock()
mock_genai.types = MagicMock()
mock_genai.types.GenerationConfig = MagicMock
sys.modules['google'] = MagicMock()
sys.modules['google.generativeai'] = mock_genai
sys.modules['google.api_core'] = MagicMock()
sys.modules['google.api_core.exceptions'] = MagicMock()

from src.ingestion.episode_segmenter import EpisodeRange, EpisodeSegmenter, MIN_EPISODE_DURATION, _format_time


class TestFormatTime(unittest.TestCase):
    def test_seconds_only(self):
        self.assertEqual(_format_time(45), "0:45")

    def test_minutes_seconds(self):
        self.assertEqual(_format_time(125), "2:05")

    def test_hours(self):
        self.assertEqual(_format_time(3661), "1:01:01")

    def test_zero(self):
        self.assertEqual(_format_time(0), "0:00")


class TestBuildSceneTable(unittest.TestCase):
    """Test _build_scene_table — the core logic that prepares data for Gemini."""

    def _make_segmenter(self, tmp_path):
        """Create segmenter with minimal required files."""
        lib_dir = tmp_path / "TestFilm"
        lib_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy scene_data.json
        scenes = [
            {"scene_id": f"scene_{i:04d}", "start_time": i * 10.0, "end_time": (i + 1) * 10.0,
             "start_frame": i * 250, "end_frame": (i + 1) * 250, "keyframes": []}
            for i in range(20)
        ]
        (lib_dir / "scene_data.json").write_text(json.dumps(scenes))

        # Create dummy master_index.json
        master = {
            "movie_name": "Test Film",
            "scenes": [
                {
                    "id": f"scene_{i:04d}",
                    "time": {"start": i * 10.0, "end": (i + 1) * 10.0},
                    "visual": {"shot_type": "Medium Shot", "path": f"keyframes/scene_{i:04d}_1.jpg"},
                    "content": {
                        "characters": ["Alice"] if i % 3 == 0 else [],
                        "raw_ids": []
                    },
                    "metadata": {
                        "is_intro": i < 2,
                        "is_credits": i >= 18,
                        "plot_position": i / 20.0
                    }
                }
                for i in range(20)
            ]
        }
        (lib_dir / "master_index.json").write_text(json.dumps(master))

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    seg = EpisodeSegmenter(lib_dir)
        return seg, lib_dir

    def test_filters_intro_and_credits(self, tmp_path=None):
        """Intro and credits scenes should be filtered out."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            seg, _ = self._make_segmenter(Path(tmp))
            scene_list, master_lookup = seg._load_ingest_data()
            table_text, filtered = seg._build_scene_table(scene_list, master_lookup)

            # Scenes 0,1 are intro, 18,19 are credits — should be filtered
            scene_ids = [s["scene_id"] for s in filtered]
            self.assertNotIn("scene_0000", scene_ids)
            self.assertNotIn("scene_0001", scene_ids)
            self.assertNotIn("scene_0018", scene_ids)
            self.assertNotIn("scene_0019", scene_ids)

    def test_table_has_header(self):
        """Table should have a header row."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            seg, _ = self._make_segmenter(Path(tmp))
            scene_list, master_lookup = seg._load_ingest_data()
            table_text, _ = seg._build_scene_table(scene_list, master_lookup)

            self.assertIn("scene_id", table_text)
            self.assertIn("time", table_text)
            self.assertIn("characters", table_text)


class TestMergeShortScenes(unittest.TestCase):
    """Test _merge_short_scenes."""

    def _make_segmenter_simple(self):
        """Create a segmenter without actual files (for method testing)."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    import tempfile
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def test_short_scenes_merged(self):
        """Scenes shorter than MIN_SCENE_DURATION should merge with next."""
        seg = self._make_segmenter_simple()
        enriched = [
            {"scene_id": "scene_0000", "start_time": 0, "end_time": 1.0,
             "duration": 1.0, "shot_type": "Close-Up Face", "characters": [],
             "is_intro": False, "is_credits": False},
            {"scene_id": "scene_0001", "start_time": 1.0, "end_time": 1.5,
             "duration": 0.5, "shot_type": "Close-Up Face", "characters": [],
             "is_intro": False, "is_credits": False},
            {"scene_id": "scene_0002", "start_time": 1.5, "end_time": 12.0,
             "duration": 10.5, "shot_type": "Medium Shot", "characters": ["Paul"],
             "is_intro": False, "is_credits": False},
        ]
        merged = seg._merge_short_scenes(enriched)

        # First two short scenes should be merged with scene_0002
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["scene_id"], "scene_0000")
        self.assertEqual(merged[0]["end_time"], 12.0)
        self.assertIn("Paul", merged[0]["characters"])

    def test_long_scenes_not_merged(self):
        """Scenes longer than MIN_SCENE_DURATION should stay separate."""
        seg = self._make_segmenter_simple()
        enriched = [
            {"scene_id": "scene_0000", "start_time": 0, "end_time": 10.0,
             "duration": 10.0, "shot_type": "Close-Up Face", "characters": ["Alice"],
             "is_intro": False, "is_credits": False},
            {"scene_id": "scene_0001", "start_time": 10.0, "end_time": 25.0,
             "duration": 15.0, "shot_type": "Medium Shot", "characters": ["Bob"],
             "is_intro": False, "is_credits": False},
        ]
        merged = seg._merge_short_scenes(enriched)
        self.assertEqual(len(merged), 2)


class TestResolveSceneIds(unittest.TestCase):
    """Test _resolve_scene_ids_to_times."""

    def _make_segmenter_simple(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    import tempfile
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def test_exact_scene_ids(self):
        """When Gemini returns exact scene IDs, timestamps must match scene_data."""
        seg = self._make_segmenter_simple()

        scene_list = [
            {"scene_id": "scene_0000", "start_time": 0.2, "end_time": 10.96},
            {"scene_id": "scene_0001", "start_time": 11.16, "end_time": 25.24},
            {"scene_id": "scene_0002", "start_time": 25.44, "end_time": 50.0},
            {"scene_id": "scene_0003", "start_time": 50.2, "end_time": 100.0},
        ]

        episodes = [
            {"name": "1. Intro", "first_scene": "scene_0000", "last_scene": "scene_0001"},
            {"name": "2. Main", "first_scene": "scene_0002", "last_scene": "scene_0003"},
        ]

        resolved = seg._resolve_scene_ids_to_times(episodes, scene_list)

        self.assertEqual(len(resolved), 2)
        self.assertEqual(resolved[0]["start_time"], 0.2)
        self.assertEqual(resolved[0]["end_time"], 25.24)
        self.assertEqual(resolved[1]["start_time"], 25.44)
        self.assertEqual(resolved[1]["end_time"], 100.0)

    def test_fuzzy_scene_id_match(self):
        """When Gemini returns a scene_id that was merged, find closest match."""
        seg = self._make_segmenter_simple()

        scene_list = [
            {"scene_id": "scene_0000", "start_time": 0.0, "end_time": 10.0},
            {"scene_id": "scene_0002", "start_time": 10.0, "end_time": 20.0},
            {"scene_id": "scene_0005", "start_time": 20.0, "end_time": 30.0},
        ]

        # Gemini returns scene_0001 which doesn't exist (was merged)
        episodes = [
            {"name": "1. Test", "first_scene": "scene_0001", "last_scene": "scene_0005"},
        ]

        resolved = seg._resolve_scene_ids_to_times(episodes, scene_list)
        self.assertEqual(len(resolved), 1)
        # Should fallback to scene_0000 or scene_0002 (closest)
        self.assertIn(resolved[0]["start_time"], [0.0, 10.0])


class TestValidateEpisodes(unittest.TestCase):

    def _make_segmenter_simple(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    import tempfile
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def test_invalid_episodes_filtered(self):
        """Episodes with end <= start should be removed."""
        seg = self._make_segmenter_simple()
        episodes = [
            {"name": "Good", "start_time": 0.0, "end_time": 10.0},
            {"name": "Bad", "start_time": 10.0, "end_time": 5.0},
            {"name": "Zero", "start_time": 10.0, "end_time": 10.0},
        ]
        validated = seg._validate_episodes(episodes)
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]["name"], "Good")

    def test_sorted_by_start_time(self):
        """Episodes should be sorted by start_time."""
        seg = self._make_segmenter_simple()
        episodes = [
            {"name": "B", "start_time": 20.0, "end_time": 30.0},
            {"name": "A", "start_time": 0.0, "end_time": 10.0},
        ]
        validated = seg._validate_episodes(episodes)
        self.assertEqual(validated[0]["name"], "A")
        self.assertEqual(validated[1]["name"], "B")

    def test_preserves_narrative_metadata(self):
        """Validation must keep optional fields used by the new episode format."""
        seg = self._make_segmenter_simple()
        episodes = [{
            "name": "1. Cobb teaches Ariadne",
            "start_time": 0.0,
            "end_time": 60.0,
            "first_scene": "scene_0000",
            "last_scene": "scene_0010",
            "confidence": 0.91,
            "reason": "hard location change after the beat",
            "episode_type": "scene",
        }]

        validated = seg._validate_episodes(episodes)
        with_ids = seg._add_ids(validated)

        self.assertEqual(with_ids[0]["first_scene"], "scene_0000")
        self.assertEqual(with_ids[0]["last_scene"], "scene_0010")
        self.assertEqual(with_ids[0]["episode_type"], "scene")
        self.assertEqual(with_ids[0]["confidence"], 0.91)


class TestNarrativeCoverageRepair(unittest.TestCase):
    """Tests for the deterministic layer that guarantees usable episode ranges."""

    def _make_segmenter_simple(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    import tempfile
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def _cards(self, durations):
        cards = []
        t = 0.0
        for i, duration in enumerate(durations):
            cards.append({
                "scene_id": f"scene_{i:04d}",
                "index": i,
                "raw_start": t,
                "raw_end": t + duration,
                "safe_start": t + 0.2,
                "safe_end": t + duration,
                "duration": duration,
                "shot_type": "Medium Shot",
                "characters": ["A"] if i < 3 else ["B"],
                "dialogue": "",
                "visual_summary": "same conversation" if i < 3 else "new location",
                "episode_type": "scene",
            })
            t += duration
        return cards

    def test_repair_fills_gaps_and_overlaps_by_scene_index(self):
        seg = self._make_segmenter_simple()
        cards = self._cards([20, 20, 20, 20, 20, 20])
        broken = [
            EpisodeRange(0, 1, reason="first"),
            EpisodeRange(3, 4, reason="gap before this"),
            EpisodeRange(4, 5, reason="overlap"),
        ]

        repaired = seg._repair_episode_ranges(broken, cards, min_duration=1.0)

        self.assertEqual(repaired[0].start_idx, 0)
        self.assertEqual(repaired[-1].end_idx, len(cards) - 1)
        for prev, nxt in zip(repaired, repaired[1:]):
            self.assertEqual(nxt.start_idx, prev.end_idx + 1)

    def test_repair_merges_short_episodes(self):
        seg = self._make_segmenter_simple()
        cards = self._cards([10, 10, 10, 60, 60])
        ranges = [
            EpisodeRange(0, 0, reason="too short"),
            EpisodeRange(1, 2, reason="also too short"),
            EpisodeRange(3, 4, reason="long"),
        ]

        repaired = seg._repair_episode_ranges(ranges, cards)

        self.assertEqual(repaired[0].start_idx, 0)
        self.assertEqual(repaired[-1].end_idx, 4)
        for item in repaired:
            self.assertGreaterEqual(seg._episode_duration(item, cards), MIN_EPISODE_DURATION)

    def test_solver_does_not_cut_every_angle_change(self):
        seg = self._make_segmenter_simple()
        cards = self._cards([40, 40, 40, 80, 80])
        boundaries = [
            {"after_scene": "scene_0000", "decision": "same_scene", "reason": "reverse angle", "confidence": 0.9},
            {"after_scene": "scene_0001", "decision": "same_scene", "reason": "same conversation", "confidence": 0.9},
            {"after_scene": "scene_0002", "decision": "hard_break", "reason": "new location and goal", "confidence": 0.9},
            {"after_scene": "scene_0003", "decision": "same_scene", "reason": "same action", "confidence": 0.9},
        ]

        ranges = seg._solve_episode_ranges(cards, boundaries)

        self.assertEqual([(r.start_idx, r.end_idx) for r in ranges], [(0, 2), (3, 4)])

    def test_ranges_to_episodes_has_continuous_times_and_metadata(self):
        seg = self._make_segmenter_simple()
        cards = self._cards([40, 40, 40])
        ranges = [EpisodeRange(0, 1, confidence=0.8, reason="beat ends"), EpisodeRange(2, 2, confidence=0.7)]

        with patch.object(seg, "_ask_gemini_to_name_ranges", return_value={}):
            episodes = seg._ranges_to_episodes(ranges, cards, "Test Film")

        self.assertEqual(episodes[1]["start_time"], episodes[0]["end_time"])
        self.assertEqual(episodes[0]["first_scene"], "scene_0000")
        self.assertEqual(episodes[0]["last_scene"], "scene_0001")
        self.assertIn("confidence", episodes[0])
        self.assertEqual(episodes[0]["episode_type"], "scene")


class TestParseGeminiResponse(unittest.TestCase):

    def _make_segmenter_simple(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    import tempfile
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def test_clean_json(self):
        seg = self._make_segmenter_simple()
        raw = '[{"name": "1. Test", "first_scene": "scene_0000", "last_scene": "scene_0010"}]'
        result = seg._parse_gemini_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["first_scene"], "scene_0000")

    def test_json_with_markdown(self):
        seg = self._make_segmenter_simple()
        raw = '```json\n[{"name": "1. Test", "first_scene": "scene_0000", "last_scene": "scene_0010"}]\n```'
        result = seg._parse_gemini_response(raw)
        self.assertEqual(len(result), 1)

    def test_json_with_trailing_comma(self):
        seg = self._make_segmenter_simple()
        raw = '[{"name": "1. Test", "first_scene": "scene_0000", "last_scene": "scene_0010"},]'
        result = seg._parse_gemini_response(raw)
        self.assertEqual(len(result), 1)


class TestLoadScreenplay(unittest.TestCase):
    """Test _load_screenplay method."""

    def _make_segmenter_with_dir(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        lib_dir = Path(tmp) / "TestFilm"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "scene_data.json").write_text("[]")

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    seg = EpisodeSegmenter(lib_dir)
        return seg, lib_dir

    def test_no_screenplay_returns_none(self):
        """When screenplay.txt doesn't exist, should return None."""
        seg, _ = self._make_segmenter_with_dir()
        result = seg._load_screenplay()
        self.assertIsNone(result)

    def test_empty_screenplay_returns_none(self):
        """When screenplay.txt is empty, should return None."""
        seg, lib_dir = self._make_segmenter_with_dir()
        (lib_dir / "screenplay.txt").write_text("   \n  \n  ")
        result = seg._load_screenplay()
        self.assertIsNone(result)

    def test_valid_screenplay_returns_text(self):
        """When screenplay.txt has content, should return the text."""
        seg, lib_dir = self._make_segmenter_with_dir()
        script = "INT. CALADAN - DAY\n\nPaul wakes up from a dream about Chani."
        (lib_dir / "screenplay.txt").write_text(script)
        result = seg._load_screenplay()
        self.assertEqual(result, script)


class TestBuildPromptWithScript(unittest.TestCase):
    """Test _build_prompt_with_script method."""

    def _make_segmenter_simple(self):
        import tempfile
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def test_prompt_contains_screenplay(self):
        """Script-based prompt should contain the screenplay text."""
        seg = self._make_segmenter_simple()
        screenplay = "INT. ARRAKIS - DAY\nPaul fights Feyd-Rautha."
        scene_table = "scene_id | time\nscene_0000 | 0:00"

        prompt = seg._build_prompt_with_script("Dune", scene_table, screenplay)

        self.assertIn("SCREENPLAY", prompt)
        self.assertIn(screenplay, prompt)
        self.assertIn(scene_table, prompt)
        self.assertIn("Dune", prompt)

    def test_prompt_differs_from_scene_only(self):
        """Script-based prompt must be different from scene-only prompt."""
        seg = self._make_segmenter_simple()
        scene_table = "scene_id | time\nscene_0000 | 0:00"

        prompt_scene_only = seg._build_prompt("Dune", scene_table)
        prompt_with_script = seg._build_prompt_with_script(
            "Dune", scene_table, "Some screenplay text"
        )
        self.assertNotEqual(prompt_scene_only, prompt_with_script)

    def test_long_screenplay_truncated(self):
        """Screenplays longer than 200k chars should be truncated."""
        seg = self._make_segmenter_simple()
        long_script = "A" * 250000
        scene_table = "scene_id | time\nscene_0000 | 0:00"

        prompt = seg._build_prompt_with_script("Dune", scene_table, long_script)
        self.assertIn("[... SCREENPLAY TRUNCATED ...]", prompt)


class TestPromptSelection(unittest.TestCase):
    """Test that _ask_gemini_to_group selects the right prompt."""

    def _make_segmenter_simple(self):
        import tempfile
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    tmp = tempfile.mkdtemp()
                    lib_dir = Path(tmp) / "TestFilm"
                    lib_dir.mkdir(parents=True, exist_ok=True)
                    (lib_dir / "scene_data.json").write_text("[]")
                    seg = EpisodeSegmenter(lib_dir)
        return seg

    def test_screenplay_text_triggers_script_prompt(self):
        """When screenplay_text is set, _build_prompt_with_script should be used."""
        seg = self._make_segmenter_simple()
        seg.screenplay_text = "INT. CALADAN\nPaul wakes up."

        with patch.object(seg, '_build_prompt_with_script', return_value="script_prompt") as mock_script, \
             patch.object(seg, '_build_prompt', return_value="scene_prompt") as mock_scene:
            # Mock the Gemini call to return valid response
            mock_response = MagicMock()
            mock_response.text = '[{"name": "1. Test", "first_scene": "scene_0000", "last_scene": "scene_0010"}]'
            seg.model.generate_content = MagicMock(return_value=mock_response)

            seg._ask_gemini_to_group("Dune", "scene_table")

            mock_script.assert_called_once()
            mock_scene.assert_not_called()

    def test_no_screenplay_uses_scene_prompt(self):
        """When screenplay_text is None, _build_prompt should be used."""
        seg = self._make_segmenter_simple()
        seg.screenplay_text = None

        with patch.object(seg, '_build_prompt_with_script') as mock_script, \
             patch.object(seg, '_build_prompt', return_value="scene_prompt") as mock_scene:
            mock_response = MagicMock()
            mock_response.text = '[{"name": "1. Test", "first_scene": "scene_0000", "last_scene": "scene_0010"}]'
            seg.model.generate_content = MagicMock(return_value=mock_response)

            seg._ask_gemini_to_group("Dune", "scene_table")

            mock_scene.assert_called_once()
            mock_script.assert_not_called()


if __name__ == "__main__":
    unittest.main()
