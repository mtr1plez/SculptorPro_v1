"""
EpisodeSegmenter — AI-powered semantic episode detection using Gemini + ingest data.

Instead of uploading audio and hoping Gemini guesses timestamps correctly,
this module takes the PRECISE scene-cut data from ingestion (scene_data.json +
master_index.json) and asks Gemini to GROUP consecutive scenes into narrative
episodes as a TEXT-ONLY call.

Result: 100% accurate timestamps (they come from real scene cuts, not LLM guesses),
10-50x faster (text vs. audio upload), and much cheaper.
"""

import os
import re
import time
import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
from google.api_core.exceptions import (
    ResourceExhausted, ServiceUnavailable, InternalServerError, DeadlineExceeded
)
from src.utils.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Minimum scene duration (seconds). Scenes shorter than this are merged with
# their neighbors to keep the table compact and reduce Gemini token usage.
MIN_SCENE_DURATION = 2.0

# Maximum rows in the scene table sent to Gemini.  If we have more rows after
# merging, we further aggregate to stay under this limit.
MAX_TABLE_ROWS = 500

# Narrative episode constraints.  These are deliberately enforced outside the
# model so malformed LLM output cannot create gaps or one-second episodes.
MIN_EPISODE_DURATION = 35.0
TARGET_MIN_EPISODE_DURATION = 90.0
TARGET_MAX_EPISODE_DURATION = 300.0
SOFT_MAX_EPISODE_DURATION = 420.0
HARD_MAX_EPISODE_DURATION = 540.0
BOUNDARY_BATCH_SIZE = 80
SCENE_CARD_BATCH_SIZE = 12
SCENE_CARDS_CACHE_VERSION = 2


@dataclass
class EpisodeRange:
    """Internal contiguous episode span over ordered scene-card indices."""

    start_idx: int
    end_idx: int
    confidence: float = 0.5
    reason: str = ""


