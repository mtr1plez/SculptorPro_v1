import json
import logging
from typing import List
from copy import deepcopy
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.utils.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

router = APIRouter()
gemini_client = GeminiClient()

class BrainstormIdeasRequest(BaseModel):
    movie_title: str

class BrainstormIdea(BaseModel):
    title: str
    synopsis: str

class BrainstormScriptRequest(BaseModel):
    idea_title: str
    idea_synopsis: str

@router.post("/ideas")
async def generate_ideas(req: BrainstormIdeasRequest):
    """
    Step 1: Generate 3 short ideas based on a movie title.
    """
    logger.info(f"Generating brainstorm ideas for: {req.movie_title}")
    
    prompt = f"""
Ты — ютуб-аналитик кино. Предложи 3 идеи для короткого видео (YouTube Shorts) по фильму "{req.movie_title}".
Формат: спорное, неочевидное или парадоксальное мнение о решении персонажа или скрытом смысле сцены. Без банального пересказа сюжета. 
Выдай только интригующий заголовок и синопсис на 2 предложения для каждой идеи.

Твой ответ должен быть валидным JSON массивом объектов, где каждый объект имеет поля "title" и "synopsis". 
Никакого лишнего текста или разметки, строго JSON массив.
Пример:
[
  {{
    "title": "Пример заголовка",
    "synopsis": "Первое предложение. Второе предложение."
  }}
]
"""
    try:
        response = gemini_client.generate_content(prompt)
        # Parse JSON from Gemini
        json_str = gemini_client.parse_json(response.text)
        
        # Validate that it's a list
        ideas = json.loads(json_str)
        if not isinstance(ideas, list):
            raise ValueError("Expected a JSON array of ideas")
            
        return {"ideas": ideas}

    except Exception as e:
        logger.error(f"Failed to generate brainstorm ideas: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/script")
async def generate_script(req: BrainstormScriptRequest):
    """
    Step 2: Generate a YouTube Shorts script based on the selected idea.
    """
    logger.info(f"Generating brainstorm script for idea: {req.idea_title}")
    
    prompt = f"""
Напиши сценарий для YouTube Shorts по этой идее на 100-150 слов.

Заголовок идеи: {req.idea_title}
Синопсис идеи: {req.idea_synopsis}

Структура: 
1) Резкий хук в первом предложении
2) Аргументация (почему все ошибаются, а этот тейк верный)
3) Короткий вывод

Текст должен быть динамичным, под быструю начитку.
Верни ПЛАЙН-ТЕКСТ (без JSON, просто текст сценария).
"""
    try:
        response = gemini_client.generate_content(prompt)
        script_text = response.text.strip()
        return {"script": script_text}
        
    except Exception as e:
        logger.error(f"Failed to generate brainstorm script: {e}")
        raise HTTPException(status_code=500, detail=str(e))
