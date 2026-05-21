
import os
import json
import logging
import time
from src.utils.gemini_client import GeminiClient
from pathlib import Path

logger = logging.getLogger(__name__)

DECISION_PROMPT_TEMPLATE = """You are a master script analyst and psychologist.
Analyzing the film episodes provided below, identify the DECISIONS made by the character "{character}" in relation to their goal: "{goal}".

For each decision, determine:
1. WHAT was the decision? (Action or choice)
2. TYPE: "Global" (Strategy/Long-term) or "Point" (Tactical/Immediate/Reaction)
3. IMPACT: Did it bring them closer (+) or move them further (-) from the goal?
4. REASONING: Brief explanation of why.

EPISODES LIST:
{episodes_json}

INSTRUCTIONS:
- Focus ONLY on significant choices that affect the goal.
- Ignore passive actions.
- "Global" decisions typically change the direction of the story or strategy.
- "Point" decisions are specific actions in a scene (e.g., saving someone, choosing violence).
- Return a valid JSON array of objects.

JSON FORMAT:
[
  {{
    "decision": "Decides to ignore the Riddler's first riddle",
    "type": "Point",
    "impact": "negative",
    "reasoning": "This allowed the Riddler to continue his plan unchecked.",
    "episode_id": "id_of_episode_closest_to_event" (optional, if clear)
  }},
  ...
]
"""

DECISION_PROMPT_SCRIPT = """You are a master screenplay analyst and psychologist.
You have the FULL SCREENPLAY of the film below. Analyze it carefully to identify every significant DECISION made by the character "{character}" in relation to their goal: "{goal}".

Because you have the actual screenplay with dialogue and stage directions, your analysis should be very precise and reference specific scenes, lines or actions from the script.

For each decision, determine:
1. WHAT was the decision? (Action or choice — reference the specific scene/moment)
2. TYPE: "Global" (Strategy/Long-term direction change) or "Point" (Tactical/Immediate/Reaction)
3. IMPACT: "positive" (closer to goal) or "negative" (further from goal)
4. REASONING: Brief explanation referencing the screenplay context.

SCREENPLAY:
{screenplay_text}

INSTRUCTIONS:
- Focus ONLY on significant choices that affect the goal.
- Ignore passive actions where the character has no agency.
- "Global" decisions typically change the direction of the story or strategy.
- "Point" decisions are specific actions in a scene (e.g., saving someone, choosing violence, revealing information).
- Reference specific scenes or dialogue when possible.
- Return a valid JSON array of objects.

JSON FORMAT:
[
  {{
    "decision": "Decides to pursue the Riddler's clue instead of attending the funeral",
    "type": "Point",
    "impact": "positive",
    "reasoning": "Despite social pressure, Batman prioritizes the investigation, which leads to uncovering a key connection.",
    "scene_ref": "INT. BATCAVE - NIGHT (page ~15)"
  }},
  ...
]
"""

