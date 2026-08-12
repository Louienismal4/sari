import os
import re
<<<<<<< HEAD
from dataclasses import dataclass, field
=======
from dataclasses import dataclass
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx

# Assuming these helpers exist in your project
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
    raw_text: str = ""          # NEW: full raw OCR text


# ----- Helpers for parsing gateway responses -----

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
<<<<<<< HEAD
        raw_text=payload.get("raw_text", ""),   # NEW: capture full raw text if present
    )


# ---------- NEW: Local raw receipt parser ----------
=======
        raw_text=payload.get("raw_text", ""),
    )


# ----- RAW RECEIPT PARSER (handles multiple layouts) -----
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)

def parse_raw_receipt(text: str) -> NormalizedOCRResult:
    """
    Parse raw OCR text from Philippine receipts (Basti's, Besta, SPJM formats).
<<<<<<< HEAD
    Returns a NormalizedOCRResult with extracted lines.
    """
    lines = []
=======
    Handles both multi-line and single-line concatenated text.
    """
    # Normalize: keep original line breaks for line-based parsing,
    # but we also need to handle single-line concatenated text.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        # If empty, return empty result
        return NormalizedOCRResult(
            provider="local_parser",
            provider_request_id="local",
            merchant_name=None,
            receipt_number=None,
            purchased_at=None,
            currency="PHP",
            total=None,
            lines=[],
            warnings=["Empty OCR text"],
            raw_payload={},
            raw_text=text,
        )

>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
    merchant = None
    receipt_no = None
    purchased_at = None
    total = None

<<<<<<< HEAD
    # Try to extract header info using regex
    merchant_match = re.search(r'^(.*?)(?:Order|Receipt|OS#)', text, re.MULTILINE | re.IGNORECASE)
    if merchant_match:
        merchant = merchant_match.group(1).strip()

    # Look for receipt number patterns
=======
    # Extract header info from the full text
    merchant_match = re.search(r'^(.*?)(?:Order|Receipt|OS#|SPJM|Besta|BASTI)', text, re.MULTILINE | re.IGNORECASE)
    if merchant_match:
        merchant = merchant_match.group(1).strip()

>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
    receipt_no_match = re.search(r'(?:Order|OS|Receipt)\s*[#:]\s*([\w\-]+)', text, re.IGNORECASE)
    if receipt_no_match:
        receipt_no = receipt_no_match.group(1).strip()

<<<<<<< HEAD
    # Look for date/time
=======
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
    date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.IGNORECASE)
    if date_match:
        try:
            purchased_at = datetime.strptime(date_match.group(1), '%m/%d/%Y %I:%M %p')
        except ValueError:
            try:
                purchased_at = datetime.strptime(date_match.group(1), '%m/%d/%Y %H:%M')
            except ValueError:
                pass

<<<<<<< HEAD
    # Look for total
=======
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
    total_match = re.search(r'(?:TOTAL|Total)\s*[:]?\s*[₱]?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if total_match:
        total = money(Decimal(total_match.group(1).replace(',', '')))

<<<<<<< HEAD
    # Split text into lines and clean
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # We'll iterate and try to group item lines.

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        # Skip headers/footers
        if re.search(r'(?:Order|Receipt|Cashier|Date|Total|Change|Item|Amount|OS#|SPJM|Besta)', line, re.IGNORECASE):
            i += 1
            continue

        # Attempt to parse different patterns

=======
    parsed_lines: list[NormalizedOCRLine] = []

    # Check if the text is likely a single concatenated line (few lines, no quantity at line start)
    # If there are many lines, we'll use line-by-line parsing.
    # Heuristic: if the number of lines is ≤ 3 and none start with a digit + space, treat as single-line.
    if len(lines) <= 3 and not any(re.match(r'^\d+\s+', ln) for ln in lines):
        # Use regex to extract all items: QTY NAME PRICE (where price may end with N)
        pattern = re.compile(r'(\d+)\s+(.+?)\s+(\d+\.?\d*N?)')
        for match in pattern.finditer(text):
            qty_str, name, price_str = match.groups()
            qty = Decimal(qty_str)
            price = money(Decimal(re.sub(r'[,N]', '', price_str)))  # remove commas and 'N'
            line_total = qty * price
            parsed_lines.append(NormalizedOCRLine(
                raw_text=match.group(0),
                name=name.strip(),
                quantity=qty,
                unit_cost=price,
                line_total=line_total,
                confidence=Decimal('0.85')
            ))
        # If we found items, use them; otherwise fall back to line-by-line
        if parsed_lines:
            if total is None:
                total = sum((l.line_total for l in parsed_lines), Decimal('0'))
            return NormalizedOCRResult(
                provider="local_parser",
                provider_request_id="local",
                merchant_name=merchant,
                receipt_number=receipt_no,
                purchased_at=purchased_at,
                currency="PHP",
                total=total,
                lines=parsed_lines,
                warnings=["Raw OCR parsing – review each line"],
                raw_payload={},
                raw_text=text,
            )

    # ---- Line-by-line parsing ----
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip common header/footer lines
        if re.search(r'(?:Order|Receipt|Cashier|Date|Total|Change|Item|Amount|OS#|SPJM|Besta|SPJM GEN\.|messenger|CASH|CHANGE|Item\(s\))', line, re.IGNORECASE):
            i += 1
            continue

>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
        # Pattern 1: Besta style: "101 Milky Milk 50    ₱780.00  2 x ₱390.00"
        besta_match = re.match(r'^(\d+)\s+(.+?)\s+[₱]?([\d,]+\.?\d*)\s+(\d+)\s*x\s*[₱]?([\d,]+\.?\d*)$', line, re.IGNORECASE)
        if besta_match:
            code, name, total_str, qty_str, unit_str = besta_match.groups()
            qty = Decimal(qty_str)
            unit = money(Decimal(unit_str.replace(',', '')))
            line_total = money(Decimal(total_str.replace(',', '')))
<<<<<<< HEAD
            lines.append(NormalizedOCRLine(
=======
            parsed_lines.append(NormalizedOCRLine(
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
                raw_text=line,
                name=name.strip(),
                quantity=qty,
                unit_cost=unit,
                line_total=line_total,
                confidence=Decimal('0.9')
            ))
            i += 1
            continue

<<<<<<< HEAD
        # Pattern 2: SPJM style: "1 TATTOOS SC 86X10    85.00N"
=======
        # Pattern 2: SPJM style (single line per item): "1 TATTOOS SC 86X10    85.00N"
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
        spjm_match = re.match(r'^(\d+)\s+(.+?)\s+([\d,]+\.?\d*)(?:N)?$', line, re.IGNORECASE)
        if spjm_match:
            qty_str, name, price_str = spjm_match.groups()
            qty = Decimal(qty_str)
            unit = money(Decimal(price_str.replace(',', '')))
            line_total = qty * unit
<<<<<<< HEAD
            lines.append(NormalizedOCRLine(
=======
            parsed_lines.append(NormalizedOCRLine(
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
                raw_text=line,
                name=name.strip(),
                quantity=qty,
                unit_cost=unit,
                line_total=line_total,
                confidence=Decimal('0.85')
            ))
            i += 1
            continue

        # Pattern 3: Basti's style (multi-line grouping)
<<<<<<< HEAD
        # First try to see if current line ends with a price, and the next line has quantity info
        # e.g., "DM Four Season 124.00" then next "4 @ 33.00"
        price_match = re.search(r'([\d,]+\.?\d*)$', line)
        if price_match and i + 1 < len(raw_lines):
            next_line = raw_lines[i+1]
=======
        # e.g., "DM Four Season   124.00" then next line "4 @ 33.00"
        price_match = re.search(r'([\d,]+\.?\d*)$', line)
        if price_match and i + 1 < len(lines):
            next_line = lines[i+1]
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
            qty_info = re.search(r'(\d+)\s*[@x]\s*([\d,]+\.?\d*)', next_line, re.IGNORECASE)
            if qty_info:
                qty = Decimal(qty_info.group(1))
                unit = money(Decimal(qty_info.group(2).replace(',', '')))
                total_price = money(Decimal(price_match.group(1).replace(',', '')))
                name = line[:price_match.start()].strip()
<<<<<<< HEAD
                # Combine raw text
                combined_raw = line + " " + next_line
                lines.append(NormalizedOCRLine(
=======
                combined_raw = line + " " + next_line
                parsed_lines.append(NormalizedOCRLine(
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
                    raw_text=combined_raw,
                    name=name,
                    quantity=qty,
                    unit_cost=unit,
                    line_total=total_price,
                    confidence=Decimal('0.88')
                ))
                i += 2
                continue

<<<<<<< HEAD
        # If no pattern, treat as a single item with just total? Or skip.
        # We'll try to extract a price at end and assume quantity=1
=======
        # Fallback: treat as single item with price at end, quantity=1
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
        fallback_price = re.search(r'([\d,]+\.?\d*)$', line)
        if fallback_price:
            total_price = money(Decimal(fallback_price.group(1).replace(',', '')))
            name = line[:fallback_price.start()].strip()
<<<<<<< HEAD
            lines.append(NormalizedOCRLine(
=======
            parsed_lines.append(NormalizedOCRLine(
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
                raw_text=line,
                name=name,
                quantity=Decimal('1'),
                unit_cost=total_price,
                line_total=total_price,
<<<<<<< HEAD
                confidence=Decimal('0.6')  # low confidence
=======
                confidence=Decimal('0.6')
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
            ))
        i += 1

    # If total not found, sum line totals
<<<<<<< HEAD
    if total is None and lines:
        total = sum((l.line_total for l in lines), Decimal('0'))
=======
    if total is None and parsed_lines:
        total = sum((l.line_total for l in parsed_lines), Decimal('0'))
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)

    return NormalizedOCRResult(
        provider="local_parser",
        provider_request_id="local",
        merchant_name=merchant,
        receipt_number=receipt_no,
        purchased_at=purchased_at,
        currency="PHP",
        total=total,
<<<<<<< HEAD
        lines=lines,
=======
        lines=parsed_lines,
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
        warnings=["Raw OCR parsing – review each line"],
        raw_payload={},
        raw_text=text,
    )


def local_mock_result(raw_text: Optional[str] = None) -> NormalizedOCRResult:
<<<<<<< HEAD
=======
    """Mock OCR result – if raw_text is given, parse it; otherwise return a sample."""
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
    if raw_text:
        return parse_raw_receipt(raw_text)
    # Fallback mock with a simple receipt
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
<<<<<<< HEAD
        "raw_text": "",  # not used
=======
        "raw_text": "",
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
    }
    return parse_normalized_response(payload)


# ----- OCR CLIENT -----

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
<<<<<<< HEAD
        # If provider is local, we need raw text – but we don't have it (only image bytes).
        # So we treat "local" as using a mock with a hardcoded sample, or we could
        # perform OCR locally (not implemented). For now, we'll rely on mock or gateway.
        if self.provider == "local":
            # You can pass raw text via environment or a file; here we'll just use a fixed sample.
            # In practice, you'd want to use a local OCR engine (e.g., Tesseract) to get raw text.
            # For demo, we use a sample from one of the receipts.
            sample = """
