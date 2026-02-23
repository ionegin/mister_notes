import json
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

# Кнопки которые показываются в первом меню (после получения текста/голосового)
MAIN_MENU_IDS = ["summarize", "translate", "change_style", "meeting_brief"]

# Кнопки которые показываются в меню результата (после любой обработки)
RESULT_MENU_IDS = ["translate", "change_style", "meeting_brief"]


def get_main_menu():
    """Первое меню — после получения текста или голосового"""
    builder = InlineKeyboardBuilder()
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    for p_id in MAIN_MENU_IDS:
        data = prompts.get(p_id)
        if data and isinstance(data, dict) and "name" in data:
            builder.row(InlineKeyboardButton(text=data["name"], callback_data=f"ai_{p_id}"))
    return builder.as_markup()


def get_result_menu(can_compress: bool = False):
    """Второе меню — после любой обработки. Опционально добавляет 'Сжать сильнее'"""
    builder = InlineKeyboardBuilder()
    if can_compress:
        builder.row(InlineKeyboardButton(text="⚡️ Сжать сильнее", callback_data="ai_summarize_harder"))
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    for p_id in RESULT_MENU_IDS:
        data = prompts.get(p_id)
        if data and isinstance(data, dict) and "name" in data:
            builder.row(InlineKeyboardButton(text=data["name"], callback_data=f"ai_{p_id}"))
    return builder.as_markup()


def get_submenu(parent_id: str):
    """Строит меню из children указанного блока"""
    builder = InlineKeyboardBuilder()
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    children = prompts.get(parent_id, {}).get("children", {})
    for child_id, data in children.items():
        builder.row(InlineKeyboardButton(text=data["name"], callback_data=f"ai_{child_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    return builder.as_markup()