FROM python:3.13-slim
WORKDIR /app
ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
ARG POETRY_VERSION=2.4.1
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY api/pyproject.toml api/poetry.lock ./
COPY shared /shared
RUN poetry install --no-root --with dev
COPY api .
RUN useradd --uid 10002 --create-home app
USER app
CMD ["uvicorn", "urbex.bootstrap.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