class DecisionAnalyzer:
    def __init__(self, library_dir, alias):
        self.library_dir = Path(library_dir)
        self.alias = alias
        self.episodes_path = self.library_dir / alias / "episodes.json"
        self.screenplay_path = self.library_dir / alias / "screenplay.txt"
        
        # New structure: decisions/ folder
        self.decisions_dir = self.library_dir / alias / "decisions"
        self.decisions_dir.mkdir(exist_ok=True)

        # Legacy file path for migration
        self.legacy_path = self.library_dir / alias / "decisions.json"
        self._migrate_legacy()
        
        # Configure Gemini
        self.model = GeminiClient()

    def _migrate_legacy(self):
        """Move old single decisions.json to new folder structure."""
        if self.legacy_path.exists():
            try:
                with open(self.legacy_path, 'r') as f:
                    data = json.load(f)
                
                char_name = data.get("character", "Unknown").replace(" ", "_")
                new_path = self.decisions_dir / f"{char_name}.json"
                
                if not new_path.exists():
                    with open(new_path, 'w') as f:
                        json.dump(data, f, indent=2)
                    logger.info(f"Migrated legacy decision analysis to {new_path}")
                
                # Rename legacy file to avoid re-migration/confusion
                self.legacy_path.rename(self.legacy_path.with_suffix(".json.bak"))
            except Exception as e:
                logger.error(f"Failed to migrate legacy decisions: {e}")

    def get_analysis_list(self):
        """List all available decision analyses."""
        analyses = []
        for f in self.decisions_dir.glob("*.json"):
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    analyses.append({
                        "id": f.stem,
                        "character": data.get("character", f.stem),
                        "goal": data.get("goal", ""),
                        "source": data.get("source", "episodes"),
                        "timestamp": data.get("timestamp", 0),
                        "filename": f.name
                    })
            except Exception as e:
                logger.warning(f"Skipping corrupt analysis file {f}: {e}")
        
        # Sort by newest first
        return sorted(analyses, key=lambda x: x["timestamp"], reverse=True)

    def get_analysis(self, analysis_id):
        """Get a specific analysis by ID (filename stem)."""
        # Security check to prevent directory traversal
        if ".." in analysis_id or "/" in analysis_id:
            raise ValueError("Invalid analysis ID")
            
        path = self.decisions_dir / f"{analysis_id}.json"
        if not path.exists():
            raise FileNotFoundError("Analysis not found")
        
        with open(path, 'r') as f:
            return json.load(f)

    def analyze(self, character, goal, force=False):
        """
        Run the decision analysis using Gemini.
        Priority: screenplay.txt > episodes.json
        Saves to decisions/{character_sanitized}.json
        """
        # Priority 1: Use screenplay if available
        if self.screenplay_path.exists():
            return self._analyze_from_screenplay(character, goal)
        
        # Priority 2: Fallback to episodes
        if self.episodes_path.exists():
            return self._analyze_from_episodes(character, goal)
        
        raise FileNotFoundError(
            f"No screenplay or episodes found for {self.alias}. "
            "Upload a screenplay (.txt) or run auto-episode segmentation first."
        )

    def _analyze_from_screenplay(self, character, goal):
        """Analyze decisions using the uploaded screenplay text."""
        screenplay_text = self.screenplay_path.read_text(encoding="utf-8")
        
        # Truncate if extremely long (>500K chars) to stay within token limits
        if len(screenplay_text) > 500_000:
            logger.warning(f"⚠️ Screenplay very long ({len(screenplay_text)} chars), truncating to 500K")
            screenplay_text = screenplay_text[:500_000] + "\n\n[... TRUNCATED ...]"
        
        prompt = DECISION_PROMPT_SCRIPT.format(
            character=character,
            goal=goal,
            screenplay_text=screenplay_text
        )

        logger.info(f"📜 Analyzing decisions from SCREENPLAY for {character} ({len(screenplay_text)} chars)...")
        return self._run_analysis(character, goal, prompt, source="screenplay")

    def _analyze_from_episodes(self, character, goal):
        """Analyze decisions using episodes.json (legacy/fallback)."""
        with open(self.episodes_path, 'r') as f:
            episodes = json.load(f)

        simplified_episodes = []
        for ep in episodes:
            simplified_episodes.append({
                "id": ep.get("id"),
                "name": ep.get("name"),
                "time": f"{ep.get('start_time')} - {ep.get('end_time')}"
            })
        
        episodes_str = json.dumps(simplified_episodes, indent=2)
        
        prompt = DECISION_PROMPT_TEMPLATE.format(
            character=character,
            goal=goal,
            episodes_json=episodes_str
        )

        logger.info(f"🎬 Analyzing decisions from EPISODES for {character} ({len(episodes)} episodes)...")
        return self._run_analysis(character, goal, prompt, source="episodes")

    def _run_analysis(self, character, goal, prompt, source="episodes"):
        """Common Gemini call + save logic."""
        try:
            response = self.model.generate_content(prompt)
            result = self._parse_response(response.text)
            
            output = {
                "character": character,
                "goal": goal,
                "source": source,
                "timestamp": time.time(),
                "decisions": result
            }
            
            # Sanitize filename
            safe_char = "".join(c for c in character if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
            output_path = self.decisions_dir / f"{safe_char}.json"

            with open(output_path, 'w') as f:
                json.dump(output, f, indent=2)
                
            return output

        except Exception as e:
            logger.error(f"❌ Decision analysis failed: {e}")
            raise

    def base_repair_json(self, json_str):
        """
        Attempt to repair common JSON syntax errors from LLMs. 
        """
        import re
        json_str = re.sub(r'//.*', '', json_str) # comments
        json_str = re.sub(r',\s*([\]\}])', r'\1', json_str) # trailing commas
        json_str = re.sub(r'\}\s*\{', '}, {', json_str) # missing comma between objects
        json_str = re.sub(r'\.\.\.', '', json_str) # ellipsis
        return json_str

    def _parse_response(self, text):
        cleaned = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try repair
            try:
                repaired = self.base_repair_json(cleaned)
                return json.loads(repaired)
            except Exception as e:
                import re
                # Try regex extraction
                match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
                if match:
                    try:
                        return json.loads(self.base_repair_json(match.group(0)))
                    except:
                        pass
                raise ValueError(f"Could not parse Gemini JSON response: {e}")
