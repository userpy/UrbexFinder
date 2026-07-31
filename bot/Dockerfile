FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    POETRY_REQUESTS_TIMEOUT=120 \
    POETRY_REQUESTS_MAX_RETRIES=5

WORKDIR /app

ARG POETRY_VERSION=2.4.1
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* ./

FROM base AS test

RUN poetry install --no-root --with dev

COPY . .

CMD ["pytest"]

FROM base AS production

RUN poetry install --no-root --only main

COPY . .

CMD ["python", "main.py"]
