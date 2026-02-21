import asyncio
import json
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, TEMP_DIR
from core.ai_client import transcribe_voice, get_ai_response
from core.keyboards import get_main_menu, get_submenu

WELCOME_TEXT = (
    "Привет! Я помогу обработать текст или голос.\n\n"
    "Умею: сократить, перевести на любой язык, изменить стиль.\n"
    "Пришли текст, голосовуху или кругляшок — и увидишь что можно сделать.\n\n"
    "Команды:\n"
    "/rawvoice — следующая голосовуха вернётся без вычитки ИИ"
)

class BotStates(StatesGroup):
    waiting_for_language = State()
    waiting_for_meeting_file = State()
    # ADD_PROMPT_FEATURE:
    # waiting_for_name = State()
    # waiting_for_content = State()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def load_prompts():
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        return json.load(f)

def find_button(prompts: dict, target_id: str) -> dict | None:
    """Ищет кнопку по id — в корне и в children"""
    if target_id in prompts:
        return prompts[target_id]
    for data in prompts.values():
        if isinstance(data, dict) and "children" in data:
            if target_id in data["children"]:
                return data["children"][target_id]
    return None

# --- СТАРТ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(WELCOME_TEXT)

@dp.message(Command("rawvoice"))
async def cmd_rawvoice(message: types.Message, state: FSMContext):
    await state.update_data(raw_mode=True)
    await message.answer("Окей, следующая голосовуха вернётся без вычитки.")

# --- ГОЛОС ---

@dp.message(F.voice)
async def handle_voice(message: types.Message, state: FSMContext):
    msg = await message.answer("📥 Скачиваю и расшифровываю...")
    file = await bot.get_file(message.voice.file_id)
    ogg_path = os.path.join(TEMP_DIR, f"{message.voice.file_id}.ogg")
    await bot.download_file(file.file_path, ogg_path)
    raw_text = await transcribe_voice(ogg_path)
    os.remove(ogg_path)

    user_data = await state.get_data()
    if user_data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        await msg.edit_text(f"📝 **Сырая расшифровка:**\n\n{raw_text}", parse_mode="Markdown")
        return

    await msg.edit_text("✍️ Привожу текст в порядок...")
    prompts = load_prompts()
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])
    await state.update_data(last_text=text)
    await msg.edit_text(f"📝 **Расшифровка:**\n\n{text}\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())

@dp.message(F.video_note)
async def handle_video_note(message: types.Message, state: FSMContext):
    msg = await message.answer("📥 Скачиваю и расшифровываю...")
    file = await bot.get_file(message.video_note.file_id)
    mp4_path = os.path.join(TEMP_DIR, f"{message.video_note.file_id}.mp4")
    await bot.download_file(file.file_path, mp4_path)
    raw_text = await transcribe_voice(mp4_path)
    os.remove(mp4_path)

    user_data = await state.get_data()
    if user_data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        await msg.edit_text(f"📝 **Сырая расшифровка:**\n\n{raw_text}", parse_mode="Markdown")
        return

    await msg.edit_text("✍️ Привожу текст в порядок...")
    prompts = load_prompts()
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])
    await state.update_data(last_text=text)
    await msg.edit_text(f"📝 **Расшифровка:**\n\n{text}\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())

@dp.message(F.text, StateFilter(None))
async def handle_text(message: types.Message, state: FSMContext):
    await state.update_data(last_text=message.text)
    await message.answer("Выберите действие:", reply_markup=get_main_menu())

# --- ОБРАБОТКА КНОПОК ---

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data.startswith("ai_"))
async def process_ai_action(callback: types.CallbackQuery, state: FSMContext):
    prompt_id = callback.data.split("_", 1)[1]
    user_data = await state.get_data()
    text = user_data.get("last_text")

    prompts = load_prompts()
    button = find_button(prompts, prompt_id)

    if not button:
        await callback.answer("Кнопка не найдена.")
        return

    btn_type = button.get("type", "action")

    # ПОДМЕНЮ
    if btn_type == "submenu":
        await callback.message.edit_reply_markup(reply_markup=get_submenu(prompt_id))
        await callback.answer()
        return

    # ФЛОУ
    if btn_type == "flow":
        flow = button.get("flow")
        if flow == "translation":
            await callback.message.answer("На какой язык перевести?\n\nВведи одно слово:")
            await state.set_state(BotStates.waiting_for_language)
        elif flow == "meeting":
            await callback.message.answer("📎 Загрузи файл встречи (.txt или .json):")
            await state.set_state(BotStates.waiting_for_meeting_file)
        await callback.answer()
        return

    # ACTION — стандартная обработка
    if not text:
        await callback.answer("Текст не найден. Пришлите сообщение заново.")
        return

    await callback.message.answer("🤖 Думаю...")
    result = await get_ai_response(text, button['prompt'])
    await state.update_data(last_text=result)
    await callback.message.answer(f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())
    await callback.answer()

# --- ФЛОУ ПЕРЕВОДА ---

@dp.message(BotStates.waiting_for_language)
async def handle_language_input(message: types.Message, state: FSMContext):
    lang_input = message.text.strip()
    if len(lang_input.split()) > 1:
        await message.answer("Пожалуйста, введи только одно слово:")
        return
    user_data = await state.get_data()
    text = user_data.get("last_text")
    await state.clear()
    msg = await message.answer("🤖 Перевожу...")
    system_prompt = (
        f"Тебе передано слово: «{lang_input}»\n\n"
        "Определи: это название языка? Если НЕ язык — ответь строго:\n"
        "❌ Не могу определить язык. Попробуй ещё раз.\n\n"
        "Если язык — переведи следующий текст. Верни только перевод.\n\nТекст:\n"
    )
    result = await get_ai_response(text, system_prompt)
    await msg.edit_text("✅ Готово")
    await message.answer(f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())
    await state.update_data(last_text=result)

# --- ФЛОУ БРИФ ВСТРЕЧИ ---

@dp.message(BotStates.waiting_for_meeting_file, F.document)
async def handle_meeting_file(message: types.Message, state: FSMContext):
    fname = message.document.file_name or ""
    if not fname.endswith((".txt", ".json")):
        await message.answer("Нужен .txt или .json файл:")
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
    prompts = load_prompts()
    result = await get_ai_response(raw[:15000], prompts["meeting_brief"]["prompt"])
    await state.update_data(last_text=result)
    await msg.edit_text(f"✅ **Бриф:**\n\n{result}\n\nЧто сделать с текстом?", parse_mode="Markdown", reply_markup=get_main_menu())

# ADD_PROMPT_FEATURE:
# @dp.callback_query(F.data == "add_new_prompt")
# async def add_prompt_start(callback, state): ...
# @dp.message(BotStates.waiting_for_name)
# async def add_prompt_name(message, state): ...
# @dp.message(BotStates.waiting_for_content)
# async def add_prompt_finish(message, state): ...

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())