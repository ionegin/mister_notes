import asyncio
import json
import logging
import os
import time
from io import BytesIO
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from config import BOT_TOKEN, TEMP_DIR
from core.ai_client import transcribe_voice, get_ai_response, text_to_speech
from core.keyboards import get_main_menu, get_submenu

logging.basicConfig(level=logging.INFO)

WELCOME_TEXT = (
    "Привет! Я помогу обработать текст или голос.\n\n"
    "Умею: сократить, перевести на любой язык, изменить стиль.\n"
    "Пришли текст, голосовуху или кругляшок — и увидишь что можно сделать.\n\n"
    "Команды:\n"
    "/help — список команд\n"
    "/rawvoice — следующая голосовуха без вычитки ИИ"
)

HELP_TEXT = (
    "📖 **Команды:**\n\n"
    "/start — приветствие\n"
    "/help — эта справка\n"
    "/rawvoice — следующая голосовуха вернётся сырой (без ИИ-вычитки)\n\n"
    "**Как пользоваться:**\n"
    "• Пришли текст → выбери действие из меню\n"
    "• Пришли голосовое или кругляшок → расшифровка → меню\n"
    "• Несколько голосовых/кружочков подряд — объединятся автоматически\n\n"
    "**Лимиты:**\n"
    "• Голос / видео — до 10 минут\n"
    "• Текст — до 3000 символов (~1.5 страницы А4)"
)

MAX_VOICE_DURATION = 600
MAX_TEXT_LENGTH = 3000

# Rate limiting
user_requests: dict = {}

# Таймер объединения голосовых {user_id: ([paths], task, status_msg)}
pending_voices: dict = {}
def check_rate_limit(user_id: int, max_requests: int = 10, window: int = 60) -> bool:
    now = time.time()
    timestamps = user_requests.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < window]
    if len(timestamps) >= max_requests:
        return False
    timestamps.append(now)
    user_requests[user_id] = timestamps
    return True

ERROR_MESSAGES = {
    "rate_limit": "⏳ Слишком много запросов. Подожди минуту и попробуй снова.",
    "connection_error": "🔌 Нет связи с сервером. Попробуй через несколько секунд.",
    "tts_error": "🔇 Не удалось озвучить текст. Попробуй позже.",
    "unknown_error": "❌ Что-то пошло не так. Попробуй ещё раз.",
}

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
    if target_id in prompts:
        return prompts[target_id]
    for data in prompts.values():
        if isinstance(data, dict) and "children" in data:
            if target_id in data["children"]:
                return data["children"][target_id]
    return None

def parse_can_compress(result: str) -> tuple[str, bool]:
    lines = result.strip().split("\n")
    can_compress = False
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and "can_compress" in stripped:
            try:
                data = json.loads(stripped)
                can_compress = data.get("can_compress", False)
            except Exception:
                pass
        else:
            clean_lines.append(line)
    return "\n".join(clean_lines).strip(), can_compress

def get_result_menu(can_compress: bool = False):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔊 Озвучить", callback_data="tts_result"))
    if can_compress:
        builder.row(InlineKeyboardButton(text="⚡️ Сжать сильнее", callback_data="ai_summarize_harder"))
    for row in get_main_menu().inline_keyboard:
        builder.row(*row)
    return builder.as_markup()

# --- СТАРТ / HELP ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(WELCOME_TEXT)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="Markdown")

@dp.message(Command("rawvoice"))
async def cmd_rawvoice(message: types.Message, state: FSMContext):
    await state.update_data(raw_mode=True)
    await message.answer("Окей, следующая голосовуха вернётся без вычитки.")

# --- ГОЛОС С ОБЪЕДИНЕНИЕМ ---

async def transcribe_and_cleanup(file_path: str, prompts: dict) -> str:
    raw_text = await transcribe_voice(file_path)
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])
    return text

