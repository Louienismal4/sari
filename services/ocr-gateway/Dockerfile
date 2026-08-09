# Pin this to a patch-level base image in CI, then promote the resolved digest
# to the deployment environment. The service must never build from `latest`.
FROM python:3.13.14-slim-bookworm

LABEL org.opencontainers.image.title="Sari-Sari OCR Gateway" \
      org.opencontainers.image.description="Private receipt OCR gateway" \
      org.opencontainers.image.source="sari"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

ENV PADDLE_OCR_BASE_DIR=/tmp/.paddlex

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 ocrgateway \
    && useradd --system --uid 10001 --gid 10001 --no-create-home ocrgateway

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY app ./app
RUN mkdir -p /tmp/.paddlex \
    && chown -R 10001:10001 /app /tmp/.paddlex

USER 10001:10001
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=3s --start-period=300s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health/ready', timeout=2)"

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
