import os
from dotenv import load_dotenv
import sys

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
LLM_KEY = os.getenv("LLM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
FFMPEG_PATH = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

TEMP_DIR = "data/temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)