"""
Script Parser - парсит Word документы (.docx) и Markdown файлы для извлечения 
структуры скрипта видео-эссе.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ScriptParser:
    """Парсер скриптов из .docx и .md форматов."""
    
    def __init__(self):
        pass
    
    def parse(self, script_path: Path) -> List[Dict[str, Any]]:
        """
        Парсит скрипт и возвращает список блоков текста.
        
        Args:
            script_path: Путь к файлу скрипта (.docx или .md)
            
        Returns:
            Список блоков вида:
            [
                {
                    "block_id": 0,
                    "type": "heading" | "paragraph",
                    "level": 1-6 (для heading),
                    "text": "Содержимое блока",
                    "word_count": 42
                },
                ...
            ]
        """
        script_path = Path(script_path)
        
        if not script_path.exists():
            raise FileNotFoundError(f"Script file not found: {script_path}")
        
        suffix = script_path.suffix.lower()
        
        if suffix == ".docx":
            return self._parse_docx(script_path)
        elif suffix in [".md", ".markdown"]:
            return self._parse_markdown(script_path)
        elif suffix == ".txt":
            return self._parse_plaintext(script_path)
        else:
            raise ValueError(f"Unsupported script format: {suffix}. Use .docx, .md, or .txt")
    
    def _parse_docx(self, path: Path) -> List[Dict[str, Any]]:
        """Парсит Word документ."""
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx not installed. Run: pip install python-docx")
        
        logger.info(f"📄 Parsing Word document: {path.name}")
        
        doc = Document(path)
        blocks = []
        block_id = 0
        
        for para in doc.paragraphs:
            text = para.text.strip()
            
            if not text:
                continue
            
            # Определяем тип блока по стилю
            style_name = para.style.name.lower() if para.style else ""
            
            if "heading" in style_name:
                # Извлекаем уровень заголовка (Heading 1 -> 1)
                level_match = re.search(r'(\d+)', style_name)
                level = int(level_match.group(1)) if level_match else 1
                
                blocks.append({
                    "block_id": block_id,
                    "type": "heading",
                    "level": level,
                    "text": text,
                    "word_count": len(text.split())
                })
            else:
                blocks.append({
                    "block_id": block_id,
                    "type": "paragraph",
                    "text": text,
                    "word_count": len(text.split())
                })
            
            block_id += 1
        
        logger.info(f"✅ Extracted {len(blocks)} blocks from document")
        return blocks
    
    def _parse_markdown(self, path: Path) -> List[Dict[str, Any]]:
        """Парсит Markdown файл."""
        logger.info(f"📄 Parsing Markdown: {path.name}")
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        blocks = []
        block_id = 0
        
        # Разбиваем на строки
        lines = content.split('\n')
        current_paragraph = []
        
        for line in lines:
            stripped = line.strip()
            
            # Heading
            if stripped.startswith('#'):
                # Сначала сохраняем накопленный параграф
                if current_paragraph:
                    para_text = ' '.join(current_paragraph)
                    blocks.append({
                        "block_id": block_id,
                        "type": "paragraph",
                        "text": para_text,
                        "word_count": len(para_text.split())
                    })
                    block_id += 1
                    current_paragraph = []
                
                # Парсим заголовок
                level = len(stripped) - len(stripped.lstrip('#'))
                heading_text = stripped.lstrip('#').strip()
                
                if heading_text:
                    blocks.append({
                        "block_id": block_id,
                        "type": "heading",
                        "level": level,
                        "text": heading_text,
                        "word_count": len(heading_text.split())
                    })
                    block_id += 1
            
            # Пустая строка - конец параграфа
            elif not stripped:
                if current_paragraph:
                    para_text = ' '.join(current_paragraph)
                    blocks.append({
                        "block_id": block_id,
                        "type": "paragraph",
                        "text": para_text,
                        "word_count": len(para_text.split())
                    })
                    block_id += 1
                    current_paragraph = []
            
            # Обычный текст
            else:
                current_paragraph.append(stripped)
        
        # Остаток
        if current_paragraph:
            para_text = ' '.join(current_paragraph)
            blocks.append({
                "block_id": block_id,
                "type": "paragraph",
                "text": para_text,
                "word_count": len(para_text.split())
            })
        
        logger.info(f"✅ Extracted {len(blocks)} blocks from markdown")
        return blocks
    
    def _parse_plaintext(self, path: Path) -> List[Dict[str, Any]]:
        """Парсит обычный текстовый файл (разбивает по абзацам)."""
        logger.info(f"📄 Parsing plaintext: {path.name}")
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        blocks = []
        block_id = 0
        
        # Разбиваем по двойным переносам строк (абзацы)
        paragraphs = re.split(r'\n\s*\n', content)
        
        for para in paragraphs:
            text = para.strip()
            if text:
                blocks.append({
                    "block_id": block_id,
                    "type": "paragraph",
                    "text": text,
                    "word_count": len(text.split())
                })
                block_id += 1
        
        logger.info(f"✅ Extracted {len(blocks)} blocks from plaintext")
        return blocks
    
    def save_parsed(self, blocks: List[Dict[str, Any]], output_path: Path) -> None:
        """Сохраняет результат парсинга в JSON."""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(blocks, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Parsed script saved to: {output_path}")
    
    def get_full_text(self, blocks: List[Dict[str, Any]]) -> str:
        """Собирает полный текст из блоков для сравнения с аудио."""
        return "\n\n".join([b["text"] for b in blocks])
