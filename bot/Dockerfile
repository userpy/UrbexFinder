FROM python:3.11-slim

# Не буферизовать вывод
ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Установка Poetry
RUN pip install --no-cache-dir poetry

# Копируем файлы зависимостей
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости
RUN poetry install --no-root

# Копируем код бота
COPY . .

# Информация

# Запуск бота
CMD ["python", "main.py"]
