from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class IngestRequest(BaseModel):
    file_path: str
    alias: str
    fullname: str



class ProjectCreateRequest(BaseModel):
    name: str
    matching_mode: str = "chaotic"  # "chaotic" | "sequential"

class ProjectCreateFromStudioRequest(BaseModel):
    name: str
    matching_mode: str = "chaotic"
    audio_filename: str


class Episode(BaseModel):
    id: str
    name: str
    start_time: str # "HH:MM:SS" ?? Or float seconds? The plan said float. Let's support both or decide. Plan said models: start_time: float. BUT user said "names and timecodes". It is better to use string timecodes "00:00:00" in API and convert, OR keep it simple. Let's use float seconds as source of truth, and frontend can send string if it wants, but `models.py` defines API type.
    # Actually, easy to debug with strings "00:01:23". 
    # But for calculation `float` is better.
    # Let's stick to Plan: start_time: float
    start_time: float
    end_time: float

class EpisodeCreateRequest(BaseModel):
    name: str
    start_time: float
    end_time: float

class EpisodeUpdateRequest(BaseModel):
    name: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None

class TrackAddRequest(BaseModel):
    audio_path: str
    source_alias: str
    episode_ids: Optional[List[str]] = None
    episode_names: Optional[List[str]] = None
    segmentation_mode: str = "episodes"  # "episodes" | "characters"
    character_names: Optional[List[str]] = None

class TrackUpdateRequest(BaseModel):
    episode_ids: Optional[List[str]] = None
    episode_names: Optional[List[str]] = None
    segmentation_mode: Optional[str] = None
    character_names: Optional[List[str]] = None

class SegmentedTimelineItem(BaseModel):
    id: str
    source_alias: str
    episode_id: Optional[str] = None
    episode_name: Optional[str] = None
    timeline_start: float       # Start position on the audio timeline (seconds)
    timeline_duration: float    # Duration of this clip on the timeline (seconds)
    clip_type: str = "episode"           # "episode", "character", or "group"
    character_name: Optional[str] = None # for clip_type="character"
    matcher_mode: str = "sequential"     # "sequential" or "chaotic"
    group_items: Optional[List[Dict[str, Any]]] = None  # for clip_type="group"
    group_selection_mode: Optional[str] = None  # "score" or "alternate" for clip_type="group"

class SegmentedTimelineSaveRequest(BaseModel):
    items: List[SegmentedTimelineItem]


class AutoTimelinePlanRequest(BaseModel):
    script_text: str
    source_aliases: List[str]
    group_ids: Optional[List[str]] = None
    model: Optional[str] = None
    save: bool = True


# === GROUPS ===

class GroupItem(BaseModel):
    source_alias: str
    type: str  # "episode" | "character"
    name: str
    episode_id: Optional[str] = None  # only for type="episode"

class GroupCreateRequest(BaseModel):
    name: str
    items: List[GroupItem]

class GroupUpdateRequest(BaseModel):
    name: Optional[str] = None
    items: Optional[List[GroupItem]] = None
