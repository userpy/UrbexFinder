from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from interface.handlers.keyboards.help import get_help_btn
from infrastructure.services.template_renderer import TemplateRenderer
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.core.logger_config import setup_logger

logger = setup_logger()
router = Router()
@router.message(Command("start"))
async def cmd_start(message: Message, db: AsyncDatabase, state: FSMContext):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}): {message.text}")
    await state.clear()
    renderer = TemplateRenderer()
    rendered_html = renderer.render(template_name="start.html",
                                    params={"full_name": message.from_user.full_name})
    await message.answer(
        rendered_html,
        parse_mode=ParseMode.HTML,
        reply_markup= await get_help_btn(message=message, db=db)
    )
