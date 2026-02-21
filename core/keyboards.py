import json
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

def get_main_menu():
    builder = InlineKeyboardBuilder()
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    for p_id, data in prompts.items():
        if isinstance(data, dict) and 'name' in data:
            builder.row(InlineKeyboardButton(text=data['name'], callback_data=f"ai_{p_id}"))
    # ADD_PROMPT_BUTTON: builder.row(InlineKeyboardButton(text="➕ Добавить промт", callback_data="add_new_prompt"))
    return builder.as_markup()

def get_submenu(parent_id: str):
    """Строит меню из children указанного блока"""
    builder = InlineKeyboardBuilder()
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    children = prompts.get(parent_id, {}).get("children", {})
    for child_id, data in children.items():
        builder.row(InlineKeyboardButton(text=data['name'], callback_data=f"ai_{child_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    return builder.as_markup()