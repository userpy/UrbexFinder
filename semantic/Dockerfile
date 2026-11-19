FROM python:3.11-slim
WORKDIR /app
ENV HF_HOME=/models/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=4
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir hf_xet==1.8.0
ENV HF_HUB_DOWNLOAD_TIMEOUT=120 \
    HF_HUB_ETAG_TIMEOUT=30
COPY app.py .
RUN useradd --uid 10003 --create-home app \
    && mkdir -p /models \
    && chown -R app:app /app /models
USER app
EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
