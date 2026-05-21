import logging
from elevenlabs.client import ElevenLabs
from elevenlabs import Voice, VoiceSettings

logger = logging.getLogger(__name__)

class ElevenLabsClient:
    """
    Wrapper for ElevenLabs API.
    """
    def __init__(self, api_key: str):
        self.client = ElevenLabs(api_key=api_key)

    def get_voices(self):
        """
        Fetches available voices.
        """
        try:
            response = self.client.voices.get_all()
            # response.voices is a list of Voice objects
            voices_data = []
            for v in response.voices:
                voices_data.append({
                    "voice_id": v.voice_id,
                    "name": v.name,
                    "category": v.category,
                    "preview_url": v.preview_url
                })
            return voices_data
        except Exception as e:
            logger.error(f"Failed to fetch voices: {e}")
            raise e

    def generate_audio(self, text: str, voice_id: str):
        """
        Generates audio for the given text and voice_id.
        Returns the audio bytes generator.
        """
        try:
            audio_generator = self.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id="eleven_multilingual_v2"
            )
            return audio_generator
        except Exception as e:
            logger.error(f"Failed to generate audio: {e}")
            raise e
