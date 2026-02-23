import asyncio
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

async def transcribe_voice(file_path: str, max_retries: int = 3) -> str:
    """Транскрибация через Groq (Whisper-3)"""
    # TEMP: язык захардкожен как ru — нужно заменить на динамическое определение языка пользователя
    with open(file_path, "rb") as file:
        file_content = file.read()
    for attempt in range(max_retries):
        try:
            translation = await asyncio.to_thread(
                lambda: groq_client.audio.transcriptions.create(
                    file=(file_path, file_content),
                    model="whisper-large-v3",
                    language="ru",
                )
            )
            return translation.text
        except groq.RateLimitError:
            if attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                logging.warning(f"Transcription rate limited, retry {attempt+1}/{max_retries} in {wait}s")
                await asyncio.sleep(wait)
            else:
                raise Exception("rate_limit")
        except groq.APIConnectionError:
            raise Exception("connection_error")
        except Exception as e:
            logging.error(f"Transcription error: {e}")
            raise Exception("unknown_error")

async def get_ai_response(text: str, system_prompt: str, max_retries: int = 3) -> str:
    """Запрос к LLM через Groq"""
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                lambda: llm_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": system_prompt + "\n\n" + text},
                        {"role": "user", "content": "Выполни задачу."},
                    ]
                )
            )
            return response.choices[0].message.content
        except groq.RateLimitError:
            if attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                logging.warning(f"LLM rate limited, retry {attempt+1}/{max_retries} in {wait}s")
                await asyncio.sleep(wait)
            else:
                raise Exception("rate_limit")
        except groq.APIConnectionError:
            raise Exception("connection_error")
        except Exception as e:
            logging.error(f"LLM error: {e}")
            raise Exception("unknown_error")

async def text_to_speech(text: str) -> bytes:
    """TTS через ElevenLabs — возвращает аудио в байтах"""
    try:
        audio = await asyncio.to_thread(
            lambda: b"".join(tts_client.text_to_speech.convert(
                voice_id="pNInz6obpgDQGcFmaJgB",  # Adam — нейтральный мужской, поддерживает русский
                text=text,
                model_id="eleven_multilingual_v2",
                voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
            ))
        )
        return audio
    except Exception as e:
        logging.error(f"TTS error: {e}")
        raise Exception("tts_error")