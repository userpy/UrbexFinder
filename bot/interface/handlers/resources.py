from aiogram import F
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters.callback_data import CallbackData

from infrastructure.db.PgDb import AsyncDatabase
from application.send_resources_page import ResourcePageHandler
from interface.handlers.keyboards.resources import get_resource_type_keyboard
from interface.handlers.keyboards.help import get_help_btn
from interface.handlers.keyboards.simple_row import make_row_keyboard
from interface.handlers.enums.resources import Resources
from infrastructure.core.logger_config import setup_logger

logger = setup_logger()
router = Router()

# ---------- FSM ----------
class AddResourceFSM(StatesGroup):
    # Шаги мастера добавления ресурса: имя -> тип -> url -> описание.
    name = State()
    type = State()
    url = State()
    description = State()

# ---------- CallbackData ----------
class ResourceTypeCallback(CallbackData, prefix="res_type"):
    # Тип ресурса, выбранный в inline-клавиатуре.
    type_: str

class ResourceDeleteCallback(CallbackData, prefix="res_del"):
    # ID ресурса, который нужно удалить.
    id: int

class ResourcePageCallback(CallbackData, prefix="res_page"):
    # Данные для пагинации и режима отображения списка ресурсов.
    page: int
    mode: str   # "view" или "delete"

# ---------- Хэндлеры ----------

handler = ResourcePageHandler(
    ResourcePageCallback=ResourcePageCallback,
    ResourceDeleteCallback=ResourceDeleteCallback
)

@router.message(F.text == Resources.COMMAND.value)
@router.message(Command("resources"))
async def resources_command(message: Message, db: AsyncDatabase):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}): {message.text}")
    # Всегда начинаем показ списка с первой страницы в режиме просмотра.
    await handler.send_resources_page(
                              target=message,
                              db=db,
                              page=1,
                              mode="view")

@router.message(StateFilter(AddResourceFSM.name, AddResourceFSM.type, AddResourceFSM.description, AddResourceFSM.url),
                F.text == Resources.CANCEL_RESOURCES_MODE.value)
async def cancel_resource_mode(message: Message, state: FSMContext, db: AsyncDatabase):
    await message.answer(
        text=Resources.MESSAGE_CANCEL_RESOURCE,
        parse_mode=ParseMode.HTML,
        reply_markup=await get_help_btn(message=message, db=db)
    )
    await state.clear()

@router.callback_query(ResourcePageCallback.filter())
async def resources_pagination(call: CallbackQuery, callback_data: ResourcePageCallback, db: AsyncDatabase):
    # Удаляем предыдущее сообщение, чтобы не копить старые страницы в чате.
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    await handler.send_resources_page(
                              target = call.message,
                              db=db,
                              page=callback_data.page,
                              mode=callback_data.mode)

@router.message(F.text == Resources.COMMAND_DELETE.value)
async def delete_resource_command(message: Message, db: AsyncDatabase):
    await handler.send_resources_page(
                              target=message,
                              db=db,
                              page=1,
                              mode="delete")

@router.callback_query(ResourceDeleteCallback.filter())
async def delete_resource(call: CallbackQuery, callback_data: ResourceDeleteCallback, db: AsyncDatabase):
    # Удаление выполняется по ID из callback_data.
    await db.resources.delete_resource(callback_data.id)
    await call.message.edit_text(Resources.MESSAGE_DELETE_RESOURCE)


# ---------- Добавление ресурса через FSM ----------
@router.message(F.text == Resources.COMMAND_ADD.value)
async def add_resource_start(message: Message, state: FSMContext):
    await state.set_state(AddResourceFSM.name)
    await message.answer(text=Resources.MESSAGE_ADD_RESOURCES_START, parse_mode=ParseMode.HTML ,
                         reply_markup=make_row_keyboard((Resources.CANCEL_RESOURCES_MODE,)),)


@router.message(AddResourceFSM.name)
async def add_resource_name(message: Message, state: FSMContext):
    # Сохраняем имя и переходим к выбору типа ресурса.
    await state.update_data(name=message.text.strip())
    await state.set_state(AddResourceFSM.type)
    await message.answer(Resources.MESSAGE_RESOURCE_NAME, reply_markup=get_resource_type_keyboard(ResourceTypeCallback))


@router.callback_query(ResourceTypeCallback.filter())
async def resource_type_chosen(call: CallbackQuery, callback_data: ResourceTypeCallback, state: FSMContext):
    # Тип приходит из callback, сохраняем и продолжаем сценарий.
    await state.update_data(type=callback_data.type_)
    await state.set_state(AddResourceFSM.url)
    await call.message.edit_text(f"Выбран тип: <b>{callback_data.type_}</b>\n\n🔗 Введите ссылку (url):", parse_mode=ParseMode.HTML)


@router.message(AddResourceFSM.url)
async def add_resource_url(message: Message, state: FSMContext):
    await state.update_data(url=message.text.strip())
    await state.set_state(AddResourceFSM.description)
    await message.answer(Resources.MESSAGE_ADD_RESOURCES_URL)


@router.message(AddResourceFSM.description)
async def add_resource_description(message: Message, state: FSMContext, db: AsyncDatabase):
    desc = message.text.strip()
    # "-" используем как маркер "описание отсутствует".
    if desc == "-":
        desc = None

    # Берем все данные, собранные на предыдущих шагах FSM, и сохраняем ресурс.
    data = await state.get_data()
    await db.resources.add_resource(
        name=data["name"],
        type_=data["type"],
        url=data["url"],
        description=desc
    )

    await message.answer(
        text=f"✅ Ресурс <b>{data['name']}</b> добавлен!",
        parse_mode=ParseMode.HTML,
        reply_markup=await get_help_btn(message=message, db=db)
    )
    await state.clear()