BASTI'S VARIETY STORE
DM Four Season 124.00
4 @ 33.00
Alaska Evaporada 360ml 108.00
3 @ 36.00
Total 232.00
"""
            return parse_raw_receipt(sample)

        # Normal gateway flow
        if self.provider in {"mock", "mock-gateway"}:
            return local_mock_result()  # optionally pass raw_text if available

=======
        # Local provider: we cannot OCR images locally, but we can parse raw text if passed.
        # For simplicity, we'll treat "local" as using a hardcoded sample (or you can use a local OCR engine).
        if self.provider == "local":
            # In a real implementation, you might call Tesseract here to get raw text from data.
            # For demo, we'll use a sample from the SPJM receipt to show multi-item parsing.
            sample = """
SPJM GEN. MODE.
1291 Bryg. Milagrosa
Carmona, Cavite
OS#: 0000172372    #: 2
Date: 08/11/2026 04:05:13 PM
1 TATTOOS SC 86X10    85.00N
1 XSALTO SPICY 56X1    85.00N
1 TATTOOS PIZZA 58X5    85.00N
1 ASSORTED BIG SNACK  65.00N
2 DOWEE RED    206.00N
TOTAL    3,213.80
"""
            return parse_raw_receipt(sample)

        # Mock provider (without gateway)
        if self.provider == "mock":
            return local_mock_result()  # could also accept raw_text from data? but we don't have it.

        # Gateway provider
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
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
<<<<<<< HEAD
            # If the gateway returns a raw_text field, we can parse it locally as a fallback
=======
            # If the gateway provides raw_text, use local parser as a fallback or enhancement
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
            if payload.get("raw_text"):
                try:
                    return parse_raw_receipt(payload["raw_text"])
                except Exception:
<<<<<<< HEAD
                    # Fall back to normalized parsing if available
=======
                    # fall through to normalized parsing
>>>>>>> 6184ea5 (feat: Enhance raw receipt parsing for Philippine formats and add support for raw text in OCRClient)
                    pass
            return parse_normalized_response(payload)
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            code = str(detail.get("code") or "provider_error")
            message = str(detail.get("message") or "OCR gateway rejected the receipt")
            retryable = bool(detail.get("retryable"))
        else:
            code, message, retryable = "provider_error", "OCR gateway rejected the receipt", False
        raise OCRClientError(code, message, retryable=retryable, http_status=response.status_code)