def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS for human readability in the table."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class EpisodeSegmenter:
    """
    Groups scene-cut data into narrative episodes using Gemini (text-only).

    Requires completed ingestion: scene_data.json and master_index.json must exist.
    """

    def __init__(self, library_dir, source_video_path=None):
        """
        :param library_dir: Path to the source folder in _library (e.g. _library/Dune/)
        :param source_video_path: Unused (kept for backward compat). Video is not needed.
        """
        self.library_dir = Path(library_dir)
        self.episodes_path = self.library_dir / "episodes.json"
        self.scene_data_path = self.library_dir / "scene_data.json"
        self.scene_data_backup_path = self.library_dir / "scene_data_backup.json"
        self.master_index_path = self.library_dir / "master_index.json"
        self.screenplay_path = self.library_dir / "screenplay.txt"
        self.scene_cards_path = self.library_dir / "scene_cards.json"

        # Screenplay text (loaded lazily in process())
        self.screenplay_text = None

        # Configure Gemini
        self.model = GeminiClient()

    # ── Data Loading ──────────────────────────────────────────────────────

    def _load_ingest_data(self):
        """
        Load scene_data.json and master_index.json.
        Returns (scene_list, master_scenes_by_id).
        """
        if not self.scene_data_path.exists():
            raise FileNotFoundError(
                f"scene_data.json not found at {self.scene_data_path}. "
                "Run ingestion first!"
            )

        with open(self.scene_data_path, "r") as f:
            scene_list = json.load(f)

        # Build a lookup from master_index for characters, shot types, flags
        master_lookup = {}
        if self.master_index_path.exists():
            with open(self.master_index_path, "r") as f:
                master_data = json.load(f)
            for scene in master_data.get("scenes", []):
                master_lookup[scene["id"]] = scene

        return scene_list, master_lookup

    def _load_screenplay(self):
        """
        Load screenplay.txt from library_dir if it exists.
        If only screenplay.pdf exists and a PDF text extractor is installed,
        extract it once to screenplay.txt so future runs are fast/stable.
        Returns the screenplay text or None.
        """
        if not self.screenplay_path.exists():
            pdf_path = self.library_dir / "screenplay.pdf"
            if pdf_path.exists():
                extracted = self._extract_screenplay_pdf(pdf_path)
                if extracted:
                    try:
                        self.screenplay_path.write_text(extracted, encoding="utf-8")
                        logger.info(f"📜 Extracted screenplay.pdf to {self.screenplay_path.name}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not cache extracted screenplay.txt: {e}")
                    return extracted

                logger.warning(
                    "⚠️ screenplay.pdf found, but no usable PDF extractor is installed. "
                    "Convert it to screenplay.txt manually."
                )

            logger.info("📝 No screenplay found — will use scene-only analysis")
            return None

        try:
            text = self.screenplay_path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("⚠️ screenplay.txt is empty — ignoring")
                return None
            logger.info(
                f"📜 Screenplay loaded: {len(text)} chars, "
                f"{text.count(chr(10)) + 1} lines"
            )
            return text
        except Exception as e:
            logger.warning(f"⚠️ Failed to load screenplay: {e}")
            return None

    def _extract_screenplay_pdf(self, pdf_path: Path) -> Optional[str]:
        """Best-effort PDF text extraction without making PDF support mandatory."""
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
            text = text.strip()
            return text if len(text) > 1000 else None
        except Exception:
            pass

        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            text = "\n\n".join(page.get_text() for page in doc)
            text = text.strip()
            return text if len(text) > 1000 else None
        except Exception:
            return None

    def _get_movie_name(self):
        """Try to determine movie name from master_index or directory name."""
        if self.master_index_path.exists():
            try:
                with open(self.master_index_path, "r") as f:
                    data = json.load(f)
                name = data.get("movie_name")
                if name:
                    return name
            except Exception:
                pass
        return self.library_dir.name

    # ── Scene Table Building ──────────────────────────────────────────────

    def _build_scene_table(self, scene_list, master_lookup):
        """
        Build a compact text table of scenes for Gemini.

        Steps:
        1. Enrich each scene with metadata from master_index
        2. Merge very short scenes (< MIN_SCENE_DURATION) with neighbors
        3. Filter out intro/credits scenes
        4. Format as a compact text table

        Returns: (table_text: str, merged_scenes: list[dict])
                 merged_scenes is the list of scene groups with their id ranges.
        """
        # Step 1: Enrich scenes
        enriched = []
        for scene in scene_list:
            sid = scene["scene_id"]
            master = master_lookup.get(sid, {})

            characters = []
            content = master.get("content", {})
            if content.get("characters"):
                characters = content["characters"]

            visual = master.get("visual", {})
            shot_type = visual.get("shot_type", "")

            metadata = master.get("metadata", {})
            is_intro = metadata.get("is_intro", False)
            is_credits = metadata.get("is_credits", False)

            enriched.append({
                "scene_id": sid,
                "start_time": scene["start_time"],
                "end_time": scene["end_time"],
                "duration": scene["end_time"] - scene["start_time"],
                "shot_type": shot_type,
                "characters": characters,
                "is_intro": is_intro,
                "is_credits": is_credits,
            })

        # Step 2: Merge short scenes with neighbors
        merged = self._merge_short_scenes(enriched)

        # Step 3: Filter intro/credits
        # Mark groups where ALL scenes are intro or credits
        filtered = []
        for group in merged:
            if group.get("is_intro") or group.get("is_credits"):
                continue
            filtered.append(group)

        # Step 4: If still too many rows, further aggregate
        if len(filtered) > MAX_TABLE_ROWS:
            filtered = self._aggregate_to_limit(filtered, MAX_TABLE_ROWS)

        # Step 5: Format as text table
        lines = []
        lines.append("scene_id | time | duration | shot_type | characters")
        lines.append("---|---|---|---|---")

        for group in filtered:
            time_str = f"{_format_time(group['start_time'])}-{_format_time(group['end_time'])}"
            dur_str = f"{group['duration']:.1f}s"
            chars_str = ", ".join(group["characters"]) if group["characters"] else "—"
            shot_str = group["shot_type"] or "—"

            lines.append(
                f"{group['scene_id']} | {time_str} | {dur_str} | {shot_str} | {chars_str}"
            )

        table_text = "\n".join(lines)
        logger.info(
            f"📊 Scene table: {len(filtered)} rows "
            f"(from {len(scene_list)} original scenes)"
        )
        return table_text, filtered

    def _merge_short_scenes(self, enriched):
        """
        Merge very short scenes (< MIN_SCENE_DURATION) with the next scene
        to reduce the number of rows.  Returns list of merged scene groups.
        """
        if not enriched:
            return []

        merged = []
        i = 0
        while i < len(enriched):
            current = enriched[i].copy()

            # Accumulate short scenes into the next meaningful scene
            accumulated_chars = set(current["characters"])
            accumulated_shots = [current["shot_type"]] if current["shot_type"] else []
            all_intro = current["is_intro"]
            all_credits = current["is_credits"]
            first_scene_id = current["scene_id"]

            while (
                i + 1 < len(enriched)
                and current["duration"] < MIN_SCENE_DURATION
            ):
                i += 1
                nxt = enriched[i]
                current["end_time"] = nxt["end_time"]
                current["duration"] = current["end_time"] - current["start_time"]
                accumulated_chars.update(nxt["characters"])
                if nxt["shot_type"]:
                    accumulated_shots.append(nxt["shot_type"])
                all_intro = all_intro and nxt["is_intro"]
                all_credits = all_credits and nxt["is_credits"]

            # Use the first scene_id as the group id, store last_scene_id too
            current["scene_id"] = first_scene_id
            current["last_scene_id"] = enriched[i]["scene_id"]
            current["characters"] = sorted(accumulated_chars)
            # Pick most common shot type
            if accumulated_shots:
                from collections import Counter
                current["shot_type"] = Counter(accumulated_shots).most_common(1)[0][0]
            current["is_intro"] = all_intro
            current["is_credits"] = all_credits

            merged.append(current)
            i += 1

        return merged

    def _aggregate_to_limit(self, scenes, limit):
        """If we still have too many rows, group every N scenes together."""
        if len(scenes) <= limit:
            return scenes

        group_size = max(2, len(scenes) // limit + 1)
        aggregated = []

        for i in range(0, len(scenes), group_size):
            chunk = scenes[i:i + group_size]
            group = {
                "scene_id": chunk[0]["scene_id"],
                "last_scene_id": chunk[-1].get("last_scene_id", chunk[-1]["scene_id"]),
                "start_time": chunk[0]["start_time"],
                "end_time": chunk[-1]["end_time"],
                "duration": chunk[-1]["end_time"] - chunk[0]["start_time"],
                "shot_type": chunk[len(chunk) // 2]["shot_type"],
                "characters": sorted(
                    set(c for s in chunk for c in s.get("characters", []))
                ),
                "is_intro": False,
                "is_credits": False,
            }
            aggregated.append(group)

        return aggregated

    # ── Narrative Scene Cards ─────────────────────────────────────────────

    def _load_ordered_scene_data(self) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """
        Load the raw scene-cut grid and the safe/flicker-adjusted scene grid.

        scene_data_backup.json is created by FlickerFixer before shifting starts.
        It is the best source for coverage because it preserves the detector's
        original contiguous cut times.  scene_data.json remains useful for safe
        in-points and keyframes.
        """
        if not self.scene_data_path.exists():
            raise FileNotFoundError(
                f"scene_data.json not found at {self.scene_data_path}. Run ingestion first!"
            )

        with open(self.scene_data_path, "r") as f:
            safe_scenes = json.load(f)

        raw_path = self.scene_data_backup_path if self.scene_data_backup_path.exists() else self.scene_data_path
        with open(raw_path, "r") as f:
            raw_scenes = json.load(f)

        raw_scenes = sorted(raw_scenes, key=lambda s: (float(s.get("start_time", 0)), s.get("scene_id", "")))
        safe_lookup = {s["scene_id"]: s for s in safe_scenes}
        return raw_scenes, safe_lookup

    def _parse_srt_timestamp(self, value: str) -> float:
        match = re.match(r"(\d+):(\d+):(\d+),(\d+)", value.strip())
        if not match:
            return 0.0
        hours, minutes, seconds, millis = [int(part) for part in match.groups()]
        return hours * 3600 + minutes * 60 + seconds + millis / 1000.0

    def _load_subtitles(self) -> List[Dict[str, Any]]:
        """Load the first SRT file in the library folder, if present."""
        srt_files = sorted(self.library_dir.glob("*.srt"))
        if not srt_files:
            return []

        try:
            text = srt_files[0].read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"⚠️ Failed to read subtitles: {e}")
            return []

        subtitles = []
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue
            time_line = lines[1] if re.match(r"^\d+$", lines[0]) and len(lines) > 1 else lines[0]
            if "-->" not in time_line:
                continue
            start_raw, end_raw = [part.strip() for part in time_line.split("-->", 1)]
            body_start = 2 if time_line == lines[1] else 1
            subtitles.append({
                "start": self._parse_srt_timestamp(start_raw),
                "end": self._parse_srt_timestamp(end_raw),
                "text": " ".join(lines[body_start:])[:600],
            })
        return subtitles

    def _subtitle_text_for_range(self, subtitles: List[Dict[str, Any]], start: float, end: float) -> str:
        if not subtitles:
            return ""
        snippets = [
            item["text"]
            for item in subtitles
            if item["end"] >= start and item["start"] <= end
        ]
        return " ".join(snippets)[:900]

    def _build_scene_cards(
        self,
        raw_scenes: List[Dict[str, Any]],
        safe_lookup: Dict[str, Dict[str, Any]],
        master_lookup: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build one card per raw visual cut.  The card keeps raw timings for
        coverage and safe timings/keyframes for visual matching.
        """
        subtitles = self._load_subtitles()
        cards = []

        for idx, raw in enumerate(raw_scenes):
            scene_id = raw["scene_id"]
            safe = safe_lookup.get(scene_id, raw)
            master = master_lookup.get(scene_id, {})
            visual = master.get("visual", {})
            content = master.get("content", {})
            metadata = master.get("metadata", {})

            raw_start = float(raw.get("start_time", 0.0))
            raw_end = float(raw.get("end_time", raw_start))
            safe_start = float(safe.get("start_time", raw_start))
            safe_end = float(safe.get("end_time", raw_end))

            episode_type = "scene"
            if metadata.get("is_intro"):
                episode_type = "intro"
            if metadata.get("is_credits"):
                episode_type = "credits"

            characters = content.get("characters", []) or []
            shot_type = visual.get("shot_type") or "Unknown"
            dialogue = self._subtitle_text_for_range(subtitles, raw_start, raw_end)

            card = {
                "scene_id": scene_id,
                "index": idx,
                "raw_start": raw_start,
                "raw_end": raw_end,
                "safe_start": safe_start,
                "safe_end": safe_end,
                "duration": max(0.0, raw_end - raw_start),
                "shot_type": shot_type,
                "characters": characters,
                "keyframes": safe.get("keyframes", raw.get("keyframes", [])),
                "dialogue": dialogue,
                "episode_type": episode_type,
                "visual_summary": self._fallback_visual_summary(shot_type, characters, dialogue),
                "semantic_confidence": 0.35,
            }
            cards.append(card)

        return cards

    def _fallback_visual_summary(self, shot_type: str, characters: List[str], dialogue: str = "") -> str:
        chars = ", ".join(characters[:4]) if characters else "unknown characters"
        if dialogue:
            return f"{shot_type} with {chars}; dialogue: {dialogue[:160]}"
        return f"{shot_type} with {chars}"

    def _load_or_build_scene_cards(
        self,
        raw_scenes: List[Dict[str, Any]],
        safe_lookup: Dict[str, Dict[str, Any]],
        master_lookup: Dict[str, Dict[str, Any]],
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        expected_ids = [s["scene_id"] for s in raw_scenes]
        if self.scene_cards_path.exists():
            try:
                cached = json.loads(self.scene_cards_path.read_text(encoding="utf-8"))
                cards = cached.get("cards", cached if isinstance(cached, list) else [])
                cache_version = cached.get("version") if isinstance(cached, dict) else None
                if cache_version == SCENE_CARDS_CACHE_VERSION and [c.get("scene_id") for c in cards] == expected_ids:
                    logger.info(f"🧩 Loaded {len(cards)} cached scene cards")
                    return cards
            except Exception as e:
                logger.warning(f"⚠️ Failed to load scene_cards.json: {e}")

        cards = self._build_scene_cards(raw_scenes, safe_lookup, master_lookup)
        self._maybe_enrich_scene_cards_with_gemini(cards, progress_callback=progress_callback)
        self._save_scene_cards(cards)
        return cards

    def _save_scene_cards(self, cards: List[Dict[str, Any]]) -> None:
        payload = {
            "version": SCENE_CARDS_CACHE_VERSION,
            "movie_name": self._get_movie_name(),
            "cards": cards,
        }
        with open(self.scene_cards_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _filter_scene_cards_to_range(
        self,
        cards: List[Dict[str, Any]],
        start_time: Optional[float],
        end_time: Optional[float],
    ) -> Tuple[List[Dict[str, Any]], float, float]:
        if not cards:
            return [], float(start_time or 0.0), float(end_time or 0.0)

        movie_start = float(cards[0].get("raw_start", 0.0))
        movie_end = float(cards[-1].get("raw_end", movie_start))
        content_start = movie_start if start_time is None else max(movie_start, float(start_time))
        content_end = movie_end if end_time is None else min(movie_end, float(end_time))

        if content_end <= content_start:
            raise ValueError(
                f"Invalid auto-segmentation range: {content_start:.2f}s — {content_end:.2f}s"
            )

        filtered = []
        for card in cards:
            raw_start = float(card.get("raw_start", 0.0))
            raw_end = float(card.get("raw_end", raw_start))
            if raw_end <= content_start or raw_start >= content_end:
                continue

            item = dict(card)
            item["raw_start"] = max(raw_start, content_start)
            item["raw_end"] = min(raw_end, content_end)
            item["duration"] = max(0.0, item["raw_end"] - item["raw_start"])
            filtered.append(item)

        if not filtered:
            raise ValueError(
                f"No scenes found inside auto-segmentation range: {content_start:.2f}s — {content_end:.2f}s"
            )

        logger.info(
            f"✂️ Auto-segmentation range: {_format_time(content_start)} — {_format_time(content_end)} "
            f"({len(filtered)}/{len(cards)} scene cards)"
        )
        return filtered, content_start, content_end

    def _append_full_range_episode(
        self,
        episodes: List[Dict[str, Any]],
        start_time: float,
        end_time: float,
    ) -> List[Dict[str, Any]]:
        has_full = any(ep.get("episode_type") == "full_movie" for ep in episodes)
        if has_full:
            return episodes

        episodes.append({
            "id": f"ep_{int(time.time() * 1000)}_full",
            "name": "Full Movie",
            "start_time": float(start_time),
            "end_time": float(end_time),
            "auto_generated": True,
            "episode_type": "full_movie",
            "reason": "Full selected auto-segmentation range",
        })
        return episodes

    def _maybe_enrich_scene_cards_with_gemini(self, cards: List[Dict[str, Any]], progress_callback=None) -> None:
        """
        Add compact visual summaries from Gemini Vision where possible.

        The pipeline remains useful without this step because the deterministic
        solver and boundary repair do not depend on summaries being present.
        """
        if not os.getenv("GOOGLE_API_KEY"):
            logger.info("🔎 GOOGLE_API_KEY missing; using metadata-only scene cards")
            return

        try:
            from PIL import Image
        except Exception as e:
            logger.warning(f"⚠️ PIL unavailable for scene-card enrichment: {e}")
            return

        total_batches = max(1, (len(cards) + SCENE_CARD_BATCH_SIZE - 1) // SCENE_CARD_BATCH_SIZE)
        for batch_idx, start in enumerate(range(0, len(cards), SCENE_CARD_BATCH_SIZE)):
            batch = cards[start:start + SCENE_CARD_BATCH_SIZE]
            if progress_callback and total_batches > 1:
                progress_callback(20, f"Building semantic scene cards {batch_idx + 1}/{total_batches}...")

            parts: List[Any] = [
                "Summarize each movie scene card. Return JSON only.",
                "For every provided scene_id, describe stable setting/location, visible action, and mood.",
                "Keep each summary under 22 words. Do not invent character names.",
                "Schema: [{\"scene_id\":\"scene_0000\",\"visual_summary\":\"...\",\"semantic_confidence\":0.0}]",
            ]

            included_ids = []
            for card in batch:
                parts.append(
                    f"scene_id={card['scene_id']}; time={_format_time(card['raw_start'])}-{_format_time(card['raw_end'])}; "
                    f"shot={card['shot_type']}; characters={', '.join(card['characters']) or '-'}; "
                    f"dialogue={card.get('dialogue') or '-'}"
                )
                # Include up to the three existing keyframes for this scene.
                for rel_path in card.get("keyframes", [])[:3]:
                    img_path = self.library_dir / rel_path
                    if not img_path.exists():
                        continue
                    try:
                        parts.append(Image.open(img_path))
                    except Exception:
                        continue
                included_ids.append(card["scene_id"])

            try:
                generation_config = self._structured_generation_config(self._scene_card_schema())
                response = self.model.generate_content(
                    parts,
                    generation_config=generation_config,
                    request_options={"timeout": 300},
                )
                parsed = self._parse_json_array(response.text)
                by_id = {item.get("scene_id"): item for item in parsed}
                for card in batch:
                    item = by_id.get(card["scene_id"])
                    if not item:
                        continue
                    summary = str(item.get("visual_summary", "")).strip()
                    if summary:
                        card["visual_summary"] = summary[:260]
                        card["semantic_confidence"] = float(item.get("semantic_confidence", 0.65) or 0.65)
            except Exception as e:
                logger.warning(f"⚠️ Scene-card Gemini enrichment skipped for batch {included_ids[:1]}: {e}")

    # ── Structured Gemini Helpers ────────────────────────────────────────

    def _scene_card_schema(self) -> Dict[str, Any]:
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_id": {"type": "string"},
                    "visual_summary": {"type": "string"},
                    "semantic_confidence": {"type": "number"},
                },
                "required": ["scene_id", "visual_summary", "semantic_confidence"],
            },
        }

    def _boundary_schema(self) -> Dict[str, Any]:
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "after_scene": {"type": "string"},
                    "decision": {"type": "string", "enum": ["same_scene", "soft_break", "hard_break"]},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["after_scene", "decision", "reason", "confidence"],
            },
        }

    def _episode_name_schema(self) -> Dict[str, Any]:
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_scene": {"type": "string"},
                    "last_scene": {"type": "string"},
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["first_scene", "last_scene", "name", "confidence"],
            },
        }

    def _structured_generation_config(self, schema: Dict[str, Any]):
        """
        Use Gemini structured output when the installed SDK supports it.
        If a mocked/older SDK rejects schema kwargs, fall back to JSON MIME only.
        """
        try:
            return genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=65536,
                response_mime_type="application/json",
                response_schema=schema,
            )
        except TypeError:
            return genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=65536,
                response_mime_type="application/json",
            )

    def _parse_json_array(self, raw_text: str) -> List[Dict[str, Any]]:
        parsed = self._parse_gemini_response(raw_text)
        return parsed if isinstance(parsed, list) else []

    # ── Boundary Analysis + Solver ───────────────────────────────────────

    def _card_boundary_row(self, card: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "scene_id": card["scene_id"],
            "time": f"{_format_time(card['raw_start'])}-{_format_time(card['raw_end'])}",
            "duration": round(card["duration"], 2),
            "type": card.get("episode_type", "scene"),
            "characters": card.get("characters", []),
            "shot_type": card.get("shot_type", "Unknown"),
            "summary": card.get("visual_summary", ""),
            "dialogue": card.get("dialogue", "")[:240],
        }

    def _screenplay_excerpt_for_cards(
        self,
        cards: List[Dict[str, Any]],
        max_chars: int = 7000,
        padding_chars: int = 2500,
    ) -> str:
        """
        Return a chronological screenplay slice that roughly matches this
        film-time window.  It is intentionally approximate: the scene cards
        still define exact video order, while the screenplay gives Gemini the
        local story events, locations, and dialogue beats.
        """
        if not self.screenplay_text or not cards:
            return ""

        text = self.screenplay_text.strip()
        if not text:
            return ""

        movie_duration = max((card.get("raw_end", 0.0) for card in cards), default=0.0)
        # When called on a small batch, use the global duration estimate from
        # scene cards if available in the last card's metadata is not enough.
        movie_duration = max(movie_duration, getattr(self, "_movie_duration_hint", 0.0))
        if movie_duration <= 0:
            return text[:max_chars]

        start_ratio = max(0.0, min(1.0, cards[0].get("raw_start", 0.0) / movie_duration))
        end_ratio = max(start_ratio, min(1.0, cards[-1].get("raw_end", 0.0) / movie_duration))
        start_char = int(len(text) * start_ratio)
        end_char = int(len(text) * end_ratio)
        start_char = max(0, start_char - padding_chars)
        end_char = min(len(text), end_char + padding_chars)

        excerpt = text[start_char:end_char].strip()
        if len(excerpt) > max_chars:
            center = len(excerpt) // 2
            half = max_chars // 2
            excerpt = excerpt[max(0, center - half):center + half].strip()
        return excerpt

    def _build_boundary_prompt(self, movie_name: str, cards: List[Dict[str, Any]]) -> str:
        rows = [self._card_boundary_row(card) for card in cards]
        screenplay_excerpt = self._screenplay_excerpt_for_cards(cards)
        screenplay_section = ""
        if screenplay_excerpt:
            screenplay_section = f"""
Approximate screenplay excerpt for this time window:
{screenplay_excerpt}

Use the screenplay excerpt to identify concrete story beats, dialogue context, and location changes.
Do not match only by character names; distinguish physical scenes from recorded messages, flashbacks, and later callbacks.
"""

        return f"""You are a film editor analyzing "{movie_name}".

Decide only whether each boundary BETWEEN neighboring scene_ids is part of the same narrative scene,
a possible scene break, or a hard episode break.

Definitions:
- same_scene: angle/reverse angle/coverage inside the same continuous dramatic scene.
- soft_break: possible transition, but the surrounding scenes may still belong to one broader narrative beat.
- hard_break: location, time, character group, goal, or major story activity changes.

Important:
- Do not create cuts for every camera angle.
- Prefer whole narrative scenes such as "Cobb teaches Ariadne how dreams work".
- Return one object for every boundary after each scene except the last card.
- after_scene must equal the scene_id before the boundary.
{screenplay_section}

Scene cards:
{json.dumps(rows, ensure_ascii=False)}
"""

    def _fallback_boundary_decision(
        self,
        left: Dict[str, Any],
        right: Dict[str, Any],
    ) -> Dict[str, Any]:
        left_chars = set(left.get("characters", []))
        right_chars = set(right.get("characters", []))
        shared_chars = left_chars & right_chars
        type_changed = left.get("episode_type") != right.get("episode_type")
        char_group_changed = bool(left_chars and right_chars and not shared_chars)
        scenery_transition = (
            "Scenery" in left.get("shot_type", "")
            or "Landscape" in left.get("shot_type", "")
            or "Scenery" in right.get("shot_type", "")
            or "Landscape" in right.get("shot_type", "")
        )
        dialogue_gap = bool(left.get("dialogue")) != bool(right.get("dialogue"))

        if type_changed:
            decision, confidence, reason = "hard_break", 0.85, "intro/credits/main-content type changes"
        elif char_group_changed and scenery_transition:
            decision, confidence, reason = "hard_break", 0.72, "character group changes around a scenery transition"
        elif char_group_changed:
            decision, confidence, reason = "soft_break", 0.62, "visible character group changes"
        elif scenery_transition and dialogue_gap:
            decision, confidence, reason = "soft_break", 0.58, "possible location or activity transition"
        else:
            decision, confidence, reason = "same_scene", 0.55, "neighboring cards look continuous"

        return {
            "after_scene": left["scene_id"],
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
        }

    def _ask_gemini_for_boundaries(
        self,
        movie_name: str,
        cards: List[Dict[str, Any]],
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        if len(cards) < 2:
            return []

        decisions: List[Dict[str, Any]] = []
        total_batches = max(1, (len(cards) - 1 + BOUNDARY_BATCH_SIZE - 1) // BOUNDARY_BATCH_SIZE)

        for batch_idx, start in enumerate(range(0, len(cards) - 1, BOUNDARY_BATCH_SIZE)):
            # Include one extra card because N cards contain N-1 boundaries.
            batch_cards = cards[start:start + BOUNDARY_BATCH_SIZE + 1]
            if progress_callback:
                progress_callback(55, f"Analyzing narrative boundaries {batch_idx + 1}/{total_batches}...")

            prompt = self._build_boundary_prompt(movie_name, batch_cards)
            try:
                generation_config = self._structured_generation_config(self._boundary_schema())
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    request_options={"timeout": 300},
                )
                parsed = self._parse_json_array(response.text)
            except Exception as e:
                logger.warning(f"⚠️ Gemini boundary batch failed; using heuristic fallback: {e}")
                parsed = []

            expected_after = {card["scene_id"] for card in batch_cards[:-1]}
            by_after = {
                item.get("after_scene"): item
                for item in parsed
                if item.get("after_scene") in expected_after
            }

            for left, right in zip(batch_cards, batch_cards[1:]):
                item = by_after.get(left["scene_id"])
                if not item:
                    item = self._fallback_boundary_decision(left, right)
                decision = item.get("decision")
                if decision not in {"same_scene", "soft_break", "hard_break"}:
                    decision = "same_scene"
                decisions.append({
                    "after_scene": left["scene_id"],
                    "decision": decision,
                    "reason": str(item.get("reason", ""))[:300],
                    "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5) or 0.5))),
                })

        return decisions

    def _solve_episode_ranges(
        self,
        cards: List[Dict[str, Any]],
        boundary_decisions: List[Dict[str, Any]],
    ) -> List[EpisodeRange]:
        if not cards:
            return []

        by_after = {item["after_scene"]: item for item in boundary_decisions}
        ranges: List[EpisodeRange] = []
        start_idx = 0
        last_reason = ""
        last_confidence = 0.5

        for idx in range(0, len(cards) - 1):
            current = cards[idx]
            start_time = cards[start_idx]["raw_start"]
            elapsed = cards[idx]["raw_end"] - start_time
            boundary = by_after.get(current["scene_id"]) or self._fallback_boundary_decision(current, cards[idx + 1])
            decision = boundary.get("decision", "same_scene")
            confidence = float(boundary.get("confidence", 0.5) or 0.5)

            should_cut = False
            if elapsed < MIN_EPISODE_DURATION:
                should_cut = False
            elif decision == "hard_break" and confidence >= 0.55:
                should_cut = True
            elif elapsed >= TARGET_MAX_EPISODE_DURATION and decision == "soft_break" and confidence >= 0.5:
                should_cut = True
            elif decision == "soft_break" and confidence >= 0.65 and elapsed >= TARGET_MIN_EPISODE_DURATION:
                should_cut = True
            elif elapsed >= SOFT_MAX_EPISODE_DURATION and decision != "same_scene":
                should_cut = True
            elif elapsed >= HARD_MAX_EPISODE_DURATION:
                should_cut = True

            if should_cut:
                ranges.append(EpisodeRange(
                    start_idx=start_idx,
                    end_idx=idx,
                    confidence=confidence,
                    reason=str(boundary.get("reason", "")),
                ))
                start_idx = idx + 1
                last_reason = str(boundary.get("reason", ""))
                last_confidence = confidence

        ranges.append(EpisodeRange(
            start_idx=start_idx,
            end_idx=len(cards) - 1,
            confidence=last_confidence,
            reason=last_reason,
        ))
        return self._repair_episode_ranges(ranges, cards)

    def _episode_duration(self, episode_range: EpisodeRange, cards: List[Dict[str, Any]]) -> float:
        return cards[episode_range.end_idx]["raw_end"] - cards[episode_range.start_idx]["raw_start"]

    def _repair_episode_ranges(
        self,
        ranges: List[EpisodeRange],
        cards: List[Dict[str, Any]],
        min_duration: float = MIN_EPISODE_DURATION,
    ) -> List[EpisodeRange]:
        """
        Make ranges a continuous partition and merge short episodes.

        This is the hard guarantee layer: no skipped scene indices, no overlaps,
        and no tiny episodes when more than one episode exists.
        """
        if not cards:
            return []
        if not ranges:
            return [EpisodeRange(0, len(cards) - 1, reason="fallback full coverage")]

        ranges = sorted(ranges, key=lambda r: (r.start_idx, r.end_idx))
        repaired: List[EpisodeRange] = []
        cursor = 0
        for item in ranges:
            start_idx = max(cursor, min(item.start_idx, len(cards) - 1))
            end_idx = max(start_idx, min(item.end_idx, len(cards) - 1))
            repaired.append(EpisodeRange(start_idx, end_idx, item.confidence, item.reason))
            cursor = end_idx + 1
            if cursor >= len(cards):
                break

        if not repaired or repaired[0].start_idx > 0:
            repaired.insert(0, EpisodeRange(0, repaired[0].start_idx - 1 if repaired else len(cards) - 1, reason="filled leading gap"))

        if repaired[-1].end_idx < len(cards) - 1:
            repaired.append(EpisodeRange(repaired[-1].end_idx + 1, len(cards) - 1, reason="filled trailing gap"))

        # Rebuild as a strict partition in case bad input overlapped.
        partitioned: List[EpisodeRange] = []
        start_idx = 0
        for item in repaired:
            end_idx = max(start_idx, item.end_idx)
            partitioned.append(EpisodeRange(start_idx, min(end_idx, len(cards) - 1), item.confidence, item.reason))
            start_idx = partitioned[-1].end_idx + 1
            if start_idx >= len(cards):
                break
        repaired = partitioned

        # Merge too-short episodes with the best neighbor until stable.
        changed = True
        while changed and len(repaired) > 1:
            changed = False
            for idx, item in enumerate(list(repaired)):
                if self._episode_duration(item, cards) >= min_duration:
                    continue

                if idx == 0:
                    repaired[1] = EpisodeRange(
                        item.start_idx,
                        repaired[1].end_idx,
                        min(item.confidence, repaired[1].confidence),
                        f"{item.reason}; merged short episode into next",
                    )
                    del repaired[0]
                elif idx == len(repaired) - 1:
                    repaired[idx - 1] = EpisodeRange(
                        repaired[idx - 1].start_idx,
                        item.end_idx,
                        min(item.confidence, repaired[idx - 1].confidence),
                        f"{repaired[idx - 1].reason}; merged short episode into previous",
                    )
                    del repaired[idx]
                else:
                    prev_duration = self._episode_duration(repaired[idx - 1], cards)
                    next_duration = self._episode_duration(repaired[idx + 1], cards)
                    if prev_duration <= next_duration:
                        repaired[idx - 1] = EpisodeRange(
                            repaired[idx - 1].start_idx,
                            item.end_idx,
                            min(item.confidence, repaired[idx - 1].confidence),
                            f"{repaired[idx - 1].reason}; merged short episode into previous",
                        )
                        del repaired[idx]
                    else:
                        repaired[idx + 1] = EpisodeRange(
                            item.start_idx,
                            repaired[idx + 1].end_idx,
                            min(item.confidence, repaired[idx + 1].confidence),
                            f"{item.reason}; merged short episode into next",
                        )
                        del repaired[idx]
                changed = True
                break

        return repaired

    def _episode_type_for_range(self, episode_range: EpisodeRange, cards: List[Dict[str, Any]]) -> str:
        types = {cards[i].get("episode_type", "scene") for i in range(episode_range.start_idx, episode_range.end_idx + 1)}
        if len(types) == 1:
            return next(iter(types))
        return "scene"

    def _fallback_episode_name(self, index: int, episode_range: EpisodeRange, cards: List[Dict[str, Any]]) -> str:
        subset = cards[episode_range.start_idx:episode_range.end_idx + 1]
        chars = []
        for card in subset:
            for character in card.get("characters", []):
                if character not in chars:
                    chars.append(character)
        char_text = ", ".join(chars[:3]) if chars else "Characters"
        first_summary = subset[0].get("visual_summary", "")
        return f"{index + 1}. {char_text} in {first_summary[:80]}".strip()

    def _ask_gemini_to_name_ranges(
        self,
        movie_name: str,
        ranges: List[EpisodeRange],
        cards: List[Dict[str, Any]],
        progress_callback=None,
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        if not ranges:
            return {}
        if progress_callback:
            progress_callback(82, "Naming narrative episodes...")

        self._movie_duration_hint = cards[-1].get("raw_end", 0.0) if cards else 0.0
        episode_rows = []
        for idx, episode_range in enumerate(ranges):
            subset = cards[episode_range.start_idx:episode_range.end_idx + 1]
            episode_rows.append({
                "episode_number": idx + 1,
                "first_scene": subset[0]["scene_id"],
                "last_scene": subset[-1]["scene_id"],
                "time": f"{_format_time(subset[0]['raw_start'])}-{_format_time(subset[-1]['raw_end'])}",
                "characters": sorted({c for card in subset for c in card.get("characters", [])})[:8],
                "summaries": [card.get("visual_summary", "") for card in subset[:8]],
                "dialogue": " ".join(card.get("dialogue", "") for card in subset[:6])[:600],
                "screenplay_hint": self._screenplay_excerpt_for_cards(subset, max_chars=1200, padding_chars=700),
            })

        prompt = f"""Name these already finalized narrative episodes from "{movie_name}".

Use the format "<number>. <character(s)> <action/event> <context>".
Names must describe the whole scene beat, not a camera angle.
Use screenplay_hint when present to name the actual event, not just visible characters.
Return JSON only.

Episodes:
{json.dumps(episode_rows, ensure_ascii=False)}
"""

        try:
            generation_config = self._structured_generation_config(self._episode_name_schema())
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config,
                request_options={"timeout": 300},
            )
            parsed = self._parse_json_array(response.text)
        except Exception as e:
            logger.warning(f"⚠️ Gemini episode naming failed; using fallback names: {e}")
            parsed = []

        result = {}
        for item in parsed:
            key = (item.get("first_scene"), item.get("last_scene"))
            if key[0] and key[1]:
                result[key] = item
        return result

    def _ranges_to_episodes(
        self,
        ranges: List[EpisodeRange],
        cards: List[Dict[str, Any]],
        movie_name: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        names = self._ask_gemini_to_name_ranges(movie_name, ranges, cards, progress_callback=progress_callback)
        episodes = []

        previous_end = None
        for idx, episode_range in enumerate(ranges):
            first = cards[episode_range.start_idx]
            last = cards[episode_range.end_idx]
            key = (first["scene_id"], last["scene_id"])
            name_item = names.get(key, {})
            name = str(name_item.get("name") or self._fallback_episode_name(idx, episode_range, cards)).strip()
            if not name.startswith(f"{idx + 1}."):
                clean_name = re.sub(r"^\d+\.\s*", "", name)
                name = f"{idx + 1}. {clean_name}"

            start_time = first["raw_start"] if previous_end is None else previous_end
            end_time = last["raw_end"]
            previous_end = end_time

            episodes.append({
                "name": name,
                "start_time": start_time,
                "end_time": end_time,
                "first_scene": first["scene_id"],
                "last_scene": last["scene_id"],
                "confidence": round(float(name_item.get("confidence", episode_range.confidence) or episode_range.confidence), 3),
                "reason": episode_range.reason,
                "episode_type": self._episode_type_for_range(episode_range, cards),
            })

        return episodes

    # ── Gemini Grouping ───────────────────────────────────────────────────

    def _build_prompt(self, movie_name, scene_table):
        """Build the prompt for Gemini to group scenes into episodes (no screenplay)."""
        return f"""You are a professional film analyst. Below is a table of ALL scene cuts from the movie "{movie_name}" with their timecodes, shot types, and visible characters.

Your task: group these consecutive scenes into NARRATIVE EPISODES.

An episode is a continuous segment where the action takes place in the SAME LOCATION/SETTING with the SAME GROUP OF CHARACTERS doing a RELATED ACTIVITY.

A new episode starts when:
- The location/setting fundamentally changes (look for landscape/scenery shots between dialogue scenes)
- The group of characters changes significantly (different names appear)
- There's a clear temporal or narrative jump
- The mood/activity shifts dramatically (dialogue → action, indoor → outdoor)

IMPORTANT RULES:
- Episodes must be CONSECUTIVE: last_scene of episode N must be immediately followed by first_scene of episode N+1
- Episodes must cover ALL scenes without gaps or overlaps
- Do NOT create episodes shorter than 20 seconds (merge with neighbor)
- Do NOT include intro/credits scenes (they are already filtered out)
- Episodes typically range from 30 seconds to 10 minutes

Name each episode as: "{{number}}. {{Character(s)}} {{action/situation}} {{location/context}}"
Examples:
- "1. Paul dreams about Chani and wakes up on Caladan"
- "7. Leto surrounded by Harkonnens bites a tooth and kills everyone in the room"
- "3. Jessica trains Paul to use voice at the table on Caladan"

Return ONLY a valid JSON array. No extra text before or after:
[
  {{"name": "1. ...", "first_scene": "scene_XXXX", "last_scene": "scene_YYYY"}},
  {{"name": "2. ...", "first_scene": "scene_YYYY", "last_scene": "scene_ZZZZ"}},
  ...
]

CRITICAL: first_scene and last_scene must be EXACT scene_id values from the table below.
The first_scene of episode N+1 must be the scene IMMEDIATELY AFTER last_scene of episode N.

Here is the scene table:

{scene_table}"""

    def _build_prompt_with_script(self, movie_name, scene_table, screenplay_text):
        """
        Build a prompt that uses the screenplay as the PRIMARY basis for
        episode segmentation, with the scene table providing exact timecodes.
        """
        # Truncate very long screenplays to stay within token limits (~200k chars ≈ 50k tokens)
        max_script_chars = 200000
        if len(screenplay_text) > max_script_chars:
            screenplay_text = screenplay_text[:max_script_chars] + "\n\n[... SCREENPLAY TRUNCATED ...]"
            logger.warning(
                f"⚠️ Screenplay truncated to {max_script_chars} chars to fit token limit"
            )

        return f"""You are a professional film analyst and screenwriter. You have TWO sources of data for the movie "{movie_name}":

1. **THE SCREENPLAY** — the written script of the film (PRIMARY source for narrative structure)
2. **THE SCENE TABLE** — a table of ALL visual scene cuts with timecodes, shot types, and characters (source of PRECISE timestamps)

Your task: Use the SCREENPLAY to identify the narrative episodes, then MAP each episode to the corresponding scenes in the table to get PRECISE timestamps.

## HOW TO WORK:

1. **Read the screenplay** and identify its logical episodes. An episode is a continuous narrative unit — a conversation, an action sequence, a journey, etc.
2. **For each episode**, find the matching scenes in the scene table by comparing:
   - Characters mentioned in the script vs. characters visible in the scene
   - Actions and setting described in the script vs. shot types and transitions
   - The sequential order (both screenplay and scenes proceed chronologically)
3. **Assign scene IDs** from the table to mark where each episode starts and ends.

## NAMING RULES:
Name each episode based on what happens in the SCREENPLAY, in the format:
"{{number}}. {{Character(s)}} {{action/situation}} {{location/context}}"

Examples:
- "1. Paul dreams about Chani and wakes up on Caladan"
- "7. Leto surrounded by Harkonnens bites a tooth and kills everyone in the room"
- "3. Jessica trains Paul to use voice at the table on Caladan"

## CRITICAL RULES:
- Episodes must be CONSECUTIVE: last_scene of episode N must be immediately followed by first_scene of episode N+1
- Episodes must cover ALL scenes in the table without gaps or overlaps
- Do NOT create episodes shorter than 20 seconds (merge with neighbor)
- Episodes typically range from 30 seconds to 10 minutes
- The screenplay is your MAIN reference for WHAT happens; the scene table is your reference for WHEN it happens
- If the screenplay mentions something not clearly visible in the scene table, use your best judgment to map it

Return ONLY a valid JSON array. No extra text before or after:
[
  {{"name": "1. ...", "first_scene": "scene_XXXX", "last_scene": "scene_YYYY"}},
  {{"name": "2. ...", "first_scene": "scene_YYYY", "last_scene": "scene_ZZZZ"}},
  ...
]

CRITICAL: first_scene and last_scene must be EXACT scene_id values from the SCENE TABLE below.

---

## SCREENPLAY:

{screenplay_text}

---

## SCENE TABLE:

{scene_table}"""

    def _ask_gemini_to_group(self, movie_name, scene_table, progress_callback=None):
        """
        Send the scene table (and optionally screenplay) to Gemini and get back episode groupings.
        Returns list of dicts with name, first_scene, last_scene.
        """
        if self.screenplay_text:
            prompt = self._build_prompt_with_script(movie_name, scene_table, self.screenplay_text)
            logger.info("📜 Using SCREENPLAY-based prompt for episode segmentation")
        else:
            prompt = self._build_prompt(movie_name, scene_table)
            logger.info("🎬 Using SCENE-ONLY prompt for episode segmentation")

        logger.info(
            f"🧠 Sending scene table to Gemini "
            f"(~{len(prompt)} chars, ~{len(prompt) // 4} tokens)..."
        )

        if progress_callback:
            progress_callback(40, "Gemini grouping scenes...")

        generation_config = genai.types.GenerationConfig(
            temperature=0.2,
            max_output_tokens=65536,
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config,
                request_options={"timeout": 300},
            )

            raw_text = response.text
            episodes = self._parse_gemini_response(raw_text)

            if not episodes:
                raise ValueError("Parsed Gemini response resulted in empty episodes.")

            logger.info(f"✅ Gemini grouped scenes into {len(episodes)} episodes")
            return episodes
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            raise RuntimeError("❌ Gemini grouping failed.") from e

    def _parse_gemini_response(self, raw_text):
        """Parse the JSON response from Gemini. Robust against LLM formatting issues."""
        # 1. Try standard cleaning
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 2. Try repair first (handles trailing commas, etc.) then parse
        repaired = self._repair_json(cleaned)
        try:
            result = json.loads(repaired)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 3. Try regex extraction of list pattern
        match = re.search(r'\[\s*\{.*\}\s*,?\s*\]', raw_text, re.DOTALL)
        if match:
            json_content = match.group(0)
            repaired = self._repair_json(json_content)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as e:
                raise ValueError(f"Gemini returned invalid JSON: {e}")

        raise ValueError("Gemini returned no valid JSON array.")

    def _repair_json(self, json_str):
        """Attempt to repair common JSON syntax errors from LLMs."""
        # Remove comments
        json_str = re.sub(r'//.*', '', json_str)
        # Fix trailing commas
        json_str = re.sub(r',\s*([\]\}])', r'\1', json_str)
        # Fix missing commas between objects
        json_str = re.sub(r'\}\s*\{', '}, {', json_str)
        # Remove ellipsis
        json_str = re.sub(r'\.\.\.', '', json_str)
        return json_str

    # ── Scene ID → Timecode Resolution ────────────────────────────────────

    def _resolve_scene_ids_to_times(self, episodes, scene_list):
        """
        Convert first_scene/last_scene IDs to precise start_time/end_time
        from scene_data.json.

        Returns list of episodes with start_time and end_time.
        """
        # Build scene lookup
        scene_lookup = {s["scene_id"]: s for s in scene_list}

        # Also build ordered list of scene_ids for gap-filling
        ordered_ids = [s["scene_id"] for s in scene_list]

        resolved = []
        for ep in episodes:
            first_id = ep.get("first_scene", "")
            last_id = ep.get("last_scene", "")
            name = ep.get("name", "Unnamed Episode")

            first_scene = scene_lookup.get(first_id)
            last_scene = scene_lookup.get(last_id)

            if not first_scene:
                # Try to find closest match
                first_scene = self._find_closest_scene(first_id, scene_lookup, ordered_ids)
                if first_scene:
                    logger.warning(
                        f"⚠️ first_scene '{first_id}' not found, "
                        f"using closest: '{first_scene['scene_id']}'"
                    )

            if not last_scene:
                last_scene = self._find_closest_scene(last_id, scene_lookup, ordered_ids)
                if last_scene:
                    logger.warning(
                        f"⚠️ last_scene '{last_id}' not found, "
                        f"using closest: '{last_scene['scene_id']}'"
                    )

            if not first_scene or not last_scene:
                logger.warning(
                    f"⚠️ Skipping episode '{name}': "
                    f"scene IDs not found ({first_id}, {last_id})"
                )
                continue

            resolved.append({
                "name": name,
                "start_time": first_scene["start_time"],
                "end_time": last_scene["end_time"],
                "first_scene": first_scene["scene_id"],
                "last_scene": last_scene["scene_id"],
            })

        return resolved

    def _find_closest_scene(self, scene_id, scene_lookup, ordered_ids):
        """
        If Gemini returned a scene_id that doesn't exist (e.g. due to merging),
        find the closest match by numeric ID.
        """
        # Extract number from scene_id like "scene_0123"
        match = re.match(r'scene_(\d+)', scene_id)
        if not match:
            return None

        target_num = int(match.group(1))

        # Search nearby IDs
        for offset in range(0, 20):
            for delta in [offset, -offset]:
                candidate = f"scene_{target_num + delta:04d}"
                if candidate in scene_lookup:
                    return scene_lookup[candidate]

        return None

    # ── Validation ────────────────────────────────────────────────────────

    def _validate_episodes(self, episodes):
        """Validate and fix episode data."""
        validated = []
        for i, ep in enumerate(episodes):
            if not isinstance(ep, dict):
                continue

            name = ep.get("name", f"{i + 1}. Unnamed Episode")
            start = float(ep.get("start_time", 0))
            end = float(ep.get("end_time", 0))

            if end <= start:
                logger.warning(f"⚠️ Skipping invalid episode: {name} (end <= start)")
                continue

            item = {
                "name": name,
                "start_time": start,
                "end_time": end,
            }
            for optional_key in ("first_scene", "last_scene", "confidence", "reason", "episode_type"):
                if optional_key in ep:
                    item[optional_key] = ep[optional_key]
            validated.append(item)

        # Sort by start time
        validated.sort(key=lambda x: x["start_time"])
        return validated

    def _add_ids(self, episodes):
        """Add unique IDs to episodes (matching existing format)."""
        result = []
        for ep in episodes:
            ep_with_id = {
                "id": f"ep_{int(time.time() * 1000)}_{len(result)}",
                "name": ep["name"],
                "start_time": ep["start_time"],
                "end_time": ep["end_time"],
                "auto_generated": True,
            }
            for optional_key in ("first_scene", "last_scene", "confidence", "reason", "episode_type"):
                if optional_key in ep:
                    ep_with_id[optional_key] = ep[optional_key]
            result.append(ep_with_id)
            time.sleep(0.001)  # Ensure unique timestamps
        return result

    # ── Main Entry Point ──────────────────────────────────────────────────

    def process(self, progress_callback=None, force=False, start_time=None, end_time=None):
        """
        Main entry point. Loads ingest data, sends scene table to Gemini,
        resolves scene IDs to precise timestamps, saves episodes.json.
        """
        # Check existing episodes
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

        try:
            # Step 0: Load screenplay if available
            self.screenplay_text = self._load_screenplay()

            # Step 1: Load ingest data and raw/safe scene grids
            if progress_callback:
                status_text = "Loading scene data + screenplay..." if self.screenplay_text else "Loading scene data..."
                progress_callback(5, status_text)

            scene_list, master_lookup = self._load_ingest_data()
            raw_scenes, safe_lookup = self._load_ordered_scene_data()
            movie_name = self._get_movie_name()

            logger.info(
                f"📦 Loaded {len(raw_scenes)} raw scenes and {len(scene_list)} safe scenes for '{movie_name}'"
            )

            # Step 2: Build one semantic card per raw scene cut.
            if progress_callback:
                progress_callback(15, "Building semantic scene cards...")

            scene_cards = self._load_or_build_scene_cards(
                raw_scenes,
                safe_lookup,
                master_lookup,
                progress_callback=progress_callback,
            )
            scene_cards, content_start, content_end = self._filter_scene_cards_to_range(
                scene_cards,
                start_time,
                end_time,
            )
            self._movie_duration_hint = max(content_end, scene_cards[-1].get("raw_end", 0.0)) if scene_cards else 0.0

            # Step 3: Ask Gemini to classify only adjacent boundaries.
            if progress_callback:
                progress_callback(45, "Classifying narrative boundaries...")

            boundary_decisions = self._ask_gemini_for_boundaries(
                movie_name,
                scene_cards,
                progress_callback=progress_callback,
            )

            # Step 4: Deterministically solve a continuous partition.
            if progress_callback:
                progress_callback(75, "Solving continuous episode coverage...")

            episode_ranges = self._solve_episode_ranges(scene_cards, boundary_decisions)
            resolved = self._ranges_to_episodes(
                episode_ranges,
                scene_cards,
                movie_name,
                progress_callback=progress_callback,
            )

            # Step 5: Validate fields and preserve optional metadata.
            if progress_callback:
                progress_callback(90, "Validating episodes...")

            validated = self._validate_episodes(resolved)
            final_episodes = self._add_ids(validated)
            final_episodes = self._append_full_range_episode(
                final_episodes,
                content_start,
                content_end,
            )

            # Step 6: Save
            with open(self.episodes_path, "w") as f:
                json.dump(final_episodes, f, indent=2)

            if progress_callback:
                progress_callback(100, f"Done! {len(final_episodes)} episodes generated")

            # Log summary
            if final_episodes:
                total_start = final_episodes[0]["start_time"]
                total_end = final_episodes[-1]["end_time"]
                logger.info(
                    f"📊 Episodes: {len(final_episodes)}, "
                    f"Range: {total_start:.1f}s — {total_end:.1f}s "
                    f"({total_end / 60:.1f}m)"
                )

            return final_episodes

        except Exception as e:
            logger.error(f"❌ Process failed: {e}")
            if progress_callback:
                progress_callback(0, f"Error: {e}")
            raise


# Public compatibility: existing callers import EpisodeSegmenter, while new
# code/documentation can refer to the implementation by its explicit role.
NarrativeEpisodeSegmenter = EpisodeSegmenter
