import unittest
import os
import shutil
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.premiere_exporter import PremiereExporter

class TestPremiereDeduplication(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/output")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.edl_path = self.test_dir / "test_edl.json"
        self.xml_path = self.test_dir / "test_output.xml"
        self.video_path = Path("/path/to/source_video.mp4")
        self.audio_path = self.test_dir / "test_audio.mp3"
        
        # Create a dummy audio file
        with open(self.audio_path, 'w') as f:
            f.write("dummy audio content")

        # Create a dummy EDL with 3 clips using same source
        self.edl = [
            {
                "target_duration": 5.0,
                "source_video_path": str(self.video_path),
                "in_point": 10.0,
                "text": "Clip 1"
            },
            {
                "target_duration": 5.0,
                "source_video_path": str(self.video_path),
                "in_point": 20.0,
                "text": "Clip 2"
            },
            {
                "target_duration": 5.0,
                "source_video_path": str(self.video_path),
                "in_point": 30.0,
                "text": "Clip 3"
            }
        ]
        
        with open(self.edl_path, 'w') as f:
            json.dump(self.edl, f)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_file_deduplication(self):
        exporter = PremiereExporter()
        
        # Mock file existence check to avoid actual file system dependency for video
        original_exists = Path.exists
        def mock_exists(path):
            if str(path) == str(self.video_path):
                return True
            return original_exists(path)
            
        Path.exists = mock_exists
        
        try:
            exporter.export(self.edl_path, self.xml_path, self.audio_path)
        finally:
             Path.exists = original_exists
        
        tree = ET.parse(self.xml_path)
        root = tree.getroot()
        
        # Find all <file> elements anywhere in the tree
        all_file_nodes = root.findall(".//file")
        
        unique_file_ids = set()
        full_definitions = 0
        
        print(f"\nFound {len(all_file_nodes)} file references in XML")
        
        for f in all_file_nodes:
            fid = f.get("id")
            if fid:
                unique_file_ids.add(fid)
            
            # Check if it has children (full definition)
            # A full definition has child elements like <name>, <pathurl>, <duration>, etc.
            if len(list(f)) > 0:
                full_definitions += 1
                
        # With 3 video clips + 1 audio track:
        # If deduplicated: 
        # - Video file ID should be same for all 3 clips (e.g. file-video-source-1)
        # - Audio file ID should be unique (e.g. file-audio-1)
        # - Total unique IDs = 2
        
        print(f"Unique File IDs: {len(unique_file_ids)} (Expected 2)")
        print(f"Full File Definitions: {full_definitions} (Expected 2)")
        
        # This assertion will fail BEFORE the fix, confirming the bug
        self.assertEqual(len(unique_file_ids), 2, f"Expected 2 unique files (1 audio, 1 video), found {len(unique_file_ids)}")
        
if __name__ == '__main__':
    unittest.main()
