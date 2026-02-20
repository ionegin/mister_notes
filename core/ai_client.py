import groq
import google.generativeai as genai
from config import GROQ_KEY, GEMINI_KEY

# Инициализация Gemini
genai.configure(api_key=GEMINI_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# Инициализация Groq
groq_client = groq.Groq(api_key=GROQ_KEY)

async def transcribe_voice(file_path: str) -> str:
    """Транскрибация через Groq (Whisper-3)"""
    with open(file_path, "rb") as file:
        translation = groq_client.audio.transcriptions.create(
            file=(file_path, file.read()),
            model="whisper-large-v3",
        )
    return translation.text

async def get_gemini_response(text: str, system_prompt: str) -> str:
    """Запрос к Gemini с заданным промтом"""
    full_prompt = f"{system_prompt}\n\nТекст для обработки:\n{text}"
    response = gemini_model.generate_content(full_prompt)
    return response.text