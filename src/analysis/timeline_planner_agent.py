import json
import logging
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class TimelinePlannerAgent:
    """
    Plans the high-level segmented timeline from exact script text, approximate
    Whisper timing, and selected library sources.
    """

    def __init__(self, library_path, model_name=None):
        self.library_path = Path(library_path)
        self.client = GeminiClient(model_name) if model_name else GeminiClient()

    def _make_units(self, transcript: Dict[str, Any], target_duration=14.0) -> List[Dict[str, Any]]:
        batches = transcript.get("batches", []) if isinstance(transcript, dict) else []
        segments = []
        for batch in batches:
            for seg in batch.get("segments", []):
                try:
                    start = float(seg.get("start", 0))
                    end = float(seg.get("end", start))
                except (TypeError, ValueError):
                    continue
                if end <= start:
                    continue
                segments.append({
                    "start": start,
                    "end": end,
                    "text": str(seg.get("text", "")).strip(),
                })

        if not segments:
            duration = float(transcript.get("duration", 0) or 0)
            if duration <= 0:
                duration = 10.0
            return [{"unit_id": 0, "start": 0.0, "end": duration, "whisper_text": ""}]

        units = []
        current = []
        for seg in segments:
            current.append(seg)
            unit_start = current[0]["start"]
            unit_end = current[-1]["end"]
            text = " ".join(s["text"] for s in current).strip()
            strong_end = text.endswith((".", "!", "?", "…"))
            if (unit_end - unit_start >= target_duration and strong_end) or unit_end - unit_start >= target_duration * 1.6:
                units.append({
                    "unit_id": len(units),
                    "start": unit_start,
                    "end": unit_end,
                    "whisper_text": text,
                })
                current = []

        if current:
            units.append({
                "unit_id": len(units),
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "whisper_text": " ".join(s["text"] for s in current).strip(),
            })

        total_duration = float(transcript.get("duration", 0) or 0)
        if total_duration > 0 and units:
            units[0]["start"] = 0.0
            units[-1]["end"] = max(units[-1]["end"], total_duration)
        return units

    def _load_source_context(self, source_aliases: List[str]) -> List[Dict[str, Any]]:
        sources = []
        for alias in source_aliases:
            source_dir = self.library_path / alias
            if not source_dir.exists():
                continue

            episodes = []
            episodes_path = source_dir / "episodes.json"
            if episodes_path.exists():
                try:
                    with open(episodes_path, "r", encoding="utf-8") as f:
                        raw_episodes = json.load(f)
                    if isinstance(raw_episodes, dict):
                        raw_episodes = raw_episodes.get("episodes", [])
                    for ep in raw_episodes or []:
                        episodes.append({
                            "id": ep.get("id"),
                            "name": ep.get("name"),
                            "start_time": ep.get("start_time"),
                            "end_time": ep.get("end_time"),
                        })
                except Exception as e:
                    logger.warning(f"Could not load episodes for {alias}: {e}")

            characters = []
            char_map_path = source_dir / "character_map.json"
            if char_map_path.exists():
                try:
                    with open(char_map_path, "r", encoding="utf-8") as f:
                        char_map = json.load(f)
                    characters = sorted({name for name in char_map.values() if name and name != "Unknown"})
                except Exception as e:
                    logger.warning(f"Could not load characters for {alias}: {e}")

            sources.append({
                "alias": alias,
                "episodes": episodes,
                "characters": characters,
            })
        return sources

    def _load_group_context(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "id": group.get("id"),
                "name": group.get("name"),
                "items": group.get("items", []),
            }
            for group in groups
        ]

    def _prompt(self, script_text: str, units: List[Dict[str, Any]], sources: List[Dict[str, Any]], groups: List[Dict[str, Any]]) -> str:
        return f"""
Role: Senior video essay timeline director for SculptorPro.

You create a HIGH-LEVEL EDITING PLAN, not final frame matches. SculptorPro will later pick exact shots.

Inputs:
1. EXACT SCRIPT TEXT. This is the source of truth for meaning. Use it to understand the real context.
2. WHISPER TIMING UNITS. These provide approximate audio boundaries. Whisper text can contain recognition errors.
3. AVAILABLE SOURCES. You may use only these films/series and groups.

Exact script text:
{script_text}

Whisper timing units:
{json.dumps(units, ensure_ascii=False, indent=2)}

Available sources:
{json.dumps(sources, ensure_ascii=False, indent=2)}

Available groups:
{json.dumps(groups, ensure_ascii=False, indent=2)}

Decision rules:
- Return exactly one plan item for every timing unit, preserving unit_id order.
- Use timing unit start/end exactly as the clip boundaries; do not invent timings.
- If the narration names a specific episode/moment and a matching episode exists, choose clip_type "episode" with that source_alias and episode_id.
- If the narration focuses on a specific character and that character exists in one selected source, choose clip_type "character" with source_alias and character_name.
- If the narration is broad/general about an archetype or character across several selected adaptations, prefer a relevant group if it exists.
- Example: broad "Batman as a symbol" may use a Batman group across Reeves/Nolan/animation. A specific "Joker" mention should use the source where Joker exists.
- If a specific episode is mentioned but unavailable, fall back in this order: exact character, relevant group, then full source.
- For abstract analysis, choose the source/group that best matches the emotional context, theme, or visual mood.
- Do not choose unavailable characters, episodes, sources, or groups.
- Favor "chaotic" matcher for characters, groups, abstract montage, emotions, and cross-source concepts.
- Favor "sequential" matcher only for a concrete episode/moment where chronological continuity matters.
- Avoid changing sources every tiny beat unless the text really changes subject.

Output JSON only:
[
  {{
    "unit_id": 0,
    "clip_type": "episode" | "character" | "group" | "source",
    "source_alias": "source alias or null for group",
    "episode_id": "episode id or null",
    "character_name": "character name or null",
    "group_id": "group id or null",
    "label": "short human readable label",
    "matcher_mode": "chaotic" | "sequential",
    "group_selection_mode": "score" | "alternate",
    "confidence": 0.0,
    "reason": "brief practical reason"
  }}
]
"""

    @staticmethod
    def _norm(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _find_source(self, sources: List[Dict[str, Any]], alias: Optional[str]) -> Optional[Dict[str, Any]]:
        key = self._norm(alias)
        return next((source for source in sources if self._norm(source.get("alias")) == key), None)

    def _find_episode(self, source: Dict[str, Any], episode_id: Optional[str], name: Optional[str]) -> Optional[Dict[str, Any]]:
        episodes = source.get("episodes") or []
        if episode_id:
            match = next((ep for ep in episodes if str(ep.get("id")) == str(episode_id)), None)
            if match:
                return match
        name_key = self._norm(name)
        if not name_key:
            return None
        scored = []
        for ep in episodes:
            ratio = SequenceMatcher(None, name_key, self._norm(ep.get("name"))).ratio()
            if ratio >= 0.74:
                scored.append((ratio, ep))
        return max(scored, key=lambda item: item[0])[1] if scored else None

    def _find_character(self, sources: List[Dict[str, Any]], source: Optional[Dict[str, Any]], name: Optional[str]):
        name_key = self._norm(name)
        if not name_key:
            return None, None
        search_sources = [source] if source else sources
        search_sources = [item for item in search_sources if item]
        best = None
        for src in search_sources:
            for char in src.get("characters") or []:
                char_key = self._norm(char)
                ratio = SequenceMatcher(None, name_key, char_key).ratio()
                token_match = name_key in char_key or char_key in name_key
                score = max(ratio, 0.9 if token_match else 0.0)
                if score >= 0.78 and (best is None or score > best[0]):
                    best = (score, src, char)
        if not best:
            return None, None
        return best[1], best[2]

    def _normalize_plan(self, raw_plan, units, sources, groups):
        groups_by_id = {str(group.get("id")): group for group in groups if group.get("id")}
        first_source = sources[0] if sources else None
        normalized = []
        raw_by_unit = {}
        if isinstance(raw_plan, list):
            for item in raw_plan:
                if isinstance(item, dict) and item.get("unit_id") is not None:
                    raw_by_unit[int(item.get("unit_id"))] = item

        stamp = int(time.time() * 1000)
        for unit in units:
            unit_id = int(unit["unit_id"])
            item = raw_by_unit.get(unit_id, {})
            clip_type = self._norm(item.get("clip_type")) or "source"
            source = self._find_source(sources, item.get("source_alias")) or first_source
            group = groups_by_id.get(str(item.get("group_id"))) if item.get("group_id") else None
            label = item.get("label") or item.get("character_name") or item.get("episode_id") or (source or {}).get("alias") or "Auto source"
            matcher_mode = item.get("matcher_mode") if item.get("matcher_mode") in {"chaotic", "sequential"} else "chaotic"

            clip = {
                "id": f"auto-{stamp}-{unit_id}",
                "source_alias": source.get("alias") if source else "",
                "episode_id": None,
                "episode_name": str(label),
                "timeline_start": float(unit["start"]),
                "timeline_duration": max(2.0, float(unit["end"]) - float(unit["start"])),
                "clip_type": "episode",
                "character_name": None,
                "matcher_mode": matcher_mode,
                "planner_reason": item.get("reason"),
                "planner_confidence": item.get("confidence"),
            }

            if clip_type == "group" and group:
                clip.update({
                    "source_alias": "group",
                    "episode_id": group.get("id"),
                    "episode_name": group.get("name"),
                    "clip_type": "group",
                    "matcher_mode": "chaotic",
                    "group_items": group.get("items", []),
                    "group_selection_mode": item.get("group_selection_mode") if item.get("group_selection_mode") in {"score", "alternate"} else "score",
                })
            elif clip_type == "character":
                char_source, char_name = self._find_character(sources, source, item.get("character_name") or item.get("label"))
                if char_source and char_name:
                    clip.update({
                        "source_alias": char_source.get("alias"),
                        "episode_name": char_name,
                        "clip_type": "character",
                        "character_name": char_name,
                        "matcher_mode": "chaotic",
                    })
            elif clip_type == "episode" and source:
                episode = self._find_episode(source, item.get("episode_id"), item.get("label"))
                if episode:
                    clip.update({
                        "episode_id": episode.get("id"),
                        "episode_name": episode.get("name"),
                        "clip_type": "episode",
                        "matcher_mode": "sequential" if matcher_mode == "sequential" else "chaotic",
                    })
                else:
                    clip.update({
                        "episode_name": f"Full Source: {source.get('alias')}",
                        "matcher_mode": "chaotic",
                    })
            elif source:
                clip.update({
                    "episode_name": f"Full Source: {source.get('alias')}",
                    "matcher_mode": "chaotic",
                })

            normalized.append(clip)

        return normalized

    def plan(self, script_text: str, transcript: Dict[str, Any], source_aliases: List[str], groups: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        sources = self._load_source_context(source_aliases)
        if not sources:
            raise ValueError("No valid selected sources")

        groups = groups or []
        units = self._make_units(transcript)
        prompt = self._prompt(
            script_text=script_text.strip(),
            units=units,
            sources=sources,
            groups=self._load_group_context(groups),
        )

        response = self.client.generate_content(prompt)
        json_str = self.client.parse_json(response.text)
        raw_plan = json.loads(json_str)
        if isinstance(raw_plan, dict):
            raw_plan = raw_plan.get("items") or raw_plan.get("plan") or raw_plan.get("timeline") or []
        clips = self._normalize_plan(raw_plan, units, sources, groups)
        return {
            "units": units,
            "raw_plan": raw_plan,
            "items": clips,
        }
