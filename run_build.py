import asyncio
from src.project_manager import ProjectManager

def progress(percent, status, **kwargs):
    print(f"{percent}%: {status}")

async def build():
    pm = ProjectManager("library", "projects")
    project_name = "TikTok"
    await pm.build_segmented_timeline_project(project_name, progress)
    
if __name__ == "__main__":
    asyncio.run(build())
