from enum import Enum

class Resources(Enum):
    COMMAND = "📚 Список ресурсов"
    COMMAND_ADD = "📚➕ Добавить ресурс"
    COMMAND_DELETE = "🗑️ Удалить ресурс"
    CANCEL_RESOURCES_MODE = "↩️ Отменить режим добавления ресурсов"
    MESSAGE_ADD_RESOURCES_START = "✍️ Введите название ресурса:"
    MESSAGE_DELETE_RESOURCE = "✅ Ресурс удалён."
    MESSAGE_RESOURCE_NAME = "📌 Выберите тип ресурса:"
    MESSAGE_ADD_RESOURCES_URL = "📝 Введите описание (или напишите '-' если не нужно):"
    MESSAGE_CANCEL_RESOURCE = "✅ Режим добавления ресурсов отменён"
    