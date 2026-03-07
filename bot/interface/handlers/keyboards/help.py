from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from loguru import logger
from infrastructure.db.PgDb import AsyncDatabase
from aiogram.types import Message
from interface.handlers.enums.places import Places
from interface.handlers.enums.help import Help
from interface.handlers.enums.resources import Resources

async def get_help_btn(message : Message, db: AsyncDatabase) -> ReplyKeyboardMarkup:
    user_role = await db.users.get_user_role(message.from_user.id)
    kb = ReplyKeyboardBuilder()
    kb.button(text=Places.ABANDONED_PLACES)
    kb.button(text=Help.COMMAND)
    kb.button(text=Resources.COMMAND)
    if user_role == 'admin':
        kb.button(text=Resources.COMMAND_ADD)
        kb.button(text=Resources.COMMAND_DELETE)
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)
