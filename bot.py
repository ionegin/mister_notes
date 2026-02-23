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
from core.keyboards import get_main_menu, get_submenu, get_result_menu
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

START_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/start")]],
    resize_keyboard=True
)

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
    "📖 <b>Команды:</b>\n\n"
    "/start — приветствие\n"
    "/help — эта справка\n"
    "/rawvoice — следующая голосовуха вернётся сырой (без ИИ-вычитки)\n\n"
    "<b>Как пользоваться:</b>\n"
    "• Пришли текст → выбери действие из меню\n"
    "• Пришли голосовое или кругляшок → расшифровка → меню\n"
    "• Несколько голосовых/кружочков подряд — объединятся автоматически\n\n"
    "<b>Лимиты:</b>\n"
    "• Голос / видео — до 10 минут\n"
    "• Текст — до 3000 символов (~1.5 страницы А4)"
)

ADMIN_ID = 250656533

MAX_VOICE_DURATION = 600
MAX_TEXT_LENGTH = 4000

user_requests: dict = {}
pending_voices: dict = {}
voice_lock = asyncio.Lock()

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

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# --- СТАРТ / HELP ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    try:
        with open("data/users.json", "r+", encoding="utf-8") as f:
            users = json.load(f)
            if user_id not in users:
                users.append(user_id)
                f.seek(0)
                f.truncate()
                json.dump(users, f)
    except Exception:
        pass
    await message.answer(WELCOME_TEXT, reply_markup=START_KB)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")

@dp.message(Command("rawvoice"))
async def cmd_rawvoice(message: types.Message, state: FSMContext):
    await state.update_data(raw_mode=True)
    await message.answer("Окей, следующая голосовуха вернётся без вычитки.")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Напиши текст после команды:\n/broadcast Привет всем!")
        return
    with open("data/users.json", "r", encoding="utf-8") as f:
        users = json.load(f)
    ok, fail = 0, 0
    for uid in users:
        try:
            await bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
    await message.answer(f"✅ Отправлено: {ok}\n❌ Не доставлено: {fail}")

# --- СКЛЕЙКА ГОЛОСОВЫХ ---

async def transcribe_and_cleanup(file_path: str, prompts: dict) -> str:
    raw_text = await transcribe_voice(file_path)
    text = await get_ai_response(raw_text, prompts["transcription_cleanup"])
    return text

