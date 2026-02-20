import groq
from config import GROQ_KEY, LLM_KEY

# Groq для транскрибации
groq_client = groq.Groq(api_key=GROQ_KEY)

# Groq для LLM
llm_client = groq.Groq(api_key=LLM_KEY)

async def transcribe_voice(file_path: str) -> str:
    """Транскрибация через Groq (Whisper-3)"""
    with open(file_path, "rb") as file:
        translation = groq_client.audio.transcriptions.create(
            file=(file_path, file.read()),
            model="whisper-large-v3",
        )
    return translation.text

async def get_ai_response(text: str, system_prompt: str) -> str:
    """Запрос к LLM через Groq"""
    response = llm_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
    )
    return response.choices[0].message.content