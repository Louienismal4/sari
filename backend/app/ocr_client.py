import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

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
    raw_text: str = ""


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
        raw_text=payload.get("raw_text", ""),
    )


# ----- RAW RECEIPT PARSER (handles multiple layouts & concatenated text) -----

def _parse_single_line_spjm(text: str) -> list[NormalizedOCRLine]:
    """
    Parse a single concatenated SPJM‑style string.
    Patterns:
      1) QTY NAME TOTAL_PRICE (e.g. "1 TATTOOS SC 86X10 85.00N")
      2) QTY NAME @ UNIT_PRICE TOTAL_PRICE (e.g. "6 CHEESERING20G @8.50 51.00N")
    """
    # Normalize spaces and remove extra newlines
    text = re.sub(r'\s+', ' ', text).strip()

    # First try pattern with @ (unit price)
    pattern_with_at = re.compile(r'(\d+)\s+(.+?)\s+@\s*([\d,]+\.?\d*)\s+([\d,]+\.?\d*N?)', re.IGNORECASE)
    matches = list(pattern_with_at.finditer(text))
    if matches:
        items = []
        for match in matches:
            qty = Decimal(match.group(1))
            name = match.group(2).strip()
            unit_price = money(Decimal(re.sub(r'[,N]', '', match.group(3))))
            total_price = money(Decimal(re.sub(r'[,N]', '', match.group(4))))
            # If total doesn't match qty*unit, trust the total and recompute unit
            if abs(total_price - qty * unit_price) > Decimal('0.01') and qty > 0:
                unit_price = (total_price / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            items.append(NormalizedOCRLine(
                raw_text=match.group(0),
                name=name,
                quantity=qty,
                unit_cost=unit_price,
                line_total=total_price,
                confidence=Decimal('0.90')
            ))
        return items

    # Otherwise try the simpler pattern: QTY NAME TOTAL
    pattern_simple = re.compile(r'(\d+)\s+(.+?)\s+([\d,]+\.?\d*N?)')
    items = []
    for match in pattern_simple.finditer(text):
        qty = Decimal(match.group(1))
        name = match.group(2).strip()
        total_price = money(Decimal(re.sub(r'[,N]', '', match.group(3))))
        # Compute unit cost from total/qty
        unit_price = (total_price / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if qty > 0 else Decimal('0')
        items.append(NormalizedOCRLine(
            raw_text=match.group(0),
            name=name,
            quantity=qty,
            unit_cost=unit_price,
            line_total=total_price,
            confidence=Decimal('0.85')
        ))
    return items


def parse_raw_receipt(text: str) -> NormalizedOCRResult:
    """
    Parse raw OCR text from Philippine receipts.
    Handles:
      - Basti's (multi‑line grouping)
      - Besta (one‑line with code, total, qty×unit)
      - SPJM (one‑line per item, sometimes concatenated)
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
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

    merchant = None
    receipt_no = None
    purchased_at = None
    total = None

    # Extract header info
    merchant_match = re.search(r'^(.*?)(?:Order|Receipt|OS#|SPJM|Besta|BASTI)', text, re.MULTILINE | re.IGNORECASE)
    if merchant_match:
        merchant = merchant_match.group(1).strip()

    receipt_no_match = re.search(r'(?:Order|OS|Receipt)\s*[#:]\s*([\w\-]+)', text, re.IGNORECASE)
    if receipt_no_match:
        receipt_no = receipt_no_match.group(1).strip()

    date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.IGNORECASE)
    if date_match:
        try:
            purchased_at = datetime.strptime(date_match.group(1), '%m/%d/%Y %I:%M %p')
        except ValueError:
            try:
                purchased_at = datetime.strptime(date_match.group(1), '%m/%d/%Y %H:%M')
            except ValueError:
                pass

    total_match = re.search(r'(?:TOTAL|Total)\s*[:]?\s*[₱]?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if total_match:
        total = money(Decimal(total_match.group(1).replace(',', '')))

    parsed_lines: list[NormalizedOCRLine] = []

    # ----- SINGLE‑LINE CONCATENATED (SPJM) DETECTION -----
    # If the whole text has very few lines and many price tokens, use the single‑line parser.
    price_count = len(re.findall(r'\d+\.?\d*N?', text))
    if len(lines) <= 3 and price_count > 1:
        spjm_items = _parse_single_line_spjm(text)
        if spjm_items:
            parsed_lines = spjm_items
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
                warnings=["Raw OCR parsed from concatenated text – review each line"],
                raw_payload={},
                raw_text=text,
            )

    # ----- LINE‑BY‑LINE PARSING -----
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip headers/footers
        if re.search(r'(?:Order|Receipt|Cashier|Date|Total|Change|Item|Amount|OS#|SPJM|Besta|SPJM GEN\.|messenger|CASH|CHANGE|Item\(s\))', line, re.IGNORECASE):
            i += 1
            continue

        # 1) Besta style: "101 Milky Milk 50    ₱780.00  2 x ₱390.00"
        besta_match = re.match(r'^(\d+)\s+(.+?)\s+[₱]?([\d,]+\.?\d*)\s+(\d+)\s*x\s*[₱]?([\d,]+\.?\d*)$', line, re.IGNORECASE)
        if besta_match:
            code, name, total_str, qty_str, unit_str = besta_match.groups()
            qty = Decimal(qty_str)
            unit = money(Decimal(unit_str.replace(',', '')))
            line_total = money(Decimal(total_str.replace(',', '')))
            parsed_lines.append(NormalizedOCRLine(
                raw_text=line,
                name=name.strip(),
                quantity=qty,
                unit_cost=unit,
                line_total=line_total,
                confidence=Decimal('0.9')
            ))
            i += 1
            continue

        # 2) SPJM style with @ (unit price)
        spjm_at = re.match(r'^(\d+)\s+(.+?)\s+@\s*([\d,]+\.?\d*)\s+([\d,]+\.?\d*N?)$', line, re.IGNORECASE)
        if spjm_at:
            qty_str, name, unit_str, total_str = spjm_at.groups()
            qty = Decimal(qty_str)
            unit = money(Decimal(unit_str.replace(',', '')))
            line_total = money(Decimal(re.sub(r'[,N]', '', total_str)))
            if abs(line_total - qty * unit) > Decimal('0.01') and qty > 0:
                unit = (line_total / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            parsed_lines.append(NormalizedOCRLine(
                raw_text=line,
                name=name.strip(),
                quantity=qty,
                unit_cost=unit,
                line_total=line_total,
                confidence=Decimal('0.9')
            ))
            i += 1
            continue

        # 3) SPJM style (simple): QTY NAME TOTAL
        spjm_match = re.match(r'^(\d+)\s+(.+?)\s+([\d,]+\.?\d*)(?:N)?$', line, re.IGNORECASE)
        if spjm_match:
            qty_str, name, price_str = spjm_match.groups()
            qty = Decimal(qty_str)
            total_price = money(Decimal(price_str.replace(',', '')))
            unit_price = (total_price / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if qty > 0 else Decimal('0')
            parsed_lines.append(NormalizedOCRLine(
                raw_text=line,
                name=name.strip(),
                quantity=qty,
                unit_cost=unit_price,
                line_total=total_price,
                confidence=Decimal('0.85')
            ))
            i += 1
            continue

        # 4) Basti's style (multi‑line grouping)
        price_match = re.search(r'([\d,]+\.?\d*)$', line)
        if price_match and i + 1 < len(lines):
            next_line = lines[i+1]
            qty_info = re.search(r'(\d+)\s*[@x]\s*([\d,]+\.?\d*)', next_line, re.IGNORECASE)
            if qty_info:
                qty = Decimal(qty_info.group(1))
                unit = money(Decimal(qty_info.group(2).replace(',', '')))
                total_price = money(Decimal(price_match.group(1).replace(',', '')))
                name = line[:price_match.start()].strip()
                combined_raw = line + " " + next_line
                parsed_lines.append(NormalizedOCRLine(
                    raw_text=combined_raw,
                    name=name,
                    quantity=qty,
                    unit_cost=unit,
                    line_total=total_price,
                    confidence=Decimal('0.88')
                ))
                i += 2
                continue

        # Fallback: single item with price at end, quantity=1
        fallback_price = re.search(r'([\d,]+\.?\d*)$', line)
        if fallback_price:
            total_price = money(Decimal(fallback_price.group(1).replace(',', '')))
            name = line[:fallback_price.start()].strip()
            parsed_lines.append(NormalizedOCRLine(
                raw_text=line,
                name=name,
                quantity=Decimal('1'),
                unit_cost=total_price,
                line_total=total_price,
                confidence=Decimal('0.6')
            ))
        i += 1

    if total is None and parsed_lines:
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


def local_mock_result(raw_text: Optional[str] = None) -> NormalizedOCRResult:
    if raw_text:
        return parse_raw_receipt(raw_text)
    # Fallback mock
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
        "raw_text": "",
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
        # Local provider – here you could call Tesseract to extract text from image.
        # For demo, we return a parsed sample.
        if self.provider == "local":
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

        if self.provider == "mock":
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
            # If the gateway provides raw_text, use local parser as a fallback
            if payload.get("raw_text"):
                try:
                    return parse_raw_receipt(payload["raw_text"])
                except Exception:
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