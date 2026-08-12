import hmac
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status

from .contracts import OCRReceiptResult
from .errors import GatewayError
from .image_validation import validate_and_normalize
from .pdf_receipts import extract_pdf_receipt, parse_consolidated_receipt_pdf
from .providers import build_provider


@asynccontextmanager
async def lifespan(_: FastAPI):
    provider = build_provider()
    await provider.warmup()
    yield


app = FastAPI(
    title="Sari-Sari OCR Gateway",
    version="0.1.0",
    description="Private, credential-isolating receipt OCR gateway.",
    lifespan=lifespan,
)


def _service_token_is_valid(authorization: str | None, service_token: str | None) -> bool:
    expected = os.getenv("OCR_SERVICE_TOKEN", "").strip()
    if not expected:
        return False
    supplied = (service_token or "").strip()
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def require_service_token(authorization: str | None = Header(default=None), x_ocr_service_token: str | None = Header(default=None)) -> None:
    if not _service_token_is_valid(authorization, x_ocr_service_token):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Valid OCR service credentials are required"})


def _error_response(error: GatewayError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message, "retryable": error.retryable})


@app.get("/health/live")
def live_health() -> dict:
    return {"status": "ok", "service": "ocr-gateway"}


@app.get("/health/ready")
def ready_health() -> dict:
    try:
        provider = build_provider()
    except GatewayError as error:
        raise _error_response(error) from error
    ready, message = provider.readiness()
    if not ready:
        raise HTTPException(status_code=503, detail={"code": "provider_not_ready", "message": message})
    return {"status": "ready", "provider": provider.name, "message": message}


@app.post("/v1/ocr/receipts", response_model=OCRReceiptResult, dependencies=[Depends(require_service_token)])
async def recognize_receipt(file: UploadFile = File(...)) -> dict:
    try:
        data = await file.read(10 * 1024 * 1024 + 1)
        content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
        if content_type == "application/pdf":
            document = extract_pdf_receipt(data)
            return parse_consolidated_receipt_pdf(document, file.filename or "receipt-report.pdf").to_wire()
        image = validate_and_normalize(data, file.content_type)
        provider = build_provider()
        result = await provider.recognize(image.data, image.content_type, file.filename or "receipt.jpg")
        return result.to_wire()
    except GatewayError as error:
        raise _error_response(error) from error
