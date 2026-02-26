from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    Message,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from interface.handlers.keyboards.simple_row import keyboard_adapter_geo
from interface.handlers.keyboards.help import get_help_btn
from application.places_view import PlacesView
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from interface.handlers.enums.places import Places as PlacesText  # Enum с текстами кнопок
from infrastructure.core.logger_config import setup_logger
from infrastructure.core.error_handler import catch_handler_errors

logger = setup_logger()
PAGE_SIZE = 4

router = Router()


# FSM для состояния просмотра промышленных и заброшенных мест
class PlacesState(StatesGroup):
    industrial_and_abandoned_places = State()
    awaiting_social_input = State()


# Хэндлер команды / кнопки "Покинутые места"
@router.message(State(None), F.text == PlacesText.ABANDONED_PLACES.value)
@router.message(State(None), Command("industrial_and_abandoned_places"))
@catch_handler_errors()
async def cmd_industrial_and_abandoned_places(
    message: Message, state: FSMContext, db: AsyncDatabase
):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.text}")
    start_slice = 0
    await state.update_data(callback_data=f"num_back_{start_slice}")

    # Получаем срез всех мест
    await PlacesView.get_all_places_slice(
        message=message,
        page_offset=start_slice,
        message_answer=PlacesText.MESSAGE_ANSVER.value,
        db=db,
        state=state,
        line_count=PAGE_SIZE
    )

    # Устанавливаем FSM-состояние
    await state.set_state(PlacesState.industrial_and_abandoned_places)

    await message.answer(
        text=PlacesText.MESSAGE_VIEW_PLACES.value,
        reply_markup=await keyboard_adapter_geo(state=state, **PlacesText.BUTTONS_MAP.value),
        parse_mode=ParseMode.HTML
    )

# Обработка геолокации
@router.message(StateFilter(PlacesState.industrial_and_abandoned_places), F.location)
@catch_handler_errors()
async def location(
    message: Message, state: FSMContext, db: AsyncDatabase, elastic: ElasticPlacesIndexer
):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.location.latitude} {message.location.longitude}")
    await state.update_data(location={"latitude": message.location.latitude, "longitude": message.location.longitude})
    info = await state.get_data()
    search_info = info.get("search")
    # При установке геолокации начинаем с первой страницы.
    start_slice = 0
    await state.update_data(callback_data="num_back_0")

    if search_info:
        await PlacesView.search_places_slice(
            message=message,
            search=search_info,
            page_offset=start_slice,
            message_answer=PlacesText.MESSAGE_ANSVER.value,
            db=db,
            elastic=elastic,
            state=state,
            line_count=PAGE_SIZE
        )
    else:
        await PlacesView.get_all_places_slice(
            message=message,
            page_offset=start_slice,
            message_answer=PlacesText.MESSAGE_ANSVER.value,
            db=db,
            state=state,
            line_count=PAGE_SIZE
        )

    await message.answer(
        text=PlacesText.MESSAGE_LOCATION.value,
        reply_markup=await keyboard_adapter_geo(state=state, **PlacesText.BUTTONS_MAP.value),
        parse_mode=ParseMode.HTML
    )

# Отмена просмотра мест и выход в главное меню
@router.message(StateFilter(PlacesState.industrial_and_abandoned_places), F.text == PlacesText.CANCEL_PLACES_VIEW.value)
@catch_handler_errors()
async def cancel_view_places(message: Message, state: FSMContext, db: AsyncDatabase):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.text}")
    await message.answer(
        parse_mode=ParseMode.HTML,
        text=PlacesText.MESSAGE_CANCEL.value,
        reply_markup=await get_help_btn(message=message, db=db)
    )
    await state.clear()

# Отмена поиска
@router.message(StateFilter(PlacesState.industrial_and_abandoned_places), F.text == PlacesText.DROP_SEARCH_MODE.value)
@catch_handler_errors()
async def cancel_search(message: Message, state: FSMContext, db: AsyncDatabase):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.text}")
    start_slice = 0
    data = await state.get_data()
    data.pop("search", None)
    data.pop("places_ids", None)
    await state.set_data(data)

    await PlacesView.get_all_places_slice(
        message=message,
        page_offset=start_slice,
        message_answer=PlacesText.MESSAGE_ANSVER.value,
        db=db,
        state=state,
        line_count=PAGE_SIZE
    )

    await message.answer(
        parse_mode=ParseMode.HTML,
        text=PlacesText.MESSAGE_CANCEL_SEARCH,
        reply_markup=await keyboard_adapter_geo(state=state, **PlacesText.BUTTONS_MAP.value)
    )

