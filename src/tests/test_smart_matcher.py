
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

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.matching.smart_matcher import SmartMatcher

class MockSmartMatcher(SmartMatcher):
    def __init__(self, library_path, aliases_content=None):
        self.library_path = Path(library_path)
        self.device = "cpu"
        self.model = MagicMock()
        
        # Mock embeddings to always return something valid
        self.model.encode_text.return_value = torch.tensor([[0.1, 0.2]])
        
        self.loaded_sources = {}
        self.aliases = aliases_content if aliases_content else {}

    def _load_source(self, source_name):
        # Return mock data directly
        return self.loaded_sources.get(source_name)

class TestSmartMatcherMatching(unittest.TestCase):
    def setUp(self):
        self.matcher = MockSmartMatcher("/tmp", aliases_content={"Duke": "Leto Atreides"})
        
        # Setup mock source data
        # Scene 1: Leto Atreides exists
        # Scene 2: Paul Atreides exists
        # Scene 3: No characters
        self.mock_scenes = [
            {
                "id": "scene_1",
                "time": {"start": 0, "end": 10},
                "visual": {"shot_type": "Close-Up", "path": "img1.jpg"},
                "content": {"characters": ["Leto Atreides"]}
            },
            {
                "id": "scene_2",
                "time": {"start": 10, "end": 20},
                "visual": {"shot_type": "Wide", "path": "img2.jpg"},
                "content": {"characters": ["Paul Atreides"]}
            }
        ]
        
        self.matcher.loaded_sources["Dune"] = {
            "source_name": "Dune",
            "source_video_path": "/tmp/dune.mp4",
            "scenes": self.mock_scenes,
            # Mock matrix compatible with encode_text mock (1x2)
            "matrix": torch.tensor([[0.1, 0.2], [0.3, 0.4]]) 
        }

    @patch("src.matching.smart_matcher.clip.tokenize")
    def test_exact_match(self, mock_tokenize):
        # Mock tokenize to return something that moves to device
        mock_tokenize.return_value.to.return_value = "tokens"
        
        # Script looking for "Leto Atreides"
        script = [{
            "text": "Scene with Leto",
            "character": "Leto Atreides",
            "start": 0, "end": 5
        }]
        
        output_path = "/tmp/test_output.json"
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(script))) as mock_file:
            self.matcher.match("dummy_script.json", output_path, ["Dune"])
            
            # Combine all write calls
            handle = mock_file()
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            written_json = json.loads(written_data)
            
            # Should match scene_1 (Leto Atreides)
            self.assertEqual(len(written_json), 1)
            self.assertEqual(written_json[0]["scene_id"], "scene_1")
            self.assertGreater(written_json[0]["match_score"], 500) # Bonus applied

    @patch("src.matching.smart_matcher.clip.tokenize")
    def test_partial_match(self, mock_tokenize):
        mock_tokenize.return_value.to.return_value = "tokens"
        
        # Script looking for "Leto" (Partial of "Leto Atreides")
        script = [{
            "text": "Scene with Leto",
            "character": "Leto",
            "start": 0, "end": 5
        }]
        
        output_path = "/tmp/test_output.json"
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(script))) as mock_file:
            self.matcher.match("dummy_script.json", output_path, ["Dune"])
            
            handle = mock_file()
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            written_json = json.loads(written_data)
            
            # Should match scene_1 (Leto is in Leto Atreides)
            self.assertEqual(written_json[0]["scene_id"], "scene_1") 
            self.assertGreater(written_json[0]["match_score"], 500)

    @patch("src.matching.smart_matcher.clip.tokenize")
    def test_alias_match(self, mock_tokenize):
        mock_tokenize.return_value.to.return_value = "tokens"
        
        # Script looking for "Duke" (Alias for "Leto Atreides")
        script = [{
            "text": "Scene with Duke",
            "character": "Duke",
            "start": 0, "end": 5
        }]
        
        output_path = "/tmp/test_output.json"
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(script))) as mock_file:
            self.matcher.match("dummy_script.json", output_path, ["Dune"])
            
            handle = mock_file()
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            written_json = json.loads(written_data)
            
            # Should match scene_1 (Duke -> Leto Atreides)
            self.assertEqual(written_json[0]["scene_id"], "scene_1")
            self.assertGreater(written_json[0]["match_score"], 500)

    @patch("src.matching.smart_matcher.clip.tokenize")
    def test_no_match(self, mock_tokenize):
        mock_tokenize.return_value.to.return_value = "tokens"
        
        # Script looking for "Harkonnen" (Not in scenes)
        script = [{
            "text": "Scene with Harkonnen",
            "character": "Harkonnen",
            "start": 0, "end": 5
        }]
        
        output_path = "/tmp/test_output.json"
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(script))) as mock_file:
            self.matcher.match("dummy_script.json", output_path, ["Dune"])
            
            handle = mock_file()
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            written_json = json.loads(written_data)
            
            if written_json:
                 # Should NOT have high score/bonus
                 self.assertLess(written_json[0]["match_score"], 0)

if __name__ == "__main__":
    unittest.main()
