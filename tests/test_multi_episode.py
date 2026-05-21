import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from matching.sequential_matcher import SequentialMatcher
from matching.chaotic_matcher import ChaoticMatcher
from matching.smart_matcher import SmartMatcher

class TestMultiEpisode(unittest.TestCase):
    def setUp(self):
        self.matcher = SequentialMatcher("dummy_lib_path")
        # Mock source data
        self.source_data = {
            "scenes": [
                {"id": "s1", "time": {"start": 0, "end": 10}, "visual": {"path": "v1"}},
                {"id": "s2", "time": {"start": 20, "end": 30}, "visual": {"path": "v2"}}, # Gap 10-20
                {"id": "s3", "time": {"start": 40, "end": 50}, "visual": {"path": "v3"}}, # Gap 30-40
                {"id": "s4", "time": {"start": 60, "end": 70}, "visual": {"path": "v4"}},
            ],
            "matrix": MagicMock() # Mock matrix
        }
        # Mock encode_text
        self.matcher._encode_text = MagicMock(return_value=MagicMock())
        # self.matcher._is_interval_blocked = MagicMock(return_value=False) # Use real logic
        
        # Mock torch dot product to return constant score
        with patch('torch.dot', return_value=1.0):
            pass

    def test_sequential_disjoint_ranges(self):
        """
        Test that SequentialMatcher respects multiple disjoint ranges.
        Ranges: [0-15] and [50-75]
        Expected: s1 (0-10) is valid. s2 (20-30) is INVALID. s3 (40-50) is INVALID (starts at 40, end at 50, but range starts 50? No wait, [50-75]).
        s4 (60-70) is valid.
        """
        ranges = [(0, 15), (55, 75)]
        
        # 1. Test Scene s1 (0-10) -> Should be found
        # We need to simulate _find_best_clip_match logic
        # But we can call the method directly with mocked data
        
        # Hack to make the method use our mock source
        
        # Test s1 (0-10)
        # It falls in [0-15]. Should be valid.
        
        # Test s2 (20-30)
        # It falls in gap. Should be invalid.
        
        # Test s4 (60-70)
        # It falls in [55-75]. Should be valid.
        
        with patch('torch.dot', return_value=MagicMock(item=lambda: 1.0)):
             # We need to mock the internal loop of _find_best_clip_match or just test the helper logic if extracted.
             # Since it's monolithic, we run the method.
             
             # Case A: Search for duration 5.0
             # s1 (0-10) is valid.
             match = self.matcher._find_best_clip_match(
                 "test", 
                 self.source_data, 
                 5.0, 
                 [], 
                 ranges
             )
             self.assertIsNotNone(match)
             self.assertEqual(match["scene"]["id"], "s1") # greedy first match
             
             # Case B: Block s1. Check if s2 (gap) is skipped and s4 is found.
             # s2 is 20-30. Ranges are [0-15], [55-75].
             # s2 is OUT. s3 is 40-50. OUT.
             # s4 is 60-70. IN.
             
             blocked = [(0, 15)] # block first range effectively
             match = self.matcher._find_best_clip_match(
                 "test", 
                 self.source_data, 
                 5.0, 
                 blocked, 
                 ranges
             )
             self.assertIsNotNone(match)
             self.assertEqual(match["scene"]["id"], "s4")

    def test_smart_virtual_timeline(self):
        """
        Test SmartMatcher virtual timeline mapping.
        Ep1: 0-100. Ep2: 500-600.
        Total Virtual: 200s.
        Segment at 50% (idx 1/2) -> Should map to start of Ep2 (Real 500).
        """
        sm = SmartMatcher("dummy")
        ranges = [(0, 100), (500, 600)]
        
        # Test Seg 0/2 (Start) -> 0% -> 0
        z0 = sm._calculate_temporal_zone(0, 2, ranges)
        # Zone width = 100. Overlap 30.
        # Start: 0 - 30 -> 0 (clamped). End: 100 + 30 -> 100? No.
        # Virtual Start: 0. Virtual End: 100.
        # Real Map: 0 -> 0. 100 -> 100.
        # Result (0, 100) approx
        print(f"Zone 0: {z0}")
        self.assertTrue(z0[0] <= 10)
        self.assertTrue(z0[1] >= 90)
        
        # Test Seg 1/2 (End) -> 50% -> Starts at Virtual 100.
        z1 = sm._calculate_temporal_zone(1, 2, ranges)
        # Virtual Start: 100 - 30 = 70. Virtual End: 200 + 30 = 230 -> 200.
        # Real Map: 
        # 70 -> 70 (Ep1). 
        # 200 -> 600 (End of Ep2).
        # Expected: (70, 600)
        # This spans the gap! But scene filter should reject gap.
        print(f"Zone 1: {z1}")
        self.assertEqual(z1[1], 600)
        self.assertTrue(z1[0] < 100) # Should start back in Ep1 due to overlap

if __name__ == '__main__':
    unittest.main()
