import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .services import money, quantity


class OCRClientError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True)
class NormalizedOCRLine:
    raw_text: str
    name: str
    quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal
    confidence: Decimal


@dataclass(frozen=True)
class NormalizedOCRResult:
    provider: str
    provider_request_id: str
    merchant_name: str | None
    receipt_number: str | None
    purchased_at: datetime | None
    currency: str
    total: Decimal | None
    lines: list[NormalizedOCRLine]
    warnings: list[str]
    raw_payload: dict[str, Any]


def _decimal(value: Any, field: str, *, minimum: Decimal | None = None, maximum: Decimal | None = None) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OCRClientError("invalid_response", f"OCR response has an invalid {field}") from exc
    if minimum is not None and parsed < minimum:
        raise OCRClientError("invalid_response", f"OCR response has an invalid {field}")
    if maximum is not None and parsed > maximum:
        raise OCRClientError("invalid_response", f"OCR response has an invalid {field}")
    return parsed


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise OCRClientError("invalid_response", "OCR response has an invalid purchased_at value") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_normalized_response(payload: dict[str, Any]) -> NormalizedOCRResult:
    provider = str(payload.get("provider") or "").strip()
    request_id = str(payload.get("provider_request_id") or "").strip()
    if not provider or not request_id:
        raise OCRClientError("invalid_response", "OCR response is missing provider metadata")
    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list):
        raise OCRClientError("invalid_response", "OCR response lines must be a list")
    lines: list[NormalizedOCRLine] = []
    for row in raw_lines:
        if not isinstance(row, dict):
            raise OCRClientError("invalid_response", "OCR response contains an invalid line")
        name = str(row.get("name") or "").strip()
        raw_text = str(row.get("raw_text") or name).strip()
        if not name or not raw_text:
            raise OCRClientError("invalid_response", "OCR response contains a line without text")
        lines.append(
            NormalizedOCRLine(
                raw_text=raw_text[:500],
                name=name[:160],
                quantity=quantity(_decimal(row.get("quantity"), "quantity", minimum=Decimal("0.001"))),
                unit_cost=money(_decimal(row.get("unit_cost"), "unit_cost", minimum=Decimal("0"))),
                line_total=money(_decimal(row.get("line_total"), "line_total", minimum=Decimal("0"))),
                confidence=_decimal(row.get("confidence"), "confidence", minimum=Decimal("0"), maximum=Decimal("1")),
            )
        )
    raw_total = payload.get("total")
    total = money(_decimal(raw_total, "total", minimum=Decimal("0"))) if raw_total is not None else None
    return NormalizedOCRResult(
        provider=provider[:40],
        provider_request_id=request_id[:120],
        merchant_name=str(payload.get("merchant_name") or "").strip()[:160] or None,
        receipt_number=str(payload.get("receipt_number") or "").strip()[:80] or None,
        purchased_at=_parse_datetime(payload.get("purchased_at")),
        currency=(str(payload.get("currency") or "PHP").strip() or "PHP")[:8],
        total=total,
        lines=lines,
        warnings=[str(warning)[:240] for warning in (payload.get("warnings") or []) if str(warning).strip()][:30],
        raw_payload=payload,
    )


def local_mock_result() -> NormalizedOCRResult:
    payload = {
        "provider": "mock",
        "provider_request_id": "mock-local",
        "merchant_name": "Prime Goods Wholesale",
        "receipt_number": "MOCK-2026-001",
        "purchased_at": datetime.now(timezone.utc).isoformat(),
        "currency": "PHP",
        "total": "157.00",
        "lines": [
            {"raw_text": "LUCKY ME PANCIT CANTON 10 8.50 85.00", "name": "Lucky Me Pancit Canton", "quantity": "10.000", "unit_cost": "8.50", "line_total": "85.00", "confidence": 0.94},
            {"raw_text": "KOPIKO BROWN 6 12.00 72.00", "name": "Kopiko Brown", "quantity": "6.000", "unit_cost": "12.00", "line_total": "72.00", "confidence": 0.89},
        ],
        "warnings": ["Mock OCR result; review every line before confirmation."],
    }
    return parse_normalized_response(payload)


class OCRClient:
    def __init__(self) -> None:
        self.provider = os.getenv("OCR_PROVIDER", "mock").strip().lower()
        self.gateway_url = os.getenv("OCR_GATEWAY_URL", "http://localhost:8090").rstrip("/")
        self.service_token = os.getenv("OCR_SERVICE_TOKEN", "").strip()
        self.timeout = float(os.getenv("OCR_GATEWAY_TIMEOUT_SECONDS", "120"))

    @property
    def max_attempts(self) -> int:
        try:
            return max(1, min(int(os.getenv("OCR_MAX_ATTEMPTS", "3")), 10))
        except ValueError:
            return 3

    async def health(self) -> dict[str, str]:
        if self.provider in {"mock", "local"}:
            return {"status": "online", "provider": "mock", "message": "Mock OCR adapter ready; drafts still require review."}
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 5)) as client:
                response = await client.get(f"{self.gateway_url}/health/ready")
        except httpx.TimeoutException:
            return {"status": "offline", "provider": "gateway", "message": "OCR gateway health check timed out."}
        except httpx.HTTPError:
            return {"status": "offline", "provider": "gateway", "message": "OCR gateway is unreachable."}
        if response.is_success:
            payload = response.json()
            return {"status": "online", "provider": str(payload.get("provider") or "gateway"), "message": str(payload.get("message") or "OCR gateway ready")}
        return {"status": "offline", "provider": "gateway", "message": "OCR gateway is not ready."}

    async def recognize(self, data: bytes | None, filename: str, content_type: str) -> NormalizedOCRResult:
        if self.provider in {"mock", "local"}:
            return local_mock_result()
        if not data:
            raise OCRClientError("image_required", "A receipt image is required when the OCR gateway is enabled")
        if not self.service_token:
            raise OCRClientError("service_not_configured", "OCR service token is not configured")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.gateway_url}/v1/ocr/receipts",
                    headers={"X-OCR-Service-Token": self.service_token},
                    files={"file": (filename, data, content_type)},
                )
        except httpx.TimeoutException as exc:
            raise OCRClientError("provider_timeout", "OCR gateway request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise OCRClientError("provider_unavailable", "OCR gateway is unreachable", retryable=True) from exc

        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.is_success:
            if not isinstance(payload, dict):
                raise OCRClientError("invalid_response", "OCR gateway returned an invalid response")
            return parse_normalized_response(payload)
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            code = str(detail.get("code") or "provider_error")
            message = str(detail.get("message") or "OCR gateway rejected the receipt")
            retryable = bool(detail.get("retryable"))
        else:
            code, message, retryable = "provider_error", "OCR gateway rejected the receipt", False
        raise OCRClientError(code, message, retryable=retryable, http_status=response.status_code)
