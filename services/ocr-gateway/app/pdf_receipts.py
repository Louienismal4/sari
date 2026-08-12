from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
import re
from uuid import uuid4

from .contracts import OCRReceiptLine, OCRReceiptResult
from .errors import GatewayError


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20


@dataclass(frozen=True)
class ExtractedPDF:
    text: str
    page_count: int


def extract_pdf_receipt(data: bytes) -> ExtractedPDF:
    """Safely extract selectable text from a small, local receipt report PDF."""
    if not data:
        raise GatewayError("empty_pdf", "Receipt PDF is empty", 422)
    if len(data) > MAX_PDF_BYTES:
        raise GatewayError("payload_too_large", "Receipt PDF must be 10 MB or smaller", 413)
    if not data.startswith(b"%PDF-"):
        raise GatewayError("invalid_pdf", "Receipt file is not a valid PDF", 422)

    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise GatewayError("encrypted_pdf", "Receipt PDF must not be password protected", 422)
        if not reader.pages:
            raise GatewayError("empty_pdf", "Receipt PDF has no pages", 422)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise GatewayError("pdf_too_large", f"Receipt PDF must contain {MAX_PDF_PAGES} pages or fewer", 422)
        pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    except GatewayError:
        raise
    except Exception as exc:
        raise GatewayError("invalid_pdf", "Receipt PDF could not be read", 422) from exc

    text = "\n\f\n".join(page.strip() for page in pages if page.strip())
    if not text:
        raise GatewayError(
            "pdf_text_unavailable",
            "Receipt PDF does not contain selectable text. Export the consolidated line-item report as a text PDF.",
            422,
        )
    return ExtractedPDF(text=text, page_count=len(pages))


_LINE_ITEM_RE = re.compile(
    r"^\s*\d+\s+(?P<name>.+?)\s+(?P<quantity>\d+(?:\.\d+)?)\s+"
    r"(?:PHP|[P₱])?\s*(?P<unit_cost>\d[\d,]*(?:\.\d{1,2})?)\s+"
    r"(?:PHP|[P₱])?\s*(?P<line_total>\d[\d,]*(?:\.\d{1,2})?)\s*$",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\bdate\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)", re.IGNORECASE)


def parse_consolidated_receipt_pdf(document: ExtractedPDF, filename: str) -> OCRReceiptResult:
    """Convert a consolidated line-item report into reviewable inventory lines."""
    source_lines = [re.sub(r"\s+", " ", line).strip() for line in document.text.splitlines()]
    lines: list[OCRReceiptLine] = []
    unparsed_rows: list[str] = []
    merchant_name = "Consolidated receipt report"
    purchased_at = None

    for row in source_lines:
        if not row:
            continue
        if purchased_at is None:
            date_match = _DATE_RE.search(row)
            if date_match:
                purchased_at = _parse_date(date_match.group(1))
        match = _LINE_ITEM_RE.fullmatch(row)
        if match is None:
            if _looks_like_line_item(row):
                unparsed_rows.append(row[:500])
            continue
        try:
            quantity = _decimal(match.group("quantity"), Decimal("0.001"))
            unit_cost = _decimal(match.group("unit_cost"), Decimal("0.01"))
            line_total = _decimal(match.group("line_total"), Decimal("0.01"))
        except InvalidOperation:
            unparsed_rows.append(row[:500])
            continue
        if quantity <= 0 or unit_cost < 0 or line_total < 0:
            unparsed_rows.append(row[:500])
            continue
        lines.append(
            OCRReceiptLine(
                raw_text=row[:500],
                name=match.group("name").strip()[:160],
                quantity=quantity,
                unit_cost=unit_cost,
                line_total=line_total,
                confidence=Decimal("1.0000"),
            )
        )

    if not lines:
        raise GatewayError(
            "pdf_lines_unavailable",
            "No line items could be read from this PDF. Upload a consolidated line-item report with item, quantity, unit price, and total columns.",
            422,
        )

    total = sum((line.line_total for line in lines), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    reported_total = _reported_combined_total(source_lines)
    warnings = [
        "Line items were imported from selectable PDF text. Review every line before confirmation.",
        "This consolidated report may contain multiple receipts; set the purchase date and verify all lines before posting stock.",
        f"Source: {filename}",
    ]
    if reported_total is not None and reported_total != total:
        warnings.insert(
            0,
            f"The report's combined total (PHP {reported_total:.2f}) differs from its imported line items (PHP {total:.2f}). Stock will post the reviewed line items.",
        )
    if unparsed_rows:
        warnings.append(f"{len(unparsed_rows)} possible line-item rows were not imported; review the source report.")
    return OCRReceiptResult(
        provider="pdf_text",
        provider_request_id=f"pdf-{uuid4().hex[:12]}",
        merchant_name=merchant_name,
        receipt_number=f"CONSOLIDATED-{document.page_count}-PAGE",
        purchased_at=purchased_at,
        currency="PHP",
        total=total,
        lines=lines,
        warnings=warnings,
        raw_result={
            "source_type": "pdf_text",
            "page_count": document.page_count,
            "imported_line_count": len(lines),
            "reported_combined_total": f"{reported_total:.2f}" if reported_total is not None else None,
            "unparsed_line_item_rows": unparsed_rows[:30],
        },
    )


def _decimal(value: str, scale: Decimal) -> Decimal:
    return Decimal(value.replace(",", "")).quantize(scale, rounding=ROUND_HALF_UP)


def _parse_date(value: str) -> datetime | None:
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _looks_like_line_item(row: str) -> bool:
    return bool(re.match(r"^\s*\d+\s+.+\s+\d+(?:\.\d+)?\s+(?:PHP|[P₱])?\s*\d", row, re.IGNORECASE))


def _reported_combined_total(rows: list[str]) -> Decimal | None:
    seen_total_heading = False
    for row in rows:
        if "COMBINED GRAND TOTAL" in row.upper():
            seen_total_heading = True
            continue
        if not seen_total_heading:
            continue
        values = re.findall(r"(?:PHP|[P₱])\s*(\d[\d,]*(?:\.\d{1,2})?)", row, re.IGNORECASE)
        if values:
            try:
                return _decimal(values[-1], Decimal("0.01"))
            except InvalidOperation:
                return None
        if row:
            seen_total_heading = False
    return None
