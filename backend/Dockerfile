# Pin the patch-level tag in deployment and promote a verified digest through CI.
FROM python:3.13.14-slim-bookworm

LABEL org.opencontainers.image.title="Sari-Sari Backend" \
      org.opencontainers.image.description="Inventory API and OCR orchestration service" \
      org.opencontainers.image.source="sari"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

RUN groupadd --system --gid 10001 sari \
    && useradd --system --uid 10001 --gid 10001 --no-create-home sari

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
RUN mkdir -p storage/receipts \
    && chown -R 10001:10001 /app/backend

ENV PYTHONPATH=/app/backend
EXPOSE 8000

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
