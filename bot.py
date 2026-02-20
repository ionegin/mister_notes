import asyncio
import json
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, TEMP_DIR
from core.ai_client import transcribe_voice, get_gemini_response
from core.keyboards import get_main_menu
from utils.audio_conv import convert_ogg_to_mp3

# Состояния для FSM
class BotStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_content = State()
    processing_text = State()

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
    
    # Конвертируем и транскрибируем
    mp3_path = convert_ogg_to_mp3(ogg_path)
    text = await transcribe_voice(mp3_path)
    
    # Чистим файлы
    os.remove(ogg_path)
    os.remove(mp3_path)
    
    await state.update_data(last_text=text)
    await msg.edit_text(f"📝 **Результат расшифровки:**\n\n{text}", parse_mode="Markdown", reply_markup=get_main_menu())

@dp.message(F.text)
async def handle_text(message: types.Message, state: FSMContext):
    await state.update_data(last_text=message.text)
    await message.answer("Выберите действие:", reply_markup=get_main_menu())

# --- ОБРАБОТКА КНОПОК ---

@dp.callback_query(F.data.startswith("ai_"))
async def process_ai_action(callback: types.CallbackQuery, state: FSMContext):
    prompt_id = callback.data.split("_")[1]
    user_data = await state.get_data()
    text = user_data.get("last_text")
    
    if not text:
        await callback.answer("Текст не найден. Пришлите сообщение заново.")
        return

    await callback.message.edit_text("🤖 Думаю...")
    
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    
    system_prompt = prompts[prompt_id]['prompt']
    result = await get_gemini_response(text, system_prompt)
    
    await callback.message.edit_text(f"✅ **Готово:**\n\n{result}", parse_mode="Markdown")
    await callback.answer()

# --- ДОБАВЛЕНИЕ ПРОМТА ---

@dp.callback_query(F.data == "add_new_prompt")
async def add_prompt_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название для новой кнопки (например: 'Юмор'):")
    await state.set_state(BotStates.waiting_for_name)
    await callback.answer()

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
    p_id = f"custom_{int(asyncio.get_event_loop().time())}" # Уникальный ID
    
    with open("data/prompts.json", "r+", encoding="utf-8") as f:
        prompts = json.load(f)
        prompts[p_id] = {"name": name, "prompt": prompt_text}
        f.seek(0)
        json.dump(prompts, f, indent=2, ensure_ascii=False)
        f.truncate()
    
    await message.answer(f"✅ Кнопка '{name}' успешно добавлена!")
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())