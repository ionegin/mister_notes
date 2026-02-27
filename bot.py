import asyncio
import json
import logging
import os
import time
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from config import BOT_TOKEN, TEMP_DIR
from core.ai_client import transcribe_voice, get_ai_response
from core.keyboards import get_main_menu, get_submenu, get_result_menu

START_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/start")]],
    resize_keyboard=True
)

logging.basicConfig(level=logging.INFO)


WELCOME_TEXT = (
    "Это бот для обработки голосовых, кружочков и текста. Панацея от любителей накидать голосовых сообщений!\n\n"
    "— Обрабатывает до 5 голосовых, кружочков или текстов за раз и склеивает их в одно сообщение\n"
    "— Кристаллизует информацию до ключевых идей — с приоритетом по важности\n"
    "— Сжимает ещё сильнее если нужен совсем короткий результат\n"
    "— Переводит на любой язык\n"

    "👉 Нажмите /start, пришлите боту голосовых и кружочков — дождитесь расшифровки и нажмите «Сократить». Сами всё поймёте 😌\n\n"
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
    "• Несколько голосовых/кружочков/текстов подряд — объединятся автоматически\n\n"
    "<b>Лимиты:</b>\n"
    "• Голос / видео — до 10 минут\n"
    "• Текст — до 4000 символов на сообщение, 8000 суммарно"
)

ADMIN_ID = 250656533

MAX_VOICE_DURATION = 600
MAX_TEXT_LENGTH = 4000
MAX_COMBINED_LENGTH = 8000
QUEUE_WAIT_SECONDS = 3.0

# --- КЭШИРОВАНИЕ ПРОМТОВ ---

def load_prompts():
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        return json.load(f)

PROMPTS = load_prompts()

# --- СОСТОЯНИЯ ---

class BotStates(StatesGroup):
    waiting_for_language = State()

# --- ИНИЦИАЛИЗАЦИЯ ---

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_requests: dict = {}
pending_messages: dict = {}
user_locks: dict = {}
processing_users: set = set()

def get_user_lock(user_id: int) -> asyncio.Lock:
    """Возвращает персональный Lock для пользователя."""
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

def check_rate_limit(user_id: int, max_requests: int = 10, window: int = 60) -> bool:
    now = time.time()
    timestamps = user_requests.get(user_id, [])
    timestamps = [ts for ts in timestamps if now - ts < window]
    user_requests[user_id] = timestamps
    if len(timestamps) >= max_requests:
        return False
    user_requests[user_id].append(now)
    return True

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=START_KB)
    # Сохраняем пользователя в JSON
    u_file = "data/users.json"
    if not os.path.exists(u_file):
        with open(u_file, "w") as f:
            json.dump([], f)
    with open(u_file, "r") as f:
        users = json.load(f)
    if message.from_user.id not in users:
        users.append(message.from_user.id)
        with open(u_file, "w") as f:
            json.dump(users, f)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")

@dp.message(Command("rawvoice"))
async def cmd_raw(message: types.Message, state: FSMContext):
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

# --- УНИВЕРСАЛЬНАЯ ОЧЕРЕДЬ (текст + голос) ---

async def transcribe_and_cleanup(file_path: str) -> str:
    raw_text = await transcribe_voice(file_path)
    text = await get_ai_response(raw_text, PROMPTS["transcription_cleanup"])
    return text

async def download_voice_file(file_id: str, ext: str) -> str | None:
    """Скачивает голосовой файл в фоне. Возвращает путь или None."""
    path = os.path.join(TEMP_DIR, f"{file_id}.{ext}")
    try:
        tg_file = await bot.get_file(file_id)
        await bot.download_file(tg_file.file_path, path)
        return path
    except Exception:
        logging.error(f"Download failed for {file_id}")
        return None

