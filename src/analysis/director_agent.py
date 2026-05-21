import json
import logging
from pathlib import Path
from src.utils.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class DirectorAgent:
    def __init__(self, library_path, model_name=None):
        self.library_path = Path(library_path)
        # Инициализируем нашего клиента с Retry-логикой
        try:
            if model_name:
                self.client = GeminiClient(model_name)
            else:
                self.client = GeminiClient()
            self.ready = True
        except Exception as e:
            logger.error(f"❌ Director Agent failed to init Gemini: {e}")
            self.ready = False


    def get_available_characters(self, source_movies):
        """
        Собирает список всех доступных персонажей из указанных фильмов.
        """
        all_chars = set()
        for movie in source_movies:
            map_path = self.library_path / movie / "character_map.json"
            if map_path.exists():
                with open(map_path, 'r') as f:
                    data = json.load(f)
                    # data = {"person_0": "Mikael", ...}
                    names = [n for n in data.values() if n != "Unknown"]
                    all_chars.update(names)
        
        return list(all_chars)

    def process(self, transcript_path, output_path, sources):
        if not self.ready:
            return

        transcript_path = Path(transcript_path)
        with open(transcript_path, 'r') as f:
            data = json.load(f)
            
        # Handle new format (dict with 'duration' and 'batches') vs old format (list of batches)
        if isinstance(data, dict) and "batches" in data:
            batches = data["batches"]
        else:
            batches = data

        # 1. Сначала мержим слишком короткие сегменты (Flicker Prevention Level 1)
        # Если фраза длится меньше 1.5 сек, она склеивается с соседом.
        
        merged_batches = []
        MIN_DURATION = 1.5 
        
        for batch in batches:
            new_segments = []
            buffer_seg = None
            
            for seg in batch['segments']:
                dur = seg['end'] - seg['start']
                if buffer_seg:
                    # Merge into buffer
                    buffer_seg['end'] = seg['end']
                    buffer_seg['text'] += " " + seg['text']
                    dur = buffer_seg['end'] - buffer_seg['start']
                    if dur >= MIN_DURATION:
                        buffer_seg['duration'] = buffer_seg['end'] - buffer_seg['start']
                        new_segments.append(buffer_seg)
                        buffer_seg = None
                else:
                    if dur < MIN_DURATION:
                        buffer_seg = seg
                    else:
                        new_segments.append(seg)
            
            if buffer_seg:  # Flush remainder - merge into last segment to avoid orphan
                if new_segments:
                    # Merge remaining buffer into the last segment
                    new_segments[-1]['end'] = buffer_seg['end']
                    new_segments[-1]['text'] += " " + buffer_seg['text']
                    new_segments[-1]['duration'] = new_segments[-1]['end'] - new_segments[-1]['start']
                else:
                    # No segments yet, just add the buffer
                    buffer_seg['duration'] = buffer_seg['end'] - buffer_seg['start']
                    new_segments.append(buffer_seg)
            
            if new_segments:
                batch['segments'] = new_segments
                merged_batches.append(batch)
                
        if not merged_batches: merged_batches = batches

        # 2. Узнаем, кто у нас есть в касте (для промпта)
        available_chars = self.get_available_characters(sources)
        logger.info(f"🎭 Director knows these actors: {available_chars}")

        visual_script = []
        
        logger.info(f"🎬 Director is visualizing {len(merged_batches)} batches (merged for flickers)...")

        prev_text_context = ""

        for batch in merged_batches:
            batch_id = batch['batch_id']
            segments = batch['segments']
            context_text = batch['context_text']
            
            prompt = f"""
            Role: Expert Film Editor & Director.
            Task: Translate the provided script text into CONCRETE visual scene descriptions for a video essay.
            
            Movie Context: The footage is from movies containing these characters: {available_chars}.
            
            PREVIOUS CONTEXT (What happened just before):
            "{prev_text_context}"
            
            CURRENT INPUT TEXT BLOCK:
            "{context_text}"
            
            Segments to visualize (Strictly correspond to this block):
            {json.dumps(segments, indent=2)}
            
            CRITICAL INSTRUCTION - CONTEXT AWARENESS:
            - **Pronouns (He/She/They)**: Always resolve pronouns based on the PREVIOUS CONTEXT or earlier sentences in the current block.
            - If the previous block mentioned "Perfidia", and the current block starts with "She", IT IS PERFIDIA. Do NOT switch to a new random character like "Willa".
            - Maintain character continuity.
            
            CRITICAL INSTRUCTION - HANDLING ABSTRACT TEXT:
            The text often contains abstract thoughts, metaphors, or political analysis.
            You CANNOT film a "metaphor". You must film a SCENE.
            
            If the text is abstract:
            1. **Infer the underlying emotion**: (e.g., "He realized it was a trap" -> "Close-up of Duke Leto looking worried/suspicious").
            2. **Show the subject**: If talking about "The Empire", show "Spaceships" or "The Emperor". If "Arrakis", show "Desert landscapes".
            3. **Show the consequence**: "No time to pay off" -> "Characters rushing" or "Battle preparation".
            
            General Instructions:
            1. **Visual Query**: Describe the VISUAL content for CLIP search. Be literal. (Good: "Paul Atreides walking in desert", Bad: "The concept of loneliness").
            2. **Shot Type**: VARY THEM! [Close-Up, Medium Shot, Wide Angle, Extreme Close-Up].
            3. **Character**: Choose a character from the list provided IF relevant. If text is general, set to null (B-Roll).
            4. **Mood**: One word (e.g., Tense, Calm, Dark, Happy).
            
            Output Format: Return ONLY a JSON list of objects matching the segments count.
            Example:
            [
              {{
                "segment_id": 0,
                "visual_query": "Duke Leto looking suspicious in dark room",
                "shot_type": "Close-Up",
                "character": "Duke Leto",
                "mood": "Tense"
              }}
            ]
            """

            try:
                response = self.client.generate_content(prompt)
                json_str = self.client.parse_json(response.text)
                shot_list = json.loads(json_str)
                
                # Валидация: проверим, что кол-во шотов совпадает с кол-вом сегментов
                # Важно: мы использовали merged segments, так что сопоставляем с ними
                for i, shot in enumerate(shot_list):
                    if i < len(segments):
                        merged = segments[i].copy()
                        merged.update(shot)
                        visual_script.append(merged)
                
                # Handle remaining segments not covered by Gemini response
                for i in range(len(shot_list), len(segments)):
                    seg = segments[i].copy()
                    seg["visual_query"] = "cinematic movie scene"
                    seg["shot_type"] = "Medium Shot"
                    seg["character"] = None
                    seg["mood"] = "Neutral"
                    visual_script.append(seg)
                    logger.warning(f"⚠️ Segment {seg.get('segment_id', i)} missing from Gemini response, using fallback.")
                
                logger.info(f"✅ Batch {batch_id} visualized.")

            except Exception as e:
                logger.error(f"❌ Error directing batch {batch_id}: {e}")
                for seg in segments:
                    seg["visual_query"] = "cinematic movie scene"
                    seg["shot_type"] = "Medium Shot"
                    visual_script.append(seg)
            
            # Save context for next iteration
            prev_text_context = context_text

        # 3. Сохраняем результат
        with open(output_path, 'w') as f:
            json.dump(visual_script, f, indent=2)
            
        logger.info(f"📜 Visual Script saved to {output_path}")