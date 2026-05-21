import time
import logging
import os
import json
import threading
from datetime import datetime, date
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, InternalServerError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type, before_sleep_log

logger = logging.getLogger(__name__)

TRACKING_FILE = os.path.expanduser("~/.sculptorpro_gemini_stats.json")

# Primary and fallback model configuration
AVAILABLE_MODELS = {
    "flash-3.1": {"id": "gemini-3.1-flash-lite-preview", "label": "Flash 3.1 Lite"},
    "flash-3":   {"id": "gemini-3.0-flash",              "label": "Flash 3.0"},
    "flash-2.5": {"id": "gemini-2.5-flash",              "label": "Flash 2.5"},
}
DEFAULT_MODEL_KEY = "flash-3.1"
FALLBACK_MODEL = "gemini-2.5-flash"

class GeminiClient:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GeminiClient, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, model_name=None):
        with self._lock:
            if model_name is None:
                model_name = AVAILABLE_MODELS[DEFAULT_MODEL_KEY]["id"]
            if getattr(self, "_initialized", False) and getattr(self, "model_name", None) == model_name:
                return

            self.model_name = model_name
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                logger.warning("GOOGLE_API_KEY not found in env variables! Gemini features will fail.")
            else:
                genai.configure(api_key=api_key)
            
            self.model = genai.GenerativeModel(model_name)
            self.fallback_model = genai.GenerativeModel(FALLBACK_MODEL)
            
            # Rate limiting configuration (14 requests per 60 seconds)
            self.rpm_limit = 14
            self.window_size = 60.0
            self.request_timestamps = []
            
            # Daily limit configuration
            self.rpd_limit = 500
            self.session_requests = 0
            self.daily_requests = 0
            self.last_reset_date = str(date.today())
            self._load_daily_stats()

            self._initialized = True

    def _load_daily_stats(self):
        self.daily_requests = 0
        self.last_reset_date = str(date.today())
        try:
            if os.path.exists(TRACKING_FILE):
                with open(TRACKING_FILE, "r") as f:
                    data = json.load(f)
                    if data.get("date") == self.last_reset_date:
                        self.daily_requests = data.get("count", 0)
        except Exception as e:
            logger.warning(f"Could not load tracking file: {e}")

    def _save_daily_stats(self):
        try:
            with open(TRACKING_FILE, "w") as f:
                json.dump({"date": self.last_reset_date, "count": self.daily_requests}, f)
        except Exception as e:
            logger.warning(f"Could not save tracking file: {e}")

    def _wait_for_capacity(self):
        with self._lock:
            now = time.time()
            today_str = str(date.today())
            
            # Reset daily counter if a new day has started
            if today_str != self.last_reset_date:
                self.last_reset_date = today_str
                self.daily_requests = 0
                self._save_daily_stats()

            # Check daily limits
            if self.daily_requests >= self.rpd_limit:
                logger.error("❌ Daily limit of 500 requests exceeded.")
                raise Exception("Daily API limit exceeded (500 RPD). Try again tomorrow.")

            if self.daily_requests >= 450 and self.daily_requests % 10 == 0:
                logger.warning(f"⚠️ Approaching daily API limit: {self.daily_requests}/{self.rpd_limit} requests used.")

            # RPM limit logic: remove old timestamps outside the window
            self.request_timestamps = [t for t in self.request_timestamps if now - t < self.window_size]

            # If we hit the RPM limit, sleep until the oldest request falls out of the window
            if len(self.request_timestamps) >= self.rpm_limit:
                sleep_time = self.window_size - (now - self.request_timestamps[0])
                if sleep_time > 0:
                    logger.info(f"⏳ Rate limiting: waiting {sleep_time:.2f}s for the next available slot...")
                    time.sleep(sleep_time)
                # Cleanup after sleep
                now = time.time()
                self.request_timestamps = [t for t in self.request_timestamps if now - t < self.window_size]

            # Record this request
            self.request_timestamps.append(now)
            self.daily_requests += 1
            self.session_requests += 1
            self._save_daily_stats()

    @retry(
        retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, InternalServerError)),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def _do_generate_content(self, *args, **kwargs):
        """Inner method wrapped by tenacity — tries PRIMARY model with 3 retries."""
        return self.model.generate_content(*args, **kwargs)

    @retry(
        retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, InternalServerError)),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def _do_generate_content_fallback(self, *args, **kwargs):
        """Fallback method — tries FALLBACK model with 3 retries."""
        return self.fallback_model.generate_content(*args, **kwargs)

    def generate_content(self, *args, **kwargs):
        """
        Public Gateway: Wait for capacity -> generate_content with backoff.
        If primary model fails after retries, automatically falls back to gemini-2.5-flash.
        """
        # Remove legacy custom kwargs
        kwargs.pop('retries', None)
        kwargs.pop('initial_delay', None)

        self._wait_for_capacity()
        
        try:
            return self._do_generate_content(*args, **kwargs)
        except (ServiceUnavailable, InternalServerError, ResourceExhausted) as e:
            logger.warning(f"⚠️ Primary model ({self.model_name}) failed after retries: {e}")
            logger.info(f"🔄 Switching to fallback model: {FALLBACK_MODEL}")
            return self._do_generate_content_fallback(*args, **kwargs)

    def parse_json(self, response_text):
        """Очищает ответ от markdown ```json ... ```"""
        if not response_text: return ""
        text = response_text.replace("```json", "").replace("```", "").strip()
        return text