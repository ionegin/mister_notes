import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")

# --- РЕЕСТР МОДЕЛЕЙ ---
# Все провайдеры через OpenAI-compatible API.
# Рабочий флоу сейчас: 2 роли (тупая/быстрая + умная), обе через Groq — этого достаточно.
# Мульти-провайдерный тест-функционал (OpenRouter/Gemini) закомментирован ниже, не удалён —
# вернуть легко, когда понадобится гонять задачи параллельно на нескольких LLM.
LLM_REGISTRY = {
    "llama70b": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.getenv("GROQ_API_KEY"),
        "model": "llama-3.3-70b-versatile",
        "label": "Llama 3.3 70B (Groq)",
    },
    "llama8b": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.getenv("GROQ_API_KEY"),
        "model": "llama-3.1-8b-instant",
        "label": "Llama 3.1 8B (Groq)",
    },
    # --- ЗАКОММЕНТИРОВАНО: тестовый multi-LLM функционал, не нужен в текущем флоу ---
    # "gemma4-31b": {
    #     "base_url": "https://openrouter.ai/api/v1",
    #     "api_key": os.getenv("OPENROUTER_KEY"),
    #     "model": "google/gemma-4-31b-it",
    #     "label": "Gemma 4 31B (OpenRouter)",
    # },
    # "gemma4-31b-free": {
    #     "base_url": "https://openrouter.ai/api/v1",
    #     "api_key": os.getenv("OPENROUTER_KEY"),
    #     "model": "google/gemma-4-31b-it:free",
    #     "label": "Gemma 4 31B free (OpenRouter)",
    # },
    # "gemini-flash": {
    #     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    #     "api_key": os.getenv("GEMINI_KEY"),
    #     "model": "gemini-2.0-flash",
    #     "label": "Gemini 2.0 Flash (Google)",
    # },
    # "gemini-flash-lite": {
    #     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    #     "api_key": os.getenv("GEMINI_KEY"),
    #     "model": "gemini-2.0-flash-lite",
    #     "label": "Gemini 2.0 Flash Lite (Google)",
    # },
    # "qwen-72b": {
    #     "base_url": "https://openrouter.ai/api/v1",
    #     "api_key": os.getenv("OPENROUTER_KEY"),
    #     "model": "qwen/qwen-2.5-72b-instruct",
    #     "label": "Qwen 2.5 72B (OpenRouter)",
    # },
    # "gemma3-27b": {
    #     "base_url": "https://openrouter.ai/api/v1",
    #     "api_key": os.getenv("OPENROUTER_KEY"),
    #     "model": "google/gemma-3-27b-it",
    #     "label": "Gemma 3 27B (OpenRouter)",
    # },
}

# --- АКТИВНЫЕ РОЛИ ---
# Меняй эти строки напрямую или через команды бота /llm1 (CLEANUP) и /llm2 (SMART).
# LLM_CLEANUP — "тупая" быстрая модель: чистка транскрипции после Whisper
#               (роль "cleanup" в get_ai_response). Гоняется на КАЖДОЕ голосовое —
#               важна скорость и цена, не качество рассуждения.
# LLM_SMART   — "умная" модель: саммари, стили, перевод, meeting_brief
#               (роль "smart" в get_ai_response). Вызывается только по кнопке —
#               важно качество, скорость вторична. Дальше пригодится и для других
#               задач за пределами этого бота.
LLM_CLEANUP = "llama8b"
LLM_SMART = "llama70b"

# Путь к папке для временных файлов
TEMP_DIR = "data/temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)