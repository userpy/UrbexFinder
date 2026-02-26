from enum import Enum

class Places(Enum):
    ABANDONED_PLACES = "🏭 Покинутые места"
    CANCEL_PLACES_VIEW = "↩️ Просмотр мест"
    DROP_SEARCH_MODE = "❌ Поиск"
    MESSAGE_ANSVER = "Заброшенные и покинутые места, Cписок мест:"
    IS_LOCATION = "📍 Геопозиция"
    LOCATION = {
        "text": "📍 Геопозиция",
        "request_location": True
    }
    DROP_LOCATION = "❌ Геопозиция"
    BUTTONS_MAP = dict(
        items=(CANCEL_PLACES_VIEW, LOCATION, DROP_LOCATION, DROP_SEARCH_MODE),
                       is_state_location=IS_LOCATION,
                       not_state_location=DROP_LOCATION, drop_search_button=DROP_SEARCH_MODE)
    MESSAGE_LOCATION = \
        "🌐 Геопозиция сохранена! Теперь расстояние до мест будет отображаться относительно вашего положения."

    MESSAGE_CANCEL = "Режим просмотра мест <b>отменён</b>❎"
    MESSAGE_VIEW_PLACES = "🔙 Для отмены нажмите кнопку ниже"
    MESSAGE_CANCEL_LOCATION = "Геолоцирование отменино ❎"
    MESSAGE_CANCEL_SEARCH = "Поиск мест отменён ❎"
    
