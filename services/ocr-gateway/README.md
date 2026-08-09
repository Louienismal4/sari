# Sari-Sari OCR gateway

This is the private service between the inventory API and the local OCR runtime. The React app never receives the gateway token or OCR model runtime. The gateway returns the application-owned normalized receipt contract.

## Local mock mode

From the repository root:

```bash
export OCR_GATEWAY_PROVIDER=mock
export OCR_SERVICE_TOKEN=replace-with-a-long-random-token
PYTHONPATH=services/ocr-gateway uvicorn app.main:app --app-dir services/ocr-gateway --host 127.0.0.1 --port 8090
```

The application API should use `OCR_PROVIDER=gateway` and point `OCR_GATEWAY_URL` at this service when testing the application-to-gateway contract. The gateway itself remains in `OCR_GATEWAY_PROVIDER=mock` mode.

Check readiness and submit a receipt:

```bash
curl http://127.0.0.1:8090/health/ready
curl -H "X-OCR-Service-Token: $OCR_SERVICE_TOKEN" \
  -F "file=@receipt.jpg;type=image/jpeg" \
  http://127.0.0.1:8090/v1/ocr/receipts
```

## Local PaddleOCR mode

Set `OCR_GATEWAY_PROVIDER=paddleocr` to use the local CPU adapter. The default profile is intentionally conservative for a hardware-limited host:

- `PADDLEOCR_VERSION=PP-OCRv4`
- `PADDLEOCR_DEVICE=cpu`
- `PADDLEOCR_DET_MODEL_NAME=PP-OCRv4_mobile_det`
- `PADDLEOCR_REC_MODEL_NAME=en_PP-OCRv4_mobile_rec`
- `PADDLEOCR_ENABLE_MKLDNN=false`
- `PADDLEOCR_CPU_THREADS=2`

Install the gateway dependencies in a clean virtual environment, then start it with the same `uvicorn` command above. The gateway loads the models and runs a small inference before `/health/ready` succeeds, so the first user receipt does not absorb the cold-start cost. The Compose profile persists downloaded weights in the `ocr-models` volume across container restarts. Set `PADDLEOCR_WARMUP_TIMEOUT_SECONDS` higher than `300` only on especially slow hosts.

PaddleOCR produces text detections rather than a guaranteed receipt table. The adapter groups detections into rows and only creates a draft line when it can infer name, quantity, unit cost, and line total. Ambiguous text stays in `raw_result` and the review screen remains the source of truth.

## Docker deployment

1. Install Docker Desktop with Linux containers.
2. Copy the repository and create an uncommitted runtime `.env` file.
3. Set `OCR_GATEWAY_PLATFORM=linux/amd64`. This runs natively on the usual x64 Windows Docker host; Docker Desktop uses amd64 emulation when building from an Apple Silicon Mac.
4. Set a rotated random `OCR_SERVICE_TOKEN` and `OCR_GATEWAY_PROVIDER=paddleocr`.
5. Keep the CPU/mobile model defaults unless a representative receipt test justifies changing them. If model weights are preloaded, mount them into the container and set the two model directory variables to the mounted read-only paths.
6. Start the backend and gateway:

```bash
docker compose up -d --build --wait
docker compose ps
```

Compose exposes the gateway only to the backend over its private Docker network. Never publish or route the OCR port to the internet.

The container runs as a non-root user, has a read-only root filesystem, drops Linux capabilities, limits CPU/memory/processes, and exposes only the authenticated OCR endpoint. Model weights are not bundled into the repository or returned to callers.
