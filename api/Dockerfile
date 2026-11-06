FROM python:3.13-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /opt/shared
RUN pip install --no-cache-dir --no-deps /opt/shared
COPY api .
RUN useradd --uid 10002 --create-home app
USER app
CMD ["uvicorn", "urbex.bootstrap.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
