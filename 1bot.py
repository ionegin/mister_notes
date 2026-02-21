import asyncio
import json
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, TEMP_DIR
from core.ai_client import transcribe_voice, get_ai_response
from core.keyboards import get_main_menu

# Состояния для FSM
class BotStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_content = State()
    waiting_for_language = State()
    waiting_for_meeting_file = State()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ОБРАБОТКА СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Пришли мне текст или голосовое, и я предложу варианты обработки.")

@dp.message(F.voice)
async def handle_voice(message: types.Message, state: FSMContext):
    msg = await message.answer("📥 Скачиваю и расшифровываю...")
    
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    ogg_path = os.path.join(TEMP_DIR, f"{file_id}.ogg")
    await bot.download_file(file.file_path, ogg_path)
    
    raw_text = await transcribe_voice(ogg_path)
    os.remove(ogg_path)

    await msg.edit_text("✍️ Привожу текст в порядок...")
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])

    await state.update_data(last_text=text)
    await msg.edit_text(f"📝 **Расшифровка:**\n\n{text}\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())

@dp.message(F.video_note)
async def handle_video_note(message: types.Message, state: FSMContext):
    msg = await message.answer("📥 Скачиваю и расшифровываю...")
    
    file_id = message.video_note.file_id
    file = await bot.get_file(file_id)
    mp4_path = os.path.join(TEMP_DIR, f"{file_id}.mp4")
    await bot.download_file(file.file_path, mp4_path)
    
    raw_text = await transcribe_voice(mp4_path)
    os.remove(mp4_path)

    await msg.edit_text("✍️ Привожу текст в порядок...")
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])

    await state.update_data(last_text=text)
    await msg.edit_text(f"📝 **Расшифровка:**\n\n{text}\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())



@dp.message(F.audio)
async def handle_audio(message: types.Message, state: FSMContext):
    msg = await message.answer("📥 Скачиваю и расшифровываю...")
    
    file_id = message.audio.file_id
    file = await bot.get_file(file_id)
    ext = message.audio.file_name.split(".")[-1] if message.audio.file_name else "mp3"
    audio_path = os.path.join(TEMP_DIR, f"{file_id}.{ext}")
    await bot.download_file(file.file_path, audio_path)
    
    raw_text = await transcribe_voice(audio_path)
    os.remove(audio_path)

    await msg.edit_text("✍️ Привожу текст в порядок...")
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])

    await state.update_data(last_text=text)
    await msg.edit_text(f"📝 **Расшифровка:**\n\n{text}\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())


@dp.message(F.document)
async def handle_document(message: types.Message, state: FSMContext):
    fname = message.document.file_name or ""
    if not fname.endswith((".txt", ".json")):
        await message.answer("Поддерживаются только .txt и .json файлы (экспорт из Telegram Desktop).")
        return

    msg = await message.answer("📥 Читаю файл...")
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = os.path.join(TEMP_DIR, fname)
    await bot.download_file(file.file_path, file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    os.remove(file_path)

    # Для JSON-экспорта Telegram — вытащить только текст сообщений
    if fname.endswith(".json"):
        try:
            data = json.loads(raw)
            messages = data.get("messages", [])
            lines = []
            for m in messages:
                name = m.get("from", "Unknown")
                text = m.get("text", "")
                if isinstance(text, list):
                    text = "".join(t if isinstance(t, str) else t.get("text", "") for t in text)
                if text:
                    lines.append(f"{name}: {text}")
            raw = "\n".join(lines)
        except Exception:
            pass

    await state.update_data(last_text=raw[:15000])  # обрезаем если очень длинный
    await msg.edit_text(f"📄 **Файл загружен** ({len(raw)} символов)\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())

# --- ОБРАБОТКА КНОПОК ---

@dp.callback_query(F.data.startswith("ai_"))
async def process_ai_action(callback: types.CallbackQuery, state: FSMContext):
    prompt_id = callback.data.split("_", 1)[1]
    user_data = await state.get_data()
    text = user_data.get("last_text")
    
    if not text:
        await callback.answer("Текст не найден. Пришлите сообщение заново.")
        return

    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)

    if prompts[prompt_id]['prompt'] == "_translation_flow_":
        await state.set_state(BotStates.waiting_for_language)
        await callback.message.answer("На какой язык перевести?\n\nВведи одно слово (например: английский, français, deutsch):")
        await callback.answer()
        return

    if prompt_id == "meeting_brief":
        await callback.message.answer("📎 Загрузи файл встречи (.txt или .json экспорт из Telegram):")
        await state.set_state(BotStates.waiting_for_meeting_file)
        await callback.answer()
        return

    await callback.message.answer("🤖 Думаю...")
    system_prompt = prompts[prompt_id]['prompt']
    result = await get_ai_response(text, system_prompt)
    
    await state.update_data(last_text=result)
    await callback.message.answer(f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())
    await callback.answer()

# @dp.callback_query(F.data == "add_new_prompt")
# async def add_prompt_start(callback: types.CallbackQuery, state: FSMContext):
#   await callback.message.answer("Введите название для новой кнопки (например: 'Юмор'):")
#   await state.set_state(BotStates.waiting_for_name)
#   await callback.answer()


# --- FSM ХЕНДЛЕРЫ (должны быть выше handle_text) ---

@dp.message(BotStates.waiting_for_language)
async def handle_language_input(message: types.Message, state: FSMContext):
    lang_input = message.text.strip()

    if len(lang_input.split()) > 1:
        await message.answer("Пожалуйста, введи только одно слово — название языка:")
        return

    user_data = await state.get_data()
    text = user_data.get("last_text")
    await state.set_state(None)

    msg = await message.answer("🤖 Перевожу...")
    system_prompt = f"Переведи текст на {lang_input}. Верни только перевод, без пояснений и без оригинала."
    result = await get_ai_response(text, system_prompt)

    await state.update_data(last_text=result)
    await msg.edit_text(f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())

# Фича бота # Добавить имя Промта @dp.message(BotStates.waiting_for_name)
#async def add_prompt_name(message: types.Message, state: FSMContext):
#    await state.update_data(new_name=message.text)
#    await message.answer(f"Теперь введите сам промт для '{message.text}':")
#    await state.set_state(BotStates.waiting_for_content)

# Фича бота добавить название промта #@dp.message(BotStates.waiting_for_content)
#async def add_prompt_finish(message: types.Message, state: FSMContext):
#    data = await state.get_data()
#    name = data['new_name']
#    prompt_text = message.text
#    p_id = f"custom_{int(asyncio.get_event_loop().time())}"
    
#   with open("data/prompts.json", "r+", encoding="utf-8") as f:
#       prompts = json.load(f)
#       prompts[p_id] = {"name": name, "prompt": prompt_text}
#        f.seek(0)
#       json.dump(prompts, f, indent=2, ensure_ascii=False)
#       f.truncate()
#   
#   await message.answer(f"✅ Кнопка '{name}' успешно добавлена!")
#   await state.clear()


# --- ОБРАБОТКА ТЕКСТА (всегда последний) ---

@dp.message(F.text)
async def handle_text(message: types.Message, state: FSMContext):
    await state.update_data(last_text=message.text)
    await message.answer("Выберите действие:", reply_markup=get_main_menu())


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

@dp.message(BotStates.waiting_for_meeting_file, F.document)
async def handle_meeting_file(message: types.Message, state: FSMContext):
    fname = message.document.file_name or ""
    if not fname.endswith((".txt", ".json")):
        await message.answer("Нужен .txt или .json файл. Попробуй ещё раз:")
        return

    msg = await message.answer("📥 Читаю файл...")
    file = await bot.get_file(message.document.file_id)
    file_path = os.path.join(TEMP_DIR, fname)
    await bot.download_file(file.file_path, file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    os.remove(file_path)

    if fname.endswith(".json"):
        try:
            data = json.loads(raw)
            lines = []
            for m in data.get("messages", []):
                name = m.get("from", "Unknown")
                text = m.get("text", "")
                if isinstance(text, list):
                    text = "".join(t if isinstance(t, str) else t.get("text", "") for t in text)
                if text:
                    lines.append(f"{name}: {text}")
            raw = "\n".join(lines)
        except Exception:
            pass

    await state.clear()
    await msg.edit_text("🤖 Составляю бриф...")

    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)

    result = await get_ai_response(raw[:15000], prompts["meeting_brief"]["prompt"])
    await state.update_data(last_text=result)
    await msg.edit_text(f"✅ **Бриф:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())