async def flush_queue(user_id: int, state: FSMContext):
    """Ждёт паузу, затем обрабатывает все накопленные сообщения."""
    await asyncio.sleep(QUEUE_WAIT_SECONDS)
    entry = pending_messages.pop(user_id, None)
    if not entry:
        return

    items = entry["items"]
    status_msg = entry["status_msg"]
    has_voice = any(item["type"] == "voice" for item in items)

    if has_voice:
        try:
            await status_msg.edit_text("📥 Расшифровываю...")
        except Exception:
            pass

    parts = []
    for item in items:
        if item["type"] == "text":
            parts.append(item["content"])
        elif item["type"] == "voice":
            # Дожидаемся предзагрузки (уже запущенной в add_to_queue)
            path = await item["download_task"]
            if path is None:
                parts.append("[ошибка скачивания]")
                continue
            try:
                result = await transcribe_and_cleanup(path)
                parts.append(result)
            except Exception:
                parts.append("[ошибка расшифровки]")
            finally:
                if os.path.exists(path):
                    os.remove(path)
            await asyncio.sleep(1.5)

    combined = "\n\n---\n\n".join(parts)
    if len(combined) > MAX_COMBINED_LENGTH:
        combined = combined[:MAX_COMBINED_LENGTH]

    await state.update_data(last_text=combined)

    count = len(parts)
    if has_voice and count > 1:
        label = f"📝 <b>Расшифровка ({count} сообщений):</b>\n\n"
    elif has_voice:
        label = "📝 <b>Расшифровка:</b>\n\n"
    elif count > 1:
        label = f"📝 <b>Текст ({count} сообщений):</b>\n\n"
    else:
        label = ""

    if has_voice or count > 1:
        display_text = escape_html(combined)
        full_msg = f"{label}{display_text}\n\nВыберите действие:"
        if len(full_msg) > 4000:
            truncated = escape_html(combined[:3500])
            full_msg = (
                f"{label}{truncated}\n\n"
                "⚠️ <i>Показана часть текста. Полный текст сохранён.</i>\n\n"
                "Выберите действие:"
            )
        try:
            await status_msg.edit_text(
                full_msg, parse_mode="HTML", reply_markup=get_main_menu(PROMPTS)
            )
        except Exception as e:
            logging.error(f"Failed to edit status message: {e}")
    else:
        try:
            await status_msg.edit_text(
                "Выберите действие:", reply_markup=get_main_menu(PROMPTS)
            )
        except Exception as e:
            logging.error(f"Failed to edit status message: {e}")

async def add_to_queue(user_id: int, item: dict, state: FSMContext, message: types.Message):
    """Добавляет элемент в очередь и (пере)запускает таймер.
    Голосовые файлы начинают скачиваться сразу (предзагрузка)."""
    # Для голосовых — запускаем скачивание немедленно
    if item["type"] == "voice":
        item["download_task"] = asyncio.create_task(
            download_voice_file(item["file_id"], item["ext"])
        )

    async with get_user_lock(user_id):
        if user_id in pending_messages:
            entry = pending_messages[user_id]
            entry["task"].cancel()
            entry["items"].append(item)
        else:
            status_msg = await message.answer("⏳ Принято, жду ещё сообщения...")
            pending_messages[user_id] = {
                "items": [item],
                "task": None,
                "status_msg": status_msg,
            }
        task = asyncio.create_task(flush_queue(user_id, state))
        pending_messages[user_id]["task"] = task

# --- ГОЛОСОВЫЕ ---

