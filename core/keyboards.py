import json
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

def get_main_menu():
    builder = InlineKeyboardBuilder()
    
    # Загружаем промты из JSON
    with open("data/prompts.json", "r", encoding="utf-8") as f:
        prompts = json.load(f)
    
    # Создаем кнопки на основе JSON
    for p_id, data in prompts.items():
        builder.row(InlineKeyboardButton(text=data['name'], callback_data=f"ai_{p_id}"))
    
    # Системная кнопка добавления нового промта
    builder.row(InlineKeyboardButton(text="➕ Добавить промт", callback_data="add_new_prompt"))
    
    return builder.as_markup()