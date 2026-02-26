# ---------- Кнопки ----------
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_resource_type_keyboard(ResourceTypeCallback):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="VK", callback_data=ResourceTypeCallback(type_="vk").pack()),
            InlineKeyboardButton(text="Website", callback_data=ResourceTypeCallback(type_="website").pack()),
            InlineKeyboardButton(text="Telegram", callback_data=ResourceTypeCallback(type_="telegram").pack())
        ]
    ])


def get_resources_pagination_keyboard(ResourcePageCallback,page: int, total_pages: int, mode: str):
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=ResourcePageCallback(page=page-1, mode=mode).pack()))
    if page < total_pages:
        buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=ResourcePageCallback(page=page+1, mode=mode).pack()))

    return InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None