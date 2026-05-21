import whisper
import torch
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, model_size="medium"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if torch.backends.mps.is_available():
             self.device = "cpu" 
        
        logger.info(f"👂 Loading Whisper model ('{model_size}') on {self.device}...")
        self.model = whisper.load_model(model_size, device=self.device)

    def transcribe(self, audio_path):
        logger.info(f"🎙 Transcribing {audio_path} (word-level)...")
        result = self.model.transcribe(str(audio_path), fp16=False, task="transcribe", word_timestamps=True)
        return result['segments']

    def syntax_segmentation(self, raw_segments):
        """
        Режет по знакам препинания (.,!?:;-), но не чаще чем раз в 3 слова.
        Гарантирует GAPLESS (отсутствие дыр).
        """
        logger.info("🔧 Segmenting by Punctuation + Gapless Flow...")
        
        all_words = []
        for seg in raw_segments:
            if 'words' in seg:
                all_words.extend(seg['words'])
        
        if not all_words: return []

        new_segments = []
        current_words = []
        
        # Ищем любые знаки препинания
        punct_pattern = re.compile(r"[.,!?;:-]$")
        
        segment_start = 0.0
        
        for i, word_data in enumerate(all_words):
            current_words.append(word_data)
            word_text = word_data['word'].strip()
            
            has_punct = bool(punct_pattern.search(word_text))
            enough_words = len(current_words) >= 3
            is_last_global = (i == len(all_words) - 1)

            if (has_punct and enough_words) or is_last_global:
                
                # Gapless логика
                if is_last_global:
                    segment_end = word_data['end']
                else:
                    segment_end = all_words[i+1]['start']

                text = "".join([w['word'] for w in current_words]).strip()
                
                new_segments.append({
                    "start": segment_start,
                    "end": segment_end,
                    "duration": segment_end - segment_start,
                    "text": text
                })
                
                segment_start = segment_end
                current_words = []

        # Хвост (на случай сбоя логики)
        if current_words:
            text = "".join([w['word'] for w in current_words]).strip()
            new_segments.append({
                "start": segment_start,
                "end": current_words[-1]['end'],
                "duration": current_words[-1]['end'] - segment_start,
                "text": text
            })

        return new_segments

    def create_batches(self, segments, target_context_words=300):
        """
        Группирует сегменты в батчи.
        ВАЖНО: Закрывает батч ТОЛЬКО если последний сегмент заканчивается точкой/воскл/вопросом.
        """
        batches = []
        current_batch_segments = []
        current_word_count = 0
        batch_id = 0

        # Регулярка для "сильного" конца предложения (Sentence End)
        # Ищем . ! ? в конце строки (возможно перед кавычкой)
        sentence_end_pattern = re.compile(r"[.!?][\"']?$")

        for idx, seg in enumerate(segments):
            # Присваиваем ID сегменту глобально (важно для связки с EDL)
            seg['segment_id'] = idx
            
            # Добавляем в текущий батч
            current_batch_segments.append(seg)
            current_word_count += len(seg['text'].split())
            
            # Проверяем, является ли этот сегмент концом предложения
            text = seg['text'].strip()
            is_sentence_end = bool(sentence_end_pattern.search(text))
            
            # ЛОГИКА ЗАКРЫТИЯ БАТЧА:
            # 1. Набрали достаточно слов (target_context_words)
            # 2. И (ОБЯЗАТЕЛЬНО) текущий сегмент заканчивает предложение
            if current_word_count >= target_context_words and is_sentence_end:
                full_text = " ".join([s['text'] for s in current_batch_segments])
                batches.append({
                    "batch_id": batch_id,
                    "context_text": full_text,
                    "segments": current_batch_segments
                })
                
                batch_id += 1
                current_batch_segments = []
                current_word_count = 0
        
        # Если остались сегменты (хвост, даже если не кончается точкой)
        if current_batch_segments:
            full_text = " ".join([s['text'] for s in current_batch_segments])
            batches.append({
                "batch_id": batch_id,
                "context_text": full_text,
                "segments": current_batch_segments
            })

        return batches

    def _get_audio_duration(self, audio_path):
        """Get actual audio file duration using ffprobe."""
        import subprocess
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', 
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get audio duration via ffprobe: {e}")
        return None

    def process(self, audio_path, output_path):
        # 1. Whisper
        raw = self.transcribe(audio_path)
        
        # Get ACTUAL audio file duration (not Whisper's last word timestamp!)
        # Whisper often ends early, cutting off trailing audio
        actual_duration = self._get_audio_duration(audio_path)
        
        # Fallback to Whisper's estimate if ffprobe fails
        whisper_duration = raw[-1]['end'] if raw else 0.0
        
        if actual_duration and actual_duration > whisper_duration:
            total_duration = actual_duration
            logger.info(f"📏 Using actual file duration: {actual_duration:.2f}s (Whisper reported: {whisper_duration:.2f}s)")
        else:
            total_duration = whisper_duration
        
        # 2. Syntax Cut + Gapless
        optimized = self.syntax_segmentation(raw)
        
        # Extend last segment to actual audio end if needed
        if optimized and actual_duration and optimized[-1]['end'] < actual_duration:
            gap = actual_duration - optimized[-1]['end']
            if gap > 0.01:  # More than 10ms gap
                logger.info(f"📏 Extending last segment by {gap:.2f}s to match actual audio end")
                optimized[-1]['end'] = actual_duration
                optimized[-1]['duration'] = optimized[-1]['end'] - optimized[-1]['start']
        
        # 3. Smart Batching (Sentence Aware)
        batches = self.create_batches(optimized)
        
        data = {
            "duration": total_duration,
            "batches": batches
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"✅ Transcript ready: {len(optimized)} segments. Duration: {total_duration:.2f}s")
        return data

    def merge_files(self, file_paths, output_path):
        """
        Merges multiple audio files into one using ffmpeg concat demuxer.
        
        Args:
            file_paths: List of file paths to merge
            output_path: Path to save the merged file
            
        Returns:
            bool: True if successful
        """
        import subprocess
        import tempfile
        
        if not file_paths:
            return False
            
        output_path = Path(output_path)
        
        # Create a temporary list file for ffmpeg
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                list_file_path = Path(f.name)
                for path in file_paths:
                    # ffmpeg requires absolute paths and specific escaping
                    abs_path = Path(path).absolute()
                    f.write(f"file '{str(abs_path)}'\n")
                    
            logger.info(f"🧬 Merging {len(file_paths)} audio files into {output_path.name}...")
            
            # Run ffmpeg concat
            # -f concat: use concat demuxer
            # -safe 0: allow unsafe file paths (absolute paths)
            # -c copy: no re-encoding (very fast)
            cmd = [
                'ffmpeg', 
                '-f', 'concat', 
                '-safe', '0', 
                '-i', str(list_file_path), 
                '-c', 'copy', 
                '-y',  # Overwrite output
                str(output_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            
            # Cleanup temp file
            if list_file_path.exists():
                list_file_path.unlink()
                
            if result.returncode == 0 and output_path.exists():
                logger.info(f"✅ Audio merge complete: {output_path}")
                return True
            else:
                logger.error(f"❌ Audio merge failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during audio merge: {e}")
            return False