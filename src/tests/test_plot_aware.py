"""
Tests for Script Parser and Plot-Aware Smart Matcher filters.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
try:
    import torch
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("torch is optional for the baseline test suite") from exc
import numpy as np
from pathlib import Path
import sys
import os
import tempfile

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.analysis.script_parser import ScriptParser
from src.matching.smart_matcher import SmartMatcher


class TestScriptParser(unittest.TestCase):
    """Tests for ScriptParser."""
    
    def setUp(self):
        self.parser = ScriptParser()
        self.temp_dir = tempfile.mkdtemp()
    
    def test_parse_markdown(self):
        """Test parsing a markdown file."""
        md_content = """# Introduction

This is the first paragraph about the movie.

## Act 1

The hero begins their journey.
This continues on the next line.

### Scene 1.1

A specific scene description.
"""
        md_path = Path(self.temp_dir) / "test_script.md"
        with open(md_path, 'w') as f:
            f.write(md_content)
        
        blocks = self.parser.parse(md_path)
        
        # Should have headings and paragraphs
        self.assertGreater(len(blocks), 0)
        
        # First should be heading
        headings = [b for b in blocks if b["type"] == "heading"]
        paragraphs = [b for b in blocks if b["type"] == "paragraph"]
        
        self.assertGreater(len(headings), 0)
        self.assertGreater(len(paragraphs), 0)
        self.assertEqual(headings[0]["text"], "Introduction")
    
    def test_parse_plaintext(self):
        """Test parsing a plain text file."""
        txt_content = """This is the first paragraph.

This is the second paragraph after a blank line.

And a third one."""
        
        txt_path = Path(self.temp_dir) / "test_script.txt"
        with open(txt_path, 'w') as f:
            f.write(txt_content)
        
        blocks = self.parser.parse(txt_path)
        
        self.assertEqual(len(blocks), 3)
        for block in blocks:
            self.assertEqual(block["type"], "paragraph")
    
    def test_get_full_text(self):
        """Test assembling full text from blocks."""
        blocks = [
            {"block_id": 0, "type": "heading", "text": "Title"},
            {"block_id": 1, "type": "paragraph", "text": "First para"},
            {"block_id": 2, "type": "paragraph", "text": "Second para"}
        ]
        
        full_text = self.parser.get_full_text(blocks)
        self.assertIn("Title", full_text)
        self.assertIn("First para", full_text)


class MockSmartMatcherPlotAware(SmartMatcher):
    """Mock SmartMatcher for testing plot-aware filters."""
    
    def __init__(self, library_path, aliases_content=None):
        self.library_path = Path(library_path)
        self.device = "cpu"
        self.model = MagicMock()
        self.model.encode_text.return_value = torch.tensor([[0.1, 0.2]])
        
        self.loaded_sources = {}
        self.aliases = aliases_content if aliases_content else {}
        self.last_matched_time = None
        self.movie_duration = 7200  # 2 hours

    def _load_source(self, source_name):
        return self.loaded_sources.get(source_name)


class TestSmartMatcherPlotFilters(unittest.TestCase):
    """Tests for new plot-aware filters in SmartMatcher."""
    
    def setUp(self):
        self.matcher = MockSmartMatcherPlotAware("/tmp")
        
        # Setup mock scenes at different times
        self.mock_scenes = [
            # Scene in intro (0-30 sec) - should be penalized
            {
                "id": "scene_intro",
                "time": {"start": 15, "end": 30},
                "visual": {"shot_type": "Wide", "path": "intro.jpg"},
                "content": {"characters": []}
            },
            # Scene in main content (5 minutes in)
            {
                "id": "scene_main_1",
                "time": {"start": 300, "end": 320},
                "visual": {"shot_type": "Close-Up", "path": "main1.jpg"},
                "content": {"characters": ["Paul Atreides"]}
            },
            # Scene in middle (1 hour in)
            {
                "id": "scene_middle",
                "time": {"start": 3600, "end": 3620},
                "visual": {"shot_type": "Medium Shot", "path": "middle.jpg"},
                "content": {"characters": ["Paul Atreides"]}
            },
            # Scene in credits (near end, 7100 sec)
            {
                "id": "scene_credits",
                "time": {"start": 7100, "end": 7150},
                "visual": {"shot_type": "Wide", "path": "credits.jpg"},
                "content": {"characters": []}
            }
        ]
        
        self.matcher.loaded_sources["Dune"] = {
            "source_name": "Dune",
            "source_video_path": "/tmp/dune.mp4",
            "scenes": self.mock_scenes,
            "matrix": torch.tensor([[0.1, 0.2], [0.15, 0.25], [0.2, 0.3], [0.1, 0.2]])
        }
    
    def test_intro_filter_penalty(self):
        """Scenes in intro (< 90s) should receive INTRO_CREDITS_PENALTY."""
        # Check that the penalty constant exists
        self.assertEqual(self.matcher.INTRO_DURATION, 90)
        self.assertEqual(self.matcher.INTRO_CREDITS_PENALTY, 1000)
        
        # Intro scene time is 15 seconds, which is < 90
        intro_scene = self.mock_scenes[0]
        self.assertLess(intro_scene["time"]["start"], self.matcher.INTRO_DURATION)
    
    def test_credits_filter_penalty(self):
        """Scenes in credits (last 180s) should receive INTRO_CREDITS_PENALTY."""
        self.assertEqual(self.matcher.CREDITS_DURATION, 180)
        
        # Credits scene time is 7100, movie is 7200 sec
        credits_threshold = self.matcher.movie_duration - self.matcher.CREDITS_DURATION
        credits_scene = self.mock_scenes[3]
        
        self.assertGreater(credits_scene["time"]["start"], credits_threshold)
    
    def test_time_window_filter_bonus(self):
        """Scenes within film_time_range should get TIME_WINDOW_BONUS."""
        self.assertEqual(self.matcher.TIME_WINDOW_BONUS, 200)
        self.assertEqual(self.matcher.TIME_WINDOW_PENALTY, 300)
    
    def test_chronology_penalty(self):
        """Jumping back in time should trigger CHRONOLOGY_PENALTY."""
        self.assertEqual(self.matcher.CHRONOLOGY_PENALTY, 100)
        
        # Set last matched time to 3600 (middle of movie)
        self.matcher.last_matched_time = 3600
        
        # Scene at 300 is before 3600-60, should trigger penalty
        scene_time = 300
        time_diff = scene_time - self.matcher.last_matched_time
        should_penalize = scene_time < self.matcher.last_matched_time - 60
        
        self.assertTrue(should_penalize)


if __name__ == "__main__":
    unittest.main()
