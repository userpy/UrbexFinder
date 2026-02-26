from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton(text="⬅ Назад", callback_data=f"page:{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton(text="Вперёд ➡", callback_data=f"page:{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
