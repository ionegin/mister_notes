import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
LLM_KEY = os.getenv("LLM_API_KEY")

# Путь к папке для временных файлов
TEMP_DIR = "data/temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)