@dp.message(F.voice)
async def handle_voice(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer("⚠️ Слишком много запросов. Подождите минуту.")
        return

    if message.voice.duration > MAX_VOICE_DURATION:
        await message.answer(f"❌ Голосовое слишком длинное. Максимум {MAX_VOICE_DURATION // 60} минут.")
        return

    # Проверка режима raw_mode
    data = await state.get_data()
    if data.get("raw_mode"):
        await state.update_data(raw_mode=False)
        # Скачиваем и транскрибируем БЕЗ вычистки
        path = os.path.join(TEMP_DIR, f"{message.voice.file_id}.ogg")
        try:
            tg_file = await bot.get_file(message.voice.file_id)
            await bot.download_file(tg_file.file_path, path)
            text = await transcribe_voice(path)
            await message.reply(f"📝 <b>Raw:</b>\n\n{escape_html(text)}", parse_mode="HTML")
        except Exception:
            await message.answer("❌ Ошибка при обработке.")
        finally:
            if os.path.exists(path):
                os.remove(path)
        return

    await add_to_queue(
        message.from_user.id,
        {"type": "voice", "file_id": message.voice.file_id, "ext": "ogg"},
        state,
        message,
    )

@dp.message(F.video_note)
async def handle_video_note(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer("⚠️ Слишком много запросов. Подождите минуту.")
        return

    if message.video_note.duration > MAX_VOICE_DURATION:
        await message.answer(f"❌ Видео слишком длинное. Максимум {MAX_VOICE_DURATION // 60} минут.")
        return

    await add_to_queue(
        message.from_user.id,
        {"type": "voice", "file_id": message.video_note.file_id, "ext": "mp4"},
        state,
        message,
    )

# --- CALLBACKS (AI Действия) ---

@dp.callback_query(F.data.startswith("ai_"))
async def process_ai_action(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Защита от двойных нажатий
    if user_id in processing_users:
        await callback.answer("⏳ Уже обрабатываю...", show_alert=False)
        return
    
    processing_users.add(user_id)
    
    try:
        action_id = callback.data.replace("ai_", "")
        data = await state.get_data()
        text = data.get("last_text", "")

        if not text:
            await callback.answer("❌ Текст не найден.")
            return

        # Специальный случай для перевода — спрашиваем язык
        if action_id == "translate":
            await callback.message.answer("На какой язык перевести? (например: английский, немецкий, испанский)")
            await state.set_state(BotStates.waiting_for_language)
            await callback.answer()
            return

        # Специальный случай для подменю (Изменить стиль)
        if action_id == "change_style":
            await callback.message.edit_reply_markup(reply_markup=get_submenu(PROMPTS, "change_style"))
            await callback.answer()
            return

        # Обычное действие (Сократи, Официальный стиль и т.д.)
        # Ищем в prompts или в prompts['change_style']['children']
        prompt_data = PROMPTS.get(action_id)
        if not prompt_data:
            # Ищем в стилях
            prompt_data = PROMPTS.get("change_style", {}).get("children", {}).get(action_id)

        if not prompt_data:
            await callback.answer("❌ Неизвестное действие.")
            return

        await callback.answer("⚙️ Обрабатываю...")
        status_msg = await callback.message.answer("🤖 Секунду...")

        try:
            result = await get_ai_response(text, prompt_data["prompt"])
            
            # Проверяем наличие JSON в конце (для can_compress)
            can_compress = False
            if action_id == "summarize":
                if "{\"can_compress\": true}" in result:
                    can_compress = True
                    result = result.replace("{\"can_compress\": true}", "").strip()
                elif "{\"can_compress\": false}" in result:
                    result = result.replace("{\"can_compress\": false}", "").strip()

            await status_msg.delete()
            
            # Кодируем HTML
            safe_result = escape_html(result)
            
            # Итоговое сообщение
            await callback.message.answer(
                f"✨ <b>Результат ({prompt_data['name']}):</b>\n\n{safe_result}\n\nВыберите что еще сделать:",
                parse_mode="HTML",
                reply_markup=get_result_menu(PROMPTS, can_compress=can_compress)
            )
            # ОБНОВЛЯЕМ last_text только если это было не 'Сжать сильнее' (опционально)
            # Но по логике — лучше всегда иметь доступ к последнему результату
            await state.update_data(last_text=result)

        except Exception as e:
            logging.error(f"AI Error: {e}")
            await status_msg.edit_text("❌ Произошла ошибка при работе с ИИ.")
    finally:
        processing_users.discard(user_id)

@dp.callback_query(F.data == "back_to_main")
async def process_back(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=get_main_menu(PROMPTS))
    await callback.answer()

@dp.message(BotStates.waiting_for_language)
async def process_translation(message: types.Message, state: FSMContext):
    target_lang = message.text.strip()
    data = await state.get_data()
    text = data.get("last_text", "")
    
    await state.clear()
    await state.update_data(last_text=text)

    status_msg = await message.answer(f"🌐 Перевожу на {target_lang}...")
    
    prompt = f"Переведи текст строго на {target_lang}. Сохрани форматирование (если есть булиты — оставь их). Верни только перевод."
    
    try:
        result = await get_ai_response(text, prompt)
        await status_msg.delete()
        await message.answer(
            f"✨ <b>Перевод ({target_lang}):</b>\n\n{escape_html(result)}\n\nВыберите что еще сделать:",
            parse_mode="HTML",
            reply_markup=get_result_menu(PROMPTS)
        )
        await state.update_data(last_text=result)
    except Exception:
        await status_msg.edit_text("❌ Ошибка при переводе.")

# --- ТЕКСТОВЫЕ СООБЩЕНИЯ ---

@dp.message(F.text)
async def handle_text(message: types.Message, state: FSMContext):
    if not check_rate_limit(message.from_user.id):
        await message.answer("⚠️ Слишком много запросов. Подождите минуту.")
        return

    if len(message.text) > MAX_TEXT_LENGTH:
        await message.answer(
            f"📄 Текст слишком длинный. Максимум — {MAX_TEXT_LENGTH} символов."
        )
        return
    await add_to_queue(
        message.from_user.id,
        {"type": "text", "content": message.text},
        state,
        message,
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
