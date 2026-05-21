import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import app directly - patching ProjectManager inside server is hard if imported at top level
# So we mock sys.modules? Or just accept we need to init real app but mock manager.
from src.api.server import app, manager

client = TestClient(app)

class TestMultiEpisodeAPI(unittest.TestCase):
    def setUp(self):
        # Reset mock
        manager.add_track = MagicMock(return_value={"id": "track1", "episode_ids": ["ep1", "ep2"]})

    def test_add_track_multi_episode(self):
        """
        Test that /projects/{name}/tracks accepts episode_ids list.
        """
        payload = {
            "audio_path": "/path/to/audio.wav",
            "source_alias": "Movie1",
            "episode_ids": ["ep1", "ep2"],
            "episode_names": ["Episode 1", "Episode 2"]
        }
        
        response = client.post("/projects/TestProject/tracks", json=payload)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["episode_ids"], ["ep1", "ep2"])
        
        # Verify manager called correctly
        manager.add_track.assert_called_once_with(
            "TestProject", 
            "/path/to/audio.wav", 
            "Movie1", 
            ["ep1", "ep2"], 
            ["Episode 1", "Episode 2"]
        )

if __name__ == '__main__':
    unittest.main()
