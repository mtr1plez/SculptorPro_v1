import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.getcwd())

from src.project_manager import ProjectManager
from src.utils.app_paths import get_app_data_dir

def verify():
    print(f"Testing environment...")
    print(f"App Data Dir: {get_app_data_dir()}")
    
    manager = ProjectManager()
    
    print(f"Manager Library: {manager.library_path}")
    print(f"Manager Projects: {manager.projects_path}")
    
    expected_root = get_app_data_dir()
    
    assert manager.library_path == expected_root / "_library"
    assert manager.projects_path == expected_root / "projects"
    
    print("\n✅ Verification SUCCESS: Paths are correct.")

if __name__ == "__main__":
    verify()
