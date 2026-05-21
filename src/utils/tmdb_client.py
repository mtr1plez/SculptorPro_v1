import requests
import logging
import re

logger = logging.getLogger(__name__)

class TMDBClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base = "https://image.tmdb.org/t/p/w500" # w500 - оптимальный размер

    def get_poster_url(self, query):
        if not self.api_key or self.api_key == "ТВОЙ_КЛЮЧ_ВСТАВИТЬ_СЮДА":
            return None

        try:
            search_query = (query or "").strip()
            year_match = re.search(r"\b(19|20)\d{2}\b", search_query)
            year = year_match.group(0) if year_match else None
            if year:
                search_query = re.sub(rf"\b{year}\b", "", search_query).strip()

            # 1. Поиск фильма
            search_url = f"{self.base_url}/search/movie"
            params = {
                "api_key": self.api_key,
                "query": search_query,
                "language": "en-US"
            }
            if year:
                params["year"] = year
            
            response = requests.get(search_url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            if data["results"]:
                # Берем первый результат
                poster_path = data["results"][0].get("poster_path")
                if poster_path:
                    return f"{self.image_base}{poster_path}"
            
            return None

        except Exception as e:
            logger.error(f"TMDB Error for '{query}': {e}")
            return None
