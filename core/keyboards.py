from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

# Кнопки первого меню (после получения текста/голосового)
MAIN_MENU_IDS = ["summarize", "translate", "change_style", "meeting_brief"]

# Кнопки меню результата (после любой обработки)
RESULT_MENU_IDS = ["summarize", "translate", "change_style", "meeting_brief"]


def get_main_menu(prompts: dict):
    """Первое меню — после получения текста или голосового"""
    builder = InlineKeyboardBuilder()
    for p_id in MAIN_MENU_IDS:
        data = prompts.get(p_id)
        if data and isinstance(data, dict) and "name" in data:
            builder.row(InlineKeyboardButton(text=data["name"], callback_data=f"ai_{p_id}"))
    return builder.as_markup()


def get_result_menu(prompts: dict, can_compress: bool = False):
    """Второе меню — после любой обработки. Опционально добавляет 'Сжать сильнее'"""
    builder = InlineKeyboardBuilder()
    if can_compress:
        builder.row(InlineKeyboardButton(text="⚡️ Сжать сильнее", callback_data="ai_summarize_harder"))
    for p_id in RESULT_MENU_IDS:
        data = prompts.get(p_id)
        if data and isinstance(data, dict) and "name" in data:
            builder.row(InlineKeyboardButton(text=data["name"], callback_data=f"ai_{p_id}"))
    return builder.as_markup()


def get_submenu(prompts: dict, parent_id: str):
    """Строит меню из children указанного блока"""
    builder = InlineKeyboardBuilder()
    children = prompts.get(parent_id, {}).get("children", {})
    for child_id, data in children.items():
        builder.row(InlineKeyboardButton(text=data["name"], callback_data=f"ai_{child_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    return builder.as_markup()