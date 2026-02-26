from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State

async def keyboard_adapter_geo(items: list[str], state: State, is_state_location: str, not_state_location: str,
                               drop_search_button) -> ReplyKeyboardMarkup:
    data = await state.get_data()  # словарь со всеми сохранёнными данными
    location = data.get("location", None)
    search = data.get("search", None)
    if location:
        items = [x for x in items if not (isinstance(x, dict) and x.get("text") == is_state_location)]
    else:
        items = [x for x in items if x != not_state_location]
    if search is None:
        items = [x for x in items if x != drop_search_button]


    return make_row_keyboard(items)

def make_row_keyboard(items: list[str]) -> ReplyKeyboardMarkup:
    """
    Создаёт реплай-клавиатуру с кнопками в один ряд
    :param items: список текстов для кнопок
    :return: объект реплай-клавиатуры
    """
    row = [KeyboardButton(**item) if isinstance(item, dict) else KeyboardButton(text=item) for item in items]
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)
