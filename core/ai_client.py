import asyncio
import groq
from config import GROQ_KEY, LLM_KEY

groq_client = groq.Groq(api_key=GROQ_KEY)
llm_client = groq.Groq(api_key=LLM_KEY)

async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as file:
        file_content = file.read()
    translation = await asyncio.to_thread(
        lambda: groq_client.audio.transcriptions.create(
            file=(file_path, file_content),
            model="whisper-large-v3",
        )
    )
    return translation.text

async def get_ai_response(text: str, system_prompt: str) -> str:
    response = await asyncio.to_thread(
        lambda: llm_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ]
        )
    )
    return response.choices[0].message.content

async def text_to_speech(text: str) -> bytes:
    raise NotImplementedError("TTS не подключён.")