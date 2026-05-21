"""
Plot Extractor - использует Gemini для анализа скрипта и определения
какой части фильма соответствует каждый блок текста.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.utils.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class PlotExtractor:
    """Извлекает сюжетные сегменты из скрипта с помощью Gemini."""
    
    def __init__(self, movie_name: str, movie_duration_seconds: Optional[float] = None):
        """
        Args:
            movie_name: Название фильма для контекста Gemini
            movie_duration_seconds: Длительность фильма в секундах (если известна)
        """
        self.movie_name = movie_name
        self.movie_duration = movie_duration_seconds or 7200  # По умолчанию 2 часа
        
        try:
            self.client = GeminiClient()
            self.ready = True
        except Exception as e:
            logger.error(f"❌ PlotExtractor failed to init Gemini: {e}")
            self.ready = False
    
    def extract(self, script_blocks: List[Dict[str, Any]], 
                available_characters: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Анализирует блоки скрипта и определяет их привязку к сюжету фильма.
        
        Args:
            script_blocks: Список блоков из ScriptParser
            available_characters: Известные персонажи фильма (для подсказки Gemini)
            
        Returns:
            Список plot_segments:
            [
                {
                    "block_id": 0,
                    "script_text": "Оригинальный текст блока",
                    "plot_point": "Introduction of Paul Atreides",
                    "film_time_range": {"start": 90, "end": 300},
                    "characters_mentioned": ["Paul Atreides"],
                    "scene_description": "Paul wakes up from a prophetic dream"
                },
                ...
            ]
        """
        if not self.ready:
            logger.warning("⚠️ PlotExtractor not ready, returning basic segments")
            return self._fallback_segments(script_blocks)
        
        # Обогащаем параграфы контекстом заголовков
        enriched_blocks = []
        current_section = "Intro"
        
        for block in script_blocks:
            if block["type"] == "heading":
                current_section = block["text"]
            elif block["type"] == "paragraph":
                # Создаем копию блока с добавленным контекстом
                block_copy = block.copy()
                block_copy["section_context"] = current_section
                enriched_blocks.append(block_copy)

        if not enriched_blocks:
            logger.warning("⚠️ No paragraphs found in script")
            return []
        
        logger.info(f"🎬 Extracting plot segments for {len(enriched_blocks)} blocks...")
        
        # Обрабатываем батчами
        batch_size = 10
        all_segments = []
        
        for i in range(0, len(enriched_blocks), batch_size):
            batch = enriched_blocks[i:i + batch_size]
            batch_segments = self._process_batch(batch, available_characters)
            all_segments.extend(batch_segments)
        
        logger.info(f"✅ Extracted {len(all_segments)} plot segments")
        return all_segments
    
    def _process_batch(self, blocks: List[Dict[str, Any]], 
                       characters: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Обрабатывает батч блоков через Gemini."""
        
        chars_str = ", ".join(characters) if characters else "unknown characters"
        duration_mins = int(self.movie_duration / 60)
        
        prompt = f"""
You are an expert film analyst specializing in scene-to-analysis mapping. 
Your task: analyze a video essay script about "{self.movie_name}" and map each paragraph to SPECIFIC VISUAL SCENES from the movie.

**CRITICAL UNDERSTANDING:**
The script discusses CHARACTER DECISIONS and plot analysis — NOT direct scene descriptions.
You MUST translate abstract analysis into the CONCRETE VISUAL SCENE where this moment is shown in the film.
Use 'section_context' to understand which plot point constitutes the analysis.

**Examples of translation:**
- "Leto's decision to accept Arrakis was a trap" → Scene: Imperial Herald arrives at Caladan, delivers the Emperor's decree to Duke Leto
- "Paul's choice to join the Fremen" → Scene: Paul and Jessica in the desert, Stilgar's sietch, first meeting
- "The Emperor's plan to destroy House Atreides" → Scene: Shaddam IV with the Baron discussing the conspiracy

**Movie Info:**
- Title: {self.movie_name}
- Duration: ~{duration_mins} minutes
- Known characters: {chars_str}

**Script blocks to analyze:**
{json.dumps(blocks, indent=2, ensure_ascii=False)}

**RULES:**
1. Find the VISUAL SCENE in the movie that corresponds to the analysis
2. If discussing a decision/choice, find the scene where that decision is SHOWN or ANNOUNCED
3. Scene description must be VISUAL (what we SEE on screen), not analytical
4. Time ranges should be specific and realistic for the movie's pacing
5. Skip intro (0-90s) and credits (last 180s)

**Output format — ONLY valid JSON array:**
[
  {{
    "block_id": <same as input>,
    "plot_point": "Brief name: e.g. 'Herald delivers Emperor's decree'",
    "film_time_range": {{"start": <seconds>, "end": <seconds>}},
    "characters_mentioned": ["Duke Leto", "Imperial Herald"],
    "scene_description": "VISUAL description: e.g. 'Duke Leto in throne room, receiving the Herald, stern expression'"
  }}
]
"""
        
        try:
            response = self.client.generate_content(prompt)
            json_str = self.client.parse_json(response.text)
            segments = json.loads(json_str)
            
            # Валидация и добавление оригинального текста
            result = []
            for seg in segments:
                # Находим соответствующий блок
                matching_block = next(
                    (b for b in blocks if b["block_id"] == seg.get("block_id")), 
                    None
                )
                
                if matching_block:
                    seg["script_text"] = matching_block["text"]
                    seg["word_count"] = matching_block["word_count"]
                    
                    # Валидация time_range
                    if "film_time_range" not in seg:
                        seg["film_time_range"] = {"start": 100, "end": self.movie_duration - 200}
                    
                    result.append(seg)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Gemini error in plot extraction: {e}")
            return self._fallback_segments(blocks)
    
    def _fallback_segments(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fallback если Gemini недоступен - равномерное распределение по фильму."""
        segments = []
        content_blocks = [b for b in blocks if b["type"] == "paragraph"]
        
        if not content_blocks:
            return []
        
        # Пропускаем первые 90 сек и последние 180 сек
        usable_start = 90
        usable_end = self.movie_duration - 180
        usable_duration = usable_end - usable_start
        
        segment_duration = usable_duration / len(content_blocks)
        
        for i, block in enumerate(content_blocks):
            start = usable_start + (i * segment_duration)
            end = start + segment_duration
            
            segments.append({
                "block_id": block["block_id"],
                "script_text": block["text"],
                "word_count": block["word_count"],
                "plot_point": f"Segment {i+1}",
                "film_time_range": {"start": int(start), "end": int(end)},
                "characters_mentioned": [],
                "scene_description": block["text"][:100] + "..."
            })
        
        return segments
    
    def save(self, segments: List[Dict[str, Any]], output_path: Path) -> None:
        """Сохраняет plot segments в JSON."""
        output_path = Path(output_path)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "movie_name": self.movie_name,
                "movie_duration": self.movie_duration,
                "segments": segments
            }, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Plot segments saved to: {output_path}")