async def flush_voice_queue(user_id: int, state: FSMContext):
    await asyncio.sleep(4.0)
    entry = pending_voices.pop(user_id, None)
    if not entry:
        return

    file_ids = entry["file_ids"]
    status_msg = entry["status_msg"]
    prompts = load_prompts()

    # ЭТАП 1: параллельное скачивание всех файлов (быстро, не тратит API-лимиты)
    async def download_one(file_id, ext):
        path = os.path.join(TEMP_DIR, f"{file_id}.{ext}")
        try:
            tg_file = await bot.get_file(file_id)
            await bot.download_file(tg_file.file_path, path)
            return path
        except Exception:
            logging.error(f"Download failed for {file_id}")
            return None

    paths = await asyncio.gather(*[download_one(fid, ext) for fid, ext in file_ids])

    # ЭТАП 2: последовательная обработка через Groq (с паузами между запросами)
    texts = []
    for path in paths:
        if path is None:
            texts.append("[ошибка скачивания]")
            continue
        try:
            result = await transcribe_and_cleanup(path, prompts)
            texts.append(result)
        except Exception:
            texts.append("[ошибка расшифровки]")
        finally:
            if os.path.exists(path):
                os.remove(path)
        await asyncio.sleep(1.5)  # пауза между файлами, чтобы не триггерить RPM

    combined = "\n\n---\n\n".join(texts)
    await state.update_data(last_text=combined)
    count = len(texts)
    label = f"📝 <b>Расшифровка ({count} сообщений):</b>\n\n" if count > 1 else "📝 <b>Расшифровка:</b>\n\n"
    await status_msg.edit_text(
        f"{label}{escape_html(combined)}\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )

@dp.message(F.voice)
async def handle_voice(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer(ERROR_MESSAGES["rate_limit"])
        return
    if message.voice.duration > MAX_VOICE_DURATION:
        await message.answer("⏱ Голосовое слишком длинное. Максимум — 10 минут.")
        return

    user_id = message.from_user.id
    file_id = message.voice.file_id

    user_data = await state.get_data()
    if user_data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        try:
            tg_file = await bot.get_file(file_id)
            ogg_path = os.path.join(TEMP_DIR, f"{file_id}.ogg")
            await bot.download_file(tg_file.file_path, ogg_path)
            raw_text = await transcribe_voice(ogg_path)
        except Exception:
            await message.answer(ERROR_MESSAGES["unknown_error"])
            return
        finally:
            if os.path.exists(ogg_path):
                os.remove(ogg_path)
        await message.answer(f"📝 <b>Сырая расшифровка:</b>\n\n{escape_html(raw_text)}", parse_mode="HTML")
        return

    async with voice_lock:
        if user_id in pending_voices:
            entry = pending_voices[user_id]
            entry["task"].cancel()
            entry["file_ids"].append((file_id, "ogg"))
        else:
            status_msg = await message.answer("📥 Расшифровываю...")
            pending_voices[user_id] = {"file_ids": [(file_id, "ogg")], "task": None, "status_msg": status_msg}

        task = asyncio.create_task(flush_voice_queue(user_id, state))
        pending_voices[user_id]["task"] = task

@dp.message(F.video_note)
async def handle_video_note(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer(ERROR_MESSAGES["rate_limit"])
        return
    if message.video_note.duration > MAX_VOICE_DURATION:
        await message.answer("⏱ Видео слишком длинное. Максимум — 10 минут.")
        return

    user_id = message.from_user.id
    file_id = message.video_note.file_id

    user_data = await state.get_data()
    if user_data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        try:
            tg_file = await bot.get_file(file_id)
            mp4_path = os.path.join(TEMP_DIR, f"{file_id}.mp4")
            await bot.download_file(tg_file.file_path, mp4_path)
            raw_text = await transcribe_voice(mp4_path)
        except Exception:
            await message.answer(ERROR_MESSAGES["unknown_error"])
            return
        finally:
            if os.path.exists(mp4_path):
                os.remove(mp4_path)
        await message.answer(f"📝 <b>Сырая расшифровка:</b>\n\n{escape_html(raw_text)}", parse_mode="HTML")
        return

    async with voice_lock:
        if user_id in pending_voices:
            entry = pending_voices[user_id]
            entry["task"].cancel()
            entry["file_ids"].append((file_id, "mp4"))
        else:
            status_msg = await message.answer("📥 Расшифровываю...")
            pending_voices[user_id] = {"file_ids": [(file_id, "mp4")], "task": None, "status_msg": status_msg}

        task = asyncio.create_task(flush_voice_queue(user_id, state))
        pending_voices[user_id]["task"] = task

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
    except Exception:
        await callback.message.answer(ERROR_MESSAGES["tts_error"])
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
    except Exception:
        await callback.message.answer(ERROR_MESSAGES["unknown_error"])
        await callback.answer()
        return

    if prompt_id in ("summarize", "summarize_harder"):
        result, can_compress = parse_can_compress(raw_result)
    else:
        result = raw_result
        can_compress = False

    await state.update_data(last_text=result)
    await callback.message.answer(
        f"✅ <b>Готово:</b>\n\n{escape_html(result)}\n\nЧто сделать с текстом?",
        parse_mode="HTML",
        reply_markup=get_result_menu(can_compress)
    )
    await callback.answer()

# --- FSM ХЕНДЛЕРЫ ---

@dp.message(BotStates.waiting_for_language)
async def handle_language_input(message: types.Message, state: FSMContext):
    lang_input = message.text.strip()
    if len(lang_input.split()) > 1:
        await message.answer("Пожалуйста, введи только одно слово:")
        return
    user_data = await state.get_data()
    text = user_data.get("last_text")
    await state.set_state(None)
    msg = await message.answer("🤖 Перевожу...")
    system_prompt = (
        f"Тебе передано слово: «{lang_input}»\n\n"
        "Определи: это название языка? Если НЕ язык — ответь строго:\n"
        "❌ Не могу определить язык. Попробуй ещё раз.\n\n"
        "Если язык — переведи следующий текст. Верни только перевод.\n\nТекст:\n"
    )
    try:
        result = await get_ai_response(text, system_prompt)
    except Exception:
        await msg.edit_text(ERROR_MESSAGES["unknown_error"])
        return
    await state.update_data(last_text=result)
    await msg.edit_text(
        f"✅ <b>Готово:</b>\n\n{escape_html(result)}\n\nЧто сделать с текстом?",
        parse_mode="HTML",
        reply_markup=get_result_menu()
    )

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
    except Exception:
        await msg.edit_text(ERROR_MESSAGES["unknown_error"])
        return
    await state.update_data(last_text=result)
    await msg.edit_text(
        f"✅ <b>Бриф:</b>\n\n{escape_html(result)}\n\nЧто сделать с текстом?",
        parse_mode="HTML",
        reply_markup=get_result_menu()
    )

# --- ТЕКСТ (всегда последний) ---

@dp.message(F.text)
async def handle_text(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer(ERROR_MESSAGES["rate_limit"])
        return
    if len(message.text) > MAX_TEXT_LENGTH:
        await message.answer(f"📄 Текст слишком длинный. Максимум — {MAX_TEXT_LENGTH} символов.")
        return
    await state.update_data(last_text=message.text)
    await message.answer("Выберите действие:", reply_markup=get_main_menu())

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())