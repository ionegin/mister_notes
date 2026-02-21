import groq
import logging
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from config import GROQ_KEY, LLM_KEY, ELEVENLABS_KEY

# Groq для транскрибации
groq_client = groq.Groq(api_key=GROQ_KEY)

# Groq для LLM
llm_client = groq.Groq(api_key=LLM_KEY)

# ElevenLabs для TTS
tts_client = ElevenLabs(api_key=ELEVENLABS_KEY)

async def transcribe_voice(file_path: str) -> str:
    """Транскрибация через Groq (Whisper-3)"""
    # TEMP: язык захардкожен как ru — нужно заменить на динамическое определение языка пользователя
    try:
        with open(file_path, "rb") as file:
            translation = groq_client.audio.transcriptions.create(
                file=(file_path, file.read()),
                model="whisper-large-v3",
                language="ru",
            )
        return translation.text
    except groq.RateLimitError:
        raise Exception("rate_limit")
    except groq.APIConnectionError:
        raise Exception("connection_error")
    except Exception as e:
        logging.error(f"Transcription error: {e}")
        raise Exception("unknown_error")

async def get_ai_response(text: str, system_prompt: str) -> str:
    """Запрос к LLM через Groq"""
    try:
        response = llm_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ]
        )
        return response.choices[0].message.content
    except groq.RateLimitError:
        raise Exception("rate_limit")
    except groq.APIConnectionError:
        raise Exception("connection_error")
    except Exception as e:
        logging.error(f"LLM error: {e}")
        raise Exception("unknown_error")

async def text_to_speech(text: str) -> bytes:
    """TTS через ElevenLabs — возвращает аудио в байтах"""
    try:
        audio = tts_client.text_to_speech.convert(
            voice_id="pNInz6obpgDQGcFmaJgB",  # Adam — нейтральный мужской, поддерживает русский
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
        )
        return b"".join(audio)
    except Exception as e:
        logging.error(f"TTS error: {e}")
        raise Exception("tts_error")