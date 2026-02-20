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

    await callback.message.answer("🤖 Думаю...")
    system_prompt = prompts[prompt_id]['prompt']
    result = await get_ai_response(text, system_prompt)
    
    await state.update_data(last_text=result)
    await callback.message.answer(f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "add_new_prompt")
async def add_prompt_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название для новой кнопки (например: 'Юмор'):")
    await state.set_state(BotStates.waiting_for_name)
    await callback.answer()


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

@dp.message(BotStates.waiting_for_name)
async def add_prompt_name(message: types.Message, state: FSMContext):
    await state.update_data(new_name=message.text)
    await message.answer(f"Теперь введите сам промт для '{message.text}':")
    await state.set_state(BotStates.waiting_for_content)

@dp.message(BotStates.waiting_for_content)
async def add_prompt_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data['new_name']
    prompt_text = message.text
    p_id = f"custom_{int(asyncio.get_event_loop().time())}"
    
    with open("data/prompts.json", "r+", encoding="utf-8") as f:
        prompts = json.load(f)
        prompts[p_id] = {"name": name, "prompt": prompt_text}
        f.seek(0)
        json.dump(prompts, f, indent=2, ensure_ascii=False)
        f.truncate()
    
    await message.answer(f"✅ Кнопка '{name}' успешно добавлена!")
    await state.clear()


# --- ОБРАБОТКА ТЕКСТА (всегда последний) ---

@dp.message(F.text)
async def handle_text(message: types.Message, state: FSMContext):
    await state.update_data(last_text=message.text)
    await message.answer("Выберите действие:", reply_markup=get_main_menu())


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())