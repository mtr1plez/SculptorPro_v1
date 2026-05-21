import json
from pathlib import Path
import unittest
from src.ingestion.script_scene_segmenter import ScriptSceneSegmenter

class TestScriptSceneSegmenter(unittest.TestCase):
    def test_parse_screenplay(self):
        screenplay_text = """
1
EXT. GARDENS, WAYNE MANOR -- DAY
1
YOUNG BRUCE peers down rows of plants on long trestle
tables.

2
EXT. DISUSED KITCHEN GARDEN, WAYNE MANOR -- CONTINUOUS
2
Young Bruce crouches in the mouth of a DISUSED WELL, peering
over the stone wall at Rachel, who searches for him.
"""
        segmenter = ScriptSceneSegmenter(Path("dummy_path"))
        scenes = segmenter._parse_screenplay(screenplay_text)
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["scene_num"], 1)
        self.assertEqual(scenes[0]["header"], "EXT. GARDENS, WAYNE MANOR -- DAY")
        self.assertIn("YOUNG BRUCE peers down rows of plants", scenes[0]["content"])
        self.assertEqual(scenes[1]["scene_num"], 2)
        self.assertEqual(scenes[1]["header"], "EXT. DISUSED KITCHEN GARDEN, WAYNE MANOR -- CONTINUOUS")
        self.assertIn("Young Bruce crouches in the mouth", scenes[1]["content"])

    def test_table_to_text(self):
        segmenter = ScriptSceneSegmenter(Path("dummy_path"))
        scenes = [
            {"scene_id": "scene_0000", "start_time": 0, "end_time": 10, "shot_type": "Close-Up", "characters": ["Bruce"]},
            {"scene_id": "scene_0001", "start_time": 10, "end_time": 20, "shot_type": "Wide", "characters": ["Bruce", "Rachel"]},
        ]
        text_table = segmenter._table_to_text(scenes)
        self.assertIn("scene_0000 | 0:00-0:10 | Close-Up | Bruce", text_table)
        self.assertIn("scene_0001 | 0:10-0:20 | Wide | Bruce, Rachel", text_table)

    def test_batman_begins_screenplay(self):
        lib_dir = Path("/Users/morgana/Documents/SculptorPro/_library/Batman Begins")
        if not lib_dir.exists():
            return
        segmenter = ScriptSceneSegmenter(lib_dir)
        text = segmenter._load_screenplay()
        self.assertIsNotNone(text)
        scenes = segmenter._parse_screenplay(text)
        print(f"Parsed {len(scenes)} scenes from Batman Begins")
        self.assertGreater(len(scenes), 300)
        self.assertLess(len(scenes), 350)
        self.assertEqual(scenes[0]["scene_num"], 1)
        self.assertEqual(scenes[-1]["scene_num"], len(scenes))

    def test_intro_episode_created(self):
        """When first screenplay scene doesn't start at scene_0000, a synthetic Intro episode is created."""
        segmenter = ScriptSceneSegmenter(Path("dummy_path"))
        
        # Raw scene list (full movie)
        raw_scene_list = [
            {"scene_id": f"scene_{i:04d}", "start_time": i * 10.0, "end_time": (i + 1) * 10.0}
            for i in range(20)
        ]
        
        # Scene table (same as raw for simplicity)
        scene_table = [
            {"scene_id": f"scene_{i:04d}", "start_time": i * 10.0, "end_time": (i + 1) * 10.0,
             "duration": 10.0, "shot_type": "Medium", "characters": []}
            for i in range(20)
        ]
        
        # Gemini results — first scene starts at scene_0003 (intro is 0-2)
        all_results = [
            {"scene_num": 1, "name": "Bruce plays in the garden", "first_scene": "scene_0003", "last_scene": "scene_0010"},
            {"scene_num": 2, "name": "Bruce falls into the well", "first_scene": "scene_0011", "last_scene": "scene_0019"},
        ]
        
        episodes = segmenter._resolve_and_stitch(all_results, scene_table, raw_scene_list)
        
        # Should have 3 episodes: Intro + 2 screenplay scenes
        self.assertEqual(len(episodes), 3)
        self.assertEqual(episodes[0]["name"], "0. Intro")
        self.assertEqual(episodes[0]["start_time"], 0.0)
        self.assertEqual(episodes[0]["end_time"], 30.0)  # scene_0002 end_time
        self.assertIn("Bruce plays", episodes[1]["name"])
        
    def test_naming_uses_narrative_name(self):
        """_resolve_and_stitch should use res['name'] for narrative naming, not res['header']."""
        segmenter = ScriptSceneSegmenter(Path("dummy_path"))
        
        raw_scene_list = [
            {"scene_id": f"scene_{i:04d}", "start_time": i * 10.0, "end_time": (i + 1) * 10.0}
            for i in range(10)
        ]
        scene_table = [
            {"scene_id": f"scene_{i:04d}", "start_time": i * 10.0, "end_time": (i + 1) * 10.0,
             "duration": 10.0, "shot_type": "Medium", "characters": []}
            for i in range(10)
        ]
        
        all_results = [
            {"scene_num": 1, "name": "Young Bruce falls into the well", "first_scene": "scene_0000", "last_scene": "scene_0004"},
            {"scene_num": 2, "name": "Rachel cries for help", "first_scene": "scene_0005", "last_scene": "scene_0009"},
        ]
        
        episodes = segmenter._resolve_and_stitch(all_results, scene_table, raw_scene_list)
        
        self.assertEqual(len(episodes), 2)
        self.assertIn("Young Bruce falls into the well", episodes[0]["name"])
        self.assertIn("Rachel cries for help", episodes[1]["name"])
        # Should NOT contain raw INT./EXT. headers
        for ep in episodes:
            self.assertNotIn("EXT.", ep["name"])
            self.assertNotIn("INT.", ep["name"])
    
    def test_batch_count_enforcement(self):
        """Prompt should contain EXACTLY N instruction for batch count."""
        segmenter = ScriptSceneSegmenter(Path("dummy_path"))
        batch_scenes = [
            {"scene_num": i, "header": f"EXT. LOCATION_{i}", "content": f"Scene {i} content"}
            for i in range(1, 6)
        ]
        prompt = segmenter._build_batch_prompt("Test Movie", batch_scenes, "scene_table_text", None)
        self.assertIn("EXACTLY 5", prompt)
        self.assertIn("5 screenplay scenes", prompt)

if __name__ == "__main__":
    unittest.main()