async def flush_voice_queue(user_id: int, state: FSMContext, last_message: types.Message):
    await asyncio.sleep(3.0)
    entry = pending_voices.pop(user_id, None)
    if not entry:
        return
    file_paths, _, s_msg = entry
    prompts = load_prompts()
    texts = []
    for path in file_paths:
        try:
            text = await transcribe_and_cleanup(path, prompts)
            texts.append(text)
        except Exception as e:
            texts.append(f"[ошибка: {ERROR_MESSAGES.get(str(e), '?')}]")
        finally:
            if os.path.exists(path):
                os.remove(path)
    combined = "\n\n---\n\n".join(texts)
    await state.update_data(last_text=combined)
    count = len(texts)
    label = f"📝 **Расшифровка ({count} сообщений):**\n\n" if count > 1 else "📝 **Расшифровка:**\n\n"
    await s_msg.edit_text(f"{label}{combined}\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_main_menu())

@dp.message(F.voice)
async def handle_voice(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer(ERROR_MESSAGES["rate_limit"])
        return
    if message.voice.duration > MAX_VOICE_DURATION:
        await message.answer("⏱ Голосовое слишком длинное. Максимум — 10 минут.")
        return

    user_id = message.from_user.id
    file = await bot.get_file(message.voice.file_id)
    ogg_path = os.path.join(TEMP_DIR, f"{message.voice.file_id}.ogg")
    await bot.download_file(file.file_path, ogg_path)

    user_data = await state.get_data()
    if user_data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        try:
            raw_text = await transcribe_voice(ogg_path)
        except Exception as e:
            await message.answer(ERROR_MESSAGES.get(str(e), ERROR_MESSAGES["unknown_error"]))
            return
        finally:
            if os.path.exists(ogg_path):
                os.remove(ogg_path)
        await message.answer(f"📝 **Сырая расшифровка:**\n\n{raw_text}", parse_mode="Markdown")
        return

    if user_id in pending_voices:
        paths, task, status_msg = pending_voices[user_id]
        task.cancel()
        paths.append(ogg_path)
        pending_voices[user_id] = (paths, None, status_msg)
    else:
        status_msg = await message.answer("📥 Расшифровываю...")
        paths = [ogg_path]
        pending_voices[user_id] = (paths, None, status_msg)

    task = asyncio.create_task(flush_voice_queue(user_id, state, message))
    paths, _, s_msg = pending_voices[user_id]
    pending_voices[user_id] = (paths, task, s_msg)

@dp.message(F.video_note)
async def handle_video_note(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer(ERROR_MESSAGES["rate_limit"])
        return
    if message.video_note.duration > MAX_VOICE_DURATION:
        await message.answer("⏱ Видео слишком длинное. Максимум — 10 минут.")
        return

    user_id = message.from_user.id
    file = await bot.get_file(message.video_note.file_id)
    mp4_path = os.path.join(TEMP_DIR, f"{message.video_note.file_id}.mp4")
    await bot.download_file(file.file_path, mp4_path)

    user_data = await state.get_data()
    if user_data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        try:
            raw_text = await transcribe_voice(mp4_path)
        except Exception as e:
            await message.answer(ERROR_MESSAGES.get(str(e), ERROR_MESSAGES["unknown_error"]))
            return
        finally:
            if os.path.exists(mp4_path):
                os.remove(mp4_path)
        await message.answer(f"📝 **Сырая расшифровка:**\n\n{raw_text}", parse_mode="Markdown")
        return

    if user_id in pending_voices:
        paths, task, status_msg = pending_voices[user_id]
        task.cancel()
        paths.append(mp4_path)
        pending_voices[user_id] = (paths, None, status_msg)
    else:
        status_msg = await message.answer("📥 Расшифровываю...")
        paths = [mp4_path]
        pending_voices[user_id] = (paths, None, status_msg)

    task = asyncio.create_task(flush_voice_queue(user_id, state, message))
    paths, _, s_msg = pending_voices[user_id]
    pending_voices[user_id] = (paths, task, s_msg)

@dp.message(F.text, StateFilter(None))
async def handle_text(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer(ERROR_MESSAGES["rate_limit"])
        return
    if len(message.text) > MAX_TEXT_LENGTH:
        await message.answer(f"📄 Текст слишком длинный. Максимум — {MAX_TEXT_LENGTH} символов.")
        return
    await state.update_data(last_text=message.text)
    await message.answer("Выберите действие:", reply_markup=get_main_menu())

# --- КНОПКИ ---

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "tts_result")
async def tts_result(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    text = user_data.get("last_text", "")
    if not text:
        await callback.answer("Текст не найден.")
        return
    await callback.message.answer("🔊 Озвучиваю...")
    try:
        audio_bytes = await text_to_speech(text[:2500])
        audio_file = BytesIO(audio_bytes)
        audio_file.name = "result.mp3"
        await callback.message.answer_voice(audio_file)
    except Exception as e:
        await callback.message.answer(ERROR_MESSAGES.get(str(e), ERROR_MESSAGES["tts_error"]))
    await callback.answer()

@dp.callback_query(F.data.startswith("ai_"))
async def process_ai_action(callback: types.CallbackQuery, state: FSMContext):
    if not check_rate_limit(callback.from_user.id):
        await callback.answer(ERROR_MESSAGES["rate_limit"], show_alert=True)
        return

    prompt_id = callback.data.split("_", 1)[1]
    user_data = await state.get_data()
    text = user_data.get("last_text")

    prompts = load_prompts()
    button = find_button(prompts, prompt_id)

    if not button:
        await callback.answer("Кнопка не найдена.")
        return

    btn_type = button.get("type", "action")

    if btn_type == "submenu":
        await callback.message.edit_reply_markup(reply_markup=get_submenu(prompt_id))
        await callback.answer()
        return

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

    if not text:
        await callback.answer("Текст не найден. Пришлите сообщение заново.")
        return

    await callback.message.answer("🤖 Думаю...")
    try:
        raw_result = await get_ai_response(text, button['prompt'])
    except Exception as e:
        await callback.message.answer(ERROR_MESSAGES.get(str(e), ERROR_MESSAGES["unknown_error"]))
        await callback.answer()
        return

    if prompt_id == "summarize":
        result, can_compress = parse_can_compress(raw_result)
    else:
        result = raw_result
        can_compress = False
    await state.update_data(last_text=result)
    await callback.message.answer(
        f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?",
        parse_mode="Markdown",
        reply_markup=get_result_menu(can_compress)
    )
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
    try:
        result = await get_ai_response(text, system_prompt)
    except Exception as e:
        await msg.edit_text(ERROR_MESSAGES.get(str(e), ERROR_MESSAGES["unknown_error"]))
        return
    await msg.edit_text("✅ Готово")
    await message.answer(
        f"✅ **Готово:**\n\n{result}\n\nЧто сделать с текстом?",
        parse_mode="Markdown",
        reply_markup=get_result_menu()
    )
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
    try:
        prompts = load_prompts()
        result = await get_ai_response(raw[:15000], prompts["meeting_brief"]["prompt"])
    except Exception as e:
        await msg.edit_text(ERROR_MESSAGES.get(str(e), ERROR_MESSAGES["unknown_error"]))
        return
    await state.update_data(last_text=result)
    await msg.edit_text(
        f"✅ **Бриф:**\n\n{result}\n\nЧто сделать с текстом?",
        parse_mode="Markdown",
        reply_markup=get_result_menu()
    )

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
