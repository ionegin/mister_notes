import asyncio
import groq
import logging
from openai import AsyncOpenAI
from config import GROQ_KEY, LLM_REGISTRY

# Groq — только для транскрипции (Whisper). Ленивая инициализация при первом вызове.
_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        _groq_client = groq.Groq(api_key=GROQ_KEY)
    return _groq_client

# Кэш клиентов — один экземпляр на провайдера
_clients: dict[str, AsyncOpenAI] = {}


def get_llm_client(model_key: str) -> tuple[AsyncOpenAI, str]:
    cfg = LLM_REGISTRY.get(model_key)
    if not cfg:
        raise ValueError(f"Unknown model key: {model_key}")
    if model_key not in _clients:
        _clients[model_key] = AsyncOpenAI(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
        )
    return _clients[model_key], cfg["model"]


async def transcribe_voice(file_path: str, max_retries: int = 3) -> str:
    """Транскрибация через Groq (Whisper large-v3). Не меняется."""
    with open(file_path, "rb") as file:
        file_content = file.read()
    for attempt in range(max_retries):
        try:
            result = await asyncio.to_thread(
                lambda: _get_groq_client().audio.transcriptions.create(
                    file=(file_path, file_content),
                    model="whisper-large-v3",
                    language="ru",
                )
            )
            return result.text
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


async def get_ai_response(
    text: str,
    system_prompt: str,
    role: str = "smart",
    max_retries: int = 3,
) -> str:
    """
    role="smart"   -> LLM_SMART   (саммари, бриф, стили)
    role="cleanup" -> LLM_CLEANUP (чистка транскрипции)
    role="qwen-72b" и тд -> прямой ключ из реестра (для тестов)
    """
    import config

    if role == "smart":
        model_key = config.LLM_SMART
    elif role == "cleanup":
        model_key = config.LLM_CLEANUP
    else:
        model_key = role

    client, model_name = get_llm_client(model_key)
    label = LLM_REGISTRY[model_key]["label"]

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt + "\n\n" + text},
                    {"role": "user", "content": "Выполни задачу."},
                ],
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            err = str(e).lower()
            if "rate" in err and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                logging.warning(f"[{label}] rate limited, retry {attempt+1}/{max_retries} in {wait}s")
                await asyncio.sleep(wait)
            else:
                logging.error(f"[{label}] error: {e}")
                if attempt == max_retries - 1:
                    raise Exception("unknown_error")