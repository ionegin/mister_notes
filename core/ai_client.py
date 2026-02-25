import asyncio
import groq
import logging
import os
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from config import GROQ_KEY, LLM_KEY, ELEVENLABS_KEY, FFMPEG_PATH
from openai import AsyncOpenAI

# Groq для транскрибации (Whisper)
groq_client = groq.Groq(api_key=GROQ_KEY)

# DeepSeek для LLM
llm_client = AsyncOpenAI(
    api_key=LLM_KEY,
    base_url="https://api.deepseek.com"
)

# ElevenLabs для TTS
tts_client = ElevenLabs(api_key=ELEVENLABS_KEY)


async def extract_audio(video_path: str) -> str:
    """Извлекает аудио из mp4 в ogg — файл становится в 10-20x легче"""
    audio_path = video_path.replace(".mp4", "_audio.ogg")
    proc = await asyncio.create_subprocess_exec(
        FFMPEG_PATH, "-i", video_path,
        "-vn",
        "-acodec", "libopus",
        "-y",
        audio_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return audio_path


async def transcribe_voice(file_path: str, max_retries: int = 3) -> str:
    """Транскрибация через Groq (Whisper-3)"""
    converted_path = None
    try:
        if file_path.endswith(".mp4"):
            converted_path = await extract_audio(file_path)
            transcribe_path = converted_path
        else:
            transcribe_path = file_path

        with open(transcribe_path, "rb") as file:
            file_content = file.read()

        for attempt in range(max_retries):
            try:
                translation = await asyncio.to_thread(
                    lambda: groq_client.audio.transcriptions.create(
                        file=(transcribe_path, file_content),
                        model="whisper-large-v3",
                        language="ru",
                    )
                )
                return translation.text
            except groq.RateLimitError:
                if attempt < max_retries - 1:
                    wait = 5 * (2 ** attempt)
                    logging.warning(f"Transcription rate limited, retry {attempt+1}/{max_retries} in {wait}s")
                    await asyncio.sleep(wait)
                else:
                    raise Exception("rate_limit")
            except groq.APIConnectionError:
                raise Exception("connection_error")
            except Exception as e:
                logging.error(f"Transcription error: {e}")
                raise Exception("unknown_error")

    finally:
        if converted_path and os.path.exists(converted_path):
            try:
                os.remove(converted_path)
            except Exception:
                pass


async def get_ai_response(text: str, system_prompt: str, max_retries: int = 3) -> str:
    """Запрос к LLM через DeepSeek"""
    for attempt in range(max_retries):
        try:
            response = await llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt + "\n\n" + text},
                    {"role": "user", "content": "Выполни задачу."},
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            err = str(e).lower()
            if "rate" in err and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                logging.warning(f"LLM rate limited, retry {attempt+1}/{max_retries} in {wait}s")
                await asyncio.sleep(wait)
            elif "connect" in err or "network" in err:
                raise Exception("connection_error")
            else:
                logging.error(f"LLM error: {e}")
                raise Exception("unknown_error")


async def text_to_speech(text: str) -> bytes:
    """TTS через ElevenLabs"""
    try:
        audio = await asyncio.to_thread(
            lambda: b"".join(tts_client.text_to_speech.convert(
                voice_id="pNInz6obpgDQGcFmaJgB",
                text=text,
                model_id="eleven_multilingual_v2",
                voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
            ))
        )
        return audio
    except Exception as e:
        logging.error(f"TTS error: {e}")
        raise Exception("tts_error")