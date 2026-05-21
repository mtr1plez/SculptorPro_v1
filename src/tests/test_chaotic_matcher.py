import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.matching.chaotic_matcher import ChaoticMatcher


def _make_matcher(library_path):
    matcher = ChaoticMatcher.__new__(ChaoticMatcher)
    matcher.library_path = Path(library_path)
    matcher.device = "cpu"
    matcher.loaded_sources = {}
    matcher.aliases = {}
    return matcher


def _write_source(library_path, source_name, scenes):
    source_dir = Path(library_path) / source_name
    source_dir.mkdir()
    with open(source_dir / "master_index.json", "w") as f:
        json.dump({
            "source_video_path": f"/fake/{source_name}.mp4",
            "scenes": scenes,
        }, f)
    embeddings = {scene["id"]: np.ones(512, dtype=np.float32) for scene in scenes}
    np.save(source_dir / "embeddings.npy", embeddings)


def _scene(scene_id, start, end, characters=None):
    return {
        "id": scene_id,
        "time": {"start": start, "end": end},
        "content": {"characters": characters or [], "raw_ids": []},
        "visual": {"path": f"/fake/{scene_id}.jpg"},
    }


class TestChaoticMatcherRanges(unittest.TestCase):
    def test_source_scoped_ranges_do_not_leak_between_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_source(tmpdir, "MovieA", [_scene("scene_1", 100.0, 110.0, ["Alice"])])
            _write_source(tmpdir, "MovieB", [_scene("scene_1", 100.0, 110.0, ["Bob"])])

            script_path = Path(tmpdir) / "script.json"
            output_path = Path(tmpdir) / "edl.json"
            with open(script_path, "w") as f:
                json.dump([{
                    "segment_id": 1,
                    "text": "",
                    "visual_query": "",
                    "character": "Bob",
                    "duration": 2.0,
                    "start": 0.0,
                }], f)

            random.seed(1)
            matcher = _make_matcher(tmpdir)
            matcher.match(
                script_path,
                output_path,
                ["MovieA", "MovieB"],
                episode_time_ranges=[
                    {"source_alias": "MovieA", "start": 100.0, "end": 110.0}
                ],
            )

            with open(output_path) as f:
                edl = json.load(f)

            self.assertEqual(len(edl), 1)
            self.assertEqual(edl[0]["source_project_alias"], "MovieA")

    def test_output_is_clamped_to_allowed_range_intersection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_source(tmpdir, "MovieA", [_scene("scene_1", 0.0, 20.0, ["Alice"])])

            script_path = Path(tmpdir) / "script.json"
            output_path = Path(tmpdir) / "edl.json"
            with open(script_path, "w") as f:
                json.dump([{
                    "segment_id": 1,
                    "text": "",
                    "visual_query": "",
                    "duration": 2.0,
                    "start": 0.0,
                }], f)

            random.seed(1)
            matcher = _make_matcher(tmpdir)
            matcher.match(
                script_path,
                output_path,
                ["MovieA"],
                episode_time_ranges=[
                    {"source_alias": "MovieA", "start": 5.0, "end": 8.0}
                ],
            )

            with open(output_path) as f:
                edl = json.load(f)

            self.assertGreaterEqual(edl[0]["in_point"], 5.0)
            self.assertLessEqual(edl[0]["out_point"], 8.0)
            self.assertAlmostEqual(edl[0]["target_duration"], 2.0)

    def test_short_source_marks_actual_duration_separately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_source(tmpdir, "MovieA", [_scene("scene_1", 0.0, 2.0, ["Alice"])])

            script_path = Path(tmpdir) / "script.json"
            output_path = Path(tmpdir) / "edl.json"
            with open(script_path, "w") as f:
                json.dump([{
                    "segment_id": 1,
                    "text": "",
                    "visual_query": "",
                    "duration": 5.0,
                    "start": 0.0,
                }], f)

            matcher = _make_matcher(tmpdir)
            matcher.match(script_path, output_path, ["MovieA"])

            with open(output_path) as f:
                edl = json.load(f)

            self.assertEqual(edl[0]["duration"], 2.0)
            self.assertEqual(edl[0]["target_duration"], 5.0)
            self.assertIn("ShortSource", edl[0]["match_type"])

    def test_alternate_source_selection_rotates_group_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_source(tmpdir, "MovieA", [
                _scene("a_1", 0.0, 10.0),
                _scene("a_2", 20.0, 30.0),
            ])
            _write_source(tmpdir, "MovieB", [
                _scene("b_1", 0.0, 10.0),
                _scene("b_2", 20.0, 30.0),
            ])

            script_path = Path(tmpdir) / "script.json"
            output_path = Path(tmpdir) / "edl.json"
            with open(script_path, "w") as f:
                json.dump([
                    {
                        "segment_id": idx,
                        "text": "",
                        "visual_query": "",
                        "duration": 2.0,
                        "start": idx * 2.0,
                    }
                    for idx in range(4)
                ], f)

            random.seed(1)
            matcher = _make_matcher(tmpdir)
            matcher.match(
                script_path,
                output_path,
                ["MovieA", "MovieB"],
                source_selection_mode="alternate",
            )

            with open(output_path) as f:
                edl = json.load(f)

            self.assertEqual(
                [clip["source_project_alias"] for clip in edl],
                ["MovieA", "MovieB", "MovieA", "MovieB"],
            )

    def test_repeated_scene_uses_do_not_overlap_source_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_source(tmpdir, "MovieA", [
                _scene("scene_1", 0.0, 8.0, ["Alice"]),
            ])

            script_path = Path(tmpdir) / "script.json"
            output_path = Path(tmpdir) / "edl.json"
            with open(script_path, "w") as f:
                json.dump([
                    {
                        "segment_id": idx,
                        "text": "",
                        "visual_query": "",
                        "character": "Alice",
                        "duration": 2.0,
                        "start": idx * 2.0,
                    }
                    for idx in range(3)
                ], f)

            random.seed(1)
            matcher = _make_matcher(tmpdir)
            matcher.match(script_path, output_path, ["MovieA"])

            with open(output_path) as f:
                edl = json.load(f)

            intervals = sorted((clip["in_point"], clip["out_point"]) for clip in edl)
            self.assertEqual(len(intervals), 3)
            for prev, curr in zip(intervals, intervals[1:]):
                self.assertLessEqual(prev[1], curr[0])


class TestChaoticMatcherCharacters(unittest.TestCase):
    def test_character_matching_uses_tokens_not_raw_substrings(self):
        matcher = _make_matcher("/tmp")

        self.assertTrue(matcher._character_matches("Bruce", ["Bruce Wayne"]))
        self.assertFalse(matcher._character_matches("Ann", ["Joanna"]))

    def test_character_matching_uses_aliases(self):
        matcher = _make_matcher("/tmp")
        matcher.aliases = {"Duke": "Leto Atreides"}

        self.assertTrue(matcher._character_matches("Duke", ["Leto Atreides"]))
        self.assertTrue(matcher._character_matches("Leto Atreides", ["Duke"]))


if __name__ == "__main__":
    unittest.main()
