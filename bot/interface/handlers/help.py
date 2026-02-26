from aiogram import Router
from aiogram.filters import Command
from aiogram import F
from aiogram.types import Message
from aiogram.enums import ParseMode
from interface.handlers.keyboards.help import get_help_btn
from infrastructure.services.template_renderer import TemplateRenderer
from aiogram.fsm.context import FSMContext
from infrastructure.db.PgDb import AsyncDatabase
from interface.handlers.enums.help import Help
from infrastructure.core.logger_config import setup_logger

logger = setup_logger()
router = Router()


router = Router()
@router.message(F.text == Help.COMMAND.value)
@router.message(Command("help"))
async def cmd_help(message: Message, db: AsyncDatabase, state: FSMContext):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}): {message.text}")
    await state.clear()
    renderer = TemplateRenderer()
    rendered_html = renderer.render(template_name="help.html", params={})
    await message.answer(
        rendered_html,
        parse_mode=ParseMode.HTML,
        reply_markup= await get_help_btn(message=message, db=db)
    )