# Отмена геолокации
@router.message(StateFilter(PlacesState.industrial_and_abandoned_places), F.text == PlacesText.DROP_LOCATION.value)
@catch_handler_errors()
async def cancel_location(
    message: Message, state: FSMContext, db: AsyncDatabase, elastic: ElasticPlacesIndexer
):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.text}")
    data = await state.get_data()
    data.pop("location", None)
    await state.set_data(data)

    info = await state.get_data()
    search_info = info.get("search")
    callback_data = info.get("callback_data")
    start_slice = int(callback_data.split("_")[2])

    if search_info:
        await PlacesView.search_places_slice(
            message=message,
            search=search_info,
            page_offset=start_slice,
            message_answer=PlacesText.MESSAGE_ANSVER.value,
            db=db,
            elastic=elastic,
            state=state,
            line_count=PAGE_SIZE
        )
    else:
        await PlacesView.get_all_places_slice(
            message=message,
            page_offset=start_slice,
            message_answer=PlacesText.MESSAGE_ANSVER.value,
            db=db,
            state=state,
            line_count=PAGE_SIZE
        )

    await message.answer(
        parse_mode=ParseMode.HTML,
        text=PlacesText.MESSAGE_CANCEL_LOCATION.value,
        reply_markup=await keyboard_adapter_geo(state=state, **PlacesText.BUTTONS_MAP.value)
    )

# Пагинация
@router.callback_query(F.data.startswith("num_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def view_places_pagination(callback: CallbackQuery, state: FSMContext, db: AsyncDatabase,
                                 elastic: ElasticPlacesIndexer):
    info = await state.get_data()
    search_info = info.get("search")
    action = callback.data.split("_")[1]
    start_slice = int(callback.data.split("_")[2])

    if action == "incr":
        start_slice += PAGE_SIZE
    elif action == "decr":
        start_slice -= PAGE_SIZE
    start_slice = max(0, start_slice)

    await state.update_data(callback_data=f"num_{action}_{start_slice}")

    if search_info:
        await PlacesView.search_places_slice(
            message=callback.message,
            search=search_info,
            page_offset=start_slice,
            message_answer=PlacesText.MESSAGE_ANSVER.value,
            db=db,
            elastic=elastic,
            state=state,
            line_count=PAGE_SIZE
        )
    else:
        await PlacesView.get_all_places_slice(
            message=callback.message,
            page_offset=start_slice,
            message_answer=PlacesText.MESSAGE_ANSVER.value,
            db=db,
            state=state,
            line_count=PAGE_SIZE
        )

    await callback.answer()

# Поиск по тексту
@router.message(StateFilter(PlacesState.industrial_and_abandoned_places),
                (F.text != PlacesText.CANCEL_PLACES_VIEW.value) &
                (F.text != PlacesText.DROP_SEARCH_MODE.value) &
                (~F.text.startswith("/place_")))
@catch_handler_errors()
async def search_places(message: Message, state: FSMContext, db: AsyncDatabase,
                                                 elastic: ElasticPlacesIndexer):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.text}")
    data = await state.get_data()
    data.pop("search", None)
    data.pop("places_ids", None)
    await state.set_data(data)
    await state.update_data(search=message.text, callback_data="num_back_0")

    await message.answer(
        parse_mode=ParseMode.HTML,
        text=f"🔎 {message.text}",
        reply_markup=await keyboard_adapter_geo(state=state, **PlacesText.BUTTONS_MAP.value)
    )

    await PlacesView.search_places_slice(
        message=message,
        search=message.text,
        page_offset=0,
        message_answer=PlacesText.MESSAGE_ANSVER.value,
        db=db,
        elastic=elastic,
        state=state,
        line_count=PAGE_SIZE
    )

# Детальное описание места
@router.message(StateFilter(PlacesState.industrial_and_abandoned_places),
                (F.text != PlacesText.CANCEL_PLACES_VIEW.value) &
                (F.text != PlacesText.DROP_SEARCH_MODE.value) &
                (F.text.startswith("/place_")))
@catch_handler_errors()
async def description_places(message: Message, state: FSMContext, db: AsyncDatabase):
    logger.info(f"[Handler] {message.from_user.id} ({message.from_user.username}):"
                f" {message.text}")
    place_id = message.text.split("_")[1]
    info = await state.get_data()
    callback_data = info.get("callback_data")
    search = info.get("search")
    start_slice = int(callback_data.split("_")[2])
    back_to_list = f"num_back_{start_slice}"

    await PlacesView.view_place_description(
        message=message,
        place_id=place_id,
        callback_data=back_to_list,
        db=db,
        search=search,
        user_id=message.from_user.id,
    )
