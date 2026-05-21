import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.utils.gemini_client import GeminiClient
import google.generativeai as genai

logger = logging.getLogger(__name__)

# Same as episode_segmenter
MIN_SCENE_DURATION = 2.0
MAX_TABLE_ROWS = 500

def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS for human readability in the table."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins >= 60:
        hrs = mins // 60
        mins = mins % 60
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

class ScriptSceneSegmenter:
    """
    Groups visual scene-cuts into precise screenplay scenes based on INT./EXT. headings.
    Unlike EpisodeSegmenter, this guarantees ~300+ scenes (depending on the screenplay)
    mapped consecutively to the visual scene table, using batched Gemini evaluation.
    """
    
    def __init__(self, library_dir: Path):
        self.library_dir = Path(library_dir)
        self.scene_data_path = self.library_dir / "scene_data.json"
        self.master_index_path = self.library_dir / "master_index.json"
        self.screenplay_path = self.library_dir / "screenplay.txt"
        self.episodes_path = self.library_dir / "episodes.json"
        
        self.model = GeminiClient()
        self.delay = 2
        self.max_retries = 5

    def _load_ingest_data(self):
        with open(self.scene_data_path, "r") as f:
            scene_list = json.load(f)
            
        with open(self.master_index_path, "r") as f:
            master = json.load(f)
            
        master_lookup = {s["id"]: s for s in master.get("scenes", [])}
        movie_name = master.get("movie_name", self.library_dir.name)
        
        return scene_list, master_lookup, movie_name

    def _get_movie_name(self) -> str:
        if self.master_index_path.exists():
            with open(self.master_index_path, "r") as f:
                d = json.load(f)
                if "movie_name" in d:
                    return d["movie_name"]
        return self.library_dir.name

    def _load_screenplay(self) -> Optional[str]:
        if not self.screenplay_path.exists():
            return None
        with open(self.screenplay_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
            return text if text else None

    def _parse_screenplay(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract scenes based on numbered INT./EXT. headers.
        """
        # Find all INT. or EXT. lines
        int_ext_matches = list(re.finditer(r'(?:^|\n)((?:[^\n]*?)(?:INT\.|EXT\.)[^\n]*)', text))
        scenes = []
        
        for i, m in enumerate(int_ext_matches):
            header = m.group(1).strip()
            
            # Look backwards for the standalone number
            prefix = text[max(0, m.start() - 50):m.start()]
            num_match = re.search(r'(?:^|\n)(\d+)\s*$', prefix)
            scene_num = int(num_match.group(1)) if num_match else -1
            
            start_idx = m.end()
            
            if i + 1 < len(int_ext_matches):
                # The next scene's text starts where we found its number
                next_prefix = text[max(0, int_ext_matches[i+1].start() - 50):int_ext_matches[i+1].start()]
                next_num_match = re.search(r'(?:^|\n)(\d+)\s*$', next_prefix)
                if next_num_match:
                    end_idx = int_ext_matches[i+1].start() - len(next_prefix) + next_num_match.start()
                else:
                    end_idx = int_ext_matches[i+1].start()
            else:
                end_idx = len(text)
                
            content = text[start_idx:end_idx].strip()
            
            # Clean up the trailing number suffix like "DAWN (WAYNE’S MEMORY)20"
            header = re.sub(r'\d+$', '', header).strip()
            
            scenes.append({
                "scene_num": scene_num,
                "header": header,
                "content": content
            })
            
        return [s for s in scenes if s["scene_num"] != -1]

    def _build_scene_table(self, scene_list, master_lookup):
        # We need a robust representation. Identical to episode_segmenter but we shouldn't 
        # heavily merge them as we want precise boundaries.
        # Let's keep it mostly 1-to-1 but merge < 2.0s scenes as it might be too large.
        enriched = []
        for s in scene_list:
            sid = s["scene_id"]
            m = master_lookup.get(sid, {})
            visual = m.get("visual", {})
            content = m.get("content", {})
            meta = m.get("metadata", {})
            
            # Skip pure intro/credits if we want, but let's keep intro to be safe in script match
            # Actually script might include first scene, let's just filter credits
            if meta.get("is_credits", False):
                continue
                
            dur = s["end_time"] - s["start_time"]
            
            enriched.append({
                "scene_id": sid,
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "duration": dur,
                "shot_type": visual.get("shot_type", "Unknown"),
                "characters": content.get("characters", []),
                "is_intro": meta.get("is_intro", False)
            })
            
        # Merge very short scenes to reduce table size
        merged = []
        for s in enriched:
            if not merged:
                merged.append(dict(s))
                continue
            
            last = merged[-1]
            if last["duration"] < MIN_SCENE_DURATION:
                last["end_time"] = s["end_time"]
                last["duration"] = last["end_time"] - last["start_time"]
                last["characters"] = list(set(last["characters"] + s["characters"]))
                continue
                
            if s["duration"] < MIN_SCENE_DURATION:
                last["end_time"] = s["end_time"]
                last["duration"] = last["end_time"] - last["start_time"]
                last["characters"] = list(set(last["characters"] + s["characters"]))
                continue
                
            merged.append(dict(s))
            
        # Aggregation if still > MAX_TABLE_ROWS? 
        # For batching, we don't need to fit the *entire* movie in one table, 
        # we can provide a slice of the table to Gemini!
        
        return merged

    def _table_to_text(self, scenes) -> str:
        lines = ["scene_id | time | shot/action | characters"]
        lines.append("--- | --- | --- | ---")
        for m in scenes:
            t_str = f"{_format_time(m['start_time'])}-{_format_time(m['end_time'])}"
            c_str = ", ".join(m["characters"]) if m["characters"] else "-"
            lines.append(f"{m['scene_id']} | {t_str} | {m['shot_type']} | {c_str}")
        return "\n".join(lines)

    def _build_batch_prompt(self, movie_name, script_scenes, scene_table_slice, previous_mapping=None):
        
        # Format script scenes
        script_text_parts = []
        for sc in script_scenes:
            script_text_parts.append(f"Scene {sc['scene_num']}: {sc['header']}")
            # Exclude very long content to save tokens, give only first 500 chars 
            # or we can give full if batch is small.
            content = sc['content'][:1500] + ("..." if len(sc['content']) > 1500 else "")
            script_text_parts.append(f"Content:\n{content}\n---")
            
        script_text = "\n".join(script_text_parts)
        
        num_scenes = len(script_scenes)
        
        # Instructions for continuity
        prev_hint = ""
        if previous_mapping:
            last_sc = previous_mapping[-1]
            prev_hint = f"\nCRITICAL: The PREVIOUS batch ended with screenplay scene {last_sc['scene_num']} ending at visual scene_id '{last_sc['last_scene']}'. The very FIRST screenplay scene in this batch MUST logically start immediately AT OR AFTER '{last_sc['last_scene']}'."
        
        prompt = f"""You are analyzing the movie "{movie_name}".

You have a BATCH of SCREENPLAY SCENES and a VISUAL SCENE TABLE slice.

Your task: Determine which visual "scene_id" ranges correspond to each screenplay scene.

RULES:
- Both the screenplay and the scene table are in CHRONOLOGICAL order.
- Every screenplay scene must be mapped to a consecutive range of visual scenes.
- Return EXACT scene_id values that exist in the VISUAL SCENE TABLE.
- Do NOT leave gaps between screenplay scenes if they are continuous (end logic: scene N last_scene is followed by scene N+1 first_scene, or they overlap safely).
- Compare the characters mentioned in the SCREENPLAY CONTENT with the "characters" column in the VISUAL SCENE TABLE to find the exact scene boundaries. When characters match, that confirms the mapping.
{prev_hint}

CRITICAL: You MUST return EXACTLY {num_scenes} JSON objects, one for each of the {num_scenes} screenplay scenes provided. No more, no less.

## SCREENPLAY SCENES (Current Batch):
{script_text}

## VISUAL SCENE TABLE (Slice):
{scene_table_slice}

NAMING: For each scene, provide a short narrative "name" based on CHARACTER ACTIONS from the screenplay content. Describe WHAT the characters DO, not the location.
Examples:
- "Young Bruce falls into the well"
- "Ra's al Ghul trains Bruce in swordfighting"
- "Gordon meets Batman on the rooftop"
- "Joker robs the bank with his crew"

Return ONLY a valid JSON array of objects. Format:
[
  {{"scene_num": 1, "name": "Young Bruce plays with Rachel near the garden", "first_scene": "scene_0000", "last_scene": "scene_0005"}},
  ...
]
"""
        return prompt

    def _ask_gemini_batch(self, prompt: str, attempt=1):
        generation_config = genai.types.GenerationConfig(
            temperature=0.1 + (attempt * 0.05),
            max_output_tokens=65536,
        )

        # GeminiClient handles rate limiting and retries internally
        response = self.model.generate_content(
            prompt,
            generation_config=generation_config,
            request_options={"timeout": 300},
        )
        
        raw_text = response.text
        
        # Parse JSON
        s = raw_text.find('[')
        e = raw_text.rfind(']')
        if s != -1 and e != -1 and e > s:
            json_str = raw_text[s:e+1]
            try:
                return json.loads(json_str)
            except Exception as jse:
                logger.error(f"❌ JSON Parse Error in batch: {jse}")
                logger.debug(f"Raw response: {raw_text}")
                return []
        
        logger.warning(f"⚠️ No JSON brackets found in Gemini response. Preview: {raw_text[:200]}")
        return []

    def _resolve_and_stitch(self, all_results, scene_table, raw_scene_list):
        # We need to map back to timestamps and ensure no gaps.
        # all_results is list of dicts: {"scene_num", "name", "first_scene", "last_scene"}
        
        # Create lookups
        table_lookup = {s["scene_id"]: s for s in scene_table}
        raw_lookup = {s["scene_id"]: s for s in raw_scene_list}
        
        episodes = []
        
        # Make a sorted list of scene IDs from raw list for gap-filling
        ordered_ids = [s["scene_id"] for s in raw_scene_list]
        
        for i, res in enumerate(all_results):
            fs_id = res["first_scene"]
            ls_id = res["last_scene"]
            
            # fallback if Gemini hallucinated IDs
            if fs_id not in raw_lookup:
                # Basic matching or just take last episode's end
                if episodes and i > 0:
                    fs_id = episodes[-1]["last_scene_id_raw"]
                else:
                    fs_id = ordered_ids[0]
                    
            if ls_id not in raw_lookup:
                # Find closest next valid scene in ordered_ids?
                # Just fallback to fs_id
                ls_id = fs_id
                
            # Find indices
            fs_idx = ordered_ids.index(fs_id)
            try:
                ls_idx = ordered_ids.index(ls_id)
            except ValueError:
                ls_idx = fs_idx
                
            if ls_idx < fs_idx:
                ls_idx = fs_idx
            
            # Create synthetic Intro episode if first screenplay scene 
            # doesn't start at the very beginning (logos/intro sequence)
            if i == 0 and fs_idx > 0:
                intro_end_idx = fs_idx - 1
                intro_start_time = raw_lookup[ordered_ids[0]]["start_time"]
                intro_end_time = raw_lookup[ordered_ids[intro_end_idx]]["end_time"]
                episodes.append({
                    "scene_num": 0,
                    "name": "0. Intro",
                    "start_time": intro_start_time,
                    "end_time": intro_end_time,
                    "first_scene_id_raw": ordered_ids[0],
                    "last_scene_id_raw": ordered_ids[intro_end_idx]
                })
                logger.info(
                    f"🎬 Created synthetic Intro episode: "
                    f"{intro_start_time:.1f}s — {intro_end_time:.1f}s "
                    f"({intro_end_idx + 1} intro/logo scenes)"
                )
                
            # If there's a gap between previous episode and this one, stitch it
            if episodes:
                prev_ls_idx = ordered_ids.index(episodes[-1]["last_scene_id_raw"])
                if fs_idx > prev_ls_idx + 1:
                    # Fill the gap by extending the previous episode
                    episodes[-1]["last_scene_id_raw"] = ordered_ids[fs_idx - 1]
                    episodes[-1]["end_time"] = raw_lookup[ordered_ids[fs_idx - 1]]["end_time"]
                elif fs_idx <= prev_ls_idx:
                    # Overlap - force non-overlap
                    fs_idx = prev_ls_idx + 1
                    if fs_idx >= len(ordered_ids):
                        fs_idx = prev_ls_idx # Cap it
                    if ls_idx < fs_idx:
                        ls_idx = fs_idx
                    
            start_time = raw_lookup[ordered_ids[fs_idx]]["start_time"]
            end_time = raw_lookup[ordered_ids[ls_idx]]["end_time"]
            
            # Use narrative name from Gemini (character action), fallback to header
            name = res.get('name', res.get('header', f'Scene {res["scene_num"]}'))
            # Ensure scene_num prefix
            if not name.startswith(str(res['scene_num'])):
                name = f"{res['scene_num']}. {name}"
            elif not name.startswith(f"{res['scene_num']}."):
                name = f"{res['scene_num']}. {name}"
            
            episodes.append({
                "scene_num": res["scene_num"],
                "name": name,
                "start_time": start_time,
                "end_time": end_time,
                "first_scene_id_raw": ordered_ids[fs_idx],
                "last_scene_id_raw": ordered_ids[ls_idx]
            })
            
        # Ensure the last episode covers the end of the movie
        if episodes and episodes[-1]["last_scene_id_raw"] != ordered_ids[-1]:
            last_idx = len(ordered_ids) - 1
            episodes[-1]["last_scene_id_raw"] = ordered_ids[last_idx]
            episodes[-1]["end_time"] = raw_lookup[ordered_ids[last_idx]]["end_time"]

        # Add 'id' fields
        for ep in episodes:
            ep["id"] = f"ep_{int(ep['start_time']*1000)}_{ep['scene_num']}"
            
        return episodes

    def _process_batch_with_validation(self, movie_name, batch_sc, scene_table,
                                        estimated_scenes_per_script_scene,
                                        batch_idx, num_batches, previous_mapping):
        """
        Process a single batch with strict count validation.
        If count doesn't match, retry. If still fails, split the batch in half.
        Returns (results_list, last_mapping).
        """
        expected_count = len(batch_sc)
        
        # Estimate visual scene slice
        start_idx_est = int(batch_idx * 40 * estimated_scenes_per_script_scene)
        end_idx_est = int((batch_idx + 1) * 40 * estimated_scenes_per_script_scene)
        
        start_idx = max(0, start_idx_est - 200)
        end_idx = min(len(scene_table), end_idx_est + 1000)
        
        if previous_mapping:
            prev_last_id = previous_mapping[-1]["last_scene"]
            try:
                prev_last_idx = next(
                    (i for i, s in enumerate(scene_table) if s["scene_id"] == prev_last_id), 0
                )
                start_idx = max(0, prev_last_idx)
            except StopIteration:
                pass
        
        # Last batch gets everything remaining
        if batch_idx == num_batches - 1:
            end_idx = len(scene_table)
        
        table_slice = scene_table[start_idx:end_idx]
        table_text = self._table_to_text(table_slice)
        prompt = self._build_batch_prompt(movie_name, batch_sc, table_text, previous_mapping)
        
        # Try full batch with retries (backoff is handled by GeminiClient)
        try:
            res = self._ask_gemini_batch(prompt, 1)
            if res and len(res) == expected_count:
                logger.info(
                    f"✅ Batch: got {len(res)}/{expected_count} scenes"
                )
                return res, res
            elif res:
                logger.warning(
                    f"⚠️ Batch returned {len(res)}/{expected_count} scenes, retrying..."
                )
            else:
                logger.warning(f"⚠️ Batch empty result")
        except Exception as e:
            logger.warning(f"⚠️ Gemini API Error failed after all retries: {e}")
        
        # Count didn't match after retries — split batch in half and recurse
        if expected_count > 1:
            mid = expected_count // 2
            logger.info(
                f"🔀 Splitting batch of {expected_count} into [{mid}, {expected_count - mid}] "
                f"for better accuracy"
            )
            first_half = batch_sc[:mid]
            second_half = batch_sc[mid:]
            
            res1, mapping1 = self._process_batch_with_validation(
                movie_name, first_half, scene_table,
                estimated_scenes_per_script_scene, batch_idx, num_batches,
                previous_mapping
            )
            res2, mapping2 = self._process_batch_with_validation(
                movie_name, second_half, scene_table,
                estimated_scenes_per_script_scene, batch_idx, num_batches,
                mapping1
            )
            return res1 + res2, mapping2
        
        # Single scene that still failed — use last attempt's result or empty
        logger.error(f"❌ Failed to get valid result for scene {batch_sc[0].get('scene_num')}")
        # Return whatever we got last, even if count is wrong
        if res:
            return res, res
        return [], previous_mapping

    def process(self, progress_callback=None, force=False):
        if self.episodes_path.exists() and not force:
            try:
                with open(self.episodes_path, "r") as f:
                    existing = json.load(f)
                if existing:
                    if progress_callback:
                        progress_callback(100, "Episodes already exist")
                    return existing
            except Exception:
                pass

        if progress_callback: progress_callback(5, "Loading ingest data...")
        scene_list, master_lookup, movie_name = self._load_ingest_data()
        
        if progress_callback: progress_callback(10, "Loading screenplay...")
        screenplay_text = self._load_screenplay()
        if not screenplay_text:
            raise ValueError("No screenplay.txt found for ScriptSceneSegmenter.")
            
        script_scenes = self._parse_screenplay(screenplay_text)
        logger.info(f"📜 Found {len(script_scenes)} numbered scenes in screenplay")
        if not script_scenes:
            raise ValueError("No numbered INT./EXT. scenes found in screenplay.txt")

        scene_table = self._build_scene_table(scene_list, master_lookup)
        
        # Determine batches. E.g. 40 script scenes per batch
        batch_size = 25
        num_batches = (len(script_scenes) + batch_size - 1) // batch_size
        
        all_results = []
        previous_mapping = None
        
        estimated_scenes_per_script_scene = len(scene_table) / len(script_scenes)
        
        for b in range(num_batches):
            if progress_callback: 
                progress_callback(
                    15 + int((b / num_batches) * 70),
                    f"Processing batch {b+1}/{num_batches}..."
                )
                
            batch_sc = script_scenes[b * batch_size : (b + 1) * batch_size]
            if not batch_sc:
                break
            
            batch_results, previous_mapping = self._process_batch_with_validation(
                movie_name, batch_sc, scene_table,
                estimated_scenes_per_script_scene, b, num_batches,
                previous_mapping
            )
            all_results.extend(batch_results)
        
        logger.info(
            f"📊 Total mapped: {len(all_results)}/{len(script_scenes)} screenplay scenes"
        )
        
        if progress_callback: progress_callback(90, "Stitching and validating episodes...")
        
        final_episodes = self._resolve_and_stitch(all_results, scene_table, scene_list)
        
        with open(self.episodes_path, "w") as f:
            clean_episodes = []
            for ep in final_episodes:
                clean_episodes.append({
                    "id": ep["id"],
                    "name": ep["name"],
                    "start_time": ep["start_time"],
                    "end_time": ep["end_time"]
                })
            json.dump(clean_episodes, f, indent=2)
            
        if progress_callback: progress_callback(100, f"Done! {len(final_episodes)} screenplay scenes mapped")
        return clean_episodes

